from __future__ import annotations

from app.llm.client import LLMError, OpenAICompatibleClient
from app.schemas.incident import FixPlan, RootCauseAnalysis
from pydantic import ValidationError


FIX_PLANNER_SYSTEM_PROMPT = """You are a cautious SRE fix planner.
Return JSON only. Do not include markdown.
The JSON object must match this shape:
{
  "diagnostic_steps": ["step"],
  "recommended_actions": ["action"],
  "rollback_plan": ["rollback step"],
  "verification_steps": ["verification step"],
  "risk_level": "low|medium|high",
  "requires_human_approval": true
}
Never recommend executing real production commands automatically.
Any rollback, database configuration change, restart, or data repair must require human approval."""


def plan_fix(root_cause_analysis: RootCauseAnalysis) -> FixPlan:
    try:
        return plan_fix_with_llm(root_cause_analysis)
    except (LLMError, ValidationError):
        return plan_fix_rule(root_cause_analysis)


def plan_fix_with_llm(
    root_cause_analysis: RootCauseAnalysis,
    client: OpenAICompatibleClient | None = None,
) -> FixPlan:
    llm = client or OpenAICompatibleClient()
    if not llm.is_enabled():
        raise LLMError("LLM is disabled.")

    data = llm.json_chat(
        [
            {"role": "system", "content": FIX_PLANNER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Create a safe fix plan for this root cause analysis:\n{root_cause_analysis.model_dump(mode='json')}",
            },
        ],
        temperature=0.1,
    )
    result = FixPlan.model_validate(data)
    if result.risk_level == "high":
        result.requires_human_approval = True
    return result


def plan_fix_rule(root_cause_analysis: RootCauseAnalysis) -> FixPlan:
    primary = root_cause_analysis.root_cause_hypotheses[0].cause.lower()
    diagnostic_steps = [
        "Confirm the incident time window and affected service instances.",
        "Compare error rate, latency, and dependency metrics before and after the alert.",
    ]
    recommended_actions = [
        "Keep the service in observe-only mode until a human confirms the mitigation.",
    ]
    rollback_plan = [
        "If the issue started after a deployment, prepare rollback to the last known good release.",
    ]
    verification_steps = [
        "Verify error rate returns near baseline.",
        "Verify p95 latency returns near baseline.",
        "Confirm no new critical log pattern appears after mitigation.",
    ]
    risk_level = "medium"

    if "connection pool" in primary or "database" in primary:
        diagnostic_steps.extend(
            [
                "Inspect database connection pool saturation and wait time.",
                "Check database connection limits and slow query metrics.",
            ]
        )
        recommended_actions.extend(
            [
                "Reduce request pressure or temporarily scale service replicas if safe.",
                "Tune connection pool settings only after reviewing database capacity.",
            ]
        )
        rollback_plan.append("Rollback the deployment or config change that modified database connection behavior.")
        risk_level = "high"

    requires_approval = risk_level == "high" or any("rollback" in action.lower() for action in rollback_plan)
    return FixPlan(
        diagnostic_steps=diagnostic_steps,
        recommended_actions=recommended_actions,
        rollback_plan=rollback_plan,
        verification_steps=verification_steps,
        risk_level=risk_level,
        requires_human_approval=requires_approval,
    )
