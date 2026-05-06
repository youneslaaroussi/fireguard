from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.dependencies import store_dependency
from app.services.store import FireGuardStore
from app.services.time import now_iso

router = APIRouter(prefix="/shelters", tags=["shelters"])


class CapacityCheckIn(BaseModel):
    capacity_available: int = Field(ge=0)
    capacity_total: int | None = Field(default=None, ge=0)
    updated_by: str = Field(min_length=2, max_length=120)
    note: str | None = Field(default=None, max_length=500)


@router.post("/{shelter_id}/capacity-check-in")
def capacity_check_in(
    shelter_id: str,
    payload: CapacityCheckIn,
    store: FireGuardStore = Depends(store_dependency),
) -> dict:
    shelter = store.get("shelters", shelter_id)
    if not shelter:
        raise HTTPException(status_code=404, detail="Shelter not found")

    capacity_total = payload.capacity_total if payload.capacity_total is not None else int(shelter.get("capacity_total", 0))
    if payload.capacity_available > capacity_total:
        raise HTTPException(status_code=400, detail="capacity_available cannot exceed capacity_total")

    timestamp = now_iso()
    update_id = f"CAPACITY_{shelter_id}_{timestamp}"
    source_label = (
        f"Operator capacity check-in by {payload.updated_by} at {timestamp}; "
        "not an official public ESS capacity feed."
    )
    updated_shelter = {
        **shelter,
        "capacity_total": capacity_total,
        "capacity_available": payload.capacity_available,
        "capacity_is_operator_assumption": False,
        "capacity_operator_confirmed": True,
        "capacity_source_type": "operator_capacity_check_in",
        "capacity_source_label": source_label,
        "capacity_confirmed_at": timestamp,
        "capacity_confirmed_by": payload.updated_by,
        "capacity_update_note": payload.note,
        "updated_at": timestamp,
    }
    update = {
        "update_id": update_id,
        "shelter_id": shelter_id,
        "capacity_total": capacity_total,
        "capacity_available": payload.capacity_available,
        "updated_by": payload.updated_by,
        "updated_at": timestamp,
        "note": payload.note,
        "source_type": "operator_capacity_check_in",
        "official_capacity_feed": False,
    }
    store.upsert("shelters", shelter_id, updated_shelter)
    store.upsert("capacity_updates", update_id, update)
    return {"shelter": updated_shelter, "capacity_update": update}
