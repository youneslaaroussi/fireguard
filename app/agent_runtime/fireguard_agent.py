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

_BASE_URL = os.environ.get("FIREGUARD_PUBLIC_BASE_URL", "http://127.0.0.1:8100").rstrip("/")


def _get(path: str, *, timeout: float = 15) -> dict[str, Any]:
    r = requests.get(f"{_BASE_URL}{path}", timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict[str, Any], *, timeout: float = 45) -> dict[str, Any]:
    r = requests.post(f"{_BASE_URL}{path}", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fireguard_health() -> dict[str, Any]:
    """Check whether the FireGuard API is reachable and healthy."""
    try:
        return {"status": "ok", "detail": _get("/api/health")}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def fireguard_status() -> dict[str, Any]:
    """Return counts of indexed wildfire data: FIRMS detections, BCWS incidents, perimeters, date range."""
    try:
        return _get("/api/stats", timeout=20)
    except Exception as exc:
        return {"error": str(exc)}


def fireguard_search_shelters(
    latitude: float,
    longitude: float,
    radius_km: float = 300,
    size: int = 10,
    status_filter: str | None = None,
) -> dict[str, Any]:
    """Search indexed BC ESS shelter facilities near a coordinate.

    Each shelter has: name, community, status (OPEN or CLOSED), capacity, distance_km.
    IMPORTANT: Only an OPEN shelter can receive evacuees.
    Use status_filter='OPEN' to find only open shelters.
    """
    body: dict[str, Any] = {"latitude": latitude, "longitude": longitude,
                             "radius_km": radius_km, "size": size}
    if status_filter:
        body["status_filter"] = status_filter
    return _post("/api/tools/fireguard_search_shelters", body)


def fireguard_evaluate_route(
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
    fire_buffer_km: float = 5.0,
    road_closure_buffer_km: float = 2.0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Evaluate an evacuation route for safety against indexed fire detections and road closures.

    Returns: safe (bool), distance_km, duration_minutes, risk_flags.
    Route safety is independent of shelter status — always check both.
    """
    body: dict[str, Any] = {
        "origin_lat": origin_lat, "origin_lon": origin_lon,
        "destination_lat": destination_lat, "destination_lon": destination_lon,
        "fire_buffer_km": fire_buffer_km,
        "road_closure_buffer_km": road_closure_buffer_km,
    }
    if start_date:
        body["start_date"] = start_date
    if end_date:
        body["end_date"] = end_date
    return _post("/api/tools/fireguard_evaluate_route", body)


def fireguard_map_annotation(
    message: str,
    markers: list[dict[str, Any]],
    routes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Push visual annotations to the live operator map.

    marker type: hotspot | shelter_open | shelter_closed | zone | blockage | alternate
    route status: safe | blocked | alternate

    Call this after completing analysis to give the operator a geographic summary.
    """
    return _post("/api/tools/fireguard_map_annotation",
                 {"message": message, "markers": markers, "routes": routes},
                 timeout=15)


def fireguard_actions(
    summary: str,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Push a prioritised action plan to the operator UI.

    Each action: id (str), priority (immediate|urgent|monitor), title (max 12 words),
    detail (one sentence), owner (e.g. 'Incident Commander').

    Call ONCE after analysis is complete, before writing the final brief.
    """
    return _post("/api/tools/fireguard_actions",
                 {"summary": summary, "actions": actions}, timeout=15)


_SYSTEM_PROMPT = """You are FireGuard, an AI incident intelligence agent embedded in a live wildfire operations centre.

When you receive an evacuation trigger (FIREGUARD_EVIDENCE in the message), follow this exact protocol:

STEP 1 — SHELTER SELECTION
- Read the shelters list in the evidence. Each has a status field: OPEN or CLOSED.
- Only an OPEN shelter is a valid evacuation destination.
- If no OPEN shelter is in the list, call fireguard_search_shelters with status_filter="OPEN" and a wider radius.
- If still no OPEN shelter: state this clearly. Do NOT recommend routing to a closed shelter.

STEP 2 — ROUTE EVALUATION
- For each viable OPEN shelter, call fireguard_evaluate_route.
- Read safe (bool) and risk_flags carefully.
- Route safety and shelter availability are independent facts.

STEP 3 — MAP ANNOTATION
- Call fireguard_map_annotation with markers for the hotspot, zone, all evaluated shelters (shelter_open or shelter_closed), and the route (safe/blocked).
- Write a 1-2 sentence map message summarising your finding.

STEP 4 — ACTION PLAN
- Call fireguard_actions with your recommended actions.
- If the only nearby shelter is CLOSED: action must be to find and activate an open one, NOT to route there.
- If the route is blocked: action must reflect that.

STEP 5 — BRIEF
- Write a concise evacuation brief: affected zone, population, shelter status and why, route evaluation, recommended action.
- Never say "route is usable" when the destination is closed. That is operationally wrong.

For non-evacuation chat questions: answer directly using your tools (fireguard_health, fireguard_status, fireguard_search_shelters, fireguard_evaluate_route). Be concise and operational."""


root_agent = Agent(
    name="fireguard_agent_platform",
    model=os.environ.get("AGENT_RUNTIME_GEMINI_MODEL", "gemini-2.5-pro-preview-06-05"),
    description="FireGuard wildfire incident intelligence agent.",
    instruction=_SYSTEM_PROMPT,
    tools=[
        fireguard_health,
        fireguard_status,
        fireguard_search_shelters,
        fireguard_evaluate_route,
        fireguard_map_annotation,
        fireguard_actions,
    ],
)

adk_app = agent_engines.AdkApp(agent=root_agent, app_name="fireguard")
