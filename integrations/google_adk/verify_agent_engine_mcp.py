from __future__ import annotations

import json
import os
import sys
from typing import Any

import vertexai
from vertexai import agent_engines


PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "verdant-upgrade-493301-q1")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
RESOURCE = os.environ.get(
    "AGENT_ENGINE_RESOURCE",
    "projects/425727109076/locations/us-central1/reasoningEngines/9137720630806839296",
)


def _parts(event: dict[str, Any]) -> list[dict[str, Any]]:
    content = event.get("content") or {}
    parts = content.get("parts")
    return parts if isinstance(parts, list) else []


def main() -> int:
    vertexai.init(project=PROJECT, location=LOCATION)
    agent = agent_engines.get(RESOURCE)
    message = (
        "Verification only: call elastic_mcp_list_indices with index_pattern fire* "
        "and return the tool result. Do not call other tools."
    )

    events = list(
        agent.stream_query(
            user_id="fireguard-devpost-proof",
            message=message,
        )
    )

    function_calls = [
        part["function_call"]
        for event in events
        for part in _parts(event)
        if "function_call" in part
    ]
    function_responses = [
        part["function_response"]
        for event in events
        for part in _parts(event)
        if "function_response" in part
    ]

    result = {
        "status": "ok" if function_responses else "failed",
        "resource": RESOURCE,
        "event_count": len(events),
        "function_calls": [
            {
                "name": call.get("name"),
                "args": call.get("args"),
            }
            for call in function_calls
        ],
        "function_responses": [
            {
                "name": response.get("name"),
                "response": response.get("response"),
            }
            for response in function_responses
        ],
    }
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
