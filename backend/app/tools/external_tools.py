from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.schemas.incident import (
    DeploymentEvent,
    ExternalToolContext,
    IncidentRequest,
    LogSearchHit,
    PrometheusFinding,
)
from app.tools.log_tools import important_lines
from app.tools.metric_tools import metric_severity, numeric_delta
from app.tools.settings import ToolSettings, get_tool_settings


class ExternalToolUnavailable(RuntimeError):
    """Raised when a configured external tool cannot return usable data."""


def _timestamp_from_line(line: str) -> str | None:
    first = line.split(maxsplit=1)[0] if line.strip() else ""
    return first if "T" in first and first.endswith("Z") else None


def _auth_headers(token: str | None, scheme: str = "Bearer") -> dict[str, str]:
    return {"Authorization": f"{scheme} {token}"} if token else {}


def _format_template(template: str, request: IncidentRequest, metric_name: str | None = None) -> str:
    replacements = {
        "{service_name}": request.service_name,
        "{service}": request.service_name,
        "{metric_name}": metric_name or "",
        "{metric}": metric_name or "",
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def _parse_level(message: str) -> str:
    upper = message.upper()
    if "CRITICAL" in upper:
        return "CRITICAL"
    if "ERROR" in upper:
        return "ERROR"
    if "WARN" in upper:
        return "WARN"
    if "INFO" in upper:
        return "INFO"
    return "UNKNOWN"


def _matched_terms(message: str) -> list[str]:
    return [
        term
        for term in ("timeout", "connection", "pool", "database", "deployment", "rollback", "payment")
        if term in message.lower()
    ]


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _window_start_end(request: IncidentRequest) -> tuple[str | None, str | None]:
    if request.time_window and "/" in request.time_window:
        start, end = request.time_window.split("/", maxsplit=1)
        return start or None, end or None
    return None, None


def query_prometheus_mock(request: IncidentRequest) -> list[PrometheusFinding]:
    findings: list[PrometheusFinding] = []
    for metric_name, value in request.metrics.items():
        before, after, change_ratio = numeric_delta(value)
        if change_ratio is None:
            continue
        severity = metric_severity(metric_name, change_ratio, after)
        if severity == "low":
            continue
        query = f'{metric_name}{{service="{request.service_name}"}}'
        findings.append(
            PrometheusFinding(
                metric_name=metric_name,
                query=query,
                value=after,
                baseline=before,
                severity=severity,
                summary=f"{metric_name} moved from {before} to {after} during the incident window.",
            )
        )
    return findings[:8]


def query_prometheus_http(request: IncidentRequest, settings: ToolSettings | None = None) -> list[PrometheusFinding]:
    settings = settings or get_tool_settings()
    if not settings.prometheus_enabled or not settings.prometheus_base_url:
        raise ExternalToolUnavailable("prometheus_not_configured")

    findings: list[PrometheusFinding] = []
    base_url = settings.prometheus_base_url.rstrip("/")
    headers = _auth_headers(settings.prometheus_bearer_token)
    metric_names = [name for name, value in request.metrics.items() if isinstance(value, dict)]
    if not metric_names:
        metric_names = ["error_rate", "p95_latency_ms", "db_connection_pool_usage"]

    with httpx.Client(timeout=settings.timeout_seconds, headers=headers) as client:
        for metric_name in metric_names[:8]:
            query = _format_template(settings.prometheus_query_template, request, metric_name)
            response = client.get(f"{base_url}/api/v1/query", params={"query": query})
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "success":
                raise ExternalToolUnavailable("prometheus_query_failed")
            results = payload.get("data", {}).get("result", [])
            value = None
            if results:
                sample = results[0].get("value", [])
                if len(sample) >= 2:
                    value = _float_or_none(sample[1])

            before, metric_after, change_ratio = numeric_delta(request.metrics.get(metric_name, {}))
            after = value if value is not None else metric_after
            if isinstance(before, (int, float)) and isinstance(after, (int, float)) and before != 0:
                change_ratio = round((after - before) / abs(before), 3)
            severity = metric_severity(metric_name, change_ratio, after)
            if severity == "low" and value is None:
                continue
            findings.append(
                PrometheusFinding(
                    metric_name=metric_name,
                    query=query,
                    value=after,
                    baseline=before,
                    severity=severity,
                    summary=f"Prometheus returned {metric_name}={after} for {request.service_name}.",
                )
            )
    return findings


def search_logs_mock(request: IncidentRequest) -> list[LogSearchHit]:
    hits: list[LogSearchHit] = []
    for line in important_lines(request.raw_logs, limit=10):
        hits.append(
            LogSearchHit(
                timestamp=_timestamp_from_line(line),
                source="loki",
                level=_parse_level(line),
                message=line,
                matched_terms=_matched_terms(line),
            )
        )
    return hits


def search_loki_http(request: IncidentRequest, settings: ToolSettings | None = None) -> list[LogSearchHit]:
    settings = settings or get_tool_settings()
    if not settings.loki_enabled or not settings.loki_base_url:
        raise ExternalToolUnavailable("loki_not_configured")

    base_url = settings.loki_base_url.rstrip("/")
    query = _format_template(settings.loki_query_template, request)
    start, end = _window_start_end(request)
    params: dict[str, str | int] = {"query": query, "limit": 20}
    if start:
        params["start"] = start
    if end:
        params["end"] = end

    with httpx.Client(timeout=settings.timeout_seconds, headers=_auth_headers(settings.loki_bearer_token)) as client:
        response = client.get(f"{base_url}/loki/api/v1/query_range", params=params)
        response.raise_for_status()
        payload = response.json()

    if payload.get("status") != "success":
        raise ExternalToolUnavailable("loki_query_failed")

    hits: list[LogSearchHit] = []
    for stream in payload.get("data", {}).get("result", []):
        for timestamp_ns, line in stream.get("values", [])[:20]:
            timestamp = None
            try:
                timestamp = datetime.fromtimestamp(int(timestamp_ns) / 1_000_000_000, timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                pass
            hits.append(
                LogSearchHit(
                    timestamp=timestamp,
                    source="loki",
                    level=_parse_level(str(line)),
                    message=str(line),
                    matched_terms=_matched_terms(str(line)),
                )
            )
    return hits[:20]


def search_elasticsearch_http(request: IncidentRequest, settings: ToolSettings | None = None) -> list[LogSearchHit]:
    settings = settings or get_tool_settings()
    if not settings.elasticsearch_enabled or not settings.elasticsearch_base_url:
        raise ExternalToolUnavailable("elasticsearch_not_configured")

    base_url = settings.elasticsearch_base_url.rstrip("/")
    headers = _auth_headers(settings.elasticsearch_api_key, scheme="ApiKey")
    query_text = f'{request.service_name} {request.alert_description} ERROR timeout connection'
    body = {
        "size": 20,
        "query": {
            "bool": {
                "should": [
                    {"match_phrase": {"service.name": request.service_name}},
                    {"match_phrase": {"service": request.service_name}},
                    {"query_string": {"query": query_text}},
                ],
                "minimum_should_match": 1,
            }
        },
        "sort": [{"@timestamp": {"order": "desc"}}],
    }

    with httpx.Client(timeout=settings.timeout_seconds, headers=headers) as client:
        response = client.post(f"{base_url}/{settings.elasticsearch_index}/_search", json=body)
        response.raise_for_status()
        payload = response.json()

    hits: list[LogSearchHit] = []
    for item in payload.get("hits", {}).get("hits", [])[:20]:
        source = item.get("_source", {})
        message = str(source.get("message") or source.get("log") or item.get("_source") or "")
        hits.append(
            LogSearchHit(
                timestamp=source.get("@timestamp"),
                source="elasticsearch",
                level=_parse_level(message),
                message=message,
                matched_terms=_matched_terms(message),
            )
        )
    return hits


def search_logs_http(request: IncidentRequest, settings: ToolSettings | None = None) -> list[LogSearchHit]:
    settings = settings or get_tool_settings()
    if settings.log_search_provider == "elasticsearch":
        return search_elasticsearch_http(request, settings)
    if settings.log_search_provider == "loki":
        return search_loki_http(request, settings)
    if settings.loki_enabled:
        return search_loki_http(request, settings)
    if settings.elasticsearch_enabled:
        return search_elasticsearch_http(request, settings)
    raise ExternalToolUnavailable("log_search_not_configured")


def get_deployment_history_mock(request: IncidentRequest) -> list[DeploymentEvent]:
    lowered = f"{request.alert_description}\n{request.raw_logs}".lower()
    has_deployment_signal = any(term in lowered for term in ("deploy", "deployment", "release", "rollback"))
    if not has_deployment_signal and request.service_name != "checkout-api":
        return []

    deployed_at = "2026-06-18T10:18:00Z"
    if request.time_window and "/" in request.time_window:
        deployed_at = request.time_window.split("/", maxsplit=1)[0]

    risk_flags = ["recent_deployment"]
    if any(term in lowered for term in ("database", "connection pool", "db_connection_pool")):
        risk_flags.append("database_config_change")

    return [
        DeploymentEvent(
            service_name=request.service_name,
            version="checkout-api-2026.06.18-rc2",
            commit_sha="8f4c2a1",
            author="release-bot",
            deployed_at=deployed_at,
            environment="production",
            summary="Mock Git history found a recent checkout-api deployment near the alert window.",
            risk_flags=risk_flags,
        )
    ]


def get_github_deployment_history_http(
    request: IncidentRequest,
    settings: ToolSettings | None = None,
) -> list[DeploymentEvent]:
    settings = settings or get_tool_settings()
    if not settings.github_enabled or not settings.github_repository:
        raise ExternalToolUnavailable("github_not_configured")

    repository = settings.github_repository.strip("/")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        **_auth_headers(settings.github_token),
    }
    params = {
        "sha": settings.github_branch,
        "per_page": max(1, min(settings.github_lookback_commits, 30)),
    }
    with httpx.Client(timeout=settings.timeout_seconds, headers=headers) as client:
        response = client.get(f"https://api.github.com/repos/{repository}/commits", params=params)
        response.raise_for_status()
        commits = response.json()

    events: list[DeploymentEvent] = []
    for item in commits[: settings.github_lookback_commits]:
        commit = item.get("commit", {})
        author = commit.get("author", {}) or {}
        message = str(commit.get("message", "")).splitlines()[0]
        sha = str(item.get("sha", ""))[:7]
        lowered = message.lower()
        risk_flags = ["recent_commit"]
        if any(term in lowered for term in ("deploy", "release", "rollback")):
            risk_flags.append("deployment_related")
        if any(term in lowered for term in ("db", "database", "pool", "connection")):
            risk_flags.append("database_related_change")

        events.append(
            DeploymentEvent(
                service_name=request.service_name,
                version=message or sha,
                commit_sha=sha,
                author=str(author.get("name") or "unknown"),
                deployed_at=str(author.get("date") or ""),
                environment="production",
                summary=f"GitHub commit {sha} on {settings.github_branch}: {message or 'no commit message'}",
                risk_flags=risk_flags,
            )
        )
    return events


def _with_fallback(
    real_call,
    mock_call,
    source_name: str,
    request: IncidentRequest,
    settings: ToolSettings,
    errors: list[str],
    sources: dict[str, str],
):
    if settings.mode == "mock":
        sources[source_name] = "mock"
        return mock_call(request)
    try:
        result = real_call(request, settings)
        sources[source_name] = "real"
        return result
    except Exception as exc:
        if isinstance(exc, ExternalToolUnavailable) and "not_configured" in str(exc):
            sources[source_name] = "mock"
            return mock_call(request)
        sources[source_name] = "mock_fallback"
        errors.append(f"{source_name}:{exc.__class__.__name__}")
        return mock_call(request)


def collect_external_tool_context(request: IncidentRequest) -> ExternalToolContext:
    settings = get_tool_settings()
    errors: list[str] = []
    sources: dict[str, str] = {}

    prometheus_findings = _with_fallback(
        query_prometheus_http,
        query_prometheus_mock,
        "prometheus",
        request,
        settings,
        errors,
        sources,
    )
    log_search_hits = _with_fallback(
        search_logs_http,
        search_logs_mock,
        "log_search",
        request,
        settings,
        errors,
        sources,
    )
    deployment_events = _with_fallback(
        get_github_deployment_history_http,
        get_deployment_history_mock,
        "github",
        request,
        settings,
        errors,
        sources,
    )

    return ExternalToolContext(
        prometheus_findings=prometheus_findings,
        log_search_hits=log_search_hits,
        deployment_events=deployment_events,
        tool_sources=sources,
        tool_errors=errors,
    )
