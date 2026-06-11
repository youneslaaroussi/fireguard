from __future__ import annotations

import os
from typing import Any

import requests
import vertexai
from google.adk.agents import Agent
from vertexai import agent_engines

vertexai.init(
    project=os.environ.get("GOOGLE_CLOUD_PROJECT", "vidovaai"),
    location=os.environ.get("AGENT_RUNTIME_LOCATION", "global"),
)


def _fireguard_base_url() -> str:
    return os.environ.get("FIREGUARD_PUBLIC_BASE_URL", "http://127.0.0.1:8100").rstrip("/")


def _get_json(paths: tuple[str, ...], *, timeout: float) -> dict[str, Any]:
    errors: list[str] = []
    for path in paths:
        url = f"{_fireguard_base_url()}{path}"
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code == 404:
                errors.append(f"{path}:404")
                continue
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            errors.append(f"{path}:non-object")
        except requests.RequestException as exc:
            errors.append(f"{path}:{exc}")
    raise RuntimeError("; ".join(errors))


def fireguard_health() -> dict[str, Any]:
    """Check whether the FireGuard web API is reachable."""
    payload = _get_json(("/api/health", "/health"), timeout=8)
    return {"base_url": _fireguard_base_url(), "health": payload}


def fireguard_status() -> dict[str, Any]:
    """Read FireGuard indexed wildfire context counts and source bounds."""
    try:
        payload = _get_json(("/api/stats",), timeout=20)
    except RuntimeError:
        incident = _get_json(("/incidents/current",), timeout=20)
        fires = incident.get("fires", [])
        zones = incident.get("zones", [])
        shelters = incident.get("shelters", [])
        road_events = incident.get("road_events", [])
        return {
            "base_url": _fireguard_base_url(),
            "incident_id": incident.get("incident_id"),
            "fires_count": len(fires) if isinstance(fires, list) else None,
            "zones_count": len(zones) if isinstance(zones, list) else None,
            "shelters_count": len(shelters) if isinstance(shelters, list) else None,
            "road_events_count": len(road_events) if isinstance(road_events, list) else None,
            "store_backend": incident.get("store_backend"),
        }
    return {
        "base_url": _fireguard_base_url(),
        "firms_count": payload.get("firms_count"),
        "bcws_incident_count": payload.get("bcws_incident_count"),
        "bcws_perimeter_count": payload.get("bcws_perimeter_count"),
        "min_acquired_at": payload.get("min_acquired_at"),
        "max_acquired_at": payload.get("max_acquired_at"),
        "sources": payload.get("sources", []),
    }


root_agent = Agent(
    name="fireguard_agent_platform",
    model=os.environ.get("AGENT_RUNTIME_GEMINI_MODEL", "gemini-3.1-pro-preview"),
    description="FireGuard incident intelligence agent for wildfire context checks.",
    instruction=(
        "You are FireGuard, an incident intelligence agent. Use the FireGuard tools "
        "before making claims about indexed wildfire context. Keep answers concise, "
        "operational, and source-bounded."
    ),
    tools=[fireguard_health, fireguard_status],
)

adk_app = agent_engines.AdkApp(agent=root_agent, app_name="fireguard")
