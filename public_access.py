"""Public accounts: identity is verified with Supabase Auth; Redis enforces shared quotas."""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request

# All counters are checked and incremented together, across all FastAPI replicas.
# The hash tag keeps the keys in one Redis Cluster slot.
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


class PublicAccess:
    """Never trust a user ID provided by an Electron client or a JWT parsed locally."""

    def __init__(self, *, supabase_url: str, publishable_key: str, redis_store):
        parsed = urlsplit(supabase_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or parsed.port not in (None, 443)):
            raise ValueError("AUTH_SUPABASE_URL must be a valid HTTPS origin.")
        if not publishable_key or len(publishable_key) > 4096:
            raise ValueError("AUTH_SUPABASE_PUBLISHABLE_KEY is required.")
        if redis_store is None:
            raise ValueError("Public auth requires a shared Redis quota store.")
        self.url = supabase_url.rstrip("/")
        self.key = publishable_key
        self.redis = redis_store
        self.user_per_minute = positive_limit("COACH_USER_PER_MINUTE", 5)
        self.user_per_day = positive_limit("COACH_USER_PER_DAY", 30)
        self.ip_per_minute = positive_limit("COACH_IP_PER_MINUTE", 180)
        self.global_per_day = positive_limit("COACH_GLOBAL_PER_DAY", 1000)
        self.auth_lookups_ip_per_minute = positive_limit("COACH_AUTH_LOOKUPS_IP_PER_MINUTE", 100)
        self.auth_lookups_global_per_minute = positive_limit("COACH_AUTH_LOOKUPS_GLOBAL_PER_MINUTE", 2500)

    async def throttle_identity_lookup(self, request: Request) -> None:
        # Protect Supabase /auth/v1/user from unlimited fabricated-JWT probes.
        now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        ip = request.client.host if request.client else "unknown"
        ip_id = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:22]
        keys = [
            f"{{coach-quota}}:auth:ip:{ip_id}:minute:{now}",
            f"{{coach-quota}}:auth:global:minute:{now}",
        ]
        try:
            allowed = await self.redis.eval(
                QUOTA_SCRIPT, 2, *keys,
                self.auth_lookups_ip_per_minute, self.auth_lookups_global_per_minute,
                120, 120,
            )
        except Exception:
            raise HTTPException(503, "Usage limits are temporarily unavailable.") from None
        if allowed != 1:
            raise HTTPException(429, "Too many authentication attempts.",
                                headers={"Retry-After": "60"})

    async def authenticate(self, token: str, client: httpx.AsyncClient) -> str:
        if not isinstance(token, str) or len(token) > 8192 or not re.fullmatch(
                r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
            raise HTTPException(401, "Sign in to continue.", headers={"WWW-Authenticate": "Bearer"})
        try:
            response = await client.get(
                f"{self.url}/auth/v1/user",
                headers={"apikey": self.key, "Authorization": f"Bearer {token}"},
                timeout=8.0,
                follow_redirects=False,
            )
        except httpx.RequestError:
            raise HTTPException(503, "Authentication is temporarily unavailable.") from None
        if response.status_code in (401, 403):
            raise HTTPException(401, "Your session has expired. Please sign in again.",
                                headers={"WWW-Authenticate": "Bearer"})
        if response.status_code != 200:
            raise HTTPException(503, "Authentication is temporarily unavailable.")
        try:
            user = response.json()
            user_id = user["id"]
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, "Authentication returned an invalid response.") from None
        if (not isinstance(user_id, str) or
                not re.fullmatch(r"[0-9a-fA-F-]{36}", user_id) or
                user.get("is_anonymous") is True or
                not user.get("email") or not user.get("email_confirmed_at")):
            raise HTTPException(401, "A verified email account is required.")
        return user_id.lower()

    async def charge(self, user_id: str, request: Request) -> None:
        now = datetime.now(timezone.utc)
        minute = now.strftime("%Y%m%d%H%M")
        day = now.strftime("%Y%m%d")
        # request.client.host is framework-controlled, not attacker-supplied X-Forwarded-For.
        # Depending on the proxy this may identify a shared gateway; keep the IP cap generous.
        ip = request.client.host if request.client else "unknown"
        ip_id = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:22]
        keys = [
            f"{{coach-quota}}:user:{user_id}:minute:{minute}",
            f"{{coach-quota}}:user:{user_id}:day:{day}",
            f"{{coach-quota}}:ip:{ip_id}:minute:{minute}",
            f"{{coach-quota}}:global:day:{day}",
        ]
        limits = [self.user_per_minute, self.user_per_day,
                  self.ip_per_minute, self.global_per_day]
        try:
            result = await self.redis.eval(
                QUOTA_SCRIPT, len(keys), *keys, *limits, 120, 172800, 120, 172800,
            )
        except Exception:
            # Never skip quota enforcement when a public Redis service is down.
            raise HTTPException(503, "Usage limits are temporarily unavailable.") from None
        if result != 1:
            raise HTTPException(429, "Usage limit reached. Try again later.",
                                headers={"Retry-After": "60"})
