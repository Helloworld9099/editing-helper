"""Guest demo tests; all Redis and Gemini traffic is simulated."""
import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import create_app


class FakeRedis:
    """In-memory stand-in for the atomic Redis Lua counter script."""

    def __init__(self):
        self.counts = {}
        self.fail = False
        self.calls = 0

    async def eval(self, _script, count, *args):
        self.calls += 1
        if self.fail:
            raise ConnectionError("private Redis error")
        keys = args[:count]
        limits = list(map(int, args[count:2 * count]))
        if any(self.counts.get(k, 0) >= cap for k, cap in zip(keys, limits)):
            return 0
        for key in keys:
            self.counts[key] = self.counts.get(key, 0) + 1
        return 1


class DemoBackendTests(unittest.TestCase):
    settings = {
        "COACH_PROVIDER": "gemini",
        "GEMINI_API_KEY": "test-private-gemini-key",
        "COACH_AUTH_MODE": "demo",
        "COACH_REQUIRE_AUTH": "1",
        "COACH_DEMO_GLOBAL_PER_DAY": "2",
        "COACH_DEMO_GLOBAL_PER_MINUTE": "10",
        "COACH_DEMO_IP_PER_MINUTE": "8",
        "COACH_DEMO_IP_PER_DAY": "60",
        "COACH_ALLOWED_HOSTS": "127.0.0.1",
    }

    def client(self, redis, model_handler, settings=None):
        with patch.dict(os.environ, {**self.settings, **(settings or {})}, clear=True):
            app = create_app(quota_store=redis, transport=httpx.MockTransport(model_handler))
        return TestClient(app, base_url="http://127.0.0.1:8000")

    @staticmethod
    def model_ok(req):
        assert req.url.host == "generativelanguage.googleapis.com"
        assert req.headers.get("x-goog-api-key") == "test-private-gemini-key"
        assert "authorization" not in req.headers
        assert json.loads(req.content)["generationConfig"]["maxOutputTokens"] == 2048
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "Use a keyframe."}]}}],
        })

    def test_guest_can_ask_without_a_token_and_global_quota_is_enforced(self):
        calls = []

        def fake(req):
            calls.append(str(req.url))
            return self.model_ok(req)

        store = FakeRedis()
        with self.client(store, fake) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            for _ in range(2):
                response = client.post("/v1/coach", json={"question": "Zoom?", "editor": "Kdenlive"})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["answer"], "Use a keyframe.")
            third = client.post("/v1/coach", json={"question": "Zoom?"})
            self.assertEqual(third.status_code, 429)
            self.assertEqual(third.headers["Retry-After"], "60")
        self.assertEqual(len(calls), 2)
        self.assertEqual(store.calls, 3)

    def test_guest_ip_limit_cannot_be_reset_by_spoofed_forwarded_header(self):
        calls = []

        def fake(req):
            calls.append(req.url.path)
            return self.model_ok(req)

        with self.client(FakeRedis(), fake, {
            "COACH_DEMO_GLOBAL_PER_DAY": "100", "COACH_DEMO_IP_PER_MINUTE": "1",
        }) as client:
            first = client.post("/v1/coach", json={"question": "Hello"},
                                headers={"X-Forwarded-For": "203.0.113.99"})
            second = client.post("/v1/coach", json={"question": "Hello"},
                                 headers={"X-Forwarded-For": "198.51.100.13"})
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 429)
        self.assertEqual(len(calls), 1)

    def test_redis_outage_fails_closed_before_gemini(self):
        store = FakeRedis()
        store.fail = True

        def no_call(_req):
            self.fail("Gemini must never be called when Redis is unavailable")

        with self.client(store, no_call) as client:
            res = client.post("/v1/coach", json={"question": "Hello"})
            self.assertEqual(res.status_code, 503)
            self.assertNotIn("private Redis error", res.text)

    def test_limit_persists_across_backend_instances_with_same_quota_store(self):
        shared = FakeRedis()
        for expected in (200, 200, 429):
            with self.client(shared, self.model_ok) as client:
                got = client.post("/v1/coach", json={"question": "Hello"})
                self.assertEqual(got.status_code, expected)

    def test_demo_mode_requires_explicit_redis_budget_and_no_shared_secret(self):
        with patch.dict(os.environ, self.settings, clear=True):
            with self.assertRaisesRegex(ValueError, "COACH_REDIS_URL"):
                create_app()
        no_budget = {**self.settings}
        del no_budget["COACH_DEMO_GLOBAL_PER_DAY"]
        with patch.dict(os.environ, no_budget, clear=True):
            with self.assertRaisesRegex(ValueError, "COACH_DEMO_GLOBAL_PER_DAY"):
                create_app(quota_store=FakeRedis())
        with patch.dict(os.environ, {**self.settings, "COACH_ACCESS_TOKEN": "secret"}, clear=True):
            with self.assertRaisesRegex(ValueError, "COACH_ACCESS_TOKEN"):
                create_app(quota_store=FakeRedis())
        with patch.dict(os.environ, {**self.settings, "COACH_DEMO_GLOBAL_PER_DAY": "9999"}, clear=True):
            with self.assertRaisesRegex(ValueError, "COACH_DEMO_GLOBAL_PER_DAY"):
                create_app(quota_store=FakeRedis())
        with patch.dict(os.environ, {**self.settings, "COACH_PROVIDER": "ollama"}, clear=True):
            with self.assertRaisesRegex(ValueError, "hosted model provider"):
                create_app(quota_store=FakeRedis())


if __name__ == "__main__":
    unittest.main()
