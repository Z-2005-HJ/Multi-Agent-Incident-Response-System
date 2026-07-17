from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.graph.workflow import run_incident_workflow
from app.job_queue import RedisJobQueue
from app.observability import record_workflow_job, record_workflow_job_retry
from app.runtime import get_runtime_settings
from app.storage import IncidentStore


logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def process_job(job_id: str, store: IncidentStore, queue: RedisJobQueue) -> None:
    settings = get_runtime_settings()
    started_at = time.perf_counter()
    job = await store.get_job(job_id)
    if job is None:
        logger.warning("Skipping unknown job %s", job_id)
        return
    if job.status in {"completed", "dead_letter", "awaiting_human"}:
        logger.info("Skipping terminal job %s with status %s", job_id, job.status)
        return

    request = await store.get_job_request(job_id)
    checkpoint = await store.get_job_checkpoint(job_id)
    if request is None:
        await store.mark_job_failed(job_id, last_error="missing request payload")
        await queue.push_dead_letter(job_id)
        record_workflow_job("failed", time.perf_counter() - started_at)
        record_workflow_job_retry("invalid_payload")
        return

    lock_token = uuid4().hex
    if not await queue.acquire_run_lock(request.incident_id, lock_token):
        next_retry_at = _utc_now() + timedelta(seconds=settings.job_retry_delay_seconds)
        await store.mark_job_retry_scheduled(
            job_id,
            next_retry_at=next_retry_at,
            last_error="run lock unavailable for incident",
        )
        await queue.schedule_retry(job_id, next_retry_at)
        record_workflow_job_retry("run_lock_retry")
        return

    try:
        current_job = await store.mark_job_running(job_id)
        if current_job is None:
            return

        result = await asyncio.to_thread(run_incident_workflow, request, checkpoint)
        await store.save_run(result, tenant_id=current_job.tenant_id)
        runtime = result.metadata.get("runtime", {})
        current_node = runtime.get("current_node")
        completed_nodes = list(runtime.get("completed_nodes", []))
        checkpoint_id = runtime.get("checkpoint_id")
        resume_state = runtime.get("resume_state")
        pending_human_input = runtime.get("pending_human_input")
        if pending_human_input:
            await store.mark_job_awaiting_human(
                job_id,
                trace_id=result.trace_id,
                run_id=result.incident_id,
                current_node=current_node,
                completed_nodes=completed_nodes,
                checkpoint_id=checkpoint_id,
                checkpoint=resume_state if isinstance(resume_state, dict) else None,
                human_action_required=pending_human_input,
            )
            record_workflow_job("awaiting_human", time.perf_counter() - started_at)
            return
        if result.workflow_status == "failed":
            error_text = str(runtime.get("last_error", "workflow failed"))
            error_category = runtime.get("last_error_category")
            if current_job.attempts < current_job.max_retries:
                next_retry_at = _utc_now() + timedelta(seconds=settings.job_retry_delay_seconds * max(1, current_job.attempts))
                await store.save_job_checkpoint(
                    job_id,
                    current_node=current_node,
                    completed_nodes=completed_nodes,
                    checkpoint_id=checkpoint_id,
                    checkpoint=resume_state if isinstance(resume_state, dict) else {},
                    trace_id=result.trace_id,
                    run_id=result.incident_id,
                )
                await store.mark_job_retry_scheduled(
                    job_id,
                    next_retry_at=next_retry_at,
                    last_error=error_text,
                    last_error_category=error_category,
                )
                await queue.schedule_retry(job_id, next_retry_at)
                record_workflow_job_retry("runtime_recover_retry")
                return
            await store.mark_job_dead_letter(
                job_id,
                last_error=error_text,
                last_error_category=error_category,
                dead_letter_reason="recoverable runtime failed after max retries",
            )
            await queue.push_dead_letter(job_id)
            record_workflow_job("dead_letter", time.perf_counter() - started_at)
            record_workflow_job_retry("runtime_dead_letter")
            return

        await store.mark_job_completed(
            job_id,
            trace_id=result.trace_id,
            run_id=result.incident_id,
            current_node=current_node,
            completed_nodes=completed_nodes,
            checkpoint_id=checkpoint_id,
        )
        record_workflow_job("completed", time.perf_counter() - started_at)
    except Exception as exc:
        current_job = await store.get_job(job_id)
        attempts = current_job.attempts if current_job is not None else 1
        error_text = f"{type(exc).__name__}: {exc}"
        error_category = "worker_runtime_error"
        if current_job is not None and attempts < current_job.max_retries:
            next_retry_at = _utc_now() + timedelta(seconds=settings.job_retry_delay_seconds * attempts)
            await store.mark_job_retry_scheduled(
                job_id,
                next_retry_at=next_retry_at,
                last_error=error_text,
                last_error_category=error_category,
            )
            await queue.schedule_retry(job_id, next_retry_at)
            record_workflow_job_retry("retry_scheduled")
            logger.warning("Scheduled retry %s for job %s", attempts, job_id)
        else:
            await store.mark_job_dead_letter(
                job_id,
                last_error=error_text,
                last_error_category=error_category,
                dead_letter_reason="max retries exhausted",
            )
            await queue.push_dead_letter(job_id)
            record_workflow_job("dead_letter", time.perf_counter() - started_at)
            record_workflow_job_retry("dead_letter")
            logger.exception("Job %s moved to dead letter queue", job_id)
    finally:
        await queue.release_run_lock(request.incident_id, lock_token)


async def run_worker() -> None:
    settings = get_runtime_settings()
    store = IncidentStore(settings.database_url)
    queue = RedisJobQueue(settings.redis_url)

    if not queue.enabled:
        raise RuntimeError("APP_REDIS_URL is required to start the worker.")

    await store.initialize()
    await queue.initialize()
    logger.info("Worker started. queue=%s delayed=%s dlq=%s", queue.queue_name, queue.delayed_queue_name, queue.dead_letter_queue_name)

    try:
        while True:
            job_id = await queue.pop_next_job()
            if not job_id:
                continue
            await process_job(job_id, store, queue)
    finally:
        await queue.close()
        await store.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
