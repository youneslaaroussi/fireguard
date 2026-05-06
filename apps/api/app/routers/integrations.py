from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.routers.dependencies import store_dependency
from app.services.fivetran import fivetran_status
from app.services.gemini import gemini_status
from app.services.phoenix import phoenix_status
from app.services.store import FireGuardStore

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/status")
def integration_status(settings: Settings = Depends(get_settings), store: FireGuardStore = Depends(store_dependency)) -> dict:
    return {
        "fivetran": fivetran_status(store),
        "elastic": store.provider_status()["elastic"],
        "gemini": gemini_status(settings),
        "arize": phoenix_status(settings),
    }


@router.get("/fivetran/status")
def get_fivetran_status(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return fivetran_status(store)


@router.get("/arize/status")
def get_arize_status(settings: Settings = Depends(get_settings)) -> dict:
    return phoenix_status(settings)


@router.get("/gemini/status")
def get_gemini_status(settings: Settings = Depends(get_settings)) -> dict:
    return gemini_status(settings)
