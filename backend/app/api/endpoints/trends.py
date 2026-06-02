from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from app.api.endpoints.scheduling import verify_cron_secret
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.database import get_db, AsyncSessionLocal
from app.models.trend import Trend
from app.models.trend_score import TrendScore
from app.schemas.trends import TrendResponse
from app.services.trends.connectors import (
    GitHubTrendSource,
    HackerNewsSource,
    ProductHuntSource,
    RedditTrendSource,
    GoogleTrendsSource,
    NewsAPITrendSource
)
from app.services.trends.aggregator import TrendAggregator

router = APIRouter(prefix="/trends", tags=["trends"])

async def run_refresh_background():
    """Background task runner for discovery aggregation."""
    # Create instances of connectors
    connectors = [
        GitHubTrendSource(),
        HackerNewsSource(),
        ProductHuntSource(),
        RedditTrendSource(),
        GoogleTrendsSource(),
        NewsAPITrendSource()
    ]
    
    aggregator = TrendAggregator(connectors)
    scored_trends = await aggregator.aggregate_and_score()
    
    # Establish a fresh session for background worker thread safety
    async with AsyncSessionLocal() as db:
        try:
            await aggregator.save_to_db(db, scored_trends)
        except Exception as e:
            import logging
            logging.getLogger("branding_engine").error(f"Background refresh failed: {e}", exc_info=True)

def _build_latest_score_subquery():
    """Build subquery to filter only the latest score record per trend."""
    return select(
        TrendScore.trend_id,
        func.max(TrendScore.created_at).label("max_created")
    ).group_by(TrendScore.trend_id).subquery()

@router.get("", response_model=List[TrendResponse])
async def get_trends(
    topic: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve trends with pagination and topic filtering, sorted by publication time."""
    subq = _build_latest_score_subquery()
    
    stmt = select(Trend, TrendScore).join(
        TrendScore, Trend.id == TrendScore.trend_id
    ).join(
        subq,
        (TrendScore.trend_id == subq.c.trend_id) & (TrendScore.created_at == subq.c.max_created)
    )
    
    if topic:
        stmt = stmt.where(Trend.topic == topic)
        
    stmt = stmt.order_by(Trend.published_at.desc()).offset(skip).limit(limit)
    res = await db.execute(stmt)
    results = res.all()
    
    response = []
    for trend, score in results:
        response.append(
            TrendResponse(
                id=trend.id,
                canonical_url=trend.canonical_url,
                title=trend.title,
                summary=trend.summary,
                topic=trend.topic,
                published_at=trend.published_at,
                metadata_json=trend.metadata_json,
                final_score=score.final_score,
                raw_score=score.raw_score
            )
        )
    return response

@router.get("/top", response_model=List[TrendResponse])
async def get_top_trends(
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """Get the highest scoring trends based on final_score."""
    subq = _build_latest_score_subquery()
    
    stmt = select(Trend, TrendScore).join(
        TrendScore, Trend.id == TrendScore.trend_id
    ).join(
        subq,
        (TrendScore.trend_id == subq.c.trend_id) & (TrendScore.created_at == subq.c.max_created)
    ).order_by(TrendScore.final_score.desc()).limit(limit)
    
    res = await db.execute(stmt)
    results = res.all()
    
    response = []
    for trend, score in results:
        response.append(
            TrendResponse(
                id=trend.id,
                canonical_url=trend.canonical_url,
                title=trend.title,
                summary=trend.summary,
                topic=trend.topic,
                published_at=trend.published_at,
                metadata_json=trend.metadata_json,
                final_score=score.final_score,
                raw_score=score.raw_score
            )
        )
    return response

@router.get("/{trend_id}", response_model=TrendResponse)
async def get_trend_by_id(
    trend_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get single trend detail by ID."""
    subq = _build_latest_score_subquery()
    
    stmt = select(Trend, TrendScore).join(
        TrendScore, Trend.id == TrendScore.trend_id
    ).join(
        subq,
        (TrendScore.trend_id == subq.c.trend_id) & (TrendScore.created_at == subq.c.max_created)
    ).where(Trend.id == trend_id)
    
    res = await db.execute(stmt)
    result = res.first()
    if not result:
        raise HTTPException(status_code=404, detail="Trend not found")
        
    trend, score = result
    return TrendResponse(
        id=trend.id,
        canonical_url=trend.canonical_url,
        title=trend.title,
        summary=trend.summary,
        topic=trend.topic,
        published_at=trend.published_at,
        metadata_json=trend.metadata_json,
        final_score=score.final_score,
        raw_score=score.raw_score
    )

@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_trends(
    background_tasks: BackgroundTasks,
    _ = Depends(verify_cron_secret)
):
    """Trigger background execution of the trend aggregator."""
    background_tasks.add_task(run_refresh_background)
    return {"status": "refresh_scheduled", "message": "Aggregation has been scheduled in the background."}
