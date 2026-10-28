"""Tests for the topic-saturation index (Phase 8.2) — pure clustering + summary."""
from __future__ import annotations

import numpy as np

from src.features.topic_saturation import cluster_embeddings, summarize_clusters


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_cluster_groups_similar_and_separates_distinct():
    # Two tight topics on near-orthogonal axes + one outlier between them.
    a1, a2 = _unit([1, 0.05, 0]), _unit([0.98, 0.1, 0])
    b1, b2 = _unit([0, 1, 0.05]), _unit([0.05, 0.97, 0])
    lone = _unit([0.6, 0.6, 0.55])
    emb = np.stack([a1, a2, b1, b2, lone])
    labels = cluster_embeddings(emb, similarity=0.9)
    assert labels[0] == labels[1]          # topic A together
    assert labels[2] == labels[3]          # topic B together
    assert labels[0] != labels[2]          # A and B distinct
    assert labels[4] not in (labels[0], labels[2])  # outlier is its own cluster


def test_cluster_first_row_leads():
    # Rows are pre-sorted by views desc — row 0 must be a leader.
    emb = np.stack([_unit([1, 0]), _unit([0.99, 0.1])])
    labels = cluster_embeddings(emb, similarity=0.9)
    assert labels[0] == 0 and labels[1] == 0


def test_summarize_filters_small_clusters_and_aggregates():
    labels = [0, 0, 0, 1, 2, 2]
    titles = [f"t{i}" for i in range(6)]
    views = [100, 50, 25, 999, 10, 5]
    channels = ["c1", "c2", "c1", "c3", "c4", "c4"]
    vids = [f"v{i}" for i in range(6)]
    out = summarize_clusters(labels, titles, views, channels, vids, min_size=2)
    sizes = {c["label"]: c for c in out}
    # Cluster 0 (3 vids) and cluster 2 (2 vids) survive; singleton cluster 1 dropped.
    assert len(out) == 2
    big = sizes["t0"]
    assert big["size"] == 3 and big["total_views"] == 175 and big["channel_count"] == 2
    assert out[0]["size"] >= out[1]["size"]  # sorted by size desc


def test_summarize_caps_example_titles():
    labels = [0] * 8
    titles = [f"t{i}" for i in range(8)]
    out = summarize_clusters(labels, titles, [1] * 8, ["c"] * 8, [f"v{i}" for i in range(8)])
    assert len(out[0]["example_titles"]) == 5
    assert out[0]["size"] == 8


def test_annotate_with_topics_maps_video_ids(tmp_path):
    import json
    from datetime import datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, TopicCluster
    from src.features.topic_saturation import annotate_with_topics

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    now = datetime(2026, 6, 12, 12, 0, 0)
    db.add(TopicCluster(
        computed_at=now, window_hours=48, label="US strikes Iran", size=113,
        total_views=9_000_000, channel_count=31,
        example_titles=json.dumps(["US strikes Iran"]),
        video_ids=json.dumps(["vidA", "vidB"]),
    ))
    # An older batch must NOT win over the latest one.
    db.add(TopicCluster(
        computed_at=datetime(2026, 6, 11), window_hours=48, label="stale", size=5,
        total_views=1, channel_count=2, example_titles="[]",
        video_ids=json.dumps(["vidA"]),
    ))
    db.commit()

    items = [{"video_id": "vidA"}, {"video_id": "vidZ"}]
    out = annotate_with_topics(db, items)
    assert out[0]["topic"]["label"] == "US strikes Iran"
    assert out[0]["topic"]["size"] == 113
    assert out[1]["topic"] is None
    db.close()


def test_match_topic_batches_trends():
    from src.features.topic_saturation import match_topic_batches

    prev = [
        {"label": "Iran strikes", "size": 50, "video_ids": ["a", "b", "c"]},
        {"label": "World Cup", "size": 30, "video_ids": ["w1", "w2"]},
        {"label": "Old story", "size": 20, "video_ids": ["o1"]},
    ]
    cur = [
        # Same topic (shares a,b) grown 50 -> 60: rising
        {"label": "IRAN: new strikes", "size": 60, "video_ids": ["a", "b", "x"]},
        # Same topic shrunk 30 -> 10: falling
        {"label": "World Cup recap", "size": 10, "video_ids": ["w2"]},
        # Brand new topic: new
        {"label": "Fresh thing", "size": 8, "video_ids": ["n1", "n2"]},
    ]
    out = {c["label"]: c for c in match_topic_batches(cur, prev)}
    assert out["IRAN: new strikes"]["trend"] == "rising" and out["IRAN: new strikes"]["prev_size"] == 50
    assert out["World Cup recap"]["trend"] == "falling" and out["World Cup recap"]["delta"] == -20
    assert out["Fresh thing"]["trend"] == "new" and out["Fresh thing"]["prev_size"] == 0


def test_match_topic_batches_small_delta_is_stable():
    from src.features.topic_saturation import match_topic_batches

    prev = [{"label": "t", "size": 10, "video_ids": ["a"]}]
    cur = [{"label": "t2", "size": 11, "video_ids": ["a", "b"]}]
    assert match_topic_batches(cur, prev)[0]["trend"] == "stable"


def test_annotate_with_topics_no_batch_yet():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base
    from src.features.topic_saturation import annotate_with_topics

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    out = annotate_with_topics(db, [{"video_id": "x"}])
    assert out[0]["topic"] is None
    db.close()
