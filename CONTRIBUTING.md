# Contributing

## Lockfiles

- **`requirements.txt`** is the source of truth for backend Python deps.
- **`frontend/pnpm-lock.yaml`** is committed to ensure reproducible installs in CI and Docker.
  - Use `pnpm install` (not `npm install` or `yarn`) to add/update frontend deps.
  - If the lockfile is missing, run `pnpm install` to regenerate it before running the dev server.

## Local development

```bash
# Backend
cp .env.example .env   # set JWT_SECRET_KEY and YOUTUBE_API_KEY_1
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.api.main:app --reload

# Frontend
cd frontend
pnpm install
pnpm dev
```

## Background workers

Distribution and shorts pipelines run via RQ when `REDIS_URL` is set. Start a worker:

```bash
REDIS_URL=redis://localhost:6379/0 python -m src.queue.client
```

Without `REDIS_URL`, jobs run synchronously in the API process (fine for dev, not safe for prod).

## Migrations

```bash
alembic upgrade head            # apply pending migrations
alembic revision -m "your msg"  # create a new migration
```

Production containers run `alembic upgrade head` automatically when `RUN_MIGRATIONS=true` (default).

## Tests

```bash
pytest                           # full suite
pytest tests/test_features/      # feature unit tests
pytest --cov=src                 # with coverage
```
