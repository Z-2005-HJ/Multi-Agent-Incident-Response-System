from __future__ import annotations

from typing import Any

from app.agents.fix_planner import plan_fix_with_llm
from app.agents.reviewer import review_with_llm
from app.agents.root_cause_agent import infer_root_cause_with_llm
from app.schemas.incident import (
    FixPlan,
    KnowledgeResults,
    LogAnalysis,
    MetricAnalysis,
    MetricAnomaly,
    ReviewResult,
    RootCauseAnalysis,
    RootCauseHypothesis,
)


class FakeLLMClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def is_enabled(self) -> bool:
        return True

    def json_chat(self, messages: list[dict[str, str]], temperature: float = 0.1) -> dict[str, Any]:
        return self.response


def test_root_cause_agent_accepts_llm_json() -> None:
    result = infer_root_cause_with_llm(
        LogAnalysis(
            error_patterns=["DatabaseConnectionTimeout"],
            important_log_lines=["ERROR checkout-api failed to acquire connection from pool"],
            suspected_components=["database"],
            log_confidence=0.8,
        ),
        MetricAnalysis(
            metric_anomalies=[
                MetricAnomaly(
                    metric_name="db_connection_pool_usage",
                    before=0.45,
                    after=0.98,
                    change_ratio=1.17,
                    direction="increase",
                    severity="high",
                )
            ],
            metric_confidence=0.8,
        ),
        KnowledgeResults(source_references=["kb_incident_db_pool_001"], retrieval_confidence=0.8),
        client=FakeLLMClient(
            {
                "root_cause_hypotheses": [
                    {
                        "cause": "Database connection pool exhaustion.",
                        "status": "likely",
                        "confidence": 0.88,
                        "evidence": ["db_connection_pool_usage changed from 0.45 to 0.98"],
                    }
                ],
                "evidence_map": {},
                "confidence": 0.88,
                "missing_information": [],
            }
        ),
    )

    assert result.root_cause_hypotheses[0].status == "likely"
    assert result.evidence_map


def test_fix_planner_agent_accepts_llm_json() -> None:
    root = RootCauseAnalysis(
        root_cause_hypotheses=[
            RootCauseHypothesis(
                cause="Database connection pool exhaustion.",
                status="likely",
                confidence=0.88,
                evidence=["pool usage high"],
            )
        ],
        confidence=0.88,
    )

    result = plan_fix_with_llm(
        root,
        client=FakeLLMClient(
            {
                "diagnostic_steps": ["Check pool wait time."],
                "recommended_actions": ["Reduce pressure before config changes."],
                "rollback_plan": ["Prepare rollback for the last deployment."],
                "verification_steps": ["Verify error rate returns to baseline."],
                "risk_level": "high",
                "requires_human_approval": False,
            }
        ),
    )

    assert result.risk_level == "high"
    assert result.requires_human_approval is True


def test_reviewer_agent_accepts_llm_json() -> None:
    root = RootCauseAnalysis(
        root_cause_hypotheses=[
            RootCauseHypothesis(
                cause="Database connection pool exhaustion.",
                status="likely",
                confidence=0.88,
                evidence=["pool usage high"],
            )
        ],
        confidence=0.88,
    )
    plan = FixPlan(
        diagnostic_steps=["Check pool wait time."],
        recommended_actions=["Reduce request pressure."],
        rollback_plan=["Prepare rollback."],
        verification_steps=["Verify error rate."],
        risk_level="high",
        requires_human_approval=True,
    )

    result = review_with_llm(
        root,
        plan,
        client=FakeLLMClient(
            {
                "approved": True,
                "review_notes": ["Evidence is sufficient and high-risk action is gated."],
                "quality_score": 0.9,
                "evidence_score": 0.9,
                "safety_score": 0.8,
                "required_revisions": [],
            }
        ),
    )

    assert isinstance(result, ReviewResult)
    assert result.approved is True

