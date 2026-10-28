"""Packaging rubric — scores a video's *packaging* (title first) against the
concrete, opinionated principles MrBeast preaches, not generic CTR heuristics.

Principles encoded:
  - **Length:** keep titles **< 50 chars** — above that they truncate to "..."
    on mobile and people don't know what they're clicking (deterministic check).
  - **Curiosity gap:** so interesting it would "haunt them if they don't click."
  - **Extremity:** the more extreme the (deliverable) claim, the higher the CTR.
  - **Clarity:** simple, instantly understandable while scrolling.
  - **Specificity:** concrete stakes / numbers, not vague.

This complements the ML reach predictor: the predictor says *whether* it will
break out; this rubric says *why* and how to fix it (the explainable layer).
LLM-judged via the shared budget-tracked client.
"""
from __future__ import annotations

import structlog

from src.features.llm_client import get_llm_client

logger = structlog.get_logger(__name__)

_SYSTEM = (
    "You are a YouTube packaging expert in the mold of MrBeast. You judge titles "
    "ONLY on click-worthiness, by these principles: a curiosity gap so strong it "
    "haunts the viewer if they don't click; an extreme but DELIVERABLE claim "
    "(more extreme = higher CTR); instant clarity while scrolling; and concrete "
    "specificity. You are blunt — most titles are weak. Score honestly."
)

_PRINCIPLES = ("curiosity_gap", "extremity", "clarity", "specificity")


def score_title(
    title: str,
    *,
    idea: str | None = None,
    user_id: int | None = None,
    plan: str = "free",
) -> dict:
    """Score a single title against the packaging rubric. Returns a dict with the
    deterministic length check, per-principle LLM scores, the biggest weakness,
    and stronger sub-50-char rewrites."""
    title = (title or "").strip()
    char_count = len(title)
    under_50 = char_count <= 50  # the hard mobile-truncation rule

    if not title:
        return {"error": "empty_title"}

    # Cache by title — identical titles re-analyzed constantly (one LLM call saved).
    # Only cache when there's no extra idea-context that changes the judgment.
    from src.cache.analyze import get_packaging_rubric_cached, set_packaging_rubric_cached
    if idea is None:
        cached = get_packaging_rubric_cached(title)
        if cached is not None:
            return cached

    ctx = f"\nVideo idea / context: {idea}" if idea else ""
    user_prompt = f"""Title to judge: "{title}" ({char_count} chars){ctx}

Score each principle 0-10 and respond with ONLY valid JSON:
{{
  "curiosity_gap": {{"score": <0-10>, "note": "..."}},
  "extremity": {{"score": <0-10>, "note": "..."}},
  "clarity": {{"score": <0-10>, "note": "..."}},
  "specificity": {{"score": <0-10>, "note": "..."}},
  "biggest_weakness": "the single most important thing holding this title back",
  "stronger_titles": ["3 rewrites, EACH under 50 characters, applying the principles"]
}}"""

    llm = get_llm_client().generate_json(
        _SYSTEM, user_prompt, max_tokens=900, temperature=0.5,
        user_id=user_id, plan=plan, feature="packaging_rubric",
    )

    out: dict = {
        "title": title,
        "char_count": char_count,
        "under_50_chars": under_50,
        "truncation_risk": not under_50,
    }
    if not llm:
        logger.warning("packaging_rubric.empty_llm")
        out["overall_score"] = None
        out["error"] = "llm_unavailable"
        return out

    # Overall = mean of the 4 principle scores (0-10 → 0-100), with a hard
    # truncation penalty so a >50-char title can never look "great".
    scores = []
    for p in _PRINCIPLES:
        try:
            scores.append(float(llm.get(p, {}).get("score", 0)))
        except (TypeError, ValueError):
            scores.append(0.0)
    overall = round(sum(scores) / len(scores) * 10) if scores else 0
    if not under_50:
        overall = max(0, overall - 15)

    out.update({
        "overall_score": overall,
        "principles": {p: llm.get(p) for p in _PRINCIPLES},
        "biggest_weakness": llm.get("biggest_weakness", ""),
        "stronger_titles": [t for t in (llm.get("stronger_titles") or []) if t][:3],
    })
    if idea is None:
        set_packaging_rubric_cached(title, out)
    return out
