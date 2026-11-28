"""Exercise the video endpoint using actual FFmpeg clips and a simulated Gemini."""
import base64
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import create_app
from quota_limits import MAX_VIDEO_BYTES, VIDEO_PATH
from test_demo_auth import FakeRedis


class VideoApiTests(unittest.TestCase):
    settings = {
        "COACH_PROVIDER": "gemini",
        "GEMINI_API_KEY": "server-only-key",
        "COACH_ACCESS_TOKEN": "coach-token",
        "COACH_ALLOWED_HOSTS": "testserver",
    }
    auth = {"Authorization": "Bearer coach-token"}

    @classmethod
    def setUpClass(cls):
        directory = cls.enterClassContext(TemporaryDirectory())
        cls.fixtures = Path(directory)
        for filename, duration in [("rapid.mov", 2), ("clean.webm", 1), ("long.mp4", 5.1), ("short.mp4", 0.9)]:
            filters = "drawbox=w=iw:h=ih:color=white:t=fill:enable='between(n,25,26)'"
            codec = "libvpx-vp9" if filename.endswith(".webm") else "libx264"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s=160x90:r=24:d={duration}",
                 "-vf", filters, "-c:v", codec, str(cls.fixtures / filename)], check=True,
            )

    def client(self, handler, settings=None, **kwargs):
        with patch.dict(os.environ, {**self.settings, **(settings or {})}, clear=True):
            return TestClient(create_app(transport=httpx.MockTransport(handler), **kwargs))

    def upload(self, client, filename="rapid.mov", *, data=None, headers=None, **fields):
        video = (self.fixtures / filename).read_bytes() if data is None else data
        return client.post(VIDEO_PATH, data={"editor": "Kdenlive", "version": "26.08", **fields},
                           files={"video": (filename, video)}, headers=self.auth if headers is None else headers)

    def no_gemini(self, _request):
        self.fail("Rejected uploads must not reach Gemini")

    @staticmethod
    def reply(text):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    def test_video_keeps_fast_frames_and_retrieves_references_from_detected_effects(self):
        calls = []
        reference = {
            "id": "flash", "title": "Flash with keyframes", "note": "Add opacity keyframes.", "editor": "Kdenlive",
            "version": "26.08", "url": "https://example.com/flash", "source_kind": "official",
            "review_status": "source_checked", "category": "effects",
        }

        def provider(request):
            payload = json.loads(request.content)
            calls.append(payload)
            self.assertEqual(request.headers["x-goog-api-key"], "server-only-key")
            self.assertNotIn("authorization", request.headers)
            if len(calls) == 2:
                text = payload["contents"][0]["parts"][0]["text"]
                self.assertIn("Add opacity keyframes.", text)
                self.assertIn("near-white burst lasting 2 sampled frames", text)
                self.assertIn('"version": "26.08"', text)
                self.assertIn('"question": ""', text)
                return self.reply("Add a white color clip on the upper track for two frames.")
            part = payload["contents"][0]["parts"][0]
            self.assertEqual(part["videoMetadata"]["fps"], 24)
            self.assertIn("1.000s, 1.167s", payload["contents"][0]["parts"][3]["text"])
            self.assertEqual(payload["contents"][0]["parts"][4]["inlineData"]["mimeType"], "image/jpeg")
            normalized = self.fixtures / "normalized.mp4"
            normalized.write_bytes(base64.b64decode(part["inlineData"]["data"]))
            frames = subprocess.check_output([
                "ffmpeg", "-v", "error", "-i", str(normalized), "-vf", "scale=1:1,format=gray",
                "-f", "rawvideo", "-",
            ])
            self.assertEqual(len(frames), 48)
            self.assertEqual([i for i, brightness in enumerate(frames) if brightness > 245], [25, 26])
            return self.reply(json.dumps({"effects": ["white flash"], "observations": "White at 1.04–1.13s."}))

        with (patch("app.index_path", return_value=self.fixtures / "rapid.mov"),
              patch("app.search_notes", return_value=[reference]) as rag,
              self.client(provider, {"COACH_RAG_ENABLED": "1"}) as client):
            response = self.upload(client)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(calls), 2)
        self.assertEqual(rag.call_args.args, ("white solid generator opacity keyframes ", "Kdenlive", "26.08"))
        self.assertEqual(response.json()["sources"][0]["id"], "flash")

    def test_rejects_unauthorized_oversized_invalid_and_out_of_range_uploads(self):
        with self.client(self.no_gemini) as client:
            self.assertEqual(self.upload(client, headers={}).status_code, 401)
            for name, data, status in [
                ("rapid.mov", b"0" * (MAX_VIDEO_BYTES + 1), 413),
                ("rapid.mov", b"0" * (MAX_VIDEO_BYTES + 65536), 413),
                ("fake.mp4", b"invalid video", 422),
                ("fake.webm", b"invalid video", 415),
                ("fake.avi", b"invalid video", 415),
                ("short.mp4", None, 422),
                ("long.mp4", None, 422),
            ]:
                with self.subTest(filename=name, expected=status):
                    response = self.upload(client, name, data=data)
                    self.assertEqual(response.status_code, status, response.text)
            bad_multipart = client.post(VIDEO_PATH, content=b"broken",
                                        headers={**self.auth, "Content-Type": "multipart/form-data; boundary=test"})
            self.assertEqual(bad_multipart.status_code, 400)

    def test_demo_video_quota_and_general_quota_are_charged_together(self):
        def provider(request):
            payload = json.loads(request.content)
            if payload.get("generationConfig", {}).get("responseMimeType"):
                return self.reply('{"effects":[],"observations":"No clear deliberate effects."}')
            return self.reply("No deliberate effect is evident.")

        settings = {"COACH_AUTH_MODE": "demo", "COACH_ACCESS_TOKEN": "", "COACH_DEMO_GLOBAL_PER_DAY": "3",
                    "COACH_VIDEO_GLOBAL_PER_DAY": "1"}
        store = FakeRedis()
        with self.client(provider, settings, quota_store=store) as client:
            first = self.upload(client, "clean.webm", headers={}, question="Is there an effect?")
            self.assertEqual(first.status_code, 200, first.text)
            with patch("app.prepare_clip", side_effect=AssertionError("Budget exhausted before decoding")) as decode:
                self.assertEqual(self.upload(client, headers={}).status_code, 429)
                decode.assert_not_called()
            self.assertEqual(client.post("/v1/coach", json={"question": "hello"}).status_code, 200)
            self.assertEqual(client.post("/v1/coach", json={"question": "hello"}).status_code, 429)
        calls = [count for key, count in store.counts.items() if ":demo:global:day:" in key]
        videos = [count for key, count in store.counts.items() if ":video:day:" in key]
        self.assertEqual(calls, [3])
        self.assertEqual(videos, [1])

    def test_video_requires_two_model_calls_remaining_before_decoding(self):
        settings = {"COACH_AUTH_MODE": "demo", "COACH_ACCESS_TOKEN": "",
                    "COACH_DEMO_GLOBAL_PER_DAY": "1"}
        store = FakeRedis()
        with self.client(self.no_gemini, settings, quota_store=store) as client:
            with patch("app.prepare_clip", side_effect=AssertionError("Quota must precede decoding")) as decode:
                self.assertEqual(self.upload(client, headers={}).status_code, 429)
                decode.assert_not_called()
        self.assertFalse(any(":demo:" in key or ":video:" in key for key in store.counts))

    def test_invalid_uploads_have_separate_predecode_limit(self):
        settings = {"COACH_AUTH_MODE": "demo", "COACH_ACCESS_TOKEN": "",
                    "COACH_DEMO_GLOBAL_PER_DAY": "20", "COACH_UPLOAD_IP_PER_DAY": "1"}
        store = FakeRedis()
        with self.client(self.no_gemini, settings, quota_store=store) as client:
            self.assertEqual(self.upload(client, "fake.mp4", data=b"bad video", headers={}).status_code, 422)
            with patch("app.prepare_clip", side_effect=AssertionError("Upload limit must precede decoding")) as decode:
                self.assertEqual(self.upload(client, headers={}).status_code, 429)
                decode.assert_not_called()
        self.assertFalse(any(":demo:" in key or ":video:" in key for key in store.counts))
        self.assertEqual([count for key, count in store.counts.items() if ":upload:global:day:" in key], [1])

    def test_video_redis_outage_does_not_decode(self):
        settings = {"COACH_AUTH_MODE": "demo", "COACH_ACCESS_TOKEN": "",
                    "COACH_DEMO_GLOBAL_PER_DAY": "20"}
        store = FakeRedis()
        store.fail = True
        with self.client(self.no_gemini, settings, quota_store=store) as client:
            with patch("app.prepare_clip", side_effect=AssertionError("Redis unavailable")) as decode:
                self.assertEqual(self.upload(client, headers={}).status_code, 503)
                decode.assert_not_called()

    def test_media_subprocess_does_not_inherit_credentials(self):
        import asyncio
        import sys
        from video_analysis import run_media

        with patch.dict(os.environ, {"GEMINI_API_KEY": "not-for-child",
                                     "COACH_ACCESS_TOKEN": "not-for-child",
                                     "COACH_REDIS_URL": "not-for-child"}):
            result = asyncio.run(run_media(sys.executable, "-c",
                "import json, os; print(json.dumps(dict(os.environ)))"))
        child = json.loads(result)
        for name in ("GEMINI_API_KEY", "COACH_ACCESS_TOKEN", "COACH_REDIS_URL"):
            self.assertNotIn(name, child)

    def test_provider_failures_and_timeouts_return_actionable_statuses(self):
        def timeout(_request):
            raise httpx.ReadTimeout("private provider details")

        for handler, status in [(timeout, 504), (lambda _: httpx.Response(500), 502)]:
            with self.subTest(expected=status), self.client(handler) as client:
                result = self.upload(client)
                self.assertEqual(result.status_code, status, result.text)
                self.assertNotIn("private provider details", result.text)

    def test_text_only_provider_still_handles_text(self):
        with self.client(lambda _: httpx.Response(200, json={"message": {"content": "Text answer"}}),
                         {"COACH_PROVIDER": "ollama"}) as client:
            self.assertEqual(self.upload(client).status_code, 503)
            response = client.post("/v1/coach", json={"question": "How do I cut?"}, headers=self.auth)
            self.assertEqual(response.json(), {"answer": "Text answer"})
