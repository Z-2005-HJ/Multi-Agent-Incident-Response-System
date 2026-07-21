from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


if os.getenv("RUN_API_INTEGRATION_TESTS") != "1":
    pytest.skip(
        "API integration tests require an explicitly configured isolated PostgreSQL instance. "
        "Set RUN_API_INTEGRATION_TESTS=1 to run them.",
        allow_module_level=True,
    )


def incident_payload(incident_id: str) -> dict[str, object]:
    logs = (DATA_DIR / "sample_logs" / "checkout_api.log").read_text(encoding="utf-8")
    metrics = json.loads((DATA_DIR / "sample_metrics" / "checkout_api_metrics.json").read_text(encoding="utf-8"))
    return {
        "incident_id": incident_id,
        "service_name": "checkout-api",
        "alert_description": "Service checkout-api error rate increased after deployment.",
        "raw_logs": logs,
        "metrics": metrics,
        "time_window": "2026-06-18T10:20:00Z/2026-06-18T10:30:00Z",
    }


def admin_headers() -> dict[str, str]:
    return {"Authorization": "Bearer admin-token"}


def bootstrap_tenant_key(client: TestClient, tenant_name: str = "Acme") -> tuple[str, str]:
    tenant_response = client.post(
        "/admin/tenants",
        json={
            "tenant_name": tenant_name,
            "request_quota_limit": 10,
            "workflow_quota_limit": 5,
            "quota_window_minutes": 1440,
        },
        headers=admin_headers(),
    )
    assert tenant_response.status_code == 201
    tenant_id = tenant_response.json()["tenant_id"]

    key_response = client.post(
        f"/admin/tenants/{tenant_id}/keys",
        json={"label": "primary"},
        headers=admin_headers(),
    )
    assert key_response.status_code == 201
    api_key = key_response.json()["api_key"]
    return tenant_id, api_key


def test_run_incident_api() -> None:
    with TestClient(app) as client:
        response = client.post("/incidents/run", json=incident_payload("inc_test_api"))

        assert response.status_code == 200
        payload = response.json()
        assert payload["workflow_status"] == "completed"
        assert payload["report"]["human_approval_required"] is True
        assert payload["eval_report"]["agent_scores"]


def test_llm_status_does_not_expose_api_key() -> None:
    with TestClient(app) as client:
        response = client.get("/llm/status")

        assert response.status_code == 200
        payload = response.json()
        assert "api_key" not in payload
        assert payload["mode"] == "mock"
        assert payload["privacy_mode"] == "strict"


def test_ready_api() -> None:
    with TestClient(app) as client:
        response = client.get("/ready")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["database"] == "ok"
        assert payload["database_backend"] == "postgresql"
        assert payload["queue"] in {"disabled", "ok"}


def test_metrics_endpoint_is_accessible() -> None:
    with TestClient(app) as client:
        health_response = client.get("/health")
        assert health_response.status_code == 200

        response = client.get("/metrics")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "incident_response_http_requests_total" in response.text


def test_demo_token_protects_runtime_endpoints(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_API_TOKEN", "demo-token")
    with TestClient(app) as client:
        unauthenticated = client.get("/incidents")
        assert unauthenticated.status_code == 401

        authenticated = client.get("/incidents", headers={"Authorization": "Bearer demo-token"})
        assert authenticated.status_code == 200


def test_feedback_ingest_api(monkeypatch) -> None:
    def fake_ingest(request):
        from app.schemas.incident import StructuredFeedbackDocument

        return StructuredFeedbackDocument(
            feedback_id="fb_test",
            feedback_type="error_log",
            title="Error Log - test-console",
            summary="test summary",
            key_signals=["ERROR checkout-api"],
            suspected_components=["database"],
            sanitized_content="ERROR checkout-api token=<redacted> from <ip>",
            doc_path="docs/feedback/fb_test.md",
            knowledge_source_id="manual_feedback_fb_test",
        )

    monkeypatch.setattr("app.api.routes.ingest_manual_feedback", fake_ingest)
    with TestClient(app) as client:
        response = client.post(
            "/feedback/ingest",
            json={
                "source_name": "test-console",
                "raw_content": "ERROR checkout-api token=secret123 DatabaseConnectionTimeout from 10.1.2.3",
                "note": "test note",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["feedback_type"] == "error_log"
        assert "secret123" not in payload["sanitized_content"]
        assert "<ip>" in payload["sanitized_content"]
        assert payload["knowledge_source_id"].startswith("manual_feedback_")


def test_submit_incident_api_creates_job() -> None:
    class FakeQueue:
        def __init__(self) -> None:
            self.enabled = True
            self.queue_name = "test-jobs"
            self.enqueued: list[str] = []

        async def initialize(self) -> None:
            return None

        async def enqueue(self, job_id: str) -> None:
            self.enqueued.append(job_id)

        async def ready_status(self) -> str:
            return "ok"

        async def close(self) -> None:
            return None

    fake_queue = FakeQueue()
    with TestClient(app) as client:
        client.app.state.job_queue = fake_queue
        response = client.post("/incidents/submit", json=incident_payload("inc_test_submit"))

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "queued"
        assert payload["queue_name"] == "test-jobs"
        assert fake_queue.enqueued == [payload["job_id"]]

        job_response = client.get(f"/jobs/{payload['job_id']}")
        assert job_response.status_code == 200
        assert job_response.json()["status"] == "queued"


def test_history_trace_and_approval_api() -> None:
    with TestClient(app) as client:
        run_response = client.post("/incidents/run", json=incident_payload("inc_test_history"))
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


def test_saas_api_key_quota_and_audit_flow(monkeypatch) -> None:
    monkeypatch.setenv("APP_ADMIN_API_TOKEN", "admin-token")
    monkeypatch.delenv("DEMO_API_TOKEN", raising=False)
    with TestClient(app) as client:
        tenant_id, api_key = bootstrap_tenant_key(client, tenant_name="Quota Tenant")
        tenant_headers = {"X-API-Key": api_key}

        me_response = client.get("/auth/me", headers=tenant_headers)
        assert me_response.status_code == 200
        assert me_response.json()["tenant_id"] == tenant_id

        run_response = client.post("/incidents/run", json=incident_payload("inc_saas_run"), headers=tenant_headers)
        assert run_response.status_code == 200

        quota_response = client.get("/tenant/quota", headers=tenant_headers)
        assert quota_response.status_code == 200
        assert quota_response.json()["requests_used"] >= 1
        assert quota_response.json()["workflows_used"] >= 1

        audit_response = client.get("/tenant/audit-events", headers=tenant_headers)
        assert audit_response.status_code == 200
        assert any(event["event_type"] == "workflow.run" for event in audit_response.json())


def test_tenant_request_quota_is_enforced(monkeypatch) -> None:
    monkeypatch.setenv("APP_ADMIN_API_TOKEN", "admin-token")
    monkeypatch.delenv("DEMO_API_TOKEN", raising=False)
    with TestClient(app) as client:
        tenant_response = client.post(
            "/admin/tenants",
            json={
                "tenant_name": "Limited Tenant",
                "request_quota_limit": 1,
                "workflow_quota_limit": 1,
                "quota_window_minutes": 1440,
            },
            headers=admin_headers(),
        )
        tenant_id = tenant_response.json()["tenant_id"]
        key_response = client.post(
            f"/admin/tenants/{tenant_id}/keys",
            json={"label": "limited", "scopes": ["incident:read"]},
            headers=admin_headers(),
        )
        api_key = key_response.json()["api_key"]
        tenant_headers = {"X-API-Key": api_key}

        first = client.get("/incidents", headers=tenant_headers)
        second = client.get("/incidents", headers=tenant_headers)

        assert first.status_code == 200
        assert second.status_code == 429


def test_production_release_gate_requires_approved_config(monkeypatch) -> None:
    monkeypatch.setenv("APP_ADMIN_API_TOKEN", "admin-token")
    monkeypatch.setenv("APP_OPERATIONS_MODE", "production")
    monkeypatch.delenv("DEMO_API_TOKEN", raising=False)
    with TestClient(app) as client:
        tenant_id, api_key = bootstrap_tenant_key(client, tenant_name="Prod Tenant")
        tenant_headers = {"X-API-Key": api_key}

        denied = client.post("/incidents/run", json=incident_payload("inc_prod_denied"), headers=tenant_headers)
        assert denied.status_code == 403

        approval_response = client.post(
            f"/admin/config-approvals?tenant_id={tenant_id}",
            json={
                "environment": "production",
                "config_scope": "incident-workflow",
                "summary": "Approve production ops mode execution",
                "requested_by": "ops-owner",
                "expires_in_hours": 2,
            },
            headers=admin_headers(),
        )
        assert approval_response.status_code == 201
        approval_id = approval_response.json()["approval_id"]

        approve_response = client.post(
            f"/admin/config-approvals/{approval_id}/approve",
            json={"decided_by": "cab", "note": "Approved for release gate test"},
            headers=admin_headers(),
        )
        assert approve_response.status_code == 200

        allowed = client.post(
            "/incidents/run",
            json=incident_payload("inc_prod_allowed"),
            headers={**tenant_headers, "X-Release-Approval": approval_id},
        )
        assert allowed.status_code == 200


def test_tenant_user_can_login_and_access_rbac_endpoints(monkeypatch) -> None:
    monkeypatch.setenv("APP_ADMIN_API_TOKEN", "admin-token")
    monkeypatch.delenv("DEMO_API_TOKEN", raising=False)
    with TestClient(app) as client:
        tenant_response = client.post(
            "/admin/tenants",
            json={
                "tenant_name": "User Tenant",
                "request_quota_limit": 10,
                "workflow_quota_limit": 5,
                "quota_window_minutes": 1440,
            },
            headers=admin_headers(),
        )
        tenant_id = tenant_response.json()["tenant_id"]

        create_user = client.post(
            f"/admin/tenants/{tenant_id}/users",
            json={
                "email": "admin@tenant.test",
                "full_name": "Tenant Admin",
                "role": "admin",
                "password": "super-secure-password",
            },
            headers=admin_headers(),
        )
        assert create_user.status_code == 201

        login = client.post(
            "/auth/login",
            json={
                "tenant_id": tenant_id,
                "email": "admin@tenant.test",
                "password": "super-secure-password",
            },
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        assert login.json()["auth_context"]["actor_type"] == "user"
        assert login.json()["auth_context"]["role"] == "admin"

        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["email"] == "admin@tenant.test"

        users = client.get("/tenant/users", headers={"Authorization": f"Bearer {token}"})
        assert users.status_code == 200
        assert users.json()[0]["role"] == "admin"


def test_user_logout_revokes_session(monkeypatch) -> None:
    monkeypatch.setenv("APP_ADMIN_API_TOKEN", "admin-token")
    monkeypatch.delenv("DEMO_API_TOKEN", raising=False)
    with TestClient(app) as client:
        tenant_response = client.post(
            "/admin/tenants",
            json={
                "tenant_name": "Logout Tenant",
                "request_quota_limit": 10,
                "workflow_quota_limit": 5,
                "quota_window_minutes": 1440,
            },
            headers=admin_headers(),
        )
        tenant_id = tenant_response.json()["tenant_id"]

        created = client.post(
            f"/admin/tenants/{tenant_id}/users",
            json={
                "email": "operator@tenant.test",
                "full_name": "Tenant Operator",
                "role": "operator",
                "password": "super-secure-password",
            },
            headers=admin_headers(),
        )
        assert created.status_code == 201

        login = client.post(
            "/auth/login",
            json={
                "tenant_id": tenant_id,
                "email": "operator@tenant.test",
                "password": "super-secure-password",
            },
        )
        token = login.json()["access_token"]

        logout = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert logout.status_code == 200

        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 401


def test_tenant_admin_can_manage_users_sessions_and_api_keys(monkeypatch) -> None:
    monkeypatch.setenv("APP_ADMIN_API_TOKEN", "admin-token")
    monkeypatch.delenv("DEMO_API_TOKEN", raising=False)
    with TestClient(app) as client:
        tenant_id, api_key = bootstrap_tenant_key(client, tenant_name="Mgmt Tenant")

        created_user = client.post(
            f"/admin/tenants/{tenant_id}/users",
            json={
                "email": "admin@mgmt.test",
                "full_name": "Management Admin",
                "role": "admin",
                "password": "super-secure-password",
            },
            headers=admin_headers(),
        )
        assert created_user.status_code == 201
        user_id = created_user.json()["user_id"]

        login = client.post(
            "/auth/login",
            json={
                "tenant_id": tenant_id,
                "email": "admin@mgmt.test",
                "password": "super-secure-password",
            },
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {token}"}

        keys = client.get("/tenant/api-keys", headers=user_headers)
        assert keys.status_code == 200
        assert any(item["key_id"] for item in keys.json())

        revoke_key = client.post(
            f"/tenant/api-keys/{keys.json()[0]['key_id']}/revoke",
            headers=user_headers,
        )
        assert revoke_key.status_code == 200
        assert revoke_key.json()["status"] == "revoked"

        sessions = client.get("/tenant/sessions", headers=user_headers)
        assert sessions.status_code == 200
        assert sessions.json()
        session_id = sessions.json()[0]["session_id"]

        revoke_session = client.post(f"/tenant/sessions/{session_id}/revoke", headers=user_headers)
        assert revoke_session.status_code == 200
        assert revoke_session.json()["revoked_at"] is not None

        relogin = client.post(
            "/auth/login",
            json={
                "tenant_id": tenant_id,
                "email": "admin@mgmt.test",
                "password": "super-secure-password",
            },
        )
        assert relogin.status_code == 200
        relogin_headers = {"Authorization": f"Bearer {relogin.json()['access_token']}"}

        updated_role = client.post(
            f"/tenant/users/{user_id}/role",
            json={"role": "approver"},
            headers=relogin_headers,
        )
        assert updated_role.status_code == 200
        assert updated_role.json()["role"] == "approver"

        reset_password = client.post(
            f"/tenant/users/{user_id}/password-reset",
            json={"new_password": "super-secure-password-2"},
            headers=relogin_headers,
        )
        assert reset_password.status_code == 200

        old_login = client.post(
            "/auth/login",
            json={
                "tenant_id": tenant_id,
                "email": "admin@mgmt.test",
                "password": "super-secure-password",
            },
        )
        assert old_login.status_code == 401

        new_login = client.post(
            "/auth/login",
            json={
                "tenant_id": tenant_id,
                "email": "admin@mgmt.test",
                "password": "super-secure-password-2",
            },
        )
        assert new_login.status_code == 200
        new_headers = {"Authorization": f"Bearer {new_login.json()['access_token']}"}

        suspended = client.post(f"/tenant/users/{user_id}/suspend", headers=new_headers)
        assert suspended.status_code == 200
        assert suspended.json()["status"] == "suspended"

        denied_login = client.post(
            "/auth/login",
            json={
                "tenant_id": tenant_id,
                "email": "admin@mgmt.test",
                "password": "super-secure-password-2",
            },
        )
        assert denied_login.status_code == 401


def test_job_human_intervention_can_be_approved(monkeypatch) -> None:
    monkeypatch.setenv("APP_ADMIN_API_TOKEN", "admin-token")
    monkeypatch.delenv("DEMO_API_TOKEN", raising=False)

    class FakeQueue:
        def __init__(self) -> None:
            self.enabled = True
            self.queue_name = "test-jobs"
            self.enqueued: list[str] = []

        async def initialize(self) -> None:
            return None

        async def enqueue(self, job_id: str) -> None:
            self.enqueued.append(job_id)

        async def ready_status(self) -> str:
            return "ok"

        async def close(self) -> None:
            return None

    fake_queue = FakeQueue()
    with TestClient(app) as client:
        client.app.state.job_queue = fake_queue
        tenant_id, api_key = bootstrap_tenant_key(client, tenant_name="HITL Tenant")
        tenant_headers = {"X-API-Key": api_key}

        run_response = client.post("/incidents/run", json=incident_payload("inc_hitl"), headers=tenant_headers)
        assert run_response.status_code == 200
        run_payload = run_response.json()

        submit_response = client.post("/incidents/submit", json=incident_payload("inc_hitl"), headers=tenant_headers)
        assert submit_response.status_code == 202
        job_id = submit_response.json()["job_id"]

        store = client.app.state.incident_store
        awaitable = store.mark_job_awaiting_human(
            job_id,
            trace_id=run_payload["trace_id"],
            run_id="inc_hitl",
            current_node="final_report",
            completed_nodes=["ingest_incident", "evidence_analysis", "knowledge_retrieval", "root_cause_analysis", "fix_planning", "review", "final_report", "eval_report"],
            checkpoint_id="ckpt_test_hitl",
            checkpoint={"incident_id": "inc_hitl"},
            human_action_required={"kind": "approval_required", "node_name": "final_report"},
        )
        import asyncio

        asyncio.run(awaitable)

        approve_response = client.post(
            f"/jobs/{job_id}/resume",
            json={"action": "approve", "approved_by": "ops-lead", "note": "Looks safe to proceed."},
            headers=tenant_headers,
        )
        assert approve_response.status_code == 200
        assert approve_response.json()["status"] == "completed"
        assert fake_queue.enqueued == [job_id]


def test_failed_job_can_be_recovered_and_requeued(monkeypatch) -> None:
    monkeypatch.setenv("APP_ADMIN_API_TOKEN", "admin-token")
    monkeypatch.delenv("DEMO_API_TOKEN", raising=False)

    class FakeQueue:
        def __init__(self) -> None:
            self.enabled = True
            self.queue_name = "test-jobs"
            self.enqueued: list[str] = []

        async def initialize(self) -> None:
            return None

        async def enqueue(self, job_id: str) -> None:
            self.enqueued.append(job_id)

        async def ready_status(self) -> str:
            return "ok"

        async def close(self) -> None:
            return None

    fake_queue = FakeQueue()
    with TestClient(app) as client:
        client.app.state.job_queue = fake_queue
        tenant_id, api_key = bootstrap_tenant_key(client, tenant_name="Recover Tenant")
        tenant_headers = {"X-API-Key": api_key}

        submit_response = client.post("/incidents/submit", json=incident_payload("inc_recover"), headers=tenant_headers)
        assert submit_response.status_code == 202
        job_id = submit_response.json()["job_id"]

        store = client.app.state.incident_store
        import asyncio

        asyncio.run(
            store.save_job_checkpoint(
                job_id,
                current_node="knowledge_retrieval",
                completed_nodes=["ingest_incident", "evidence_analysis"],
                checkpoint_id="ckpt_recover",
                checkpoint={"incident_id": "inc_recover", "completed_nodes": ["ingest_incident"]},
            )
        )
        asyncio.run(
            store.mark_job_failed(
                job_id,
                last_error="TimeoutError: knowledge retrieval timed out",
                last_error_category="timeout",
            )
        )

        recover_response = client.post(
            f"/jobs/{job_id}/resume",
            json={"action": "recover", "approved_by": "ops-lead", "note": "Retry from last checkpoint."},
            headers=tenant_headers,
        )
        assert recover_response.status_code == 200
        assert recover_response.json()["status"] == "recovering"
        assert fake_queue.enqueued == [job_id, job_id]
