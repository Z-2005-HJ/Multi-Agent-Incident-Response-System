from __future__ import annotations

from typing import Any

import httpx

from app.schemas.incident import IncidentRequest
from app.tools.external_tools import query_prometheus_http
from app.tools.settings import ToolSettings


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakePrometheusClient:
    def __init__(self, *args, **kwargs) -> None:
        self.requests: list[tuple[str, dict[str, Any] | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def get(self, url: str, params: dict[str, Any] | None = None):
        self.requests.append((url, params))
        return FakeResponse(
            {
                "status": "success",
                "data": {
                    "result": [
                        {
                            "value": [1718706060, "0.97"],
                        }
                    ]
                },
            }
        )


def test_prometheus_http_client_parses_query_result(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "Client", FakePrometheusClient)
    request = IncidentRequest(
        service_name="checkout-api",
        alert_description="error rate increased",
        metrics={"db_connection_pool_usage": {"before": 0.45, "after": 0.8}},
    )
    settings = ToolSettings(
        prometheus_base_url="http://prometheus.local",
        prometheus_query_template='{metric_name}{service="{service_name}"}',
    )

    findings = query_prometheus_http(request, settings)

    assert findings
    assert findings[0].metric_name == "db_connection_pool_usage"
    assert findings[0].value == 0.97
    assert findings[0].severity == "high"
    assert findings[0].query == 'db_connection_pool_usage{service="checkout-api"}'
