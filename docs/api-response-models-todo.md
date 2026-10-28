# API response-model backlog

Status as of this commit: **106 typed / 37 untyped (74.1 % coverage)**.

The remaining endpoints below still return ad-hoc dictionaries, so their
Scalar (`/docs`) example response renders as `{"additionalProperty":
"anything"}` instead of a real shape. Each one needs a Pydantic
`response_model` for the docs to show a meaningful example.

Tests guarding the work:

- `tests/test_api/test_openapi.py::test_no_empty_2xx_response_schemas` —
  fails if any 2xx response has a literally-empty schema (`{}`).
- `tests/test_api/test_openapi.py::test_untyped_response_count_is_tracked` —
  passes a ceiling on untyped endpoints. **Tighten the ceiling each time
  you knock one out** so the count can only go down.
- `tests/test_api/test_openapi.py::test_openapi_tag_declarations_match_endpoint_usage` —
  guards against tag-name typos / unused tags.

When all 37 are done, set the ceiling to `0` and the test becomes a
permanent regression guard.

---

## Pattern to follow

For every endpoint:

1. Open the router file and find the `return { ... }` (or
   `return some_helper(...)` that yields a dict).
2. Declare a `BaseModel` next to the existing request models (or in a
   sibling `# --- Response models ---` block — see
   `src/api/routers/ai_writer.py` for a clean template).
3. Add `response_model=YourModel` to the route decorator and an
   `-> YourModel` return annotation on the function.
4. Wrap the dict in `YourModel(**dict)` (or build it field-by-field if
   the dict has aliases) so FastAPI does a real validation pass.
5. Add a one-line `description` to each field — Scalar shows these in
   the right pane, and the MCP server reuses them as `outputSchema`
   docs.

For endpoints that return binary content (images / video / audio), do
**not** add a JSON `response_model`. Instead use the pattern from
`src/api/routers/hooks.py::_BINARY_FILE_RESPONSES`:

```python
@router.post(
    "/foo/binary",
    response_class=FileResponse,
    responses={200: {"content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}}}},
)
```

---

## Remaining endpoints by router

### `src/api/routers/auth.py` — Authentication (6)

| Endpoint                       | Current return                              | Suggested model              |
|--------------------------------|---------------------------------------------|------------------------------|
| `POST /auth/logout`            | `{"success": True, "message": "..."}`       | `LogoutResponse`             |
| `POST /auth/verify-email`      | `{"success": True, "user": {...}}`          | `VerifyEmailResponse`        |
| `POST /auth/resend-verification` | `{"success": True, "message": "..."}`     | `ResendVerificationResponse` |
| `POST /auth/2fa/enable`        | `{"secret": "...", "qr_code": "...", "backup_codes": [...]}` | `TwoFactorEnableResponse` |
| `POST /auth/2fa/disable`       | `{"success": True}`                         | `TwoFactorDisableResponse`   |
| `GET /auth/referral-code`      | `{"referral_code": "...", "referral_url": "..."}` | `ReferralCodeResponse` |

Notes: `/auth/login`, `/auth/register`, `/auth/me`, `/auth/refresh` are
already typed — copy that style. Reuse the `UserResponse` model in
`src/api/schemas/auth.py` for any endpoint that returns a user.

### `src/api/routers/youtube_oauth.py` — youtube-oauth (3)

| Endpoint                          | Current return                                                  | Suggested model               |
|-----------------------------------|-----------------------------------------------------------------|-------------------------------|
| `GET /auth/youtube/callback`      | Usually a `RedirectResponse` — confirm before adding a JSON model. | `response_class=RedirectResponse` (no JSON model) |
| `GET /auth/youtube/disconnect`    | `{"success": True, "message": "..."}`                           | `YouTubeDisconnectResponse`   |
| `GET /auth/youtube/connections`   | `{"connections": [{"channel_id": "...", "channel_name": "...", "connected_at": "..."}]}` | `YouTubeConnectionsResponse` |

### `src/api/routers/system.py` (or root in `main.py`) — system (2)

| Endpoint     | Current return                                | Suggested model        |
|--------------|-----------------------------------------------|------------------------|
| `GET /`      | `{"service": "...", "version": "...", "status": "ok", "docs": "..."}` | `ServiceInfoResponse` |
| `GET /health` | `{"status": "ok", "checks": {...}}`          | `HealthCheckResponse`  |

Note: `/health` is hit by load balancers — keep the response shape stable.

### `src/api/routers/analytics.py` — analytics (4)

| Endpoint                              | Suggested model               |
|---------------------------------------|-------------------------------|
| `GET /analytics/channel`              | `ChannelAnalyticsResponse`    |
| `GET /analytics/video/{video_id}`     | `VideoAnalyticsResponse`      |
| `GET /niche/{category}/insights`      | `NicheInsightsResponse`       |
| `GET /niche/categories`               | `NicheCategoryListResponse`   |

Inspect the underlying `NicheAnalyzer` / `AnalyticsService` return shapes
before declaring fields — these are LLM-summarized so the shape is
documented in `src/features/`.

### `src/api/routers/channel.py` — channel (1)

| Endpoint                | Suggested model           |
|-------------------------|---------------------------|
| `GET /channel/overview` | `ChannelOverviewResponse` |

### `src/api/routers/analyses.py` — analyses (4)

| Endpoint                                     | Suggested model            |
|----------------------------------------------|----------------------------|
| `GET /dashboard/stats`                       | `DashboardStatsResponse`   |
| `GET /analyses/history`                      | `AnalysesHistoryResponse`  |
| `GET /analyses/{video_id}`                   | `AnalysisDetailResponse`   |
| `GET /analyses/video-count/{video_id}`       | `VideoAnalysisCountResponse` |

`/dashboard/stats` is high-traffic (every dashboard load) — typing this
unlocks a useful Scalar example.

### `src/api/routers/keywords.py` — keywords (1)

| Endpoint                | Suggested model         |
|-------------------------|-------------------------|
| `GET /keywords/research` | `KeywordResearchResponse` |

### `src/api/routers/trends.py` — trends (1)

| Endpoint               | Suggested model       |
|------------------------|-----------------------|
| `GET /trends/analyze`  | `TrendsAnalyzeResponse` |

### `src/api/routers/competitors.py` — competitors (1)

| Endpoint                  | Suggested model           |
|---------------------------|---------------------------|
| `POST /competitors/analyze` | `CompetitorAnalyzeResponse` |

### `src/api/routers/ab_test.py` — ab-test (1)

| Endpoint                 | Suggested model           |
|--------------------------|---------------------------|
| `POST /ab-test/simulate` | `ABTestSimulateResponse`  |

### `src/api/routers/alerts.py` — alerts (3)

| Endpoint                            | Current return                                            | Suggested model            |
|-------------------------------------|-----------------------------------------------------------|----------------------------|
| `POST /alerts/settings`             | `{"status": "updated", "user_id": "...", "settings": {...}}` | `AlertSettingsUpdateResponse` |
| `POST /alerts/{alert_id}/dismiss`   | `{"status": "dismissed", "alert_id": "..."}`              | `AlertDismissResponse`     |
| `GET /alerts/summary`               | `{"total": N, "by_type": {...}, "by_priority": {...}, "high_priority": [{"title", "message"}]}` | `AlertSummaryResponse` |

`GET /alerts` is already typed — copy that style for the missing three.

### `src/api/routers/winning_formula.py` — winning-formula (2)

| Endpoint                                          | Suggested model              |
|---------------------------------------------------|------------------------------|
| `GET /winning-formula/{channel_id}`               | `WinningFormulaResponse`     |
| `GET /winning-formula/{channel_id}/engagement`    | `WinningFormulaEngagementResponse` |

### `src/api/routers/benchmarks.py` — benchmarks (1)

| Endpoint                       | Suggested model         |
|--------------------------------|-------------------------|
| `GET /benchmarks/{category}`   | `BenchmarksResponse`    |

### `src/api/routers/velocity.py` — velocity (5)

| Endpoint                        | Current return                                                                                                          | Suggested model              |
|---------------------------------|-------------------------------------------------------------------------------------------------------------------------|------------------------------|
| `POST /velocity/monitor`        | `{"status": "added\|already_tracked\|error", "channel_id": "...", "added_at": "...", "video_added": {...}}`             | `VelocityMonitorResponse`    |
| `GET /velocity/channels`        | `{"channels": [{"channel_id", "channel_name", "subscriber_count", "videos_tracked", "added_at", "avg_accuracy", "growth_pattern"}]}` | `VelocityChannelsResponse` |
| `GET /velocity/videos`          | `{"videos": [{"video_id", "title", ..., "predictions": {"3d","7d","14d","30d"}, "actuals": {...}, "snapshots": [...]}]}` | `VelocityVideosResponse`     |
| `GET /velocity/video/{video_id}` | Per-video object with `predictions`, `actuals`, `accuracy`, `snapshots`                                                | `VideoVelocityResponse`      |
| `GET /velocity/accuracy`        | `{"status": "no_completed_videos"}` OR `{"total_complete_videos": N, "24h_to_3d": {"avg": ...}, ...}`                   | `VelocityAccuracyResponse` (use `Union` or discriminator) |

`/velocity/accuracy` has two distinct shapes — model as
`VelocityAccuracyReport | VelocityAccuracyEmpty` and let FastAPI emit
both in `oneOf`.

### `src/api/routers/studio.py` — studio (2)

| Endpoint                                     | Suggested model            |
|----------------------------------------------|----------------------------|
| `GET /studio/sessions/{clip_key}/tracking`   | `StudioSessionTrackingResponse` |
| `GET /studio/source-proxy`                   | This streams video bytes — use `response_class=StreamingResponse` + `responses={200: {"content": {"video/mp4": {...}}}}`, not a JSON model. |

---

## Process per endpoint

```bash
# 1. Run the test suite for the openapi guard
pytest tests/test_api/test_openapi.py -q

# 2. Spec sanity check
curl -s http://localhost:8000/openapi.json | python -c "
import json, sys
s = json.load(sys.stdin)
op = s['paths']['/YOUR/ENDPOINT']['GET']
print(op['responses']['200']['content']['application/json']['schema'])
"

# 3. After each batch, tighten the ceiling in
#    tests/test_api/test_openapi.py::test_untyped_response_count_is_tracked
#    so it can never regress.
```

When the count hits zero, drop the `_upgrade_untyped_response_schemas`
fallback in `src/api/openapi.py` — at that point every endpoint will
have a real schema and the safety-net is no longer needed.
