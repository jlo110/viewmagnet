# ViewMagnet API Documentation

**Canonical URL:** https://viewmagnet.io/docs  
**Last updated:** 2026-05-27

> Interactive Scalar-rendered API reference for 130+ REST endpoints.
> Auth: Personal Access Tokens (PAT). Base URL: https://api.viewmagnet.com

---

## Authentication

All endpoints require a `Authorization: Bearer vm_pat_<prefix>_<secret>` header.

Generate tokens at https://viewmagnet.io/dashboard/api-tokens. Tokens are revocable and scope-limited — grant only the scopes your integration needs.

Available scopes: `analyze`, `scripts`, `hooks`, `titles`, `studio`, `distribution`

---

## Endpoint groups

### Auth & Tokens
- `GET /auth/me` — current user profile
- `GET /auth/tokens` — list PATs
- `POST /auth/tokens` — create PAT
- `DELETE /auth/tokens/{token_id}` — revoke PAT

### Video Analysis
- `POST /analyze/video` — analyze a YouTube URL; returns prediction score, Start / Keep / Repeat bottleneck, and action recommendations
- `GET /analyze/outcomes/{video_id}` — post-publish analytics with velocity and attribution

### Script Writer
- `GET /scripts/frameworks` — list the four viral script frameworks
- `POST /scripts/generate` — generate a full script from topic + framework + goal
- `POST /scripts/generate-framework` — generate a framework-structured script

### Hook Lab
- `GET /hooks/types` — list the six hook types
- `POST /hooks/score` — score a hook against the taxonomy
- `POST /hooks/rewrite` — rewrite a weak hook
- `POST /hooks/preview` — render hook overlay preview (returns image)
- `POST /hooks/apply` — apply hook overlay to video (returns video file)

### Title & A/B Testing
- `POST /titles/score` — score a title for CTR potential
- `POST /titles/generate` — generate multiple title variants
- `POST /titles/ab-test` — create A/B test for titles

### Shorts Detection
- `POST /shorts/detect-highlights` — detect clip-worthy moments in a video
- `POST /shorts/extract-clip` — extract and export a specific clip

### Pacing Analysis
- `POST /pacing/analyze` — identify dead-air segments and cut suggestions

### Captions
- `POST /captions/generate` — transcribe and generate animated caption data
- `POST /captions/export` — export captioned video (returns video file)

### Thumbnails
- `GET /thumbnails/templates` — list thumbnail templates
- `POST /thumbnails/generate` — generate thumbnail variants

### B-Roll
- `GET /broll/search` — search Pexels and Giphy for B-roll clips
- `POST /broll/suggest` — AI-suggest B-roll for a script
- `POST /broll/script` — map B-roll to script sections
- `POST /broll/promote-image` — convert still image to video clip

### Voiceover
- `GET /voiceover/voices` — list available voices
- `POST /voiceover/estimate` — estimate cost for a script
- `POST /voiceover/generate` — generate voiceover audio (returns mp3)

### Video Effects
- `POST /effects/analyze` — analyze a video for auto-zoom, transitions
- `POST /effects/apply` — apply video effects (returns video file)

### Loop Designer
- `POST /loop/analyze` — analyze loop quality
- `POST /loop/generate-endings` — generate loop ending sequences

### Dubbing
- `GET /dubbing/languages` — list supported dub languages
- `POST /dubbing/create` — create a dubbing job
- `POST /dubbing/download/{job_id}` — download dubbed video (returns video file)

### Social Publishing
- `GET /social/accounts` — list connected social accounts
- `POST /social/publish` — publish a clip to social platforms

### Distribution Hub
- `GET /distribution/accounts` — list connected distribution accounts
- `POST /distribution/accounts` — connect a distribution account
- `PUT /distribution/accounts/{account_id}` — update account
- `DELETE /distribution/accounts/{account_id}` — remove account
- `GET /distribution/setup-status` — get platform setup status
- `GET /distribution/jobs` — list distribution jobs
- `GET /distribution/jobs/{job_id}` — get job details
- `POST /distribution/publish` — publish to distribution channels

### Studio Sessions
- `GET /studio/sessions` — list edit sessions
- `POST /studio/sessions` — create session
- `GET /studio/sessions/{key}` — get session
- `PUT /studio/sessions/{key}` — update session
- `DELETE /studio/sessions/{key}` — delete session

---

## OpenAPI spec

Machine-readable OpenAPI 3.1 JSON: https://api.viewmagnet.com/openapi.json

The spec is auto-generated from FastAPI route decorators + Pydantic models and is the source of truth for this docs page (rendered via Scalar).

---

## Rate limits

| Plan | Requests / min | Concurrent renders |
|---|---|---|
| Free | 20 | 1 |
| Creator | 60 | 3 |
| Pro | 200 | 10 |
| API (enterprise) | unlimited | negotiated |

---

## SDKs & integrations

- **MCP server:** `npx viewmagnet-mcp install` — exposes 10 tools in Claude Desktop, Cursor, Cline
- **REST + PAT:** direct HTTP with the `Authorization: Bearer` header
- **OpenAPI → generated client:** point any OpenAPI codegen tool at `https://api.viewmagnet.com/openapi.json`

---

## Related pages

- [MCP server](https://viewmagnet.io/mcp) — one-command install for AI agents
- [Methodology](https://viewmagnet.io/methodology) — how the ML prediction stack works
- [Script Frameworks](https://viewmagnet.io/frameworks) — the four viral script structures
- [Personal Access Tokens](https://viewmagnet.io/dashboard/api-tokens) — generate auth credentials

*Author: ViewMagnet. Cite as: ViewMagnet API Documentation, https://viewmagnet.io/docs*
