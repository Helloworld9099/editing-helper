"""Public account auth and quota tests; never touch real Supabase, Redis or Gemini."""
import base64
import io
import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from app import create_app


class FakeRedis:
    def __init__(self):
        self.counters = {}
        self.calls = 0
        self.fail = False

    async def eval(self, script, count, *args):
        self.calls += 1
        if self.fail:
            raise ConnectionError("redis down")
        keys = args[:count]
        limits = [int(x) for x in args[count:count * 2]]
        if any(self.counters.get(k, 0) >= limit for k, limit in zip(keys, limits)):
            return 0
        for key in keys:
            self.counters[key] = self.counters.get(key, 0) + 1
        return 1


class PublicAuthTests(unittest.TestCase):
    env = {
        "COACH_PROVIDER": "gemini",
        "GEMINI_API_KEY": "gemini-private-test-key",
        "COACH_AUTH_MODE": "users",
        "COACH_REQUIRE_AUTH": "1",
        "AUTH_SUPABASE_URL": "https://project.supabase.co",
        "AUTH_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
        "COACH_USER_PER_MINUTE": "3",
        "COACH_USER_PER_DAY": "10",
        "COACH_GLOBAL_PER_DAY": "20",
    }
    valid_token = "header.payload.signature"

    def server(self, handler, *, redis=None, changes=None):
        store = redis or FakeRedis()
        with patch.dict(os.environ, {**self.env, **(changes or {})}, clear=True):
            api = create_app(transport=httpx.MockTransport(handler), quota_store=store)
        return TestClient(api, base_url="http://127.0.0.1:8000"), store

    @staticmethod
    def fake_user(request):
        if request.url.path == "/auth/v1/user":
            if request.headers.get("authorization") != "Bearer header.payload.signature":
                return httpx.Response(401)
            return httpx.Response(200, json={
                "id": "74ca47c8-dda1-499e-99cc-50f5b6ae1fa3",
                "email": "someone@example.com",
                "email_confirmed_at": "2026-11-24T18:00:00Z",
                "is_anonymous": False,
            })
        if request.url.host == "generativelanguage.googleapis.com":
            assert request.headers["x-goog-api-key"] == "gemini-private-test-key"
            assert "authorization" not in request.headers
            assert json.loads(request.content)["generationConfig"]["maxOutputTokens"] == 2048
            return httpx.Response(200, json={
                "candidates": [{"content": {"parts": [{"text": "Use keyframes."}]}}],
            })
        raise AssertionError(f"Unexpected network call: {request.url}")

    def test_public_mode_requires_configured_identity_and_quotas(self):
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaisesRegex(ValueError, "COACH_REDIS_URL"):
                create_app()
        with patch.dict(os.environ, {**self.env, "AUTH_SUPABASE_URL": ""}, clear=True):
            with self.assertRaisesRegex(ValueError, "AUTH_SUPABASE_URL"):
                create_app(quota_store=FakeRedis())
        with patch.dict(os.environ, {**self.env, "AUTH_SUPABASE_PUBLISHABLE_KEY": ""}, clear=True):
            with self.assertRaisesRegex(ValueError, "AUTH_SUPABASE_PUBLISHABLE_KEY"):
                create_app(quota_store=FakeRedis())
        with patch.dict(os.environ, {**self.env, "COACH_GLOBAL_PER_DAY": "0"}, clear=True):
            with self.assertRaisesRegex(ValueError, "COACH_GLOBAL_PER_DAY"):
                create_app(quota_store=FakeRedis())

    def test_missing_bad_and_shared_tokens_never_reach_gemini(self):
        calls = []
        def handler(req):
            calls.append(str(req.url))
            return httpx.Response(401)
        client, store = self.server(handler)
        with client:
            for auth in ({}, {"Authorization": "Bearer old-shared-secret"},
                         {"Authorization": "Bearer bogus"}):
                response = client.post("/v1/coach", headers=auth, json={"question": "How?"})
                self.assertEqual(response.status_code, 401)
        self.assertEqual(store.calls, 0)
        self.assertEqual(calls, [])

    def test_verified_user_can_call_gemini_with_per_user_quota(self):
        calls = []
        def handler(req):
            calls.append(str(req.url))
            return self.fake_user(req)
        client, store = self.server(handler, changes={"COACH_USER_PER_MINUTE": "1"})
        with client:
            headers = {"Authorization": f"Bearer {self.valid_token}"}
            result = client.post("/v1/coach", json={"question": "How?"}, headers=headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["answer"], "Use keyframes.")
            again = client.post("/v1/coach", json={"question": "How?"}, headers=headers)
            self.assertEqual(again.status_code, 429)
            self.assertEqual(again.headers.get("Retry-After"), "60")
            self.assertEqual(store.calls, 4)
            self.assertEqual(sum("generativelanguage" in u for u in calls), 1)

    def test_remote_screen_analysis_uses_public_identity_and_shared_quota(self):
        calls = []

        def handler(request):
            calls.append(request)
            return self.fake_user(request)

        client, _ = self.server(handler, changes={"COACH_USER_PER_MINUTE": "1"})
        image = io.BytesIO()
        Image.new("RGB", (20, 10), "blue").save(image, format="PNG")
        payload = {"editor": "Kdenlive", "mode": "improve", "mime_type": "image/png",
                   "image": base64.b64encode(image.getvalue()).decode("ascii")}
        endpoint = "https://127.0.0.1:8000/v1/screen-analysis"
        headers = {"Authorization": f"Bearer {self.valid_token}"}
        with client:
            self.assertEqual(client.post(endpoint, json=payload).status_code, 401)
            self.assertEqual(calls, [])
            res = client.post(endpoint, json=payload, headers=headers)
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.json(), {"answer": "Use keyframes."})
            coach = client.post("https://127.0.0.1:8000/v1/coach",
                                json={"question": "What next?"}, headers=headers)
            self.assertEqual(coach.status_code, 429)
        self.assertEqual(sum(r.url.host == "generativelanguage.googleapis.com" for r in calls), 1)

    def test_invalid_identity_cannot_claim_an_account(self):
        def fake(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json={
                    "id": "74ca47c8-dda1-499e-99cc-50f5b6ae1fa3",
                    "email": "someone@example.com",
                    "is_anonymous": True,
                    "email_confirmed_at": None,
                })
            raise AssertionError("Model should not run")
        client, store = self.server(fake)
        with client:
            response = client.post("/v1/coach",
                                   headers={"Authorization": f"Bearer {self.valid_token}"},
                                   json={"question": "Hello"})
            self.assertEqual(response.status_code, 401)
        self.assertEqual(store.calls, 1)

    def test_auth_and_quota_fail_closed(self):
        client, store = self.server(lambda req: httpx.Response(503))
        with client:
            res = client.post("/v1/coach",
                              headers={"Authorization": f"Bearer {self.valid_token}"},
                              json={"question": "Hello"})
            self.assertEqual(res.status_code, 503)
        store = FakeRedis()
        store.fail = True
        client, store = self.server(self.fake_user, redis=store)
        with client:
            res = client.post("/v1/coach",
                              headers={"Authorization": f"Bearer {self.valid_token}"},
                              json={"question": "Hello"})
            self.assertEqual(res.status_code, 503)
            self.assertNotIn("redis down", res.text)


if __name__ == "__main__":
    unittest.main()
