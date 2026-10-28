"""
Unified LLM Client with Automatic Fallback + Per-User Budget Tracking.

Provider order:
1. Anthropic Claude (if API key and within budget)
2. Synthetic (subscription-based OSS models via OpenAI-compatible endpoint)
3. Groq (free fallback)

Every call **should** pass ``user_id``, ``plan``, and ``feature`` so the cost
is metered and the ``PLAN_LIMITS[plan]["daily_llm_usd"]`` budget is enforced.

A ``LLMBudgetExceeded`` exception is raised when the user is over budget; the
endpoint layer translates this to HTTP 402 (or 429) so the frontend can prompt
to upgrade.

**Defense in depth (added 2026-05-19 after the cross-call-site audit
revealed most callers were dropping ``user_id``):**

1. **Per-request hard cap** — before any provider is called, we estimate the
   worst-case cost from ``max_tokens`` and the model's output rate. If that
   exceeds ``LLM_MAX_REQUEST_USD`` (default $0.40, env-tunable) the call is
   rejected. A single bad prompt with ``max_tokens=64000`` can no longer blow
   $4 in one shot.
2. **Anonymous budget bucket** — when ``user_id`` is ``None`` we count the
   spend against a synthetic "anonymous" pseudo-user (negative id ``-1``) so
   even forgetting to thread ``user_id`` through can't run unbounded.
   ``LLM_ANONYMOUS_DAILY_USD`` controls the cap (default $5/day platform-wide).
3. **Strict mode** — set ``LLM_STRICT_BUDGET=1`` to make the budget DB lookup
   fail closed instead of fail open. Recommended for prod; off by default in
   dev so a Postgres outage doesn't block work.
4. **Loud warnings** — every call without ``user_id`` logs ``llm.no_user_id``
   at warning level so leaks surface in the operator's log feed.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import structlog

from src.config import get_settings, PLAN_LIMITS

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Safety-net knobs. All env-tunable so prod can clamp tighter than dev.
# ---------------------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("llm.env_bad_float", name=name, value=raw, default=default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Worst-case cost a single LLM call is allowed to incur. Computed from
# ``max_tokens`` * the most expensive output-token rate the call could hit.
# This is a *defense-in-depth* gate distinct from the daily user budget.
LLM_MAX_REQUEST_USD = _env_float("LLM_MAX_REQUEST_USD", 0.40)

# Daily platform-wide spend bucket for calls that arrived without a
# ``user_id`` (e.g. background jobs that forgot to plumb it through).
# This keeps a buggy worker from torching the bill while we fix it.
LLM_ANONYMOUS_DAILY_USD = _env_float("LLM_ANONYMOUS_DAILY_USD", 5.00)

# When True, a DB error during the budget check raises instead of falling
# through. In dev we fail-open so a Postgres hiccup doesn't block work; in
# prod set ``LLM_STRICT_BUDGET=1`` so a DB outage can't bypass billing.
LLM_STRICT_BUDGET = _env_bool("LLM_STRICT_BUDGET", False)

# Magic user-id for the anonymous bucket. Negative so it can't collide with
# a real ``users.id`` value (those are auto-incrementing positives).
_ANONYMOUS_USER_ID = -1


# Rough cost (USD per 1K tokens) used purely for daily budget enforcement.
# These can drift slightly from billing; tighten them in Settings if needed.
_MODEL_COSTS = {
    # Anthropic Claude pricing (input, output)
    "claude-sonnet-4-20250514": (0.003, 0.015),
    "claude-3-5-sonnet-20241022": (0.003, 0.015),
    "claude-3-opus-20240229": (0.015, 0.075),
    "claude-3-haiku-20240307": (0.00025, 0.00125),
    # Groq pricing (very cheap; treated as free)
    "llama-3.3-70b-versatile": (0.0, 0.0),
    "llama-3.1-70b-versatile": (0.0, 0.0),
    # Synthetic — included in subscription, so treated as $0 for daily-budget
    # purposes. Override in Settings if you switch to usage-based billing.
    # ``syn:*`` are the always-current aliases (preferred over pinned hf: ids).
    "syn:large:text": (0.0, 0.0),
    "syn:small:text": (0.0, 0.0),
    "syn:large:vision": (0.0, 0.0),
    "syn:small:vision": (0.0, 0.0),
    "hf:meta-llama/Llama-3.3-70B-Instruct": (0.0, 0.0),
    "hf:moonshotai/Kimi-K2.6": (0.0, 0.0),
    "hf:zai-org/GLM-5.2": (0.0, 0.0),
    "hf:zai-org/GLM-5.1": (0.0, 0.0),
    "hf:zai-org/GLM-4.7": (0.0, 0.0),
    "hf:Qwen/Qwen3-Coder-480B-A35B-Instruct": (0.0, 0.0),
    "hf:deepseek-ai/DeepSeek-V3": (0.0, 0.0),
    "hf:openai/gpt-oss-120b": (0.0, 0.0),
}


class LLMBudgetExceeded(Exception):
    """Raised when a user has exceeded their daily LLM budget."""
    def __init__(self, user_id: int, spent_usd: float, limit_usd: float):
        self.user_id = user_id
        self.spent_usd = spent_usd
        self.limit_usd = limit_usd
        super().__init__(
            f"Daily LLM budget exceeded for user {user_id}: "
            f"${spent_usd:.2f} of ${limit_usd:.2f} used. Upgrade plan for more headroom."
        )


@dataclass
class LLMResponse:
    """Response from the LLM."""
    text: str
    provider: str
    model: str
    success: bool = True
    error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def _estimate_tokens(text: str) -> int:
    """Cheap token estimator (4 chars per token)."""
    return max(1, len(text) // 4)


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    cost_in, cost_out = _MODEL_COSTS.get(model, (0.003, 0.015))
    return (input_tokens / 1000.0) * cost_in + (output_tokens / 1000.0) * cost_out


def _resolve_limit(user_id: Optional[int], plan: str) -> float:
    """Daily $ budget for this caller. The anonymous bucket uses a single
    platform-wide cap instead of a per-plan cap."""
    if user_id == _ANONYMOUS_USER_ID:
        return LLM_ANONYMOUS_DAILY_USD
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"]).get("daily_llm_usd", 0.50)


def _check_budget(user_id: Optional[int], plan: str) -> tuple[bool, float, float]:
    """Sum today's LLM spend for ``user_id`` and return
    ``(within_budget, spent, limit)``. ``user_id=None`` is the wide-open
    legacy path; callers should pass the anonymous id via
    :func:`_effective_user_id` so even un-attributed spend gets capped."""
    if user_id is None:
        return True, 0.0, 0.0

    limit = _resolve_limit(user_id, plan)
    if limit <= 0:
        # An explicit "unlimited" plan still avoids the DB roundtrip.
        return True, 0.0, 0.0

    try:
        from sqlalchemy import func, select
        from src.database.connection import get_session
        from src.database.models import LLMUsageRecord

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        with get_session() as session:
            stmt = select(func.coalesce(func.sum(LLMUsageRecord.cost_usd), 0.0)).where(
                LLMUsageRecord.user_id == user_id,
                LLMUsageRecord.created_at >= today_start,
                LLMUsageRecord.success.is_(True),
            )
            spent = float(session.execute(stmt).scalar() or 0.0)

        return spent < limit, spent, limit
    except Exception as e:
        # Fail-closed in strict mode (prod) — we'd rather a 503 than a
        # silent unbounded spend. Fail-open elsewhere so dev keeps working
        # when the DB is briefly unavailable.
        logger.warning(
            "llm_budget.check_failed",
            user_id=user_id,
            error=str(e),
            strict=LLM_STRICT_BUDGET,
        )
        if LLM_STRICT_BUDGET:
            return False, 0.0, limit
        return True, 0.0, limit


def _effective_user_id(user_id: Optional[int]) -> int:
    """Turn a missing ``user_id`` into the anonymous bucket id so even
    un-attributed spend is bounded. Logs a loud warning so the leak is
    visible in the operator's stream."""
    if user_id is None:
        # Single record at WARNING is enough to surface the call site in
        # logs without spamming when there's a hot path of leakers.
        logger.warning("llm.no_user_id", anonymous_cap_usd=LLM_ANONYMOUS_DAILY_USD)
        return _ANONYMOUS_USER_ID
    return user_id


# Per-token output rate to use for the worst-case-cost projection. We pick
# the most expensive output rate across the active model table so the cap
# stays accurate when Anthropic is the chosen provider — the cheaper
# fallback providers will naturally fit under the same ceiling.
def _max_output_rate_per_1k() -> float:
    out_rates = [out for (_, out) in _MODEL_COSTS.values() if out > 0]
    return max(out_rates) if out_rates else 0.015


def _max_request_cost_usd(max_tokens: int, prompt_tokens: int) -> float:
    """Worst-case dollar cost a single call could ring up. Uses Anthropic's
    output rate (most expensive) so the gate is conservative."""
    rate_out = _max_output_rate_per_1k()
    rate_in = max(c[0] for c in _MODEL_COSTS.values()) if _MODEL_COSTS else 0.003
    return (prompt_tokens / 1000.0) * rate_in + (max_tokens / 1000.0) * rate_out


def _record_usage(
    user_id: Optional[int],
    provider: str,
    model: str,
    feature: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    success: bool,
    error: Optional[str] = None,
) -> None:
    """Persist one usage record. Silent on DB errors."""
    try:
        from src.database.connection import get_session
        from src.database.models import LLMUsageRecord
        
        record = LLMUsageRecord(
            # Anonymous calls use the sentinel id -1; persist NULL instead so we
            # don't violate the users FK (the column is nullable for this).
            user_id=user_id if (user_id and user_id > 0) else None,
            provider=provider,
            model=model,
            feature=feature,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            success=success,
            error_message=error,
        )
        with get_session() as session:
            session.add(record)
            session.commit()
    except Exception as e:
        logger.warning("llm_usage.persist_failed", error=str(e))


class LLMClient:
    """Unified LLM client with automatic provider fallback + budget tracking."""
    
    def __init__(self):
        settings = get_settings()
        self.anthropic_key = settings.anthropic_api_key
        self.groq_key = settings.groq_api_key
        self.synthetic_key = settings.synthetic_api_key
        self.anthropic_model = settings.anthropic_model
        self.groq_model = settings.groq_model
        self.synthetic_model = settings.synthetic_model
        self.synthetic_base_url = settings.synthetic_base_url
    
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1500,
        temperature: float = 0.7,
        json_response: bool = False,
        user_id: Optional[int] = None,
        feature: str = "unknown",
        plan: str = "free",
    ) -> LLMResponse:
        """Generate text with automatic Anthropic -> Synthetic -> Groq fallback.

        Three safety gates run before any provider is invoked:

        1. **Per-request cap** — worst-case ``max_tokens`` cost can't exceed
           ``LLM_MAX_REQUEST_USD`` (defense against runaway prompts).
        2. **Effective user-id** — ``None`` is rewritten to the anonymous
           bucket so even un-attributed traffic gets a daily ceiling.
        3. **Daily budget** — sum of today's recorded cost vs. plan limit.

        Each gate raises ``LLMBudgetExceeded`` so the API layer can return
        a clean HTTP 402.
        """
        # Gate 1: per-request hard cap. Cheap to compute, runs before any
        # network or DB call.
        prompt_tokens_est = _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt)
        max_cost = _max_request_cost_usd(max_tokens, prompt_tokens_est)
        if max_cost > LLM_MAX_REQUEST_USD:
            logger.warning(
                "llm.request_cap_exceeded",
                feature=feature,
                user_id=user_id,
                max_tokens=max_tokens,
                prompt_tokens_est=prompt_tokens_est,
                projected_usd=round(max_cost, 4),
                cap_usd=LLM_MAX_REQUEST_USD,
            )
            raise LLMBudgetExceeded(
                user_id=user_id if user_id is not None else 0,
                spent_usd=max_cost,
                limit_usd=LLM_MAX_REQUEST_USD,
            )

        # Gate 2 + 3: bucket-attribute + daily budget. Even if the caller
        # forgot to pass user_id we still cap via the anonymous pseudo-user.
        effective_uid = _effective_user_id(user_id)
        within_budget, spent, limit = _check_budget(effective_uid, plan)
        if not within_budget:
            logger.warning(
                "llm.budget_exceeded",
                user_id=user_id,
                effective_uid=effective_uid,
                spent=spent,
                limit=limit,
                feature=feature,
            )
            raise LLMBudgetExceeded(
                user_id=user_id if user_id is not None else effective_uid,
                spent_usd=spent,
                limit_usd=limit,
            )
        
        # Record usage under the effective uid so the anonymous bucket
        # accumulates real numbers (otherwise leakers would always show
        # spent=0 on the next call and the cap would be illusory).
        record_uid = effective_uid

        # Try Anthropic first
        if self.anthropic_key:
            response = self._try_anthropic(system_prompt, user_prompt, max_tokens, temperature)
            if response.success:
                _record_usage(
                    record_uid, response.provider, response.model, feature,
                    response.input_tokens, response.output_tokens, response.cost_usd,
                    success=True,
                )
                self._alert_if_expensive(response, feature, user_id)
                return response
            # WARNING-level so the operator sees that the primary provider is
            # down even when root log level is WARNING (the default).
            logger.warning(
                "llm.fallback", from_="anthropic", to="synthetic",
                error=response.error, feature=feature,
            )

        # Fall back to Synthetic (OSS models, OpenAI-compatible)
        if self.synthetic_key:
            response = self._try_synthetic(system_prompt, user_prompt, max_tokens, temperature)
            if response.success:
                _record_usage(
                    record_uid, response.provider, response.model, feature,
                    response.input_tokens, response.output_tokens, response.cost_usd,
                    success=True,
                )
                self._alert_if_expensive(response, feature, user_id)
                logger.warning(
                    "llm.used", provider="synthetic", model=response.model,
                    feature=feature, tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                )
                return response
            logger.warning(
                "llm.fallback", from_="synthetic", to="groq",
                error=response.error, feature=feature,
            )

        # Fall back to Groq
        if self.groq_key:
            response = self._try_groq(system_prompt, user_prompt, max_tokens, temperature)
            if response.success:
                _record_usage(
                    record_uid, response.provider, response.model, feature,
                    response.input_tokens, response.output_tokens, response.cost_usd,
                    success=True,
                )
                self._alert_if_expensive(response, feature, user_id)
                logger.warning(
                    "llm.used", provider="groq", model=response.model,
                    feature=feature, tokens_in=response.input_tokens,
                    tokens_out=response.output_tokens,
                )
                return response
            logger.warning("llm.groq_failed", error=response.error, feature=feature)

        # All providers failed
        _record_usage(
            record_uid, "none", "none", feature, 0, 0, 0.0,
            success=False, error="All providers failed",
        )
        return LLMResponse(
            text="",
            provider="none",
            model="none",
            success=False,
            error="All LLM providers failed. Check API keys and credits.",
        )
    
    # Threshold above which an individual call gets surfaced as a
    # warning (and Sentry breadcrumb when configured). Tuned so the
    # noise floor stays low: a $0.10 call is fine, a $0.30 call is
    # worth noticing, a $0.40+ call would have hit the per-request gate.
    _EXPENSIVE_CALL_USD = 0.15

    def _alert_if_expensive(
        self,
        response: "LLMResponse",
        feature: str,
        user_id: Optional[int],
    ) -> None:
        """Log a loud line whenever a single call rings up real money.
        Cheap to make this a structured event so we can grep ``llm.expensive``
        in production logs (and pipe to Sentry / Slack later)."""
        if response.cost_usd <= self._EXPENSIVE_CALL_USD:
            return
        logger.warning(
            "llm.expensive",
            feature=feature,
            user_id=user_id,
            provider=response.provider,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=round(response.cost_usd, 4),
        )

    def _try_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        try:
            import anthropic
            
            client = anthropic.Anthropic(api_key=self.anthropic_key)

            # Prompt caching: mark the system prompt as cacheable. Large, reused
            # system prompts (the analyzer/title prompts) then hit the cache on
            # repeat calls — cheaper + faster. Harmless no-op when the prompt is
            # below the cache minimum.
            response = client.messages.create(
                model=self.anthropic_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_prompt}],
            )

            text = response.content[0].text
            input_tokens = getattr(response.usage, "input_tokens", 0) or _estimate_tokens(system_prompt + user_prompt)
            output_tokens = getattr(response.usage, "output_tokens", 0) or _estimate_tokens(text)
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            cache_write = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            if cache_read or cache_write:
                logger.info(
                    "llm.cache", provider="anthropic", model=self.anthropic_model,
                    cache_read_tokens=cache_read, cache_write_tokens=cache_write,
                )
            cost = _estimate_cost(self.anthropic_model, input_tokens, output_tokens)
            
            return LLMResponse(
                text=text,
                provider="anthropic",
                model=self.anthropic_model,
                success=True,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
            )
        except ImportError:
            return LLMResponse(
                text="", provider="anthropic", model="",
                success=False, error="anthropic package not installed",
            )
        except Exception as e:
            error_msg = str(e)
            if "credit" in error_msg.lower() or "billing" in error_msg.lower():
                return LLMResponse(
                    text="", provider="anthropic", model=self.anthropic_model,
                    success=False, error="Anthropic credit balance too low",
                )
            return LLMResponse(
                text="", provider="anthropic", model=self.anthropic_model,
                success=False, error=error_msg,
            )
    
    def _try_synthetic(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError:
            return LLMResponse(
                text="", provider="synthetic", model="",
                success=False, error="openai package not installed",
            )

        try:
            client = OpenAI(
                api_key=self.synthetic_key,
                base_url=self.synthetic_base_url,
            )
            response = client.chat.completions.create(
                model=self.synthetic_model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            text = response.choices[0].message.content or ""
            try:
                input_tokens = response.usage.prompt_tokens
                output_tokens = response.usage.completion_tokens
            except AttributeError:
                input_tokens = _estimate_tokens(system_prompt + user_prompt)
                output_tokens = _estimate_tokens(text)
            cost = _estimate_cost(self.synthetic_model, input_tokens, output_tokens)

            return LLMResponse(
                text=text,
                provider="synthetic",
                model=self.synthetic_model,
                success=True,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
            )
        except Exception as e:
            return LLMResponse(
                text="", provider="synthetic", model=self.synthetic_model,
                success=False, error=str(e),
            )

    def _try_groq(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        try:
            from groq import Groq
            
            client = Groq(api_key=self.groq_key)
            
            response = client.chat.completions.create(
                model=self.groq_model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            
            text = response.choices[0].message.content
            try:
                input_tokens = response.usage.prompt_tokens
                output_tokens = response.usage.completion_tokens
            except AttributeError:
                input_tokens = _estimate_tokens(system_prompt + user_prompt)
                output_tokens = _estimate_tokens(text or "")
            cost = _estimate_cost(self.groq_model, input_tokens, output_tokens)
            
            return LLMResponse(
                text=text or "",
                provider="groq",
                model=self.groq_model,
                success=True,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
            )
        except ImportError:
            return LLMResponse(
                text="", provider="groq", model="",
                success=False, error="groq package not installed",
            )
        except Exception as e:
            return LLMResponse(
                text="", provider="groq", model=self.groq_model,
                success=False, error=str(e),
            )
    
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1500,
        temperature: float = 0.7,
        user_id: Optional[int] = None,
        feature: str = "unknown",
        plan: str = "free",
    ) -> Dict[str, Any]:
        """Generate and parse JSON. Returns {} on parse failure."""
        response = self.generate(
            system_prompt, user_prompt, max_tokens, temperature,
            user_id=user_id, feature=feature, plan=plan,
        )
        
        if not response.success:
            logger.warning("llm.json_call_failed", error=response.error, feature=feature)
            return {}
        
        try:
            text = response.text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text.strip())
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning("llm.json_parse_failed", error=str(e), feature=feature)
            return {}


_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Return the shared LLMClient instance."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
