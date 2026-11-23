import asyncio
import json
import unittest

import httpx
from fastapi.testclient import TestClient

from app import OLLAMA_CHAT, create_app


class BackendTests(unittest.TestCase):
    def client(self, handler, **options):
        return TestClient(
            create_app(model="qwen3.5:4b", transport=httpx.MockTransport(handler), **options),
            base_url="http://127.0.0.1:8000",
        )

    def test_frontend_contract_and_private_ollama_request(self):
        def fake(request):
            self.assertEqual(str(request.url), OLLAMA_CHAT)
            self.assertEqual(request.method, "POST")
            data = json.loads(request.content)
            self.assertEqual(data["model"], "qwen3.5:4b")
            self.assertEqual(data["messages"], [{"role": "user", "content": "Hello"}])
            self.assertFalse(data["think"])
            self.assertFalse(data["stream"])
            return httpx.Response(200, json={"message": {"content": "Hi", "thinking": "private"}})

        with self.client(fake) as client:
            response = client.post("/v1/coach", json={"question": " Hello "})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"answer": "Hi"})

    def test_health_and_validation_do_not_call_model(self):
        def never(request):
            self.fail("Invalid request reached Ollama")

        with self.client(never) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            for request in ({}, {"question": "  "}, {"question": "x" * 1001},
                            {"question": 3}, {"question": "hello", "model": "other"}):
                with self.subTest(request=request):
                    self.assertEqual(client.post("/v1/coach", json=request).status_code, 422)
            self.assertEqual(client.get("/health", headers={"host": "example.org"}).status_code, 400)

    def test_bad_upstream_http_and_payload(self):
        cases = [(httpx.Response(404), 503), (httpx.Response(500), 502),
                 (httpx.Response(302, headers={"location": "https://example.org"}), 502),
                 (httpx.Response(200, text="not json"), 502),
                 (httpx.Response(200, json={"message": {"content": ""}}), 502)]
        for upstream, expected in cases:
            with self.subTest(expected=expected, upstream=upstream):
                with self.client(lambda request: upstream) as client:
                    response = client.post("/v1/coach", json={"question": "Hello"})
                    self.assertEqual(response.status_code, expected)
                    self.assertIn("detail", response.json())

    def test_model_down(self):
        def unavailable(request):
            raise httpx.ConnectError("local failure detail", request=request)

        with self.client(unavailable) as client:
            response = client.post("/v1/coach", json={"question": "Hello"})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("local failure detail", response.text)

    def test_timeout_releases_slot(self):
        calls = 0

        async def slow_first(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                await asyncio.sleep(1)
            return httpx.Response(200, json={"message": {"content": "Hi"}})

        with self.client(slow_first, timeout=0.05) as client:
            self.assertEqual(client.post("/v1/coach", json={"question": "First"}).status_code, 504)
            self.assertEqual(client.post("/v1/coach", json={"question": "Second"}).json(), {"answer": "Hi"})

    def test_cloud_model_tags_rejected(self):
        with self.assertRaises(ValueError):
            create_app(model="qwen3.5:cloud")


if __name__ == "__main__":
    unittest.main()
