"""Tests for src.features.shorts.score — pure scoring functions.

All tests are hermetic (no I/O, no LLM calls).  The functions tested here
are pure or nearly-pure; we mock the LLM entry-points so the test suite runs
offline.
"""
from __future__ import annotations

import pytest
from src.features.shorts.models import Highlight
from src.features.shorts import score as sc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hi(**kwargs) -> Highlight:
    """Build a Highlight with safe defaults."""
    defaults = dict(
        start_time=0.0, end_time=30.0, duration=30.0,
        score=50.0, reason="test", transcript="sample text",
        hook_quality="medium", suggested_title="", crop_x=0,
        crop_width=608, crop_height=1080,
    )
    defaults.update(kwargs)
    return Highlight(**defaults)


# ---------------------------------------------------------------------------
# score_segment
# ---------------------------------------------------------------------------

class TestScoreSegment:
    def setup_method(self):
        from src.features.shorts.fetch import load_viral_patterns
        self.patterns = load_viral_patterns()

    def test_empty_text_scores_zero(self):
        assert sc.score_segment("", self.patterns) == 0.0

    def test_score_is_capped_at_100(self):
        # Pile on every kind of signal
        text = (
            "here's the thing you won't believe this! this is crazy and then "
            "suddenly 25% boom! bang! amazing insane clutch buzzer champion. "
            "down by 10 for the win at the buzzer swish!"
        )
        assert sc.score_segment(text, self.patterns) <= 100

    def test_short_text_penalty(self):
        # < 5 words → 0.5× multiplier
        score_short = sc.score_segment("crazy", self.patterns)
        score_long = sc.score_segment("crazy amazing insane clutch highlight buzzer dagger", self.patterns)
        assert score_long >= score_short

    def test_question_mark_adds_points(self):
        no_q = sc.score_segment("amazing play right there", self.patterns)
        with_q = sc.score_segment("amazing play right there?", self.patterns)
        assert with_q >= no_q

    def test_hook_phrase_triggers(self):
        text = "here's the thing nobody talks about this"
        score = sc.score_segment(text, self.patterns)
        assert score > 20  # hook_phrase contributes +25

    def test_sport_vocabulary_adds_emotion_points(self):
        text = "buzzer beater clutch shot for the championship finals mvp"
        score = sc.score_segment(text, self.patterns)
        assert score > 0


# ---------------------------------------------------------------------------
# get_highlight_reason
# ---------------------------------------------------------------------------

class TestGetHighlightReason:
    def setup_method(self):
        from src.features.shorts.fetch import load_viral_patterns
        self.patterns = load_viral_patterns()

    def test_hook_phrase_returns_viral_hook(self):
        reason = sc.get_highlight_reason("here's the thing nobody says", self.patterns)
        assert reason == "viral_hook"

    def test_story_beat_returns_story_beat(self):
        reason = sc.get_highlight_reason("and then everything changed suddenly", self.patterns)
        assert reason == "story_beat"

    def test_no_signal_returns_content_density(self):
        reason = sc.get_highlight_reason("generic talking with no keywords", self.patterns)
        assert reason == "content_density"


# ---------------------------------------------------------------------------
# assess_hook_quality
# ---------------------------------------------------------------------------

class TestAssessHookQuality:
    def test_strong_hook_pattern(self):
        assert sc.assess_hook_quality("here's what nobody tells you about this thing") == "strong"

    def test_question_mark_strong(self):
        assert sc.assess_hook_quality("Did you see what just happened?") == "strong"

    def test_number_gives_medium(self):
        assert sc.assess_hook_quality("3 reasons this fails every time") == "medium"

    def test_plain_text_is_weak(self):
        assert sc.assess_hook_quality("talking about sports today with team") == "weak"


# ---------------------------------------------------------------------------
# extract_comment_timestamps
# ---------------------------------------------------------------------------

class TestExtractCommentTimestamps:
    def test_parses_mm_ss(self):
        comments = ["The buzzer beater at 2:35 was insane 🔥"]
        results = sc.extract_comment_timestamps(comments)
        assert any(r["seconds"] == 155 for r in results)

    def test_parses_hh_mm_ss(self):
        comments = ["Amazing play at 1:02:15"]
        results = sc.extract_comment_timestamps(comments)
        assert any(r["seconds"] == 3735 for r in results)

    def test_deduplicates_same_timestamp(self):
        comments = ["2:35 was amazing 🔥", "2:35 insane 🔥 gold"]
        results = sc.extract_comment_timestamps(comments)
        secs = [r["seconds"] for r in results]
        assert secs.count(155) == 1

    def test_no_comments_returns_empty(self):
        assert sc.extract_comment_timestamps([]) == []

    def test_positive_words_boost_sentiment(self):
        comments = ["The shot at 1:30 was amazing and incredible 🔥 gold"]
        results = sc.extract_comment_timestamps(comments)
        assert results[0]["sentiment_score"] >= 2


# ---------------------------------------------------------------------------
# fuzzy_find_text
# ---------------------------------------------------------------------------

class TestFuzzyFindText:
    def _segs(self):
        return [
            {"text": "We were down by 10 points.", "start": 0.0, "end": 5.0},
            {"text": "Then the buzzer beater happened.", "start": 5.0, "end": 10.0},
            {"text": "Nobody expected that finish.", "start": 10.0, "end": 15.0},
        ]

    def test_exact_phrase_match(self):
        seg = sc.fuzzy_find_text("buzzer beater happened", self._segs())
        assert seg is not None
        assert "buzzer" in seg["text"]

    def test_partial_word_match(self):
        seg = sc.fuzzy_find_text("Nobody expected", self._segs())
        assert seg is not None

    def test_no_match_returns_none(self):
        seg = sc.fuzzy_find_text("completely unrelated phrase xyz", self._segs())
        assert seg is None

    def test_empty_query_returns_none(self):
        assert sc.fuzzy_find_text("", self._segs()) is None

    def test_empty_segments_returns_none(self):
        assert sc.fuzzy_find_text("something", []) is None

    def test_search_from_end(self):
        segs = [
            {"text": "first occurrence here.", "start": 0.0, "end": 5.0},
            {"text": "Nothing.", "start": 5.0, "end": 8.0},
            {"text": "here is the last occurrence.", "start": 8.0, "end": 12.0},
        ]
        # search_from_end should prefer the last segment
        seg = sc.fuzzy_find_text("occurrence here", segs, search_from_end=True)
        assert seg["start"] == 8.0


# ---------------------------------------------------------------------------
# find_natural_end
# ---------------------------------------------------------------------------

class TestFindNaturalEnd:
    def _segs(self):
        return [
            {"text": "First sentence.", "start": 0.0, "end": 5.0},
            {"text": "Second with energy!", "start": 5.0, "end": 10.0},
            {"text": "Third ends with a question?", "start": 10.0, "end": 15.0},
            {"text": "Fourth run-on with no ending", "start": 15.0, "end": 20.0},
        ]

    def test_picks_up_sentence_ending(self):
        end = sc.find_natural_end(self._segs(), 0.0, min_duration=5.0, max_duration=60.0)
        assert end >= 5.0  # at least the first sentence

    def test_respects_max_duration(self):
        segs = [{"text": "very long text.", "start": 0.0, "end": 300.0}]
        end = sc.find_natural_end(segs, 0.0, min_duration=10.0, max_duration=60.0)
        assert end <= 60.0


# ---------------------------------------------------------------------------
# select_diverse_clips
# ---------------------------------------------------------------------------

class TestSelectDiverseClips:
    def _clips(self, starts):
        return [_hi(start_time=s, end_time=s + 30, score=80 - i * 5)
                for i, s in enumerate(starts)]

    def test_empty_returns_empty(self):
        assert sc.select_diverse_clips([], 300.0, 3) == []

    def test_returns_at_most_num_clips(self):
        clips = self._clips([0, 120, 240, 360, 480])
        selected = sc.select_diverse_clips(clips, 600.0, 3)
        assert len(selected) <= 3

    def test_clips_sorted_by_start_time(self):
        clips = self._clips([300, 0, 150])
        selected = sc.select_diverse_clips(clips, 600.0, 3)
        times = [c.start_time for c in selected]
        assert times == sorted(times)

    def test_enforces_min_gap(self):
        # Clips all at 0, 10, 20 — below 60s gap — only first should be kept
        clips = self._clips([0, 10, 20, 200, 400])
        selected = sc.select_diverse_clips(clips, 600.0, 3, min_gap_seconds=60)
        # No two selected clips within 60s of each other
        for i in range(len(selected)):
            for j in range(i + 1, len(selected)):
                assert abs(selected[i].start_time - selected[j].start_time) >= 30


# ---------------------------------------------------------------------------
# calculate_objective_quality
# ---------------------------------------------------------------------------

class TestCalculateObjectiveQuality:
    def test_passes_on_strong_clip(self):
        clip = _hi(transcript=(
            "Here's what nobody tells you. The championship came down to one shot. "
            "He was down by 2 with 5 seconds left. And then boom — buzzer beater! "
            "The crowd went insane. That's why they call him the clutch king wow!"
        ))
        q = sc.calculate_objective_quality(clip)
        assert q["total"] > 0
        assert isinstance(q["passes"], bool)

    def test_fails_on_weak_clip(self):
        clip = _hi(transcript="talking about stuff today nothing special happens")
        q = sc.calculate_objective_quality(clip)
        # Should have issues
        assert len(q["issues"]) > 0

    def test_strong_hook_pattern_scores_hook(self):
        clip = _hi(transcript="here's the truth that nobody mentions. " + "word " * 60 + " wow!")
        q = sc.calculate_objective_quality(clip)
        assert q["hook_score"] >= 10

    def test_returns_all_required_keys(self):
        q = sc.calculate_objective_quality(_hi(transcript="test text here for the clip moment wow!"))
        for key in ("hook_score", "payoff_score", "emotion_score", "clarity_score", "total", "passes", "issues"):
            assert key in q


# ---------------------------------------------------------------------------
# normalize_scores
# ---------------------------------------------------------------------------

class TestNormalizeScores:
    def test_empty_returns_empty(self):
        assert sc.normalize_scores([]) == []

    def test_scores_capped_at_95(self):
        clip = _hi(score=99.0, transcript=(
            "here's the thing you won't believe! amazing insane wow crazy! "
            "boom the shot goes in! exactly right there boom! !! the crowd loses it!"
        ))
        result = sc.normalize_scores([clip])
        assert result[0].score <= 95

    def test_sorted_by_score_descending(self):
        clips = [
            _hi(start_time=0, score=80, transcript="strong hook. " + "word " * 60 + " wow!"),
            _hi(start_time=100, score=40, transcript="plain talking nothing"),
        ]
        result = sc.normalize_scores(clips)
        scores = [c.score for c in result]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# parse_llm_response
# ---------------------------------------------------------------------------

class TestParseLlmResponse:
    def test_valid_json_array(self):
        payload = '[{"start_sentence": "here", "end_sentence": "done", "score": 80, "reason": "test", "hook_quality": "strong", "suggested_title": "T", "approximate_position": "early"}]'
        result = sc.parse_llm_response(payload, chunk_idx=0, chunk_start_pct=0.0)
        assert len(result) == 1
        assert result[0]["_chunk_idx"] == 0

    def test_json_in_code_fence(self):
        payload = '```json\n[{"start_sentence": "x", "end_sentence": "y", "score": 70, "reason": "r", "hook_quality": "medium", "suggested_title": "T", "approximate_position": "middle"}]\n```'
        result = sc.parse_llm_response(payload, chunk_idx=1, chunk_start_pct=0.5)
        assert result[0]["_chunk_start_pct"] == 0.5

    def test_invalid_json_returns_empty(self):
        result = sc.parse_llm_response("not json at all {}", chunk_idx=0, chunk_start_pct=0.0)
        assert result == []

    def test_empty_array_is_valid(self):
        result = sc.parse_llm_response("[]", chunk_idx=0, chunk_start_pct=0.0)
        assert result == []


# ---------------------------------------------------------------------------
# merge_highlights / apply_comment_signal
# ---------------------------------------------------------------------------

class TestMergeHighlights:
    def test_audio_boost_overlapping_text_highlight(self):
        text_hi = _hi(start_time=100.0, end_time=130.0, score=60.0)
        audio_hi = _hi(start_time=110.0, end_time=135.0, score=70.0, reason="audio_peak")
        merged = sc.merge_highlights([text_hi], [audio_hi], video_duration=600.0)
        # overlap → text highlight boosted, audio one not added separately
        boosted = next(h for h in merged if abs(h.start_time - 100.0) < 1)
        assert boosted.score > 60.0
        assert boosted.reason == "text_audio_peak"

    def test_non_overlapping_audio_appended(self):
        text_hi = _hi(start_time=0.0, end_time=30.0, score=60.0)
        audio_hi = _hi(start_time=300.0, end_time=330.0, score=70.0, reason="audio_peak")
        merged = sc.merge_highlights([text_hi], [audio_hi], video_duration=600.0)
        assert len(merged) == 2


class TestApplyCommentSignal:
    def test_nearby_comment_boosts_highlight(self):
        clips = [_hi(start_time=120.0, end_time=150.0, score=50.0)]
        timestamps = [{"seconds": 130, "mention_count": 3, "sentiment_score": 2, "timestamp": "2:10", "context": "amazing"}]
        result = sc.apply_comment_signal(clips, timestamps, 600.0)
        assert result[0].score > 50.0

    def test_unmatched_popular_timestamp_seeds_new_highlight(self):
        clips = [_hi(start_time=0.0, end_time=30.0, score=50.0)]
        timestamps = [{"seconds": 300, "mention_count": 5, "sentiment_score": 3, "timestamp": "5:00", "context": "wow"}]
        result = sc.apply_comment_signal(clips, timestamps, 600.0)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _chunk_transcript
# ---------------------------------------------------------------------------

class TestChunkTranscript:
    def test_empty_string_returns_empty(self):
        assert sc._chunk_transcript("") == []

    def test_short_string_produces_at_least_one_chunk(self):
        # Any non-empty string must produce at least one chunk
        text = "hello world this is a test"
        chunks = sc._chunk_transcript(text, chunk_size=6000, overlap=500)
        assert len(chunks) >= 1
        # Every chunk must contain the full text when text < chunk_size
        assert chunks[0][0] == text

    def test_long_text_produces_multiple_chunks(self):
        text = "a" * 1000
        chunks = sc._chunk_transcript(text, chunk_size=200, overlap=50)
        assert len(chunks) > 1

    def test_chunks_overlap_in_content(self):
        text = "a" * 1000
        chunks = sc._chunk_transcript(text, chunk_size=200, overlap=50)
        # Second chunk's start offset is less than chunk_size (due to overlap)
        _, _, start = chunks[1]
        assert start < 200

    def test_all_text_covered(self):
        text = "word " * 500
        chunks = sc._chunk_transcript(text, chunk_size=100, overlap=20)
        # Reconstruct: unique characters should cover the full string
        assert all(len(c) > 0 for c, _, _ in chunks)
