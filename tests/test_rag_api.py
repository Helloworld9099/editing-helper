"""End-to-end RAG request/response checks using a mocked Gemini API."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import create_app
from knowledge_rag import build_index


class RAGBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "docs.sqlite3"
        build_index(database=self.db)
        self.env = {
            "COACH_PROVIDER": "gemini",
            "GEMINI_API_KEY": "test-gemini-key",
            "COACH_ACCESS_TOKEN": "test-coach-token",
            "COACH_RAG_ENABLED": "1",
            "COACH_KNOWLEDGE_DB": str(self.db),
        }
        self.headers = {"Authorization": "Bearer test-coach-token"}

    def client(self, handler, overrides=None):
        with patch.dict("os.environ", {**self.env, **(overrides or {})}, clear=True):
            instance = create_app(transport=httpx.MockTransport(handler))
        return TestClient(instance, base_url="http://127.0.0.1:8000")

    def test_rag_sources_and_gemini_system_instruction(self):
        def fake(request):
            self.assertEqual(request.headers["x-goog-api-key"], "test-gemini-key")
            content = json.loads(request.content)
            self.assertIn("systemInstruction", content)
            guidance = content["systemInstruction"]["parts"][0]["text"]
            self.assertIn("Minecraft", guidance)
            question = content["contents"][0]["parts"][0]["text"]
            self.assertIn("Editor: Kdenlive", question)
            self.assertIn("Version: 26.08", question)
            self.assertIn("RETRIEVED REFERENCE DATA", question)
            self.assertIn("Nosync0r", question)
            self.assertNotIn("DaVinci Resolve", question)
            return httpx.Response(200, json={"candidates": [{"content": {
                "parts": [{"text": "Try Nosync0r, then preview the result [1]."}]
            }}]})

        with self.client(fake) as client:
            response = client.post("/v1/coach", headers=self.headers, json={
                "editor": "Kdenlive", "version": "26.08", "question": "Broken TV glitch effect?",
            })
            self.assertEqual(response.status_code, 200)
            answer = response.json()
            self.assertIn("Nosync0r", answer["answer"])
            self.assertGreater(len(answer["sources"]), 0)
            self.assertEqual(answer["sources"][0]["id"], "kdenlive-broken-tv")
            self.assertEqual(answer["sources"][0]["source_kind"], "official")
            self.assertTrue(all(s["editor"] == "Kdenlive" for s in answer["sources"]))
            self.assertTrue(all(s["url"].startswith("https://") for s in answer["sources"]))

    def test_version_mismatch_does_not_attach_unrelated_sources(self):
        def fake(request):
            question = json.loads(request.content)["contents"][0]["parts"][0]["text"]
            self.assertNotIn("RETRIEVED REFERENCE DATA", question)
            return httpx.Response(200, json={"candidates": [{"content": {
                "parts": [{"text": "I do not have a version-specific reference."}]
            }}]})

        with self.client(fake) as client:
            response = client.post("/v1/coach", headers=self.headers, json={
                "editor": "Kdenlive", "version": "25.08", "question": "How do I make a zoom?",
            })
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("sources", response.json())

    def test_other_editor_still_works_without_indexed_sources(self):
        def fake(request):
            question = json.loads(request.content)["contents"][0]["parts"][0]["text"]
            self.assertIn("Editor: Canva", question)
            self.assertNotIn("RETRIEVED REFERENCE DATA", question)
            return httpx.Response(200, json={"candidates": [{"content": {
                "parts": [{"text": "Check the Canva video editor controls."}]
            }}]})

        with self.client(fake) as client:
            response = client.post("/v1/coach", headers=self.headers, json={
                "editor": "Canva", "question": "How to zoom?",
            })
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("sources", response.json())

    def test_missing_index_fails_before_starting_server_when_enabled(self):
        with patch.dict("os.environ", {**self.env, "COACH_KNOWLEDGE_DB": str(self.db) + "-missing"}, clear=True):
            with self.assertRaisesRegex(ValueError, "Knowledge index"):
                create_app()

    def test_rag_still_requires_auth(self):
        def never(request):
            self.fail("Unauthorized request reached Gemini")

        with self.client(never) as client:
            self.assertEqual(client.post("/v1/coach", json={
                "editor": "Kdenlive", "question": "How do I cut?"
            }).status_code, 401)


if __name__ == "__main__":
    unittest.main()
