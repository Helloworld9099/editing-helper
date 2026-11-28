"""Atomic, fail-closed usage protection for the anonymous demo."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from quota_limits import QUOTA_SCRIPT, positive_limit


class DemoAccess:
    """Bound public usage across replicas and restarts; IPs are not identities."""

    def __init__(self, redis_store):
        if redis_store is None:
            raise ValueError("COACH_REDIS_URL is required in demo mode.")
        if not os.environ.get("COACH_DEMO_GLOBAL_PER_DAY", "").strip():
            raise ValueError("COACH_DEMO_GLOBAL_PER_DAY must be explicitly set in demo mode.")
        self.redis = redis_store
        enabled = os.environ.get("COACH_DEMO_ENABLED", "1").strip()
        if enabled not in {"0", "1"}:
            raise ValueError("COACH_DEMO_ENABLED must be 0 or 1.")
        self.enabled = enabled == "1"
        self.global_per_day = positive_limit("COACH_DEMO_GLOBAL_PER_DAY", 100, 1000)
        self.global_per_minute = positive_limit("COACH_DEMO_GLOBAL_PER_MINUTE", 20, 120)
        self.ip_per_day = positive_limit("COACH_DEMO_IP_PER_DAY", 60, 200)
        self.ip_per_minute = positive_limit("COACH_DEMO_IP_PER_MINUTE", 8, 60)
        self.upload_global_per_minute = positive_limit("COACH_UPLOAD_GLOBAL_PER_MINUTE", 8, 60)
        self.upload_global_per_day = positive_limit("COACH_UPLOAD_GLOBAL_PER_DAY", 60, 1000)
        self.upload_ip_per_minute = positive_limit("COACH_UPLOAD_IP_PER_MINUTE", 4, 30)
        self.upload_ip_per_day = positive_limit("COACH_UPLOAD_IP_PER_DAY", 30, 200)

    @staticmethod
    def address_key(request):
        # Use only the server-observed address. Proxy configuration must trust
        # only the real ingress; never accept arbitrary forwarded IPs.
        address = request.client.host if request.client else "unknown"
        return hashlib.sha256(address.encode("utf-8")).hexdigest()[:22]

    async def reserve(self, keys, limits, expiries, weights, label, *, check_only=False):
        if not self.enabled:
            raise HTTPException(503, "The public demo is temporarily disabled.")
        try:
            allowed = await self.redis.eval(
                QUOTA_SCRIPT, len(keys), *keys, *limits, *expiries, *weights, int(check_only),
            )
        except Exception:
            raise HTTPException(503, "Demo usage protection is temporarily unavailable.") from None
        if allowed != 1:
            raise HTTPException(429, f"{label} usage limit reached. Try again later.",
                                headers={"Retry-After": "60"})

    async def charge(self, request: Request, video_quota=None, *, check_only=False):
        now = datetime.now(timezone.utc)
        minute, day = now.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d")
        address = self.address_key(request)
        keys = [
            f"{{coach-quota}}:demo:ip:{address}:minute:{minute}",
            f"{{coach-quota}}:demo:ip:{address}:day:{day}",
            f"{{coach-quota}}:demo:global:minute:{minute}",
            f"{{coach-quota}}:demo:global:day:{day}",
        ]
        limits = [self.ip_per_minute, self.ip_per_day, self.global_per_minute, self.global_per_day]
        expiries = [120, 172800, 120, 172800]
        # Reserve both model calls for a clip before starting either. Video
        # counters still count analyses, not individual calls. No refunds:
        # a failed upstream call may still have incurred provider usage.
        weights = [2 if video_quota is not None else 1] * 4
        if video_quota is not None:
            keys.extend(video_quota.keys(now))
            limits.extend(video_quota.limits)
            expiries.extend([120, 172800])
            weights.extend([1, 1])
        await self.reserve(keys, limits, expiries, weights,
                           "Video analysis or demo" if video_quota is not None else "Public demo",
                           check_only=check_only)

    async def admit_video_upload(self, request: Request, video_quota):
        """Rate-limit all upload attempts, then check budget without charging AI."""
        now = datetime.now(timezone.utc)
        minute, day = now.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d")
        address = self.address_key(request)
        keys = [
            f"{{coach-quota}}:upload:ip:{address}:minute:{minute}",
            f"{{coach-quota}}:upload:ip:{address}:day:{day}",
            f"{{coach-quota}}:upload:global:minute:{minute}",
            f"{{coach-quota}}:upload:global:day:{day}",
        ]
        limits = [self.upload_ip_per_minute, self.upload_ip_per_day,
                  self.upload_global_per_minute, self.upload_global_per_day]
        await self.reserve(keys, limits, [120, 172800, 120, 172800], [1] * 4, "Video upload")
        await self.charge(request, video_quota, check_only=True)
