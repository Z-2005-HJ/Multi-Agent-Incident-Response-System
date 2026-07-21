from __future__ import annotations

from datetime import datetime, timezone

from redis.asyncio import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.runtime import get_runtime_settings


def _utc_timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


class RedisJobQueue:
    def __init__(self, redis_url: str | None = None) -> None:
        settings = get_runtime_settings()
        self.redis_url = redis_url or settings.redis_url
        self.queue_name = settings.queue_name
        self.delayed_queue_name = settings.delayed_queue_name
        self.dead_letter_queue_name = settings.dead_letter_queue_name
        self.run_lock_prefix = settings.run_lock_prefix
        self.run_lock_ttl_seconds = settings.run_lock_ttl_seconds
        self.worker_poll_seconds = settings.worker_poll_seconds
        self._redis: Redis | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.redis_url)

    async def initialize(self) -> None:
        if not self.enabled or self._redis is not None:
            return
        self._redis = Redis.from_url(self.redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._redis is None:
            return
        await self._redis.aclose()
        self._redis = None

    async def ready_status(self) -> str:
        if not self.enabled:
            return "disabled"
        redis = await self._ensure_client()
        await redis.ping()
        return "ok"

    async def enqueue(self, job_id: str) -> None:
        redis = await self._ensure_client()
        await redis.rpush(self.queue_name, job_id)

    async def schedule_retry(self, job_id: str, available_at: datetime) -> None:
        redis = await self._ensure_client()
        await redis.zadd(self.delayed_queue_name, {job_id: _utc_timestamp(available_at)})

    async def promote_due_jobs(self) -> int:
        if not self.enabled:
            return 0
        redis = await self._ensure_client()
        now = datetime.now(timezone.utc).timestamp()
        promoted = 0
        while True:
            items = await redis.zpopmin(self.delayed_queue_name, 1)
            if not items:
                return promoted
            job_id, score = items[0]
            if float(score) > now:
                await redis.zadd(self.delayed_queue_name, {job_id: float(score)})
                return promoted
            await redis.rpush(self.queue_name, job_id)
            promoted += 1

    async def pop_next_job(self) -> str | None:
        if not self.enabled:
            return None
        await self.promote_due_jobs()
        redis = await self._ensure_client()
        timeout = max(1, int(self.worker_poll_seconds))
        try:
            result = await redis.blpop(self.queue_name, timeout=timeout)
        except RedisTimeoutError:
            # redis-py 8 raises on an empty blocking pop instead of returning None.
            return None
        if not result:
            return None
        _, job_id = result
        return str(job_id)

    async def push_dead_letter(self, job_id: str) -> None:
        redis = await self._ensure_client()
        await redis.rpush(self.dead_letter_queue_name, job_id)

    async def acquire_run_lock(self, incident_id: str, token: str) -> bool:
        redis = await self._ensure_client()
        return bool(
            await redis.set(
                self._lock_key(incident_id),
                token,
                ex=self.run_lock_ttl_seconds,
                nx=True,
            )
        )

    async def release_run_lock(self, incident_id: str, token: str) -> None:
        if not self.enabled:
            return
        redis = await self._ensure_client()
        lock_key = self._lock_key(incident_id)
        current_token = await redis.get(lock_key)
        if current_token == token:
            await redis.delete(lock_key)

    async def _ensure_client(self) -> Redis:
        await self.initialize()
        if self._redis is None:
            raise RuntimeError("Redis job queue is not configured.")
        return self._redis

    def _lock_key(self, incident_id: str) -> str:
        return f"{self.run_lock_prefix}:{incident_id}"
