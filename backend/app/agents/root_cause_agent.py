from __future__ import annotations

from typing import Any

from app.llm.client import LLMError, OpenAICompatibleClient
from app.llm.settings import get_llm_settings
from app.prompts.loader import load_prompt, prompt_version
from app.schemas.incident import (
    KnowledgeResults,
    LogAnalysis,
    MetricAnalysis,
    RootCauseAnalysis,
    RootCauseHypothesis,
    ExternalToolContext,
)
from pydantic import ValidationError


def _llm_metadata(client: OpenAICompatibleClient, prompt_name: str) -> dict[str, Any]:
    metadata = dict(client.last_call_metadata)
    metadata["prompt_version"] = prompt_version(prompt_name)
    metadata["privacy_mode"] = get_llm_settings().privacy_mode
    return metadata


def _root_cause_payload(
    log_analysis: LogAnalysis,
    metric_analysis: MetricAnalysis,
    knowledge_results: KnowledgeResults,
    tool_context: ExternalToolContext | None = None,
) -> dict[str, Any]:
    settings = get_llm_settings()
    if settings.privacy_mode == "strict":
        return {
            "privacy_mode": "strict",
            "log_analysis": {
                "error_patterns": log_analysis.error_patterns,
                "suspected_components": log_analysis.suspected_components,
                "log_confidence": log_analysis.log_confidence,
                "important_log_line_count": len(log_analysis.important_log_lines),
            },
            "metric_analysis": metric_analysis.model_dump(mode="json"),
            "knowledge_results": {
                "known_failure_modes": knowledge_results.known_failure_modes,
                "source_references": knowledge_results.source_references,
                "retrieval_mode": knowledge_results.retrieval_mode,
                "retrieval_confidence": knowledge_results.retrieval_confidence,
            },
            "external_tool_context": _strict_tool_context(tool_context),
        }
    return {
        "privacy_mode": settings.privacy_mode,
        "log_analysis": log_analysis.model_dump(mode="json"),
        "metric_analysis": metric_analysis.model_dump(mode="json"),
        "knowledge_results": knowledge_results.model_dump(mode="json"),
        "external_tool_context": tool_context.model_dump(mode="json") if tool_context else {},
    }


def _strict_tool_context(tool_context: ExternalToolContext | None) -> dict[str, Any]:
    if tool_context is None:
        return {}
    return {
        "prometheus_findings": [
            {
                "metric_name": item.metric_name,
                "value": item.value,
                "baseline": item.baseline,
                "severity": item.severity,
                "summary": item.summary,
            }
            for item in tool_context.prometheus_findings
        ],
        "log_search_hit_count": len(tool_context.log_search_hits),
        "log_matched_terms": sorted({term for hit in tool_context.log_search_hits for term in hit.matched_terms}),
        "deployment_events": [
            {
                "service_name": item.service_name,
                "version": item.version,
                "deployed_at": item.deployed_at,
                "risk_flags": item.risk_flags,
                "summary": item.summary,
            }
            for item in tool_context.deployment_events
        ],
        "tool_errors": tool_context.tool_errors,
    }


def infer_root_cause(
    log_analysis: LogAnalysis,
    metric_analysis: MetricAnalysis,
    knowledge_results: KnowledgeResults,
    tool_context: ExternalToolContext | None = None,
) -> RootCauseAnalysis:
    result, _metadata = infer_root_cause_with_metadata(log_analysis, metric_analysis, knowledge_results, tool_context)
    return result


def infer_root_cause_with_metadata(
    log_analysis: LogAnalysis,
    metric_analysis: MetricAnalysis,
    knowledge_results: KnowledgeResults,
    tool_context: ExternalToolContext | None = None,
) -> tuple[RootCauseAnalysis, dict[str, Any]]:
    try:
        client = OpenAICompatibleClient()
        return infer_root_cause_with_llm(log_analysis, metric_analysis, knowledge_results, tool_context, client=client), {
            "execution_mode": "llm",
            "fallback_reason": None,
            **_llm_metadata(client, "root_cause.md"),
        }
    except (LLMError, ValidationError) as exc:
        client = locals().get("client")
        llm_error_metadata = dict(getattr(client, "last_call_metadata", {}))
        return infer_root_cause_rule(log_analysis, metric_analysis, knowledge_results, tool_context), {
            "execution_mode": "rule_fallback",
            "fallback_reason": str(exc),
            "llm_error_type": llm_error_metadata.get("llm_error_type") or exc.__class__.__name__,
            "privacy_mode": get_llm_settings().privacy_mode,
            "prompt_version": prompt_version("root_cause.md"),
        }


def infer_root_cause_with_llm(
    log_analysis: LogAnalysis,
    metric_analysis: MetricAnalysis,
    knowledge_results: KnowledgeResults,
    tool_context: ExternalToolContext | None = None,
    client: OpenAICompatibleClient | None = None,
) -> RootCauseAnalysis:
    llm = client or OpenAICompatibleClient()
    if not llm.is_enabled():
        raise LLMError("LLM is disabled.")

    payload = _root_cause_payload(log_analysis, metric_analysis, knowledge_results, tool_context)
    data = llm.json_chat(
        [
            {"role": "system", "content": load_prompt("root_cause.md")},
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
    tool_context: ExternalToolContext | None = None,
) -> RootCauseAnalysis:
    evidence: list[str] = []
    evidence.extend(log_analysis.important_log_lines[:3])
    evidence.extend(
        f"{item.metric_name} changed from {item.before} to {item.after}"
        for item in metric_analysis.metric_anomalies[:3]
    )
    evidence.extend(f"knowledge:{source}" for source in knowledge_results.source_references[:3])
    if tool_context:
        evidence.extend(item.summary for item in tool_context.prometheus_findings[:3])
        evidence.extend(f"deployment:{item.version} flags={','.join(item.risk_flags)}" for item in tool_context.deployment_events[:2])

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

    if tool_context and any("recent_deployment" in item.risk_flags for item in tool_context.deployment_events):
        hypotheses.append(
            RootCauseHypothesis(
                cause="A recent deployment may have introduced a risky runtime or dependency configuration change.",
                status="possible",
                confidence=0.66,
                evidence=evidence[:5],
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
    if tool_context and tool_context.tool_errors:
        missing.extend(tool_context.tool_errors)

    return RootCauseAnalysis(
        root_cause_hypotheses=hypotheses,
        evidence_map={item.cause: item.evidence for item in hypotheses},
        confidence=confidence,
        missing_information=missing,
    )
