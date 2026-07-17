from __future__ import annotations

import re
from collections import Counter


ERROR_TOKEN_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:Error|Exception|Timeout|Failure))\b")
TIMESTAMP_RE = re.compile(r"^\S+")

#important_lines这个函数就是从返回的很多内容里面找到含ERROR等类型的报错，然后保留前八条
def important_lines(raw_logs: str, limit: int = 8) -> list[str]:
    lines = [line.strip() for line in raw_logs.splitlines() if line.strip()]
    selected = [
        line
        for line in lines
        if any(level in line.upper() for level in ("ERROR", "WARN", "CRITICAL", "TIMEOUT"))
    ]
    return selected[:limit]

#接收 important_lines 筛选出来的关键报错日志行，提取日志里所有故障关键词，统计出现频次，
# 返回出现最多的前 6 种故障特征，给 AI 生成故障根因假设（hypothesis）提供核心线索。
def error_patterns(lines: list[str]) -> list[str]:
    tokens: list[str] = []
    for line in lines:
        tokens.extend(ERROR_TOKEN_RE.findall(line))
        if "connection pool" in line.lower():
            tokens.append("connection pool exhausted")
    counts = Counter(tokens)
    return [token for token, _ in counts.most_common(6)]

#接收日志/告警文本，通过内置关键词规则，识别出故障可能关联的后端组件，返回组件名称列表
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

#接收经过 important_lines 过滤后的关键日志行，提取每行开头时间戳，
# 组装成标准化时间线日志，最多返回前 8 条，用于故障报告里展示事件发生时序。
def timeline_from_lines(lines: list[str]) -> list[str]:
    timeline: list[str] = []
    for line in lines:
        match = TIMESTAMP_RE.match(line)
        if match:
            timeline.append(f"{match.group(0)} - {line}")
    return timeline[:8]

