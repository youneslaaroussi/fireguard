from __future__ import annotations

import asyncio
import json
import math
import mimetypes
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

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
        firms = await _elastic_request(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            "POST",
            f"/{_fireguard_index(fireguard_elasticsearch_index_prefix, 'firms')}/_search",
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
        incidents = await _elastic_request(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            "GET",
            f"/{_fireguard_index(fireguard_elasticsearch_index_prefix, 'bcws-incidents')}/_count",
        )
        perimeters = await _elastic_request(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            "GET",
            f"/{_fireguard_index(fireguard_elasticsearch_index_prefix, 'bcws-perimeters')}/_count",
        )
        total = firms.get("hits", {}).get("total", 0)
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        aggs = firms.get("aggregations", {})
        buckets = aggs.get("sources", {}).get("buckets", [])
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
            "bcws_incident_count": int(incidents.get("count", 0)),
            "bcws_perimeter_count": int(perimeters.get("count", 0)),
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
        result = await _elastic_request(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            "POST",
            f"/{_fireguard_index(fireguard_elasticsearch_index_prefix, 'firms')}/_search",
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
        incidents = await _elastic_request(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            "POST",
            f"/{_fireguard_index(fireguard_elasticsearch_index_prefix, 'bcws-incidents')}/_search",
            incident_body,
        )
        perimeters = await _elastic_request(
            fireguard_elasticsearch_url,
            fireguard_elasticsearch_api_key,
            "POST",
            f"/{_fireguard_index(fireguard_elasticsearch_index_prefix, 'bcws-perimeters')}/_search",
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


async def _elastic_request(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(base_url.strip()) == 0:
        raise RuntimeError("ELASTICSEARCH_URL is not configured")
    if len(api_key.strip()) == 0:
        raise RuntimeError("ELASTICSEARCH_API_KEY is not configured")
    headers = {"Authorization": f"ApiKey {api_key}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(
            method,
            f"{base_url.rstrip('/')}{path}",
            headers=headers,
            json=body,
        )
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Elasticsearch response must be an object")
    return data


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
