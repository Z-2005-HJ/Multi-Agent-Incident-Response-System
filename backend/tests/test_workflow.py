from __future__ import annotations

import json
from pathlib import Path

import app.graph.workflow as workflow_module
from app.graph.workflow import WorkflowNodeSpec, run_incident_workflow
from app.schemas.incident import IncidentRequest


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def sample_request() -> IncidentRequest:
    logs = (DATA_DIR / "sample_logs" / "checkout_api.log").read_text(encoding="utf-8")
    metrics = json.loads((DATA_DIR / "sample_metrics" / "checkout_api_metrics.json").read_text(encoding="utf-8"))
    return IncidentRequest(
        incident_id="inc_test_checkout_api",
        service_name="checkout-api",
        alert_description="Service checkout-api error rate increased from 0.5% to 12% after deployment.",
        raw_logs=logs,
        metrics=metrics,
        time_window="2026-06-18T10:20:00Z/2026-06-18T10:30:00Z",
    )


def test_workflow_generates_report_with_evidence() -> None:
    result = run_incident_workflow(sample_request())

    assert result.workflow_status == "completed"
    assert result.report.service_name == "checkout-api"
    assert result.report.root_causes
    assert result.report.root_causes[0].evidence
    assert result.report.sources
    assert "Incident Report" in result.markdown_report


def test_high_risk_fix_requires_human_approval() -> None:
    result = run_incident_workflow(sample_request())

    assert result.report.human_approval_required is True
    assert result.eval_report.risks


def test_trace_contains_all_core_nodes() -> None:
    result = run_incident_workflow(sample_request())
    node_names = {event.node_name for event in result.trace_events if event.event_type == "node_end"}

    assert {
        "ingest_incident",
        "log_analysis",
        "metric_analysis",
        "deployment_analysis",
        "knowledge_retrieval",
        "root_cause_analysis",
        "fix_planning",
        "review",
        "final_report",
        "eval_report",
    }.issubset(node_names)


def test_workflow_includes_standardized_evidence_context() -> None:
    result = run_incident_workflow(sample_request())

    assert result.evidence_context is not None
    assert result.evidence_context.metric_findings
    assert result.evidence_context.log_evidence_hits
    assert result.evidence_context.deployment_events
    assert "evidence_metrics_metrics_window" in result.report.sources
    assert result.evidence_context.evidence_sources["metrics"] == "metrics_window"
    assert result.eval_report.agent_scores["standardized_evidence"]["metric_findings"] >= 1


def test_knowledge_agent_reports_retrieval_mode() -> None:
    result = run_incident_workflow(sample_request())

    assert result.eval_report.agent_scores["knowledge_agent"]["retrieval_mode"] in {
        "chroma_vector",
        "keyword_fallback",
    }
    assert result.metadata["standardized_evidence"]["log_evidence_hits"] >= 1


def test_llm_execution_metadata_is_reported() -> None:
    result = run_incident_workflow(sample_request())
    execution = result.metadata["agent_execution"]

    assert execution["root_cause_agent"]["execution_mode"] == "rule_fallback"
    assert execution["fix_planner"]["execution_mode"] == "rule_fallback"
    assert execution["reviewer"]["execution_mode"] == "rule_fallback"
    assert result.eval_report.agent_scores["root_cause_agent"]["execution_mode"] == "rule_fallback"
    assert result.eval_report.agent_scores["root_cause_agent"]["privacy_mode"] == "strict"
    assert "prompt_version" in result.eval_report.agent_scores["root_cause_agent"]


def test_workflow_runtime_metadata_contains_checkpoint_and_human_handoff() -> None:
    result = run_incident_workflow(sample_request())
    runtime = result.metadata["runtime"]

    assert runtime["checkpoint_id"].startswith("ckpt_")
    assert runtime["completed_nodes"][-1] == "eval_report"
    assert runtime["pending_human_input"]["kind"] == "approval_required"
    assert runtime["resume_state"]["trace_id"] == result.trace_id


def test_workflow_failure_is_classified_and_recoverable(monkeypatch) -> None:
    original_nodes = workflow_module.WORKFLOW_NODES

    def flaky_knowledge(_state):
        raise TimeoutError("knowledge retrieval timed out")

    monkeypatch.setattr(
        workflow_module,
        "WORKFLOW_NODES",
        [
            *original_nodes[:4],
            WorkflowNodeSpec("knowledge_retrieval", "knowledge_agent", flaky_knowledge, max_retries=1),
            *original_nodes[5:],
        ],
    )

    result = run_incident_workflow(sample_request())
    runtime = result.metadata["runtime"]
    error_events = [event for event in result.trace_events if event.event_type == "error"]

    assert result.workflow_status == "failed"
    assert runtime["failure_node"] == "knowledge_retrieval"
    assert runtime["last_error_category"] == "timeout"
    assert runtime["recoverable"] is True
    assert error_events[-1].retryable is True
    assert error_events[-1].attempt == 2
