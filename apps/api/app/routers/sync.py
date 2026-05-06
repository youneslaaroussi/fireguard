from fastapi import APIRouter, Depends

from app.routers.dependencies import store_dependency
from app.services.fivetran import sync_fivetran_to_elastic
from app.services.store import FireGuardStore

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/fivetran-to-elastic")
def fivetran_to_elastic(store: FireGuardStore = Depends(store_dependency)) -> dict:
    return sync_fivetran_to_elastic(store)
