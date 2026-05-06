from fastapi import APIRouter, Depends

from app.models.schemas import ToolRequest
from app.routers.dependencies import store_dependency
from app.services.agent import tool_response
from app.services.store import FireGuardStore

router = APIRouter(prefix="/tools", tags=["agent-tools"])


@router.post("/get_incident_context")
def get_incident_context(request: ToolRequest, store: FireGuardStore = Depends(store_dependency)) -> dict:
    return tool_response("get_incident_context", request.payload, store)


@router.post("/search_operational_memory")
def search_operational_memory(request: ToolRequest, store: FireGuardStore = Depends(store_dependency)) -> dict:
    return tool_response("search_operational_memory", request.payload, store)


@router.post("/compute_zone_risk")
def compute_zone_risk(request: ToolRequest, store: FireGuardStore = Depends(store_dependency)) -> dict:
    return tool_response("compute_zone_risk", request.payload, store)


@router.post("/compute_routes")
def compute_routes(request: ToolRequest, store: FireGuardStore = Depends(store_dependency)) -> dict:
    return tool_response("compute_routes", request.payload, store)


@router.post("/draft_evacuation_plan")
def draft_evacuation_plan(request: ToolRequest, store: FireGuardStore = Depends(store_dependency)) -> dict:
    return tool_response("draft_evacuation_plan", request.payload, store)


@router.post("/create_action_bundle")
def create_action_bundle(request: ToolRequest, store: FireGuardStore = Depends(store_dependency)) -> dict:
    return tool_response("create_action_bundle", request.payload, store)


@router.post("/request_human_approval")
def request_human_approval(request: ToolRequest, store: FireGuardStore = Depends(store_dependency)) -> dict:
    return tool_response("request_human_approval", request.payload, store)


@router.post("/execute_approved_actions")
def execute_approved_actions(request: ToolRequest, store: FireGuardStore = Depends(store_dependency)) -> dict:
    return tool_response("execute_approved_actions", request.payload, store)
