from fastapi import APIRouter, Depends, Response

from app.routers.dependencies import store_dependency
from app.services import demo_data
from app.services.store import FireGuardStore
from app.services.visuals import render_route_map_svg, render_tool_trace_svg

router = APIRouter(prefix="/visuals", tags=["visuals"])


@router.get("/route-map.svg")
def route_map(
    incident_id: str = demo_data.INCIDENT_ID,
    store: FireGuardStore = Depends(store_dependency),
) -> Response:
    svg = render_route_map_svg(store, incident_id)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/tool-trace.svg")
def tool_trace(
    incident_id: str = demo_data.INCIDENT_ID,
    store: FireGuardStore = Depends(store_dependency),
) -> Response:
    svg = render_tool_trace_svg(store, incident_id)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )
