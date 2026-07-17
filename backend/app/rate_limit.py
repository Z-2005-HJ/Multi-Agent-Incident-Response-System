from __future__ import annotations

import hashlib
import time
from collections.abc import MutableMapping

from redis.asyncio import Redis

from app.runtime import get_runtime_settings


class RateLimiter:
    def __init__(self, redis_url: str | None = None) -> None:
        settings = get_runtime_settings()
        self.redis_url = redis_url or settings.redis_url
        self._redis: Redis | None = None
        self._memory_windows: MutableMapping[str, tuple[int, float]] = {}

    async def initialize(self) -> None:
        if self.redis_url and self._redis is None:
            self._redis = Redis.from_url(self.redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._redis is None:
            return
        await self._redis.aclose()
        self._redis = None

    async def hit(self, *, scope: str, subject: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        safe_limit = max(1, int(limit))
        safe_window = max(1, int(window_seconds))
        key = self._key(scope, subject)
        if self._redis is not None:
            return await self._hit_redis(key, safe_limit, safe_window)
        return self._hit_memory(key, safe_limit, safe_window)

    async def _hit_redis(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        assert self._redis is not None
        current = await self._redis.incr(key)
        ttl = await self._redis.ttl(key)
        if current == 1 or ttl < 0:
            await self._redis.expire(key, window_seconds)
            ttl = window_seconds
        return current <= limit, max(int(ttl), 1)

    def _hit_memory(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        count, reset_at = self._memory_windows.get(key, (0, now + window_seconds))
        if now >= reset_at:
            count = 0
            reset_at = now + window_seconds
        count += 1
        self._memory_windows[key] = (count, reset_at)
        retry_after = max(int(reset_at - now), 1)
        return count <= limit, retry_after

    def _key(self, scope: str, subject: str) -> str:
        digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        return f"incident-response:ratelimit:{scope}:{digest}"
