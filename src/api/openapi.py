"""OpenAPI schema customization for the public API reference at /docs.

The auto-generated OpenAPI document from FastAPI is correct but bare:
no top-level prose, no security scheme docs, no tag descriptions, no
hosted-server list. Scalar (the renderer that powers
``viewmagnet.io/docs``) shows all of these prominently, so investing
in them here pays off as the difference between "looks like a json
dump" and "looks like Stripe docs".

We keep this module separate from ``main.py`` because the
metadata is long-form Markdown that's painful to scroll past when
you're really just trying to read the app factory wiring.

Anything in this file is **public-facing copy** — write it for an
external developer, not for an internal teammate.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from src.config import Settings

# Surfaced verbatim in the docs hero. Bumping this should track the
# user-visible release notes on /changelog, not internal patches.
API_VERSION = "1.0.0"


# Markdown rendered above the endpoint list. Scalar parses this as
# CommonMark, so the headings, lists, and inline code below all
# render natively. Keep paragraphs short — Scalar's intro panel is
# narrow.
API_DESCRIPTION = """\
The **ViewMagnet REST API** powers everything you see in the dashboard,
the [MCP server](https://viewmagnet.io/mcp), and your own scripts. Use it
to analyze YouTube videos, generate viral scripts, score hooks, detect
clip-worthy moments, and pull post-publish outcomes.

## Most users should start with the MCP server

If you use **Claude Desktop**, **Cursor**, or **Cline**, install the
[ViewMagnet MCP server](https://viewmagnet.io/mcp) in one command:

```bash
npx viewmagnet-mcp install
```

Your agent will get 10 tools wired to these endpoints automatically.
You only need to read this reference if you're building your own
integration.

## Authentication

Every endpoint that isn't explicitly public accepts a Bearer token:

```http
Authorization: Bearer vm_pat_<your-token>
```

Two token formats are supported:

| Format | Where to get it | Use it for |
| --- | --- | --- |
| **Personal Access Token** — `vm_pat_<prefix>_<secret>` | [Dashboard → API Tokens](https://viewmagnet.io/dashboard/api-tokens) | Scripts, MCP server, CI |
| **Session JWT** — opaque string | `POST /auth/login` | First-party browser sessions |

PATs are revocable, scope-limited, and optionally hard-expire — prefer
them over JWTs for anything that isn't a logged-in browser session.

## Conventions

- **All errors** return the envelope `{"error": {"code", "message", "request_id", "details"}}`. The HTTP status carries the broad class (`400`, `401`, `402`, `404`, `422`, `429`); `code` carries the specific reason.
- **Rate limits** are tier-based and surface as `429` with a `Retry-After` header. Defaults: 60/min reads, 30/min writes, 5/min LLM-heavy.
- **Render-budget headers** (`X-Render-Budget-Remaining-Minutes`, `X-Render-Softcap`, `X-Render-Queue-Surge`) accompany every Studio render enqueue.

## Need help?

- Email [hello@viewmagnet.app](mailto:hello@viewmagnet.app)
- Read the [API tokens guide](https://viewmagnet.io/dashboard/api-tokens)
- Browse the [methodology](https://viewmagnet.io/methodology) if you want to know what the prediction numbers mean before you call `/analyze`.
"""


# Order matters — Scalar renders the sidebar in the order tags
# appear here. We group by user journey (auth → discovery → write →
# analyze → distribute → admin) rather than alphabetically so a
# first-time reader naturally walks down the page from "log in" to
# "schedule a post".
OPENAPI_TAGS: list[dict[str, str]] = [
    {
        "name": "Authentication",
        "description": (
            "Signup, login, refresh, password reset, and email "
            "verification. Returns short-lived access tokens + "
            "long-lived refresh tokens."
        ),
    },
    {
        "name": "API Tokens",
        "description": (
            "Personal Access Tokens for the MCP server, CI scripts, and "
            "third-party integrations. Tokens are revocable, scope-limited "
            "(`read` / `write` / `admin`), and optionally hard-expire."
        ),
    },
    {
        "name": "Billing",
        "description": (
            "Subscription billing via Stripe — start a checkout for a paid "
            "plan (Starter / Pro / Agency), open the Customer Portal to "
            "manage or cancel, and read current subscription status. Plans "
            "map to the analysis / render / LLM limits enforced across the API."
        ),
    },
    {
        "name": "analyze",
        "description": (
            "Predict whether a YouTube URL will perform well — 0-100 score, "
            "tier, niche comparison, and the Start / Keep / Repeat bottleneck "
            "with rewrite hints. The single most-called endpoint."
        ),
    },
    {
        "name": "scripts",
        "description": (
            "Discover the 4 viral script frameworks and generate full "
            "framework-based scripts from a topic + duration target."
        ),
    },
    {
        "name": "hooks",
        "description": (
            "Score a hook on belief challenge / mistake callout / urgency / "
            "specificity. Discover the 6 hook archetypes. Rewrite weak hooks."
        ),
    },
    {
        "name": "titles",
        "description": (
            "CTR-focused title scoring with per-feature breakdown, plus "
            "generation of N optimized variations for a topic + niche."
        ),
    },
    {
        "name": "thumbnails",
        "description": "AI thumbnail generation and template scoring.",
    },
    {
        "name": "shorts",
        "description": (
            "Find clip-worthy moments inside a long-form video, ranked by "
            "virality, with timestamps and suggested clip titles."
        ),
    },
    {
        "name": "pacing",
        "description": "Pacing grade + concrete cut recommendations.",
    },
    {
        "name": "studio",
        "description": "Studio editor backend — render jobs, status, cancel.",
    },
    {
        "name": "studio-projects",
        "description": "Multi-clip long-form projects (timeline, transitions, brand kit).",
    },
    {
        "name": "distribution",
        "description": (
            "Distribution Hub — schedule and publish renders to YouTube, "
            "TikTok, Instagram Reels, X/Twitter. Pull post-publish outcomes "
            "+ per-recommendation effectiveness rollups."
        ),
    },
    {
        "name": "channel",
        "description": "Channel discovery, benchmarking, and history.",
    },
    {
        "name": "analytics",
        "description": "Performance analytics surfaces.",
    },
    {
        "name": "trends",
        "description": "Cross-niche trend detection and timing windows.",
    },
    {
        "name": "competitors",
        "description": "Competitor channel analysis.",
    },
    {
        "name": "keywords",
        "description": "Keyword research and intent matching.",
    },
    {
        "name": "captions",
        "description": "Animated caption generation for Shorts and Reels.",
    },
    {
        "name": "voiceover",
        "description": "AI voiceover generation.",
    },
    {
        "name": "faceless",
        "description": "Faceless video generator — script → voiceover + B-roll + captions → rendered MP4.",
    },
    {
        "name": "dubbing",
        "description": "Multi-language voice dubbing.",
    },
    {
        "name": "broll",
        "description": "B-roll search (Pexels, Giphy) + image promotion.",
    },
    {
        "name": "loop",
        "description": "Background loop / satisfying-clip library.",
    },
    {
        "name": "effects",
        "description": "Visual effects (zoom, transitions, overlays).",
    },
    {
        "name": "descriptions",
        "description": "Video description generation and SEO scoring.",
    },
    {
        "name": "social",
        "description": (
            "**Deprecated** — use `/distribution/*` for all new publish workflows. "
            "These low-level file-path endpoints are kept for internal shorts-clip "
            "use only and will be removed in a future version."
        ),
    },
    {
        "name": "winning-formula",
        "description": "The 'what worked on your channel' pattern miner.",
    },
    {
        "name": "ab-test",
        "description": "A/B test result tracking.",
    },
    {
        "name": "alerts",
        "description": "Smart alerts (anomalies, milestones, opportunities).",
    },
    {
        "name": "benchmarks",
        "description": "Niche and channel-tier benchmarks.",
    },
    {
        "name": "velocity",
        "description": "View velocity tracker (Day 1 / 7 / 30 projections).",
    },
    {
        "name": "impact",
        "description": "Cumulative impact dashboard.",
    },
    {
        "name": "usage",
        "description": "Per-user usage and quota state (render minutes, etc.).",
    },
    {
        "name": "ai-writer",
        "description": "General-purpose LLM helpers.",
    },
    {
        "name": "analyses",
        "description": "Historical analyses and saved video records.",
    },
    {
        "name": "breakouts",
        "description": "Breakout Radar — what's breaking out across the tracked "
                       "YouTube ecosystem right now (calibrated P(breakout), topic "
                       "saturation, niche-conditioned confidence). The live wedge.",
    },
    {
        "name": "watchlist",
        "description": "Competitive Watchlist — track any public channel and get "
                       "breakouts detected on it (with a sustain-vs-flash durability "
                       "badge). The wedge Studio can't match: it's your-channel-only.",
    },
    {
        "name": "my-channel",
        "description": "Connect Your Own Channel — the validated detector + durability "
                       "grader on your own uploads, with a durability-driven sequel "
                       "recommendation, plus your real owner-side CTR + retention "
                       "(YouTube Analytics). We detect and coach; we don't predict.",
    },
    {
        "name": "formats",
        "description": "Format Radar — title/packaging formats mined from live "
                       "breakouts, ranked by momentum and openness so creators "
                       "catch a pattern while it's still rising and uncrowded.",
    },
    {
        "name": "comment-intelligence",
        "description": "LLM insights from a tracked video's captured comments: "
                       "viewer questions, next-video ideas, FAQ, sentiment.",
    },
    {
        "name": "candidate-ranker",
        "description": "Rank 2-4 title(+thumbnail) candidates for one video: "
                       "reach-model scores + the packaging rubric per title, "
                       "blended into a winner with explanations.",
    },
    {
        "name": "hook-analyzer",
        "description": "Score a clip's opening seconds: measured visual energy "
                       "(motion/cuts/brightness) + LLM hook rubric with the "
                       "highest-impact fix and rewritten openings.",
    },
    {
        "name": "websub",
        "description": "YouTube WebSub (PubSubHubbub) callback: hub verification "
                       "+ push upload notifications that enroll videos for "
                       "velocity tracking with zero API quota.",
    },
    {
        "name": "youtube-oauth",
        "description": (
            "Connect a YouTube channel via OAuth so ViewMagnet can pull "
            "private analytics for the post-publish loop."
        ),
    },
    {
        "name": "tiktok-oauth",
        "description": (
            "One-click TikTok Login Kit OAuth — connect a TikTok account "
            "so ViewMagnet can publish and pull post metrics. "
            "Requires TIKTOK_CLIENT_KEY + TIKTOK_CLIENT_SECRET env vars."
        ),
    },
    {
        "name": "instagram-oauth",
        "description": (
            "One-click Instagram Business Login OAuth (via Meta) — connect "
            "an Instagram Business account for publishing and metric polling. "
            "Requires INSTAGRAM_APP_ID + INSTAGRAM_APP_SECRET env vars."
        ),
    },
    {
        "name": "system",
        "description": "Health checks and system status.",
    },
    {
        "name": "admin",
        "description": "Operator-only admin endpoints (DLQ, queue, telemetry).",
    },
    {
        "name": "admin-management",
        "description": "Admin dashboard — user, analysis, render, and project management.",
    },
    # NB: ``renders-ws`` is a WebSocket-only router. FastAPI doesn't
    # emit WebSocket endpoints in the OpenAPI document (the spec
    # doesn't support them), so declaring the tag here would render
    # an empty sidebar section. The WebSocket protocol is documented
    # in prose under the ``/mcp`` and Docs pages instead.
]


def build_openapi_servers(settings: Settings) -> list[dict[str, str]]:
    """List of `servers:` entries surfaced in the docs page.

    Scalar uses these to populate its "Try it out" base-URL dropdown.
    Order is meaningful: the first entry is the default the
    request-builder lands on, so we put production first in prod
    builds and the local server first in dev.
    """
    prod = {
        "url": "https://api.viewmagnet.com",
        "description": "Production",
    }
    local = {
        "url": "http://localhost:8000",
        "description": "Local development",
    }
    if settings.is_production:
        return [prod, local]
    return [local, prod]


# Tag used to mark schemas that this module synthesized (vs. ones
# that came straight out of a Pydantic ``response_model``). The
# regression test in ``test_openapi.py`` keys on this so we can
# track — and over time, drive down — how many endpoints still
# rely on the fallback.
UNTYPED_RESPONSE_MARKER = "x-viewmagnet-untyped-response"


def _upgrade_untyped_response_schemas(schema: dict[str, Any]) -> None:
    """Replace empty ``{}`` 2xx response schemas with a generic
    object schema so Scalar renders ``{}`` instead of ``null``.

    Background: many ViewMagnet endpoints predate the
    "every-endpoint-needs-a-Pydantic-response-model" rule and just
    do ``return {"foo": ...}``. FastAPI emits an empty schema for
    those — technically correct ("we don't know the shape") but
    Scalar's example generator interprets the empty schema as
    "this endpoint returns ``null``" and the docs page reads like
    half the API is broken.

    Until each endpoint grows a real ``response_model=``, this
    upgrade keeps the rendered docs honest: every untyped response
    advertises itself as a generic JSON object and the example
    body renders as ``{}``. The synthesized schema is tagged with
    :data:`UNTYPED_RESPONSE_MARKER` so we can audit how many
    endpoints still need the proper fix.

    Mutates ``schema`` in place; safe to call multiple times
    (idempotent on already-upgraded responses).
    """
    paths = schema.get("paths", {})
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for verb, op in path_item.items():
            if verb not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(op, dict):
                continue
            for code, response in op.get("responses", {}).items():
                if not code.startswith("2"):
                    continue
                content = response.get("content")
                if not isinstance(content, dict):
                    continue
                for media in content.values():
                    current = media.get("schema")
                    if current == {} or current is None:
                        media["schema"] = {
                            "type": "object",
                            "additionalProperties": True,
                            "description": (
                                "Free-form JSON object. This endpoint "
                                "doesn't ship a formal Pydantic schema "
                                "yet — see the inline `viewmagnet-mcp` "
                                "tool output or the dashboard's network "
                                "tab for the exact field set."
                            ),
                            UNTYPED_RESPONSE_MARKER: True,
                        }


def customize_openapi_schema(app: FastAPI) -> Callable[[], dict[str, Any]]:
    """Return a replacement for ``FastAPI.openapi`` that adds the
    bits FastAPI doesn't generate from decorators alone:

    - ``x-logo`` for Scalar's docs hero
    - ``externalDocs`` pointing at the marketing site
    - ``securitySchemes.PersonalAccessToken`` (FastAPI emits
      ``HTTPBearer`` as "HTTPBearer"; we promote it to a named scheme
      with usage docs)
    - A global ``security`` requirement so every endpoint that isn't
      explicitly public defaults to "needs a Bearer token" in the docs

    The wrapper caches its result so the schema is built once per
    process — same behaviour as the default :meth:`FastAPI.openapi`.
    """
    cached: dict[str, Any] | None = None

    def _openapi() -> dict[str, Any]:
        nonlocal cached
        if cached is not None:
            return cached

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
            servers=app.servers,
            contact=app.contact,
            license_info=app.license_info,
            terms_of_service=app.terms_of_service,
        )

        # x-logo shows in the Scalar hero. Use the absolute URL so
        # the spec is portable (the docs page renders the spec
        # cross-origin in production).
        schema["info"]["x-logo"] = {
            "url": "https://viewmagnet.io/logo.svg",
            "altText": "ViewMagnet",
        }

        # Patch every 2xx response that ended up with an empty
        # ``{}`` schema. See ``_upgrade_untyped_response_schemas``
        # for why — TL;DR Scalar's example generator turns an empty
        # schema into the literal example body ``null`` and the
        # rendered docs page reads as "this endpoint returns
        # nothing" for ~half of the API.
        _upgrade_untyped_response_schemas(schema)

        schema["externalDocs"] = {
            "description": "Product docs, guides, and the MCP server",
            "url": "https://viewmagnet.io/docs",
        }

        # Named security scheme so the docs page renders "Bearer
        # vm_pat_..." in copy with our prose attached, instead of
        # FastAPI's generic "HTTPBearer".
        components = schema.setdefault("components", {})
        schemes = components.setdefault("securitySchemes", {})
        schemes["PersonalAccessToken"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "vm_pat_<prefix>_<secret>",
            "description": (
                "Personal Access Token from "
                "[/dashboard/api-tokens](https://viewmagnet.io/dashboard/api-tokens). "
                "Pass as `Authorization: Bearer vm_pat_...`. "
                "Tokens are revocable, scope-limited, and optionally "
                "hard-expire."
            ),
        }
        schemes["SessionJWT"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "Short-lived session token returned by `POST /auth/login` "
                "and `POST /auth/refresh`. Use for first-party browser "
                "sessions only — prefer a PAT for anything else."
            ),
        }

        cached = schema
        return cached

    return _openapi
