from __future__ import annotations

import json
from pathlib import Path

from app.graph.workflow import run_incident_workflow
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
        "external_tools",
        "knowledge_retrieval",
        "root_cause_analysis",
        "fix_planning",
        "review",
        "final_report",
        "eval_report",
    }.issubset(node_names)


def test_workflow_includes_external_tool_context() -> None:
    result = run_incident_workflow(sample_request())

    assert result.tool_context is not None
    assert result.tool_context.prometheus_findings
    assert result.tool_context.log_search_hits
    assert result.tool_context.deployment_events
    assert "prometheus_mock" in result.report.sources
    assert result.eval_report.agent_scores["tool_adapter"]["prometheus_findings"] >= 1


def test_knowledge_agent_reports_retrieval_mode() -> None:
    result = run_incident_workflow(sample_request())

    assert result.eval_report.agent_scores["knowledge_agent"]["retrieval_mode"] in {
        "chroma_vector",
        "keyword_fallback",
    }
    assert result.metadata["external_tools"]["log_search_hits"] >= 1


def test_llm_execution_metadata_is_reported() -> None:
    result = run_incident_workflow(sample_request())
    execution = result.metadata["agent_execution"]

    assert execution["root_cause_agent"]["execution_mode"] == "rule_fallback"
    assert execution["fix_planner"]["execution_mode"] == "rule_fallback"
    assert execution["reviewer"]["execution_mode"] == "rule_fallback"
    assert result.eval_report.agent_scores["root_cause_agent"]["execution_mode"] == "rule_fallback"
    assert result.eval_report.agent_scores["root_cause_agent"]["privacy_mode"] == "strict"
    assert "prompt_version" in result.eval_report.agent_scores["root_cause_agent"]
