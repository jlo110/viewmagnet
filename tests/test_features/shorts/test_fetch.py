"""Tests for src.features.shorts.fetch — pure helper functions.

YouTube API calls and youtube_transcript_api are mocked so the tests run
offline and without credentials.
"""
from __future__ import annotations

import json
import pytest
from src.features.shorts import fetch as fe


# ---------------------------------------------------------------------------
# extract_video_id
# ---------------------------------------------------------------------------

class TestExtractVideoId:
    @pytest.mark.parametrize("url,expected_id", [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/v/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),  # raw 11-char ID
    ])
    def test_extracts_id(self, url, expected_id):
        assert fe.extract_video_id(url) == expected_id

    @pytest.mark.parametrize("url", [
        "https://vimeo.com/123456789",
        "https://example.com",
        "",
        "not-a-url",
        "https://youtube.com/watch?v=tooshort",  # < 11 chars
    ])
    def test_returns_none_for_non_youtube(self, url):
        assert fe.extract_video_id(url) is None


# ---------------------------------------------------------------------------
# parse_timestamp
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    @pytest.mark.parametrize("ts,expected", [
        ("00:00:00,000", 0.0),
        ("00:01:30,500", 90.5),
        ("01:00:00,000", 3600.0),
        ("00:00:00.000", 0.0),  # VTT dot separator
        ("00:02:15.250", 135.25),
    ])
    def test_parses_correctly(self, ts, expected):
        assert abs(fe.parse_timestamp(ts) - expected) < 0.01


# ---------------------------------------------------------------------------
# parse_transcript
# ---------------------------------------------------------------------------

class TestParseTranscript:
    def test_parses_json(self):
        data = {
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "Hello world."},
                {"start": 5.0, "end": 10.0, "text": "Second segment."},
            ],
            "text": "Hello world. Second segment.",
            "duration": 10.0,
        }
        result = fe.parse_transcript(json.dumps(data))
        assert result["duration"] == 10.0
        assert len(result["segments"]) == 2

    def test_parses_srt(self):
        srt = """1
00:00:00,000 --> 00:00:05,000
First subtitle.

2
00:00:05,000 --> 00:00:10,000
Second subtitle here.
"""
        result = fe.parse_transcript(srt)
        assert len(result["segments"]) == 2
        assert result["segments"][0]["text"] == "First subtitle."
        assert abs(result["segments"][1]["start"] - 5.0) < 0.01

    def test_parses_vtt(self):
        vtt = """WEBVTT

00:00:00.000 --> 00:00:05.000
VTT line one.

00:00:05.000 --> 00:00:10.000
VTT line two.
"""
        result = fe.parse_transcript(vtt)
        assert len(result["segments"]) >= 1

    def test_empty_string_returns_no_segments(self):
        result = fe.parse_transcript("")
        assert result["segments"] == []

    def test_plain_text_fallback(self):
        result = fe.parse_transcript("Just some plain text with no timestamps.")
        # No SRT timestamps found; segments may be empty but must not crash
        assert isinstance(result, dict)
        assert "segments" in result


# ---------------------------------------------------------------------------
# split_into_sentences
# ---------------------------------------------------------------------------

class TestSplitIntoSentences:
    def test_splits_on_periods(self):
        sents = fe.split_into_sentences("First. Second. Third.")
        assert len(sents) == 3

    def test_splits_on_question_marks(self):
        sents = fe.split_into_sentences("Is this good? Yes it is!")
        assert len(sents) == 2

    def test_empty_string(self):
        assert fe.split_into_sentences("") == []


# ---------------------------------------------------------------------------
# load_viral_patterns
# ---------------------------------------------------------------------------

class TestLoadViralPatterns:
    def test_returns_four_keys(self):
        patterns = fe.load_viral_patterns()
        for key in ("hook_phrases", "emotion_words", "story_beats", "specifics"):
            assert key in patterns

    def test_each_category_non_empty(self):
        patterns = fe.load_viral_patterns()
        for key, val in patterns.items():
            assert len(val) > 0, f"Category '{key}' is empty"

    def test_sports_vocabulary_present(self):
        patterns = fe.load_viral_patterns()
        assert any("buzzer" in w or "clutch" in w for w in patterns["emotion_words"])


# ---------------------------------------------------------------------------
# fetch_youtube_comments — no API key → returns []
# ---------------------------------------------------------------------------

class TestFetchYoutubeComments:
    def test_no_key_returns_empty(self, monkeypatch):
        """When no YouTube API key is configured, returns [] gracefully."""
        monkeypatch.delenv("YOUTUBE1", raising=False)
        monkeypatch.delenv("YOUTUBE2", raising=False)
        monkeypatch.delenv("YOUTUBE_API_KEY_1", raising=False)
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        # Patch settings to also return no keys
        monkeypatch.setattr(
            "src.features.shorts.fetch._resolve_youtube_api_key",
            lambda: None,
        )
        result = fe.fetch_youtube_comments("dQw4w9WgXcQ")
        assert result == []
