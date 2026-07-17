from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.job_worker import process_job


class FakeStore:
    def __init__(self, *, job, request, checkpoint=None) -> None:
        self.job = job
        self.request = request
        self.checkpoint = checkpoint
        self.failed_calls: list[dict] = []
        self.retry_calls: list[dict] = []
        self.checkpoint_calls: list[dict] = []
        self.dead_letter_calls: list[dict] = []
        self.completed_calls: list[dict] = []
        self.awaiting_human_calls: list[dict] = []
        self.saved_runs: list[tuple[object, str | None]] = []

    async def get_job(self, _job_id: str):
        return self.job

    async def get_job_request(self, _job_id: str):
        return self.request

    async def get_job_checkpoint(self, _job_id: str):
        return self.checkpoint

    async def mark_job_failed(self, job_id: str, **kwargs):
        self.failed_calls.append({"job_id": job_id, **kwargs})

    async def mark_job_retry_scheduled(self, job_id: str, **kwargs):
        self.retry_calls.append({"job_id": job_id, **kwargs})

    async def mark_job_running(self, _job_id: str):
        return self.job

    async def save_run(self, result, tenant_id: str | None = None):
        self.saved_runs.append((result, tenant_id))

    async def save_job_checkpoint(self, job_id: str, **kwargs):
        self.checkpoint_calls.append({"job_id": job_id, **kwargs})

    async def mark_job_dead_letter(self, job_id: str, **kwargs):
        self.dead_letter_calls.append({"job_id": job_id, **kwargs})

    async def mark_job_completed(self, job_id: str, **kwargs):
        self.completed_calls.append({"job_id": job_id, **kwargs})

    async def mark_job_awaiting_human(self, job_id: str, **kwargs):
        self.awaiting_human_calls.append({"job_id": job_id, **kwargs})


class FakeQueue:
    def __init__(self, *, lock_available: bool = True) -> None:
        self.lock_available = lock_available
        self.dead_letters: list[str] = []
        self.scheduled: list[tuple[str, object]] = []
        self.released: list[tuple[str, str]] = []

    async def push_dead_letter(self, job_id: str) -> None:
        self.dead_letters.append(job_id)

    async def schedule_retry(self, job_id: str, available_at) -> None:
        self.scheduled.append((job_id, available_at))

    async def acquire_run_lock(self, incident_id: str, token: str) -> bool:
        self.last_lock = (incident_id, token)
        return self.lock_available

    async def release_run_lock(self, incident_id: str, token: str) -> None:
        self.released.append((incident_id, token))


def test_missing_job_payload_moves_job_to_dead_letter(monkeypatch) -> None:
    store = FakeStore(
        job=SimpleNamespace(status="queued", attempts=0, max_retries=3, tenant_id="tenant-1"),
        request=None,
    )
    queue = FakeQueue()
    monkeypatch.setattr(
        "app.job_worker.get_runtime_settings",
        lambda: SimpleNamespace(job_retry_delay_seconds=30),
    )

    asyncio.run(process_job("job-missing", store, queue))

    assert store.failed_calls[0]["job_id"] == "job-missing"
    assert store.failed_calls[0]["last_error"] == "missing request payload"
    assert queue.dead_letters == ["job-missing"]


def test_run_lock_unavailable_schedules_retry(monkeypatch) -> None:
    request = SimpleNamespace(incident_id="inc-lock")
    store = FakeStore(
        job=SimpleNamespace(status="queued", attempts=0, max_retries=3, tenant_id="tenant-1"),
        request=request,
    )
    queue = FakeQueue(lock_available=False)
    monkeypatch.setattr(
        "app.job_worker.get_runtime_settings",
        lambda: SimpleNamespace(job_retry_delay_seconds=30),
    )

    asyncio.run(process_job("job-lock", store, queue))

    assert store.retry_calls[0]["job_id"] == "job-lock"
    assert "run lock unavailable" in store.retry_calls[0]["last_error"]
    assert queue.scheduled[0][0] == "job-lock"
    assert queue.released == []


def test_workflow_result_waiting_for_human_is_persisted(monkeypatch) -> None:
    request = SimpleNamespace(incident_id="inc-human")
    store = FakeStore(
        job=SimpleNamespace(status="queued", attempts=1, max_retries=3, tenant_id="tenant-1"),
        request=request,
        checkpoint={"incident_id": "inc-human"},
    )
    queue = FakeQueue()
    result = SimpleNamespace(
        trace_id="trace-human",
        incident_id="inc-human",
        workflow_status="completed",
        metadata={
            "runtime": {
                "current_node": "final_report",
                "completed_nodes": ["ingest_incident", "final_report"],
                "checkpoint_id": "ckpt-human",
                "resume_state": {"incident_id": "inc-human"},
                "pending_human_input": {"kind": "approval_required", "node_name": "final_report"},
            }
        },
    )
    monkeypatch.setattr(
        "app.job_worker.get_runtime_settings",
        lambda: SimpleNamespace(job_retry_delay_seconds=30),
    )
    monkeypatch.setattr("app.job_worker.run_incident_workflow", lambda req, checkpoint: result)

    asyncio.run(process_job("job-human", store, queue))

    assert store.saved_runs[0][0] is result
    assert store.awaiting_human_calls[0]["job_id"] == "job-human"
    assert store.awaiting_human_calls[0]["trace_id"] == "trace-human"
    assert queue.released


def test_failed_workflow_is_checkpointed_and_retried(monkeypatch) -> None:
    request = SimpleNamespace(incident_id="inc-retry")
    store = FakeStore(
        job=SimpleNamespace(status="queued", attempts=1, max_retries=3, tenant_id="tenant-1"),
        request=request,
        checkpoint={"incident_id": "inc-retry"},
    )
    queue = FakeQueue()
    result = SimpleNamespace(
        trace_id="trace-retry",
        incident_id="inc-retry",
        workflow_status="failed",
        metadata={
            "runtime": {
                "current_node": "knowledge_retrieval",
                "completed_nodes": ["ingest_incident", "log_analysis"],
                "checkpoint_id": "ckpt-retry",
                "resume_state": {"incident_id": "inc-retry", "current_node": "knowledge_retrieval"},
                "last_error": "TimeoutError: dependency timed out",
                "last_error_category": "timeout",
            }
        },
    )
    monkeypatch.setattr(
        "app.job_worker.get_runtime_settings",
        lambda: SimpleNamespace(job_retry_delay_seconds=30),
    )
    monkeypatch.setattr("app.job_worker.run_incident_workflow", lambda req, checkpoint: result)

    asyncio.run(process_job("job-retry", store, queue))

    assert store.checkpoint_calls[0]["job_id"] == "job-retry"
    assert store.retry_calls[0]["last_error_category"] == "timeout"
    assert queue.scheduled[0][0] == "job-retry"
    assert not store.dead_letter_calls


def test_successful_workflow_marks_job_completed(monkeypatch) -> None:
    request = SimpleNamespace(incident_id="inc-success")
    store = FakeStore(
        job=SimpleNamespace(status="queued", attempts=1, max_retries=3, tenant_id="tenant-1"),
        request=request,
    )
    queue = FakeQueue()
    result = SimpleNamespace(
        trace_id="trace-success",
        incident_id="inc-success",
        workflow_status="completed",
        metadata={
            "runtime": {
                "current_node": "eval_report",
                "completed_nodes": ["ingest_incident", "eval_report"],
                "checkpoint_id": "ckpt-success",
                "resume_state": {"incident_id": "inc-success"},
                "pending_human_input": None,
            }
        },
    )
    monkeypatch.setattr(
        "app.job_worker.get_runtime_settings",
        lambda: SimpleNamespace(job_retry_delay_seconds=30),
    )
    monkeypatch.setattr("app.job_worker.run_incident_workflow", lambda req, checkpoint: result)

    asyncio.run(process_job("job-success", store, queue))

    assert store.completed_calls[0]["job_id"] == "job-success"
    assert store.completed_calls[0]["trace_id"] == "trace-success"
    assert queue.released
