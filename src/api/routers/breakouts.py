"""Breakout Radar — the live, cross-channel breakout feed (plan 9.1 flagship).

The wedge a static-index competitor can't match: what's breaking out across the
tracked YouTube ecosystem *right now*, detected from the live velocity collection
(calibrated P(breakout), AUC 0.93) — annotated with topic saturation (is the wave
crowded?) and niche-conditioned confidence (how reliable the early call is for
that vertical). User-facing (auth'd, not admin); works on the tracked set, so it
needs no user OAuth.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_session
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["breakouts"])

_CAT_NAMES = {
    "1": "Film", "2": "Autos", "10": "Music", "15": "Pets", "17": "Sports",
    "19": "Travel", "20": "Gaming", "22": "People & Blogs", "23": "Comedy",
    "24": "Entertainment", "25": "News", "26": "Howto", "27": "Education",
    "28": "Science & Tech", "29": "Nonprofit",
}


def _annotate_niche(db, items: list) -> list:
    """Attach category + measured niche detection-confidence to each item."""
    from sqlalchemy import func, select

    from src.database.models import VideoSnapshot
    from src.features.breakout_detector import detection_confidence

    vids = [it["video_id"] for it in items]
    if not vids:
        return items
    # Modal category + an audio-language per video (one grouped query).
    rows = db.execute(
        select(VideoSnapshot.video_id, VideoSnapshot.youtube_category_id,
               func.count().label("n"))
        .where(VideoSnapshot.video_id.in_(vids),
               VideoSnapshot.youtube_category_id.isnot(None))
        .group_by(VideoSnapshot.video_id, VideoSnapshot.youtube_category_id)
    ).all()
    best: dict = {}
    for vid, cat, n in rows:
        if vid not in best or n > best[vid][1]:
            best[vid] = (cat, n)
    langs = dict(
        db.execute(
            select(VideoSnapshot.video_id, func.max(VideoSnapshot.default_audio_language))
            .where(VideoSnapshot.video_id.in_(vids))
            .group_by(VideoSnapshot.video_id)
        ).all()
    )
    for it in items:
        cat = best.get(it["video_id"], (None, 0))[0]
        conf = detection_confidence(cat)
        it["niche"] = _CAT_NAMES.get(cat or "", "Other")
        it["confidence"] = conf["confidence"]
        it["audio_language"] = langs.get(it["video_id"])
        it["thumbnail_url"] = f"https://i.ytimg.com/vi/{it['video_id']}/hqdefault.jpg"
        it["watch_url"] = f"https://www.youtube.com/watch?v={it['video_id']}"
    return items


@router.get("/breakouts")
@limiter.limit(Tier.READ)
async def breakout_radar(
    request: Request,  # noqa: ARG001 — slowapi
    checkpoint: str = Query(default="6h", pattern="^(1h|6h|24h)$"),
    min_probability: float = Query(default=0.7, ge=0.0, le=1.0),
    max_age_hours: float = Query(default=48.0, ge=1.0, le=336.0),
    min_views: float = Query(default=1000.0, ge=0.0),
    niche: Optional[str] = Query(default=None, description="category id filter, e.g. 20"),
    english_only: bool = Query(default=True, description="drop non-English titles"),
    limit: int = Query(default=40, ge=1, le=100),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """What's breaking out across the tracked ecosystem right now, ranked.

    Each item: calibrated P(breakout) + level, the topic it's riding (with how
    saturated that topic is), and the niche-conditioned detection confidence.
    """
    from src.features.breakout_detector import detect_live_breakouts
    from src.features.topic_saturation import annotate_with_topics

    try:
        with get_session() as db:
            items = detect_live_breakouts(
                db, checkpoint=checkpoint, min_probability=min_probability,
                max_age_hours=max_age_hours, min_views=min_views, limit=limit,
            )
            items = annotate_with_topics(db, items)
            items = _annotate_niche(db, items)
    except Exception as exc:  # noqa: BLE001
        logger.warning("breakouts.failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"breakout radar failed: {exc}",
        )
    if english_only:
        from src.features.language import is_probably_english

        items = [it for it in items if is_probably_english(it.get("title"), it.get("audio_language"))]
    if niche:
        items = [it for it in items if best_cat_matches(it, niche)]
    return {
        "checkpoint": checkpoint,
        "count": len(items),
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "breakouts": items,
    }


def best_cat_matches(item: dict, niche_id: str) -> bool:
    return _CAT_NAMES.get(niche_id, "") == item.get("niche")


@router.get("/breakouts/{video_id}/explain")
@limiter.limit(Tier.LLM_HEAVY)
async def explain(
    request: Request,  # noqa: ARG001
    video_id: str,
    idea: Optional[str] = Query(default=None, description="the creator's niche/context"),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """Why is this breaking out + your version of the angle (plan 8.7).

    Grounded only in measured evidence (early performance vs the channel's own
    norm, topic saturation, packaging, early comments) — never the open web.
    The single-shot strategist move that makes the radar actionable.
    """
    from src.features.breakout_explainer import explain_breakout

    plan = getattr(current_user, "plan", None) or "free"
    try:
        with get_session() as db:
            result = explain_breakout(db, video_id, user_idea=idea,
                                      user_id=current_user.id, plan=plan)
    except Exception as exc:  # noqa: BLE001
        logger.warning("breakouts.explain_failed", video_id=video_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"explain failed: {exc}",
        )
    if result.get("error") == "video_not_found_or_no_snapshots":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown video.")
    return result


def _teardown_comments(db, video_id: str):
    """Captured comments for this video, or an on-demand fetch (most breakouts
    aren't in our ~1% capture). Returns a list of {text, like_count} or []."""
    from sqlalchemy import select

    from src.database.models import VideoComment
    rows = db.execute(
        select(VideoComment.text, VideoComment.like_count)
        .where(VideoComment.video_id == video_id)
        .order_by(VideoComment.like_count.desc()).limit(100)
    ).all()
    if rows:
        return [{"text": t, "like_count": lc} for t, lc in rows]
    try:
        from src.features.comment_analyzer import CommentFetcher
        return [{"text": c.text, "like_count": getattr(c, "like_count", 0)}
                for c in CommentFetcher().fetch_comments(video_id, max_results=100, order="relevance")]
    except Exception:  # noqa: BLE001
        return []


@router.get("/breakouts/{video_id}/teardown")
@limiter.limit(Tier.LLM_HEAVY)
async def teardown(
    request: Request,  # noqa: ARG001
    video_id: str,
    idea: Optional[str] = Query(default=None, description="the creator's niche/context"),
    current_user: User = Depends(get_current_user),
):
    """Full reverse-engineering of one breakout — assembles every signal we have:
    WHY it's breaking out (vs the channel), the FORMAT it used, what viewers are
    saying (comment themes / content gaps), and the RETENTION shape (most-replayed).
    The 'make your version' teardown. Each section degrades gracefully if missing.
    """
    import json as _json

    from src.database.models import VideoHeatmap
    from src.features.breakout_explainer import explain_breakout
    from src.features.comment_intelligence import analyze_comments
    from src.features.emerging_formats import FORMAT_SPEC_BY_KEY, _match_format

    plan = getattr(current_user, "plan", None) or "free"
    try:
        with get_session() as db:
            explanation = explain_breakout(db, video_id, user_idea=idea,
                                           user_id=current_user.id, plan=plan)
            if explanation.get("error") == "video_not_found_or_no_snapshots":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown video.")
            title = (explanation.get("evidence") or {}).get("title", "")

            fmt = None
            key = _match_format(title) if title else None
            if key:
                _, template, psychology = FORMAT_SPEC_BY_KEY[key]
                fmt = {"key": key, "template": template, "psychology": psychology}

            comments = _teardown_comments(db, video_id)
            comment_intel = analyze_comments(
                comments, user_id=current_user.id, plan=plan) if comments else None

            heatmap = None
            hm = db.query(VideoHeatmap.points, VideoHeatmap.video_duration_seconds).filter_by(
                video_id=video_id, has_heatmap=True).first()
            if hm and hm[0]:
                heatmap = {"points": _json.loads(hm[0]), "duration_seconds": hm[1]}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("breakouts.teardown_failed", video_id=video_id, error=str(exc))
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"teardown failed: {exc}")
    return {
        "video_id": video_id,
        "title": title,
        "explanation": explanation,    # why / your_angle / caveat / evidence
        "format": fmt,                 # the transferable format it used (or null)
        "comments": comment_intel,     # themes / questions / next-video ideas (or null)
        "retention": heatmap,          # most-replayed curve (or null — <~2wk old)
    }
