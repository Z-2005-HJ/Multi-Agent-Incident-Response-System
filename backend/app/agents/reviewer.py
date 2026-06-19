from __future__ import annotations

from app.llm.client import LLMError, OpenAICompatibleClient
from app.schemas.incident import FixPlan, ReviewResult, RootCauseAnalysis
from pydantic import ValidationError


REVIEWER_SYSTEM_PROMPT = """You are a strict incident report reviewer.
Return JSON only. Do not include markdown.
The JSON object must match this shape:
{
  "approved": true,
  "review_notes": ["note"],
  "quality_score": 0.0,
  "evidence_score": 0.0,
  "safety_score": 0.0,
  "required_revisions": ["revision"]
}
Approve only if root causes have evidence and high-risk actions require human approval."""


def review(root_cause_analysis: RootCauseAnalysis, fix_plan: FixPlan) -> ReviewResult:
    try:
        return review_with_llm(root_cause_analysis, fix_plan)
    except (LLMError, ValidationError):
        return review_rule(root_cause_analysis, fix_plan)


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
            {"role": "system", "content": REVIEWER_SYSTEM_PROMPT},
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
