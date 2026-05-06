from app.config import get_settings
from app.services.store import FireGuardStore, get_store


def store_dependency() -> FireGuardStore:
    return get_store(get_settings())
