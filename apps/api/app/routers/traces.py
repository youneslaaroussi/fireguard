from fastapi import APIRouter, Depends

from app.routers.dependencies import store_dependency
from app.services.store import FireGuardStore

router = APIRouter(prefix="/traces", tags=["traces"])


@router.get("/{incident_id}")
def traces(incident_id: str, store: FireGuardStore = Depends(store_dependency)) -> dict:
    records = [trace for trace in store.list("traces") if trace["incident_id"] == incident_id]
    records = sorted(records, key=lambda item: item["created_at"])
    return {"incident_id": incident_id, "traces": records, "latest": records[-1] if records else None}
