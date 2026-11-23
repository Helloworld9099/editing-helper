import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

import httpx
from fastapi.testclient import TestClient

from app import create_app
from launch import run
from argparse import Namespace


class LocalRunnerTests(unittest.TestCase):
    def test_llama_backend_preserves_contract(self):
        def reply(req):
            import json
            body = json.loads(req.content)
            self.assertEqual(str(req.url), "http://127.0.0.1:8081/v1/chat/completions")
            self.assertEqual(body["messages"][0]["content"], "Editor: Kdenlive\nVersion: 26.08\nZoom?")
            return httpx.Response(200, json={"choices": [{"message": {
                "content": "Use Transform.", "reasoning_content": "Not for display",
            }}]})
        app = create_app(provider="llama.cpp", transport=httpx.MockTransport(reply))
        with TestClient(app, base_url="http://127.0.0.1") as client:
            resp = client.post("/v1/coach", json={"question": "Zoom?", "editor": "Kdenlive",
                                                  "version": "26.08"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"answer": "Use Transform."})

    def test_empty_choices_yields_502(self):
        t = httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": []}))
        with TestClient(create_app(provider="llama.cpp", transport=t), base_url="http://127.0.0.1") as client:
            self.assertEqual(client.post("/v1/coach", json={"question": "Zoom?"}).status_code, 502)

    def test_launcher_rejects_wrong_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "sample.gguf"
            model.write_bytes(b"GGUFexample")
            args = Namespace(model=model, runner=Path(sys.executable),
                             sha256=hashlib.sha256(b"wrong").hexdigest())
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                run(args)
