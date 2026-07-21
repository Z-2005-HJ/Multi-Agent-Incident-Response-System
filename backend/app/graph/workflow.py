from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel

from app.agents.evidence_analyst import analyze_evidence
from app.agents.fix_planner import plan_fix_with_metadata
from app.agents.knowledge_agent import retrieve_knowledge
from app.agents.reviewer import review_with_metadata
from app.agents.root_cause_agent import infer_root_cause_with_metadata
from app.eval.adapter import generate_eval_report, state_snapshot
from app.graph.state import IncidentState
from app.observability import record_node_execution, record_workflow_run
from app.reports.markdown import render_markdown_report
from app.schemas.incident import (
    DeploymentAnalysis,
    EvidenceAnalysis,
    EvalReport,
    FixPlan,
    IncidentReport,
    IncidentRequest,
    IncidentRunResult,
    KnowledgeResults,
    LogAnalysis,
    ManualEvidenceContext,
    MetricAnalysis,
    ReviewResult,
    RootCauseAnalysis,
    TraceEvent,
)
from app.tools.manual_evidence_tools import derive_log_hits, derive_metric_findings


@dataclass(frozen=True)
class WorkflowNodeSpec:
    node_name: str
    agent_name: str
    handler: Callable[[IncidentState], dict[str, Any]]
    max_retries: int = 0


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


STATE_MODEL_LOADERS: dict[str, Callable[[Any], Any]] = {
    "request": IncidentRequest.model_validate,
    "evidence_analysis": EvidenceAnalysis.model_validate,
    "log_analysis": LogAnalysis.model_validate,
    "metric_analysis": MetricAnalysis.model_validate,
    "deployment_analysis": DeploymentAnalysis.model_validate,
    "evidence_context": ManualEvidenceContext.model_validate,
    "knowledge_results": KnowledgeResults.model_validate,
    "root_cause_analysis": RootCauseAnalysis.model_validate,
    "fix_plan": FixPlan.model_validate,
    "review_result": ReviewResult.model_validate,
    "final_report": IncidentReport.model_validate,
    "eval_report": EvalReport.model_validate,
}


def serialize_state(state: IncidentState) -> dict[str, Any]:
    raw = {key: _jsonable(value) for key, value in state.items()}
    metadata = raw.get("metadata")
    if isinstance(metadata, dict):
        runtime = metadata.get("runtime")
        if isinstance(runtime, dict):
            runtime = dict(runtime)
            runtime.pop("resume_state", None)
            metadata = dict(metadata)
            metadata["runtime"] = runtime
            raw["metadata"] = metadata
    return raw


def deserialize_state(raw_state: dict[str, Any]) -> IncidentState:
    state: IncidentState = {}
    for key, value in raw_state.items():
        if key == "trace_events" and isinstance(value, list):
            state[key] = [TraceEvent.model_validate(item) for item in value]
        elif key in STATE_MODEL_LOADERS and value is not None:
            state[key] = STATE_MODEL_LOADERS[key](value)
        else:
            state[key] = value
    return state


def ingest_node(state: IncidentState) -> dict[str, Any]:
    request = state["request"]
    return {
        "incident_id": request.incident_id,
        "status": "running",
        "errors": [],
    }


def evidence_node(state: IncidentState) -> dict[str, Any]:
    evidence_analysis = analyze_evidence(state["request"])
    evidence_context = _evidence_context(state)
    log_analysis = evidence_analysis.log_analysis
    metric_analysis = evidence_analysis.metric_analysis
    deployment_analysis = evidence_analysis.deployment_analysis
    evidence_context.log_evidence_hits = derive_log_hits(state["request"])
    evidence_context.metric_findings = derive_metric_findings(state["request"])
    evidence_context.deployment_events = deployment_analysis.deployment_events
    evidence_context.evidence_sources["logs"] = "logs_window"
    evidence_context.evidence_sources["metrics"] = "metrics_window"
    evidence_context.evidence_sources["deployment"] = "change_window"
    return {
        "evidence_analysis": evidence_analysis,
        "log_analysis": log_analysis,
        "metric_analysis": metric_analysis,
        "deployment_analysis": deployment_analysis,
        "evidence_context": evidence_context,
        "metadata": _evidence_metadata(state, evidence_context),
    }


def knowledge_node(state: IncidentState) -> dict[str, Any]:
    return {
        "knowledge_results": retrieve_knowledge(
            state["request"],
            state["log_analysis"],
            state["metric_analysis"],
        )
    }


def _with_agent_execution_metadata(
    state: IncidentState,
    agent_name: str,
    execution_metadata: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(state.get("metadata", {}))
    agent_execution = dict(metadata.get("agent_execution", {}))
    agent_execution[agent_name] = execution_metadata
    metadata["agent_execution"] = agent_execution
    return metadata


def _evidence_context(state: IncidentState) -> ManualEvidenceContext:
    return state.get("evidence_context") or ManualEvidenceContext(
        evidence_sources={
            "metrics": "metrics_window",
            "logs": "logs_window",
            "deployment": "change_window",
        }
    )


def _evidence_metadata(state: IncidentState, evidence_context: ManualEvidenceContext) -> dict[str, Any]:
    metadata = dict(state.get("metadata", {}))
    metadata["standardized_evidence"] = {
        "metric_findings": len(evidence_context.metric_findings),
        "log_evidence_hits": len(evidence_context.log_evidence_hits),
        "deployment_events": len(evidence_context.deployment_events),
        "evidence_sources": evidence_context.evidence_sources,
        "evidence_errors": evidence_context.evidence_errors,
    }
    metadata["manual_evidence"] = metadata["standardized_evidence"]
    metadata["evidence_context"] = evidence_context.model_dump(mode="json")
    metadata["evidence_observations"] = [
        {
            "name": "metric_evidence",
            "source": evidence_context.evidence_sources.get("metrics", "unknown"),
            "status": "ok",
            "result_count": len(evidence_context.metric_findings),
        },
        {
            "name": "log_evidence",
            "source": evidence_context.evidence_sources.get("logs", "unknown"),
            "status": "ok",
            "result_count": len(evidence_context.log_evidence_hits),
        },
        {
            "name": "deployment_evidence",
            "source": evidence_context.evidence_sources.get("deployment", "unknown"),
            "status": "ok",
            "result_count": len(evidence_context.deployment_events),
        },
    ]
    return metadata


def root_cause_node(state: IncidentState) -> dict[str, Any]:
    result, execution_metadata = infer_root_cause_with_metadata(
        state["log_analysis"],
        state["metric_analysis"],
        state["knowledge_results"],
        state.get("evidence_context"),
    )
    return {
        "root_cause_analysis": result,
        "metadata": _with_agent_execution_metadata(state, "root_cause_agent", execution_metadata),
    }


def fix_plan_node(state: IncidentState) -> dict[str, Any]:
    result, execution_metadata = plan_fix_with_metadata(state["root_cause_analysis"])
    return {
        "fix_plan": result,
        "metadata": _with_agent_execution_metadata(state, "fix_planner", execution_metadata),
    }


def review_node(state: IncidentState) -> dict[str, Any]:
    result, execution_metadata = review_with_metadata(state["root_cause_analysis"], state["fix_plan"])
    return {
        "review_result": result,
        "metadata": _with_agent_execution_metadata(state, "reviewer", execution_metadata),
    }


def final_report_node(state: IncidentState) -> dict[str, Any]:
    request = state["request"]
    log_analysis = state["log_analysis"]
    metric_analysis = state["metric_analysis"]
    knowledge_results = state["knowledge_results"]
    evidence_context = state.get("evidence_context")
    root_cause_analysis = state["root_cause_analysis"]
    fix_plan = state["fix_plan"]
    review_result = state["review_result"]

    severity = "medium"
    if fix_plan.risk_level == "high":
        severity = "high"
    if any(item.metric_name == "error_rate" and item.severity == "high" for item in metric_analysis.metric_anomalies):
        severity = "critical"

    signals = list(log_analysis.error_patterns)
    signals.extend(
        f"{item.metric_name}: {item.before} -> {item.after}"
        for item in metric_analysis.metric_anomalies
    )
    if evidence_context:
        signals.extend(item.summary for item in evidence_context.metric_findings)
        signals.extend(f"log_evidence:{item.level} {item.message}" for item in evidence_context.log_evidence_hits[:4])
        signals.extend(f"deployment:{item.version} {', '.join(item.risk_flags)}" for item in evidence_context.deployment_events)
    summary = (
        f"{request.service_name} incident analysis found "
        f"{len(root_cause_analysis.root_cause_hypotheses)} root cause hypothesis."
    )
    report = IncidentReport(
        incident_id=state["incident_id"],
        service_name=request.service_name,
        severity=severity,
        summary=summary,
        timeline=[*log_analysis.log_timeline, *metric_analysis.timeline],
        signals=signals,
        root_causes=root_cause_analysis.root_cause_hypotheses,
        recommended_actions=fix_plan.recommended_actions,
        rollback_plan=fix_plan.rollback_plan,
        verification_steps=fix_plan.verification_steps,
        confidence=root_cause_analysis.confidence,
        review_notes=review_result.review_notes,
        sources=[
            *knowledge_results.source_references,
            *(
                [f"evidence_metrics_{evidence_context.evidence_sources.get('metrics', 'unknown')}"]
                if evidence_context and evidence_context.metric_findings
                else []
            ),
            *(
                [f"evidence_logs_{evidence_context.evidence_sources.get('logs', 'unknown')}"]
                if evidence_context and evidence_context.log_evidence_hits
                else []
            ),
            *(
                [f"evidence_deployment_{evidence_context.evidence_sources.get('deployment', 'unknown')}"]
                if evidence_context and evidence_context.deployment_events
                else []
            ),
        ],
        human_approval_required=fix_plan.requires_human_approval,
    )
    markdown = render_markdown_report(report)
    return {
        "final_report": report,
        "markdown_report": markdown,
        "status": "completed" if review_result.approved else "needs_revision",
    }


def eval_node(state: IncidentState) -> dict[str, Any]:
    return {"eval_report": generate_eval_report(state)}


WORKFLOW_NODES: list[WorkflowNodeSpec] = [
    WorkflowNodeSpec("ingest_incident", "ingest", ingest_node),
    WorkflowNodeSpec("evidence_analysis", "evidence_analyst", evidence_node),
    WorkflowNodeSpec("knowledge_retrieval", "knowledge_agent", knowledge_node, max_retries=1),
    WorkflowNodeSpec("root_cause_analysis", "root_cause_agent", root_cause_node, max_retries=1),
    WorkflowNodeSpec("fix_planning", "fix_planner", fix_plan_node, max_retries=1),
    WorkflowNodeSpec("review", "reviewer", review_node, max_retries=1),
    WorkflowNodeSpec("final_report", "reporter", final_report_node),
    WorkflowNodeSpec("eval_report", "observability_layer", eval_node),
]


def build_workflow() -> list[str]:
    return [node.node_name for node in WORKFLOW_NODES]


def classify_workflow_error(exc: Exception) -> tuple[str, bool]:
    message = f"{type(exc).__name__}: {exc}".lower()
    if "timeout" in message:
        return "timeout", True
    if "connection" in message or "unavailable" in message or "temporarily" in message:
        return "dependency_unavailable", True
    if "validation" in message or "schema" in message or "json" in message:
        return "validation_error", False
    if "llm" in message or "provider" in message:
        return "llm_error", True
    if "permission" in message or "unauthorized" in message or "forbidden" in message:
        return "authorization_error", False
    return "runtime_error", True


def _ensure_runtime_metadata(state: IncidentState) -> dict[str, Any]:
    metadata = dict(state.get("metadata", {}))
    runtime = dict(metadata.get("runtime", {}))
    runtime.setdefault("completed_nodes", list(state.get("completed_nodes", [])))
    runtime.setdefault("recoverable", False)
    metadata["runtime"] = runtime
    state["metadata"] = metadata
    return runtime


def _merge_state(state: IncidentState, output: dict[str, Any]) -> IncidentState:
    merged = dict(state)
    for key, value in output.items():
        if key in {"trace_events", "errors"}:
            continue
        if key == "metadata":
            next_metadata = dict(state.get("metadata", {}))
            next_metadata.update(value)
            merged["metadata"] = next_metadata
            continue
        merged[key] = value
    return merged


def _record_checkpoint(state: IncidentState, current_node: str | None = None) -> None:
    checkpoint_id = f"ckpt_{uuid4().hex[:12]}"
    state["last_checkpoint_id"] = checkpoint_id
    runtime = _ensure_runtime_metadata(state)
    runtime["checkpoint_id"] = checkpoint_id
    runtime["current_node"] = current_node or state.get("current_node")
    runtime["completed_nodes"] = list(state.get("completed_nodes", []))
    runtime["resume_state"] = serialize_state(state)


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _append_trace(state: IncidentState, event: TraceEvent) -> None:
    state["trace_events"] = [*state.get("trace_events", []), event]


def _pending_human_input(state: IncidentState) -> dict[str, Any] | None:
    review = state.get("review_result")
    report = state.get("final_report")
    if review and not review.approved:
        return {
            "kind": "revision_required",
            "node_name": "review",
            "summary": "Reviewer requested revisions before the workflow can be promoted.",
            "required_revisions": review.required_revisions,
        }
    if report and report.human_approval_required:
        return {
            "kind": "approval_required",
            "node_name": "final_report",
            "summary": "High-risk fix plan requires human approval before operational execution.",
        }
    return None


def _fallback_report(state: IncidentState, message: str) -> IncidentReport:
    request = state["request"]
    return IncidentReport(
        incident_id=state.get("incident_id", request.incident_id),
        service_name=request.service_name,
        severity="high",
        summary=f"{request.service_name} workflow runtime stopped before completion.",
        timeline=[],
        signals=[],
        root_causes=[],
        recommended_actions=[],
        rollback_plan=[],
        verification_steps=[],
        confidence=0.0,
        review_notes=[message],
        sources=[],
        human_approval_required=False,
    )


def _restore_or_initialize_state(request: IncidentRequest, resume_state: dict[str, Any] | None) -> IncidentState:
    if resume_state:
        state = deserialize_state(resume_state)
        state["request"] = request
        state.setdefault("trace_events", [])
        state.setdefault("errors", [])
        state.setdefault("completed_nodes", [])
        state.setdefault("node_attempts", {})
        state.setdefault("metadata", {})
        return state
    trace_id = f"trace_{uuid4().hex[:12]}"
    return {
        "request": request,
        "incident_id": request.incident_id,
        "trace_id": trace_id,
        "trace_events": [],
        "errors": [],
        "status": "created",
        "completed_nodes": [],
        "node_attempts": {},
        "metadata": {},
    }


def _node_execution_metadata(state: IncidentState, agent_name: str, output: dict[str, Any]) -> dict[str, Any]:
    metadata = output.get("metadata", state.get("metadata", {}))
    agent_execution = metadata.get("agent_execution", {})
    return agent_execution.get(agent_name, {})


def _finalize_result(state: IncidentState, workflow_status: str) -> IncidentRunResult:
    runtime = _ensure_runtime_metadata(state)
    runtime["pending_human_input"] = _pending_human_input(state)
    runtime["completed_nodes"] = list(state.get("completed_nodes", []))
    runtime["current_node"] = state.get("current_node")
    runtime["checkpoint_id"] = state.get("last_checkpoint_id")
    if workflow_status == "failed":
        runtime.setdefault("failure_node", state.get("current_node"))
        runtime.setdefault("last_error_category", "runtime_error")
    runtime["resume_state"] = serialize_state(state)
    state["metadata"]["runtime"] = runtime
    state["workflow_status"] = workflow_status  # type: ignore[typeddict-item]
    if "final_report" not in state:
        state["final_report"] = _fallback_report(state, runtime.get("last_error", "Workflow did not produce a final report."))
        state["markdown_report"] = render_markdown_report(state["final_report"])
    if "eval_report" not in state:
        state["eval_report"] = generate_eval_report(state)
    return IncidentRunResult(
        incident_id=state["incident_id"],
        trace_id=state["trace_id"],
        workflow_status=workflow_status,
        report=state["final_report"],
        markdown_report=state["markdown_report"],
        eval_report=state["eval_report"],
        trace_events=state.get("trace_events", []),
        evidence_context=state.get("evidence_context"),
        metadata=state.get("metadata", {}),
    )


def run_incident_workflow(request: IncidentRequest, resume_state: dict[str, Any] | None = None) -> IncidentRunResult:
    state = _restore_or_initialize_state(request, resume_state)
    completed_nodes = list(state.get("completed_nodes", []))
    started_at = time.perf_counter()
    start_index = len(completed_nodes)

    for spec in WORKFLOW_NODES[start_index:]:
        runtime = _ensure_runtime_metadata(state)
        state["current_node"] = spec.node_name
        if state.get("status") not in {"completed", "needs_revision"}:
            state["status"] = "running"
        runtime["current_node"] = spec.node_name
        attempts = max(1, spec.max_retries + 1)
        for attempt in range(1, attempts + 1):
            state.setdefault("node_attempts", {})[spec.node_name] = attempt
            start_event = TraceEvent(
                trace_id=state["trace_id"],
                node_name=spec.node_name,
                agent_name=spec.agent_name,
                event_type="node_start",
                input_snapshot=state_snapshot(state),
                attempt=attempt,
                checkpoint_id=state.get("last_checkpoint_id"),
            )
            _append_trace(state, start_event)
            started_node_at = time.perf_counter()
            try:
                output = spec.handler(state)
                duration_ms = int((time.perf_counter() - started_node_at) * 1000)
                agent_info = _node_execution_metadata(state, spec.agent_name, output)
                end_event = TraceEvent(
                    trace_id=state["trace_id"],
                    node_name=spec.node_name,
                    agent_name=spec.agent_name,
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
                    evidence_observations=output.get("metadata", {}).get("evidence_observations", []),
                    attempt=attempt,
                    checkpoint_id=state.get("last_checkpoint_id"),
                )
                record_node_execution(
                    node_name=spec.node_name,
                    agent_name=spec.agent_name,
                    status="success",
                    duration_seconds=duration_ms / 1000.0,
                    execution_metadata=agent_info,
                )
                state = _merge_state(state, output)
                runtime = _ensure_runtime_metadata(state)
                _append_trace(state, end_event)
                completed_nodes = [*state.get("completed_nodes", []), spec.node_name]
                state["completed_nodes"] = completed_nodes
                runtime["completed_nodes"] = completed_nodes
                _record_checkpoint(state, current_node=spec.node_name)
                break
            except Exception as exc:
                duration_ms = int((time.perf_counter() - started_node_at) * 1000)
                error_category, retryable = classify_workflow_error(exc)
                error_text = _error_text(exc)
                error_event = TraceEvent(
                    trace_id=state["trace_id"],
                    node_name=spec.node_name,
                    agent_name=spec.agent_name,
                    event_type="error",
                    error=error_text,
                    error_category=error_category,
                    retryable=retryable,
                    attempt=attempt,
                    checkpoint_id=state.get("last_checkpoint_id"),
                    duration_ms=duration_ms,
                )
                _append_trace(state, error_event)
                record_node_execution(
                    node_name=spec.node_name,
                    agent_name=spec.agent_name,
                    status="error",
                    duration_seconds=duration_ms / 1000.0,
                    execution_metadata={"error_category": error_category, "retryable": retryable, "attempt": attempt},
                )
                if retryable and attempt < attempts:
                    continue

                state["errors"] = [*state.get("errors", []), error_text]
                state["status"] = "failed"
                runtime["last_error"] = error_text
                runtime["last_error_category"] = error_category
                runtime["failure_node"] = spec.node_name
                runtime["recoverable"] = bool(state.get("completed_nodes")) or retryable
                state["metadata"]["runtime"] = runtime
                if not state.get("last_checkpoint_id"):
                    _record_checkpoint(state, current_node=spec.node_name)
                result = _finalize_result(state, "failed")
                record_workflow_run("failed", time.perf_counter() - started_at)
                return result

    state["status"] = state.get("status", "completed")
    result = _finalize_result(state, state.get("status", "completed"))
    record_workflow_run(result.workflow_status, time.perf_counter() - started_at)
    return result
