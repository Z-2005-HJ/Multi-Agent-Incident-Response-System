from __future__ import annotations

from app.schemas.incident import FixPlan, ReviewResult, RootCauseAnalysis


def review(root_cause_analysis: RootCauseAnalysis, fix_plan: FixPlan) -> ReviewResult:
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

