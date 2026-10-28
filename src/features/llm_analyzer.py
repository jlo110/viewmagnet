"""
LLM-powered feature analysis using Claude (with Groq fallback).

IMPORTANT: This does NOT replace the ML model. The LLM's job is to:
1. Take the ML model's SHAP values and benchmark comparisons
2. Translate them into clear, actionable human language
3. Generate title alternatives based on what YOUR DATA says works

The ML model drives the recommendations. The LLM explains them.
"""
import json
import structlog
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from src.config import get_settings
from src.features.llm_client import get_llm_client

logger = structlog.get_logger()

# Size of the training corpus the served content model was fit on
# (data/cache/exp_features.pkl). Surfaced in prompts so the claim stays
# truthful — update here (or wire to the model manifest) rather than
# hardcoding a number inside prompt strings.
TRAINING_CORPUS_SIZE = 144_641


@dataclass
class ModelDrivenExplanation:
    """LLM-generated explanation of ML model findings."""
    summary: str  # One-sentence summary
    key_findings: List[str]  # Top 3 data-driven findings
    specific_actions: List[str]  # What to do based on model
    confidence_explanation: str  # Why model is confident/not


class LLMAnalyzer:
    """
    LLM-powered explainer for ML model findings (Claude with Groq fallback).
    
    This does NOT replace ML - it explains ML findings in natural language.
    """
    
    def __init__(self):
        self.llm_client = get_llm_client()
        settings = get_settings()
        
        # Check if we have any LLM configured
        has_anthropic = bool(settings.anthropic_api_key)
        has_groq = bool(__import__('os').getenv("GROQ_API_KEY"))
        
        if has_anthropic or has_groq:
            logger.info(f"LLM Analyzer initialized (Anthropic: {has_anthropic}, Groq fallback: {has_groq})")
        else:
            logger.warning("No LLM API key configured - LLM features will use fallback")
    
    def explain_model_findings(
        self,
        prediction: str,
        score: int,
        confidence: float,
        shap_values: Dict[str, float],
        benchmark_comparisons: Dict[str, dict],
        category: str,
        similar_videos: List[dict] = None
    ) -> Optional[ModelDrivenExplanation]:
        """
        Translate ML model findings into human-readable explanations.
        
        Args:
            prediction: "ABOVE AVERAGE" or "BELOW AVERAGE"
            score: 0-100 prediction score
            confidence: Model confidence percentage
            shap_values: Feature importances from SHAP (what drives the prediction)
            benchmark_comparisons: How user compares to niche (from personalized_recommender)
            category: Video category for context
            similar_videos: Examples of similar successful videos
            
        Returns:
            ModelDrivenExplanation with human-readable findings
        """
        # Format SHAP values for the prompt
        shap_text = "\n".join([
            f"- {feat}: {val:+.3f} {'(helping)' if val > 0 else '(hurting)'}"
            for feat, val in sorted(shap_values.items(), key=lambda x: abs(x[1]), reverse=True)[:10]
        ])
        
        # Format benchmark comparisons
        benchmark_text = "\n".join([
            f"- {key}: User={comp.get('user', 'N/A')}, Category Avg={comp.get('category_avg', 'N/A')}, "
            f"Top 10%={comp.get('top_10', 'N/A')}, Gap={comp.get('gap', 'N/A')}"
            for key, comp in benchmark_comparisons.items()
        ])
        
        # Format similar videos
        similar_text = ""
        if similar_videos:
            similar_text = "\nSimilar successful videos in this niche:\n" + "\n".join([
                f"- \"{v.get('title', 'N/A')}\" ({v.get('views', 0):,} views, {v.get('performance_ratio', 1):.1f}x avg)"
                for v in similar_videos[:3]
            ])
        
        system_prompt = "You are an expert at explaining ML model findings to YouTube creators. Translate data into actionable advice."
        
        user_prompt = f"""IMPORTANT: Do NOT give generic YouTube advice. Only explain what THIS MODEL found from analyzing {TRAINING_CORPUS_SIZE:,} videos.

Model Prediction: {prediction} (Score: {score}/100, Confidence: {confidence:.0f}%)
Category: {category}

SHAP Feature Importances (what's driving the prediction):
{shap_text}

How user compares to {category} benchmarks:
{benchmark_text}
{similar_text}

Based ONLY on the data above, provide:
1. A one-sentence summary of why the model predicts {prediction}
2. The top 3 specific findings from the data (not generic advice)
3. 3 specific actions based on the benchmark gaps (with exact numbers)
4. Why the model confidence is {confidence:.0f}%

Respond as JSON:
{{
    "summary": "<one sentence explaining the prediction based on SHAP values>",
    "key_findings": [
        "<specific finding #1 from the data>",
        "<specific finding #2 from the data>",
        "<specific finding #3 from the data>"
    ],
    "specific_actions": [
        "<action based on specific benchmark gap with numbers>",
        "<action based on specific SHAP value>",
        "<action based on similar successful videos>"
    ],
    "confidence_explanation": "<why model confidence is what it is>"
}}

Only respond with valid JSON."""

        try:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=600,
                temperature=0.5
            )
            
            if not response.success:
                logger.warning(f"LLM explanation failed: {response.error}")
                return self._fallback_explanation(prediction, score, shap_values, benchmark_comparisons)
            
            logger.info(f"Explanation generated using {response.provider}/{response.model}")
            result = json.loads(response.text)
            
            return ModelDrivenExplanation(
                summary=result.get("summary", ""),
                key_findings=result.get("key_findings", []),
                specific_actions=result.get("specific_actions", []),
                confidence_explanation=result.get("confidence_explanation", "")
            )
            
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response", error=str(e))
            return self._fallback_explanation(prediction, score, shap_values, benchmark_comparisons)
        except Exception as e:
            logger.error("LLM explanation failed", error=str(e))
            return self._fallback_explanation(prediction, score, shap_values, benchmark_comparisons)
    
    def _fallback_explanation(
        self,
        prediction: str,
        score: int,
        shap_values: Dict[str, float],
        benchmark_comparisons: Dict[str, dict]
    ) -> ModelDrivenExplanation:
        """Generate explanation without LLM using rule-based approach."""
        
        # Find top positive and negative SHAP contributors
        sorted_shap = sorted(shap_values.items(), key=lambda x: x[1], reverse=True)
        top_positive = [f for f, v in sorted_shap if v > 0][:3]
        top_negative = [f for f, v in sorted_shap if v < 0][:3]
        
        # Find biggest benchmark gaps
        gaps = []
        for key, comp in benchmark_comparisons.items():
            if comp.get('gap') in ['below', 'way_below']:
                gaps.append(f"{key}: you have {comp.get('user')}, top 10% have {comp.get('top_10')}")
        
        findings = []
        if top_positive:
            findings.append(f"Strengths: {', '.join(top_positive[:2])}")
        if top_negative:
            findings.append(f"Weaknesses: {', '.join(top_negative[:2])}")
        if gaps:
            findings.append(f"Biggest gap vs top performers: {gaps[0]}")
        
        actions = []
        for gap in gaps[:3]:
            actions.append(f"Fix: {gap}")
        
        return ModelDrivenExplanation(
            summary=f"Model predicts {prediction} (score {score}) based on {len(top_negative)} weak features",
            key_findings=findings[:3],
            specific_actions=actions[:3],
            confidence_explanation="Model trained on 145K videos in this category"
        )
    
    def generate_model_driven_titles(
        self,
        original_title: str,
        category: str,
        benchmark_comparisons: Dict[str, dict],
        similar_successful_titles: List[str],
        shap_values: Dict[str, float] = None,
        count: int = 5
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Generate title alternatives based on what YOUR DATA says works.
        
        NOT generic title advice - specific to what the model found works in this niche.
        
        Args:
            original_title: Current title
            category: Video category
            benchmark_comparisons: How user compares to benchmarks
            similar_successful_titles: Actual titles that performed well in this niche
            shap_values: Optional SHAP values for title features
            count: Number of alternatives
            
        Returns:
            List of {title, reasoning, data_basis} dicts
        """
        # Extract what the data says works
        title_insights = []
        
        if 'title_length' in benchmark_comparisons:
            comp = benchmark_comparisons['title_length']
            title_insights.append(
                f"Title length: top 10% in {category} use {comp.get('top_10', 50)} chars "
                f"(user has {comp.get('user', 'N/A')})"
            )
        
        if 'has_number' in benchmark_comparisons:
            comp = benchmark_comparisons['has_number']
            title_insights.append(
                f"Numbers in title: {comp.get('top_10', '50%')} of top performers use numbers"
            )
        
        if 'has_question' in benchmark_comparisons:
            comp = benchmark_comparisons['has_question']
            title_insights.append(
                f"Questions: {comp.get('top_10', '20%')} of top performers use question format"
            )
        
        # Format SHAP insights for titles
        shap_text = ""
        if shap_values:
            title_shap = {k: v for k, v in shap_values.items() if 'title' in k.lower()}
            if title_shap:
                shap_text = "\n\nSHAP importance for title features:\n" + "\n".join([
                    f"- {feat}: {val:+.3f}" for feat, val in title_shap.items()
                ])
        
        system_prompt = "You are a YouTube title optimization expert that generates data-driven title suggestions."
        
        user_prompt = f"""Generate {count} improved titles for this YouTube video.

IMPORTANT: Base your suggestions on the DATA below, not generic advice.

Original title: "{original_title}"
Category: {category}

What the data says works in {category}:
{chr(10).join(title_insights)}
{shap_text}

Successful titles in this niche (to learn from):
{chr(10).join(f'- "{t}"' for t in similar_successful_titles[:8])}

Generate {count} alternatives that:
1. Match the patterns that WORK in this niche (based on data above)
2. Learn from the successful examples (structure, length, hooks)
3. Fix the specific gaps identified in the benchmarks

Respond as JSON array:
[
    {{
        "title": "<improved title>",
        "reasoning": "<why this matches what works in {category}>",
        "data_basis": "<which specific data point this addresses>"
    }}
]

Only respond with valid JSON array."""

        try:
            response = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=800,
                temperature=0.7
            )
            
            if not response.success:
                logger.warning(f"Title generation failed: {response.error}")
                return self._fallback_titles(original_title, benchmark_comparisons, similar_successful_titles)
            
            logger.info(f"Titles generated using {response.provider}/{response.model}")
            return json.loads(response.text)
            
        except Exception as e:
            logger.error("Title generation failed", error=str(e))
            return self._fallback_titles(original_title, benchmark_comparisons, similar_successful_titles)
    
    def _fallback_titles(
        self,
        original_title: str,
        benchmark_comparisons: Dict[str, dict],
        similar_titles: List[str]
    ) -> List[Dict[str, Any]]:
        """Rule-based title generation based on benchmark data."""
        
        suggestions = []
        
        # Learn from successful titles in the niche
        if similar_titles:
            # Find common patterns
            avg_length = sum(len(t) for t in similar_titles) / len(similar_titles)
            has_numbers = sum(1 for t in similar_titles if any(c.isdigit() for c in t)) / len(similar_titles)
            has_questions = sum(1 for t in similar_titles if '?' in t) / len(similar_titles)
            
            # Generate based on patterns
            topic = ' '.join(original_title.split()[:4])
            
            if has_numbers > 0.3 and not any(c.isdigit() for c in original_title):
                suggestions.append({
                    "title": f"7 {topic} Secrets That Actually Work",
                    "reasoning": f"{has_numbers*100:.0f}% of top videos in your niche use numbers",
                    "data_basis": "benchmark: number usage rate"
                })
            
            if has_questions > 0.15 and '?' not in original_title:
                suggestions.append({
                    "title": f"Why Does {topic} Work So Well?",
                    "reasoning": f"{has_questions*100:.0f}% of top videos use question format",
                    "data_basis": "benchmark: question usage rate"
                })
            
            if len(original_title) < avg_length * 0.8:
                suggestions.append({
                    "title": f"{original_title} - The Complete Guide for 2024",
                    "reasoning": f"Top titles average {avg_length:.0f} chars, yours has {len(original_title)}",
                    "data_basis": "benchmark: title length"
                })
        
        # Add variations from similar successful titles
        for similar in similar_titles[:2]:
            # Extract structure and apply to user's topic
            words = similar.split()
            if len(words) > 3:
                suggestions.append({
                    "title": f"Inspired by: {similar[:50]}",
                    "reasoning": "This title performed well in your niche",
                    "data_basis": "similar successful video"
                })
        
        return suggestions[:5]


def explain_prediction(
    prediction: str,
    score: int,
    confidence: float,
    shap_values: Dict[str, float],
    benchmark_comparisons: Dict[str, dict],
    category: str
) -> Optional[ModelDrivenExplanation]:
    """Convenience function to explain model findings."""
    analyzer = LLMAnalyzer()
    return analyzer.explain_model_findings(
        prediction, score, confidence, shap_values, benchmark_comparisons, category
    )


# ============================================================
# ALGORITHM SIGNALS (Start, Keep, Repeat)
# ============================================================
# Based on Chris Girbu's framework: every video is judged on 3 signals:
#   1. START - did people click to start watching? (~packaging: title + thumb)
#   2. KEEP - did they stay watching? (retention quality)
#   3. REPEAT - did they want to come back? (saves, shares, follows)
# A weak score on any one of these caps your potential reach.


@dataclass
class RecommendationCta:
    """A structured, deep-linkable recommendation.

    The historical ``recommendations: List[str]`` field shipped free text
    that the frontend had to regex-match to surface clickable links —
    fragile, hard to evolve, and prone to silent drift when copy changed.
    This shape lets the analyzer emit the same recommendation *with the
    deep link baked in*, so the UI just renders a button.

    Fields:
        label:   the human-readable text shown on the button/card.
        tool:    short id of the destination tool, e.g. ``"script_writer"``.
        href:    relative path the frontend should navigate to (already
                 includes query params so the destination tool can
                 pre-populate itself — see ``lib/deepLinks.ts``).
        context: optional structured context the destination tool can
                 read (e.g. framework=hype_heit, topic=...). Mostly here
                 for future tools that want richer pre-loaded state than
                 URL params can carry.
    """
    label: str
    tool: str
    href: str
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "tool": self.tool,
            "href": self.href,
            "context": self.context,
        }


@dataclass
class AlgorithmSignals:
    """The 3 algorithm signals that determine a video's reach."""
    start_score: float           # 0-100: ability to attract clicks
    keep_score: float            # 0-100: ability to retain attention
    repeat_score: float          # 0-100: ability to drive return behavior
    overall_score: float         # 0-100: weighted composite
    bottleneck: str              # which signal is the limiter ("start", "keep", "repeat", or "balanced")
    bottleneck_message: str      # human-friendly diagnostic
    recommendations: List[str]   # backward-compat free-text recs
    # Structured, deep-linkable form of the same recommendations. New
    # frontends should prefer this list — each item already encodes the
    # destination tool + URL params, so the UI doesn't have to regex-match
    # text. ``recommendations`` is kept in sync as a flat list of labels
    # so older clients still render something useful.
    recommendation_ctas: List[RecommendationCta] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_score": round(self.start_score, 1),
            "keep_score": round(self.keep_score, 1),
            "repeat_score": round(self.repeat_score, 1),
            "overall_score": round(self.overall_score, 1),
            "bottleneck": self.bottleneck,
            "bottleneck_message": self.bottleneck_message,
            "recommendations": self.recommendations,
            "recommendation_ctas": [c.to_dict() for c in self.recommendation_ctas],
        }


def compute_algorithm_signals(
    title_score: float,
    thumbnail_score: float,
    prediction_score: float,
    channel_score: Optional[float] = None,
    features: Optional[Dict[str, Any]] = None,
) -> AlgorithmSignals:
    """
    Compute the 3 algorithm signals from existing analysis output.
    
    Mappings (until we have direct retention/saves data):
    - START = title + thumbnail packaging (clickability)
    - KEEP = prediction_score (model-predicted retention proxy) + channel performance
    - REPEAT = blend of channel_score (return-viewer signal) + content novelty
    
    Args:
        title_score: 0-100 score for the title
        thumbnail_score: 0-100 score for the thumbnail
        prediction_score: 0-100 model prediction (proxy for retention)
        channel_score: 0-100 channel performance (proxy for repeat behavior)
        features: optional raw features dict for richer signal extraction
    """
    features = features or {}
    
    # START: weighted thumbnail (clicks happen on visual first), then title.
    start_score = (thumbnail_score * 0.6) + (title_score * 0.4)
    
    # KEEP: prediction is a learned proxy for full retention. Boost slightly with
    # channel performance because channels with retention history get the benefit
    # of the doubt from the algorithm.
    if channel_score is not None:
        keep_score = (prediction_score * 0.75) + (channel_score * 0.25)
    else:
        keep_score = prediction_score
    
    # REPEAT: derive from channel performance (return-viewer base) and a
    # novelty/specificity proxy from features (numeric/specific titles tend to
    # generate more saves and shares).
    novelty_boost = 0.0
    if features:
        if features.get("has_number", 0):
            novelty_boost += 8
        if features.get("title_specificity", 0):
            novelty_boost += float(features.get("title_specificity", 0)) * 0.2
        # Low channel hit rate = harder to drive repeat behavior
        hit_rate = features.get("channel_hit_rate")
        if isinstance(hit_rate, (int, float)) and hit_rate > 0:
            novelty_boost += min(15, hit_rate * 30)
    
    base_repeat = channel_score if channel_score is not None else (prediction_score * 0.7)
    repeat_score = max(0.0, min(100.0, base_repeat + novelty_boost))
    
    # Overall composite (algorithm weights all three roughly equally)
    overall_score = (start_score * 0.35) + (keep_score * 0.40) + (repeat_score * 0.25)
    
    # Find bottleneck - the lowest-scoring signal that's significantly behind
    scores = {
        "start": start_score,
        "keep": keep_score,
        "repeat": repeat_score,
    }
    min_signal = min(scores, key=scores.get)
    min_value = scores[min_signal]
    max_value = max(scores.values())
    
    if max_value - min_value < 8:
        bottleneck = "balanced"
        bottleneck_message = "All three signals are roughly aligned. Improve the weakest one to lift overall reach."
    else:
        bottleneck = min_signal
        bottleneck_messages = {
            "start": (
                "START is your bottleneck - your title/thumbnail aren't earning enough clicks. "
                "Even great content can't reach if nobody clicks. Fix packaging first."
            ),
            "keep": (
                "KEEP is your bottleneck - viewers click but drop off. "
                "Tighten your hook, cut dead air, and re-anchor curiosity every 15-30 seconds."
            ),
            "repeat": (
                "REPEAT is your bottleneck - viewers watch once but don't come back. "
                "Add named systems, shareable insights, and clear viewer-belief alignment."
            ),
        }
        bottleneck_message = bottleneck_messages[bottleneck]
    
    # Recommendations targeting the bottleneck. Each entry is a pair
    # of (free-text label, structured CTA) so we can ship both the
    # backward-compat ``recommendations`` list AND the new structured
    # ``recommendation_ctas`` list in one pass. The frontend prefers
    # the structured form; older clients still get readable text.
    # NOTE on hrefs (Week 9 Connected Tools fix): these MUST match the
    # actual React routes in ``frontend/client/src/App.tsx`` and the
    # tab query params each destination tool reads. Historical drift:
    #
    #   * Hook Lab lives as a TAB inside the Title Generator route,
    #     not a standalone ``/dashboard/hook-lab`` page.
    #   * The Script Writer route is ``/dashboard/scripts`` (plural)
    #     and the tab key is ``frameworks`` (plural), not ``framework``.
    #   * A/B Tester is ``/dashboard/ab-test`` (singular).
    #   * Loop Designer is ``/dashboard/loop-designer`` (the bare
    #     ``/loop`` route doesn't exist).
    #
    # Keeping these correct is non-negotiable because the structured
    # CTA path is what the Algorithm Signals card uses for every
    # bottleneck — a stale href turns the "recommendations" UI into a
    # set of 404s.
    cta_pairs: List[tuple] = []
    if bottleneck == "start":
        cta_pairs = [
            (
                "Engineer a stronger hook in Hook Lab",
                RecommendationCta(
                    label="Engineer a stronger hook",
                    tool="hook_lab",
                    href="/dashboard/titles?tab=hooks",
                    context={"reason": "start_bottleneck"},
                ),
            ),
            (
                "Generate thumbnail variations",
                RecommendationCta(
                    label="Generate thumbnail variations",
                    tool="thumbnail_generator",
                    href="/dashboard/thumbnails",
                    context={"reason": "start_bottleneck"},
                ),
            ),
            (
                "A/B test 3-5 packaging variations",
                RecommendationCta(
                    label="Set up an A/B test",
                    tool="ab_tester",
                    href="/dashboard/ab-test",
                    context={"reason": "start_bottleneck"},
                ),
            ),
        ]
    elif bottleneck == "keep":
        cta_pairs = [
            (
                "Cut dead air with the Pacing Analyzer",
                RecommendationCta(
                    label="Find dead-air segments",
                    tool="velocity",
                    href="/dashboard/velocity",
                    context={"reason": "keep_bottleneck"},
                ),
            ),
            (
                "Close the loop with Loop Designer",
                RecommendationCta(
                    label="Design a loop ending",
                    tool="loop_designer",
                    href="/dashboard/loop-designer",
                    context={"reason": "keep_bottleneck"},
                ),
            ),
            (
                "Try the Progressive Debunking framework (built for watch time)",
                RecommendationCta(
                    label="Try Progressive Debunking",
                    tool="script_writer",
                    href="/dashboard/scripts?tab=frameworks&framework=progressive_debunking&autoRun=1",
                    context={"framework": "progressive_debunking", "reason": "keep_bottleneck"},
                ),
            ),
        ]
    elif bottleneck == "repeat":
        cta_pairs = [
            (
                "Try the Lead Magnet framework (named-system + keyword DM)",
                RecommendationCta(
                    label="Try Lead Magnet",
                    tool="script_writer",
                    href="/dashboard/scripts?tab=frameworks&framework=hype_heit&autoRun=1",
                    context={"framework": "hype_heit", "reason": "repeat_bottleneck"},
                ),
            ),
            (
                "Name your insight with the Authority Myth-Buster framework",
                RecommendationCta(
                    label="Try Authority Myth-Buster",
                    tool="script_writer",
                    href="/dashboard/scripts?tab=frameworks&framework=authority_myth_buster&autoRun=1",
                    context={"framework": "authority_myth_buster", "reason": "repeat_bottleneck"},
                ),
            ),
            (
                "Run a Delta Shift script (built for save rate)",
                RecommendationCta(
                    label="Try Delta Shift",
                    tool="script_writer",
                    href="/dashboard/scripts?tab=frameworks&framework=delta_shift&autoRun=1",
                    context={"framework": "delta_shift", "reason": "repeat_bottleneck"},
                ),
            ),
        ]
    else:
        cta_pairs = [
            (
                "Run Hook Lab on your current title",
                RecommendationCta(
                    label="Open Hook Lab",
                    tool="hook_lab",
                    href="/dashboard/titles?tab=hooks",
                    context={"reason": "balanced"},
                ),
            ),
            (
                "Track pacing & loops with Velocity Tracker",
                RecommendationCta(
                    label="Open Velocity Tracker",
                    tool="velocity",
                    href="/dashboard/velocity",
                    context={"reason": "balanced"},
                ),
            ),
            (
                "Generate a viral-framework script",
                RecommendationCta(
                    label="Open Script Writer",
                    tool="script_writer",
                    href="/dashboard/scripts?tab=frameworks",
                    context={"reason": "balanced"},
                ),
            ),
        ]

    recommendations = [pair[0] for pair in cta_pairs]
    recommendation_ctas = [pair[1] for pair in cta_pairs]

    return AlgorithmSignals(
        start_score=start_score,
        keep_score=keep_score,
        repeat_score=repeat_score,
        overall_score=overall_score,
        bottleneck=bottleneck,
        bottleneck_message=bottleneck_message,
        recommendations=recommendations,
        recommendation_ctas=recommendation_ctas,
    )
