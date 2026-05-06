from fastapi import APIRouter, Depends

from app.routers.dependencies import store_dependency
from app.services.evals import evaluate_incident
from app.services.store import FireGuardStore

router = APIRouter(prefix="/evals", tags=["evals"])


@router.post("/{incident_id}")
def run_eval(incident_id: str, store: FireGuardStore = Depends(store_dependency)) -> dict:
    return evaluate_incident(store, incident_id)


@router.get("/{incident_id}")
def get_evals(incident_id: str, store: FireGuardStore = Depends(store_dependency)) -> dict:
    evals = [record for record in store.list("evals") if record["incident_id"] == incident_id]
    return {"incident_id": incident_id, "evals": evals, "latest": evals[-1] if evals else None}
