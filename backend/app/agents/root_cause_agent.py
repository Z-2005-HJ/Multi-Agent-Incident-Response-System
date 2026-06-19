from __future__ import annotations

from app.schemas.incident import (
    KnowledgeResults,
    LogAnalysis,
    MetricAnalysis,
    RootCauseAnalysis,
    RootCauseHypothesis,
)
from app.llm.client import LLMError, OpenAICompatibleClient
from pydantic import ValidationError


ROOT_CAUSE_SYSTEM_PROMPT = """You are a senior SRE root cause analyst.
Return JSON only. Do not include markdown.
The JSON object must match this shape:
{
  "root_cause_hypotheses": [
    {
      "cause": "short evidence-backed cause",
      "status": "confirmed|likely|possible",
      "confidence": 0.0,
      "evidence": ["evidence item"]
    }
  ],
  "evidence_map": {"cause text": ["evidence item"]},
  "confidence": 0.0,
  "missing_information": ["missing item"]
}
Use only the provided evidence. Do not invent production actions or facts."""


def infer_root_cause(
    log_analysis: LogAnalysis,
    metric_analysis: MetricAnalysis,
    knowledge_results: KnowledgeResults,
) -> RootCauseAnalysis:
    try:
        return infer_root_cause_with_llm(log_analysis, metric_analysis, knowledge_results)
    except (LLMError, ValidationError):
        return infer_root_cause_rule(log_analysis, metric_analysis, knowledge_results)


def infer_root_cause_with_llm(
    log_analysis: LogAnalysis,
    metric_analysis: MetricAnalysis,
    knowledge_results: KnowledgeResults,
    client: OpenAICompatibleClient | None = None,
) -> RootCauseAnalysis:
    llm = client or OpenAICompatibleClient()
    if not llm.is_enabled():
        raise LLMError("LLM is disabled.")

    payload = {
        "log_analysis": log_analysis.model_dump(mode="json"),
        "metric_analysis": metric_analysis.model_dump(mode="json"),
        "knowledge_results": knowledge_results.model_dump(mode="json"),
    }
    data = llm.json_chat(
        [
            {"role": "system", "content": ROOT_CAUSE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze this incident evidence:\n{payload}"},
        ],
        temperature=0.1,
    )
    result = RootCauseAnalysis.model_validate(data)
    if not result.evidence_map:
        result.evidence_map = {item.cause: item.evidence for item in result.root_cause_hypotheses}
    return result


def infer_root_cause_rule(
    log_analysis: LogAnalysis,
    metric_analysis: MetricAnalysis,
    knowledge_results: KnowledgeResults,
) -> RootCauseAnalysis:
    evidence: list[str] = []
    evidence.extend(log_analysis.important_log_lines[:3])
    evidence.extend(
        f"{item.metric_name} changed from {item.before} to {item.after}"
        for item in metric_analysis.metric_anomalies[:3]
    )
    evidence.extend(f"knowledge:{source}" for source in knowledge_results.source_references[:3])

    hypotheses: list[RootCauseHypothesis] = []
    components = set(log_analysis.suspected_components)
    metric_names = {item.metric_name for item in metric_analysis.metric_anomalies}
    known_modes = set(knowledge_results.known_failure_modes)

    if "database" in components or "db_connection_pool_usage" in metric_names or "database connection pool exhaustion" in known_modes:
        hypotheses.append(
            RootCauseHypothesis(
                cause="Database connection pool exhaustion in the impacted service.",
                status="likely",
                confidence=0.86,
                evidence=evidence,
            )
        )

    if any("error_rate" == item.metric_name for item in metric_analysis.metric_anomalies):
        hypotheses.append(
            RootCauseHypothesis(
                cause="Recent service behavior change increased request failures.",
                status="possible",
                confidence=0.62,
                evidence=evidence[:3],
            )
        )

    if not hypotheses:
        hypotheses.append(
            RootCauseHypothesis(
                cause="Insufficient evidence; manual investigation is required.",
                status="possible",
                confidence=0.35,
                evidence=evidence,
            )
        )

    confidence = max(item.confidence for item in hypotheses)
    missing = []
    if not knowledge_results.source_references:
        missing.append("No related knowledge base item was retrieved.")
    if not metric_analysis.metric_anomalies:
        missing.append("No structured metric anomaly was detected.")

    return RootCauseAnalysis(
        root_cause_hypotheses=hypotheses,
        evidence_map={item.cause: item.evidence for item in hypotheses},
        confidence=confidence,
        missing_information=missing,
    )
