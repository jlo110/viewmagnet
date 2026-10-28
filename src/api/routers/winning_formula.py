"""Winning Formula: /winning-formula/{channel_id} and /engagement comparison."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import unquote

import numpy as np
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["winning-formula"])


class TitlePatternResponse(BaseModel):
    pattern: str
    example: str
    frequency: float
    avg_performance: float
    recommendation: str


class ThumbnailPatternResponse(BaseModel):
    element: str
    frequency: float
    impact: float
    description: str


class ContentPatternResponse(BaseModel):
    aspect: str
    optimal_value: str
    current_avg: str
    impact: float


@router.get("/winning-formula/{channel_id:path}")
@limiter.limit(Tier.READ)
async def get_winning_formula(
    request: Request,
    channel_id: str,
    current_user: User = Depends(get_current_user),
):
    """Analyze a channel's winning formula (auth required).

    Accepts a channel ID (``UC...``), a handle (``@username``), or a full
    YouTube URL.
    """
    try:
        from src.features.winning_formula import WinningFormulaAnalyzer

        channel_id = unquote(channel_id)
        if "youtube.com" in channel_id:
            handle_match = re.search(r"youtube\.com/@([^/?\s]+)", channel_id)
            if handle_match:
                channel_id = f"@{handle_match.group(1)}"
            else:
                channel_match = re.search(r"youtube\.com/channel/([^/?\s]+)", channel_id)
                if channel_match:
                    channel_id = channel_match.group(1)
        channel_id = channel_id.rstrip("/")

        logger.info(f"Analyzing winning formula for: {channel_id}")

        analyzer = WinningFormulaAnalyzer()
        formula = analyzer.analyze(channel_id)

        if not formula:
            logger.info(f"Channel not in database, fetching from YouTube: {channel_id}")
            return await _live_winning_formula(channel_id)

        return {
            "channel_name": formula.channel_name,
            "channel_id": formula.channel_id,
            "total_videos_analyzed": formula.total_videos_analyzed,
            "avg_views": formula.avg_views,
            "hit_rate": formula.hit_rate,
            "title_patterns": [
                {
                    "pattern": p.pattern,
                    "example": p.example,
                    "frequency": p.frequency,
                    "avg_performance": p.avg_performance,
                    "recommendation": p.recommendation,
                }
                for p in formula.title_patterns
            ],
            "thumbnail_patterns": [
                {
                    "element": p.element,
                    "frequency": p.frequency,
                    "impact": p.impact,
                    "description": p.description,
                }
                for p in formula.thumbnail_patterns
            ],
            "content_patterns": [
                {
                    "aspect": p.aspect,
                    "optimal_value": p.optimal_value,
                    "current_avg": p.current_avg,
                    "impact": p.impact,
                }
                for p in formula.content_patterns
            ],
            "optimal_title_length": formula.optimal_title_length,
            "optimal_video_length": formula.optimal_video_length,
            "best_posting_times": formula.best_posting_times,
            "top_videos": formula.top_videos[:5],
            "key_insights": formula.key_insights,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to analyze winning formula: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _live_winning_formula(channel_id: str) -> dict:
    """Live-API fallback when the channel isn't yet in our DB."""
    from src.youtube.client import YouTubeClient

    yt = YouTubeClient()

    actual_channel_id = channel_id
    channel_info = None

    if channel_id.startswith("@"):
        handle_name = channel_id[1:]
        search_results = yt.search_channels(query=handle_name, max_results=5)

        if search_results and "items" in search_results:
            for item in search_results["items"]:
                snippet = item.get("snippet", {})
                found_channel_id = snippet.get("channelId")
                custom_url = snippet.get("customUrl", "").lower()

                if custom_url in (channel_id.lower(), handle_name.lower()):
                    actual_channel_id = found_channel_id
                    break
                if found_channel_id:
                    actual_channel_id = found_channel_id
                    break

        if actual_channel_id == channel_id:
            raise HTTPException(status_code=404, detail=f"Channel not found: {channel_id}")

    channels = yt.get_channel_details([actual_channel_id])
    if not channels:
        raise HTTPException(status_code=404, detail=f"Channel not found: {channel_id}")
    channel_info = channels[0]

    uploads_playlist_id = channel_info.uploads_playlist_id
    if not uploads_playlist_id and actual_channel_id.startswith("UC"):
        uploads_playlist_id = "UU" + actual_channel_id[2:]

    video_ids: list[str] = []
    if uploads_playlist_id:
        playlist_response = yt.get_channel_videos(
            uploads_playlist_id=uploads_playlist_id, max_results=30
        )
        if playlist_response and "items" in playlist_response:
            for item in playlist_response["items"]:
                vid_id = item.get("contentDetails", {}).get("videoId")
                if vid_id:
                    video_ids.append(vid_id)

    if len(video_ids) < 5:
        raise HTTPException(
            status_code=404,
            detail=f"Not enough videos to analyze. Found {len(video_ids)}, need at least 5.",
        )

    videos = yt.get_video_details(video_ids)

    view_counts = [v.view_count or 0 for v in videos]
    avg_views = float(np.mean(view_counts)) if view_counts else 0
    median_views = float(np.median(view_counts)) if view_counts else 0

    hits = [v for v in videos if (v.view_count or 0) > avg_views * 1.5]
    hit_rate = len(hits) / len(videos) if videos else 0

    title_patterns: list[dict] = []
    common_words: dict = {}
    for v in videos:
        for word in v.title.lower().split():
            if len(word) > 3:
                bucket = common_words.setdefault(
                    word, {"count": 0, "total_views": 0, "example": v.title}
                )
                bucket["count"] += 1
                bucket["total_views"] += v.view_count or 0

    for word, data in sorted(
        common_words.items(), key=lambda x: x[1]["total_views"], reverse=True
    )[:5]:
        if data["count"] >= 2:
            avg_pattern_views = data["total_views"] / data["count"]
            title_patterns.append({
                "pattern": word.title(),
                "example": data["example"],
                "frequency": data["count"] / len(videos),
                "avg_performance": avg_pattern_views / avg_views if avg_views > 0 else 1,
                "recommendation": f"Videos with '{word}' perform well",
            })

    insights: list[str] = []
    if hit_rate > 0.3:
        insights.append(f"Strong hit rate! {hit_rate:.0%} of videos outperform average")
    elif hit_rate < 0.1:
        insights.append(
            f"Low hit rate ({hit_rate:.0%}). Focus on replicating your top performers"
        )

    subs = channel_info.subscriber_count or 0
    if subs > 0:
        view_sub_ratio = median_views / subs
        if view_sub_ratio > 1:
            insights.append(f"Great reach! Videos get {view_sub_ratio:.1f}x subscriber count")
        elif view_sub_ratio < 0.3:
            insights.append(
                "Subscribers not converting to views. Improve notification prompts"
            )

    day_views: dict = {}
    for v in videos:
        if v.published_at:
            day = v.published_at.strftime("%A")
            day_views.setdefault(day, []).append(v.view_count or 0)
    if day_views:
        best_day = max(day_views.items(), key=lambda x: np.mean(x[1]))
        insights.append(f"Best upload day: {best_day[0]}")

    sorted_videos = sorted(videos, key=lambda x: x.view_count or 0, reverse=True)
    top_videos = sorted_videos[:5]
    bottom_videos = sorted_videos[-5:] if len(sorted_videos) > 5 else []

    losing_patterns: list[dict] = []
    bottom_half = sorted_videos[len(sorted_videos) // 2:]
    top_half = sorted_videos[: len(sorted_videos) // 2]

    weak_patterns: list[dict] = []
    for v in bottom_half[:5]:
        title = v.title.lower()
        if "?" in title and len(title.split()) < 6:
            weak_patterns.append({
                "pattern": "Short question-only titles",
                "example": v.title,
                "views": v.view_count or 0,
            })
        elif title.startswith(("what ", "how to ", "why ")):
            if not any(c in title for c in ["!", "🔥", "💀", "😱"]):
                weak_patterns.append({
                    "pattern": "Tutorial titles without hooks",
                    "example": v.title,
                    "views": v.view_count or 0,
                })
        elif len(title.split()) <= 3:
            weak_patterns.append({
                "pattern": "Very short titles (<4 words)",
                "example": v.title,
                "views": v.view_count or 0,
            })

    hit_words: set = set()
    for v in top_half:
        for word in v.title.lower().split():
            if len(word) > 3:
                hit_words.add(word)

    flop_words: dict = {}
    for v in bottom_half:
        for word in v.title.lower().split():
            if len(word) > 3 and word not in hit_words:
                bucket = flop_words.setdefault(
                    word, {"count": 0, "total_views": 0, "example": v.title}
                )
                bucket["count"] += 1
                bucket["total_views"] += v.view_count or 0

    for word, data in sorted(
        flop_words.items(), key=lambda x: x[1]["count"], reverse=True
    )[:3]:
        avg_flop_views = data["total_views"] / data["count"] if data["count"] > 0 else 0
        perf_ratio = avg_flop_views / avg_views if avg_views > 0 else 0
        if perf_ratio < 1.0:
            losing_patterns.append({
                "pattern": f"Videos mentioning '{word}'",
                "impact": f"-{max(0.2, 1 - perf_ratio):.1f}x",
                "example": data["example"],
            })

    pattern_counts: dict = {}
    for wp in weak_patterns:
        bucket = pattern_counts.setdefault(
            wp["pattern"], {"count": 0, "example": wp["example"], "total_views": 0}
        )
        bucket["count"] += 1
        bucket["total_views"] += wp["views"]
    for pattern, data in pattern_counts.items():
        pattern_avg = data["total_views"] / data["count"] if data["count"] > 0 else 0
        perf_ratio = pattern_avg / avg_views if avg_views > 0 else 0
        losing_patterns.append({
            "pattern": pattern,
            "impact": f"-{max(0.3, 1 - perf_ratio):.1f}x",
            "example": data["example"],
        })

    if not losing_patterns and bottom_half:
        worst = bottom_half[-1]
        losing_patterns = [
            {
                "pattern": "Low engagement thumbnails",
                "impact": "-0.4x",
                "example": "Videos with cluttered or dark thumbnails",
            },
            {
                "pattern": "Non-trending topics",
                "impact": "-0.3x",
                "example": worst.title if worst else "Content outside your niche",
            },
            {
                "pattern": "Inconsistent upload timing",
                "impact": "-0.2x",
                "example": "Weekend uploads or irregular schedules",
            },
        ]

    hit_videos = [v for v in videos if (v.view_count or 0) > avg_views]
    flop_videos = [v for v in videos if (v.view_count or 0) < avg_views * 0.5]

    def _timing(video_list):
        if not video_list:
            return 50
        good_times = 0
        for v in video_list:
            if v.published_at:
                if v.published_at.weekday() < 4:
                    good_times += 1
                if 14 <= v.published_at.hour <= 18:
                    good_times += 0.5
        return min(100, int((good_times / len(video_list)) * 100))

    def _title(video_list):
        if not video_list:
            return 50
        score = 0
        for v in video_list:
            if any(c.isdigit() for c in v.title[:20]):
                score += 1
            if 40 <= len(v.title) <= 65:
                score += 1
            if any(w in v.title.lower() for w in ["how", "why", "best", "top", "!"]):
                score += 0.5
        return min(100, int((score / (len(video_list) * 2.5)) * 100))

    def _hook(video_list):
        if not video_list:
            return 50
        score = 0
        for v in video_list:
            title = v.title.lower()
            if any(c.isdigit() for c in title[:20]):
                score += 1
            if any(w in title for w in [
                "best", "worst", "ultimate", "insane", "crazy", "amazing", "secret", "hidden",
            ]):
                score += 1
            if any(w in title for w in ["never", "always", "only", "finally", "actually"]):
                score += 0.5
            if any(ord(c) > 127 for c in v.title):
                score += 0.5
        return min(100, int((score / (len(video_list) * 2)) * 100))

    def _thumb(video_list):
        if not video_list:
            return 50
        score = 0
        for v in video_list:
            tl = len(v.title)
            if 30 <= tl <= 60:
                score += 1
            if tl < 30:
                score += 0.5
            if any(w in v.title.lower() for w in ["i ", "my ", "the ", "this "]):
                score += 0.5
        return min(100, int((score / (len(video_list) * 1.5)) * 100))

    def _topic_relevance(video_list, all_videos):
        if not video_list or not all_videos:
            return 50
        all_words: dict = {}
        for v in all_videos:
            for word in v.title.lower().split():
                if len(word) > 3:
                    all_words[word] = all_words.get(word, 0) + 1
        top_topics = [w for w, _ in sorted(all_words.items(), key=lambda x: -x[1])[:10]]

        score = 0
        for v in video_list:
            title_words = v.title.lower().split()
            matches = sum(1 for w in title_words if w in top_topics)
            score += min(2, matches)
        return min(100, int((score / (len(video_list) * 2)) * 100))

    def _tag(video_list):
        if not video_list:
            return 50
        score = 0
        for v in video_list:
            title = v.title.lower()
            if any(c.isdigit() for c in title):
                score += 0.5
            if "|" in v.title or "-" in v.title:
                score += 0.5
            if 40 <= len(v.title) <= 70:
                score += 1
            if any(year in title for year in ["2024", "2025", "2026"]):
                score += 1
        return min(100, int((score / (len(video_list) * 2)) * 100))

    radar_data = [
        {"factor": "Title Length", "hits": _title(hit_videos), "flops": _title(flop_videos)},
        {"factor": "Thumbnail Quality", "hits": _thumb(hit_videos), "flops": _thumb(flop_videos)},
        {"factor": "Hook Strength", "hits": _hook(hit_videos), "flops": _hook(flop_videos)},
        {
            "factor": "Topic Relevance",
            "hits": _topic_relevance(hit_videos, videos),
            "flops": _topic_relevance(flop_videos, videos),
        },
        {"factor": "Upload Timing", "hits": _timing(hit_videos), "flops": _timing(flop_videos)},
        {"factor": "Tag Optimization", "hits": _tag(hit_videos), "flops": _tag(flop_videos)},
    ]

    return {
        "channel_name": channel_info.channel_name,
        "channel_id": actual_channel_id,
        "total_videos_analyzed": len(videos),
        "avg_views": int(avg_views),
        "median_views": int(median_views),
        "hit_rate": hit_rate,
        "subscriber_count": subs,
        "title_patterns": title_patterns[:5],
        "losing_patterns": losing_patterns[:3],
        "thumbnail_patterns": [],
        "timing_patterns": [],
        "radar_data": radar_data,
        "key_insights": insights[:5],
        "top_performing_videos": [
            {"title": v.title, "views": v.view_count, "video_id": v.video_id}
            for v in top_videos
        ],
        "bottom_performing_videos": [
            {"title": v.title, "views": v.view_count, "video_id": v.video_id}
            for v in bottom_videos
        ],
        "source": "live_api",
    }


@router.get("/winning-formula/{channel_id}/engagement")
@limiter.limit(Tier.READ)
async def compare_channel_engagement(
    request: Request,
    channel_id: str,
    video_id: Optional[str] = Query(default=None, max_length=11),
    current_user: User = Depends(get_current_user),
):
    """Compare a video's engagement to the channel's baseline."""
    try:
        from src.features.winning_formula import compare_engagement_to_baseline

        comparison = compare_engagement_to_baseline(channel_id, video_id)
        if not comparison:
            raise HTTPException(status_code=404, detail="No data found")

        def _attr(name: str, default=0):
            return getattr(comparison, name, default)

        return {
            "channel_id": channel_id,
            "video_id": video_id,
            "views": {
                "current": _attr("video_views"),
                "baseline": _attr("baseline_views"),
                "vs_baseline": _attr("views_vs_baseline"),
            },
            "likes": {
                "current_ratio": _attr("like_ratio"),
                "baseline_ratio": _attr("baseline_like_ratio"),
                "vs_baseline": _attr("likes_vs_baseline"),
            },
            "comments": {
                "current_ratio": _attr("comment_ratio"),
                "baseline_ratio": _attr("baseline_comment_ratio"),
                "vs_baseline": _attr("comments_vs_baseline"),
            },
            "performance_tier": _attr("performance_tier", "unknown"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compare engagement: {e}")
        raise HTTPException(status_code=500, detail=str(e))
