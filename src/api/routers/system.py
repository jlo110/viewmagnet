"""Health / readiness / liveness probes.

- ``/`` -- friendly root for smoke tests
- ``/livez`` -- liveness (always 200 if process is up)
- ``/readyz`` -- readiness (DB + Redis reachable; 503 otherwise)
- ``/health`` -- detailed status retained for backwards compatibility
"""
from __future__ import annotations

import os

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.config import get_settings
from src.database.connection import get_async_session

logger = structlog.get_logger(__name__)
settings = get_settings()

router = APIRouter(tags=["system"])


@router.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "healthy", "service": "ViewMagnet API", "version": "1.0.0"}


@router.get("/livez", include_in_schema=False)
async def livez():
    """Liveness probe: the process is up. Always 200 if we can answer."""
    return {"status": "alive"}


@router.get("/readyz", include_in_schema=False)
async def readyz():
    """Readiness probe: DB and Redis reachable."""
    from sqlalchemy import text

    db_status = "disconnected"
    try:
        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error("readyz.db_failed", error=str(e))

    redis_status = "disconnected"
    try:
        from src.cache import redis as redis_module
        if await redis_module.ping():
            redis_status = "connected"
    except Exception as e:
        logger.warning("readyz.redis_failed", error=str(e))

    ready = db_status == "connected"
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "database": db_status,
            "redis": redis_status,
        },
    )


@router.get("/health")
async def health():
    """Detailed health check (backwards compatible).

    Reports DB + Redis + optional model status. Returns 200 unless DB is down.
    Use ``/livez`` and ``/readyz`` for orchestrator probes.
    """
    from sqlalchemy import text

    db_status = "disconnected"
    try:
        async with get_async_session() as session:
            await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error("health.db_failed", error=str(e))

    # Resolve via the model registry (single source of truth) instead of
    # hardcoded paths, with a graceful fallback if the registry is unavailable.
    try:
        from src.ml import registry

        model_loaded = registry.artifact_exists("content_classifier")
        velocity_models_loaded = registry.artifact_exists("velocity_horizons")
    except Exception:
        model_loaded = os.path.exists("data/models/clean_predictor.pkl")
        velocity_models_loaded = os.path.exists("models/velocity_models_index.joblib")

    redis_status = "disconnected"
    try:
        from src.cache import redis as redis_module
        if await redis_module.ping():
            redis_status = "connected"
    except Exception:
        pass

    if db_status == "connected" and model_loaded:
        overall_status = "healthy"
        status_code = 200
    elif db_status == "connected":
        overall_status = "degraded"
        status_code = 200
    else:
        overall_status = "unhealthy"
        status_code = 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall_status,
            "database": db_status,
            "redis": redis_status,
            "model_loaded": model_loaded,
            "velocity_models_loaded": velocity_models_loaded,
            "environment": settings.environment,
        },
    )
