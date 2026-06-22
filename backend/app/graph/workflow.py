from __future__ import annotations

from uuid import uuid4
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.fix_planner import plan_fix_with_metadata
from app.agents.knowledge_agent import retrieve_knowledge
from app.agents.log_analyst import analyze_logs
from app.agents.metric_analyst import analyze_metrics
from app.agents.reviewer import review_with_metadata
from app.agents.root_cause_agent import infer_root_cause_with_metadata
from app.eval.adapter import generate_eval_report, traced_node
from app.graph.state import IncidentState
from app.reports.markdown import render_markdown_report
from app.schemas.incident import IncidentReport, IncidentRequest, IncidentRunResult
from app.tools.manual_evidence_tools import collect_manual_evidence_context


def ingest_node(state: IncidentState) -> dict:
    request = state["request"]
    return {
        "incident_id": request.incident_id,
        "status": "running",
        "errors": [],
    }


def log_node(state: IncidentState) -> dict:
    return {"log_analysis": analyze_logs(state["request"])}


def metric_node(state: IncidentState) -> dict:
    return {"metric_analysis": analyze_metrics(state["request"])}


def manual_evidence_node(state: IncidentState) -> dict:
    tool_context = collect_manual_evidence_context(state["request"])
    tool_calls = [
        {
            "name": "manual_metric_evidence",
            "source": tool_context.tool_sources.get("metrics", "unknown"),
            "status": "ok",
            "result_count": len(tool_context.metric_findings),
        },
        {
            "name": "manual_log_evidence",
            "source": tool_context.tool_sources.get("logs", "unknown"),
            "status": "ok",
            "result_count": len(tool_context.log_search_hits),
        },
        {
            "name": "manual_deployment_clues",
            "source": tool_context.tool_sources.get("deployment", "unknown"),
            "status": "ok",
            "result_count": len(tool_context.deployment_events),
        },
    ]
    metadata = dict(state.get("metadata", {}))
    metadata["manual_evidence"] = {
        "metric_findings": len(tool_context.metric_findings),
        "log_search_hits": len(tool_context.log_search_hits),
        "deployment_events": len(tool_context.deployment_events),
        "tool_sources": tool_context.tool_sources,
        "tool_errors": tool_context.tool_errors,
    }
    metadata["tool_context"] = tool_context.model_dump(mode="json")
    metadata["tool_calls"] = [*metadata.get("tool_calls", []), *tool_calls]
    return {"tool_context": tool_context, "metadata": metadata}


def knowledge_node(state: IncidentState) -> dict:
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
) -> dict:
    metadata = dict(state.get("metadata", {}))
    agent_execution = dict(metadata.get("agent_execution", {}))
    agent_execution[agent_name] = execution_metadata
    metadata["agent_execution"] = agent_execution
    return metadata


def root_cause_node(state: IncidentState) -> dict:
    result, execution_metadata = infer_root_cause_with_metadata(
        state["log_analysis"],
        state["metric_analysis"],
        state["knowledge_results"],
        state.get("tool_context"),
    )
    return {
        "root_cause_analysis": result,
        "metadata": _with_agent_execution_metadata(state, "root_cause_agent", execution_metadata),
    }


def fix_plan_node(state: IncidentState) -> dict:
    result, execution_metadata = plan_fix_with_metadata(state["root_cause_analysis"])
    return {
        "fix_plan": result,
        "metadata": _with_agent_execution_metadata(state, "fix_planner", execution_metadata),
    }


def review_node(state: IncidentState) -> dict:
    result, execution_metadata = review_with_metadata(state["root_cause_analysis"], state["fix_plan"])
    return {
        "review_result": result,
        "metadata": _with_agent_execution_metadata(state, "reviewer", execution_metadata),
    }


def final_report_node(state: IncidentState) -> dict:
    request = state["request"]
    log_analysis = state["log_analysis"]
    metric_analysis = state["metric_analysis"]
    knowledge_results = state["knowledge_results"]
    tool_context = state.get("tool_context")
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
    if tool_context:
        signals.extend(item.summary for item in tool_context.metric_findings)
        signals.extend(f"log_search:{item.level} {item.message}" for item in tool_context.log_search_hits[:4])
        signals.extend(f"deployment:{item.version} {', '.join(item.risk_flags)}" for item in tool_context.deployment_events)
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
                [f"manual_metrics_{tool_context.tool_sources.get('metrics', 'unknown')}"]
                if tool_context and tool_context.metric_findings
                else []
            ),
            *(
                [f"manual_logs_{tool_context.tool_sources.get('logs', 'unknown')}"]
                if tool_context and tool_context.log_search_hits
                else []
            ),
            *(
                [f"manual_deployment_{tool_context.tool_sources.get('deployment', 'unknown')}"]
                if tool_context and tool_context.deployment_events
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


def eval_node(state: IncidentState) -> dict:
    return {"eval_report": generate_eval_report(state)}


def build_workflow():
    graph = StateGraph(IncidentState)
    graph.add_node("ingest_incident", traced_node("ingest_incident", "ingest", ingest_node))
    graph.add_node("log_analysis", traced_node("log_analysis", "log_analyst", log_node))
    graph.add_node("metric_analysis", traced_node("metric_analysis", "metric_analyst", metric_node))
    graph.add_node("manual_evidence", traced_node("manual_evidence", "evidence_adapter", manual_evidence_node))
    graph.add_node("knowledge_retrieval", traced_node("knowledge_retrieval", "knowledge_agent", knowledge_node))
    graph.add_node("root_cause_analysis", traced_node("root_cause_analysis", "root_cause_agent", root_cause_node))
    graph.add_node("fix_planning", traced_node("fix_planning", "fix_planner", fix_plan_node))
    graph.add_node("review", traced_node("review", "reviewer", review_node))
    graph.add_node("final_report", traced_node("final_report", "reporter", final_report_node))
    graph.add_node("eval_report", traced_node("eval_report", "eval_adapter", eval_node))

    graph.add_edge(START, "ingest_incident")
    graph.add_edge("ingest_incident", "log_analysis")
    graph.add_edge("log_analysis", "metric_analysis")
    graph.add_edge("metric_analysis", "manual_evidence")
    graph.add_edge("manual_evidence", "knowledge_retrieval")
    graph.add_edge("knowledge_retrieval", "root_cause_analysis")
    graph.add_edge("root_cause_analysis", "fix_planning")
    graph.add_edge("fix_planning", "review")
    graph.add_edge("review", "final_report")
    graph.add_edge("final_report", "eval_report")
    graph.add_edge("eval_report", END)
    return graph.compile()


def run_incident_workflow(request: IncidentRequest) -> IncidentRunResult:
    trace_id = f"trace_{uuid4().hex[:12]}"
    initial_state: IncidentState = {
        "request": request,
        "incident_id": request.incident_id,
        "trace_id": trace_id,
        "trace_events": [],
        "errors": [],
        "status": "created",
    }
    state = build_workflow().invoke(initial_state)
    return IncidentRunResult(
        incident_id=state["incident_id"],
        trace_id=state["trace_id"],
        workflow_status=state["status"],
        report=state["final_report"],
        markdown_report=state["markdown_report"],
        eval_report=state["eval_report"],
        trace_events=state["trace_events"],
        tool_context=state.get("tool_context"),
        metadata=state.get("metadata", {}),
    )
