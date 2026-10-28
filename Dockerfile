# ViewMagnet Backend Dockerfile
# Multi-stage build for smaller production image

# ============================================================
# Stage 1: Builder
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ============================================================
# Stage 2: Production
# ============================================================
FROM python:3.11-slim AS production

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Bake the MiniLM embedding model into the image. The scheduler's topic_clusters
# job is the only one that embeds (SentenceTransformer all-MiniLM-L6-v2); without
# this it downloads the weights from HuggingFace at runtime, and Railway's
# ephemeral filesystem wipes that cache on every redeploy. A failed/rate-limited
# re-download then silently kills the job (observed: clusters froze after a
# redeploy while non-embedding jobs kept running). Shipping the model in the
# image removes the runtime HF dependency entirely; the cache survives restarts.
ENV SENTENCE_TRANSFORMERS_HOME=/opt/models \
    HF_HOME=/opt/models
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" \
    && chmod -R a+rX /opt/models

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

# Copy application code
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser alembic/ ./alembic/
COPY --chown=appuser:appuser alembic.ini ./alembic.ini
# Plan 8.9: artifact fetcher runs at startup (entrypoint) to pull models from R2.
COPY --chown=appuser:appuser scripts/fetch_ml_artifacts.py ./scripts/fetch_ml_artifacts.py

# Create directories for data and models
RUN mkdir -p /app/data/models /app/models /app/temp && \
    chown -R appuser:appuser /app

# Entrypoint script (runs alembic upgrade head when RUN_MIGRATIONS=true)
COPY --chown=appuser:appuser scripts/docker_entrypoint.sh /usr/local/bin/docker_entrypoint.sh
RUN chmod +x /usr/local/bin/docker_entrypoint.sh

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    RUN_MIGRATIONS=true

# Expose port
EXPOSE 8000

# Health check (uses /livez so DB outages don't restart the container)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/livez')" || exit 1

ENTRYPOINT ["/usr/local/bin/docker_entrypoint.sh"]
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
