import base64
import io
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

from app import create_app
from screen_analysis import MAX_BODY


class ScreenAnalysisTests(unittest.TestCase):
    def setUp(self):
        png = io.BytesIO()
        meta = PngImagePlugin.PngInfo()
        meta.add_text("comment", "private metadata")
        Image.new("RGB", (20, 12), "blue").save(png, format="PNG", pnginfo=meta)
        self.body = dict(image=base64.b64encode(png.getvalue()).decode(), mime_type="image/png",
                         editor="Kdenlive", mode="improve", context="Minecraft SMP")
        self.path = "/v1/screen-analysis"
        self.calls = []
        self.reply = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "**Review**"}]}}]})

    def client(self, key="test-key", **settings):
        def mock(req):
            self.calls.append(req)
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply

        with patch.dict("os.environ", {"GEMINI_API_KEY": key, "GEMINI_VISION_MODEL": "fixture",
                                       **settings}, clear=True):
            api = create_app(transport=httpx.MockTransport(mock))
        return TestClient(api, base_url="http://127.0.0.1", client=("127.0.0.1", 5000))

    def test_vision_is_independent_of_text_provider_and_strips_metadata(self):
        with self.client() as client:
            for mode in ["effect", "fix", "improve"]:
                result = client.post(self.path, json={**self.body, "mode": mode})
                self.assertEqual(result.json(), {"answer": "**Review**"})
                req = self.calls[-1]
                self.assertEqual(req.url.host, "generativelanguage.googleapis.com")
                self.assertIn("fixture:generateContent", req.url.path)
                self.assertEqual(req.headers["x-goog-api-key"], "test-key")
                data = json.loads(req.content)
                self.assertIn("untrusted", data["systemInstruction"]["parts"][0]["text"])
                image, text = data["contents"][0]["parts"]
                decoded = Image.open(io.BytesIO(base64.b64decode(image["inlineData"]["data"])))
                self.assertEqual(decoded.getpixel((0, 0)), (0, 0, 255, 255))
                self.assertNotIn("comment", decoded.info)
                self.assertEqual(json.loads(text["text"])["context"], "Minecraft SMP")

    def test_request_limits_and_content_validation(self):
        with self.client() as client:
            for fields in [{"image": ""}, {"image": "private-invalid-data"}, {"context": "x"*1001},
                           {"mode": "bogus"}, {"editor": "bogus"}, {"mime_type": "image/jpeg"},
                           {"content_type": "bogus"}, {"question": "bad\x00text"}]:
                reply = client.post(self.path, json={**self.body, **fields})
                self.assertEqual(reply.status_code, 422)
                self.assertNotIn("private-invalid-data", reply.text)
            self.assertEqual(client.post(self.path, content=b' '*(MAX_BODY+1),
                                         headers={"Content-Type": "application/json"}).status_code, 413)
            self.assertEqual(self.calls, [])

    def test_auth_transport_and_configuration(self):
        with self.client(key="") as client:
            self.assertEqual(client.post(self.path, json=self.body).status_code, 503)
        with self.client(COACH_ACCESS_TOKEN="token", COACH_ALLOWED_HOSTS="example.org") as client:
            self.assertEqual(client.post("https://example.org"+self.path, json=self.body).status_code, 401)
            reply = client.post("http://example.org"+self.path, headers={"Authorization": "Bearer token"}, json=self.body)
            self.assertEqual(reply.status_code, 403)
        self.assertEqual(self.calls, [])

    def test_upstream_failures_release_capacity(self):
        with self.client() as client:
            for upstream, status in [(httpx.ReadTimeout("private"), 504), (httpx.Response(404), 503),
                                     (httpx.Response(429), 429), (httpx.Response(500), 502),
                                     (httpx.Response(200, json={"malformed": "private"}), 502)]:
                self.reply = upstream
                response = client.post(self.path, json=self.body)
                self.assertEqual(response.status_code, status)
                self.assertNotIn("private", response.text)
            self.assertEqual(len(self.calls), 5)

    def test_rate_and_concurrency_limits_leave_text_usable(self):
        with self.client() as client:
            slot = client.app.state.vision_slot
            client.portal.call(slot.acquire)
            try:
                self.assertEqual(client.post(self.path, json=self.body).status_code, 429)
                self.assertEqual(self.calls, [])
            finally:
                client.portal.call(slot.release)
            for _ in range(10):
                self.assertEqual(client.post(self.path, json=self.body).status_code, 200)
            self.assertEqual(client.post(self.path, json=self.body).status_code, 429)
            self.reply = httpx.Response(200, json={"message": {"content": "Text still works"}})
            self.assertEqual(client.post("/v1/coach", json={"question": "How do I trim?"}).json(),
                             {"answer": "Text still works"})
