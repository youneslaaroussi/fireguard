from __future__ import annotations

import asyncio
from typing import Any

from app.agentic import tools as tools_module
from app.agentic.models import ToolInvocation
from app.agentic.tools import build_base_tool_registry


def _invoke(tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = build_base_tool_registry(
        default_timeout_seconds=5,
        max_parallel_tools=4,
        fireguard_elasticsearch_url="http://elastic.invalid",
        fireguard_elasticsearch_api_key="test-key",
        fireguard_elasticsearch_index_prefix="fireguard",
    )
    result = asyncio.run(
        registry.run_tools(
            [
                ToolInvocation(
                    invocation_id=f"tool_{tool_name}",
                    tool_name=tool_name,
                    session_id="ses_test",
                    run_id="run_test",
                    node_id="research_agent",
                    agent_id="research_agent",
                    args=args or {},
                )
            ]
        )
    )[0]
    assert result.ok is True, result.output
    return result.output


def test_fireguard_stats_returns_counts_and_source_buckets() -> None:
    calls: list[dict[str, Any]] = []

    async def elastic_stub(
        base_url: str,
        api_key: str,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        calls.append({"base_url": base_url, "api_key": api_key, "method": method, "path": path, "body": body})
        if path == "/fireguard-firms/_search":
            return {
                "hits": {"total": {"value": 12}},
                "aggregations": {
                    "min_time": {"value_as_string": "2026-06-01T00:00:00Z"},
                    "max_time": {"value_as_string": "2026-06-02T00:00:00Z"},
                    "sources": {"buckets": [{"key": "VIIRS_SNPP_NRT", "doc_count": 7}]},
                },
            }
        if path == "/fireguard-bcws-incidents/_count":
            return {"count": 3}
        if path == "/fireguard-bcws-perimeters/_count":
            return {"count": 2}
        raise AssertionError(path)

    original = tools_module._elastic_request
    tools_module._elastic_request = elastic_stub
    try:
        output = _invoke("fireguard_stats")
    finally:
        tools_module._elastic_request = original

    assert output["firms_count"] == 12
    assert output["bcws_incident_count"] == 3
    assert output["bcws_perimeter_count"] == 2
    assert output["sources"] == [{"source": "VIIRS_SNPP_NRT", "count": 7}]
    assert [call["path"] for call in calls] == [
        "/fireguard-firms/_search",
        "/fireguard-bcws-incidents/_count",
        "/fireguard-bcws-perimeters/_count",
    ]


def test_fireguard_search_events_builds_geo_and_date_filters() -> None:
    captured: dict[str, Any] = {}

    async def elastic_stub(
        base_url: str,
        api_key: str,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del base_url, api_key, method
        captured["path"] = path
        captured["body"] = body
        return {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "source": "VIIRS_SNPP_NRT",
                            "acquired_at": "2026-06-01T12:00:00Z",
                            "latitude": 49.1,
                            "longitude": -123.1,
                            "confidence": "n",
                            "frp": 11.2,
                            "unused": "ignored",
                        }
                    }
                ]
            }
        }

    original = tools_module._elastic_request
    tools_module._elastic_request = elastic_stub
    try:
        output = _invoke(
            "fireguard_search_events",
            {
                "latitude": 49.2,
                "longitude": -123.2,
                "radius_km": 75,
                "start_date": "2026-06-01",
                "end_date": "2026-06-03",
                "sources": ["VIIRS_SNPP_NRT"],
                "size": 10,
            },
        )
    finally:
        tools_module._elastic_request = original

    assert captured["path"] == "/fireguard-firms/_search"
    filters = captured["body"]["query"]["bool"]["filter"]
    assert filters[0]["geo_distance"]["distance"] == "75.0km"
    assert {"range": {"acquired_at": {"gte": "2026-06-01", "lte": "2026-06-03"}}} in filters
    assert {"terms": {"source": ["VIIRS_SNPP_NRT"]}} in filters
    assert output["count"] == 1
    assert output["events"] == [
        {
            "source": "VIIRS_SNPP_NRT",
            "acquired_at": "2026-06-01T12:00:00Z",
            "latitude": 49.1,
            "longitude": -123.1,
            "confidence": "n",
            "frp": 11.2,
        }
    ]


def test_fireguard_bcws_context_reads_incidents_and_perimeters() -> None:
    calls: list[dict[str, Any]] = []

    async def elastic_stub(
        base_url: str,
        api_key: str,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del base_url, api_key, method
        calls.append({"path": path, "body": body})
        if path == "/fireguard-bcws-incidents/_search":
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "fire_number": "V12345",
                                "incident_name": "Sample Ridge",
                                "latitude": 49.2,
                                "longitude": -123.2,
                                "fire_status": None,
                            }
                        }
                    ]
                }
            }
        if path == "/fireguard-bcws-perimeters/_search":
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "fire_number": "V12345",
                                "fire_status": "Out",
                                "fire_size_hectares": 42,
                            }
                        }
                    ]
                }
            }
        raise AssertionError(path)

    original = tools_module._elastic_request
    tools_module._elastic_request = elastic_stub
    try:
        output = _invoke(
            "fireguard_bcws_context",
            {"latitude": 49.2, "longitude": -123.2, "radius_km": 25, "size": 5},
        )
    finally:
        tools_module._elastic_request = original

    assert [call["path"] for call in calls] == [
        "/fireguard-bcws-incidents/_search",
        "/fireguard-bcws-perimeters/_search",
    ]
    assert calls[0]["body"]["query"]["bool"]["filter"][0]["geo_bounding_box"]["location"]
    assert calls[1]["body"]["query"]["geo_shape"]["geometry"]["relation"] == "intersects"
    assert output["incidents"] == [
        {
            "fire_number": "V12345",
            "incident_name": "Sample Ridge",
            "latitude": 49.2,
            "longitude": -123.2,
        }
    ]
    assert output["perimeters"] == [
        {"fire_number": "V12345", "fire_status": "Out", "fire_size_hectares": 42}
    ]
