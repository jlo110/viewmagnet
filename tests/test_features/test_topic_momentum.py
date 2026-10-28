"""Topic Momentum (2.1): trend classification + breakout-density computation."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from src.features.topic_saturation import (
    _match_prev_rate,
    classify_momentum,
    compute_topic_momentum,
)


def test_classify_momentum_transitions():
    assert classify_momentum(0.3, None) == "new"
    assert classify_momentum(0.5, 0.3) == "rising"        # +0.2
    assert classify_momentum(0.2, 0.5) == "fading"        # -0.3
    assert classify_momentum(0.6, 0.6) == "peaking"       # flat but high
    assert classify_momentum(0.1, 0.1) == "steady"        # flat and low


def test_match_prev_rate_by_membership_overlap():
    prev = [
        {"breakout_rate": 0.9, "video_ids": ["a", "b", "c"]},
        {"breakout_rate": 0.1, "video_ids": ["x", "y"]},
    ]
    assert _match_prev_rate(["b", "c", "z"], prev) == 0.9   # best overlap = first topic
    assert _match_prev_rate(["q", "r"], prev) is None       # no overlap


class _Cluster:
    def __init__(self, label, vids):
        self.computed_at = "T"
        self.window_hours = 48.0
        self.label = label
        self.size = len(vids)
        self.total_views = 1000
        self.channel_count = 3
        self.example_titles = json.dumps([label])
        self.video_ids = json.dumps(vids)


class _Q:
    def __init__(self, rows):
        self._rows = rows
    def filter(self, *a, **k):
        return self
    def all(self):
        return self._rows


class _Session:
    """Stub: 1st execute() = latest cluster ts, 2nd = prev momentum ts (None);
    query() returns TopicCluster rows, [] for the (absent) prior momentum snapshot."""
    def __init__(self, cluster_rows, cluster_ts="T"):
        self._cluster_rows = cluster_rows
        self._exec_returns = [cluster_ts, None]
        self.added = []

    def execute(self, *a, **k):
        val = self._exec_returns.pop(0) if self._exec_returns else None
        return SimpleNamespace(scalar_one_or_none=lambda: val)

    def query(self, model, *rest):
        name = getattr(model, "__name__", "")
        return _Q(self._cluster_rows if name == "TopicCluster" else [])

    def add(self, row):
        self.added.append(row)

    def commit(self):
        pass


def test_compute_writes_one_momentum_row_per_topic_with_density():
    clusters = [_Cluster("MrBeast challenge", ["v1", "v2", "v3", "v4"]),
                _Cluster("cooking asmr", ["v5", "v6"])]
    session = _Session(clusters)
    # v1,v2,v3 of topic A are breaking out (3/4 = 0.75); none of topic B (0/2).
    breaking = [{"video_id": v} for v in ("v1", "v2", "v3")]
    with patch("src.features.breakout_detector.detect_live_breakouts", return_value=breaking):
        out = compute_topic_momentum(session)
    assert out == {"topics": 2, "breaking_videos": 3}
    by_label = {r.label: r for r in session.added}
    assert by_label["MrBeast challenge"].breakout_count == 3
    assert by_label["MrBeast challenge"].breakout_rate == 0.75
    assert by_label["MrBeast challenge"].trend == "new"   # no prior momentum snapshot
    assert by_label["cooking asmr"].breakout_rate == 0.0


def test_compute_no_clusters_returns_zero():
    session = _Session([], cluster_ts=None)
    assert compute_topic_momentum(session) == {"topics": 0, "breaking_videos": 0}
