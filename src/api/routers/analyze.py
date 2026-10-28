"""POST /analyze: predict the performance of a YouTube video."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api._common import (
    AlgorithmSignalsResponse,
    StabilityWarning,
    _cache_analysis_for_alerts,
    check_usage_limit,
)
from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.connection import get_session
from src.database.models import User, UserVideoAnalysis

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["analyze"])


class AnalyzeRequest(BaseModel):
    """Request to analyze a video."""
    url: str
    channel_id: Optional[str] = None  # For channel context


class AnalyzeResponse(BaseModel):
    """Response from video analysis."""
    video_id: str
    title: str
    prediction_score: float
    prediction_tier: str  # mode-scoped label (see `mode`)
    title_score: float
    thumbnail_score: float
    channel_score: Optional[float] = None
    explanations: list
    recommendations: list
    niche_comparison: dict
    # Honest framing of what this analysis actually claims
    mode: str = "evaluation"  # coaching | detection | evaluation
    score_label: str = "Performance vs your channel"
    headline: str = ""
    disclaimer: Optional[str] = None
    stability_warning: Optional[StabilityWarning] = None
    algorithm_signals: Optional[AlgorithmSignalsResponse] = None


@router.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit(Tier.MEDIA_HEAVY)
async def analyze_video_endpoint(
    request: Request,
    analyze_request: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
):
    """Analyze a YouTube video and predict performance.

    Requires authentication. Heavy ML/IO work runs in a thread pool so the
    event loop stays responsive for other requests.

    Pipeline:
      1. Fetch video metadata from the YouTube API
      2. Extract title features (length, hooks, emotion, embeddings)
      3. Download + analyze thumbnail (face, colors, composition)
      4. Pull channel context (hit rate, momentum, history)
      5. Run ML prediction with the trained gradient-boosted model
      6. Generate heuristic, feature-driven explanations
         (NOTE: not real SHAP -- the gradient boosted predictor is stable
         enough that we use threshold-based feature attributions; track
         ``#shap-todo`` to integrate ``shap.TreeExplainer`` later.)
      7. Return actionable recommendations
    """
    from src.api.analyze import analyze_video

    user_id = current_user.id
    request.state.current_user = current_user

    # Check usage limits (includes referral bonus).
    with get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()
        can_analyze, message = check_usage_limit(user, session)
        if not can_analyze:
            raise HTTPException(status_code=403, detail=message)

    try:
        # analyze_video is CPU+IO heavy; offload to a thread pool.
        result = await asyncio.to_thread(
            analyze_video, analyze_request.url, analyze_request.channel_id
        )

        stability_warning = None

        with get_session() as session:
            cutoff_date = datetime.utcnow() - timedelta(days=7)
            previous_analyses = session.query(UserVideoAnalysis).filter(
                UserVideoAnalysis.user_id == user_id,
                UserVideoAnalysis.video_id == result.video_id,
                UserVideoAnalysis.analyzed_at >= cutoff_date,
            ).order_by(UserVideoAnalysis.analyzed_at.desc()).all()

            analysis_count = len(previous_analyses) + 1

            if analysis_count >= 4:
                stability_warning = StabilityWarning(
                    level="high",
                    message=f"You've analyzed this video {analysis_count} times in 7 days.",
                    recommendation=(
                        "Frequent re-analysis suggests over-optimization. Your "
                        "title/thumbnail need time to gather real viewer data. "
                        "Wait at least 3-7 days before analyzing again."
                    ),
                    analysis_count=analysis_count,
                )
            elif analysis_count >= 2 and previous_analyses:
                last_analysis = previous_analyses[0]
                days_since_last = (
                    (datetime.utcnow() - last_analysis.analyzed_at).days
                    if last_analysis.analyzed_at
                    else 7
                )
                if days_since_last <= 2:
                    stability_warning = StabilityWarning(
                        level="medium",
                        message=f"You've analyzed this video {analysis_count} times recently.",
                        recommendation=(
                            "Sometimes the best advice is to wait. Give your video "
                            "time to gather real data before re-optimizing."
                        ),
                        analysis_count=analysis_count,
                    )

            explanations_json = json.dumps(result.explanations) if result.explanations else None
            recommendations_json = json.dumps(result.recommendations) if result.recommendations else None

            analysis = UserVideoAnalysis(
                user_id=user_id,
                video_id=result.video_id,
                video_url=analyze_request.url,
                title=result.title,
                prediction_score=result.prediction_score,
                prediction_tier=result.prediction_tier,
                title_score=result.title_score,
                thumbnail_score=result.thumbnail_score,
                shap_explanations=explanations_json,
                recommendations=recommendations_json,
                analyzed_at=datetime.utcnow(),
            )
            session.add(analysis)

            user = session.query(User).filter(User.id == user_id).first()
            if user:
                user.analyses_this_month += 1
                user.analyses_today += 1
                user.last_analysis_at = datetime.utcnow()

            session.commit()

        # Cache for the alerts engine.
        if analyze_request.channel_id:
            _cache_analysis_for_alerts(
                channel_id=analyze_request.channel_id,
                video_id=result.video_id,
                analysis_result={
                    "score": result.prediction_score,
                    "video_title": result.title,
                    "video_id": result.video_id,
                    "niche_comparison": (
                        result.niche_comparison.model_dump()
                        if hasattr(result.niche_comparison, "model_dump")
                        else result.niche_comparison
                    ),
                    "trajectory": (
                        result.niche_comparison.model_dump()
                        if hasattr(result.niche_comparison, "model_dump")
                        else {}
                    ),
                    "component_scores": {
                        "title_effectiveness": result.title_score,
                        "thumbnail_impact": result.thumbnail_score,
                    },
                },
            )

        algorithm_signals = None
        try:
            from src.features.llm_analyzer import compute_algorithm_signals

            signals = compute_algorithm_signals(
                title_score=result.title_score,
                thumbnail_score=result.thumbnail_score,
                prediction_score=result.prediction_score,
                channel_score=result.channel_score,
                features=result.features,
            )
            algorithm_signals = AlgorithmSignalsResponse(**signals.to_dict())
        except Exception as e:
            logger.warning(f"Failed to compute algorithm signals: {e}")

        return AnalyzeResponse(
            video_id=result.video_id,
            title=result.title,
            prediction_score=result.prediction_score,
            prediction_tier=result.prediction_tier,
            title_score=result.title_score,
            thumbnail_score=result.thumbnail_score,
            channel_score=result.channel_score,
            explanations=result.explanations,
            recommendations=result.recommendations,
            niche_comparison=result.niche_comparison,
            mode=result.mode,
            score_label=result.score_label,
            headline=result.headline,
            disclaimer=result.disclaimer,
            stability_warning=stability_warning,
            algorithm_signals=algorithm_signals,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
