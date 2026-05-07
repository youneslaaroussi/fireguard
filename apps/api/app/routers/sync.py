from fastapi import APIRouter, Depends

from app.routers.dependencies import store_dependency
from app.services.fivetran import sync_fivetran_to_elastic
from app.services.shelter_capacity import sync_google_sheets_shelter_capacity
from app.services.store import FireGuardStore
from app.services.zone_operations import sync_google_sheets_zone_operations

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/fivetran-to-elastic")
def fivetran_to_elastic(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return sync_fivetran_to_elastic(store)


@router.post("/google-sheets-shelter-capacity")
def google_sheets_shelter_capacity(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return sync_google_sheets_shelter_capacity(store)


@router.post("/google-sheets-zone-operations")
def google_sheets_zone_operations(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return sync_google_sheets_zone_operations(store)
