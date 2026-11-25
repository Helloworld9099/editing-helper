"""Exercise body limits at the ASGI boundary without an external server."""
import asyncio
import json
import unittest

from quota_limits import CoachBodyLimitMiddleware


class RequestLimitTests(unittest.TestCase):
    def run_request(self, chunks, headers=(), method="POST", limit=16):
        sent = []
        seen = []
        pending = iter(chunks)

        async def receive():
            return next(pending)

        async def send(message):
            sent.append(message)

        async def downstream(scope, receive, send):
            seen.append(await receive())
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        scope = {"type": "http", "method": method, "path": "/v1/coach", "headers": list(headers)}
        asyncio.run(CoachBodyLimitMiddleware(downstream, max_bytes=limit)(scope, receive, send))
        return sent, seen

    def test_declared_oversize_rejected_before_read(self):
        sent, seen = self.run_request([], [(b"content-length", b"17")])
        self.assertEqual(sent[0]["status"], 413)
        self.assertEqual(seen, [])
        self.assertIn("too large", json.loads(sent[1]["body"])["detail"])

    def test_chunked_body_cannot_bypass_limit(self):
        chunks = [
            {"type": "http.request", "body": b"a" * 10, "more_body": True},
            {"type": "http.request", "body": b"b" * 7, "more_body": False},
        ]
        for headers in ([], [(b"content-length", b"5")]):
            with self.subTest(headers=headers):
                sent, seen = self.run_request(chunks, headers)
                self.assertEqual(sent[0]["status"], 413)
                self.assertEqual(seen, [])

    def test_exact_limit_passes_and_replays_complete_body(self):
        chunks = [
            {"type": "http.request", "body": b"a" * 8, "more_body": True},
            {"type": "http.request", "body": b"b" * 8, "more_body": False},
        ]
        sent, seen = self.run_request(chunks)
        self.assertEqual(sent[0]["status"], 200)
        self.assertEqual(seen, [{"type": "http.request", "body": b"a" * 8 + b"b" * 8, "more_body": False}])

    def test_invalid_content_length_is_rejected(self):
        for value in (b"-1", b"bad"):
            with self.subTest(value=value):
                sent, seen = self.run_request([], [(b"content-length", value)])
                self.assertEqual(sent[0]["status"], 400)
                self.assertEqual(seen, [])

    def test_disconnect_does_not_call_application(self):
        sent, seen = self.run_request([{"type": "http.disconnect"}])
        self.assertEqual((sent, seen), ([], []))

    def test_get_is_not_buffered(self):
        message = {"type": "http.request", "body": b"", "more_body": False}
        sent, seen = self.run_request([message], method="GET")
        self.assertEqual(sent[0]["status"], 200)
        self.assertEqual(seen, [message])
