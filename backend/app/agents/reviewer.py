from __future__ import annotations

from typing import Any

from app.llm.client import LLMError, OpenAICompatibleClient
from app.llm.settings import get_llm_settings
from app.prompts.loader import load_prompt, prompt_version
from app.schemas.incident import FixPlan, ReviewResult, RootCauseAnalysis
from pydantic import ValidationError


def _llm_metadata(client: OpenAICompatibleClient, prompt_name: str) -> dict[str, Any]:
    metadata = dict(client.last_call_metadata)
    metadata["prompt_version"] = prompt_version(prompt_name)
    metadata["privacy_mode"] = get_llm_settings().privacy_mode
    return metadata


def review(root_cause_analysis: RootCauseAnalysis, fix_plan: FixPlan) -> ReviewResult:
    result, _metadata = review_with_metadata(root_cause_analysis, fix_plan)
    return result


def review_with_metadata(
    root_cause_analysis: RootCauseAnalysis,
    fix_plan: FixPlan,
) -> tuple[ReviewResult, dict[str, Any]]:
    try:
        client = OpenAICompatibleClient()
        return review_with_llm(root_cause_analysis, fix_plan, client=client), {
            "execution_mode": "llm",
            "fallback_reason": None,
            **_llm_metadata(client, "reviewer.md"),
        }
    except (LLMError, ValidationError) as exc:
        client = locals().get("client")
        llm_error_metadata = dict(getattr(client, "last_call_metadata", {}))
        return review_rule(root_cause_analysis, fix_plan), {
            "execution_mode": "rule_fallback",
            "fallback_reason": str(exc),
            **llm_error_metadata,
            "llm_error_type": llm_error_metadata.get("llm_error_type") or exc.__class__.__name__,
            "privacy_mode": get_llm_settings().privacy_mode,
            "prompt_version": prompt_version("reviewer.md"),
        }


def review_with_llm(
    root_cause_analysis: RootCauseAnalysis,
    fix_plan: FixPlan,
    client: OpenAICompatibleClient | None = None,
) -> ReviewResult:
    llm = client or OpenAICompatibleClient()
    if not llm.is_enabled():
        raise LLMError("LLM is disabled.")

    data = llm.json_chat(
        [
            {"role": "system", "content": load_prompt("reviewer.md")},
            {
                "role": "user",
                "content": (
                    "Review this root cause analysis and fix plan:\n"
                    f"root_cause_analysis={root_cause_analysis.model_dump(mode='json')}\n"
                    f"fix_plan={fix_plan.model_dump(mode='json')}"
                ),
            },
        ],
        temperature=0.1,
    )
    result = ReviewResult.model_validate(data)
    if fix_plan.risk_level == "high" and not fix_plan.requires_human_approval:
        result.approved = False
        result.required_revisions.append("High-risk fix plan must require human approval.")
    return result


def review_rule(root_cause_analysis: RootCauseAnalysis, fix_plan: FixPlan) -> ReviewResult:
    notes: list[str] = []
    revisions: list[str] = []

    evidence_count = sum(len(item.evidence) for item in root_cause_analysis.root_cause_hypotheses)
    evidence_score = min(evidence_count / 5, 1.0)
    safety_score = 0.7 if fix_plan.requires_human_approval else 0.9
    quality_score = round((evidence_score + safety_score + root_cause_analysis.confidence) / 3, 2)

    if evidence_score < 0.4:
        revisions.append("Add more evidence before treating the root cause as likely.")
    if fix_plan.risk_level == "high":
        notes.append("Fix plan contains high-risk operations and requires human approval.")
    if root_cause_analysis.missing_information:
        notes.extend(root_cause_analysis.missing_information)

    approved = not revisions
    return ReviewResult(
        approved=approved,
        review_notes=notes or ["Report passed basic evidence and safety checks."],
        quality_score=quality_score,
        evidence_score=round(evidence_score, 2),
        safety_score=safety_score,
        required_revisions=revisions,
    )
