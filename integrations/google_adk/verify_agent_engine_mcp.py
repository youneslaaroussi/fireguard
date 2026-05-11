from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any

import vertexai
from google.oauth2.credentials import Credentials
from vertexai import agent_engines


PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "verdant-upgrade-493301-q1")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
RESOURCE = os.environ.get(
    "AGENT_ENGINE_RESOURCE",
    "projects/425727109076/locations/us-central1/reasoningEngines/9137720630806839296",
)
EXPECTED_MODEL = os.environ.get(
    "AGENT_ENGINE_EXPECTED_MODEL",
    "gemini-3.1-flash-lite-preview",
)


def _parts(event: dict[str, Any]) -> list[dict[str, Any]]:
    content = event.get("content") or {}
    parts = content.get("parts")
    return parts if isinstance(parts, list) else []


def main() -> int:
    credentials = None
    gcloud_account = os.environ.get("AGENT_ENGINE_GCLOUD_AUTH_ACCOUNT", "").strip()
    if gcloud_account:
        token = subprocess.check_output(
            [
                "gcloud",
                "auth",
                "print-access-token",
                f"--account={gcloud_account}",
                "--quiet",
            ],
            text=True,
        ).strip()
        credentials = Credentials(
            token=token,
            expiry=datetime.utcnow() + timedelta(minutes=50),
        )

    vertexai.init(project=PROJECT, location=LOCATION, credentials=credentials)
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
    text_parts = [
        part["text"]
        for event in events
        for part in _parts(event)
        if "text" in part
    ]
    model_versions = sorted(
        {
            event.get("model_version")
            for event in events
            if isinstance(event.get("model_version"), str)
        }
    )
    proof_metadata = [
        event.get("fireguard_proof")
        for event in events
        if isinstance(event.get("fireguard_proof"), dict)
    ]
    has_expected_model = not EXPECTED_MODEL or EXPECTED_MODEL in model_versions
    has_elastic_mcp_call = any(
        call.get("name") == "elastic_mcp_list_indices" for call in function_calls
    )
    has_elastic_mcp_response = any(
        response.get("name") == "elastic_mcp_list_indices"
        for response in function_responses
    )

    result = {
        "status": (
            "ok"
            if events
            and has_expected_model
            and has_elastic_mcp_call
            and has_elastic_mcp_response
            else "failed"
        ),
        "resource": RESOURCE,
        "expected_model": EXPECTED_MODEL,
        "model_versions": model_versions,
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
        "text": text_parts,
        "proof_metadata": proof_metadata,
        "checks": {
            "has_events": bool(events),
            "has_expected_model": has_expected_model,
            "has_elastic_mcp_call": has_elastic_mcp_call,
            "has_elastic_mcp_response": has_elastic_mcp_response,
        },
    }
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
