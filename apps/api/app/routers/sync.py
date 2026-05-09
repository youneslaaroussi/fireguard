from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.routers.dependencies import store_dependency
from app.services.fivetran import sync_fivetran_to_elastic
from app.services.live_overlay import sync_live_overlay
from app.services.shelter_capacity import sync_google_sheets_shelter_capacity
from app.services.source_zone_context import sync_source_backed_zone_context
from app.services.store import FireGuardStore
from app.services.zone_operations import sync_google_sheets_zone_operations

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/fivetran-to-elastic")
def fivetran_to_elastic(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return sync_fivetran_to_elastic(store)


@router.post("/live-overlay")
async def live_overlay(settings: Settings = Depends(get_settings), store: FireGuardStore = Depends(store_dependency)) -> dict:
    return await sync_live_overlay(store, settings)


@router.post("/google-sheets-shelter-capacity")
def google_sheets_shelter_capacity(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return sync_google_sheets_shelter_capacity(store)


@router.post("/google-sheets-zone-operations")
def google_sheets_zone_operations(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return sync_google_sheets_zone_operations(store)


@router.post("/source-backed-zone-context")
def source_backed_zone_context(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return sync_source_backed_zone_context(store)
