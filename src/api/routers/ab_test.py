"""POST /ab-test/simulate: predict the winner of an A/B test."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["ab-test"])


class ABTestRequest(BaseModel):
    variation_a: str
    variation_b: str
    test_type: str = "title"  # title, thumbnail, description
    sample_size: int = 1000


@router.post("/ab-test/simulate")
@limiter.limit(Tier.LLM_HEAVY)
async def simulate_ab_test(
    request: Request,
    body: ABTestRequest,
    current_user: User = Depends(get_current_user),
):
    """Simulate an A/B test using ``ABTestSimulator`` (auth required)."""
    try:
        from src.features.ab_test_simulator import ABTestSimulator, TestType

        simulator = ABTestSimulator()
        ttype = TestType.THUMBNAIL if body.test_type == "thumbnail" else TestType.TITLE
        pair = [body.variation_a, body.variation_b]
        # Rubric COMPARISON (not a CTR prediction). The previous path called a
        # non-existent simulate()/a_ctr and always 500'd — this uses the real
        # rubric scorer and returns honest packaging scores + a disclaimer.
        result = (
            simulator.test_thumbnails(pair) if ttype == TestType.THUMBNAIL
            else simulator.test_titles(pair)
        )

        by_content = {v.content: v for v in result.variations}
        va = by_content.get(body.variation_a)
        vb = by_content.get(body.variation_b)
        a_score = round(va.score, 1) if va else 0.0
        b_score = round(vb.score, 1) if vb else 0.0

        return {
            "winner": "A" if a_score >= b_score else "B",
            "confidence": round(result.confidence, 1),
            "disclaimer": result.disclaimer,
            "variation_a": {
                "name": "A", "value": body.variation_a, "score": a_score,
                "strengths": va.strengths if va else [],
                "weaknesses": va.weaknesses if va else [],
            },
            "variation_b": {
                "name": "B", "value": body.variation_b, "score": b_score,
                "strengths": vb.strengths if vb else [],
                "weaknesses": vb.weaknesses if vb else [],
            },
            "recommendation": result.recommendation,
            "insights": result.insights,
        }
    except Exception as e:
        logger.error(f"A/B test simulation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
