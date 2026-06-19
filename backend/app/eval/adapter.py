from __future__ import annotations

import time
from typing import Any, Callable

from pydantic import BaseModel

from app.graph.state import IncidentState
from app.schemas.incident import EvalReport, TraceEvent


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def state_snapshot(state: IncidentState) -> dict[str, Any]:
    keys = [
        "incident_id",
        "trace_id",
        "status",
        "log_analysis",
        "metric_analysis",
        "knowledge_results",
        "root_cause_analysis",
        "fix_plan",
        "review_result",
        "metadata",
    ]
    return {key: _jsonable(state[key]) for key in keys if key in state}


def traced_node(
    node_name: str,
    agent_name: str,
    handler: Callable[[IncidentState], dict[str, Any]],
) -> Callable[[IncidentState], dict[str, Any]]:
    def wrapped(state: IncidentState) -> dict[str, Any]:
        trace_id = state["trace_id"]
        existing_events = list(state.get("trace_events", []))
        start = TraceEvent(
            trace_id=trace_id,
            node_name=node_name,
            agent_name=agent_name,
            event_type="node_start",
            input_snapshot=state_snapshot(state),
        )
        started_at = time.perf_counter()
        try:
            output = handler(state)
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            metadata = output.get("metadata", state.get("metadata", {}))
            agent_info = metadata.get("agent_execution", {}).get(agent_name, {})
            end = TraceEvent(
                trace_id=trace_id,
                node_name=node_name,
                agent_name=agent_name,
                event_type="node_end",
                output_snapshot=_jsonable(output),
                state_diff=_jsonable(output),
                duration_ms=duration_ms,
                execution_mode=agent_info.get("execution_mode"),
                fallback_reason=agent_info.get("fallback_reason"),
                llm_provider=agent_info.get("llm_provider"),
                llm_model=agent_info.get("llm_model"),
                prompt_tokens=agent_info.get("prompt_tokens"),
                completion_tokens=agent_info.get("completion_tokens"),
                total_tokens=agent_info.get("total_tokens"),
                llm_latency_ms=agent_info.get("llm_latency_ms"),
                llm_error_type=agent_info.get("llm_error_type"),
                prompt_version=agent_info.get("prompt_version"),
                privacy_mode=agent_info.get("privacy_mode"),
            )
            output["trace_events"] = existing_events + [start, end]
            return output
        except Exception as exc:  # pragma: no cover - defensive path
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            error = TraceEvent(
                trace_id=trace_id,
                node_name=node_name,
                agent_name=agent_name,
                event_type="error",
                error=str(exc),
                duration_ms=duration_ms,
            )
            return {
                "trace_events": existing_events + [start, error],
                "errors": [*state.get("errors", []), str(exc)],
                "status": "failed",
            }

    return wrapped


def generate_eval_report(state: IncidentState) -> EvalReport:
    events = state.get("trace_events", [])
    total_duration = sum(event.duration_ms for event in events if event.event_type == "node_end")
    agent_scores: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type != "node_end":
            continue
        schema_valid = bool(event.output_snapshot)
        agent_scores[event.agent_name] = {
            "success": True,
            "schema_valid": schema_valid,
            "duration_ms": event.duration_ms,
        }
        if event.execution_mode:
            agent_scores[event.agent_name]["execution_mode"] = event.execution_mode
        if event.fallback_reason:
            agent_scores[event.agent_name]["fallback_reason"] = event.fallback_reason
        for key in (
            "llm_provider",
            "llm_model",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "llm_latency_ms",
            "llm_error_type",
            "prompt_version",
            "privacy_mode",
        ):
            value = getattr(event, key)
            if value is not None:
                agent_scores[event.agent_name][key] = value

    knowledge = state.get("knowledge_results")
    if knowledge:
        agent_scores.setdefault("knowledge_agent", {})["retrieval_hit_count"] = len(knowledge.source_references)
        agent_scores["knowledge_agent"]["top_source_score"] = (
            max((item.score for item in [*knowledge.retrieved_cases, *knowledge.related_runbooks]), default=0.0)
        )

    root = state.get("root_cause_analysis")
    if root:
        evidence_total = sum(len(item.evidence) for item in root.root_cause_hypotheses)
        agent_scores.setdefault("root_cause_agent", {})["hypothesis_count"] = len(root.root_cause_hypotheses)
        agent_scores["root_cause_agent"]["evidence_coverage"] = round(min(evidence_total / 5, 1.0), 2)

    risks: list[str] = []
    fix_plan = state.get("fix_plan")
    if fix_plan and fix_plan.requires_human_approval:
        risks.append("Fix plan includes high-risk operations and requires human approval.")

    recommendations: list[str] = []
    if knowledge and not knowledge.source_references:
        recommendations.append("Add more incident cases or runbooks to improve retrieval quality.")
    if root and root.missing_information:
        recommendations.extend(root.missing_information)

    return EvalReport(
        trace_id=state["trace_id"],
        workflow_status="failed" if state.get("errors") else "completed",
        total_duration_ms=total_duration,
        agent_scores=agent_scores,
        risks=risks,
        recommendations=recommendations,
    )
