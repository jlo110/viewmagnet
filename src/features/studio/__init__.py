"""Studio editor package — the canonical edit-session spec and render pipeline.

Architecture (Week 1 vertical slice):

    ┌─────────────┐    PUT spec     ┌──────────────┐
    │  Frontend   │ ─────────────▶  │  /studio/    │
    │  (Remotion  │ ◀───────────── │  sessions/   │ ─── DB (EditSession.spec JSON)
    │   Player)   │  GET spec       └──────────────┘
    └─────┬───────┘                       │
          │ POST /studio/render           │
          ▼                               │
    ┌──────────────┐  enqueue_job  ┌──────▼───────┐
    │ Render queue │ ───────────▶  │ render_job() │ ─── ffmpeg + ASS captions
    │  (RQ + sync  │               │              │       ↓
    │   fallback)  │               │              │ R2 upload (mp4)
    └──────────────┘               └──────────────┘       ↓
                                            └──── EditSession.last_render_url

The ``EditSpec`` Pydantic model is the **single source of truth** — the same
JSON that drives the in-browser Remotion preview drives the server-side
render, so what users see is what they get.
"""
from src.features.studio.spec import (
    AspectRatio,
    BRollTrack,
    BrandKit,
    CaptionPosition,
    CaptionStyleName,
    Captions,
    Crop,
    EditSpec,
    SourceClip,
    TranscriptWord,
    Transitions,
)

__all__ = [
    "AspectRatio",
    "BRollTrack",
    "BrandKit",
    "CaptionPosition",
    "CaptionStyleName",
    "Captions",
    "Crop",
    "EditSpec",
    "SourceClip",
    "TranscriptWord",
    "Transitions",
]
