from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.services.gemini import agent_manifest

router = APIRouter(prefix="/agent", tags=["gemini-agent"])


@router.get("/manifest")
def manifest(settings: Settings = Depends(get_settings)) -> dict:
    return agent_manifest(settings)
