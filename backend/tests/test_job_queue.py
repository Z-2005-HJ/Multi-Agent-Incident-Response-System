from __future__ import annotations

import asyncio

from redis.exceptions import TimeoutError as RedisTimeoutError

from app.job_queue import RedisJobQueue


class EmptyBlockingRedis:
    async def blpop(self, _queue_name: str, timeout: int):
        assert timeout >= 1
        raise RedisTimeoutError("empty queue")


def test_empty_blocking_pop_keeps_worker_alive(monkeypatch) -> None:
    queue = RedisJobQueue("redis://localhost:6379/0")
    queue._redis = EmptyBlockingRedis()  # type: ignore[assignment]

    async def no_due_jobs() -> int:
        return 0

    monkeypatch.setattr(queue, "promote_due_jobs", no_due_jobs)

    assert asyncio.run(queue.pop_next_job()) is None
