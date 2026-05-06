from fastapi import APIRouter, Depends

from app.models.schemas import AssessmentResult
from app.routers.dependencies import store_dependency
from app.services import demo_data
from app.services.agent import run_assessment
from app.services.store import FireGuardStore

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("/current")
def current_incident(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return store.incident_context(demo_data.INCIDENT_ID)


@router.post("/assess", response_model=AssessmentResult)
def assess_current_incident(store: FireGuardStore = Depends(store_dependency)) -> AssessmentResult:
    return run_assessment(store, demo_data.INCIDENT_ID)


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
