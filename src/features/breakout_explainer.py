"""Breakout explainer (plan 8.7) — "why is this winning + your version".

Turns a radar item from *what's* breaking out into *what to do about it*: a
grounded, structured explanation of why a video is taking off, plus a concrete
"your version of this angle" a creator could make to ride the same wave.

Grounding is the point (Shorts-Cast: structured evidence helps, raw web snippets
HURT). The LLM only sees evidence we measured — the breakout signal (how far it's
outpacing its own channel), the topic it's riding and how crowded that topic is,
its packaging (title), niche, and the early comment reaction — never the open
web. The single-shot version of the agentic strategist.
"""
from __future__ import annotations

import math
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

_CAT_NAMES = {
    "1": "Film", "2": "Autos", "10": "Music", "15": "Pets", "17": "Sports",
    "19": "Travel", "20": "Gaming", "22": "People & Blogs", "23": "Comedy",
    "24": "Entertainment", "25": "News", "26": "Howto", "27": "Education",
    "28": "Science & Tech", "29": "Nonprofit",
}

_SYSTEM = (
    "You are a YouTube growth strategist with INTELLECTUAL HONESTY. You describe "
    "what's HAPPENING and what's UNUSUAL about a breaking-out video, grounded ONLY "
    "in the evidence given. Critical rule: you do NOT claim to know WHY it's "
    "winning. Packaging does not reliably predict performance, and a lot of "
    "breakout timing is the algorithm and luck you cannot see — so you describe "
    "what's DIFFERENT (topic, packaging, timing, audience reaction) and frame it "
    "as a HYPOTHESIS to test, never as the proven cause. Then give a concrete, "
    "do-it-this-week 'your version of this angle' the creator can run as an "
    "experiment. Be specific and tactical; if a topic is crowded, advise "
    "differentiation; if open, advise speed."
)


def gather_evidence(session, video_id: str) -> Optional[dict]:
    """Collect the structured, measured evidence for one breakout (no web)."""
    from sqlalchemy import select

    from src.database.models import TrackedVideo, VideoComment, VideoSnapshot
    from src.features.breakout_detector import (
        assess, calibrator_path, channel_baseline_logviews, BreakoutCalibrator,
    )
    from src.features.topic_saturation import annotate_with_topics

    tv = session.query(TrackedVideo).filter_by(video_id=video_id).one_or_none()
    if tv is None:
        return None

    # Latest snapshot (prefer an early checkpoint we have a calibrator for).
    snaps = session.execute(
        select(VideoSnapshot.checkpoint, VideoSnapshot.view_count,
               VideoSnapshot.youtube_category_id)
        .where(VideoSnapshot.video_id == video_id)
    ).all()
    if not snaps:
        return None
    order = {"6h": 0, "1h": 1, "24h": 2, "3d": 3, "7d": 4, "14d": 5, "30d": 6}
    cp, views, cat = sorted(snaps, key=lambda r: order.get(r[0], 9))[0]

    baseline = channel_baseline_logviews(session, tv.channel_id, cp, exclude_video_id=video_id)
    outpace = None
    breakout = {}
    if baseline is not None:
        a = assess(views, baseline, checkpoint=cp,
                   calibrator=BreakoutCalibrator.load(calibrator_path(cp)))
        outpace = round(math.exp(a.score), 1)  # ~how many× the channel norm
        breakout = {"probability": a.probability, "level": a.level, "checkpoint": cp}

    topic = annotate_with_topics(session, [{"video_id": video_id}])[0].get("topic")
    comments = [
        c[0] for c in session.execute(
            select(VideoComment.text).where(VideoComment.video_id == video_id)
            .order_by(VideoComment.like_count.desc()).limit(5)
        ).all()
    ]
    return {
        "title": tv.title,
        "niche": _CAT_NAMES.get(cat or "", "Other"),
        "views": int(views or 0),
        "outpaces_channel_x": outpace,
        "breakout": breakout,
        "topic": {"label": topic["label"], "uploads": topic["size"],
                  "channels": topic["channel_count"]} if topic else None,
        "top_comments": comments,
    }


def explain_breakout(
    session, video_id: str, user_idea: Optional[str] = None,
    user_id: Optional[int] = None, plan: str = "free",
) -> dict:
    """Evidence → LLM → {why, packaging_takeaway, your_angle}."""
    from src.features.llm_client import get_llm_client

    ev = gather_evidence(session, video_id)
    if ev is None:
        return {"error": "video_not_found_or_no_snapshots"}

    topic_line = (
        f"Topic it's riding: \"{ev['topic']['label']}\" — {ev['topic']['uploads']} uploads "
        f"across {ev['topic']['channels']} channels in 48h "
        f"({'CROWDED' if ev['topic']['channels'] >= 10 else 'open ground'})."
        if ev["topic"] else "Topic: not part of a detected cluster (possibly novel)."
    )
    outpace_line = (
        f"It's at ~{ev['outpaces_channel_x']}x its own channel's typical "
        f"{ev['breakout'].get('checkpoint','early')} views "
        f"(breakout probability {ev['breakout'].get('probability')})."
        if ev["outpaces_channel_x"] else "Outpace vs channel: not computable."
    )
    comments_line = (
        "Top early comments:\n- " + "\n- ".join(c[:160] for c in ev["top_comments"])
        if ev["top_comments"] else "No comments captured yet."
    )
    ctx = f"\nThe creator asking is in this space: {user_idea}" if user_idea else ""

    user_prompt = f"""A YouTube video is breaking out. Evidence (all measured, no web):
Title: "{ev['title']}"
Niche: {ev['niche']} · {ev['views']:,} views
{outpace_line}
{topic_line}
{comments_line}{ctx}

Respond with ONLY valid JSON:
{{
  "why": "2-3 sentences. FIRST state the fact (it's at Nx its channel's norm). THEN describe what's UNUSUAL about it vs typical videos (topic/packaging/timing/early reaction). Do NOT claim these CAUSED the breakout — describe what's different, not why.",
  "packaging_takeaway": "one sentence: what's worth NOTICING and testing here (framed as a hypothesis, not 'this is why it won')",
  "your_angle": "a concrete video idea THIS creator could make this week to TEST the same angle (differentiate if the topic is crowded; move fast if it's open)",
  "caveat": "one short sentence reminding that we can't prove what caused it — breakout timing is often the algorithm and luck; treat the differences as a hypothesis to test"
}}"""

    llm = get_llm_client().generate_json(
        _SYSTEM, user_prompt, max_tokens=600, temperature=0.6,
        user_id=user_id, plan=plan, feature="breakout_explainer",
    )
    if not llm:
        logger.warning("breakout_explainer.empty_llm")
        return {"evidence": ev, "error": "llm_unavailable"}
    return {
        "evidence": ev,
        "why": llm.get("why", ""),
        "packaging_takeaway": llm.get("packaging_takeaway", ""),
        "your_angle": llm.get("your_angle", ""),
        "caveat": llm.get(
            "caveat",
            "We can't prove what caused this — breakout timing is often the algorithm "
            "and luck. Treat the differences as a hypothesis to test, not the reason.",
        ),
    }
