"""Topic-saturation index from our own collection (Phase 8.2).

Shorts-Cast (arXiv 2605.18653) showed popularity depends on whether a topic
currently commands attention and how *saturated* the content pool is — and that
unstructured web context hurts. The cheapest structured version needs no web
and no API quota: we already watch ~4.8k channels, so the recent uploads ARE
the content pool. Embed their titles, cluster, and the cluster sizes/velocity
are the saturation signal.

Three uses for one index: (a) model feature for reach/breakout, (b) a timing
advisor ("12 tracked channels posted this topic in 48h — saturated; or rising
with low supply — post now"), (c) topic assignment for tracked-set
stratification (7.6).

Clustering is greedy leader clustering on cosine similarity — O(n·k), no
fitted state, deterministic given order (we order by views desc so cluster
leaders are the biggest videos, which also makes them good labels).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List, Optional, Sequence

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Cosine similarity for two titles to share a topic. MiniLM embeddings of
# news/video titles: ~0.55+ is "same story/topic", ~0.4 is "same broad theme".
DEFAULT_SIMILARITY = 0.55
DEFAULT_WINDOW_HOURS = 48
MAX_VIDEOS = 5000

_st_model = None


def _model():
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer

        _st_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _st_model


def embed_titles(titles: Sequence[str]) -> np.ndarray:
    """L2-normalized MiniLM embeddings (so dot product = cosine sim)."""
    emb = _model().encode(list(titles), batch_size=64, show_progress_bar=False)
    emb = np.asarray(emb, dtype=np.float32)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    return emb / np.clip(norms, 1e-9, None)


def cluster_embeddings(
    embeddings: np.ndarray, similarity: float = DEFAULT_SIMILARITY
) -> List[int]:
    """Greedy leader clustering: assign each row to the first leader with
    cosine >= ``similarity``, else it becomes a new leader.

    Pure numpy, no DB/model — unit-testable. Returns a cluster id per row.
    Rows should be pre-sorted by importance (views desc) so leaders = the
    biggest video on each topic.
    """
    n = len(embeddings)
    labels = [-1] * n
    leaders: List[int] = []  # row indices of cluster leaders
    for i in range(n):
        if leaders:
            sims = embeddings[leaders] @ embeddings[i]
            best = int(np.argmax(sims))
            if sims[best] >= similarity:
                labels[i] = best
                continue
        labels[i] = len(leaders)
        leaders.append(i)
    return labels


def summarize_clusters(
    labels: Sequence[int],
    titles: Sequence[str],
    views: Sequence[float],
    channel_ids: Sequence[str],
    video_ids: Sequence[str],
    min_size: int = 3,
    top_n: int = 50,
) -> List[dict]:
    """Aggregate per-cluster stats; only clusters with >= ``min_size`` uploads
    are 'topics' (a 1-video cluster is just a video). Pure — unit-testable."""
    agg: dict = {}
    for lbl, title, v, ch, vid in zip(labels, titles, views, channel_ids, video_ids):
        c = agg.setdefault(lbl, {"titles": [], "views": 0.0, "channels": set(), "video_ids": []})
        if len(c["titles"]) < 5:
            c["titles"].append(title)
        c["views"] += float(v or 0)
        c["channels"].add(ch)
        c["video_ids"].append(vid)

    out = []
    for lbl, c in agg.items():
        size = len(c["video_ids"])
        if size < min_size:
            continue
        out.append(
            {
                "label": c["titles"][0],  # leader = biggest video's title
                "size": size,
                "total_views": int(c["views"]),
                "channel_count": len(c["channels"]),
                "example_titles": c["titles"],
                "video_ids": c["video_ids"],
            }
        )
    out.sort(key=lambda r: r["size"], reverse=True)
    return out[:top_n]


def build_topic_clusters(
    session,
    window_hours: float = DEFAULT_WINDOW_HOURS,
    similarity: float = DEFAULT_SIMILARITY,
    min_size: int = 3,
) -> dict:
    """Compute and persist the current topic clusters from recent uploads.

    Loads tracked videos published in the window (title from the freshest
    snapshot, ordered by views desc), embeds + clusters, stores one
    ``TopicClusterRun`` batch. Reads are served from the latest batch.
    """
    from sqlalchemy import func, select

    from src.database.models import TopicCluster, TrackedVideo, VideoSnapshot

    now = datetime.utcnow()
    cutoff = now - timedelta(hours=window_hours)

    # Freshest snapshot per recent video (views + title), via max(id) per video.
    latest = (
        select(VideoSnapshot.video_id, func.max(VideoSnapshot.id).label("mid"))
        .group_by(VideoSnapshot.video_id)
        .subquery()
    )
    rows = session.execute(
        select(
            VideoSnapshot.video_id,
            VideoSnapshot.title,
            VideoSnapshot.view_count,
            TrackedVideo.channel_id,
        )
        .join(latest, VideoSnapshot.id == latest.c.mid)
        .join(TrackedVideo, TrackedVideo.video_id == VideoSnapshot.video_id)
        .where(TrackedVideo.published_at >= cutoff, VideoSnapshot.title.isnot(None))
        .order_by(VideoSnapshot.view_count.desc())
        .limit(MAX_VIDEOS)
    ).all()

    if len(rows) < min_size:
        logger.info("topics.insufficient_data", videos=len(rows))
        return {"videos": len(rows), "clusters": 0}

    video_ids = [r[0] for r in rows]
    titles = [r[1] or "" for r in rows]
    views = [r[2] or 0 for r in rows]
    channels = [r[3] for r in rows]

    emb = embed_titles(titles)
    labels = cluster_embeddings(emb, similarity=similarity)
    clusters = summarize_clusters(labels, titles, views, channels, video_ids, min_size=min_size)

    computed_at = now
    for c in clusters:
        session.add(
            TopicCluster(
                computed_at=computed_at,
                window_hours=window_hours,
                label=c["label"][:500],
                size=c["size"],
                total_views=c["total_views"],
                channel_count=c["channel_count"],
                example_titles=json.dumps(c["example_titles"]),
                video_ids=json.dumps(c["video_ids"]),
            )
        )
    session.commit()
    return {"videos": len(rows), "clusters": len(clusters)}


def match_topic_batches(current: List[dict], previous: List[dict]) -> List[dict]:
    """Annotate current clusters with their previous-batch counterpart.

    Labels drift between batches (the leader video changes), so matching is by
    shared ``video_ids`` — clusters with overlapping membership are the same
    topic. Adds ``prev_size``/``delta``/``trend`` (new|rising|stable|falling)
    to each current cluster. Pure — unit-testable.
    """
    prev_sets = [(set(p.get("video_ids") or []), p) for p in previous]
    out = []
    for c in current:
        cur_vids = set(c.get("video_ids") or [])
        best, best_overlap = None, 0
        for pset, p in prev_sets:
            overlap = len(cur_vids & pset)
            if overlap > best_overlap:
                best, best_overlap = p, overlap
        cc = dict(c)
        if best is None:
            cc.update({"prev_size": 0, "delta": c["size"], "trend": "new"})
        else:
            delta = c["size"] - best["size"]
            trend = "rising" if delta > 2 else ("falling" if delta < -2 else "stable")
            cc.update({"prev_size": best["size"], "delta": delta, "trend": trend})
        out.append(cc)
    return out


def get_topic_velocity(session, limit: int = 30, min_channels: int = 2) -> Optional[dict]:
    """Compare the two most recent batches → rising / new / falling topics.

    The timing-advisor signal: "rising with low supply — post now" vs
    "saturated/falling — differentiate or wait". None until 2 batches exist.
    """
    from sqlalchemy import select

    from src.database.models import TopicCluster

    stamps = [
        r[0]
        for r in session.execute(
            select(TopicCluster.computed_at)
            .distinct()
            .order_by(TopicCluster.computed_at.desc())
            .limit(2)
        ).all()
    ]
    if len(stamps) < 2:
        return None

    def _load(ts):
        rows = (
            session.query(TopicCluster)
            .filter(TopicCluster.computed_at == ts, TopicCluster.channel_count >= min_channels)
            .all()
        )
        return [
            {
                "label": r.label,
                "size": r.size,
                "channel_count": r.channel_count,
                "total_views": r.total_views,
                "video_ids": json.loads(r.video_ids or "[]"),
            }
            for r in rows
        ]

    matched = match_topic_batches(_load(stamps[0]), _load(stamps[1]))
    for m in matched:
        m.pop("video_ids", None)
    matched.sort(key=lambda r: r["delta"], reverse=True)
    return {
        "current_batch": stamps[0].isoformat(),
        "previous_batch": stamps[1].isoformat(),
        "topics": matched[:limit],
    }


def annotate_with_topics(session, items: List[dict]) -> List[dict]:
    """Attach each item's topic (label/size/channel_count) from the latest batch.

    ``items`` need a ``video_id``; videos not in any stored cluster get
    ``topic: None``. Turns the breakout feed into "what's breaking out AND how
    crowded that topic already is" — high saturation means move fast or
    differentiate; low means open ground.
    """
    from sqlalchemy import select

    from src.database.models import TopicCluster

    latest_ts = session.execute(
        select(TopicCluster.computed_at).order_by(TopicCluster.computed_at.desc()).limit(1)
    ).scalar_one_or_none()
    if latest_ts is None:
        for it in items:
            it["topic"] = None
        return items

    vid_to_topic: dict = {}
    for row in session.query(TopicCluster).filter(TopicCluster.computed_at == latest_ts):
        info = {
            "label": row.label,
            "size": row.size,
            "channel_count": row.channel_count,
        }
        for vid in json.loads(row.video_ids or "[]"):
            vid_to_topic[vid] = info

    for it in items:
        it["topic"] = vid_to_topic.get(it.get("video_id"))
    return items


def get_latest_topics(session, limit: int = 50, min_channels: int = 2) -> Optional[dict]:
    """Read the most recent cluster batch (None if never computed).

    ``min_channels`` filters out single-channel "topics" — 50 uploads from one
    mass-uploading channel is that channel's behavior, not topic saturation
    (observed live: an Armenian news channel produced a 56-video cluster).
    """
    from sqlalchemy import select

    from src.database.models import TopicCluster

    latest_ts = session.execute(
        select(TopicCluster.computed_at).order_by(TopicCluster.computed_at.desc()).limit(1)
    ).scalar_one_or_none()
    if latest_ts is None:
        return None
    rows = (
        session.query(TopicCluster)
        .filter(
            TopicCluster.computed_at == latest_ts,
            TopicCluster.channel_count >= min_channels,
        )
        .order_by(TopicCluster.size.desc())
        .limit(limit)
        .all()
    )
    return {
        "computed_at": latest_ts.isoformat(),
        "window_hours": rows[0].window_hours if rows else None,
        "topics": [
            {
                "label": r.label,
                "size": r.size,
                "total_views": r.total_views,
                "channel_count": r.channel_count,
                "example_titles": json.loads(r.example_titles or "[]"),
            }
            for r in rows
        ],
    }


# --- Topic Momentum (Phase 2.1): per-topic breakout density over time -------
# Saturation (above) = upload supply. Momentum = how often a topic's videos are
# actually breaking out *now* (audience demand), and whether that rate is
# rising/peaking/fading. The honest market-timing lever — descriptive, not a
# packaging predictor.

MOMENTUM_DELTA = 0.05   # breakout-rate change that counts as rising/fading
MOMENTUM_PEAK_RATE = 0.4  # a flat-but-high rate is "peaking", not "steady"


def classify_momentum(rate: float, prev_rate: Optional[float]) -> str:
    """new | rising | peaking | fading | steady from a topic's breakout rate.

    Pure — unit-testable. ``prev_rate`` None means the topic is new to the
    momentum series (no prior snapshot to compare against)."""
    if prev_rate is None:
        return "new"
    delta = rate - prev_rate
    if delta >= MOMENTUM_DELTA:
        return "rising"
    if delta <= -MOMENTUM_DELTA:
        return "fading"
    if rate >= MOMENTUM_PEAK_RATE:
        return "peaking"
    return "steady"


def _match_prev_rate(video_ids: List[str], prev_rows: List[dict]) -> Optional[float]:
    """Prior breakout_rate for the topic best-matching ``video_ids`` (by overlap).

    Topics are matched across snapshots by shared membership (labels drift), same
    as ``match_topic_batches``. None if no prior topic shares any videos."""
    cur = set(video_ids or [])
    best, best_overlap = None, 0
    for p in prev_rows:
        overlap = len(cur & set(p.get("video_ids") or []))
        if overlap > best_overlap:
            best, best_overlap = p, overlap
    return best["breakout_rate"] if best else None


def compute_topic_momentum(
    session,
    breakout_min_probability: float = 0.7,
    breakout_checkpoint: str = "6h",
    window_hours: float = DEFAULT_WINDOW_HOURS,
) -> dict:
    """For the latest topic-cluster batch, compute each topic's breakout density
    and trend, and persist one ``TopicMomentum`` snapshot.

    Reuses the validated detector: a topic's breakout_rate = share of its videos
    that are breaking out right now. Trend is vs the previous momentum snapshot
    (matched by membership overlap). Zero API quota."""
    from sqlalchemy import select

    from src.database.models import TopicCluster, TopicMomentum
    from src.features.breakout_detector import detect_live_breakouts

    latest_ts = session.execute(
        select(TopicCluster.computed_at).order_by(TopicCluster.computed_at.desc()).limit(1)
    ).scalar_one_or_none()
    if latest_ts is None:
        return {"topics": 0, "breaking_videos": 0}

    clusters = session.query(TopicCluster).filter(TopicCluster.computed_at == latest_ts).all()
    if not clusters:
        return {"topics": 0, "breaking_videos": 0}

    breaking = detect_live_breakouts(
        session, checkpoint=breakout_checkpoint, min_probability=breakout_min_probability,
        max_age_hours=float(window_hours), min_views=500.0, limit=5000,
    )
    breaking_ids = {it["video_id"] for it in breaking}

    # Previous momentum snapshot (for the trend comparison).
    prev_ts = session.execute(
        select(TopicMomentum.computed_at).order_by(TopicMomentum.computed_at.desc()).limit(1)
    ).scalar_one_or_none()
    prev_rows = []
    if prev_ts is not None:
        prev_rows = [
            {"breakout_rate": r.breakout_rate, "video_ids": json.loads(r.video_ids or "[]")}
            for r in session.query(TopicMomentum).filter(TopicMomentum.computed_at == prev_ts).all()
        ]

    now = datetime.utcnow()
    written = 0
    for c in clusters:
        vids = json.loads(c.video_ids or "[]")
        if not vids:
            continue
        bc = sum(1 for v in vids if v in breaking_ids)
        rate = bc / len(vids)
        prev_rate = _match_prev_rate(vids, prev_rows)
        session.add(TopicMomentum(
            computed_at=now,
            window_hours=c.window_hours,
            label=c.label[:500],
            topic_size=c.size,
            breakout_count=bc,
            breakout_rate=round(rate, 4),
            total_views=c.total_views,
            channel_count=c.channel_count,
            trend=classify_momentum(rate, prev_rate),
            prev_breakout_rate=prev_rate,
            example_titles=c.example_titles,
            video_ids=c.video_ids,
        ))
        written += 1
    session.commit()
    logger.info("topic_momentum.computed", topics=written, breaking=len(breaking_ids))
    return {"topics": written, "breaking_videos": len(breaking_ids)}


def get_topic_momentum(session, limit: int = 30, min_channels: int = 2) -> Optional[dict]:
    """Read the latest momentum snapshot — topics ranked by breakout density.

    "Where audiences are rewarding content right now" — rising/low-supply topics
    are the post-now signal; fading ones are cooling. None until computed once."""
    from sqlalchemy import select

    from src.database.models import TopicMomentum

    latest_ts = session.execute(
        select(TopicMomentum.computed_at).order_by(TopicMomentum.computed_at.desc()).limit(1)
    ).scalar_one_or_none()
    if latest_ts is None:
        return None
    rows = (
        session.query(TopicMomentum)
        .filter(TopicMomentum.computed_at == latest_ts,
                TopicMomentum.channel_count >= min_channels)
        .order_by(TopicMomentum.breakout_rate.desc(), TopicMomentum.topic_size.desc())
        .limit(limit)
        .all()
    )
    return {
        "computed_at": latest_ts.isoformat(),
        "topics": [
            {
                "label": r.label,
                "topic_size": r.topic_size,
                "breakout_count": r.breakout_count,
                "breakout_rate": r.breakout_rate,
                "channel_count": r.channel_count,
                "total_views": r.total_views,
                "trend": r.trend,
                "prev_breakout_rate": r.prev_breakout_rate,
                "example_titles": json.loads(r.example_titles or "[]"),
            }
            for r in rows
        ],
    }
