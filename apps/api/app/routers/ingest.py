from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.routers.dependencies import store_dependency
from app.services.ingest import (
    ingest_bc_perimeters,
    ingest_firms,
    ingest_public_ess_facilities,
    ingest_public_evacuation_orders,
    ingest_road_events,
    ingest_weather,
)
from app.services.store import FireGuardStore

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/synthetic/reset-demo")
def reset_demo(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return store.seed_demo()


@router.post("/firms")
async def firms(settings: Settings = Depends(get_settings), store: FireGuardStore = Depends(store_dependency)) -> dict:
    result = await ingest_firms(settings)
    store.bulk_upsert("fire_hotspots", result["docs"], "external_id")
    return {"status": "ok", "production_path": "fivetran_connector_sdk", "fallback_only": True, "count": len(result["docs"]), **{key: value for key, value in result.items() if key != "docs"}}


@router.post("/bc-perimeters")
async def bc_perimeters(store: FireGuardStore = Depends(store_dependency)) -> dict:
    result = await ingest_bc_perimeters()
    store.bulk_upsert("fire_perimeters", result["docs"], "fire_number")
    return {"status": "ok", "production_path": "fivetran_connector_sdk", "fallback_only": True, "count": len(result["docs"]), **{key: value for key, value in result.items() if key != "docs"}}


@router.post("/road-events")
async def road_events(store: FireGuardStore = Depends(store_dependency)) -> dict:
    result = await ingest_road_events()
    store.bulk_upsert("road_events", result["docs"], "external_id")
    return {"status": "ok", "production_path": "fivetran_connector_sdk", "fallback_only": True, "count": len(result["docs"]), **{key: value for key, value in result.items() if key != "docs"}}


@router.post("/weather")
async def weather(store: FireGuardStore = Depends(store_dependency)) -> dict:
    result = await ingest_weather()
    store.bulk_upsert("weather_observations", result["docs"], "weather_id")
    return {"status": "ok", "production_path": "fivetran_connector_sdk", "fallback_only": True, "count": len(result["docs"]), **{key: value for key, value in result.items() if key != "docs"}}


@router.post("/public-bc-context")
async def public_bc_context(store: FireGuardStore = Depends(store_dependency)) -> dict:
    orders = await ingest_public_evacuation_orders()
    facilities = await ingest_public_ess_facilities()
    store.bulk_upsert("public_evacuation_orders", orders["docs"], "order_alert_id")
    store.bulk_upsert("public_ess_facilities", facilities["docs"], "facility_id")
    return {
        "status": "ok",
        "production_path": "official_bc_arcgis_live_query",
        "orders": {"count": len(orders["docs"]), **{key: value for key, value in orders.items() if key != "docs"}},
        "facilities": {"count": len(facilities["docs"]), **{key: value for key, value in facilities.items() if key != "docs"}},
    }
