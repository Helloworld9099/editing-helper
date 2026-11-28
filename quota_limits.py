"""Shared request limits and atomic quota utilities for the coach API."""
import asyncio
import os
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

MAX_REQUEST_BYTES = 32 * 1024
MAX_VIDEO_BYTES = 10 * 1024 * 1024
VIDEO_PATH = "/v1/coach/video"


class CoachBodyLimitMiddleware:
    """Bound POST bodies before FastAPI parses JSON, including chunked bodies."""

    def __init__(self, app, max_bytes=MAX_REQUEST_BYTES, *, video_guard=None, guest_enabled=True):
        self.app = app
        self.max_bytes = max_bytes
        self.video_guard = video_guard
        self.guest_enabled = guest_enabled
        self.video_upload = asyncio.Lock()
        self.in_flight = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        if not self.guest_enabled:
            await JSONResponse({"detail": "The public demo is temporarily disabled."},
                               status_code=503)(scope, receive, send)
            return
        if self.in_flight >= 16:
            await JSONResponse({"detail": "Coach is busy. Try again in a moment."},
                               status_code=429, headers={"Retry-After": "1"})(scope, receive, send)
            return
        self.in_flight += 1
        try:
            if scope["path"] == VIDEO_PATH:
                if self.video_upload.locked():
                    await JSONResponse({"detail": "Video analysis is busy. Try again in a moment."},
                                       status_code=429, headers={"Retry-After": "1"})(scope, receive, send)
                    return
                async with self.video_upload:
                    # Fail closed before buffering or decoding an untrusted clip.
                    if self.video_guard is not None:
                        try:
                            await self.video_guard(Request(scope))
                        except HTTPException as exc:
                            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                                               headers=exc.headers)(scope, receive, send)
                            return
                    await self.bounded_request(scope, receive, send, MAX_VIDEO_BYTES + MAX_REQUEST_BYTES, 20)
            else:
                await self.bounded_request(scope, receive, send, self.max_bytes, 15)
        finally:
            self.in_flight -= 1

    async def bounded_request(self, scope, receive, send, max_bytes, upload_timeout=None):
        async def reject():
            detail = ("The video exceeds the 10 MiB upload limit." if scope["path"] == VIDEO_PATH
                      else "Request body is too large.")
            response = JSONResponse({"detail": detail}, status_code=413)
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
                if length > max_bytes:
                    await reject()
                    return

        body = bytearray()
        try:
            async with asyncio.timeout(upload_timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > max_bytes:
                        await reject()
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            response = JSONResponse({"detail": "The request upload took too long. Try again."}, status_code=408)
            await response(scope, receive, send)
            return

        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            payload = bytes(body)
            body.clear()
            return {"type": "http.request", "body": payload, "more_body": False}

        await self.app(scope, replay, send)


# Use a Redis Cluster hash tag so all keys in the atomic script share a slot.
QUOTA_SCRIPT = """
-- ARGV: limits, expiry seconds, positive reservation weights, check-only flag.
for i = 1, #KEYS do
  local used = tonumber(redis.call('GET', KEYS[i]) or '0')
  local weight = tonumber(ARGV[2 * #KEYS + i])
  if used + weight > tonumber(ARGV[i]) then return 0 end
end
if ARGV[3 * #KEYS + 1] == '1' then return 1 end
for i = 1, #KEYS do
  local weight = tonumber(ARGV[2 * #KEYS + i])
  local count = redis.call('INCRBY', KEYS[i], weight)
  if count == weight then redis.call('EXPIRE', KEYS[i], tonumber(ARGV[#KEYS + i])) end
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


class VideoQuota:
    """Limit expensive analyses independently of the general chat quota."""

    def __init__(self, redis_store=None):
        self.redis = redis_store
        self.per_minute = positive_limit("COACH_VIDEO_GLOBAL_PER_MINUTE", 3, 60)
        self.per_day = positive_limit("COACH_VIDEO_GLOBAL_PER_DAY", 20, 1000)
        self.windows = [(None, 0), (None, 0)]

    @staticmethod
    def keys(now):
        return [f"{{coach-quota}}:video:minute:{now:%Y%m%d%H%M}",
                f"{{coach-quota}}:video:day:{now:%Y%m%d}"]

    @property
    def limits(self):
        return [self.per_minute, self.per_day]

    @staticmethod
    def exceeded():
        return HTTPException(429, "Video analysis usage limit reached. Try again later.",
                             headers={"Retry-After": "60"})

    async def charge(self):
        keys = self.keys(datetime.now(timezone.utc))
        if self.redis is not None:
            try:
                allowed = await self.redis.eval(QUOTA_SCRIPT, 2, *keys, *self.limits, 120, 172800, 1, 1, 0)
            except Exception:
                raise HTTPException(503, "Video usage protection is temporarily unavailable.") from None
            if allowed != 1:
                raise self.exceeded()
            return
        counts = [used if current == previous else 0
                  for current, (previous, used) in zip(keys, self.windows)]
        if any(used >= limit for used, limit in zip(counts, self.limits)):
            raise self.exceeded()
        self.windows = [(key, used + 1) for key, used in zip(keys, counts)]
