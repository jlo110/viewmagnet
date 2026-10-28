"""Tests for the most-replayed (heatmap) clip re-ranking."""
from src.features.shorts.models import Highlight
from src.features.shorts.score import apply_heatmap_boost, heatmap_intensity


def _hl(start, end, score, reason="kw"):
    return Highlight(
        start_time=start, end_time=end, duration=end - start, score=score, reason=reason,
        transcript="", hook_quality="", suggested_title="", crop_x=0, crop_width=0, crop_height=0,
    )


# Re-watch curve: a strong peak at 100-120s, low elsewhere.
_POINTS = (
    [{"start_time": float(t), "end_time": float(t + 10), "value": 0.1} for t in range(0, 100, 10)]
    + [{"start_time": 100.0, "end_time": 120.0, "value": 0.9}]
    + [{"start_time": float(t), "end_time": float(t + 10), "value": 0.1} for t in range(120, 200, 10)]
)


def test_heatmap_intensity_overlap():
    assert heatmap_intensity(_POINTS, 100, 120) == 0.9          # the peak
    assert heatmap_intensity(_POINTS, 0, 10) == 0.1             # a trough
    assert heatmap_intensity([], 0, 10) is None                 # no data


def test_boost_promotes_rewatched_clip_over_keyword_clip():
    # A weak-keyword clip ON the re-watch peak should beat a strong-keyword clip
    # in a trough — real retention wins over the keyword guess.
    peak_clip = _hl(100, 120, score=40)
    kw_clip = _hl(0, 20, score=70)
    out = apply_heatmap_boost([kw_clip, peak_clip], _POINTS)
    assert out[0] is peak_clip
    assert "re-watched" in peak_clip.reason.lower()


def test_noop_without_heatmap():
    a, b = _hl(0, 20, 70), _hl(100, 120, 40)
    out = apply_heatmap_boost([a, b], [])
    assert out == [a, b]  # unchanged
