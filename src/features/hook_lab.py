"""
Hook Lab - Engineer the Competence Gap

Based on Chris Girbu's virality framework: a 10M-view hook attacks a specific
mistake the viewer is already making, or destroys something they believed was true.
The hook's only job is to create a gap that can only be closed by watching.

This module:
- Classifies hooks into types (summary vs strong gap-engineered)
- Scores hooks across 4 dimensions (belief, mistake, urgency, specificity)
- Rewrites weak hooks into strong gap-engineered alternatives
"""

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

import structlog

from src.features.llm_client import get_llm_client

logger = structlog.get_logger()


class HookType(str, Enum):
    """Hook classification - 'summary' is weak, others are strong."""
    SUMMARY = "summary"                      # weak: "Here are 3 tips to..."
    MISTAKE_CALLOUT = "mistake_callout"      # "You've been doing X wrong"
    BELIEF_DESTRUCTION = "belief_destruction"  # "X is a lie"
    AUTHORITY_ANCHOR = "authority_anchor"    # Credentials + contrarian
    STAKE_REVERSAL = "stake_reversal"        # "Stop X. Do Y instead."
    SPECIFICITY = "specificity"              # Named system / hidden asset


HOOK_TYPE_DESCRIPTIONS = {
    HookType.SUMMARY: "Summary hook - simply states what you'll cover. Weak.",
    HookType.MISTAKE_CALLOUT: "Mistake callout - tells the viewer they're doing something wrong.",
    HookType.BELIEF_DESTRUCTION: "Belief destruction - challenges something the viewer thinks is true.",
    HookType.AUTHORITY_ANCHOR: "Authority anchor - establishes credentials before delivering a contrarian take.",
    HookType.STAKE_REVERSAL: "Stake reversal - inverts what the viewer expects to do.",
    HookType.SPECIFICITY: "Specificity hook - promises a named system or hidden asset.",
}


@dataclass
class GapAnalysis:
    """Analysis of a hook's competence gap strength."""
    hook: str
    overall_score: float                # 0-100
    detected_type: HookType
    type_description: str
    
    # Sub-scores (0-100)
    belief_challenge: float             # Does it attack a belief?
    mistake_callout: float              # Does it call out an error?
    urgency: float                      # Does it create immediate need to know?
    specificity: float                  # Is it concrete vs vague?
    
    weakest_dimension: str
    strongest_dimension: str
    is_summary_pattern: bool
    rationale: str


# Regex patterns for fast detection (no LLM needed)
SUMMARY_PATTERNS = [
    r"^\s*(here\s+are|these\s+are|top|the)\s+\d+\s+\w+",  # "Here are 3 tips"
    r"^\s*\d+\s+(tips|ways|things|reasons|secrets|hacks|tricks|methods)",  # "3 tips to..."
    r"^\s*how\s+to\s+\w+",  # "How to grow Instagram"
    r"^\s*(in\s+this\s+video|today\s+i'?ll|let'?s\s+talk\s+about)",
]

MISTAKE_PATTERNS = [
    r"\b(you'?re\s+|you'?ve\s+been\s+)",  # "You're / You've been"
    r"\b(wrong|mistake|failing|messing\s+up|stop\s+doing)\b",
    r"\b(here'?s\s+why\s+you|the\s+reason\s+you)\b",
]

BELIEF_PATTERNS = [
    r"\b(is\s+a\s+lie|don'?t\s+matter|doesn'?t\s+work|won'?t\s+work)\b",
    r"\b(myth|misconception|everyone\s+thinks|most\s+people\s+believe)\b",
    r"\b(actually|the\s+truth\s+is|reality\s+is)\b",
]

AUTHORITY_PATTERNS = [
    r"\b(i'?ve\s+)?(generated|managed|built|grown|made|earned|spent)\s+\$?[\d,.]+\s*(billion|million|thousand|k|m|b)\b",
    r"\b(i'?ve\s+)?(worked\s+with|consulted\s+for|helped)\s+\d+",
    r"\b(after|years?\s+of)\s+(\d+\s+)?years?",
]

STAKE_REVERSAL_PATTERNS = [
    r"^\s*(stop|don'?t)\s+\w+",  # "Stop chasing trends"
    r"\b(instead\s+of|rather\s+than)\b",
]

SPECIFICITY_PATTERNS = [
    r"\b(framework|system|method|formula|playbook|blueprint)\b",
    r"\b[A-Z]{3,}\b",  # Acronyms like AIDA, PAS, named-system labels
]

STOP_WORDS = {"the", "a", "an", "is", "are", "was", "were", "to", "for", "of", "in", "on", "at"}


class HookLab:
    """
    Hook scoring + rewriting using LLM (with regex pre-classification).
    """

    def __init__(self):
        self.llm_client = get_llm_client()
        # Budget attribution context. Routers should call
        # ``set_budget_context(current_user.id, current_user.plan)``
        # so the LLM calls below meter against the right user's daily
        # $ cap instead of falling into the anonymous bucket.
        self._budget_user_id: Optional[int] = None
        self._budget_plan: str = "free"

    def set_budget_context(self, user_id: Optional[int], plan: str = "free") -> None:
        self._budget_user_id = user_id
        self._budget_plan = plan
    
    def detect_summary_pattern(self, hook: str) -> bool:
        """Fast regex check for summary-style hooks."""
        h = hook.lower().strip()
        return any(re.search(p, h) for p in SUMMARY_PATTERNS)
    
    def _regex_classify(self, hook: str) -> HookType:
        """Quick rule-based hook type detection (used as a fallback)."""
        h = hook.lower().strip()
        
        if self.detect_summary_pattern(hook):
            return HookType.SUMMARY
        if any(re.search(p, h) for p in AUTHORITY_PATTERNS):
            return HookType.AUTHORITY_ANCHOR
        if any(re.search(p, h) for p in STAKE_REVERSAL_PATTERNS):
            return HookType.STAKE_REVERSAL
        if any(re.search(p, h) for p in BELIEF_PATTERNS):
            return HookType.BELIEF_DESTRUCTION
        if any(re.search(p, h) for p in MISTAKE_PATTERNS):
            return HookType.MISTAKE_CALLOUT
        if any(re.search(p, h) for p in SPECIFICITY_PATTERNS):
            return HookType.SPECIFICITY
        # Default to summary if nothing distinctive
        return HookType.SUMMARY
    
    def _regex_score(self, hook: str) -> dict:
        """Quick rule-based scoring of the four dimensions."""
        h = hook.lower().strip()
        
        belief = 60.0 if any(re.search(p, h) for p in BELIEF_PATTERNS) else 25.0
        mistake = 60.0 if any(re.search(p, h) for p in MISTAKE_PATTERNS) else 25.0
        
        # Urgency proxies: question marks, present-tense action, short length
        urgency = 30.0
        if "?" in hook:
            urgency += 15
        if len(hook.split()) <= 12:
            urgency += 15
        if re.search(r"\b(now|today|right\s+now|immediately)\b", h):
            urgency += 20
        urgency = min(100.0, urgency)
        
        # Specificity proxies: named systems, numbers, proper nouns, named entities
        specificity = 25.0
        if any(re.search(p, h) for p in SPECIFICITY_PATTERNS):
            specificity += 25
        if re.search(r"\b\d+\b", hook):
            specificity += 15
        # Capitalized words (excluding sentence start) = proper nouns
        words = hook.split()
        cap_words = sum(1 for w in words[1:] if w and w[0].isupper())
        specificity += min(25, cap_words * 8)
        specificity = min(100.0, specificity)
        
        return {
            "belief_challenge": belief,
            "mistake_callout": mistake,
            "urgency": urgency,
            "specificity": specificity,
        }
    
    def score_gap(self, hook: str) -> GapAnalysis:
        """
        Score a hook's competence gap strength.
        Tries LLM first for nuanced scoring; falls back to regex on failure.
        """
        if not hook or not hook.strip():
            return self._empty_analysis(hook)
        
        # Get baseline regex signals
        is_summary = self.detect_summary_pattern(hook)
        regex_type = self._regex_classify(hook)
        regex_scores = self._regex_score(hook)
        
        # Try LLM for richer analysis
        llm_result = self._llm_score(hook)
        
        if llm_result:
            scores = {
                "belief_challenge": float(llm_result.get("belief_challenge", regex_scores["belief_challenge"])),
                "mistake_callout": float(llm_result.get("mistake_callout", regex_scores["mistake_callout"])),
                "urgency": float(llm_result.get("urgency", regex_scores["urgency"])),
                "specificity": float(llm_result.get("specificity", regex_scores["specificity"])),
            }
            try:
                detected_type = HookType(llm_result.get("detected_type", regex_type.value))
            except ValueError:
                detected_type = regex_type
            rationale = llm_result.get("rationale", "Hook scored via heuristic analysis.")
        else:
            scores = regex_scores
            detected_type = regex_type
            rationale = self._build_fallback_rationale(detected_type, is_summary)
        
        # Composite: weighted average. Summary hooks are penalized.
        composite = (
            scores["belief_challenge"] * 0.30
            + scores["mistake_callout"] * 0.25
            + scores["urgency"] * 0.20
            + scores["specificity"] * 0.25
        )
        if is_summary:
            composite *= 0.65  # heavy penalty for summary hooks
        
        # Find weakest/strongest dimension
        weakest = min(scores.items(), key=lambda kv: kv[1])[0]
        strongest = max(scores.items(), key=lambda kv: kv[1])[0]
        
        return GapAnalysis(
            hook=hook,
            overall_score=round(composite, 1),
            detected_type=detected_type,
            type_description=HOOK_TYPE_DESCRIPTIONS[detected_type],
            belief_challenge=round(scores["belief_challenge"], 1),
            mistake_callout=round(scores["mistake_callout"], 1),
            urgency=round(scores["urgency"], 1),
            specificity=round(scores["specificity"], 1),
            weakest_dimension=weakest,
            strongest_dimension=strongest,
            is_summary_pattern=is_summary,
            rationale=rationale,
        )
    
    def _llm_score(self, hook: str) -> Optional[dict]:
        """Use LLM to score the hook. Returns parsed JSON or None on failure."""
        system_prompt = (
            "You are a viral content expert who evaluates video hooks for their "
            "ability to create a 'competence gap' - a psychological need to keep watching. "
            "You score hooks across 4 dimensions and classify their type."
        )
        
        user_prompt = f"""Analyze this video hook for its competence gap strength:

HOOK: "{hook}"

Score the hook 0-100 on each dimension:
- belief_challenge: Does it challenge something the viewer believes is true?
- mistake_callout: Does it tell the viewer they're doing something wrong?
- urgency: Does it create an immediate psychological need to know more?
- specificity: Is it concrete and specific (vs vague summary)?

Classify the detected_type as one of:
- "summary" (weak, just states what's coming)
- "mistake_callout" (calls out a viewer error)
- "belief_destruction" (challenges a belief)
- "authority_anchor" (credentials + contrarian)
- "stake_reversal" (inverts expectation)
- "specificity" (named system/hidden asset)

Respond with ONLY valid JSON:
{{
  "belief_challenge": <0-100>,
  "mistake_callout": <0-100>,
  "urgency": <0-100>,
  "specificity": <0-100>,
  "detected_type": "<one of the types above>",
  "rationale": "<one sentence explaining the score>"
}}"""
        
        try:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=400,
                temperature=0.3,
                user_id=self._budget_user_id,
                plan=self._budget_plan,
                feature="hook_lab.score",
            )

            if not response.success:
                logger.warning(f"LLM hook scoring failed: {response.error}")
                return None
            
            text = response.text.strip()
            # Strip markdown code fences if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            return json.loads(text.strip())
        
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to parse LLM hook scoring: {e}")
            return None
    
    def _build_fallback_rationale(self, hook_type: HookType, is_summary: bool) -> str:
        """Build a rationale string when LLM is unavailable."""
        if is_summary:
            return "This is a summary hook - it tells viewers what's coming instead of opening a gap. Rewrite to challenge a belief or call out a mistake."
        return f"Detected as {hook_type.value}. {HOOK_TYPE_DESCRIPTIONS[hook_type]}"
    
    def _empty_analysis(self, hook: str) -> GapAnalysis:
        """Return an empty analysis for invalid input."""
        return GapAnalysis(
            hook=hook,
            overall_score=0.0,
            detected_type=HookType.SUMMARY,
            type_description="No hook provided.",
            belief_challenge=0.0,
            mistake_callout=0.0,
            urgency=0.0,
            specificity=0.0,
            weakest_dimension="all",
            strongest_dimension="none",
            is_summary_pattern=False,
            rationale="Empty hook provided.",
        )
    
    def rewrite_for_gap(
        self,
        weak_hook: str,
        video_topic: str,
        target_type: Optional[HookType] = None,
        count: int = 5,
    ) -> List[str]:
        """
        Rewrite a weak hook into N gap-engineered alternatives.
        If target_type is None, generates a mix of strong types.
        """
        if not weak_hook.strip():
            return []
        
        type_instruction = (
            f"Use the {target_type.value} pattern: {HOOK_TYPE_DESCRIPTIONS[target_type]}"
            if target_type else
            "Use a mix of strong patterns: mistake callout, belief destruction, stake reversal, or specificity."
        )
        
        system_prompt = (
            "You are a viral content writer. You rewrite weak summary-style hooks "
            "into strong hooks that create a 'competence gap' - a psychological need "
            "to keep watching. Strong hooks attack a viewer mistake, destroy a belief, "
            "or promise a specific named system."
        )
        
        user_prompt = f"""Rewrite this weak hook into {count} stronger alternatives.

ORIGINAL HOOK: "{weak_hook}"
VIDEO TOPIC: {video_topic}

INSTRUCTION: {type_instruction}

Rules:
- Each rewrite must open a competence gap (make the viewer NEED to keep watching)
- Be specific, not vague
- 8-15 words ideally
- No "Here are X tips" patterns
- No greetings or filler

Respond with ONLY a JSON array of {count} strings:
["hook 1", "hook 2", "hook 3", ...]"""
        
        try:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=600,
                temperature=0.85,
                user_id=self._budget_user_id,
                plan=self._budget_plan,
                feature="hook_lab.rewrite",
            )

            if not response.success:
                logger.warning(f"LLM hook rewrite failed: {response.error}")
                return self._fallback_rewrites(weak_hook, video_topic, count)
            
            text = response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            rewrites = json.loads(text.strip())
            if isinstance(rewrites, list):
                return [str(r).strip() for r in rewrites[:count] if str(r).strip()]
            return self._fallback_rewrites(weak_hook, video_topic, count)
        
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse rewrites: {e}")
            return self._fallback_rewrites(weak_hook, video_topic, count)
    
    def _fallback_rewrites(self, weak_hook: str, topic: str, count: int) -> List[str]:
        """Template-based fallback rewrites when LLM is unavailable."""
        topic_clean = topic.strip().rstrip(".")
        templates = [
            f"You've been doing {topic_clean} wrong - here's the proof",
            f"Everything you know about {topic_clean} is a myth",
            f"Stop {topic_clean} the old way. Here's what works in 2026",
            f"The {topic_clean} framework no one talks about",
            f"Why {topic_clean} isn't working for you (and the fix)",
            f"I've spent years on {topic_clean}. Here's the one thing that matters",
        ]
        return templates[:count]


# Module-level helpers
_lab: Optional[HookLab] = None

def get_hook_lab() -> HookLab:
    """Get the shared HookLab instance."""
    global _lab
    if _lab is None:
        _lab = HookLab()
    return _lab


def score_hook(hook: str) -> GapAnalysis:
    """Convenience function for scoring a single hook."""
    return get_hook_lab().score_gap(hook)


def rewrite_hook(
    hook: str,
    topic: str,
    target_type: Optional[HookType] = None,
    count: int = 5,
) -> List[str]:
    """Convenience function for rewriting a hook."""
    return get_hook_lab().rewrite_for_gap(hook, topic, target_type, count)
