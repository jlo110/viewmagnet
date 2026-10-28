# ViewMagnet

ViewMagnet is a full-stack app for YouTube creators. It tracks thousands of channels in near real time to learn which videos break out, then turns that into decisions: score a video or title before you publish, get an alert when an upload starts to take off, and see which topics are rising in a niche. It also includes AI writing tools, a browser-based short-form video editor that renders finished MP4s, and cross-posting to other platforms.

## Features

- **Analyze and predict**: score a YouTube video or title, A/B test titles and thumbnails, and track view velocity over time. Every model is evaluated against a naive baseline with channel-grouped splits.
- **Creator intelligence**: competitor analysis, trend timing, keyword research and niche insights.
- **AI writing tools**: titles, scripts, descriptions, hooks and thumbnails, through an LLM client with provider fallback and per-user budget caps.
- **Studio**: a browser short-form editor with live preview, animated captions, subject tracking (auto-reframe), auto-zoom, B-roll, transitions, templates and a brand kit, rendered server-side with ffmpeg.
- **Short-form pipeline**: find the most clip-worthy moments in a long video and cut them into Shorts.
- **Distribution**: publish to YouTube, TikTok, Instagram and X from one place.
- **MCP server** (`mcp/`): use the analysis and writing tools from Claude Desktop, Cursor, Cline or any MCP client.
- **Chrome extension** (`chrome-extension/`): ViewMagnet scores shown directly on YouTube pages.

## Architecture

| Layer | Stack |
|---|---|
| API | FastAPI, Pydantic, SQLAlchemy (async) + Alembic (`src/api/`, one router per domain in `src/api/routers/`) |
| Business logic | `src/features/` (one module per dashboard tool) |
| ML | XGBoost / scikit-learn predictors, sentence-transformer title embeddings (`src/ml/`) |
| Data collection | YouTube Data API + WebSub push notifications, time-series sampling at fixed windows (`src/tracking/`) |
| Background jobs | Redis + RQ worker (renders, distribution, Shorts); a single-instance APScheduler process for periodic jobs (`src/scheduler.py`) |
| Database | PostgreSQL in production, SQLite for local development |
| Storage | S3-compatible object storage (Cloudflare R2) for renders and model artifacts |
| Video | ffmpeg (with libass for captions), YOLOv8n + MediaPipe for subject tracking, Whisper for transcription |
| Frontend | React, Vite, TypeScript, Tailwind, shadcn/ui, Remotion (`frontend/`) |
| Billing, auth | Stripe, self-hosted JWT auth with optional 2FA |
| Observability | structlog, Sentry, Prometheus, OpenTelemetry |

The API, worker and scheduler run from the same Docker image; the scheduler must run as a single replica (`RUN_SCHEDULER=true`) so periodic jobs fire once. See `docs/ARCHITECTURE.md` for a deeper reference.

## Quick start

### Requirements

- Python 3.11 (TensorFlow and MediaPipe need 3.12 or lower)
- Node 20+ and pnpm
- Redis
- ffmpeg (on macOS, `ffmpeg-full` for caption burn-in)
- At least one YouTube Data API v3 key

### Configure

```bash
cp .env.example .env
```

Fill in `.env`. The minimum for local development is `JWT_SECRET_KEY` and `YOUTUBE_API_KEY_1`. If `DATABASE_URL` is unset in development, the API uses a local SQLite file. Every other key in `.env.example` (LLM providers, Stripe, R2, email, social publishing) is optional and only enables the matching feature. Never commit `.env`.

### Option 1: local dev script (macOS)

```bash
./dev.sh               # API, worker and frontend
./dev.sh --no-worker   # skip the RQ worker; renders run inside the API process
```

`dev.sh` installs missing tools with Homebrew, creates `.venv`, installs Python and frontend dependencies, runs Alembic migrations when `DATABASE_URL` is set, and starts:

- API: http://localhost:8000 (interactive docs at `/docs`)
- Frontend: http://localhost:3000

### Option 2: Docker Compose

```bash
docker compose up --build
```

This starts the API, the RQ worker, the scheduler, Redis and the frontend dev server. Compose does not include a database: set `DATABASE_URL` in `.env` to a PostgreSQL instance you run.

### Option 3: manual

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head                     # when DATABASE_URL is set
uvicorn src.api.main:app --reload        # API
python -m src.queue.client               # worker; without REDIS_URL, jobs run inside the API
cd frontend && pnpm install && pnpm dev  # frontend
```

The data-collection CLI is available with `python -m src.cli --help` (discovery, tracking, quota status).

### Model artifacts

Trained model files (`models/`, `data/models/`) are not in this repository. In deployment, the container fetches a pinned artifact bundle from object storage at startup (`scripts/fetch_ml_artifacts.py`). Without them the rest of the app runs, but the prediction features have no model to serve (`/health` reports `model_loaded`). You can train your own with the scripts in `scripts/` once you have collected data.

## Tests

```bash
# Backend
source .venv/bin/activate
python -m pytest tests/ --ignore=tests/test_ml/test_thumbnail_predictor.py -q
ruff check src/

# Frontend
cd frontend
pnpm check   # TypeScript
pnpm test    # Vitest

# End-to-end (frontend running on :3000)
npx playwright test
```

CI (`.github/workflows/ci.yml`) runs the backend suite against a real PostgreSQL, the ruff gate, the TypeScript check and Vitest on every push.

## Project status

Active personal project, under development. The data collection, analysis, writing tools, Studio and distribution features work end to end; some backend capabilities are not surfaced in the UI yet. The original historical training dataset was lost, so prediction models are being retrained on newly collected time-series data, and published metrics should be read as work in progress. APIs and the database schema may change without notice.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

MIT — see [LICENSE](./LICENSE). The MCP server in `mcp/` carries its own MIT license (`mcp/LICENSE`).
