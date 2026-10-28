"""Tests for src.features.hook_lab — HookLab regex classification & scoring.

The LLM calls (``_llm_score``, ``rewrite_hook``) are mocked to keep tests
hermetic and fast.  We verify the regex fallback path, which contains all
the deterministic business logic.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.features.hook_lab import (
    BELIEF_PATTERNS,
    HOOK_TYPE_DESCRIPTIONS,
    MISTAKE_PATTERNS,
    SPECIFICITY_PATTERNS,
    STAKE_REVERSAL_PATTERNS,
    SUMMARY_PATTERNS,
    GapAnalysis,
    HookLab,
    HookType,
)


@pytest.fixture()
def lab():
    """HookLab with LLM stubbed out so scoring is deterministic."""
    with patch("src.features.hook_lab.get_llm_client"):
        instance = HookLab()
    # Always return None from _llm_score so we exercise the regex path
    instance._llm_score = lambda _: None
    return instance


# ---------------------------------------------------------------------------
# detect_summary_pattern
# ---------------------------------------------------------------------------

class TestDetectSummaryPattern:
    @pytest.mark.parametrize("hook", [
        "Here are 5 tips to grow on Instagram",
        "3 ways to make more money online",
        "How to grow your YouTube channel fast",
        "In this video I'll show you how to edit",
        "Today I'll explain the best strategy",
    ])
    def test_identifies_summary_hooks(self, lab, hook):
        assert lab.detect_summary_pattern(hook) is True

    @pytest.mark.parametrize("hook", [
        "You've been doing this wrong your whole life",
        "Stop chasing trends. Do this instead.",
        "I made $1M and here's what nobody tells you",
    ])
    def test_non_summary_hooks(self, lab, hook):
        assert lab.detect_summary_pattern(hook) is False


# ---------------------------------------------------------------------------
# _regex_classify
# ---------------------------------------------------------------------------

class TestRegexClassify:
    def test_summary(self, lab):
        assert lab._regex_classify("Here are 3 tips to improve your feed") == HookType.SUMMARY

    def test_mistake_callout(self, lab):
        assert lab._regex_classify("You've been editing your videos all wrong") == HookType.MISTAKE_CALLOUT

    def test_belief_destruction(self, lab):
        assert lab._regex_classify("SEO is a myth and here's why") == HookType.BELIEF_DESTRUCTION

    def test_stake_reversal(self, lab):
        assert lab._regex_classify("Stop chasing views and do this instead") == HookType.STAKE_REVERSAL

    def test_specificity(self, lab):
        assert lab._regex_classify("The AIDA framework that got me 1M views") == HookType.SPECIFICITY

    def test_authority_anchor(self, lab):
        # Matches AUTHORITY_PATTERNS: "I've generated $5M" or "worked with 500"
        assert lab._regex_classify("I've worked with 500 creators over 5 years") == HookType.AUTHORITY_ANCHOR


# ---------------------------------------------------------------------------
# _regex_score
# ---------------------------------------------------------------------------

class TestRegexScore:
    def test_returns_four_dimensions(self, lab):
        scores = lab._regex_score("You've been doing this wrong")
        for key in ("belief_challenge", "mistake_callout", "urgency", "specificity"):
            assert key in scores

    def test_belief_hooks_score_high_belief(self, lab):
        scores = lab._regex_score("Viral growth is a myth and everyone believes it")
        assert scores["belief_challenge"] > 50

    def test_mistake_hooks_score_high_mistake(self, lab):
        scores = lab._regex_score("You're doing this wrong and failing at it")
        assert scores["mistake_callout"] > 50

    def test_question_mark_boosts_urgency(self, lab):
        base = lab._regex_score("Plain hook with no urgency")["urgency"]
        question = lab._regex_score("Why are you still doing this the wrong way?")["urgency"]
        assert question >= base

    def test_number_boosts_specificity(self, lab):
        scores = lab._regex_score("The 3 frameworks that changed everything")
        assert scores["specificity"] > 25

    def test_all_scores_within_0_100(self, lab):
        for hook in [
            "Here are 3 tips!",
            "Stop wasting time. Do this instead.",
            "I earned $5M after 10 years working with 200 brands",
        ]:
            scores = lab._regex_score(hook)
            for v in scores.values():
                assert 0.0 <= v <= 100.0, f"Score {v} out of range for hook: {hook}"


# ---------------------------------------------------------------------------
# score_gap (full analysis via regex fallback)
# ---------------------------------------------------------------------------

class TestScoreGap:
    def test_empty_hook_returns_analysis(self, lab):
        result = lab.score_gap("")
        assert isinstance(result, GapAnalysis)

    def test_result_has_all_fields(self, lab):
        result = lab.score_gap("Stop doing this one thing that's killing your growth")
        assert isinstance(result.overall_score, float)
        assert isinstance(result.detected_type, HookType)
        assert isinstance(result.is_summary_pattern, bool)
        assert result.belief_challenge >= 0
        assert result.mistake_callout >= 0
        assert result.urgency >= 0
        assert result.specificity >= 0

    def test_summary_hook_is_penalized(self, lab):
        summary = lab.score_gap("Here are 5 tips to grow your channel")
        strong = lab.score_gap("You've been doing this wrong and here's the truth")
        assert summary.overall_score < strong.overall_score

    def test_summary_detected(self, lab):
        result = lab.score_gap("3 ways to make money online today")
        assert result.is_summary_pattern is True
        assert result.detected_type == HookType.SUMMARY

    def test_stake_reversal_detected(self, lab):
        result = lab.score_gap("Stop posting every day. Do this instead.")
        assert result.detected_type == HookType.STAKE_REVERSAL

    def test_weakest_strongest_are_valid_dimensions(self, lab):
        result = lab.score_gap("You've been wrong this whole time")
        valid = {"belief_challenge", "mistake_callout", "urgency", "specificity"}
        assert result.weakest_dimension in valid
        assert result.strongest_dimension in valid

    def test_type_description_matches_enum(self, lab):
        result = lab.score_gap("You've been doing this wrong")
        assert result.type_description == HOOK_TYPE_DESCRIPTIONS[result.detected_type]


# ---------------------------------------------------------------------------
# HookType enum
# ---------------------------------------------------------------------------

class TestHookTypeEnum:
    def test_summary_value(self):
        assert HookType.SUMMARY.value == "summary"

    def test_all_types_have_descriptions(self):
        for hook_type in HookType:
            assert hook_type in HOOK_TYPE_DESCRIPTIONS
