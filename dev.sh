#!/usr/bin/env bash
# ============================================================
# ViewMagnet — local dev starter (no Docker needed)
#
# Usage:  ./dev.sh
# Stop:   Ctrl+C  (kills all child processes cleanly)
#
# Requirements (installed automatically via Homebrew if missing):
#   - python@3.11  (TensorFlow / mediapipe need <=3.12, 3.11 is the safest)
#   - node 20+
#   - pnpm
#   - redis
# ============================================================
set -eo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Flag parsing ───────────────────────────────────────────
# --no-worker     skip starting the RQ worker (saves memory; render
#                 jobs will run synchronously inside the API request
#                 since REDIS_URL is unset OR the worker just isn't
#                 consuming — useful when iterating on non-render code)
# --worker-only   skip API + frontend; only run the worker (useful
#                 for debugging a stuck render in isolation)
SKIP_WORKER=false
ONLY_WORKER=false
for arg in "$@"; do
  case "$arg" in
    --no-worker) SKIP_WORKER=true ;;
    --worker-only) ONLY_WORKER=true ;;
    -h|--help)
      cat <<EOF
Usage: ./dev.sh [--no-worker] [--worker-only]
  --no-worker     Skip the RQ worker (smaller memory footprint).
  --worker-only   Skip API + frontend; only run the worker.
EOF
      exit 0 ;;
  esac
done

# ── Colours ────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${BOLD}[dev]${RESET} $*"; }
ok()   { echo -e "${GREEN}[dev]${RESET} $*"; }
warn() { echo -e "${YELLOW}[dev]${RESET} $*"; }
err()  { echo -e "${RED}[dev]${RESET} $*"; }

# ── Cleanup on exit ────────────────────────────────────────
PIDS=()
cleanup() {
  echo ""
  log "Shutting down…"
  for pid in "${PIDS[@]+"${PIDS[@]}"}"; do
    kill "$pid" 2>/dev/null || true
  done
  if [ "${REDIS_STARTED:-false}" = "true" ]; then
    brew services stop redis 2>/dev/null || true
    ok "Redis stopped."
  fi
  ok "Done."
}
trap cleanup INT TERM EXIT

# ── Load .env ──────────────────────────────────────────────
# Parse line-by-line so $-signs and special chars in values (e.g. DB
# passwords) are NOT expanded by the shell. Lines like `KEY=value` only.
if [ -f "$ROOT/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    key="${line%%=*}"
    val="${line#*=}"
    # strip optional surrounding quotes
    val="${val%\"}"; val="${val#\"}"
    val="${val%\'}"; val="${val#\'}"
    export "$key=$val"
  done < "$ROOT/.env"
  ok ".env loaded"
else
  warn "No .env file found — copy .env.example to .env and fill in values"
fi

# ── Homebrew ───────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  err "Homebrew is required. Install from https://brew.sh and re-run."
  exit 1
fi

# ── Python 3.11 ────────────────────────────────────────────
# TensorFlow (deepface) and mediapipe require Python <=3.12.
# 3.11 has the broadest wheel support across the whole stack.
PY=""
for candidate in /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11 python3.11; do
  if command -v "$candidate" &>/dev/null; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  log "Installing python@3.11 via Homebrew (one-time, ~2 min)…"
  brew install python@3.11
  PY="$(brew --prefix)/opt/python@3.11/bin/python3.11"
fi

PY_VER="$("$PY" --version 2>&1 | awk '{print $2}')"
ok "Using Python $PY_VER at $PY"

# ── ffmpeg ─────────────────────────────────────────────────
# yt-dlp + openai-whisper shell out to ffmpeg/ffprobe to extract audio,
# and the Studio render pipeline needs the ``subtitles``/``ass`` filters
# (libass) to burn animated captions into final MP4s. Stock ``ffmpeg``
# from Homebrew has dropped libass, so we install ``ffmpeg-full`` which
# is keg-only and bundles libass + 40+ other libs.
if [[ -x /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg ]] || [[ -x /usr/local/opt/ffmpeg-full/bin/ffmpeg ]]; then
  log "ffmpeg-full already installed (caption burn-in supported)"
elif ! command -v ffmpeg &>/dev/null || ! command -v ffprobe &>/dev/null; then
  log "Installing ffmpeg-full via Homebrew (one-time, ~2 min, includes libass)…"
  brew install ffmpeg-full || brew install ffmpeg
else
  log "Found stock ffmpeg; installing ffmpeg-full alongside for libass caption burn-in…"
  brew install ffmpeg-full || log "ffmpeg-full install failed; Studio caption rendering will be unavailable"
fi

# ── Redis ──────────────────────────────────────────────────
log "Checking Redis…"
if ! command -v redis-cli &>/dev/null; then
  log "Installing Redis via Homebrew…"
  brew install redis
fi

if redis-cli ping &>/dev/null 2>&1; then
  ok "Redis already running"
else
  log "Starting Redis via Homebrew services…"
  brew services start redis
  REDIS_STARTED=true
  sleep 1
  if redis-cli ping &>/dev/null 2>&1; then
    ok "Redis started"
  else
    err "Redis failed to start — check: brew services info redis"
    exit 1
  fi
fi

# ── Python venv (.venv) ────────────────────────────────────
VENV="$ROOT/.venv"
NEEDS_NEW_VENV=false

if [ ! -d "$VENV" ]; then
  NEEDS_NEW_VENV=true
elif [ -f "$VENV/pyvenv.cfg" ] && ! grep -q "version = 3.11" "$VENV/pyvenv.cfg"; then
  warn "Existing .venv is not Python 3.11 — recreating…"
  rm -rf "$VENV"
  NEEDS_NEW_VENV=true
fi

if [ "$NEEDS_NEW_VENV" = "true" ]; then
  log "Creating Python 3.11 virtual environment at .venv…"
  "$PY" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

log "Installing/syncing Python dependencies (first run: ~5–10 min)…"
# Pin setuptools <82 so it stays compatible with torch's constraint.
pip install -q --upgrade pip "setuptools<82" wheel
if ! pip install -r "$ROOT/requirements.txt"; then
  err "Dependency install failed. Re-run 'pip install -r requirements.txt' inside .venv for details."
  exit 1
fi
ok "Python deps ready"

# ── Database migrations ────────────────────────────────────
if [ -n "${DATABASE_URL:-}" ]; then
  log "Running Alembic migrations…"
  cd "$ROOT"
  if alembic upgrade head; then
    ok "Migrations applied"
  else
    warn "Alembic migration failed — continuing (DB may already be current)"
  fi
else
  warn "DATABASE_URL not set — skipping migrations"
fi

# ── Node / pnpm ────────────────────────────────────────────
if ! command -v node &>/dev/null; then
  log "Installing Node via Homebrew…"
  brew install node
fi
if ! command -v pnpm &>/dev/null; then
  log "Enabling pnpm via corepack…"
  corepack enable
  corepack prepare pnpm@latest --activate
fi

# ── Frontend deps ──────────────────────────────────────────
# Always run pnpm install — it's a no-op when up to date, and picks up
# new packages added to package.json since last run.
log "Syncing frontend dependencies (pnpm install)…"
cd "$ROOT/frontend"
PNPM_PKG_HASH_BEFORE="$(shasum package.json pnpm-lock.yaml 2>/dev/null | shasum | awk '{print $1}')"
pnpm install --prefer-offline
PNPM_PKG_HASH_AFTER="$(shasum package.json pnpm-lock.yaml 2>/dev/null | shasum | awk '{print $1}')"

# Vite caches optimized deps in node_modules/.vite. When packages change,
# the cache can desync with the live React module and cause cryptic
# "Cannot read properties of null (reading 'useContext')" errors. Bust
# the cache whenever the lockfile or package.json moved.
if [ "$PNPM_PKG_HASH_BEFORE" != "$PNPM_PKG_HASH_AFTER" ] || [ -n "${FORCE_VITE_REBUILD:-}" ]; then
  log "Clearing Vite optimized-deps cache (frontend deps changed)…"
  rm -rf node_modules/.vite
fi

# ── Start services in background ───────────────────────────
echo ""
log "${BOLD}Starting all services…${RESET}"
echo ""

if [ "$ONLY_WORKER" = "false" ]; then
  echo -e "${CYAN}▶ API${RESET}      → http://localhost:8000  (docs: http://localhost:8000/docs)"
  cd "$ROOT"
  uvicorn src.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --reload-dir src \
    --log-level info \
    2>&1 | sed "s/^/${CYAN}[api]${RESET} /" &
  PIDS+=($!)
fi

if [ "$SKIP_WORKER" = "false" ]; then
  echo -e "${YELLOW}▶ Worker${RESET}   → processing background jobs (renders, distribution, shorts)"
  cd "$ROOT"
  # OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES — on macOS, RQ's default Worker
  # forks a child process per job and our ML deps (mediapipe / OpenCV / YOLO)
  # pull in Objective-C frameworks that abort the child with SIGABRT 6 unless
  # this flag is set. See: https://github.com/rq/rq/issues/1418
  OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
  python -m src.queue.client \
    2>&1 | sed "s/^/${YELLOW}[worker]${RESET} /" &
  PIDS+=($!)
else
  warn "Skipping worker (--no-worker). Render jobs will run synchronously in the API process."
fi

if [ "$ONLY_WORKER" = "false" ]; then
  echo -e "${GREEN}▶ Frontend${RESET} → http://localhost:3000"
  cd "$ROOT/frontend"
  # package.json's "dev" script already passes --host; just add a port override.
  pnpm dev --port 3000 \
    2>&1 | sed "s/^/${GREEN}[ui]${RESET} /" &
  PIDS+=($!)
fi

echo ""
ok "All services started — press ${BOLD}Ctrl+C${RESET} to stop everything"
echo ""

wait
