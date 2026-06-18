from __future__ import annotations

import re
from collections import Counter


ERROR_TOKEN_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:Error|Exception|Timeout|Failure))\b")
TIMESTAMP_RE = re.compile(r"^\S+")


def important_lines(raw_logs: str, limit: int = 8) -> list[str]:
    lines = [line.strip() for line in raw_logs.splitlines() if line.strip()]
    selected = [
        line
        for line in lines
        if any(level in line.upper() for level in ("ERROR", "WARN", "CRITICAL", "TIMEOUT"))
    ]
    return selected[:limit]


def error_patterns(lines: list[str]) -> list[str]:
    tokens: list[str] = []
    for line in lines:
        tokens.extend(ERROR_TOKEN_RE.findall(line))
        if "connection pool" in line.lower():
            tokens.append("connection pool exhausted")
    counts = Counter(tokens)
    return [token for token, _ in counts.most_common(6)]


def suspected_components_from_text(text: str) -> list[str]:
    lowered = text.lower()
    components: list[str] = []
    rules = {
        "database": ["database", "db", "connection pool", "sql"],
        "payment": ["payment", "charge", "transaction"],
        "cache": ["redis", "cache"],
        "queue": ["queue", "kafka", "lag"],
        "network": ["timeout", "dns", "connection"],
    }
    for component, keywords in rules.items():
        if any(keyword in lowered for keyword in keywords):
            components.append(component)
    return components


def timeline_from_lines(lines: list[str]) -> list[str]:
    timeline: list[str] = []
    for line in lines:
        match = TIMESTAMP_RE.match(line)
        if match:
            timeline.append(f"{match.group(0)} - {line}")
    return timeline[:8]

