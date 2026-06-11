from __future__ import annotations

import asyncio
import json
import math
import mimetypes
import os
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .models import ToolDefinition, ToolInvocation, ToolResult

ToolHandler = Callable[[ToolInvocation], Awaitable[dict[str, Any]]]


class ToolRuntimeProtocol(Protocol):
    def available_tools(self, allowed_names: list[str]) -> list[ToolDefinition]:
        raise NotImplementedError

    async def run_tools(self, invocations: list[ToolInvocation]) -> list[ToolResult]:
        raise NotImplementedError


class SandboxManagerProtocol(Protocol):
    async def exec(
        self, session_id: str, command: list[str], *, timeout_seconds: float | None
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def write_file(self, session_id: str, path: str, content: str) -> dict[str, Any]:
        raise NotImplementedError

    async def read_file(self, session_id: str, path: str, *, max_bytes: int) -> dict[str, Any]:
        raise NotImplementedError

    async def export_asset(
        self, session_id: str, sandbox_path: str, assets_dir: Path
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def list_files(self, session_id: str, path: str, *, max_entries: int) -> dict[str, Any]:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self, *, default_timeout_seconds: float, max_parallel_tools: int) -> None:
        self._default_timeout_seconds = default_timeout_seconds
        self._max_parallel_tools = max_parallel_tools
        self._definitions: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}
        self._results: dict[str, ToolResult] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"tool {definition.name} is already registered")
        self._definitions[definition.name] = definition
        self._handlers[definition.name] = handler

    def available_tools(self, allowed_names: list[str]) -> list[ToolDefinition]:
        if len(allowed_names) == 0:
            return []
        tools: list[ToolDefinition] = []
        for name in allowed_names:
            definition = self._definitions.get(name)
            if definition is None:
                raise KeyError(f"agent requested unknown tool {name}")
            tools.append(definition)
        return tools

    async def run_tools(self, invocations: list[ToolInvocation]) -> list[ToolResult]:
        batches: list[list[ToolInvocation]] = []
        current: list[ToolInvocation] = []
        for invocation in invocations:
            definition = self._definition(invocation.tool_name)
            if definition.concurrency_safe and not definition.mutating:
                current.append(invocation)
                if len(current) >= self._max_parallel_tools:
                    batches.append(current)
                    current = []
                continue
            if len(current) > 0:
                batches.append(current)
                current = []
            batches.append([invocation])
        if len(current) > 0:
            batches.append(current)
        results: list[ToolResult] = []
        for batch in batches:
            if len(batch) == 1:
                results.append(await self._run_one(batch[0]))
            else:
                batch_results = await asyncio.gather(*(self._run_one(item) for item in batch))
                results.extend(batch_results)
        return results

    async def _run_one(self, invocation: ToolInvocation) -> ToolResult:
        previous = self._results.get(invocation.invocation_id)
        if previous is not None:
            return previous
        definition = self._definition(invocation.tool_name)
        handler = self._handlers[invocation.tool_name]
        started = datetime.now(UTC)
        try:
            timeout = definition.timeout_seconds
            if timeout is None:
                timeout = self._default_timeout_seconds
            output = await asyncio.wait_for(handler(invocation), timeout=timeout)
            result = ToolResult(
                invocation_id=invocation.invocation_id,
                tool_name=invocation.tool_name,
                ok=True,
                output=output,
                started_at=started,
                completed_at=datetime.now(UTC),
            )
        except Exception as exc:
            result = ToolResult(
                invocation_id=invocation.invocation_id,
                tool_name=invocation.tool_name,
                ok=False,
                output={"error": str(exc), "tool_name": invocation.tool_name},
                started_at=started,
                completed_at=datetime.now(UTC),
            )
        self._results[invocation.invocation_id] = result
        return result

    def _definition(self, tool_name: str) -> ToolDefinition:
        definition = self._definitions.get(tool_name)
        if definition is None:
            raise KeyError(f"unknown tool {tool_name}")
        return definition


def build_base_tool_registry(
    *,
    default_timeout_seconds: float,
    max_parallel_tools: int,
    exa_api_key: str = "",
    exa_base_url: str = "https://api.exa.ai",
    fireguard_elasticsearch_url: str = "",
    fireguard_elasticsearch_api_key: str = "",
    fireguard_elasticsearch_index_prefix: str = "fireguard",
    sandbox_manager: SandboxManagerProtocol | None = None,
    assets_dir_fn: Callable[[str], Path] | None = None,
) -> ToolRegistry:
    registry = ToolRegistry(
        default_timeout_seconds=default_timeout_seconds,
        max_parallel_tools=max_parallel_tools,
    )

    async def emit_message(invocation: ToolInvocation) -> dict[str, Any]:
        message = invocation.args.get("message")
        if not isinstance(message, str) or len(message.strip()) == 0:
            raise ValueError("message must be a non-empty string")
        return {"message": message}

    registry.register(
        ToolDefinition(
            name="emit_message",
            description="Emit a workflow-visible message.",
            parameters={
                "type": "object",
                "properties": {"message": {"type": "string", "minLength": 1}},
                "required": ["message"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
        ),
        emit_message,
    )

    async def fireguard_stats(invocation: ToolInvocation) -> dict[str, Any]:
        del invocation
        firms = await _elastic_search(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            fireguard_elasticsearch_index_prefix,
            "firms",
            {
                "size": 0,
                "track_total_hits": True,
                "aggs": {
                    "min_time": {"min": {"field": "acquired_at"}},
                    "max_time": {"max": {"field": "acquired_at"}},
                    "sources": {"terms": {"field": "source", "size": 20}},
                },
            },
        )
        incident_count = await _elastic_count(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            fireguard_elasticsearch_index_prefix,
            "bcws-incidents",
        )
        perimeter_count = await _elastic_count(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            fireguard_elasticsearch_index_prefix,
            "bcws-perimeters",
        )
        total = firms.get("hits", {}).get("total", 0)
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        aggs = firms.get("aggregations", {})
        buckets = aggs.get("sources", {}).get("buckets", [])
        if int(total_value or 0) == 0 and isinstance(buckets, list):
            total_value = sum(
                int(bucket.get("doc_count", 0))
                for bucket in buckets
                if isinstance(bucket, dict)
            )
        return {
            "indices": {
                "firms": _fireguard_index(fireguard_elasticsearch_index_prefix, "firms"),
                "bcws_incidents": _fireguard_index(
                    fireguard_elasticsearch_index_prefix, "bcws-incidents"
                ),
                "bcws_perimeters": _fireguard_index(
                    fireguard_elasticsearch_index_prefix, "bcws-perimeters"
                ),
            },
            "firms_count": int(total_value or 0),
            "bcws_incident_count": incident_count,
            "bcws_perimeter_count": perimeter_count,
            "min_acquired_at": aggs.get("min_time", {}).get("value_as_string"),
            "max_acquired_at": aggs.get("max_time", {}).get("value_as_string"),
            "sources": [
                {"source": bucket.get("key"), "count": bucket.get("doc_count", 0)}
                for bucket in buckets
                if isinstance(bucket, dict)
            ],
        }

    registry.register(
        ToolDefinition(
            name="fireguard_stats",
            description="Read FireGuard index counts, time bounds, and FIRMS source counts.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            mutating=False,
            concurrency_safe=True,
            timeout_seconds=30,
        ),
        fireguard_stats,
    )

    async def fireguard_search_events(invocation: ToolInvocation) -> dict[str, Any]:
        latitude = _required_float(invocation.args, "latitude", minimum=-90, maximum=90)
        longitude = _required_float(invocation.args, "longitude", minimum=-180, maximum=180)
        radius_km = _optional_float(invocation.args, "radius_km", default=100, minimum=1, maximum=2000)
        size = _optional_int(invocation.args, "size", default=50, minimum=1, maximum=500)
        start_date = _optional_string(invocation.args, "start_date")
        end_date = _optional_string(invocation.args, "end_date")
        sources = _optional_string_list(invocation.args, "sources")
        filters: list[dict[str, Any]] = [
            {
                "geo_distance": {
                    "distance": f"{radius_km}km",
                    "location": {"lat": latitude, "lon": longitude},
                }
            }
        ]
        if start_date is not None or end_date is not None:
            date_range: dict[str, str] = {}
            if start_date is not None:
                date_range["gte"] = start_date
            if end_date is not None:
                date_range["lte"] = end_date
            filters.append({"range": {"acquired_at": date_range}})
        if sources:
            filters.append({"terms": {"source": sources}})
        body = {
            "size": size,
            "sort": [{"acquired_at": "desc"}],
            "query": {"bool": {"filter": filters}},
            "_source": [
                "source",
                "acquired_at",
                "latitude",
                "longitude",
                "confidence",
                "frp",
                "brightness",
                "satellite",
                "instrument",
                "weather",
                "place",
            ],
        }
        result = await _elastic_search(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            fireguard_elasticsearch_index_prefix,
            "firms",
            body,
        )
        hits = result.get("hits", {}).get("hits", [])
        events = [_compact_public_event(hit.get("_source", {})) for hit in hits if isinstance(hit, dict)]
        return {
            "query": {
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
                "start_date": start_date,
                "end_date": end_date,
                "sources": sources,
                "size": size,
            },
            "count": len(events),
            "events": events,
        }

    registry.register(
        ToolDefinition(
            name="fireguard_search_events",
            description="Search indexed FIRMS detections by point, radius, optional date range, and optional sources.",
            parameters={
                "type": "object",
                "properties": {
                    "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                    "longitude": {"type": "number", "minimum": -180, "maximum": 180},
                    "radius_km": {"type": "number", "minimum": 1, "maximum": 2000},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                    "size": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "required": ["latitude", "longitude"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
            timeout_seconds=60,
        ),
        fireguard_search_events,
    )

    async def fireguard_search_zones(invocation: ToolInvocation) -> dict[str, Any]:
        latitude = _required_float(invocation.args, "latitude", minimum=-90, maximum=90)
        longitude = _required_float(invocation.args, "longitude", minimum=-180, maximum=180)
        radius_km = _optional_float(invocation.args, "radius_km", default=150, minimum=1, maximum=2000)
        size = _optional_int(invocation.args, "size", default=50, minimum=1, maximum=500)
        body = {
            "size": size,
            "sort": [
                {
                    "_geo_distance": {
                        "location": {"lat": latitude, "lon": longitude},
                        "order": "asc",
                        "unit": "km",
                        "distance_type": "arc",
                    }
                }
            ],
            "query": {
                "bool": {
                    "filter": [
                        {
                            "geo_distance": {
                                "distance": f"{radius_km}km",
                                "location": {"lat": latitude, "lon": longitude},
                            }
                        }
                    ]
                }
            },
            "_source": [
                "zone_id",
                "name",
                "population",
                "homes",
                "issuing_agency",
                "event_name",
                "location",
            ],
        }
        result = await _elastic_search(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            fireguard_elasticsearch_index_prefix,
            "zones",
            body,
        )
        hits = result.get("hits", {}).get("hits", [])
        zones = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            source = hit.get("_source", {})
            if not isinstance(source, dict):
                continue
            zones.append(_compact_zone(source, latitude, longitude))
        return {
            "query": {
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
                "size": size,
            },
            "count": len(zones),
            "zones": zones,
        }

    registry.register(
        ToolDefinition(
            name="fireguard_search_zones",
            description="Search seeded BC evacuation zones by point and radius.",
            parameters={
                "type": "object",
                "properties": {
                    "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                    "longitude": {"type": "number", "minimum": -180, "maximum": 180},
                    "radius_km": {"type": "number", "minimum": 1, "maximum": 2000},
                    "size": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "required": ["latitude", "longitude"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
            timeout_seconds=60,
        ),
        fireguard_search_zones,
    )

    async def fireguard_search_shelters(invocation: ToolInvocation) -> dict[str, Any]:
        latitude = _required_float(invocation.args, "latitude", minimum=-90, maximum=90)
        longitude = _required_float(invocation.args, "longitude", minimum=-180, maximum=180)
        radius_km = _optional_float(invocation.args, "radius_km", default=200, minimum=1, maximum=2000)
        size = _optional_int(invocation.args, "size", default=50, minimum=1, maximum=500)
        status_filter = _optional_string(invocation.args, "status_filter")
        filters: list[dict[str, Any]] = [
            {
                "geo_distance": {
                    "distance": f"{radius_km}km",
                    "location": {"lat": latitude, "lon": longitude},
                }
            }
        ]
        if status_filter is not None:
            filters.append({"term": {"status": status_filter}})
        body = {
            "size": size,
            "sort": [
                {
                    "_geo_distance": {
                        "location": {"lat": latitude, "lon": longitude},
                        "order": "asc",
                        "unit": "km",
                        "distance_type": "arc",
                    }
                }
            ],
            "query": {"bool": {"filter": filters}},
            "_source": [
                "facility_id",
                "name",
                "facility_type",
                "address",
                "community",
                "municipality",
                "status",
                "location",
                "capacity",
            ],
        }
        result = await _elastic_search(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            fireguard_elasticsearch_index_prefix,
            "shelters",
            body,
        )
        hits = result.get("hits", {}).get("hits", [])
        shelters = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            source = hit.get("_source", {})
            if not isinstance(source, dict):
                continue
            shelters.append(_compact_shelter(source, latitude, longitude))
        return {
            "query": {
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
                "status_filter": status_filter,
                "size": size,
            },
            "count": len(shelters),
            "shelters": shelters,
        }

    registry.register(
        ToolDefinition(
            name="fireguard_search_shelters",
            description="Search indexed ESS facilities by point, radius, and optional status.",
            parameters={
                "type": "object",
                "properties": {
                    "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                    "longitude": {"type": "number", "minimum": -180, "maximum": 180},
                    "radius_km": {"type": "number", "minimum": 1, "maximum": 2000},
                    "size": {"type": "integer", "minimum": 1, "maximum": 500},
                    "status_filter": {"type": "string"},
                },
                "required": ["latitude", "longitude"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
            timeout_seconds=60,
        ),
        fireguard_search_shelters,
    )

    async def fireguard_search_road_events(invocation: ToolInvocation) -> dict[str, Any]:
        latitude = _required_float(invocation.args, "latitude", minimum=-90, maximum=90)
        longitude = _required_float(invocation.args, "longitude", minimum=-180, maximum=180)
        radius_km = _optional_float(invocation.args, "radius_km", default=200, minimum=1, maximum=2000)
        size = _optional_int(invocation.args, "size", default=50, minimum=1, maximum=500)
        body = {
            "size": size,
            "sort": [
                {
                    "_geo_distance": {
                        "location": {"lat": latitude, "lon": longitude},
                        "order": "asc",
                        "unit": "km",
                        "distance_type": "arc",
                    }
                }
            ],
            "query": {
                "bool": {
                    "filter": [
                        {
                            "geo_distance": {
                                "distance": f"{radius_km}km",
                                "location": {"lat": latitude, "lon": longitude},
                            }
                        }
                    ]
                }
            },
            "_source": [
                "event_id",
                "title",
                "description",
                "road_name",
                "event_type",
                "severity",
                "status",
                "location",
                "geometry",
            ],
        }
        result = await _elastic_search(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            fireguard_elasticsearch_index_prefix,
            "road-events",
            body,
        )
        hits = result.get("hits", {}).get("hits", [])
        road_events = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            source = hit.get("_source", {})
            if not isinstance(source, dict):
                continue
            road_events.append(_compact_road_event(source, latitude, longitude))
        return {
            "query": {
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
                "size": size,
            },
            "count": len(road_events),
            "road_events": road_events,
        }

    registry.register(
        ToolDefinition(
            name="fireguard_search_road_events",
            description="Search indexed road events by point and radius.",
            parameters={
                "type": "object",
                "properties": {
                    "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                    "longitude": {"type": "number", "minimum": -180, "maximum": 180},
                    "radius_km": {"type": "number", "minimum": 1, "maximum": 2000},
                    "size": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "required": ["latitude", "longitude"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
            timeout_seconds=60,
        ),
        fireguard_search_road_events,
    )

    async def fireguard_evaluate_route(invocation: ToolInvocation) -> dict[str, Any]:
        from ..geo import haversine_km, min_distance_to_polyline_km

        origin_lat = _required_float(invocation.args, "origin_lat", minimum=-90, maximum=90)
        origin_lon = _required_float(invocation.args, "origin_lon", minimum=-180, maximum=180)
        destination_lat = _required_float(
            invocation.args, "destination_lat", minimum=-90, maximum=90
        )
        destination_lon = _required_float(
            invocation.args, "destination_lon", minimum=-180, maximum=180
        )
        start_date = _optional_string(invocation.args, "start_date")
        end_date = _optional_string(invocation.args, "end_date")
        fire_buffer_km = _optional_float(
            invocation.args, "fire_buffer_km", default=5.0, minimum=0, maximum=2000
        )
        road_closure_buffer_km = _optional_float(
            invocation.args, "road_closure_buffer_km", default=2.0, minimum=0, maximum=2000
        )
        hypothetical_closures = _optional_hypothetical_closures(
            invocation.args, "hypothetical_closures"
        )
        ignore_closures = _optional_string_list(invocation.args, "ignore_closures")

        origin = {"lat": origin_lat, "lon": origin_lon}
        destination = {"lat": destination_lat, "lon": destination_lon}
        points = _interpolate_route(origin, destination, segments=4)
        distance_km = sum(haversine_km(a, b) for a, b in zip(points, points[1:]))
        duration_minutes = max(5, round(distance_km / 55 * 60))

        route_center_lat = (origin_lat + destination_lat) / 2
        route_center_lon = (origin_lon + destination_lon) / 2
        corridor_radius = (distance_km / 2) + fire_buffer_km + 20

        fire_filters: list[dict[str, Any]] = [
            {
                "geo_distance": {
                    "distance": f"{corridor_radius}km",
                    "location": {"lat": route_center_lat, "lon": route_center_lon},
                }
            }
        ]
        if start_date is not None or end_date is not None:
            date_range: dict[str, str] = {}
            if start_date is not None:
                date_range["gte"] = start_date
            if end_date is not None:
                date_range["lte"] = end_date
            fire_filters.append({"range": {"acquired_at": date_range}})
        fires_result = await _elastic_search(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            fireguard_elasticsearch_index_prefix,
            "firms",
            {
                "size": 200,
                "sort": [
                    {
                        "_geo_distance": {
                            "location": {"lat": route_center_lat, "lon": route_center_lon},
                            "order": "asc",
                            "unit": "km",
                            "distance_type": "arc",
                        }
                    }
                ],
                "query": {"bool": {"filter": fire_filters}},
                "_source": [
                    "source",
                    "acquired_at",
                    "latitude",
                    "longitude",
                    "confidence",
                    "frp",
                    "location",
                ],
            },
        )
        road_result = await _elastic_search(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            fireguard_elasticsearch_index_prefix,
            "road-events",
            {
                "size": 100,
                "sort": [
                    {
                        "_geo_distance": {
                            "location": {"lat": route_center_lat, "lon": route_center_lon},
                            "order": "asc",
                            "unit": "km",
                            "distance_type": "arc",
                        }
                    }
                ],
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "geo_distance": {
                                    "distance": f"{corridor_radius}km",
                                    "location": {
                                        "lat": route_center_lat,
                                        "lon": route_center_lon,
                                    },
                                }
                            }
                        ]
                    }
                },
                "_source": [
                    "event_id",
                    "title",
                    "description",
                    "road_name",
                    "event_type",
                    "severity",
                    "status",
                    "location",
                    "geometry",
                ],
            },
        )

        risk_flags: list[str] = []
        evidence: list[dict[str, Any]] = []
        safe = True

        for hit in fires_result.get("hits", {}).get("hits", []):
            if not isinstance(hit, dict):
                continue
            fire_hit = hit.get("_source", {})
            if not isinstance(fire_hit, dict):
                continue
            fire_lat = fire_hit.get("latitude")
            fire_lon = fire_hit.get("longitude")
            if not isinstance(fire_lat, (int, float)) or not isinstance(fire_lon, (int, float)):
                continue
            fire_loc = {"lat": float(fire_lat), "lon": float(fire_lon)}
            dist = min_distance_to_polyline_km(fire_loc, points)
            if dist <= fire_buffer_km:
                frp = fire_hit.get("frp", 0)
                risk_flags.append(
                    f"Route passes within {round(dist, 1)} km of active fire (FRP {frp})"
                )
                safe = False
                evidence.append(
                    {
                        "type": "fire",
                        "lat": fire_loc["lat"],
                        "lon": fire_loc["lon"],
                        "frp": frp,
                        "distance_km": round(dist, 1),
                        "acquired_at": fire_hit.get("acquired_at"),
                    }
                )

        for hit in road_result.get("hits", {}).get("hits", []):
            if not isinstance(hit, dict):
                continue
            road_hit = hit.get("_source", {})
            if not isinstance(road_hit, dict):
                continue
            event_id = road_hit.get("event_id", "")
            if isinstance(event_id, str) and event_id in ignore_closures:
                continue
            if not _is_closure(road_hit):
                continue
            road_loc = road_hit.get("location", {})
            if not isinstance(road_loc, dict):
                continue
            rlat = road_loc.get("lat")
            rlon = road_loc.get("lon")
            if not isinstance(rlat, (int, float)) or not isinstance(rlon, (int, float)):
                continue
            dist = min_distance_to_polyline_km({"lat": float(rlat), "lon": float(rlon)}, points)
            if dist <= road_closure_buffer_km:
                label = road_hit.get("road_name") or road_hit.get("title") or "road event"
                risk_flags.append(f"Route passes within {round(dist, 1)} km of closure: {label}")
                safe = False
                evidence.append(
                    {
                        "type": "road_closure",
                        "event_id": event_id,
                        "label": label,
                        "distance_km": round(dist, 1),
                    }
                )

        for hyp in hypothetical_closures:
            hyp_loc = {"lat": hyp["lat"], "lon": hyp["lon"]}
            dist = min_distance_to_polyline_km(hyp_loc, points)
            if dist <= road_closure_buffer_km:
                label = hyp.get("label", "hypothetical closure")
                risk_flags.append(
                    f"Route passes within {round(dist, 1)} km of hypothetical closure: {label}"
                )
                safe = False
                evidence.append(
                    {
                        "type": "hypothetical_closure",
                        "label": label,
                        "distance_km": round(dist, 1),
                    }
                )

        return {
            "origin": origin,
            "destination": destination,
            "distance_km": round(distance_km, 1),
            "duration_minutes": duration_minutes,
            "route_source": "deterministic_straight_line",
            "safe": safe,
            "risk_flags": risk_flags,
            "evidence": evidence,
            "polyline": [{"lat": p["lat"], "lon": p["lon"]} for p in points],
            "assumptions": [
                "Straight-line route at 55 kph average speed",
                f"Fire buffer: {fire_buffer_km} km",
                f"Road closure buffer: {road_closure_buffer_km} km",
            ],
        }

    registry.register(
        ToolDefinition(
            name="fireguard_evaluate_route",
            description=(
                "Evaluate route safety between two points. Checks against indexed fire detections "
                "and road closures. Supports hypothetical_closures for 'what if' analysis "
                "(e.g., 'what if Highway 97 closes') and ignore_closures to simulate reopenings."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "origin_lat": {"type": "number", "minimum": -90, "maximum": 90},
                    "origin_lon": {"type": "number", "minimum": -180, "maximum": 180},
                    "destination_lat": {"type": "number", "minimum": -90, "maximum": 90},
                    "destination_lon": {"type": "number", "minimum": -180, "maximum": 180},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "fire_buffer_km": {"type": "number", "minimum": 0, "maximum": 2000},
                    "road_closure_buffer_km": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 2000,
                    },
                    "hypothetical_closures": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "lat": {"type": "number", "minimum": -90, "maximum": 90},
                                "lon": {"type": "number", "minimum": -180, "maximum": 180},
                                "label": {"type": "string"},
                            },
                            "required": ["lat", "lon", "label"],
                            "additionalProperties": False,
                        },
                    },
                    "ignore_closures": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["origin_lat", "origin_lon", "destination_lat", "destination_lon"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
            timeout_seconds=60,
        ),
        fireguard_evaluate_route,
    )

    async def fireguard_bcws_context(invocation: ToolInvocation) -> dict[str, Any]:
        latitude = _required_float(invocation.args, "latitude", minimum=-90, maximum=90)
        longitude = _required_float(invocation.args, "longitude", minimum=-180, maximum=180)
        radius_km = _optional_float(invocation.args, "radius_km", default=100, minimum=1, maximum=2000)
        size = _optional_int(invocation.args, "size", default=50, minimum=1, maximum=500)
        west, south, east, north = _bbox(latitude, longitude, radius_km)
        incident_body = {
            "size": size,
            "sort": [{"updated_at": "desc"}],
            "query": {
                "bool": {
                    "filter": [
                        {
                            "geo_bounding_box": {
                                "location": {
                                    "top_left": {"lat": north, "lon": west},
                                    "bottom_right": {"lat": south, "lon": east},
                                }
                            }
                        }
                    ]
                }
            },
            "_source": [
                "source",
                "fire_number",
                "incident_name",
                "fire_status",
                "fire_cause",
                "fire_type",
                "current_size_ha",
                "ignition_date",
                "fire_out_date",
                "geographic_description",
                "fire_url",
                "latitude",
                "longitude",
                "updated_at",
            ],
        }
        perimeter_body = {
            "size": size,
            "sort": [{"updated_at": "desc"}],
            "query": {
                "geo_shape": {
                    "geometry": {
                        "shape": {
                            "type": "envelope",
                            "coordinates": [[west, north], [east, south]],
                        },
                        "relation": "intersects",
                    }
                }
            },
            "_source": [
                "source",
                "fire_number",
                "fire_status",
                "fire_size_hectares",
                "track_date",
                "load_date",
                "fire_url",
                "feature_area_sqm",
                "feature_length_m",
                "updated_at",
            ],
        }
        incidents = await _elastic_search(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            fireguard_elasticsearch_index_prefix,
            "bcws-incidents",
            incident_body,
        )
        perimeters = await _elastic_search(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            fireguard_elasticsearch_index_prefix,
            "bcws-perimeters",
            perimeter_body,
        )
        incident_hits = incidents.get("hits", {}).get("hits", [])
        perimeter_hits = perimeters.get("hits", {}).get("hits", [])
        return {
            "query": {
                "latitude": latitude,
                "longitude": longitude,
                "radius_km": radius_km,
                "bbox": {"west": west, "south": south, "east": east, "north": north},
                "size": size,
            },
            "incidents": [
                _compact(hit.get("_source", {})) for hit in incident_hits if isinstance(hit, dict)
            ],
            "perimeters": [
                _compact(hit.get("_source", {})) for hit in perimeter_hits if isinstance(hit, dict)
            ],
        }

    registry.register(
        ToolDefinition(
            name="fireguard_bcws_context",
            description="Read indexed BCWS incidents and perimeters around a point and radius.",
            parameters={
                "type": "object",
                "properties": {
                    "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                    "longitude": {"type": "number", "minimum": -180, "maximum": 180},
                    "radius_km": {"type": "number", "minimum": 1, "maximum": 2000},
                    "size": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "required": ["latitude", "longitude"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
            timeout_seconds=60,
        ),
        fireguard_bcws_context,
    )

    async def ask_user(invocation: ToolInvocation) -> dict[str, Any]:
        questions = invocation.args.get("questions")
        if not isinstance(questions, list) or len(questions) == 0:
            raise ValueError("questions must be a non-empty list")
        normalized: list[dict[str, Any]] = []
        for index, raw_question in enumerate(questions):
            if not isinstance(raw_question, dict):
                raise ValueError(f"questions[{index}] must be an object")
            question = raw_question.get("question")
            if not isinstance(question, str) or len(question.strip()) == 0:
                raise ValueError(f"questions[{index}].question must be a non-empty string")
            options = raw_question.get("options")
            if options is not None and not isinstance(options, list):
                raise ValueError(f"questions[{index}].options must be a list when provided")
            normalized_options: list[str] = []
            if isinstance(options, list):
                for option_index, option in enumerate(options):
                    if not isinstance(option, str) or len(option.strip()) == 0:
                        raise ValueError(
                            f"questions[{index}].options[{option_index}] must be a non-empty string"
                        )
                    normalized_options.append(option)
            normalized.append(
                {
                    "id": raw_question.get("id")
                    if isinstance(raw_question.get("id"), str)
                    else f"q{index + 1}",
                    "question": question,
                    "options": normalized_options,
                    "allow_other": True,
                }
            )
        return {
            "ask_user": True,
            "title": invocation.args.get("title")
            if isinstance(invocation.args.get("title"), str)
            else "Clarify request",
            "questions": normalized,
        }

    registry.register(
        ToolDefinition(
            name="ask_user",
            description=(
                "Ask the human one or more clarification questions before deciding whether to "
                "handoff to research. Use this instead of writing clarification questions in prose."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "questions": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "question": {"type": "string", "minLength": 1},
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string", "minLength": 1},
                                },
                            },
                            "required": ["question"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["questions"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=False,
        ),
        ask_user,
    )

    async def fireguard_map_annotation(invocation: ToolInvocation) -> dict[str, Any]:
        markers = invocation.args.get("markers", [])
        routes = invocation.args.get("routes", [])
        message = invocation.args.get("message", "")
        return {
            "ok": True,
            "annotation": {
                "markers": markers,
                "routes": routes,
                "message": message,
            },
        }

    registry.register(
        ToolDefinition(
            name="fireguard_map_annotation",
            description=(
                "Push geographic annotations directly to the live map panel visible to the operator. "
                "Use this to visualize your reasoning — show evaluated routes, shelters, blockages, "
                "fire hotspots, and a summary message. Call this AFTER your route evaluation steps "
                "to give the operator a visual summary before writing the final brief."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Short decision summary shown as a map overlay headline (1-2 sentences).",
                    },
                    "markers": {
                        "type": "array",
                        "description": "Point markers to place on the map.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "lat": {"type": "number"},
                                "lon": {"type": "number"},
                                "type": {
                                    "type": "string",
                                    "enum": ["hotspot", "shelter_open", "shelter_closed", "zone", "blockage", "alternate"],
                                    "description": "hotspot=fire, shelter_open=green shelter, shelter_closed=grey shelter, zone=evac zone centroid, blockage=road blocked, alternate=alternate destination",
                                },
                                "label": {"type": "string", "description": "Short text label for the popup."},
                                "detail": {"type": "string", "description": "Additional detail shown in popup (distance, FRP, status, etc)."},
                            },
                            "required": ["lat", "lon", "type", "label"],
                            "additionalProperties": False,
                        },
                    },
                    "routes": {
                        "type": "array",
                        "description": "Straight-line routes to draw between two points.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from_lat": {"type": "number"},
                                "from_lon": {"type": "number"},
                                "to_lat": {"type": "number"},
                                "to_lon": {"type": "number"},
                                "status": {
                                    "type": "string",
                                    "enum": ["safe", "blocked", "alternate"],
                                    "description": "safe=green, blocked=red, alternate=orange",
                                },
                                "label": {"type": "string", "description": "Route label e.g. 'Williams Lake → Merritt (BLOCKED)'"},
                                "distance_km": {"type": "number"},
                                "duration_minutes": {"type": "number"},
                            },
                            "required": ["from_lat", "from_lon", "to_lat", "to_lon", "status", "label"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["message", "markers", "routes"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
            timeout_seconds=10,
        ),
        fireguard_map_annotation,
    )

    async def fireguard_actions(invocation: ToolInvocation) -> dict[str, Any]:
        return {"ok": True, "plan": invocation.args}

    registry.register(
        ToolDefinition(
            name="fireguard_actions",
            description=(
                "Push a structured action plan to the FireGuard UI. Call this ONCE after "
                "completing your analysis, before complete_workflow_node. "
                "Provide a short summary sentence and a list of prioritised actions the "
                "incident commander should take immediately."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "One sentence summarising the overall recommended action.",
                    },
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id":       {"type": "string"},
                                "priority": {"type": "string", "enum": ["immediate", "urgent", "monitor"]},
                                "title":    {"type": "string", "description": "Short imperative action title, max 12 words."},
                                "detail":   {"type": "string", "description": "One sentence of supporting detail or caveat."},
                                "owner":    {"type": "string", "description": "Responsible party, e.g. 'Incident Commander', 'ESS'."},
                            },
                            "required": ["id", "priority", "title"],
                        },
                    },
                },
                "required": ["summary", "actions"],
            },
            mutating=False,
            concurrency_safe=True,
        ),
        fireguard_actions,
    )

    async def complete_workflow_node(invocation: ToolInvocation) -> dict[str, Any]:
        return {"completed": True, "payload": invocation.args}

    registry.register(
        ToolDefinition(
            name="complete_workflow_node",
            description="Return a structured payload to complete the current workflow node.",
            parameters={
                "type": "object",
                "properties": {"payload": {"type": "object"}},
                "additionalProperties": True,
            },
            mutating=False,
            concurrency_safe=True,
        ),
        complete_workflow_node,
    )

    async def request_approval(invocation: ToolInvocation) -> dict[str, Any]:
        return {"approval_requested": True, "payload": invocation.args}

    registry.register(
        ToolDefinition(
            name="request_approval",
            description="Request a human approval gate from inside an agent.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            mutating=False,
            concurrency_safe=False,
        ),
        request_approval,
    )

    async def echo_json(invocation: ToolInvocation) -> dict[str, Any]:
        return {"json": json.loads(json.dumps(invocation.args))}

    registry.register(
        ToolDefinition(
            name="echo_json",
            description="Return the provided JSON payload exactly for workflow plumbing checks.",
            parameters={"type": "object", "properties": {}, "additionalProperties": True},
            mutating=False,
            concurrency_safe=True,
        ),
        echo_json,
    )

    async def exa_search(invocation: ToolInvocation) -> dict[str, Any]:
        if len(exa_api_key.strip()) == 0:
            raise RuntimeError("EXA_API_KEY is not configured")
        query = invocation.args.get("query")
        if not isinstance(query, str) or len(query.strip()) == 0:
            raise ValueError("query must be a non-empty string")
        request_body: dict[str, Any] = {"query": query}
        optional_passthrough = [
            "numResults",
            "type",
            "category",
            "includeDomains",
            "excludeDomains",
            "startCrawlDate",
            "endCrawlDate",
            "startPublishedDate",
            "endPublishedDate",
            "includeText",
            "excludeText",
            "moderation",
            "extras",
        ]
        for key in optional_passthrough:
            value = invocation.args.get(key)
            if value is not None:
                request_body[key] = value
        contents = invocation.args.get("contents")
        if contents is None:
            request_body["contents"] = {
                "text": {"maxCharacters": 2000},
                "highlights": {"numSentences": 3, "highlightsPerUrl": 3},
                "summary": True,
            }
        elif isinstance(contents, dict):
            request_body["contents"] = contents
        else:
            raise ValueError("contents must be an object when provided")
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                f"{exa_base_url.rstrip('/')}/search",
                headers={"x-api-key": exa_api_key, "Content-Type": "application/json"},
                json=request_body,
            )
            response.raise_for_status()
            data = response.json()
        return {
            "query": query,
            "request": request_body,
            "results": data.get("results") if isinstance(data, dict) else data,
            "raw": data,
        }

    registry.register(
        ToolDefinition(
            name="exa_search",
            description=(
                "Search the live web with Exa and return result metadata plus extracted text, "
                "highlights, or summaries. Use for factual research, source discovery, and "
                "image retrieval. Each result includes a top-level image field. To retrieve "
                "additional images embedded in a page, pass extras={\"imageLinks\": 5}; those "
                "URLs are returned under result.extras.imageLinks. Use image search to find "
                "maps, charts, and other visuals relevant to FireGuard intelligence reports."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "numResults": {"type": "integer", "minimum": 1},
                    "type": {"type": "string", "enum": ["auto", "keyword", "neural", "fast"]},
                    "category": {"type": "string"},
                    "includeDomains": {"type": "array", "items": {"type": "string"}},
                    "excludeDomains": {"type": "array", "items": {"type": "string"}},
                    "startCrawlDate": {"type": "string"},
                    "endCrawlDate": {"type": "string"},
                    "startPublishedDate": {"type": "string"},
                    "endPublishedDate": {"type": "string"},
                    "includeText": {"type": "array", "items": {"type": "string"}},
                    "excludeText": {"type": "array", "items": {"type": "string"}},
                    "moderation": {"type": "boolean"},
                    "extras": {
                        "type": "object",
                        "description": "Pass {\"imageLinks\": N} to retrieve image URLs under result.extras.imageLinks.",
                        "additionalProperties": True,
                    },
                    "contents": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
        ),
        exa_search,
    )

    async def sandbox_exec(invocation: ToolInvocation) -> dict[str, Any]:
        if sandbox_manager is None:
            raise RuntimeError("sandbox manager is not configured")
        command = invocation.args.get("command")
        if (
            not isinstance(command, list)
            or len(command) == 0
            or not all(isinstance(item, str) for item in command)
        ):
            raise ValueError("command must be a non-empty array of strings")
        timeout_seconds = invocation.args.get("timeout_seconds")
        if timeout_seconds is not None and not isinstance(timeout_seconds, (int, float)):
            raise ValueError("timeout_seconds must be a number when provided")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero when provided")
        return await sandbox_manager.exec(
            invocation.session_id,
            command,
            timeout_seconds=float(timeout_seconds) if timeout_seconds is not None else None,
        )

    registry.register(
        ToolDefinition(
            name="sandbox_exec",
            description=(
                "Execute a command inside the session Docker sandbox. Use for research computation, "
                "data exploration, parsing, analysis scripts, and reproducible checks."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            mutating=True,
            concurrency_safe=False,
        ),
        sandbox_exec,
    )

    async def sandbox_write_file(invocation: ToolInvocation) -> dict[str, Any]:
        if sandbox_manager is None:
            raise RuntimeError("sandbox manager is not configured")
        path = invocation.args.get("path")
        content = invocation.args.get("content")
        if not isinstance(path, str) or len(path.strip()) == 0:
            raise ValueError("path must be a non-empty string")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        return await sandbox_manager.write_file(invocation.session_id, path, content)

    registry.register(
        ToolDefinition(
            name="sandbox_write_file",
            description="Write UTF-8 text into a file inside the session Docker sandbox.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            mutating=True,
            concurrency_safe=False,
        ),
        sandbox_write_file,
    )

    async def sandbox_read_file(invocation: ToolInvocation) -> dict[str, Any]:
        if sandbox_manager is None:
            raise RuntimeError("sandbox manager is not configured")
        path = invocation.args.get("path")
        max_bytes = invocation.args.get("max_bytes", 20000)
        if not isinstance(path, str) or len(path.strip()) == 0:
            raise ValueError("path must be a non-empty string")
        if not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        return await sandbox_manager.read_file(invocation.session_id, path, max_bytes=max_bytes)

    registry.register(
        ToolDefinition(
            name="sandbox_read_file",
            description="Read a UTF-8/text file from the session Docker sandbox.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "max_bytes": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
        ),
        sandbox_read_file,
    )

    async def sandbox_export_asset(invocation: ToolInvocation) -> dict[str, Any]:
        if sandbox_manager is None:
            raise RuntimeError("sandbox manager is not configured")
        if assets_dir_fn is None:
            raise RuntimeError("asset storage is not configured")
        path = invocation.args.get("path")
        if not isinstance(path, str) or len(path.strip()) == 0:
            raise ValueError("path must be a non-empty string")
        result = await sandbox_manager.export_asset(
            invocation.session_id,
            path,
            assets_dir_fn(invocation.session_id),
        )
        filename = result.get("saved_as")
        size = result.get("size")
        if not isinstance(filename, str) or not isinstance(size, int):
            raise RuntimeError("sandbox export returned an invalid payload")
        content_type, _ = mimetypes.guess_type(filename)
        return {
            "url": f"/api/intelligence/sessions/{invocation.session_id}/assets/{filename}",
            "filename": filename,
            "content_type": content_type or "application/octet-stream",
            "size": size,
        }

    registry.register(
        ToolDefinition(
            name="sandbox_export_asset",
            description=(
                "Copy a file from the sandbox to persistent storage and return a URL that can be "
                "embedded directly in the report. Use this for generated charts, plots, diagrams, "
                "tables as images, PDFs, or other files that should appear in the final output. "
                "Use the returned URL in markdown as ![alt text](url) for images or [label](url) "
                "for downloadable files."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Absolute path inside the sandbox, e.g. /workspace/chart.png",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
        ),
        sandbox_export_asset,
    )

    async def sandbox_list_files(invocation: ToolInvocation) -> dict[str, Any]:
        if sandbox_manager is None:
            raise RuntimeError("sandbox manager is not configured")
        path = invocation.args.get("path", "/workspace")
        max_entries = invocation.args.get("max_entries", 200)
        if not isinstance(path, str) or len(path.strip()) == 0:
            raise ValueError("path must be a non-empty string")
        if not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        return await sandbox_manager.list_files(
            invocation.session_id, path, max_entries=max_entries
        )

    registry.register(
        ToolDefinition(
            name="sandbox_list_files",
            description="List files inside the session Docker sandbox.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "max_entries": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
            mutating=False,
            concurrency_safe=True,
        ),
        sandbox_list_files,
    )

    return registry


def _fireguard_index(prefix: str, suffix: str) -> str:
    return f"{prefix.strip()}-{suffix}"


async def _elastic_search(
    base_url: str,
    api_key: str,
    index_prefix: str,
    index_suffix: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await _elastic_mcp_search(
        base_url,
        api_key,
        _fireguard_index(index_prefix, index_suffix),
        body or {"query": {"match_all": {}}},
    )


async def _elastic_count(
    base_url: str,
    api_key: str,
    index_prefix: str,
    index_suffix: str,
) -> int:
    result = await _elastic_search(
        base_url,
        api_key,
        index_prefix,
        index_suffix,
        {"size": 0, "track_total_hits": True, "query": {"match_all": {}}},
    )
    total = result.get("hits", {}).get("total", 0)
    if isinstance(total, dict):
        return int(total.get("value", 0) or 0)
    return int(total or 0)


async def _elastic_mcp_search(
    base_url: str,
    api_key: str,
    index: str,
    query_body: dict[str, Any],
) -> dict[str, Any]:
    if len(base_url.strip()) == 0:
        raise RuntimeError("ELASTICSEARCH_URL is not configured")
    image = os.environ.get("ELASTICSEARCH_MCP_IMAGE", "docker.elastic.co/mcp/elasticsearch")
    env = {"ES_URL": _mcp_elasticsearch_url(base_url)}
    if len(api_key.strip()) > 0:
        env["ES_API_KEY"] = api_key
    server = StdioServerParameters(
        command="docker",
        args=[
            "run",
            "-i",
            "--rm",
            "--add-host=host.docker.internal:host-gateway",
            "-e",
            "ES_URL",
            "-e",
            "ES_API_KEY",
            image,
            "stdio",
        ],
        env=env,
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "search", {"index": index, "query_body": query_body}
            )
    return _mcp_tool_result_object(result)


def _mcp_elasticsearch_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    return (
        url.replace("http://127.0.0.1:", "http://host.docker.internal:", 1)
        .replace("http://localhost:", "http://host.docker.internal:", 1)
    )


def _mcp_tool_result_object(result: Any) -> dict[str, Any]:
    content = getattr(result, "content", None)
    if not isinstance(content, list):
        raise RuntimeError("Elastic MCP tool returned no content")
    texts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            texts.append(text)
            continue
        if hasattr(item, "model_dump"):
            dumped = item.model_dump()
            raw_text = dumped.get("text") if isinstance(dumped, dict) else None
            if isinstance(raw_text, str):
                texts.append(raw_text)
    text = "\n".join(texts).strip()
    if len(text) == 0:
        raise RuntimeError("Elastic MCP tool returned empty content")
    total: int | None = None
    docs: list[dict[str, Any]] = []
    object_payload: dict[str, Any] | None = None
    for item in texts:
        match = re.search(r"Total results:\s*(\d+)", item)
        if match is not None:
            total = int(match.group(1))
            continue
        try:
            parsed = json.loads(item)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            object_payload = parsed
            continue
        if isinstance(parsed, list):
            docs.extend([doc for doc in parsed if isinstance(doc, dict)])
    if object_payload is not None:
        if "hits" in object_payload:
            return object_payload
        return {
            "hits": {
                "total": {"value": total if total is not None else len(docs)},
                "hits": [{"_source": doc} for doc in docs],
            },
            "aggregations": object_payload,
        }
    return {
        "hits": {
            "total": {"value": total if total is not None else len(docs)},
            "hits": [{"_source": doc} for doc in docs],
        }
    }


def _required_float(
    payload: dict[str, Any], key: str, *, minimum: float, maximum: float
) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    value = float(value)
    if value < minimum or value > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _optional_float(
    payload: dict[str, Any],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    value = payload.get(key)
    if value is None:
        return default
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    value = float(value)
    if value < minimum or value > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _optional_int(
    payload: dict[str, Any], key: str, *, default: int, minimum: int, maximum: int
) -> int:
    value = payload.get(key)
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) == 0:
        raise ValueError(f"{key} must be a non-empty string when provided")
    return value


def _optional_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or len(item.strip()) == 0:
            raise ValueError(f"{key}[{index}] must be a non-empty string")
        out.append(item)
    return out


def _optional_hypothetical_closures(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{key}[{index}] must be an object")
        lat = item.get("lat")
        lon = item.get("lon")
        label = item.get("label", "hypothetical closure")
        if not isinstance(lat, int | float) or isinstance(lat, bool):
            raise ValueError(f"{key}[{index}].lat must be a number")
        if not isinstance(lon, int | float) or isinstance(lon, bool):
            raise ValueError(f"{key}[{index}].lon must be a number")
        if float(lat) < -90 or float(lat) > 90:
            raise ValueError(f"{key}[{index}].lat must be between -90 and 90")
        if float(lon) < -180 or float(lon) > 180:
            raise ValueError(f"{key}[{index}].lon must be between -180 and 180")
        if not isinstance(label, str) or len(label.strip()) == 0:
            raise ValueError(f"{key}[{index}].label must be a non-empty string")
        out.append({"lat": float(lat), "lon": float(lon), "label": label})
    return out


def _bbox(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / max(1.0, 111.0 * math.cos(math.radians(lat)))
    return (
        max(-180.0, lon - lon_delta),
        max(-90.0, lat - lat_delta),
        min(180.0, lon + lon_delta),
        min(90.0, lat + lat_delta),
    )


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _compact_public_event(payload: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "source",
        "acquired_at",
        "latitude",
        "longitude",
        "confidence",
        "frp",
        "brightness",
        "satellite",
        "instrument",
        "weather",
        "place",
    ]
    return _compact({key: payload.get(key) for key in keys})


def _compact_zone(payload: dict[str, Any], latitude: float, longitude: float) -> dict[str, Any]:
    location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
    zone_lat = location.get("lat") if isinstance(location, dict) else None
    zone_lon = location.get("lon") if isinstance(location, dict) else None
    distance = None
    if isinstance(zone_lat, (int, float)) and isinstance(zone_lon, (int, float)):
        distance = _distance_km(latitude, longitude, float(zone_lat), float(zone_lon))
    return _compact(
        {
            "zone_id": payload.get("zone_id"),
            "name": payload.get("name"),
            "population": payload.get("population"),
            "homes": payload.get("homes"),
            "issuing_agency": payload.get("issuing_agency"),
            "event_name": payload.get("event_name"),
            "location": payload.get("location"),
            "distance_km": round(distance, 2) if distance is not None else None,
        }
    )


def _compact_shelter(payload: dict[str, Any], latitude: float, longitude: float) -> dict[str, Any]:
    location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
    shelter_lat = location.get("lat") if isinstance(location, dict) else None
    shelter_lon = location.get("lon") if isinstance(location, dict) else None
    distance = None
    if isinstance(shelter_lat, (int, float)) and isinstance(shelter_lon, (int, float)):
        distance = _distance_km(latitude, longitude, float(shelter_lat), float(shelter_lon))
    return _compact(
        {
            "facility_id": payload.get("facility_id"),
            "name": payload.get("name"),
            "facility_type": payload.get("facility_type"),
            "address": payload.get("address"),
            "community": payload.get("community"),
            "municipality": payload.get("municipality"),
            "status": payload.get("status"),
            "location": payload.get("location"),
            "capacity": payload.get("capacity"),
            "distance_km": round(distance, 2) if distance is not None else None,
        }
    )


def _compact_road_event(payload: dict[str, Any], latitude: float, longitude: float) -> dict[str, Any]:
    location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
    event_lat = location.get("lat") if isinstance(location, dict) else None
    event_lon = location.get("lon") if isinstance(location, dict) else None
    distance = None
    if isinstance(event_lat, (int, float)) and isinstance(event_lon, (int, float)):
        distance = _distance_km(latitude, longitude, float(event_lat), float(event_lon))
    return _compact(
        {
            "event_id": payload.get("event_id"),
            "title": payload.get("title"),
            "description": payload.get("description"),
            "road_name": payload.get("road_name"),
            "event_type": payload.get("event_type"),
            "severity": payload.get("severity"),
            "status": payload.get("status"),
            "location": payload.get("location"),
            "geometry": payload.get("geometry"),
            "distance_km": round(distance, 2) if distance is not None else None,
        }
    )


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _interpolate_route(
    origin: dict[str, float], destination: dict[str, float], *, segments: int = 4
) -> list[dict[str, float]]:
    if segments < 1:
        raise ValueError("segments must be at least 1")
    return [
        {
            "lat": origin["lat"]
            + (destination["lat"] - origin["lat"]) * (index / segments),
            "lon": origin["lon"]
            + (destination["lon"] - origin["lon"]) * (index / segments),
        }
        for index in range(segments + 1)
    ]


def _is_closure(event: dict[str, Any]) -> bool:
    blob = " ".join(
        str(event.get(field, ""))
        for field in ["event_type", "severity", "title", "description"]
    ).lower()
    closure_phrases = [
        "road closed",
        "full closure",
        "closed in both directions",
        "no detour",
        "detour unavailable",
    ]
    if any(phrase in blob for phrase in closure_phrases):
        return True
    return "closure" in blob and not any(
        phrase in blob
        for phrase in ["lane closure", "right lane", "left lane", "centre lane", "shoulder closed"]
    )
