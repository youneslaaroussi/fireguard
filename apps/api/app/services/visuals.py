from __future__ import annotations

import html
import json
from typing import Any

from app.models.schemas import RouteOption
from app.services import demo_data
from app.services.routes import compute_routes
from app.services.store import FireGuardStore


SVG_HEADER = """<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{title}">"""


def render_route_map_svg(store: FireGuardStore, incident_id: str = demo_data.INCIDENT_ID) -> str:
    context = store.incident_context(incident_id)
    plan = _latest_plan(store, incident_id)
    routes = _routes_from_plan(plan)
    if not routes:
        routes = [route.model_dump() for route in compute_routes(context, google_maps_api_key=store.settings.google_maps_api_key)]

    selected_keys = {
        (step.get("zone_id"), step.get("destination_id"))
        for step in (plan or {}).get("steps", [])
        if step.get("destination_id")
    }
    rejected_keys = {
        (item.get("origin_id"), item.get("destination_id"))
        for item in (plan or {}).get("rejected_alternatives", [])
        if item.get("origin_id") and item.get("destination_id")
    }

    width, height = 1280, 720
    map_box = (54, 118, 790, 542)
    points = _visual_points(context, routes)
    project = _projector(points, map_box)
    safe_count = sum(1 for route in routes if route.get("safe") is True)
    blocked_count = sum(1 for route in routes if route.get("safe") is False)
    strategy = _escape((plan or {}).get("recommended_strategy", "route options").replace("_", " ").title())
    summary = _truncate((plan or {}).get("summary") or "Current route options generated from FireGuard assessment evidence.", 128)

    route_paths = []
    for route in routes:
        route_paths.append(_route_path(route, project, selected_keys, rejected_keys))

    zone_nodes = []
    for zone in context.get("zones", []):
        centroid = zone.get("centroid") or {}
        if _valid_point(centroid):
            x, y = project(centroid["lon"], centroid["lat"])
            zone_nodes.append(
                f"""
                <g>
                  <circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="#f9c74f" stroke="#0b1117" stroke-width="3"/>
                  <text x="{x + 12:.1f}" y="{y + 4:.1f}" class="map-label">{_escape(zone.get("zone_id", "zone"))}</text>
                </g>"""
            )

    shelter_nodes = []
    for shelter in context.get("shelters", []):
        location = shelter.get("location") or {}
        if _valid_point(location):
            x, y = project(location["lon"], location["lat"])
            fill = "#32d583" if str(shelter.get("status", "")).upper() == "OPEN" else "#ff5a5f"
            shelter_nodes.append(
                f"""
                <g>
                  <rect x="{x - 8:.1f}" y="{y - 8:.1f}" width="16" height="16" rx="3" fill="{fill}" stroke="#0b1117" stroke-width="3"/>
                  <text x="{x + 12:.1f}" y="{y + 4:.1f}" class="map-label">{_escape(shelter.get("shelter_id", "shelter"))}</text>
                </g>"""
            )

    fire_nodes = []
    for fire in context.get("fires", [])[:12]:
        location = fire.get("location") or {}
        if _valid_point(location):
            x, y = project(location["lon"], location["lat"])
            fire_nodes.append(
                f"""<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#ff6b35" stroke="#ffd166" stroke-width="1.5" opacity="0.95"/>"""
            )

    road_nodes = []
    for event in context.get("road_events", [])[:10]:
        location = event.get("location") or {}
        if _valid_point(location):
            x, y = project(location["lon"], location["lat"])
            road_nodes.append(
                f"""
                <g>
                  <path d="M{x - 7:.1f},{y - 7:.1f} L{x + 7:.1f},{y + 7:.1f} M{x + 7:.1f},{y - 7:.1f} L{x - 7:.1f},{y + 7:.1f}" stroke="#ff4d4f" stroke-width="3" stroke-linecap="round"/>
                  <circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="none" stroke="#ff4d4f" stroke-width="1.5" opacity="0.8"/>
                </g>"""
            )

    cards = _route_cards(routes, selected_keys, rejected_keys)
    return f"""{SVG_HEADER.format(width=width, height=height, title='FireGuard route options map')}
  <style>
    .bg {{ fill: #071017; }}
    .panel {{ fill: #0d1822; stroke: #294158; stroke-width: 1; }}
    .map {{ fill: #09131c; stroke: #38566f; stroke-width: 1.2; }}
    .grid {{ stroke: #1c3447; stroke-width: 1; opacity: 0.62; }}
    .title {{ fill: #f4f7fb; font: 700 34px Inter, Arial, sans-serif; letter-spacing: 0; }}
    .sub {{ fill: #b7c4d2; font: 500 17px Inter, Arial, sans-serif; }}
    .eyebrow {{ fill: #77a6ff; font: 800 13px Inter, Arial, sans-serif; letter-spacing: 3px; }}
    .metric {{ fill: #f4f7fb; font: 800 36px Inter, Arial, sans-serif; }}
    .metric-label {{ fill: #93a4b7; font: 700 12px Inter, Arial, sans-serif; letter-spacing: 2px; }}
    .route-card-title {{ fill: #f4f7fb; font: 800 16px Inter, Arial, sans-serif; }}
    .route-card-meta {{ fill: #b5c3d4; font: 600 13px Inter, Arial, sans-serif; }}
    .route-card-reason {{ fill: #8fa0b2; font: 500 12px Inter, Arial, sans-serif; }}
    .map-label {{ fill: #d9e4f1; font: 800 12px Inter, Arial, sans-serif; paint-order: stroke; stroke: #071017; stroke-width: 3; }}
    .watermark {{ fill: #355166; font: 700 12px Inter, Arial, sans-serif; letter-spacing: 2px; opacity: 0.72; }}
  </style>
  <rect class="bg" width="{width}" height="{height}"/>
  <rect x="24" y="24" width="{width - 48}" height="{height - 48}" rx="12" class="panel"/>
  <text x="54" y="72" class="eyebrow">FIREGUARD ROUTE DECISION ARTIFACT</text>
  <text x="54" y="108" class="title">{strategy}</text>
  <text x="54" y="136" class="sub">{_escape(summary)}</text>
  <rect x="{map_box[0]}" y="{map_box[1]}" width="{map_box[2]}" height="{map_box[3]}" rx="8" class="map"/>
  {_grid(map_box)}
  {''.join(route_paths)}
  {''.join(fire_nodes)}
  {''.join(road_nodes)}
  {''.join(zone_nodes)}
  {''.join(shelter_nodes)}
  <text x="{map_box[0] + 20}" y="{map_box[1] + map_box[3] - 22}" class="watermark">ROUTES FROM GOOGLE ROUTES + FIREGUARD VALIDATION</text>
  <rect x="880" y="118" width="346" height="112" rx="8" class="panel"/>
  <text x="904" y="154" class="metric-label">SAFE ROUTES</text>
  <text x="904" y="196" class="metric">{safe_count}</text>
  <text x="1054" y="154" class="metric-label">REJECTED</text>
  <text x="1054" y="196" class="metric">{blocked_count}</text>
  <rect x="880" y="254" width="346" height="406" rx="8" class="panel"/>
  <text x="904" y="292" class="eyebrow">ROUTE EVIDENCE</text>
  {cards}
</svg>"""


def render_tool_trace_svg(store: FireGuardStore, incident_id: str = demo_data.INCIDENT_ID) -> str:
    trace = _latest_trace(store, incident_id)
    events = trace.get("events") or []
    width, height = 1280, 720
    visible_events = events[:12]
    if not visible_events:
        visible_events = [
            {"event_id": "trace-000", "step": "observe", "tool": "run_assessment", "evidence_ids": [], "assumption_ids": []}
        ]

    nodes = []
    x0, y0 = 76, 194
    dx, dy = 260, 142
    for index, event in enumerate(visible_events):
        col = index % 4
        row = index // 4
        x = x0 + col * dx
        y = y0 + row * dy
        nodes.append(_trace_node(event, x, y, index + 1))

    edges = []
    for index in range(len(visible_events) - 1):
        col = index % 4
        row = index // 4
        next_col = (index + 1) % 4
        next_row = (index + 1) // 4
        x1 = x0 + col * dx + 188
        y1 = y0 + row * dy + 42
        x2 = x0 + next_col * dx
        y2 = y0 + next_row * dy + 42
        if next_row == row:
            path = f"M{x1},{y1} L{x2 - 16},{y2}"
        else:
            path = f"M{x1},{y1} L{x1 + 36},{y1} L{x1 + 36},{y1 + 70} L{x0 - 16},{y1 + 70} L{x0 - 16},{y2} L{x2 - 16},{y2}"
        edges.append(f"""<path d="{path}" fill="none" stroke="#355166" stroke-width="2.5" marker-end="url(#arrow)"/>""")

    phoenix = len([event for event in events if event.get("phoenix_trace_id")])
    arize = len([event for event in events if event.get("arize_ax_trace_id")])
    evidence = sum(len(event.get("evidence_ids") or []) for event in events)
    return f"""{SVG_HEADER.format(width=width, height=height, title='FireGuard tool usage trace')}
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#355166"/>
    </marker>
  </defs>
  <style>
    .bg {{ fill: #071017; }}
    .panel {{ fill: #0d1822; stroke: #294158; stroke-width: 1; }}
    .title {{ fill: #f4f7fb; font: 700 34px Inter, Arial, sans-serif; }}
    .sub {{ fill: #b7c4d2; font: 500 17px Inter, Arial, sans-serif; }}
    .eyebrow {{ fill: #77a6ff; font: 800 13px Inter, Arial, sans-serif; letter-spacing: 3px; }}
    .node-title {{ fill: #f4f7fb; font: 800 15px Inter, Arial, sans-serif; }}
    .node-meta {{ fill: #9babbc; font: 700 11px Inter, Arial, sans-serif; letter-spacing: 1.8px; }}
    .node-small {{ fill: #b7c4d2; font: 600 12px Inter, Arial, sans-serif; }}
    .badge {{ fill: #17345a; stroke: #3b82f6; stroke-width: 1; }}
    .badge-text {{ fill: #d8e8ff; font: 800 13px Inter, Arial, sans-serif; }}
    .metric {{ fill: #f4f7fb; font: 800 32px Inter, Arial, sans-serif; }}
    .metric-label {{ fill: #93a4b7; font: 700 12px Inter, Arial, sans-serif; letter-spacing: 2px; }}
  </style>
  <rect class="bg" width="{width}" height="{height}"/>
  <rect x="24" y="24" width="{width - 48}" height="{height - 48}" rx="12" class="panel"/>
  <text x="54" y="72" class="eyebrow">FIREGUARD TOOL TRACE ARTIFACT</text>
  <text x="54" y="108" class="title">Assessment Tool Chain</text>
  <text x="54" y="136" class="sub">Each box is a backend tool span captured during the latest incident assessment.</text>
  <rect x="930" y="54" width="92" height="74" rx="8" class="panel"/>
  <text x="950" y="84" class="metric-label">EVIDENCE</text>
  <text x="950" y="116" class="metric">{evidence}</text>
  <rect x="1036" y="54" width="84" height="74" rx="8" class="panel"/>
  <text x="1056" y="84" class="metric-label">PHX</text>
  <text x="1056" y="116" class="metric">{phoenix}</text>
  <rect x="1134" y="54" width="84" height="74" rx="8" class="panel"/>
  <text x="1154" y="84" class="metric-label">AX</text>
  <text x="1154" y="116" class="metric">{arize}</text>
  {''.join(edges)}
  {''.join(nodes)}
</svg>"""


def _latest_plan(store: FireGuardStore, incident_id: str) -> dict[str, Any] | None:
    plans = [plan for plan in store.list("plans") if plan.get("incident_id") == incident_id]
    if plans:
        return plans[-1]
    if not store.es or store.elastic_error:
        return None
    try:
        response = store.es.search(
            index="plans",
            size=1,
            query={"match": {"incident_id": incident_id}},
        )
    except Exception:
        return None
    hits = response.get("hits", {}).get("hits", [])
    return hits[0].get("_source") if hits else None


def _latest_trace(store: FireGuardStore, incident_id: str) -> dict[str, Any]:
    traces = [trace for trace in store.list("traces") if trace.get("incident_id") == incident_id]
    memory_traces_with_events = [trace for trace in traces if trace.get("events")]
    if memory_traces_with_events:
        return sorted(memory_traces_with_events, key=lambda trace: trace.get("created_at", ""))[-1]
    if not store.es or store.elastic_error:
        return sorted(traces, key=lambda trace: trace.get("created_at", ""))[-1] if traces else {}
    try:
        response = store.es.search(
            index="traces",
            size=1,
            query={"match": {"incident_id": incident_id}},
            sort=[{"created_at": {"order": "desc"}}],
        )
    except Exception:
        return {}
    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        return {}
    source = dict(hits[0].get("_source") or {})
    if isinstance(source.get("events_json"), str):
        try:
            source["events"] = json.loads(source["events_json"])
        except json.JSONDecodeError:
            source["events"] = []
    return source


def _routes_from_plan(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not plan:
        return []
    routes = plan.get("routes")
    return routes if isinstance(routes, list) else []


def _visual_points(context: dict[str, Any], routes: list[dict[str, Any]]) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for route in routes:
        points.extend(point for point in route.get("polyline", []) if _valid_point(point))
    for zone in context.get("zones", []):
        centroid = zone.get("centroid")
        if _valid_point(centroid):
            points.append(centroid)
    for shelter in context.get("shelters", []):
        location = shelter.get("location")
        if _valid_point(location):
            points.append(location)
    for fire in context.get("fires", [])[:20]:
        location = fire.get("location")
        if _valid_point(location):
            points.append(location)
    for event in context.get("road_events", [])[:20]:
        location = event.get("location")
        if _valid_point(location):
            points.append(location)
    return points or [{"lat": 52.1, "lon": -122.1}, {"lat": 53.2, "lon": -120.2}]


def _projector(points: list[dict[str, float]], box: tuple[int, int, int, int]):
    left, top, width, height = box
    lons = [point["lon"] for point in points]
    lats = [point["lat"] for point in points]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    lon_pad = max((max_lon - min_lon) * 0.08, 0.05)
    lat_pad = max((max_lat - min_lat) * 0.08, 0.05)
    min_lon -= lon_pad
    max_lon += lon_pad
    min_lat -= lat_pad
    max_lat += lat_pad

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = left + ((lon - min_lon) / max(max_lon - min_lon, 0.000001)) * width
        y = top + (1 - ((lat - min_lat) / max(max_lat - min_lat, 0.000001))) * height
        return x, y

    return project


def _route_path(route: dict[str, Any], project, selected_keys: set[tuple[Any, Any]], rejected_keys: set[tuple[Any, Any]]) -> str:
    points = [point for point in route.get("polyline", []) if _valid_point(point)]
    if len(points) < 2:
        return ""
    sampled = _sample(points, 280)
    commands = []
    for index, point in enumerate(sampled):
        x, y = project(point["lon"], point["lat"])
        commands.append(("M" if index == 0 else "L") + f"{x:.1f},{y:.1f}")
    key = (route.get("origin_id"), route.get("destination_id"))
    selected = key in selected_keys
    rejected = key in rejected_keys or route.get("safe") is False
    color = "#36d399" if selected else "#4cc9f0" if route.get("safe") else "#ff5a5f"
    width = 5.5 if selected else 3.5 if route.get("safe") else 3
    dash = " stroke-dasharray=\"10 8\"" if rejected and not selected else ""
    opacity = "0.95" if selected or rejected else "0.62"
    return f"""<path d="{' '.join(commands)}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" opacity="{opacity}"{dash}/>"""


def _route_cards(routes: list[dict[str, Any]], selected_keys: set[tuple[Any, Any]], rejected_keys: set[tuple[Any, Any]]) -> str:
    ranked = sorted(
        routes,
        key=lambda route: (
            0 if (route.get("origin_id"), route.get("destination_id")) in selected_keys else 1,
            0 if route.get("safe") is False or (route.get("origin_id"), route.get("destination_id")) in rejected_keys else 1,
            route.get("duration_minutes", 9999),
        ),
    )[:5]
    cards = []
    for index, route in enumerate(ranked):
        y = 320 + index * 62
        key = (route.get("origin_id"), route.get("destination_id"))
        selected = key in selected_keys
        safe = route.get("safe") is True
        color = "#36d399" if selected else "#4cc9f0" if safe else "#ff5a5f"
        status = "SELECTED" if selected else "SAFE" if safe else "REJECTED"
        reason = _truncate("; ".join(route.get("risk_flags") or []) or "Validated route option.", 74)
        title = f"{route.get('origin_id')} -> {route.get('destination_id')}"
        cards.append(
            f"""
            <g>
              <rect x="904" y="{y - 22}" width="292" height="52" rx="6" fill="#09131c" stroke="#22394d"/>
              <circle cx="924" cy="{y + 3}" r="6" fill="{color}"/>
              <text x="940" y="{y - 2}" class="route-card-title">{_escape(title)}</text>
              <text x="940" y="{y + 17}" class="route-card-meta">{status} · {route.get('duration_minutes', '?')} min · {route.get('distance_km', '?')} km</text>
              <text x="904" y="{y + 48}" class="route-card-reason">{_escape(reason)}</text>
            </g>"""
        )
    return "".join(cards)


def _trace_node(event: dict[str, Any], x: int, y: int, number: int) -> str:
    tool = _truncate(str(event.get("tool") or "tool"), 27)
    step = _truncate(str(event.get("step") or "tool"), 18).upper()
    evidence = len(event.get("evidence_ids") or [])
    assumptions = len(event.get("assumption_ids") or [])
    has_span = bool(event.get("phoenix_trace_id") or event.get("arize_ax_trace_id"))
    fill = "#102132" if has_span else "#09131c"
    return f"""
    <g>
      <rect x="{x}" y="{y}" width="204" height="84" rx="8" fill="{fill}" stroke="#294158" stroke-width="1.4"/>
      <rect x="{x + 14}" y="{y + 14}" width="30" height="30" rx="15" class="badge"/>
      <text x="{x + 23}" y="{y + 35}" class="badge-text">{number}</text>
      <text x="{x + 56}" y="{y + 27}" class="node-meta">{_escape(step)}</text>
      <text x="{x + 56}" y="{y + 50}" class="node-title">{_escape(tool)}</text>
      <text x="{x + 16}" y="{y + 72}" class="node-small">evidence {evidence} · assumptions {assumptions}</text>
    </g>"""


def _grid(box: tuple[int, int, int, int]) -> str:
    left, top, width, height = box
    lines = []
    for index in range(1, 5):
        x = left + width * index / 5
        lines.append(f"""<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + height}" class="grid"/>""")
    for index in range(1, 4):
        y = top + height * index / 4
        lines.append(f"""<line x1="{left}" y1="{y:.1f}" x2="{left + width}" y2="{y:.1f}" class="grid"/>""")
    return "".join(lines)


def _sample(points: list[dict[str, float]], limit: int) -> list[dict[str, float]]:
    if len(points) <= limit:
        return points
    step = max(len(points) // limit, 1)
    sampled = points[::step]
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled


def _valid_point(point: Any) -> bool:
    return (
        isinstance(point, dict)
        and isinstance(point.get("lat"), int | float)
        and isinstance(point.get("lon"), int | float)
    )


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "..."
