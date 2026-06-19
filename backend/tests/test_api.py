from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_run_incident_api() -> None:
    client = TestClient(app)
    logs = (DATA_DIR / "sample_logs" / "checkout_api.log").read_text(encoding="utf-8")
    metrics = json.loads((DATA_DIR / "sample_metrics" / "checkout_api_metrics.json").read_text(encoding="utf-8"))

    response = client.post(
        "/incidents/run",
        json={
            "incident_id": "inc_test_api",
            "service_name": "checkout-api",
            "alert_description": "Service checkout-api error rate increased after deployment.",
            "raw_logs": logs,
            "metrics": metrics,
            "time_window": "2026-06-18T10:20:00Z/2026-06-18T10:30:00Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow_status"] == "completed"
    assert payload["report"]["human_approval_required"] is True
    assert payload["eval_report"]["agent_scores"]


def test_llm_status_does_not_expose_api_key() -> None:
    client = TestClient(app)

    response = client.get("/llm/status")

    assert response.status_code == 200
    payload = response.json()
    assert "api_key" not in payload
    assert payload["mode"] == "mock"
    assert payload["privacy_mode"] == "strict"


def test_history_trace_and_approval_api() -> None:
    client = TestClient(app)
    logs = (DATA_DIR / "sample_logs" / "checkout_api.log").read_text(encoding="utf-8")
    metrics = json.loads((DATA_DIR / "sample_metrics" / "checkout_api_metrics.json").read_text(encoding="utf-8"))

    run_response = client.post(
        "/incidents/run",
        json={
            "incident_id": "inc_test_history",
            "service_name": "checkout-api",
            "alert_description": "Service checkout-api error rate increased after deployment.",
            "raw_logs": logs,
            "metrics": metrics,
        },
    )
    assert run_response.status_code == 200

    list_response = client.get("/incidents")
    assert list_response.status_code == 200
    assert any(item["incident_id"] == "inc_test_history" for item in list_response.json())

    detail_response = client.get("/incidents/inc_test_history")
    assert detail_response.status_code == 200
    assert detail_response.json()["incident_id"] == "inc_test_history"

    trace_response = client.get("/incidents/inc_test_history/trace")
    assert trace_response.status_code == 200
    assert trace_response.json()

    approve_response = client.post(
        "/incidents/inc_test_history/approve",
        json={"approved_by": "tester", "note": "Demo approval."},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["approval_status"] == "approved"

    reject_response = client.post(
        "/incidents/inc_test_history/reject",
        json={"approved_by": "tester", "note": "Demo rejection."},
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["approval_status"] == "rejected"
