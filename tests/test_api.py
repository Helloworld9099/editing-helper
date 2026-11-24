import asyncio
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import GROQ_CHAT, OLLAMA_CHAT, create_app


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


class CloudBackendTests(unittest.TestCase):
    env = {
        "COACH_PROVIDER": "groq",
        "COACH_MODEL": "test/chat-model",
        "GROQ_API_KEY": "test-groq-key",
        "COACH_ACCESS_TOKEN": "test-coach-token",
        "COACH_ALLOWED_HOSTS": " coach.example.org, 127.0.0.1 ",
    }
    auth = {"Authorization": "Bearer test-coach-token"}

    def client(self, handler):
        with patch.dict("os.environ", self.env, clear=True):
            app = create_app(transport=httpx.MockTransport(handler))
        return TestClient(app, base_url="https://coach.example.org")

    def test_authentication_and_allowed_hosts_leave_health_public(self):
        def never(request):
            self.fail("An unauthorized request or health check reached Groq")

        with self.client(never) as client:
            health = client.get("/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json(), {"status": "ok"})
            self.assertEqual(client.get("/health", headers={"Host": "127.0.0.1:8000"}).status_code, 200)
            self.assertEqual(client.get("/health", headers={"Host": "other.example.org"}).status_code, 400)

            for header in (None, "Bearer wrong", "Basic test-coach-token", "Bearer test-groq-key"):
                with self.subTest(header=header):
                    response = client.post("/v1/coach", json={"question": "Hello"},
                                           headers={} if header is None else {"Authorization": header})
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_groq_request_and_response(self):
        def fake(request):
            self.assertEqual(str(request.url), GROQ_CHAT)
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.headers["Authorization"], "Bearer test-groq-key")
            self.assertEqual(json.loads(request.content), {
                "model": "test/chat-model",
                "messages": [{"role": "user", "content": "Editor: DaVinci Resolve\nVersion: 20\nZoom?"}],
                "max_completion_tokens": 512,
                "stream": False,
            })
            return httpx.Response(200, json={"choices": [{"message": {
                "content": "Use the Inspector.", "reasoning": "extra provider metadata",
            }}]})

        with self.client(fake) as client:
            response = client.post("/v1/coach", headers=self.auth, json={
                "question": "Zoom?", "editor": "DaVinci Resolve", "version": "20",
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"answer": "Use the Inspector."})

    def test_groq_invalid_replies_and_upstream_errors(self):
        cases = [
            (httpx.Response(200, json={"choices": []}), 502),
            (httpx.Response(200, json={"choices": [{"message": {"content": None}}]}), 502),
            (httpx.Response(401, text="private upstream detail"), 502),
            (httpx.Response(404), 503),
        ]
        for upstream, expected in cases:
            with self.subTest(upstream=upstream), self.client(lambda request: upstream) as client:
                response = client.post("/v1/coach", headers=self.auth, json={"question": "Hi"})
                self.assertEqual(response.status_code, expected)
                self.assertIn("Groq", response.json()["detail"])
                self.assertNotIn("private upstream detail", response.text)

    def test_incomplete_cloud_configuration_fails_closed(self):
        for setting in ("GROQ_API_KEY", "COACH_ACCESS_TOKEN", "COACH_MODEL"):
            with self.subTest(setting=setting), patch.dict("os.environ", {**self.env, setting: ""}, clear=True):
                with self.assertRaisesRegex(ValueError, setting):
                    create_app()
        with patch.dict("os.environ", {"COACH_REQUIRE_AUTH": "1"}, clear=True):
            with self.assertRaisesRegex(ValueError, "COACH_ACCESS_TOKEN"):
                create_app()


class GeminiBackendTests(unittest.TestCase):
    env = {
        "COACH_PROVIDER": "gemini",
        "GEMINI_API_KEY": "test-gemini-key",
        "COACH_ACCESS_TOKEN": "test-coach-token",
    }
    auth = {"Authorization": "Bearer test-coach-token"}

    def client(self, handler, **settings):
        with patch.dict("os.environ", {**self.env, **settings}, clear=True):
            api = create_app(transport=httpx.MockTransport(handler))
        return TestClient(api, base_url="http://127.0.0.1:8000")

    def test_native_request_and_multipart_answer(self):
        def fake(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(
                str(request.url),
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            )
            self.assertEqual(request.headers["x-goog-api-key"], "test-gemini-key")
            self.assertNotIn("Authorization", request.headers)
            self.assertEqual(json.loads(request.content), {
                "contents": [{
                    "role": "user",
                    "parts": [{"text": "Editor: DaVinci Resolve\nVersion: 20\nZoom?"}],
                }],
            })
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                {"text": "Internal thought summary", "thought": True},
                {"text": "Open the Inspector.\n"},
                {"thoughtSignature": "opaque"},
                {"text": "Adjust Zoom."},
            ]}}]})

        with self.client(fake) as client:
            response = client.post("/v1/coach", headers=self.auth, json={
                "question": " Zoom? ", "editor": " DaVinci Resolve ", "version": " 20 ",
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"answer": "Open the Inspector.\nAdjust Zoom."})

    def test_model_override(self):
        def fake(request):
            self.assertEqual(request.url.path, "/v1beta/models/gemini-test:generateContent")
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Hi"}]}}]})

        for model in ("gemini-test", "models/gemini-test"):
            with self.subTest(model=model), self.client(fake, COACH_MODEL=model) as client:
                response = client.post("/v1/coach", headers=self.auth, json={"question": "Hello"})
                self.assertEqual(response.json(), {"answer": "Hi"})

    def test_coach_authentication(self):
        def never(request):
            self.fail("An unauthorized request or health check reached Gemini")

        with self.client(never) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            for headers in ({}, {"Authorization": "Bearer wrong"}, {"x-goog-api-key": "test-gemini-key"}):
                with self.subTest(headers=headers):
                    response = client.post("/v1/coach", headers=headers, json={"question": "Hello"})
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")

    def test_invalid_replies_and_upstream_errors(self):
        cases = [
            (httpx.Response(200, text="not JSON"), 502),
            (httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}), 502),
            (httpx.Response(200, json={"candidates": []}), 502),
            (httpx.Response(200, json={"candidates": [{"content": {"parts": {"text": "Hi"}}}]}), 502),
            (httpx.Response(200, json={"candidates": [{"content": {"parts": [
                {"text": 123}, {"text": " "}, {"text": "thought only", "thought": True},
            ]}}]}), 502),
            (httpx.Response(401, text="test-gemini-key"), 502),
            (httpx.Response(404), 503),
            (httpx.Response(429), 502),
            (httpx.Response(500), 502),
        ]
        for upstream, expected in cases:
            with self.subTest(upstream=upstream), self.client(lambda request: upstream) as client:
                response = client.post("/v1/coach", headers=self.auth, json={"question": "Hello"})
                self.assertEqual(response.status_code, expected)
                self.assertIn("Gemini", response.json()["detail"])
                self.assertNotIn("test-gemini-key", response.text)

    def test_connection_errors_and_timeouts(self):
        for error, expected in ((httpx.ConnectError, 503), (httpx.ReadTimeout, 504)):
            def fail(request):
                raise error("private upstream detail", request=request)

            with self.subTest(error=error), self.client(fail) as client:
                response = client.post("/v1/coach", headers=self.auth, json={"question": "Hello"})
                self.assertEqual(response.status_code, expected)
                self.assertIn("Gemini", response.json()["detail"])
                self.assertNotIn("private upstream detail", response.text)

    def test_invalid_configuration(self):
        for setting, value in (
            ("GEMINI_API_KEY", " "), ("COACH_ACCESS_TOKEN", ""), ("COACH_MODEL", "models/../other"),
        ):
            with self.subTest(setting=setting), patch.dict("os.environ", {**self.env, setting: value}, clear=True):
                with self.assertRaisesRegex(ValueError, setting):
                    create_app()


if __name__ == "__main__":
    unittest.main()
