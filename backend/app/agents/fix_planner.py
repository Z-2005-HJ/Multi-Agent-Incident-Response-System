from __future__ import annotations

from typing import Any

from app.llm.client import LLMError, OpenAICompatibleClient
from app.llm.settings import get_llm_settings
from app.prompts.loader import load_prompt, prompt_version
from app.schemas.incident import FixPlan, RootCauseAnalysis
from pydantic import ValidationError


def _llm_metadata(client: OpenAICompatibleClient, prompt_name: str) -> dict[str, Any]:
    metadata = dict(client.last_call_metadata)
    metadata["prompt_version"] = prompt_version(prompt_name)
    metadata["privacy_mode"] = get_llm_settings().privacy_mode
    return metadata


def plan_fix(root_cause_analysis: RootCauseAnalysis) -> FixPlan:
    result, _metadata = plan_fix_with_metadata(root_cause_analysis)
    return result


def plan_fix_with_metadata(root_cause_analysis: RootCauseAnalysis) -> tuple[FixPlan, dict[str, Any]]:
    try:
        client = OpenAICompatibleClient()
        return plan_fix_with_llm(root_cause_analysis, client=client), {
            "execution_mode": "llm",
            "fallback_reason": None,
            **_llm_metadata(client, "fix_planner.md"),
        }
    except (LLMError, ValidationError) as exc:
        client = locals().get("client")
        llm_error_metadata = dict(getattr(client, "last_call_metadata", {}))
        return plan_fix_rule(root_cause_analysis), {
            "execution_mode": "rule_fallback",
            "fallback_reason": str(exc),
            "llm_error_type": llm_error_metadata.get("llm_error_type") or exc.__class__.__name__,
            "privacy_mode": get_llm_settings().privacy_mode,
            "prompt_version": prompt_version("fix_planner.md"),
        }


def plan_fix_with_llm(
    root_cause_analysis: RootCauseAnalysis,
    client: OpenAICompatibleClient | None = None,
) -> FixPlan:
    llm = client or OpenAICompatibleClient()
    if not llm.is_enabled():
        raise LLMError("LLM is disabled.")

    data = llm.json_chat(
        [
            {"role": "system", "content": load_prompt("fix_planner.md")},
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
