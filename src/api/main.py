"""
ViewMagnet API - FastAPI application factory.

This module is intentionally thin: app + lifespan + middleware + router wiring.
All endpoints live under :mod:`src.api.routers` as one module per domain.
See ``src/api/routers/__init__.py`` for the canonical list.

Heavy logic that's shared between routers lives in :mod:`src.api._common`
(usage limits, channel handle resolution, in-memory alert state).
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.errors import install_error_handlers, request_id_middleware
from src.api.limiter import limiter
from src.api.openapi import (
    API_DESCRIPTION,
    API_VERSION,
    OPENAPI_TAGS,
    build_openapi_servers,
    customize_openapi_schema,
)
from src.api.routers import ALL_ROUTERS
from src.auth.routes import router as auth_router
from src.config import get_settings
from src.database.connection import get_session
from src.security.crypto import scrub_tokens_processor

logger = structlog.get_logger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Optional integrations: Sentry + structured logging
# ---------------------------------------------------------------------------
if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.1 if settings.is_production else 1.0,
            profiles_sample_rate=0.1 if settings.is_production else 1.0,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
            ],
        )
        logger.info("Sentry initialized", environment=settings.environment)
    except ImportError:
        logger.warning("Sentry SDK not installed, skipping initialization")


structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        scrub_tokens_processor,
        (
            structlog.processors.JSONRenderer()
            if settings.is_production
            else structlog.dev.ConsoleRenderer()
        ),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)


# ---------------------------------------------------------------------------
# Lifespan: warm DB + Redis on startup, drain on shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup and clean up on shutdown."""
    try:
        # Schema is owned by Alembic; we only verify connectivity here.
        # (Multiple uvicorn workers racing on metadata.create_all causes
        # spurious duplicate-key errors on pg_type during startup.)
        from sqlalchemy import text
        with get_session() as session:
            session.execute(text("SELECT 1"))
        logger.info("startup.db_verified", mode=settings.environment)
    except Exception as e:
        logger.error("startup.db_failed", error=str(e))
        if settings.is_production:
            raise

    # Auto-create tables added in non-production environments. This is the
    # equivalent of running an alembic migration in dev — production envs
    # are expected to apply migrations out-of-band, so we skip this there
    # to avoid the "Multiple uvicorn workers racing on metadata.create_all"
    # issue called out above. ``create_all`` is idempotent: it only creates
    # missing tables, so this is safe to call on every boot in dev.
    if not settings.is_production:
        try:
            from src.database.connection import get_engine
            from src.database.models import Base
            Base.metadata.create_all(bind=get_engine())
            logger.info("startup.db_create_all_dev")
        except Exception as e:
            logger.warning("startup.db_create_all_failed", error=str(e))

    try:
        from src.cache import get_redis
        client = get_redis()
        await client.ping()
        logger.info("startup.redis_ready")
    except Exception as e:
        logger.warning("startup.redis_unavailable", error=str(e))

    # Reset orphaned Studio long-job statuses. If a worker crashed mid-job
    # (e.g. the macOS objc-fork crash that took out compute_tracking before
    # we switched to SimpleWorker), the EditSession row is stuck saying
    # ``rendering`` / ``computing`` forever and the polling UI just spins.
    # Sweeping on each API boot makes restarts self-healing.
    try:
        from src.database.models import EditSession
        with get_session() as session:
            rendering = (
                session.query(EditSession)
                .filter(EditSession.last_render_status == "rendering")
                .update({
                    "last_render_status": "failed",
                    "last_render_error": "API restarted while job was running",
                })
            )
            tracking = (
                session.query(EditSession)
                .filter(EditSession.tracking_status == "computing")
                .update({
                    "tracking_status": "idle",
                    "tracking_progress_message": "Reset on API restart",
                })
            )
            session.commit()
            if rendering or tracking:
                logger.info(
                    "startup.studio_jobs_reset",
                    rendering_reset=rendering,
                    tracking_reset=tracking,
                )
    except Exception as e:
        logger.warning("startup.studio_reset_failed", error=str(e))

    # ------------------------------------------------------------------
    # Register real platform metrics fetchers (no-op when libs absent).
    # ------------------------------------------------------------------
    try:
        from src.features.distribution.youtube_metrics import register as _yt_register
        _yt_register()
    except Exception as _e:
        logger.warning("startup.youtube_metrics_register_failed", error=str(_e))

    # ------------------------------------------------------------------
    # Metrics collection scheduler — sweeps due PublishedMetricSnapshot
    # windows every hour using APScheduler (background thread).
    #
    # MUST run in exactly one process. Under ``uvicorn --workers N`` the
    # lifespan runs once per worker, so an unguarded scheduler fires the
    # hourly job N times (duplicate snapshots, wasted YouTube quota, write
    # races). It is therefore gated behind ``RUN_SCHEDULER`` and disabled by
    # default — enable it on a single dedicated process (the worker/scheduler
    # container), never on a multi-worker API.
    #
    # Gracefully skipped when APScheduler isn't installed.
    # ------------------------------------------------------------------
    _scheduler = None
    if not settings.run_scheduler:
        logger.info(
            "startup.metrics_scheduler_disabled",
            message="RUN_SCHEDULER is not set; scheduler runs only on the dedicated process",
        )
    else:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler

            from src.scheduler import register_jobs

            _scheduler = BackgroundScheduler(
                job_defaults={"misfire_grace_time": 300, "coalesce": True},
                timezone="UTC",
            )
            register_jobs(_scheduler)
            _scheduler.start()
            logger.info("startup.metrics_scheduler_started", interval_hours=1)
        except ImportError:
            logger.warning(
                "startup.apscheduler_not_installed",
                message="pip install apscheduler to enable hourly metrics collection",
            )
        except Exception as _e:
            logger.warning("startup.metrics_scheduler_failed", error=str(_e))

    yield

    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass

    try:
        from src.cache import get_redis
        client = get_redis()
        if hasattr(client, "close"):
            await client.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ViewMagnet API",
    description=API_DESCRIPTION,
    version=API_VERSION,
    # Disable Swagger UI / ReDoc in production — the canonical public API
    # reference lives at https://viewmagnet.io/docs (Scalar, rendered from
    # ``/openapi.json`` below). The internal ones stay on in dev so the
    # FastAPI muscle memory still works locally.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_tags=OPENAPI_TAGS,
    servers=build_openapi_servers(settings),
    contact={
        "name": "ViewMagnet Support",
        "url": "https://viewmagnet.io/contact",
        "email": "hello@viewmagnet.app",
    },
    license_info={
        "name": "Proprietary",
        "url": "https://viewmagnet.io/terms",
    },
    terms_of_service="https://viewmagnet.io/terms",
    lifespan=lifespan,
)

# Override the OpenAPI schema generator so the rendered docs page gets
# the security scheme, branded logo, and external-docs link Scalar
# expects. The customization is applied lazily on first request (and
# cached by FastAPI thereafter) so app startup stays fast.
app.openapi = customize_openapi_schema(app)  # type: ignore[method-assign]

# Auth routes (mounted first so they get auth/rate-limit + error envelopes).
app.include_router(auth_router)

# Shared rate limiter (Redis-backed when REDIS_URL is set).
app.state.limiter = limiter

# Trusted hosts (Host-header / DNS-rebind protection). Skipped when the
# allowlist is the default "*" so existing deploys are unaffected; set
# ALLOWED_HOSTS to the real domains in production to enforce.
_allowed_hosts = settings.allowed_hosts_list
if _allowed_hosts != ["*"]:
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)

# CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Request-ID middleware so error responses can include the request id.
app.middleware("http")(request_id_middleware)

# Unified error handlers (HTTP, validation, rate-limit, LLM budget, fallthrough).
install_error_handlers(app)

# Prometheus metrics endpoint (graceful fallback when not installed).
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator(should_group_status_codes=True).instrument(app).expose(
        app, endpoint="/metrics", include_in_schema=False
    )
    logger.info("startup.prometheus_enabled")
except ImportError:
    logger.warning(
        "startup.prometheus_unavailable",
        message="prometheus-fastapi-instrumentator not installed",
    )

# OpenTelemetry instrumentation (graceful fallback).
try:
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info(
            "startup.otel_enabled",
            endpoint=os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"],
        )
except Exception as e:
    logger.warning("startup.otel_unavailable", error=str(e))


# ---------------------------------------------------------------------------
# Mount domain routers
# ---------------------------------------------------------------------------
for router in ALL_ROUTERS:
    app.include_router(router)


# Static mount for the Studio source-normalization cache. The
# ``/studio/source-proxy`` endpoint 307-redirects here so the browser issues
# Range requests directly against Starlette's StaticFiles (which handles
# ``bytes=...`` natively — critical for `<video>` seeking and Safari).
try:
    from fastapi.staticfiles import StaticFiles

    from src.features.studio.source_proxy import CACHE_DIR as _SOURCE_CACHE_DIR

    _SOURCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/studio/source-cache",
        StaticFiles(directory=str(_SOURCE_CACHE_DIR)),
        name="studio_source_cache",
    )
    logger.info("startup.studio_source_cache_mounted", path=str(_SOURCE_CACHE_DIR))
except Exception as e:
    logger.warning("startup.studio_source_cache_failed", error=str(e))


# Static mount for the bundled Studio asset libraries (Week 6 followup):
# background loops + default B-roll quick-picks. These ship in the repo as
# small procedural mp4s + jpg posters under ``src/assets/`` so the catalog
# panels work out of the box on a fresh clone — no R2 bucket, no API keys.
# The render job also reads these locally (see ``background_catalog.get_local_path``)
# so an in-process render doesn't even hit the static endpoint.
try:
    from fastapi.staticfiles import StaticFiles  # noqa: F811  reuse import

    _STUDIO_ASSETS_DIR = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "assets")
    )
    if os.path.isdir(_STUDIO_ASSETS_DIR):
        app.mount(
            "/studio/assets",
            StaticFiles(directory=_STUDIO_ASSETS_DIR),
            name="studio_bundled_assets",
        )
        logger.info(
            "startup.studio_assets_mounted",
            path=_STUDIO_ASSETS_DIR,
        )
    else:
        logger.warning(
            "startup.studio_assets_missing",
            path=_STUDIO_ASSETS_DIR,
            hint="run scripts/synth_background_loops.py and scripts/synth_default_broll.py",
        )
except Exception as e:
    logger.warning("startup.studio_assets_failed", error=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
