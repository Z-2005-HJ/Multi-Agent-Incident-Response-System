from __future__ import annotations

from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agents.fix_planner import plan_fix
from app.agents.knowledge_agent import retrieve_knowledge
from app.agents.log_analyst import analyze_logs
from app.agents.metric_analyst import analyze_metrics
from app.agents.reviewer import review
from app.agents.root_cause_agent import infer_root_cause
from app.eval.adapter import generate_eval_report, traced_node
from app.graph.state import IncidentState
from app.reports.markdown import render_markdown_report
from app.schemas.incident import IncidentReport, IncidentRequest, IncidentRunResult


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


def knowledge_node(state: IncidentState) -> dict:
    return {
        "knowledge_results": retrieve_knowledge(
            state["request"],
            state["log_analysis"],
            state["metric_analysis"],
        )
    }


def root_cause_node(state: IncidentState) -> dict:
    return {
        "root_cause_analysis": infer_root_cause(
            state["log_analysis"],
            state["metric_analysis"],
            state["knowledge_results"],
        )
    }


def fix_plan_node(state: IncidentState) -> dict:
    return {"fix_plan": plan_fix(state["root_cause_analysis"])}


def review_node(state: IncidentState) -> dict:
    return {"review_result": review(state["root_cause_analysis"], state["fix_plan"])}


def final_report_node(state: IncidentState) -> dict:
    request = state["request"]
    log_analysis = state["log_analysis"]
    metric_analysis = state["metric_analysis"]
    knowledge_results = state["knowledge_results"]
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
        sources=knowledge_results.source_references,
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
    graph.add_node("knowledge_retrieval", traced_node("knowledge_retrieval", "knowledge_agent", knowledge_node))
    graph.add_node("root_cause_analysis", traced_node("root_cause_analysis", "root_cause_agent", root_cause_node))
    graph.add_node("fix_planning", traced_node("fix_planning", "fix_planner", fix_plan_node))
    graph.add_node("review", traced_node("review", "reviewer", review_node))
    graph.add_node("final_report", traced_node("final_report", "reporter", final_report_node))
    graph.add_node("eval_report", traced_node("eval_report", "eval_adapter", eval_node))

    graph.add_edge(START, "ingest_incident")
    graph.add_edge("ingest_incident", "log_analysis")
    graph.add_edge("log_analysis", "metric_analysis")
    graph.add_edge("metric_analysis", "knowledge_retrieval")
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
    )
