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
        index: str,
        query_body: dict[str, Any],
    ) -> dict[str, Any]:
        calls.append({"base_url": base_url, "api_key": api_key, "index": index, "body": query_body})
        if index == "fireguard-firms":
            return {
                "hits": {"total": {"value": 12}},
                "aggregations": {
                    "min_time": {"value_as_string": "2026-06-01T00:00:00Z"},
                    "max_time": {"value_as_string": "2026-06-02T00:00:00Z"},
                    "sources": {"buckets": [{"key": "VIIRS_SNPP_NRT", "doc_count": 7}]},
                },
            }
        if index == "fireguard-bcws-incidents":
            return {"hits": {"total": {"value": 3}, "hits": []}}
        if index == "fireguard-bcws-perimeters":
            return {"hits": {"total": {"value": 2}, "hits": []}}
        raise AssertionError(index)

    original = tools_module._elastic_mcp_search
    tools_module._elastic_mcp_search = elastic_stub
    try:
        output = _invoke("fireguard_stats")
    finally:
        tools_module._elastic_mcp_search = original

    assert output["firms_count"] == 12
    assert output["bcws_incident_count"] == 3
    assert output["bcws_perimeter_count"] == 2
    assert output["sources"] == [{"source": "VIIRS_SNPP_NRT", "count": 7}]
    assert [call["index"] for call in calls] == [
        "fireguard-firms",
        "fireguard-bcws-incidents",
        "fireguard-bcws-perimeters",
    ]


def test_fireguard_search_events_builds_geo_and_date_filters() -> None:
    captured: dict[str, Any] = {}

    async def elastic_stub(
        base_url: str,
        api_key: str,
        index: str,
        query_body: dict[str, Any],
    ) -> dict[str, Any]:
        del base_url, api_key
        captured["index"] = index
        captured["body"] = query_body
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

    original = tools_module._elastic_mcp_search
    tools_module._elastic_mcp_search = elastic_stub
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
        tools_module._elastic_mcp_search = original

    assert captured["index"] == "fireguard-firms"
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


def test_fireguard_search_shelters_builds_geo_status_filter() -> None:
    captured: dict[str, Any] = {}

    async def elastic_stub(
        base_url: str,
        api_key: str,
        index: str,
        query_body: dict[str, Any],
    ) -> dict[str, Any]:
        del base_url, api_key
        captured["index"] = index
        captured["body"] = query_body
        return {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "facility_id": "ESS-1",
                            "name": "Reception Centre",
                            "facility_type": "reception_centre",
                            "address": "1 Main St",
                            "community": "Kamloops",
                            "municipality": "Kamloops",
                            "status": "OPEN",
                            "location": {"lat": 50.7, "lon": -120.4},
                            "capacity": 120,
                            "unused": "ignored",
                        }
                    }
                ]
            }
        }

    original = tools_module._elastic_mcp_search
    tools_module._elastic_mcp_search = elastic_stub
    try:
        output = _invoke(
            "fireguard_search_shelters",
            {
                "latitude": 50.7,
                "longitude": -120.4,
                "radius_km": 25,
                "status_filter": "OPEN",
                "size": 5,
            },
        )
    finally:
        tools_module._elastic_mcp_search = original

    assert captured["index"] == "fireguard-shelters"
    filters = captured["body"]["query"]["bool"]["filter"]
    assert filters[0]["geo_distance"]["distance"] == "25.0km"
    assert {"term": {"status": "OPEN"}} in filters
    assert captured["body"]["sort"][0]["_geo_distance"]["order"] == "asc"
    assert output["count"] == 1
    assert output["shelters"] == [
        {
            "facility_id": "ESS-1",
            "name": "Reception Centre",
            "facility_type": "reception_centre",
            "address": "1 Main St",
            "community": "Kamloops",
            "municipality": "Kamloops",
            "status": "OPEN",
            "location": {"lat": 50.7, "lon": -120.4},
            "capacity": 120,
            "distance_km": 0.0,
        }
    ]


def test_fireguard_search_road_events_builds_geo_query() -> None:
    captured: dict[str, Any] = {}

    async def elastic_stub(
        base_url: str,
        api_key: str,
        index: str,
        query_body: dict[str, Any],
    ) -> dict[str, Any]:
        del base_url, api_key
        captured["index"] = index
        captured["body"] = query_body
        return {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "event_id": "DBC-1",
                            "title": "Highway 97 closed",
                            "description": "Road closed in both directions",
                            "road_name": "Highway 97",
                            "event_type": "closure",
                            "severity": "major",
                            "status": "ACTIVE",
                            "location": {"lat": 50.7, "lon": -120.4},
                            "geometry": {"type": "Point", "coordinates": [-120.4, 50.7]},
                            "unused": "ignored",
                        }
                    }
                ]
            }
        }

    original = tools_module._elastic_mcp_search
    tools_module._elastic_mcp_search = elastic_stub
    try:
        output = _invoke(
            "fireguard_search_road_events",
            {"latitude": 50.7, "longitude": -120.4, "radius_km": 25, "size": 5},
        )
    finally:
        tools_module._elastic_mcp_search = original

    assert captured["index"] == "fireguard-road-events"
    filters = captured["body"]["query"]["bool"]["filter"]
    assert filters[0]["geo_distance"]["distance"] == "25.0km"
    assert captured["body"]["sort"][0]["_geo_distance"]["order"] == "asc"
    assert output["count"] == 1
    assert output["road_events"][0]["event_id"] == "DBC-1"
    assert output["road_events"][0]["distance_km"] == 0.0


def test_fireguard_evaluate_route_checks_fires_road_events_and_hypotheticals() -> None:
    calls: list[dict[str, Any]] = []

    async def elastic_stub(
        base_url: str,
        api_key: str,
        index: str,
        query_body: dict[str, Any],
    ) -> dict[str, Any]:
        del base_url, api_key
        calls.append({"index": index, "body": query_body})
        if index == "fireguard-firms":
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "latitude": 50.0,
                                "longitude": -119.5,
                                "frp": 16.5,
                                "acquired_at": "2026-06-01T12:00:00Z",
                            }
                        }
                    ]
                }
            }
        if index == "fireguard-road-events":
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "event_id": "DBC-1",
                                "title": "Highway 97 closed",
                                "description": "Road closed in both directions",
                                "road_name": "Highway 97",
                                "event_type": "closure",
                                "severity": "major",
                                "location": {"lat": 50.0, "lon": -119.5},
                            }
                        }
                    ]
                }
            }
        raise AssertionError(index)

    original = tools_module._elastic_mcp_search
    tools_module._elastic_mcp_search = elastic_stub
    try:
        output = _invoke(
            "fireguard_evaluate_route",
            {
                "origin_lat": 50.0,
                "origin_lon": -120.0,
                "destination_lat": 50.0,
                "destination_lon": -119.0,
                "start_date": "2026-06-01",
                "end_date": "2026-06-02",
                "hypothetical_closures": [
                    {"lat": 50.0, "lon": -119.25, "label": "Highway 97"}
                ],
            },
        )
    finally:
        tools_module._elastic_mcp_search = original

    assert [call["index"] for call in calls] == [
        "fireguard-firms",
        "fireguard-road-events",
    ]
    fire_filters = calls[0]["body"]["query"]["bool"]["filter"]
    assert {"range": {"acquired_at": {"gte": "2026-06-01", "lte": "2026-06-02"}}} in fire_filters
    assert output["route_source"] == "deterministic_straight_line"
    assert output["safe"] is False
    assert len(output["polyline"]) == 5
    assert {item["type"] for item in output["evidence"]} == {
        "fire",
        "road_closure",
        "hypothetical_closure",
    }


def test_fireguard_bcws_context_reads_incidents_and_perimeters() -> None:
    calls: list[dict[str, Any]] = []

    async def elastic_stub(
        base_url: str,
        api_key: str,
        index: str,
        query_body: dict[str, Any],
    ) -> dict[str, Any]:
        del base_url, api_key
        calls.append({"index": index, "body": query_body})
        if index == "fireguard-bcws-incidents":
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
        if index == "fireguard-bcws-perimeters":
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
        raise AssertionError(index)

    original = tools_module._elastic_mcp_search
    tools_module._elastic_mcp_search = elastic_stub
    try:
        output = _invoke(
            "fireguard_bcws_context",
            {"latitude": 49.2, "longitude": -123.2, "radius_km": 25, "size": 5},
        )
    finally:
        tools_module._elastic_mcp_search = original

    assert [call["index"] for call in calls] == [
        "fireguard-bcws-incidents",
        "fireguard-bcws-perimeters",
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
