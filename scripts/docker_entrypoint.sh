#!/usr/bin/env bash
set -euo pipefail

# Plan 8.9: fetch ML model artifacts from R2 when ML_ARTIFACTS_VERSION is
# pinned and artifacts are absent (the image ships only src/). Best-effort -
# the script always exits 0 so a fetch problem can never block startup.
echo "[entrypoint] Checking ML artifacts..."
python scripts/fetch_ml_artifacts.py || true

# Run Alembic migrations on container start when RUN_MIGRATIONS=true (default).
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "[entrypoint] Running 'alembic upgrade head'..."
    if alembic upgrade head; then
        echo "[entrypoint] Migrations applied."
    else
        echo "[entrypoint] WARNING: alembic upgrade failed; continuing anyway"
    fi
fi

# Role routing from one image. The scheduler service sets RUN_SCHEDULER=true and
# runs the single-instance periodic-jobs process instead of the API. This keeps
# one Dockerfile/image for API + scheduler; only the env var differs (no Railway
# start-command override needed).
if [ "${RUN_SCHEDULER:-false}" = "true" ]; then
    echo "[entrypoint] RUN_SCHEDULER=true -> starting periodic scheduler (python -m src.scheduler)"
    exec python -m src.scheduler
fi

exec "$@"
