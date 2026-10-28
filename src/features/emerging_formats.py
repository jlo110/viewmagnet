"""Emerging Formats — the live "Format Radar" (spec: docs/specs/emerging-formats.md).

Mines title/packaging *formats* (templates with placeholders) out of the rolling
window of breakout videos, then ranks them by momentum and openness. The live
counterpart to a static format archive: it surfaces patterns that are *rising and
not yet crowded*, which a static index structurally cannot do.

Scope (this module):
- Pull breakout corpus (reuses ``breakout_detector.detect_live_breakouts``).
- Match each title against a library of *generic, transferable* title formats
  (``FORMAT_PATTERNS``) — structural skeletons like "[topic] Explained in [N]
  Minutes" or "[X] vs [Y]", not topic-specific named events.
- Aggregate metrics (count, outlier, momentum, openness, reliability) + examples.
- Upsert ``EmergingFormat`` rows.

Why pattern-matching and not embedding-clustering: clustering by title similarity
groups *near-duplicate same-topic* videos (e.g. every World Cup match) and the
"shared scaffold" it extracts is a specific event name — a topic, not a format.
A real format is a reusable pattern whose placeholders are filled by *different*
topics across *different* channels. Matching against generic skeletons surfaces
exactly that and structurally can't produce a one-event cluster.

Honesty guardrails: formats below MIN_OCCURRENCES / MIN_CHANNELS are dropped, the
outlier is always relative to the video's *own channel* (never raw views), and
examples are spread across distinct channels so one hot event can't fill a card.
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from statistics import median
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# Tuning knobs (kept module-level so tests + the job share them).
WINDOW_DAYS = 45
MIN_OCCURRENCES = 4          # a format needs at least this many videos (4/3 while
MIN_CHANNELS = 3             # the English corpus is thin — surfaces more formats)
ANCHOR_DF = 0.5              # token kept as scaffold if in >= this share of titles
MAX_EXAMPLES = 5
RECENT_DAYS = 7              # momentum numerator window
PRIOR_DAYS = 14             # momentum denominator window (the 7..21d span)

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+|[^\sA-Za-z0-9]")


# ---------------------------------------------------------------------------
# Template induction (pure, unit-testable — no DB, no model)
# ---------------------------------------------------------------------------
def _tokenize(title: str) -> list[str]:
    return _TOKEN_RE.findall(title.strip())


def induce_template(titles: list[str]) -> str:
    """Collapse a cluster of similar titles into one template skeleton.

    Tokens shared by >= ANCHOR_DF of the cluster are kept verbatim (the fixed
    scaffold); runs of variable tokens become a single ``[...]`` placeholder.
    The most representative (longest) member is used as the walk template so the
    word order is natural. Cheap and deterministic — the MVP stand-in for an LLM
    naming pass.

    >>> induce_template(["Love Explained in 9 Minutes",
    ...                   "Relationship Explained in 12 Minutes"])
    '[...] Explained in [...] Minutes'
    """
    if not titles:
        return ""
    toks = [_tokenize(t) for t in titles]
    n = len(toks)
    df: Counter[str] = Counter()
    for tk in toks:
        for w in set(t.lower() for t in tk):
            df[w] += 1
    # Only real words (ASCII letters, 2+ chars) can be scaffold anchors — never
    # punctuation, emoji, numbers, hashtags, or non-Latin script. Everything else
    # collapses into a [...] placeholder, so symbol/foreign noise can't become a
    # "format".
    def is_word(t: str) -> bool:
        return len(t) >= 2 and t.isascii() and t.isalpha()

    anchors = {w for w, c in df.items() if c >= max(2, math.ceil(ANCHOR_DF * n)) and is_word(w)}

    walk = max(toks, key=len)  # longest title = richest scaffold
    out: list[str] = []
    in_gap = False
    for tok in walk:
        if tok.lower() in anchors:
            out.append(tok)
            in_gap = False
        elif not in_gap:
            out.append("[...]")
            in_gap = True
    # tidy spacing around punctuation
    template = " ".join(out)
    template = re.sub(r"\s+([,.:;!?])", r"\1", template)
    template = re.sub(r"(\[\.\.\.\])(\s+\1)+", r"\1", template)  # collapse adjacent placeholders
    return template.strip()


def slugify(template: str) -> str:
    s = template.lower().replace("[...]", "x")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:120] or "format"


def classify_psychology(template: str) -> str:
    """Lightweight heuristic packaging-type label (MVP; LLM upgrade later)."""
    t = template.lower()
    if "explained" in t or "minutes" in t or "how to" in t:
        return "Utility Promise"
    if "truth" in t or "real reason" in t or "nobody" in t or "no one" in t:
        return "Curiosity Gap"
    if re.search(r"\b(most|best|worst|biggest|scariest)\b", t):
        return "Shock & Extreme"
    if re.search(r"\b(facts|things|reasons|ways|tips)\b", t):
        return "Listicle"
    if re.search(r"\b(i|my|we)\b", t):
        return "Personal Confession"
    return "Pattern"


def _openness(unique_channels: int) -> str:
    if unique_channels < 6:
        return "open"
    if unique_channels < 12:
        return "warming"
    return "crowded"


def _reliability(count: int, unique_channels: int) -> str:
    if count >= 15 and unique_channels >= 8:
        return "high"
    if count >= MIN_OCCURRENCES and unique_channels >= MIN_CHANNELS:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# The format library — generic, transferable title skeletons
# ---------------------------------------------------------------------------
# Each entry: (key, display template, psychology, regex). A title is assigned to
# the FIRST pattern it matches, so order from specific -> generic. These are the
# *reusable* patterns a creator can borrow into any topic — never named events.
FORMAT_PATTERNS: list[tuple[str, str, str, str]] = [
    ("explained-in-minutes", "[topic] Explained in [N] Minutes", "Utility Promise", r"\bexplained\s+in\s+\d+\s*min"),
    ("ultimate-guide", "The Ultimate Guide to [topic]", "Utility Promise", r"\b(ultimate|complete|beginner'?s?)\s+guide\b|\bguide\s+to\b"),
    ("how-to", "How to [do something]", "Utility Promise", r"\bhow\s+to\b"),
    ("how-i", "How I [achieved something]", "Personal Confession", r"\bhow\s+i\b"),
    ("the-history-of", "The History of [subject]", "Utility Promise", r"\bthe\s+history\s+of\b"),
    ("explained", "[topic], Explained", "Utility Promise", r"\bexplained\b"),
    ("n-things", "[N] Things [about topic]", "Listicle", r"\b\d+\s+things\b"),
    ("n-reasons", "[N] Reasons [why]", "Listicle", r"\b\d+\s+reasons\b"),
    ("n-ways", "[N] Ways to [do something]", "Listicle", r"\b\d+\s+ways\s+to\b"),
    ("n-mistakes", "[N] [topic] Mistakes", "Listicle", r"\b\d+\s+\w+\s+mistakes\b"),
    ("n-tips", "[N] [topic] Tips", "Listicle", r"\b\d+\s+\w+\s+tips\b"),
    ("n-facts", "[N] Facts About [topic]", "Listicle", r"\b\d+\s+(\w+\s+){0,2}facts\b"),
    ("the-truth-about", "The Truth About [topic]", "Curiosity Gap", r"\bthe\s+truth\s+about\b"),
    ("the-real-reason", "The Real Reason [something]", "Curiosity Gap", r"\bthe\s+real\s+reason\b"),
    ("nobody-tells-you", "What Nobody Tells You About [topic]", "Curiosity Gap", r"\b(nobody|no\s+one)\b.{0,20}\b(tells|talks|knows)\b"),
    ("you-didnt-know", "[topic] You Didn't Know", "Curiosity Gap", r"\byou\s+(didn'?t|never)\s+know\b"),
    ("what-happens-when", "What Happens When [X]", "Curiosity Gap", r"\bwhat\s+happens\s+(when|if|to)\b"),
    ("the-problem-with", "The Problem With [topic]", "Curiosity Gap", r"\bthe\s+problem\s+with\b"),
    ("everything-wrong", "Everything Wrong With [topic]", "Shock & Extreme", r"\beverything\s+wrong\s+with\b"),
    ("rise-and-fall", "The Rise and Fall of [subject]", "Curiosity Gap", r"\brise\s+(and|&)\s+fall\b"),
    ("what-if", "What If [scenario]", "Curiosity Gap", r"^\s*what\s+if\b"),
    ("why", "Why [claim]", "Curiosity Gap", r"^\s*why\b"),
    ("i-tried", "I Tried [thing]", "Personal Confession", r"\bi\s+tried\b"),
    ("i-spent", "I Spent [time/amount] [doing X]", "Personal Confession", r"\bi\s+spent\b"),
    ("i-built", "I Built [thing]", "Personal Confession", r"\bi\s+built\b"),
    ("for-n-days", "[did X] for [N] Days", "Personal Confession", r"\bfor\s+\d+\s+(days|hours|weeks|months|years)\b"),
    ("day-in-the-life", "A Day in the Life of [someone]", "Personal Confession", r"\bday\s+in\s+(the|my)\s+life\b"),
    ("reacting-to", "Reacting to [thing]", "Personal Confession", r"\breact(ing|s)?\s+to\b"),
    ("x-vs-y", "[X] vs [Y]", "Comparison", r"\bvs\.?\b|\bversus\b"),
    ("tier-list", "[topic] Tier List", "Comparison", r"\btier\s+list\b"),
    ("ranked", "[topics] Ranked", "Comparison", r"\branked\b"),
    ("review", "[product] Review", "Comparison", r"\breview\b"),
    ("worlds-most", "The World's Most [superlative] [thing]", "Shock & Extreme", r"\bworld'?s\s+(most|best|biggest|largest|smallest|deadliest|rarest|expensive)\b"),
    ("stop-doing", "Stop [doing X]", "Utility Promise", r"^\s*stop\b"),
    ("challenge", "The [topic] Challenge", "Personal Confession", r"\bchallenge\b"),
]

_COMPILED_PATTERNS = [
    (key, tmpl, psych, re.compile(rx, re.IGNORECASE)) for key, tmpl, psych, rx in FORMAT_PATTERNS
]
FORMAT_SPEC_BY_KEY = {key: (key, tmpl, psych) for key, tmpl, psych, _ in _COMPILED_PATTERNS}


def _match_format(title: str) -> Optional[str]:
    """Return the key of the first generic format the title matches, or None."""
    for key, _tmpl, _psych, rx in _COMPILED_PATTERNS:
        if rx.search(title):
            return key
    return None


# ---------------------------------------------------------------------------
# LLM discovery — grow the library from titles the curated set didn't catch
# ---------------------------------------------------------------------------
# The curated 35 cover the common formats; this pass lets the LLM *propose* new
# generic skeletons from the leftover breakouts. The LLM only proposes a
# (template, regex) — every metric is still computed from real data by running
# that regex over the corpus, so nothing the model claims is trusted blindly.
LLM_DISCOVERY_MAX_TITLES = 150     # cap the prompt to the strongest leftovers
LLM_DISCOVERY_MAX_PATTERNS = 12    # cap how many new formats one run can add
LLM_DISCOVERY_MAX_DF = 0.5         # reject a regex that matches > this share (catch-all)


def _discovery_enabled() -> bool:
    raw = os.environ.get("EMERGING_FORMATS_LLM_DISCOVERY", "1")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def discover_formats_llm(
    unmatched_titles: list[str], all_titles: list[str]
) -> list[tuple[str, str, str, "re.Pattern"]]:
    """Ask the LLM for generic formats hiding in the un-matched breakout titles.

    Returns compiled ``(key, template, psychology, regex)`` tuples — already
    validated (compiles, has a placeholder, and matches a sane share of the
    corpus). Fails *closed*: any error / missing key / over-budget → ``[]``, so
    the radar always falls back to the curated library. Never raises.
    """
    if not _discovery_enabled():
        return []
    titles = unmatched_titles[:LLM_DISCOVERY_MAX_TITLES]
    if len(titles) < MIN_OCCURRENCES:
        return []
    system = (
        "You are a YouTube packaging analyst. From a list of high-performing video "
        "titles, extract RECURRING, GENERIC, TRANSFERABLE title formats — reusable "
        "skeletons a creator could borrow into ANY topic, like '[topic] Explained in "
        "[N] Minutes' or '[X] vs [Y]'. NEVER output a specific person, brand, team, "
        "event, place, or news story — those are topics, not formats. Only output a "
        "format if at least 4 of the given titles share it. Return JSON: "
        '{"formats":[{"template":"...with [placeholders]...","regex":"python regex '
        'matching the generic scaffold words, case-insensitive","psychology":"one of '
        "Utility Promise|Curiosity Gap|Listicle|Shock & Extreme|Personal Confession|"
        'Comparison"}]}. Keep regexes anchored on the GENERIC words (not the topic).'
    )
    user = "Titles:\n" + "\n".join(f"- {t}" for t in titles)
    try:
        from src.features.llm_client import get_llm_client

        data = get_llm_client().generate_json(
            system, user, max_tokens=1200, temperature=0.2,
            feature="emerging_formats_discovery", plan="free",
        )
    except Exception as e:  # never let discovery break the job
        logger.warning("formats.llm_discovery_failed", error=str(e)[:120])
        return []

    raw = data.get("formats") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []

    out: list[tuple[str, str, str, "re.Pattern"]] = []
    seen = set(FORMAT_SPEC_BY_KEY)
    n_all = max(1, len(all_titles))
    for item in raw:
        if not isinstance(item, dict):
            continue
        template = str(item.get("template") or "").strip()
        rx_src = str(item.get("regex") or "").strip()
        psych = (str(item.get("psychology") or "Pattern").strip() or "Pattern")[:40]
        # Must be a real skeleton (has a placeholder) with a usable regex.
        if not template or "[" not in template or not rx_src:
            continue
        key = "llm-" + slugify(template)
        if key in seen:
            continue
        try:
            rx = re.compile(rx_src, re.IGNORECASE)
        except re.error:
            continue
        # Breadth sanity: reject catch-alls and one-offs before they ever rank.
        hits = sum(1 for t in all_titles if rx.search(t))
        if hits < MIN_OCCURRENCES or hits > LLM_DISCOVERY_MAX_DF * n_all:
            continue
        seen.add(key)
        out.append((key, template[:200], psych, rx))
        if len(out) >= LLM_DISCOVERY_MAX_PATTERNS:
            break
    if out:
        logger.info("formats.llm_discovered", patterns=len(out), candidates=len(titles))
    return out


# ---------------------------------------------------------------------------
# Corpus + format aggregation (touches DB)
# ---------------------------------------------------------------------------
def _build_corpus(session) -> list[dict]:
    """Breakout videos in the trailing window, enriched with published_at.

    Reuses the live-breakout detector over a wide window; then joins published_at
    (needed for momentum). Each row: video_id, channel_id, title, views, outlier,
    published_at, niche.
    """
    from sqlalchemy import func, select

    from src.database.models import TrackedVideo, VideoSnapshot
    from src.features.breakout_detector import detect_live_breakouts
    from src.features.language import is_probably_english

    rows = detect_live_breakouts(
        session,
        checkpoint="6h",
        min_probability=0.0,        # we re-rank by outlier ourselves; take the breadth
        max_age_hours=WINDOW_DAYS * 24,
        limit=4000,
        min_views=1000.0,
        min_channel_videos=3,
    )
    if not rows:
        return []
    vids = [r["video_id"] for r in rows]
    pub = dict(
        session.execute(
            select(TrackedVideo.video_id, TrackedVideo.published_at).where(TrackedVideo.video_id.in_(vids))
        ).all()
    )
    cat = dict(
        session.execute(
            select(VideoSnapshot.video_id, VideoSnapshot.youtube_category_id)
            .where(VideoSnapshot.video_id.in_(vids), VideoSnapshot.youtube_category_id.isnot(None))
        ).all()
    )
    # default_audio_language per video — the strong English signal (en* keeps,
    # any other language drops; the title script heuristic is only the fallback).
    lang = dict(
        session.execute(
            select(VideoSnapshot.video_id, func.max(VideoSnapshot.default_audio_language))
            .where(VideoSnapshot.video_id.in_(vids))
            .group_by(VideoSnapshot.video_id)
        ).all()
    )
    corpus: list[dict] = []
    for r in rows:
        title = r.get("title") or ""
        if not is_probably_english(title, lang.get(r["video_id"])):
            continue
        corpus.append({
            "video_id": r["video_id"],
            "channel_id": r["channel_id"],
            "title": title,
            "views": float(r["views"]),
            "outlier": round(math.exp(r["score"]), 2),  # vs the channel's own norm
            "published_at": pub.get(r["video_id"]),
            "niche": cat.get(r["video_id"]),
        })
    return corpus


def _aggregate_format(spec: tuple[str, str, str], members: list[dict], now: datetime) -> Optional[dict]:
    """Turn all breakout videos matching one generic format into an EmergingFormat
    dict, or None if too thin to be trustworthy. ``spec`` is (key, template,
    psychology) — works the same for curated and LLM-discovered patterns."""
    key, template, psychology = spec
    channels = {m["channel_id"] for m in members}
    if len(members) < MIN_OCCURRENCES or len(channels) < MIN_CHANNELS:
        return None

    outliers = [m["outlier"] for m in members]
    # momentum: recent occurrences vs the prior window
    recent_cut = now - timedelta(days=RECENT_DAYS)
    prior_cut = now - timedelta(days=RECENT_DAYS + PRIOR_DAYS)
    recent = sum(1 for m in members if m["published_at"] and m["published_at"] >= recent_cut)
    prior = sum(1 for m in members if m["published_at"] and prior_cut <= m["published_at"] < recent_cut)
    momentum = round(recent / max(1.0, prior * RECENT_DAYS / PRIOR_DAYS), 2)

    # Examples spread across distinct channels — one hot event (a single
    # tournament, one viral story) must not fill every slot. A format is shown
    # by the *variety* of topics using it, so each example is a different creator.
    examples: list[dict] = []
    seen_ch: set = set()
    for m in sorted(members, key=lambda x: x["outlier"], reverse=True):
        if m["channel_id"] in seen_ch:
            continue
        seen_ch.add(m["channel_id"])
        examples.append({
            "video_id": m["video_id"],
            "title": m["title"],
            "outlier": m["outlier"],
            "views": int(m["views"]),
            "niche": m["niche"],
            "age_days": (now - m["published_at"]).days if m["published_at"] else None,
        })
        if len(examples) >= MAX_EXAMPLES:
            break
    niche_counts = Counter(m["niche"] for m in members if m["niche"])
    modal_niche = niche_counts.most_common(1)[0][0] if niche_counts else None

    return {
        "slug": key,
        "template": template[:300],
        "name": template[:200],
        "psychology_type": psychology,
        "niche": modal_niche,
        "count": len(members),
        "avg_outlier": round(sum(outliers) / len(outliers), 2),
        "median_outlier": round(median(outliers), 2),
        "avg_views": round(sum(m["views"] for m in members) / len(members), 0),
        "momentum": momentum,
        "unique_channels": len(channels),
        "openness": _openness(len(channels)),
        "reliability": _reliability(len(members), len(channels)),
        "examples": examples,
        "window_days": WINDOW_DAYS,
    }


def compute_emerging_formats(session) -> dict:
    """Recompute the Format Radar from the live breakout window. Upserts rows.

    Groups breakout titles by the *generic* format they match (``FORMAT_PATTERNS``)
    rather than clustering by topic similarity, so each row is a transferable
    pattern ("[X] vs [Y]", "[topic] Explained in [N] Minutes") whose examples span
    many different topics — not a cluster of near-duplicate videos about one event.
    """
    from src.database.models import EmergingFormat

    now = datetime.utcnow()
    corpus = _build_corpus(session)
    if len(corpus) < MIN_OCCURRENCES:
        logger.info("formats.skip_thin_corpus", n=len(corpus))
        return {"formats": 0, "corpus": len(corpus)}

    # Pass 1: assign each title to the curated format it matches (first wins).
    groups: dict[str, list[dict]] = {}
    unmatched: list[dict] = []
    for row in corpus:
        key = _match_format(row["title"])
        if key:
            groups.setdefault(key, []).append(row)
        else:
            unmatched.append(row)

    # Pass 2: let the LLM mine new generic formats out of what the curated set
    # missed, then match the leftovers against those discovered skeletons. Specs
    # for both sources share one map so aggregation is identical.
    spec_by_key: dict[str, tuple[str, str, str]] = dict(FORMAT_SPEC_BY_KEY)
    discovered = discover_formats_llm(
        [r["title"] for r in unmatched], [r["title"] for r in corpus]
    )
    if discovered:
        for key, tmpl, psych, _rx in discovered:
            spec_by_key[key] = (key, tmpl, psych)
        for row in unmatched:
            for key, _tmpl, _psych, rx in discovered:
                if rx.search(row["title"]):
                    groups.setdefault(key, []).append(row)
                    break
    matched = sum(len(m) for m in groups.values())

    formats = [
        f for f in (_aggregate_format(spec_by_key[k], m, now) for k, m in groups.items()) if f
    ]

    # Replace the prior batch wholesale (simplest correct upsert for a periodic recompute).
    session.query(EmergingFormat).delete()
    for f in formats:
        session.add(EmergingFormat(
            slug=f["slug"], template=f["template"], name=f["name"],
            psychology_type=f["psychology_type"], niche=f["niche"], count=f["count"],
            avg_outlier=f["avg_outlier"], median_outlier=f["median_outlier"],
            avg_views=f["avg_views"], momentum=f["momentum"],
            unique_channels=f["unique_channels"], openness=f["openness"],
            reliability=f["reliability"], examples=json.dumps(f["examples"]),
            window_days=f["window_days"], computed_at=now,
        ))
    session.commit()
    logger.info(
        "formats.complete", formats=len(formats), corpus=len(corpus),
        matched=matched, discovered=len(discovered),
    )
    return {
        "formats": len(formats), "corpus": len(corpus),
        "matched": matched, "discovered": len(discovered),
    }


# ---------------------------------------------------------------------------
# Read path (API)
# ---------------------------------------------------------------------------
def get_formats(
    session,
    niche: Optional[str] = None,
    sort: str = "momentum",
    openness: Optional[str] = None,
    min_reliability: Optional[str] = None,
    limit: int = 40,
) -> dict:
    """Read the latest Format Radar batch for the API."""
    from src.database.models import EmergingFormat

    q = session.query(EmergingFormat)
    if niche:
        q = q.filter(EmergingFormat.niche == niche)
    if openness:
        q = q.filter(EmergingFormat.openness == openness)
    if min_reliability:
        tiers = {"low": 0, "medium": 1, "high": 2}
        floor = tiers.get(min_reliability, 0)
        allowed = [k for k, v in tiers.items() if v >= floor]
        q = q.filter(EmergingFormat.reliability.in_(allowed))

    sort_col = {
        "momentum": EmergingFormat.momentum,
        "outlier": EmergingFormat.avg_outlier,
        "views": EmergingFormat.avg_views,
        "count": EmergingFormat.count,
    }.get(sort, EmergingFormat.momentum)
    rows = q.order_by(sort_col.desc()).limit(limit).all()

    def card(f) -> dict:
        return {
            "slug": f.slug, "template": f.template, "name": f.name,
            "psychology_type": f.psychology_type, "niche": f.niche,
            "count": f.count, "avg_outlier": f.avg_outlier,
            "median_outlier": f.median_outlier, "avg_views": f.avg_views,
            "momentum": f.momentum, "unique_channels": f.unique_channels,
            "openness": f.openness, "reliability": f.reliability,
            "examples": json.loads(f.examples) if f.examples else [],
        }

    updated = max((f.computed_at for f in rows), default=None)
    return {
        "count": len(rows),
        "updated_at": (updated.isoformat() + "Z") if updated else None,
        "formats": [card(f) for f in rows],
    }
