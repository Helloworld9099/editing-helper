"""Shared request limits and atomic quota utilities for the coach API."""
import os

from starlette.responses import JSONResponse

MAX_REQUEST_BYTES = 32 * 1024


class CoachBodyLimitMiddleware:
    """Bound POST bodies before FastAPI parses JSON, including chunked bodies."""

    def __init__(self, app, max_bytes=MAX_REQUEST_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        async def reject():
            response = JSONResponse({"detail": "Request body is too large."}, status_code=413)
            await response(scope, receive, send)

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    length = int(value)
                except ValueError:
                    length = -1
                if length < 0:
                    response = JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)
                    await response(scope, receive, send)
                    return
                if length > self.max_bytes:
                    await reject()
                    return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await reject()
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


# Use a Redis Cluster hash tag so all keys in the atomic script share a slot.
QUOTA_SCRIPT = """
for i = 1, #KEYS do
  local used = tonumber(redis.call('GET', KEYS[i]) or '0')
  if used >= tonumber(ARGV[i]) then return 0 end
end
for i = 1, #KEYS do
  local count = redis.call('INCR', KEYS[i])
  if count == 1 then redis.call('EXPIRE', KEYS[i], tonumber(ARGV[#KEYS + i])) end
end
return 1
"""


def positive_limit(name: str, default: int, max_value: int = 100000) -> int:
    value = os.environ.get(name, str(default))
    try:
        n = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be a positive integer.") from None
    if n < 1 or n > max_value:
        raise ValueError(f"{name} must be between 1 and {max_value}.")
    return n
