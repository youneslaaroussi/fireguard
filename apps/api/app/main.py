from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import actions, agent, evals, incidents, ingest, integrations, residents, shelters, sync, tools, traces
from app.services.store import INDEX_MAPPINGS, get_store

settings = get_settings()

app = FastAPI(
    title="FireGuard API",
    description="Wildfire evacuation orchestration backend with Elastic-compatible operational memory and Gemini tool endpoints.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(incidents.router)
app.include_router(ingest.router)
app.include_router(actions.router)
app.include_router(agent.router)
app.include_router(evals.router)
app.include_router(integrations.router)
app.include_router(residents.router)
app.include_router(shelters.router)
app.include_router(sync.router)
app.include_router(tools.router)
app.include_router(traces.router)


@app.on_event("startup")
def startup() -> None:
    get_store(settings).ensure_seeded()


@app.get("/health")
def health() -> dict:
    store = get_store(settings)
    return {
        "status": "ok",
        "env": settings.app_env,
        "demo_mode": settings.demo_mode,
        "store_backend": store.backend_name(),
    }


@app.get("/elastic/mappings")
def elastic_mappings() -> dict:
    return {"mappings": INDEX_MAPPINGS}
