"""B-Roll Finder: /broll/search, /broll/suggest, /broll/script."""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
from typing import List, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["broll"])


# ---------------------------------------------------------------------------
# Image → MP4 cache for the "Images" tab in the Studio B-roll panel.
#
# Stock photo APIs (Pexels images) return JPG/PNG URLs. The Studio timeline
# only deals in MP4 B-roll clips, so when the user adds an image we encode
# a short still-video on first use and cache it under ``src/assets/image-cache/``
# (which is already served by the ``/studio/assets`` static mount).
#
# Caching is content-addressed: ``sha1(image_url + ":" + duration)``. Re-adding
# the same image (or two users adding the same Pexels photo) reuses the same
# MP4 instead of re-encoding. The cache grows ~200KB per unique image.
# ---------------------------------------------------------------------------

_IMAGE_CACHE_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "assets", "image-cache",
    )
)
_IMAGE_CACHE_PUBLIC_PREFIX = "/api/studio/assets/image-cache"
_IMAGE_DOWNLOAD_TIMEOUT_S = 20.0
_IMAGE_MAX_BYTES = 20 * 1024 * 1024  # 20 MB — generous; Pexels caps ~5 MB


def _configured_stock_sources(media_type: str = "video") -> List[str]:
    """Which providers actually have API keys wired up for ``media_type``.

    Returned to the frontend on every search response so the UI can show
    an actionable empty state ("Add a TENOR_API_KEY to enable GIF
    search") instead of an unexplained empty grid when the user has no
    providers configured for the type they picked.
    """
    sources: List[str] = []
    if media_type == "video":
        if os.getenv("PEXELS_API_KEY"):
            sources.append("pexels")
        if os.getenv("PIXABAY_API_KEY"):
            sources.append("pixabay")
    elif media_type == "image":
        # Only Pexels image search is wired right now. Pixabay has a
        # photo API too — easy follow-up if we ever need more breadth.
        if os.getenv("PEXELS_API_KEY"):
            sources.append("pexels")
    elif media_type == "gif":
        # Order mirrors the BRollFinder.search_gifs preference: Giphy
        # first (the user already had a key for it), Tenor as fallback.
        if os.getenv("GIPHY_API_KEY"):
            sources.append("giphy")
        if os.getenv("TENOR_API_KEY"):
            sources.append("tenor")
    return sources


class BRollSearchRequest(BaseModel):
    """Request for B-roll search."""
    query: str
    max_results: int = 10
    source: Optional[str] = None  # "pexels", "pixabay", or None for both
    # ``video`` (default) → Pexels/Pixabay clips.
    # ``image`` → Pexels photo library (rendered as a still B-roll on add).
    # ``gif``   → Tenor GIFs (downloaded as MP4 loops).
    media_type: str = "video"


class BRollForTextRequest(BaseModel):
    """Request for finding B-roll based on text content."""
    text: str
    max_clips: int = 5


class ScriptSection(BaseModel):
    """A section of a script."""
    name: str
    content: str
    timestamp: Optional[str] = None


class BRollForScriptRequest(BaseModel):
    """Request for finding B-roll for a full script."""
    sections: List[ScriptSection]
    clips_per_section: int = 3


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class BRollClip(BaseModel):
    """A single B-roll search hit (video, image, or GIF). Fields with
    ``Optional`` are present for most media types but not all — e.g.
    GIFs from Tenor return without an attributable user."""

    id: str = Field(..., description="Provider-stable clip id")
    source: str = Field(..., description="pexels | pixabay | giphy | tenor")
    title: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[float] = Field(default=None, ge=0, description="Clip duration in seconds")
    width: Optional[int] = Field(default=None, ge=0)
    height: Optional[int] = Field(default=None, ge=0)
    preview_url: Optional[str] = Field(default=None, description="Low-bandwidth preview URL")
    download_url: Optional[str] = Field(
        default=None, description="Full-resolution download URL"
    )
    thumbnail_url: Optional[str] = None
    user: Optional[str] = Field(default=None, description="Attribution / creator handle when available")
    quality: Optional[str] = Field(default=None, description="hd | sd | sm")
    media_type: Optional[str] = Field(default=None, description="video | image | gif")


class BRollSearchResponse(BaseModel):
    query: str
    media_type: str
    clips: list[BRollClip]
    total: int = Field(..., ge=0)
    available_sources: list[str] = Field(
        ...,
        description=(
            "Providers with API keys configured for this media type. "
            "An empty list means no provider is enabled — surface as a "
            "configuration-needed empty state, not a 'no results' state."
        ),
    )


class BRollSuggestion(BaseModel):
    """Compact B-roll record returned by /broll/suggest (a subset of
    BRollClip — provider-side suggestion doesn't always include width
    / height / user)."""

    id: str
    source: str
    title: Optional[str] = None
    duration: Optional[float] = None
    preview_url: Optional[str] = None
    download_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    quality: Optional[str] = None


class BRollSuggestResponse(BaseModel):
    text_preview: str = Field(..., description="First ~200 chars of the input text, for confirmation")
    extracted_keywords: list[str]
    visual_cues: list[str] = Field(
        ..., description="Concrete visual phrases extracted from the text (e.g. 'split-screen comparison')"
    )
    clips: list[BRollSuggestion]


class BRollScriptSectionSuggestion(BaseModel):
    section_name: str
    section_preview: str
    keywords: list[str]
    timestamp: Optional[str] = None
    clips: list[BRollSuggestion]


class BRollScriptResponse(BaseModel):
    suggestions: list[BRollScriptSectionSuggestion]


class PromoteImageResponse(BaseModel):
    """Result of /broll/promote-image — image URL → cached MP4 URL."""

    download_url: str = Field(..., description="Public URL to the rendered MP4 loop")
    duration_seconds: float = Field(..., ge=0)
    cached: bool = Field(
        ...,
        description="True when this MP4 was served from the on-disk cache (no encode happened)",
    )


@router.post("/broll/search", response_model=BRollSearchResponse)
@limiter.limit(Tier.READ)
async def search_broll(
    request: Request,
    body: BRollSearchRequest,
    current_user: User = Depends(get_current_user),
) -> BRollSearchResponse:
    """Search for B-roll media — videos, images, or GIFs (auth required).

    Dispatches on ``body.media_type``:
      - ``video`` → Pexels + Pixabay video search (default)
      - ``image`` → Pexels photo library
      - ``gif``   → Tenor (MP4 loops, drop-in compatible with the timeline)
    All branches return the same response shape so the frontend can use
    one renderer / "add to timeline" path regardless of media type.
    """
    media_type = (body.media_type or "video").lower()
    if media_type not in ("video", "image", "gif"):
        raise HTTPException(
            status_code=400,
            detail=f"unsupported media_type {media_type!r}; expected video|image|gif",
        )
    try:
        from src.features.broll_finder import BRollFinder

        finder = BRollFinder()
        if media_type == "image":
            clips = finder.search_images(
                query=body.query,
                max_results=body.max_results,
                source=body.source,
            )
        elif media_type == "gif":
            clips = finder.search_gifs(
                query=body.query,
                max_results=body.max_results,
                source=body.source,
            )
        else:
            clips = finder.search_clips(
                query=body.query,
                max_results=body.max_results,
                source=body.source,
            )

        return BRollSearchResponse(
            query=body.query,
            media_type=media_type,
            clips=[
                BRollClip(
                    id=c.id,
                    source=c.source,
                    title=c.title,
                    description=c.description,
                    duration=c.duration,
                    width=c.width,
                    height=c.height,
                    preview_url=c.preview_url,
                    download_url=c.download_url,
                    thumbnail_url=c.thumbnail_url,
                    user=c.user,
                    quality=c.quality,
                    media_type=c.media_type,
                )
                for c in clips
            ],
            total=len(clips),
            available_sources=_configured_stock_sources(media_type),
        )
    except Exception as e:
        logger.error(f"B-roll search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/broll/suggest", response_model=BRollSuggestResponse)
@limiter.limit(Tier.LLM_HEAVY)
async def suggest_broll(
    request: Request,
    body: BRollForTextRequest,
    current_user: User = Depends(get_current_user),
) -> BRollSuggestResponse:
    """Find B-roll suggestions based on text content (auth required)."""
    try:
        from src.features.broll_finder import BRollFinder

        finder = BRollFinder()
        keywords = finder.extract_keywords(body.text)
        visual_cues = finder.extract_visual_cues(body.text)

        clips = finder.find_broll_for_text(
            text=body.text,
            max_clips=body.max_clips,
        )

        return BRollSuggestResponse(
            text_preview=(
                body.text[:200] + "..." if len(body.text) > 200 else body.text
            ),
            extracted_keywords=keywords[:5],
            visual_cues=visual_cues,
            clips=[
                BRollSuggestion(
                    id=c.id,
                    source=c.source,
                    title=c.title,
                    duration=c.duration,
                    preview_url=c.preview_url,
                    download_url=c.download_url,
                    thumbnail_url=c.thumbnail_url,
                    quality=c.quality,
                )
                for c in clips
            ],
        )
    except Exception as e:
        logger.error(f"B-roll suggestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/broll/script", response_model=BRollScriptResponse)
@limiter.limit(Tier.LLM_HEAVY)
async def get_broll_for_script(
    request: Request,
    body: BRollForScriptRequest,
    current_user: User = Depends(get_current_user),
) -> BRollScriptResponse:
    """Find B-roll suggestions for each section of a video script (auth required)."""
    try:
        from src.features.broll_finder import BRollFinder

        finder = BRollFinder()
        sections = [
            {"name": s.name, "content": s.content, "timestamp": s.timestamp}
            for s in body.sections
        ]

        suggestions = finder.find_broll_for_script(
            script_sections=sections,
            clips_per_section=body.clips_per_section,
        )

        return BRollScriptResponse(
            suggestions=[
                BRollScriptSectionSuggestion(
                    section_name=s.section_name,
                    section_preview=s.section_text,
                    keywords=s.keywords,
                    timestamp=s.timestamp,
                    clips=[
                        BRollSuggestion(
                            id=c.id,
                            source=c.source,
                            title=c.title,
                            duration=c.duration,
                            preview_url=c.preview_url,
                            download_url=c.download_url,
                            thumbnail_url=c.thumbnail_url,
                        )
                        for c in s.clips
                    ],
                )
                for s in suggestions
            ],
        )
    except Exception as e:
        logger.error(f"B-roll for script failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# /broll/promote-image — image URL → cached MP4 URL
# ---------------------------------------------------------------------------


class PromoteImageRequest(BaseModel):
    """Body for POST /broll/promote-image.

    ``duration_seconds`` controls how long the resulting still video plays;
    the user can still trim it on the timeline after adding, so a default
    of 4s is a safe sweet-spot for short-form B-roll.
    """

    image_url: str = Field(..., min_length=8, max_length=2000)
    duration_seconds: float = Field(default=4.0, ge=0.5, le=15.0)


def _ffmpeg_bin() -> str:
    """Locate the ffmpeg binary, preferring ffmpeg-full (libass) when
    installed via Homebrew. Falls back to PATH so the endpoint still
    works in containers / CI without the Homebrew prefix."""
    for cand in (
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
    ):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return shutil.which("ffmpeg") or "ffmpeg"


def _cache_key_for(image_url: str, duration_seconds: float) -> str:
    """Content-addressed cache key. Same URL + same duration ⇒ same MP4."""
    seed = f"{image_url}|{duration_seconds:.2f}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _download_image(url: str, dest_path: str) -> str:
    """Fetch the image to ``dest_path``. Validates size + content-type so
    we never feed ffmpeg a 500 MB png or an HTML error page."""
    try:
        with httpx.Client(follow_redirects=True, timeout=_IMAGE_DOWNLOAD_TIMEOUT_S) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                ctype = (response.headers.get("content-type") or "").lower()
                if "image/" not in ctype:
                    raise HTTPException(
                        status_code=415,
                        detail=f"URL did not return an image (content-type={ctype!r})",
                    )
                size = 0
                with open(dest_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=1 << 16):
                        size += len(chunk)
                        if size > _IMAGE_MAX_BYTES:
                            raise HTTPException(
                                status_code=413,
                                detail=f"image exceeds {_IMAGE_MAX_BYTES} bytes",
                            )
                        f.write(chunk)
        return dest_path
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"image download failed: {exc}")


def _encode_still_to_mp4(image_path: str, mp4_path: str, duration_seconds: float) -> None:
    """ffmpeg-encode a static image into a fixed-duration MP4 loop.

    The filter graph rounds dimensions to even numbers (required by
    yuv420p) and converts to a render-friendly pixel format. We use
    ``-preset veryfast`` because the inputs are tiny still images; the
    encode is bottlenecked by libx264 startup, not throughput.
    """
    cmd = [
        _ffmpeg_bin(),
        "-y",
        "-loop", "1",
        "-i", image_path,
        "-t", f"{duration_seconds:.3f}",
        "-vf", "scale='trunc(iw/2)*2:trunc(ih/2)*2',format=yuv420p",
        "-r", "30",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-movflags", "+faststart",
        mp4_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        # Don't leak ffmpeg's full stderr to the client — it's long. Log
        # the tail and surface a generic 500 with the last line for hint.
        tail = "\n".join(proc.stderr.splitlines()[-6:])
        logger.error(
            "broll.promote_image.ffmpeg_failed",
            rc=proc.returncode,
            tail=tail[:500],
        )
        raise HTTPException(
            status_code=500,
            detail=f"image-to-video encode failed (ffmpeg rc={proc.returncode})",
        )


def _promote_image_sync(image_url: str, duration_seconds: float) -> dict:
    """Synchronous worker for the endpoint — runs off the event loop."""
    os.makedirs(_IMAGE_CACHE_DIR, exist_ok=True)
    key = _cache_key_for(image_url, duration_seconds)
    mp4_path = os.path.join(_IMAGE_CACHE_DIR, f"{key}.mp4")
    public_url = f"{_IMAGE_CACHE_PUBLIC_PREFIX}/{key}.mp4"

    if os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 1024:
        return {
            "download_url": public_url,
            "duration_seconds": duration_seconds,
            "cached": True,
        }

    # Pull image into the cache dir under a temp name so a failed encode
    # never leaves a half-written .mp4 with the canonical key.
    tmp_img = os.path.join(_IMAGE_CACHE_DIR, f"{key}.src")
    try:
        _download_image(image_url, tmp_img)
        _encode_still_to_mp4(tmp_img, mp4_path, duration_seconds)
    finally:
        # Source image is no longer needed after the encode succeeds; the
        # MP4 is the source of truth from here on out.
        if os.path.exists(tmp_img):
            try:
                os.remove(tmp_img)
            except OSError:
                pass

    return {
        "download_url": public_url,
        "duration_seconds": duration_seconds,
        "cached": False,
    }


@router.post("/broll/promote-image", response_model=PromoteImageResponse)
@limiter.limit(Tier.WRITE)
async def promote_image_to_video(
    request: Request,
    body: PromoteImageRequest,
    current_user: User = Depends(get_current_user),
) -> PromoteImageResponse:
    """Convert a still-image URL into a short, looping MP4 the Studio
    timeline can render as a B-roll clip.

    The first call downloads + encodes (1-3 seconds); subsequent calls
    for the same ``(image_url, duration_seconds)`` pair are O(1) from
    the on-disk cache.
    """
    payload = await asyncio.to_thread(
        _promote_image_sync, body.image_url, body.duration_seconds
    )
    return PromoteImageResponse(**payload)
