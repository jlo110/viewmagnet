"""Tests for src.features.shorts.models — Highlight and ShortsAnalysis dataclasses."""
from __future__ import annotations

import pytest
from src.features.shorts.models import Highlight, ShortsAnalysis, TranscriptUnavailable


def _hi(**kwargs) -> Highlight:
    defaults = dict(
        start_time=10.0, end_time=40.0, duration=30.0,
        score=75.0, reason="viral_hook", transcript="Here's what nobody tells you.",
        hook_quality="strong", suggested_title="The Untold Story",
        crop_x=656, crop_width=607, crop_height=1080,
    )
    defaults.update(kwargs)
    return Highlight(**defaults)


# ---------------------------------------------------------------------------
# Highlight.to_dict
# ---------------------------------------------------------------------------

class TestHighlightToDict:
    def test_required_keys_present(self):
        d = _hi().to_dict()
        for key in (
            "start_time", "end_time", "duration", "score", "reason",
            "transcript", "hook_quality", "suggested_title",
            "crop", "ffmpeg_crop", "timestamp_display", "smart_tracking_enabled",
        ):
            assert key in d, f"Missing key: {key}"

    def test_crop_subdict(self):
        d = _hi(crop_x=100, crop_width=500, crop_height=900).to_dict()
        assert d["crop"] == {"x": 100, "width": 500, "height": 900}

    def test_ffmpeg_crop_format(self):
        d = _hi(crop_x=656, crop_width=607, crop_height=1080).to_dict()
        assert d["ffmpeg_crop"] == "crop=607:1080:656:0"

    def test_timestamp_display_format(self):
        d = _hi(start_time=90.0, end_time=120.0).to_dict()
        # 90s = 01:30, 120s = 02:00
        assert "01:30" in d["timestamp_display"]
        assert "02:00" in d["timestamp_display"]

    def test_smart_tracking_disabled_by_default(self):
        d = _hi().to_dict()
        assert d["smart_tracking_enabled"] is False

    def test_dynamic_crop_absent_when_not_tracking(self):
        d = _hi().to_dict()
        assert "ffmpeg_crop_dynamic" not in d


# ---------------------------------------------------------------------------
# Highlight._format_time
# ---------------------------------------------------------------------------

class TestFormatTime:
    @pytest.mark.parametrize("seconds,expected", [
        (0.0, "00:00"),
        (60.0, "01:00"),
        (90.5, "01:30"),
        (3599.9, "59:59"),
    ])
    def test_format(self, seconds, expected):
        assert Highlight._format_time(seconds) == expected


# ---------------------------------------------------------------------------
# ShortsAnalysis
# ---------------------------------------------------------------------------

class TestShortsAnalysis:
    def _analysis(self, scores):
        highlights = [
            _hi(score=s, start_time=i * 60.0, end_time=i * 60.0 + 30.0)
            for i, s in enumerate(scores)
        ]
        return ShortsAnalysis(
            video_title="Test Video",
            video_duration=600.0,
            highlights=highlights,
            transcript_full="full transcript",
            captions_srt="",
        )

    def test_get_top_clips_sorted_by_score(self):
        analysis = self._analysis([50.0, 90.0, 70.0])
        top = analysis.get_top_clips(n=2)
        assert top[0].score == 90.0
        assert top[1].score == 70.0

    def test_get_top_clips_respects_n(self):
        analysis = self._analysis([80.0, 60.0, 40.0, 20.0])
        assert len(analysis.get_top_clips(n=2)) == 2

    def test_empty_highlights(self):
        analysis = self._analysis([])
        assert analysis.get_top_clips(n=5) == []

    def test_clip_paths_default_empty(self):
        analysis = self._analysis([75.0])
        assert analysis.clip_paths == []
        assert analysis.vertical_clip_paths == []


# ---------------------------------------------------------------------------
# TranscriptUnavailable
# ---------------------------------------------------------------------------

class TestTranscriptUnavailable:
    def test_is_exception(self):
        exc = TranscriptUnavailable("captions are disabled")
        assert isinstance(exc, Exception)

    def test_message_preserved(self):
        msg = "YouTube captions are disabled and Whisper failed"
        assert msg in str(TranscriptUnavailable(msg))

    def test_not_value_error_subclass(self):
        try:
            raise TranscriptUnavailable("test")
        except ValueError:
            pytest.fail("TranscriptUnavailable should not be caught as ValueError")
        except TranscriptUnavailable:
            pass
