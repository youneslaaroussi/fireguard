from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.schemas import AssessmentResult
from app.routers.dependencies import store_dependency
from app.services import demo_data
from app.services.agent import run_assessment, stream_assessment_events
from app.services.store import FireGuardStore

router = APIRouter(prefix="/incidents", tags=["incidents"])


class AssessmentRequest(BaseModel):
    commander_context: str | None = None
    custom_fires: list[dict] | None = None


@router.get("/current")
def current_incident(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return store.incident_context(demo_data.INCIDENT_ID)


@router.post("/assess", response_model=AssessmentResult)
def assess_current_incident(store: FireGuardStore = Depends(store_dependency)) -> AssessmentResult:
    return run_assessment(store, demo_data.INCIDENT_ID)


@router.post("/assess/stream")
def assess_current_incident_stream(
    body: AssessmentRequest | None = None,
    store: FireGuardStore = Depends(store_dependency),
) -> StreamingResponse:
    commander_context = body.commander_context if body else None
    custom_fires = body.custom_fires if body else None
    return StreamingResponse(
        stream_assessment_events(store, demo_data.INCIDENT_ID, commander_context=commander_context, custom_fires=custom_fires),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{incident_id}/context")
def incident_context(incident_id: str, store: FireGuardStore = Depends(store_dependency)) -> dict:
    return store.incident_context(incident_id)


@router.get("/{incident_id}/plan")
def incident_plan(incident_id: str, store: FireGuardStore = Depends(store_dependency)) -> dict:
    plans = [plan for plan in store.list("plans") if plan["incident_id"] == incident_id]
    return plans[-1] if plans else {"status": "not_found", "incident_id": incident_id}


@router.get("/{incident_id}/actions")
def incident_actions(incident_id: str, store: FireGuardStore = Depends(store_dependency)) -> dict:
    plans = [plan["plan_id"] for plan in store.list("plans") if plan["incident_id"] == incident_id]
    actions = [action for action in store.list("action_logs") if action.get("payload", {}).get("plan_id") in plans or action.get("payload", {}).get("source_plan_id") in plans]
    return {"incident_id": incident_id, "actions": actions}
