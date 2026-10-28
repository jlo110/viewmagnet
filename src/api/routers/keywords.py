"""GET /keywords/research: keyword opportunities for a seed phrase."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["keywords"])


@router.get("/keywords/research")
@limiter.limit(Tier.READ)
async def research_keywords(
    request: Request,
    query: str = Query(..., max_length=300),
    category: str = Query(default="general", max_length=50),
    current_user: User = Depends(get_current_user),
    max_results: int = Query(default=20),
):
    """Research keywords using ``KeywordResearchTool``."""
    try:
        from src.features.keyword_research import KeywordResearchTool

        tool = KeywordResearchTool()
        results = tool.generate_keywords(
            seed_keyword=query,
            num_keywords=max_results,
        )

        def competition_label(comp: float) -> str:
            if comp < 40:
                return "Low"
            elif comp < 70:
                return "Medium"
            return "High"

        def trend_string(direction: str, change: float) -> str:
            sign = "+" if change >= 0 else ""
            return f"{sign}{int(change)}%"

        return {
            "seed_keyword": query,
            "keywords": [
                {
                    "keyword": kw.keyword,
                    "search_volume": kw.search_volume,
                    "competition": competition_label(kw.competition),
                    "competition_score": kw.competition,
                    "trend": trend_string(kw.trend, kw.trend_change),
                    "trend_direction": kw.trend,
                    "difficulty": kw.competition,
                    "opportunity_score": kw.score,
                    "trend_change": kw.trend_change,
                    "avg_views": kw.avg_views,
                    "related": kw.related_keywords[:5] if kw.related_keywords else [],
                }
                for kw in results
            ],
            "total_found": len(results),
        }
    except Exception as e:
        logger.error(f"Keyword research failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
