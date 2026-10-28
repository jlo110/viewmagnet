# ViewMagnet — Architecture & Models

*The definitive system reference. Current as of 2026-06-12. Living companions:
`src/ml/model_registry.json` (model source of truth), `docs/velocity_eval_report.md` (honest eval),
`docs/research_notes_2026-06.md` (literature grounding).*

ViewMagnet is a YouTube video-performance intelligence SaaS: it watches thousands of channels in
real time, learns what makes videos break out, and turns that into pre-upload decisions (which
title/thumbnail wins), post-upload alerts (your video is breaking out — act), and niche
intelligence (what's rising right now). The differentiator is **honesty**: every model ships with
a leakage-free, baseline-compared metric, and anything that can't beat a naive baseline doesn't
ship.

---

## 1. Services & deployment

Three services built from this repo on a container host, one Postgres (managed PG
on the host's private network — migrated off Supabase 2026-07-03; nightly backup + snapshot archival to
R2 via `src/tools/db_backup.py`), one object store (Cloudflare R2), Redis for queues/cache:

| Service | Source | Role |
|---|---|---|
| **api** | root `Dockerfile`, role-routed by env | FastAPI app — 46+ routers, auth, billing, all product endpoints, WebSub callback |
| **scheduler** | same image, `RUN_SCHEDULER=true` | Single-process APScheduler — all periodic jobs (exactly-once; never run jobs in the multi-worker API) |
| **frontend** | `frontend/Dockerfile` | React SPA + Express, served via nginx |

**CD (verified end-to-end):** push to `main` → GitHub Actions gates (≈1,080 backend tests on a
real Postgres, ruff E9/F, vitest, tsc) → `deploy-scheduler` job ships the scheduler via
the host's CLI (deploy token) → the host releases the API/frontend deploys once CI passes. E2E (Playwright) runs advisory. The full suite (~18 min) is the deploy-latency floor;
rapid pushes stack native deploys in WAITING — batch doc commits.

**Model artifact delivery (8.9):** the image ships only `src/`. At container start,
`docker_entrypoint.sh` → `scripts/fetch_ml_artifacts.py` pulls the pinned backup tarball
(`ml-artifact-backups/$ML_ARTIFACTS_VERSION/…`, ~69MB) from R2 and extracts `models/` +
`data/models/` if absent. **Backup and deployment are the same artifact** — promotion = bump the
pin. `scripts/backup_ml_artifacts.py` produces it. Prod `/health` reports `model_loaded`.

---

## 2. Collection system (the moat)

The historical training data was lost; everything below
exists to rebuild and exceed it. **Collection is wall-clock data — it can never be backfilled.**
A competitor starting today waits 30+ days for their first complete trajectory.

### Discovery: WebSub push (primary) + polling (reconciliation)
- **WebSub**: YouTube's hub POSTs Atom notifications to `POST /websub/youtube` when a tracked
  channel uploads — **~30s detection latency, zero API quota**. HMAC-signed (`WEBSUB_SECRET`),
  topic-validated, enrolls ≤3-day-old videos from active tracked channels. Leases (~9.6 days)
  renew via the `websub_renew` job. *Gotcha: subscription rows must be committed before
  contacting the hub — its verification GET arrives within ~1s.*
- **Polling**: `playlistItems.list` sweep every 6h (cap 20k channels) as the safety net for
  missed pushes. This was hourly and consumed a measured **99.5% of all quota** before the
  cutover.

### Tracked set
~7,700 channels (`tracked_channels`): the original 4.8k seed (aligned with the lost 144k-video
distribution) + chart-sweep expansion (`scripts/expand_tracked_channels.py` — mostPopular per
region×category, 1 unit/call, niche-labeled `source='chart:<cat>'`). Target 15–20k (plan 8.11).
The 144k-cache seed source is exhausted.

### Checkpoint sampling (the core time-series)
`src/tracking/video_tracker.py` samples each tracked video at **windows** — `1h, 6h, 24h, 3d,
7d, 14d, 30d`, each `[target, target+grace]`. A late sample is **never** backfilled under an
earlier label (the bug that corrupted the original dataset); expired windows resolve as honest
gaps. Verified integrity: **99.99% window hit-rate** across all closed windows.

### Capture streams (scheduler jobs, 12 total)
| Job | Cadence | What it captures |
|---|---|---|
| `velocity_collect_snapshots` | 30 min | views/likes/comments + engagement ratios + **per-checkpoint metadata** (title, thumbnail URL, description, tags, duration, category, `is_short`, live flag, audio language) → title/thumbnail-swap natural experiments |
| `velocity_discover_new_videos` | 6h | polling reconciliation (see above) |
| `websub_renew` | 6h | push-subscription enrollment + lease renewal (batch 2,500) |
| `channel_snapshots` | daily | per-channel subs/views/upload counts (growth denominators) |
| `thumbnail_archive` | hourly | thumbnail **bytes** → R2 (URLs rotate; content-addressed keys auto-capture swaps) |
| `top_comments` | 2h | top ~20 comments at 24h (viewer-intent signal) |
| `heatmap_capture` | 6h | **Most-Replayed heatmaps** (public retention-shape proxy; present from ~13d of age) **+ opening ~60s transcript** from caption tracks — both zero-quota via yt-dlp |
| `topic_clusters` | 6h | MiniLM title embeddings → greedy cosine clusters = **topic-saturation index** (zero quota) |
| `collect_due_metrics` | hourly | published-video outcome metrics (publish loop) |
| `quota_persist` | 5 min | durable quota accounting + low-quota alerts |
| `collection_health` | daily | window hit-rate + view-decrease anomaly monitoring |
| `model_drift_check` | daily | live backtest vs stored reference; warns at +15%, alerts at +30% |

### Quota architecture
22 API keys (~220k units/day — do **not** add more: ToS risk and unnecessary post-WebSub;
steady-state burn ≈ 30–40k/day). All YouTube access goes through `YouTubeClient` (rotation,
retries, accounting) — *raw `client._youtube` access bypasses rotation and 403s forever after one
key exhausts.* Usage persists to `youtube_quota_usage` (per date/key/operation; restart-proof);
`GET /admin/quota` + `quota.alert` logs answer "are we running out?". Discovery skips runs when
remaining < `YOUTUBE_QUOTA_DISCOVERY_RESERVE` (20k) to protect capture jobs.

---

## 3. Data model (key tables)

| Table | Purpose |
|---|---|
| `tracked_channels` / `tracked_videos` | the watch set + per-video checkpoint flags |
| `video_snapshots` | the time-series: one row per (video, checkpoint) with metrics + metadata snapshot |
| `channel_snapshots` | daily channel time-series |
| `video_comments` | top comments @24h |
| `video_heatmaps` | Most-Replayed points + opening transcript (+ probe bookkeeping) |
| `topic_clusters` | topic-saturation batches (history = topic velocity) |
| `websub_subscriptions` | push-lease state + notification health |
| `youtube_quota_usage` | durable quota ledger |
| `velocity_predictions`, `publish_outcomes`, … | prediction/outcome feedback loop |

R2 buckets hold thumbnail bytes (`thumbnails/<vid>/<sha1(url)>.jpg`) and ML artifact backups.
Local-only irreplaceables (also in R2 backups): `data/cache/exp_features.pkl` (144k feature
cache), `data/reach/` (40k labeled reach dataset), `models/`, `data/models/`.

---

## 4. Models — what exists, what's honest, what's served

Source of truth: `src/ml/model_registry.json` (committed in-repo; every entry carries a
`metric_caveat`). **Evaluation discipline (non-negotiable):** channel-grouped splits
(`GroupKFold` by `channel_id` — random splits leak channel baselines), metrics reported as
**MAPE/AUC + lift over a naive baseline**, never raw R² ("94% accuracy" claims from old docs are
autocorrelation, not skill).

### Live / served
| Model | Task | Honest metric | Notes |
|---|---|---|---|
| **Content classifier** (`clean_predictor.pkl`, XGBoost, 409 feats) | overperform vs own channel, pre-upload | grouped bal-acc **0.690** / AUC 0.814 (the stored 0.746 is random-split inflation) | served by `/analyze`; lean 25-feature variant exists (embeddings add nothing on this target) |
| **Breakout detector** (`breakout_calibrator*.json`) | P(top-25% channel-relative overperformance at 24h) from early signals | grouped-CV AUC **0.9275 @6h**, **0.850 @1h** | deliberately a **single explainable feature** (early views vs channel leave-one-out norm) + isotonic calibration — a full XGBoost adds only +0.01 AUC. Powers `/admin/breakouts` (topic-annotated live feed) |
| **Velocity per-horizon regressors** (`velocity_*.joblib`) | view projection from→to checkpoint | **lose to persistence×growth baseline at every measurable horizon** (lift −14% to −48% despite R² 0.43–0.77 — the autocorrelation trap, live) | legacy; serving continues but **the honest play is the baseline + ranges** until the quantile/trajectory retrain (~Jul 8) clears the lift gate |

### Prototypes (built, not yet user-facing)
| Model | Task | Metric | Status |
|---|---|---|---|
| **Reach predictor** (`reach_predictor.pkl`, XGBoost + frozen CLIP img+txt) | absolute breakout (top-quartile views/sub, age-normalized) from thumbnail+title | grouped-CV AUC **0.615** vs 0.51 chance for hand-crafted features (thumbnails/titles ARE the signal for *absolute* reach — the channel-relative target masks it) | served inside the **candidate ranker**; end-to-end CLIP fine-tune ready (`scripts/finetune_reach_clip.py` + 40k dataset) — biggest dormant accuracy win, needs a GPU run |

### Key modeling findings (learned the hard way, don't relearn)
1. **Early trajectory ≫ content features** for post-upload prediction (matches the literature):
   the same data that loses at point-view prediction wins decisively as breakout classification.
2. **Label construction decides everything**: channel-relative targets hide thumbnail signal;
   absolute reach reveals it. Age-normalize labels.
3. **Frozen generic embeddings into trees hurt** (tested: −accuracy); proper CLIP helps only on
   the right target; fine-tuning is the lever.
4. **Inference must mirror training byte-for-byte** — e.g. CLIP `image_embeds` (normalized) vs
   `get_image_features` (not) silently shifts distributions.
5. macOS only: torch+xgboost co-load deadlocks (OpenMP) — test in subprocesses with
   `KMP_DUPLICATE_LIB_OK=TRUE`; Linux prod is unaffected.

### The retrain plan (data-gated, ~Jul 8 when 30d trajectories mature)
One **horizon-conditioned quantile model** (P10/50/90 + split-conformal) replaces the 21
regressors — absorbing the no-clipping fix and calibrated-uncertainty goals in one move. HIP/
self-exciting variants enter the A/B (their fitted params — inherent virality vs promotion
sensitivity — are themselves product). YouNiverse (133k channels of weekly series,
`data/youniverse/`) pretrains the curve priors. Per-niche models follow at ~50–100k pairs/family
(plan 8.10). Gate for everything: **lift > 0 over the persistence baseline under grouped CV** via
`scripts/evaluate_models.py --compare-splits`.

---

## 5. Product surface (selected)

**Intelligence (built on the collection):**
- `GET /admin/breakouts` — live breakout feed across the tracked set (calibrated P, sanity-gated,
  each item annotated with its topic's saturation)
- `GET /admin/topics` + `/admin/topics/velocity` — what's saturated vs rising right now
- `GET /comment-intelligence/{video_id}` — LLM digest of captured comments

**Pre-upload decisions:**
- `POST /rank/candidates` — **the candidate ranker**: 2–4 titles(+thumbnails) → reach scores +
  packaging rubric + blended winner (plan 6.4's generate→score→rank loop, v1)
- `POST /titles/packaging-score` — MrBeast-principles rubric (<50-char rule, curiosity gap…)
- `POST /hook/analyze` — first-8s hook report: measured visual energy (motion/cuts/brightness)
  fed into an LLM rubric → score + highest-impact fix + rewritten openings
- `/analyze` — the classic overperform score

**Ops:** `/health` (incl. model presence via registry), `/admin/quota`,
`/admin/collection-health` (hit-rate + anomaly monitor), `/admin/telemetry/*` (render funnel).

**LLM layer** (`src/features/llm_client.py`): Anthropic → Synthetic → Groq fallback with budget
caps + prompt caching. *Current reality: Anthropic credits exhausted and Synthetic unsubscribed →
all LLM features run on Groq llama-3.3-70b; the Anthropic top-up is the single quality lever.*

---

## 6. Invariants (the list that keeps the system honest)

1. **Never backfill a late sample under an earlier checkpoint label.**
2. **Channel-grouped CV always**; report lift over baseline, never raw R²/accuracy.
3. **Capture now or lose it forever** — wall-clock data drives every "widen capture" decision.
4. All YouTube access via `YouTubeClient`; quota is accounted durably.
5. Models ship with a `metric_caveat`; the registry is committed (a blanket `*.json` gitignore
   once silently excluded it — CI red for days).
6. Jobs never raise (log + retry next tick); observability jobs never gate collection.
7. Tests green before commit; CI gates deploys; the scheduler deploys from CI, not laptops.
8. Secrets in env/platform stores. (*Outstanding: rotation + git-history purge of the old `.env`.*)
