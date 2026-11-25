"""Guest demo quotas for a public, unauthenticated but bounded AI endpoint.

A request is charged atomically in Redis before Gemini is contacted. Quotas
are not proof of identity; a guest can rotate IPs, so the global cap is vital.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from public_access import QUOTA_SCRIPT, positive_limit


class DemoAccess:
    """Bound anonymous use even across multiple FastAPI instances/restarts."""

    def __init__(self, redis_store):
        if redis_store is None:
            raise ValueError("COACH_REDIS_URL is required in demo mode.")
        if not os.environ.get("COACH_DEMO_GLOBAL_PER_DAY", "").strip():
            raise ValueError("COACH_DEMO_GLOBAL_PER_DAY must be explicitly set in demo mode.")
        self.redis = redis_store
        self.global_per_day = positive_limit("COACH_DEMO_GLOBAL_PER_DAY", 100, 1000)
        self.global_per_minute = positive_limit("COACH_DEMO_GLOBAL_PER_MINUTE", 20, 120)
        self.ip_per_day = positive_limit("COACH_DEMO_IP_PER_DAY", 60, 200)
        self.ip_per_minute = positive_limit("COACH_DEMO_IP_PER_MINUTE", 8, 60)

    async def charge(self, request: Request) -> None:
        now = datetime.now(timezone.utc)
        minute = now.strftime("%Y%m%d%H%M")
        day = now.strftime("%Y%m%d")
        # Never trust an arbitrary client-supplied X-Forwarded-For header.
        # If reverse proxy is not configured to forward a trusted remote IP,
        # this can be a shared proxy address, but the global caps still apply.
        address = request.client.host if request.client else "unknown"
        hashed_address = hashlib.sha256(address.encode("utf-8")).hexdigest()[:22]
        keys = [
            f"{{coach-quota}}:demo:ip:{hashed_address}:minute:{minute}",
            f"{{coach-quota}}:demo:ip:{hashed_address}:day:{day}",
            f"{{coach-quota}}:demo:global:minute:{minute}",
            f"{{coach-quota}}:demo:global:day:{day}",
        ]
        limits = [self.ip_per_minute, self.ip_per_day,
                  self.global_per_minute, self.global_per_day]
        try:
            allowed = await self.redis.eval(
                QUOTA_SCRIPT, len(keys), *keys, *limits,
                120, 172800, 120, 172800,
            )
        except Exception:
            # A broken Redis connection must not bypass the guest quota.
            raise HTTPException(503, "Demo usage protection is temporarily unavailable.") from None
        if allowed != 1:
            raise HTTPException(429, "Judge demo usage limit reached. Try again later.",
                                headers={"Retry-After": "60"})
