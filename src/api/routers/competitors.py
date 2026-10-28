"""POST /competitors/analyze: side-by-side comparison vs. another channel."""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

import numpy as np
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["competitors"])


@router.post("/competitors/analyze")
@limiter.limit(Tier.LLM_HEAVY)
async def analyze_competitor(
    request: Request,
    channel_url: str = Query(..., max_length=500),
    your_channel_id: Optional[str] = Query(default=None, max_length=24),
    current_user: User = Depends(get_current_user),
):
    """Analyze a competitor channel -- fetches data from YouTube directly."""
    try:
        from src.youtube.client import YouTubeClient

        client = YouTubeClient()
        channel_input = channel_url.strip()

        def search_and_get_channel(query):
            """Search for a channel and get its details."""
            search_result = client.search_channels(query, max_results=1)
            items = search_result.get("items", [])
            if items:
                channel_id = (
                    items[0].get("snippet", {}).get("channelId")
                    or items[0].get("id", {}).get("channelId")
                )
                if channel_id:
                    details = client.get_channel_details([channel_id])
                    return details[0] if details else None
            return None

        channel_details = None
        if channel_input.startswith("@"):
            channel_details = search_and_get_channel(channel_input[1:])
        elif "youtube.com" in channel_input:
            patterns = [
                r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})",
                r"youtube\.com/@([a-zA-Z0-9_-]+)",
                r"youtube\.com/c/([a-zA-Z0-9_-]+)",
            ]
            for pattern in patterns:
                match = re.search(pattern, channel_input)
                if match:
                    identifier = match.group(1)
                    if identifier.startswith("UC"):
                        details = client.get_channel_details([identifier])
                        channel_details = details[0] if details else None
                    else:
                        channel_details = search_and_get_channel(identifier)
                    break
        else:
            if channel_input.startswith("UC") and len(channel_input) == 24:
                details = client.get_channel_details([channel_input])
                channel_details = details[0] if details else None
            else:
                channel_details = search_and_get_channel(channel_input)

        if not channel_details:
            return {
                "competitor": {"name": channel_input, "channel_id": channel_input},
                "metrics": [],
                "strategy_differences": [],
                "opportunities": [],
                "competitor_strengths": ["Channel not found - check the URL/name"],
                "your_advantages": [],
            }

        if not channel_details.uploads_playlist_id:
            return {
                "competitor": {
                    "name": channel_details.channel_name,
                    "channel_id": channel_details.channel_id,
                    "subscribers": channel_details.subscriber_count,
                    "total_views": channel_details.total_views,
                },
                "metrics": [],
                "strategy_differences": [],
                "opportunities": [],
                "competitor_strengths": ["Could not access channel videos"],
                "your_advantages": [],
            }

        playlist_response = client.get_channel_videos(
            channel_details.uploads_playlist_id, max_results=30
        )
        playlist_items = playlist_response.get("items", [])

        if not playlist_items:
            return {
                "competitor": {
                    "name": channel_details.channel_name,
                    "channel_id": channel_details.channel_id,
                    "subscribers": channel_details.subscriber_count,
                    "total_views": channel_details.total_views,
                },
                "metrics": [],
                "strategy_differences": [],
                "opportunities": [],
                "competitor_strengths": ["No recent videos found"],
                "your_advantages": [],
            }

        video_ids = [
            item.get("contentDetails", {}).get("videoId")
            for item in playlist_items
            if item.get("contentDetails", {}).get("videoId")
        ]
        video_details = client.get_video_details(video_ids) if video_ids else []

        avg_views = int(np.mean([v.view_count for v in video_details])) if video_details else 0
        avg_likes = int(np.mean([v.like_count or 0 for v in video_details])) if video_details else 0
        avg_comments = int(np.mean([v.comment_count or 0 for v in video_details])) if video_details else 0
        avg_duration = (
            int(np.mean([v.duration_seconds or 0 for v in video_details]) / 60)
            if video_details else 0
        )
        engagement_rate = round((avg_likes / max(avg_views, 1)) * 100, 2)

        titles = [v.title for v in video_details]
        question_titles = sum(1 for t in titles if "?" in t) / max(len(titles), 1) * 100
        number_titles = sum(1 for t in titles if re.search(r"\d", t)) / max(len(titles), 1) * 100

        sorted_videos = sorted(video_details, key=lambda v: v.view_count, reverse=True)
        top_video = sorted_videos[0] if sorted_videos else None
        hit_rate = (
            len([v for v in video_details if v.view_count > avg_views * 1.5])
            / max(len(video_details), 1) * 100
        )

        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
            "with", "by", "from", "is", "it", "this", "that", "my", "i", "you", "we",
            "they", "how", "what", "why", "when", "where",
        }
        all_words: list[str] = []
        for t in titles:
            words = re.findall(r"\b[a-zA-Z]{3,}\b", t.lower())
            all_words.extend([w for w in words if w not in stop_words])
        common_topics = [w for w, _ in Counter(all_words).most_common(5)]

        # Optional: pull "your" channel metrics for the comparison view.
        your_channel_details = None
        your_avg_views = 0
        your_avg_likes = 0
        your_avg_duration = 0
        your_engagement_rate = 0.0
        your_hit_rate = 0.0
        your_question_titles = 0.0
        your_number_titles = 0.0
        your_topics: list[str] = []
        your_advantages: list[str] = []

        if your_channel_id and your_channel_id.startswith("UC"):
            try:
                your_details = client.get_channel_details([your_channel_id])
                if your_details:
                    your_channel_details = your_details[0]
                    if your_channel_details.uploads_playlist_id:
                        your_playlist = client.get_channel_videos(
                            your_channel_details.uploads_playlist_id, max_results=30
                        )
                        your_video_ids = [
                            item.get("contentDetails", {}).get("videoId")
                            for item in your_playlist.get("items", [])
                            if item.get("contentDetails", {}).get("videoId")
                        ]
                        your_videos = (
                            client.get_video_details(your_video_ids) if your_video_ids else []
                        )

                        if your_videos:
                            your_avg_views = int(np.mean([v.view_count for v in your_videos]))
                            your_avg_likes = int(
                                np.mean([v.like_count or 0 for v in your_videos])
                            )
                            your_avg_duration = int(
                                np.mean([v.duration_seconds or 0 for v in your_videos]) / 60
                            )
                            your_engagement_rate = round(
                                (your_avg_likes / max(your_avg_views, 1)) * 100, 2
                            )
                            your_hit_rate = (
                                len([
                                    v for v in your_videos
                                    if v.view_count > your_avg_views * 1.5
                                ]) / max(len(your_videos), 1) * 100
                            )

                            your_titles = [v.title for v in your_videos]
                            your_question_titles = (
                                sum(1 for t in your_titles if "?" in t)
                                / max(len(your_titles), 1) * 100
                            )
                            your_number_titles = (
                                sum(1 for t in your_titles if re.search(r"\d", t))
                                / max(len(your_titles), 1) * 100
                            )

                            your_words: list[str] = []
                            for t in your_titles:
                                words = re.findall(r"\b[a-zA-Z]{3,}\b", t.lower())
                                your_words.extend([w for w in words if w not in stop_words])
                            your_topics = [w for w, _ in Counter(your_words).most_common(5)]

                            if your_avg_views > avg_views:
                                your_advantages.append(
                                    f"Higher avg views: {int(your_avg_views/1000)}K vs "
                                    f"{int(avg_views/1000)}K"
                                )
                            if your_engagement_rate > engagement_rate:
                                your_advantages.append(
                                    f"Better engagement: {your_engagement_rate}% vs "
                                    f"{engagement_rate}%"
                                )
                            if your_hit_rate > hit_rate:
                                your_advantages.append(
                                    f"Better hit rate: {your_hit_rate:.0f}% vs "
                                    f"{hit_rate:.0f}%"
                                )
                            if your_channel_details.subscriber_count > channel_details.subscriber_count:
                                your_advantages.append(
                                    f"Larger audience: "
                                    f"{your_channel_details.subscriber_count/1000:.0f}K vs "
                                    f"{channel_details.subscriber_count/1000:.0f}K subs"
                                )
            except Exception as e:
                logger.warning(f"Failed to fetch your channel data: {e}")

        def format_num(n):
            if n >= 1_000_000:
                return f"{n/1_000_000:.1f}M"
            if n >= 1_000:
                return f"{n/1_000:.1f}K"
            return str(n)

        def get_winner(yours_val, theirs_val, higher_is_better=True):
            if yours_val == 0 or theirs_val == 0:
                return None
            if higher_is_better:
                return (
                    "you" if yours_val > theirs_val
                    else "competitor" if theirs_val > yours_val
                    else "tie"
                )
            return (
                "you" if yours_val < theirs_val
                else "competitor" if theirs_val < yours_val
                else "tie"
            )

        has_your_data = your_channel_details is not None
        metrics = [
            {
                "metric": "Subscribers",
                "yours": format_num(your_channel_details.subscriber_count) if has_your_data else "N/A",
                "competitor": format_num(channel_details.subscriber_count),
                "winner": get_winner(
                    your_channel_details.subscriber_count if has_your_data else 0,
                    channel_details.subscriber_count,
                ),
            },
            {
                "metric": "Avg Views",
                "yours": format_num(your_avg_views) if has_your_data else "N/A",
                "competitor": format_num(avg_views),
                "winner": get_winner(your_avg_views, avg_views),
            },
            {
                "metric": "Avg Likes",
                "yours": format_num(your_avg_likes) if has_your_data else "N/A",
                "competitor": format_num(avg_likes),
                "winner": get_winner(your_avg_likes, avg_likes),
            },
            {
                "metric": "Engagement Rate",
                "yours": f"{your_engagement_rate}%" if has_your_data else "N/A",
                "competitor": f"{engagement_rate}%",
                "winner": get_winner(your_engagement_rate, engagement_rate),
            },
            {
                "metric": "Avg Duration",
                "yours": f"{your_avg_duration} min" if has_your_data else "N/A",
                "competitor": f"{avg_duration} min",
                "winner": None,
            },
            {
                "metric": "Hit Rate",
                "yours": f"{your_hit_rate:.0f}%" if has_your_data else "N/A",
                "competitor": f"{hit_rate:.0f}%",
                "winner": get_winner(your_hit_rate, hit_rate),
            },
        ]

        strategy_diffs = [
            {
                "strategy": "Title Style",
                "description": "How titles are formatted",
                "your_approach": (
                    f"{your_question_titles:.0f}% questions, {your_number_titles:.0f}% with numbers"
                    if has_your_data else "N/A"
                ),
                "their_approach": (
                    f"{question_titles:.0f}% questions, {number_titles:.0f}% with numbers"
                ),
                "recommendation": (
                    "Test question titles for more engagement"
                    if question_titles > your_question_titles
                    else "Your title strategy is working"
                ),
            },
            {
                "strategy": "Video Length",
                "description": "Average content duration",
                "your_approach": f"{your_avg_duration} minutes average" if has_your_data else "N/A",
                "their_approach": f"{avg_duration} minutes average",
                "recommendation": (
                    f"Consider testing {avg_duration} min videos"
                    if abs(avg_duration - your_avg_duration) > 5
                    else "Similar video lengths"
                ),
            },
            {
                "strategy": "Topic Focus",
                "description": "Main content themes",
                "your_approach": ", ".join(your_topics[:3]) if your_topics else "N/A",
                "their_approach": ", ".join(common_topics) if common_topics else "Varied",
                "recommendation": (
                    f"Topics they cover that you don't: "
                    f"{', '.join([t for t in common_topics[:3] if t not in your_topics])}"
                    if your_topics
                    else f"Key topics: {', '.join(common_topics[:3])}"
                ),
            },
        ]

        opportunities: list[dict] = []
        if hit_rate > 20:
            opportunities.append({
                "opportunity": "High Hit Rate Strategy",
                "description": f"They achieve {hit_rate:.0f}% hit rate",
                "action_item": "Study their top performing video patterns",
            })
        if top_video:
            opportunities.append({
                "opportunity": "Viral Content Pattern",
                "description": f"Top video: {top_video.title[:50]}...",
                "action_item": f"Analyze why this got {format_num(top_video.view_count)} views",
            })
        if question_titles > 30:
            opportunities.append({
                "opportunity": "Question Titles",
                "description": f"{question_titles:.0f}% of their titles are questions",
                "action_item": "Test question-based titles for your content",
            })

        strengths: list[str] = []
        if channel_details.subscriber_count > 1_000_000:
            strengths.append(
                f"Large audience: {format_num(channel_details.subscriber_count)} subscribers"
            )
        if engagement_rate > 4:
            strengths.append(f"High engagement: {engagement_rate}% like rate")
        if hit_rate > 25:
            strengths.append(f"Consistent hits: {hit_rate:.0f}% of videos overperform")
        if avg_views > 100_000:
            strengths.append(f"Strong viewership: {format_num(avg_views)} avg views")
        if len(video_details) >= 20:
            strengths.append(f"Active channel: {len(video_details)} recent videos analyzed")

        return {
            "competitor": {
                "name": channel_details.channel_name,
                "channel_id": channel_details.channel_id,
                "subscribers": channel_details.subscriber_count,
                "total_views": channel_details.total_views,
                "avg_views": avg_views,
            },
            "metrics": metrics,
            "strategy_differences": strategy_diffs,
            "opportunities": opportunities,
            "competitor_strengths": strengths,
            "your_advantages": your_advantages,
            "your_channel": (
                {
                    "name": your_channel_details.channel_name,
                    "channel_id": your_channel_details.channel_id,
                    "subscribers": your_channel_details.subscriber_count,
                }
                if your_channel_details else None
            ),
        }

    except Exception as e:
        logger.error(f"Competitor analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
