"""Tests for the unified LLM client (cost estimation + budget gate).

These intentionally avoid hitting any real API: we exercise the pure
functions and mock the provider clients in :class:`LLMClient.generate`.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.features import llm_client as llm_module
from src.features.llm_client import (
    LLMBudgetExceeded,
    LLMClient,
    LLMResponse,
    _estimate_cost,
    _estimate_tokens,
)


class TestCostEstimation:
    def test_estimate_tokens_basic(self):
        # Roughly 4 chars per token
        assert _estimate_tokens("") == 1
        assert _estimate_tokens("abcd") == 1
        assert _estimate_tokens("a" * 40) == 10

    def test_estimate_cost_known_model(self):
        # Sonnet: $0.003/1k input, $0.015/1k output
        cost = _estimate_cost("claude-3-5-sonnet-20241022", 1000, 500)
        assert cost == pytest.approx(0.003 + (500 / 1000.0) * 0.015)

    def test_estimate_cost_unknown_model_falls_back(self):
        # Default fallback should be non-zero (treats as paid model).
        cost = _estimate_cost("brand-new-model", 1000, 1000)
        assert cost > 0


class TestBudgetEnforcement:
    def test_no_user_id_skips_budget_check(self):
        within, spent, limit = llm_module._check_budget(user_id=None, plan="free")
        assert within is True
        assert spent == 0.0
        assert limit == 0.0

    def test_unlimited_plan_skips_budget_check(self):
        # Patch PLAN_LIMITS to make 'pro' unlimited (limit <= 0 means skip).
        with patch.dict(llm_module.PLAN_LIMITS, {"free": {"daily_llm_usd": 0.0}}):
            within, _, _ = llm_module._check_budget(user_id=42, plan="free")
            assert within is True

    def test_budget_exceeded_raises(self):
        # Force a tiny budget and a session that returns a high spent total.
        with patch.dict(llm_module.PLAN_LIMITS, {"free": {"daily_llm_usd": 0.10}}):
            mock_session = MagicMock()
            mock_session.execute.return_value.scalar.return_value = 0.50
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value = mock_session
            mock_ctx.__exit__.return_value = False
            with patch("src.database.connection.get_session", return_value=mock_ctx):
                within, spent, limit = llm_module._check_budget(user_id=1, plan="free")
                assert within is False
                assert spent == 0.50
                assert limit == 0.10


class TestGenerateRespectsBudget:
    def test_generate_raises_when_over_budget(self):
        client = LLMClient()
        with patch.object(llm_module, "_check_budget", return_value=(False, 1.0, 0.5)):
            with pytest.raises(LLMBudgetExceeded) as exc_info:
                client.generate(
                    system_prompt="be brief",
                    user_prompt="write a haiku",
                    user_id=7,
                    feature="haiku",
                    plan="free",
                )
            assert exc_info.value.user_id == 7
            assert exc_info.value.spent_usd == 1.0
            assert exc_info.value.limit_usd == 0.5

    def test_generate_records_usage_on_success(self):
        client = LLMClient()
        fake_response = LLMResponse(
            text="ok",
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.001,
        )
        with (
            patch.object(llm_module, "_check_budget", return_value=(True, 0.0, 1.0)),
            patch.object(client, "_try_anthropic", return_value=fake_response),
            patch.object(llm_module, "_record_usage") as mock_record,
        ):
            # Force the client to attempt anthropic by pretending the key exists.
            client.anthropic_key = "fake-key"
            result = client.generate(
                system_prompt="sys",
                user_prompt="hi",
                user_id=1,
                feature="test",
                plan="pro",
            )
            assert result.text == "ok"
            mock_record.assert_called_once()


class TestSafetyNet:
    """Tests for the 2026-05-19 defense-in-depth additions."""

    def test_per_request_cap_blocks_giant_max_tokens(self):
        """A single call asking for an absurd max_tokens should be
        rejected before any provider is dialed, regardless of budget."""
        client = LLMClient()
        # 200_000 output tokens at the worst rate is way over $0.40 cap.
        with patch.object(llm_module, "_check_budget", return_value=(True, 0.0, 100.0)):
            with pytest.raises(LLMBudgetExceeded):
                client.generate(
                    system_prompt="",
                    user_prompt="hi",
                    max_tokens=200_000,
                    user_id=1,
                    feature="oversized",
                )

    def test_per_request_cap_allows_normal_call(self):
        """The default 1500 max_tokens should sit well under the cap."""
        client = LLMClient()
        fake = LLMResponse(text="ok", provider="anthropic", model="claude-3-5-sonnet-20241022", cost_usd=0.0)
        with (
            patch.object(llm_module, "_check_budget", return_value=(True, 0.0, 100.0)),
            patch.object(client, "_try_anthropic", return_value=fake),
        ):
            client.anthropic_key = "fake"
            result = client.generate(
                system_prompt="s",
                user_prompt="u",
                max_tokens=1500,
                user_id=1,
                feature="normal",
            )
            assert result.text == "ok"

    def test_missing_user_id_routes_to_anonymous_bucket(self):
        """``user_id=None`` should NOT skip the budget check anymore — it
        should attribute to the anonymous bucket so leaks are bounded."""
        client = LLMClient()
        seen_uids: list = []

        def fake_check_budget(uid, plan):
            seen_uids.append(uid)
            return True, 0.0, 5.0

        fake = LLMResponse(text="ok", provider="anthropic", model="claude-3-5-sonnet-20241022")
        with (
            patch.object(llm_module, "_check_budget", side_effect=fake_check_budget),
            patch.object(client, "_try_anthropic", return_value=fake),
            patch.object(llm_module, "_record_usage") as mock_record,
        ):
            client.anthropic_key = "fake"
            client.generate(
                system_prompt="s",
                user_prompt="u",
                user_id=None,  # legacy caller / forgot to plumb
                feature="leaky",
            )
            assert seen_uids == [llm_module._ANONYMOUS_USER_ID]
            # Usage is recorded under the anonymous bucket so it
            # actually accumulates toward the cap on the next call.
            args, kwargs = mock_record.call_args
            recorded_uid = args[0] if args else kwargs.get("user_id")
            assert recorded_uid == llm_module._ANONYMOUS_USER_ID

    def test_anonymous_bucket_uses_platform_cap(self):
        """The synthetic anonymous user gets ``LLM_ANONYMOUS_DAILY_USD``,
        not whatever plan the caller passed."""
        # Force a known cap so the assertion is stable across env.
        with patch.object(llm_module, "LLM_ANONYMOUS_DAILY_USD", 7.5):
            assert llm_module._resolve_limit(llm_module._ANONYMOUS_USER_ID, "free") == 7.5
            assert llm_module._resolve_limit(llm_module._ANONYMOUS_USER_ID, "pro") == 7.5
            # Real users still get plan-based limits.
            real_limit = llm_module._resolve_limit(42, "pro")
            assert real_limit == llm_module.PLAN_LIMITS["pro"]["daily_llm_usd"]

    def test_budget_check_fails_closed_in_strict_mode(self):
        """When the DB lookup explodes and LLM_STRICT_BUDGET=True, the
        check must reject — fail-open is a billing footgun."""
        with patch.object(llm_module, "LLM_STRICT_BUDGET", True):
            mock_session = MagicMock()
            mock_session.execute.side_effect = RuntimeError("DB unreachable")
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value = mock_session
            mock_ctx.__exit__.return_value = False
            with patch("src.database.connection.get_session", return_value=mock_ctx):
                within, _spent, _limit = llm_module._check_budget(user_id=1, plan="free")
                assert within is False

    def test_budget_check_fails_open_in_lenient_mode(self):
        """Dev/default behavior keeps working when the DB hiccups."""
        with patch.object(llm_module, "LLM_STRICT_BUDGET", False):
            mock_session = MagicMock()
            mock_session.execute.side_effect = RuntimeError("DB unreachable")
            mock_ctx = MagicMock()
            mock_ctx.__enter__.return_value = mock_session
            mock_ctx.__exit__.return_value = False
            with patch("src.database.connection.get_session", return_value=mock_ctx):
                within, _, _ = llm_module._check_budget(user_id=1, plan="free")
                assert within is True

    def test_expensive_call_emits_warning(self):
        """High-cost responses log ``llm.expensive`` so operators can
        catch runaway features early."""
        client = LLMClient()
        events: list = []

        class _Capture:
            def warning(self, event, **kwargs):
                events.append((event, kwargs))

        big_response = LLMResponse(
            text="long",
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            input_tokens=5000,
            output_tokens=5000,
            cost_usd=0.30,  # well above the 0.15 threshold
        )
        with patch.object(llm_module, "logger", _Capture()):
            client._alert_if_expensive(big_response, "scripts", user_id=42)
        assert any(e[0] == "llm.expensive" for e in events)
        # Cheap calls should not page.
        events.clear()
        cheap = LLMResponse(text="ok", provider="anthropic", model="claude-3-5-sonnet-20241022", cost_usd=0.01)
        with patch.object(llm_module, "logger", _Capture()):
            client._alert_if_expensive(cheap, "scripts", user_id=42)
        assert all(e[0] != "llm.expensive" for e in events)
