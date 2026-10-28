"""Tests for the LLM-driven emoji suggester (Week 6 Phase 4).

We stub ``LLMClient.generate_json`` so the tests run in milliseconds and
don't touch any external service. The focus is on the three things that
can break independently of the LLM:

  1. Phrase grouping matches the ass_renderer's rules (force_break_after
     and the max-words bucket size).
  2. Emojis land on the LAST word of their phrase so they render as the
     trailing glyph.
  3. The suggester is defensive: tolerates dict-wrapped LLM output,
     skips empty-string sentinels, swallows LLM exceptions.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.features.studio.emoji_suggester import (
    _group_phrases,
    _parse_response,
    clear_emojis,
    suggest_emojis_for_transcript,
)
from src.features.studio.spec import TranscriptWord


def _wd(text: str, start: float, end: float, **extra) -> TranscriptWord:
    """Compact TranscriptWord factory for fixture-heavy tests."""
    return TranscriptWord(text=text, start=start, end=end, **extra)


# ---------------------------------------------------------------------------
# _group_phrases
# ---------------------------------------------------------------------------


class TestGroupPhrases:
    def test_empty_input(self):
        assert _group_phrases([]) == []

    def test_buckets_at_max_words(self):
        words = [_wd(f"w{i}", i * 0.1, i * 0.1 + 0.1) for i in range(13)]
        phrases = _group_phrases(words, group_max_words=5)
        assert [len(p) for p in phrases] == [5, 5, 3]
        # Indices flow sequentially.
        assert phrases[0] == [0, 1, 2, 3, 4]
        assert phrases[1] == [5, 6, 7, 8, 9]
        assert phrases[2] == [10, 11, 12]

    def test_force_break_after_true_splits_early(self):
        words = [
            _wd("hello", 0.0, 0.2),
            _wd("there", 0.2, 0.4, force_break_after=True),
            _wd("world", 0.4, 0.6),
        ]
        phrases = _group_phrases(words, group_max_words=5)
        assert phrases == [[0, 1], [2]]

    def test_force_break_after_false_overrides_max(self):
        # group_max_words=2 would normally split after each pair; the
        # explicit force_break_after=False on the second word should
        # keep the bucket growing past the cap.
        words = [
            _wd("a", 0.0, 0.1),
            _wd("b", 0.1, 0.2, force_break_after=False),
            _wd("c", 0.2, 0.3, force_break_after=False),
            _wd("d", 0.3, 0.4),
            _wd("e", 0.4, 0.5),
        ]
        phrases = _group_phrases(words, group_max_words=2)
        # First phrase grew through the two False overrides, then closed
        # on the next implicit hit of the cap.
        assert phrases[0] == [0, 1, 2, 3]
        assert phrases[-1][-1] == 4


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_plain_list(self):
        out = _parse_response(
            [
                {"phrase_idx": 0, "emoji": "🔥"},
                {"phrase_idx": 1, "emoji": "🚀"},
            ],
            n_phrases=2,
        )
        assert out == {0: "🔥", 1: "🚀"}

    def test_dict_wrapped(self):
        # Models sometimes return ``{"results": [...]}`` instead of a
        # bare list. We accept the common wrapper keys.
        out = _parse_response(
            {"results": [{"phrase_idx": 0, "emoji": "✨"}]},
            n_phrases=1,
        )
        assert out == {0: "✨"}

    def test_skips_empty_and_sentinels(self):
        out = _parse_response(
            [
                {"phrase_idx": 0, "emoji": ""},
                {"phrase_idx": 1, "emoji": "none"},
                {"phrase_idx": 2, "emoji": "-"},
                {"phrase_idx": 3, "emoji": "🎯"},
            ],
            n_phrases=4,
        )
        assert out == {3: "🎯"}

    def test_drops_out_of_range_indices(self):
        out = _parse_response(
            [
                {"phrase_idx": 5, "emoji": "🔥"},
                {"phrase_idx": -1, "emoji": "💀"},
                {"phrase_idx": 0, "emoji": "✅"},
            ],
            n_phrases=2,
        )
        assert out == {0: "✅"}

    def test_tolerates_malformed_entries(self):
        out = _parse_response(
            [
                "not a dict",
                {"missing_idx": "🔥"},
                {"phrase_idx": "abc", "emoji": "🚀"},
                {"phrase_idx": 0, "emoji": 12345},
                {"phrase_idx": 1, "emoji": "👍"},
            ],
            n_phrases=2,
        )
        assert out == {1: "👍"}


# ---------------------------------------------------------------------------
# suggest_emojis_for_transcript
# ---------------------------------------------------------------------------


class FakeClient:
    """Minimal stand-in for LLMClient — captures the prompts and replays
    a canned ``generate_json`` payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls: list = []

    def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class TestSuggestEmojisForTranscript:
    def test_attaches_emoji_to_last_word_of_each_phrase(self):
        # 3 words → fits in a single phrase (max 6). The emoji should
        # land on index 2 (the last word).
        words = [
            _wd("this", 0.0, 0.2),
            _wd("is", 0.2, 0.4),
            _wd("fire", 0.4, 0.7),
        ]
        client = FakeClient([{"phrase_idx": 0, "emoji": "🔥"}])
        with patch(
            "src.features.studio.emoji_suggester.get_llm_client",
            return_value=client,
        ):
            updated, n = suggest_emojis_for_transcript(words)

        assert n == 1
        assert [w.emoji for w in updated] == [None, None, "🔥"]
        # Caller's list must be untouched (we cloned).
        assert all(w.emoji is None for w in words)

    def test_multi_phrase_emoji_placement(self):
        # 7 words at default max=6 → splits as [6, 1].
        words = [_wd(f"w{i}", i * 0.1, i * 0.1 + 0.1) for i in range(7)]
        client = FakeClient(
            [
                {"phrase_idx": 0, "emoji": "🎯"},
                {"phrase_idx": 1, "emoji": "✨"},
            ]
        )
        with patch(
            "src.features.studio.emoji_suggester.get_llm_client",
            return_value=client,
        ):
            updated, n = suggest_emojis_for_transcript(words)

        assert n == 2
        # Last word of first phrase = index 5; second phrase = index 6.
        assert updated[5].emoji == "🎯"
        assert updated[6].emoji == "✨"
        # All other words remain bare.
        for i in (0, 1, 2, 3, 4):
            assert updated[i].emoji is None

    def test_empty_transcript_short_circuits(self):
        with patch(
            "src.features.studio.emoji_suggester.get_llm_client"
        ) as mock_client:
            updated, n = suggest_emojis_for_transcript([])
        assert n == 0
        assert updated == []
        # LLM was never called for empty input.
        mock_client.assert_not_called()

    def test_llm_failure_returns_untouched_transcript(self):
        words = [_wd("hi", 0.0, 0.2), _wd("there", 0.2, 0.4)]

        class BoomClient:
            def generate_json(self, **_):
                raise RuntimeError("network exploded")

        with patch(
            "src.features.studio.emoji_suggester.get_llm_client",
            return_value=BoomClient(),
        ):
            updated, n = suggest_emojis_for_transcript(words)

        assert n == 0
        assert all(w.emoji is None for w in updated)

    def test_llm_budget_exceeded_propagates(self):
        """``LLMBudgetExceeded`` must bubble up so the API can map it to
        a friendly 402/upgrade-modal response — we do NOT swallow it."""
        from src.features.llm_client import LLMBudgetExceeded

        words = [_wd("hi", 0.0, 0.2)]

        class BudgetClient:
            def generate_json(self, **_):
                raise LLMBudgetExceeded(
                    user_id=1, spent_usd=1.0, limit_usd=0.5
                )

        with patch(
            "src.features.studio.emoji_suggester.get_llm_client",
            return_value=BudgetClient(),
        ):
            with pytest.raises(LLMBudgetExceeded):
                suggest_emojis_for_transcript(words)

    def test_clear_emojis_returns_fresh_list(self):
        words = [
            _wd("hello", 0.0, 0.2, emoji="👋"),
            _wd("world", 0.2, 0.4, emoji="🌍"),
        ]
        cleared = clear_emojis(words)
        assert [w.emoji for w in cleared] == [None, None]
        # Originals untouched (clear returns a copy).
        assert words[0].emoji == "👋"
        assert words[1].emoji == "🌍"
