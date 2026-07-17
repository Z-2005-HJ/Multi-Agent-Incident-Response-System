from __future__ import annotations

from typing import Any

#计算指标波动
def numeric_delta(value: Any) -> tuple[float | int | None, float | int | None, float | None]:
    if not isinstance(value, dict):
        return None, None, None
    before = value.get("before")
    after = value.get("after")
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return before, after, None
    if before == 0:
        return before, after, None
    return before, after, round((after - before) / abs(before), 3)

#计算指标严重等级
def metric_severity(metric_name: str, change_ratio: float | None, after: float | int | None) -> str:
    if change_ratio is None:
        return "low"
    name = metric_name.lower()
    if name in {"error_rate", "db_connection_pool_usage"} and after is not None and after >= 0.9:
        return "high"
    if change_ratio >= 3:
        return "high"
    if change_ratio >= 1:
        return "medium"
    return "low"

