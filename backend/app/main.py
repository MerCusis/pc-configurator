"""Точка входа FastAPI."""
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import builds, catalog, sessions
from app.config import get_settings
from app.database import check_db, engine
from app.redis_client import check_redis, redis_client

from app.openapi_patch import install_openapi

settings = get_settings()
API = settings.api_prefix
VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(
    title="PC Configurator API",
    version=VERSION,
    lifespan=lifespan,
    # В production Swagger выключен
    docs_url=None if settings.is_production else f"{API}/docs",
    openapi_url=None if settings.is_production else f"{API}/openapi.json",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.get(f"{API}/health/live", tags=["system"])
async def liveness() -> dict[str, str]:
    """Процесс жив. Используется healthcheck контейнера, БД не трогает."""
    return {"status": "alive"}


@app.get(f"{API}/health", tags=["system"])
async def readiness() -> JSONResponse:
    """Готовность: доступны ли PostgreSQL и Redis. 503, если что-то лежит."""
    db_ok, redis_ok = await asyncio.gather(check_db(), check_redis())
    ok = db_ok and redis_ok
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded", "db": db_ok, "redis": redis_ok, "version": VERSION},
    )


for _router in (sessions.router, catalog.router, builds.router):
    app.include_router(_router, prefix=API)

install_openapi(app)
