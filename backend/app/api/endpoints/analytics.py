import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.database import get_db, AsyncSessionLocal
from app.models.content import ContentDraft, PostAnalytics
from app.schemas.analytics import (
    DashboardMetricsResponse,
    SyncResponse,
    PostWithAnalyticsResponse
)
from app.services.analytics.metrics import PipelineMetricsService
from app.services.analytics.syncer import EngagementSyncer

logger = logging.getLogger("branding_engine.api.analytics")

router = APIRouter(prefix="/analytics", tags=["analytics"])
metrics_service = PipelineMetricsService()

async def run_sync_background():
    """Background task to sync external engagement metrics."""
    logger.info("Starting background engagement metrics synchronization.")
    async with AsyncSessionLocal() as db:
        try:
            syncer = EngagementSyncer()
            await syncer.sync_engagement(db)
        except Exception as e:
            logger.error(f"Failed to execute background engagement sync: {str(e)}", exc_info=True)


@router.get("/dashboard", response_model=DashboardMetricsResponse)
async def get_dashboard_analytics(db: AsyncSession = Depends(get_db)):
    """Fetch pipeline dashboard metrics containing generation summaries and platform statistics."""
    try:
        metrics = await metrics_service.get_dashboard_metrics(db)
        return metrics
    except Exception as e:
        logger.error(f"Error retrieving dashboard metrics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dashboard metrics calculation failed: {str(e)}"
        )


@router.post("/sync", response_model=SyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_engagement_sync(background_tasks: BackgroundTasks):
    """Trigger the engagement synchronization process asynchronously in the background."""
    background_tasks.add_task(run_sync_background)
    return {
        "status": "sync_scheduled",
        "message": "Engagement synchronization has been scheduled in the background."
    }


@router.get("/posts", response_model=List[PostWithAnalyticsResponse])
async def list_posts_with_analytics(
    skip: int = 0,
    limit: int = 20,
    sort_by: Optional[str] = None,
    order: str = "desc",
    db: AsyncSession = Depends(get_db)
):
    """List paginated posts joined with their external engagement metrics.
    
    Query Parameters:
        - skip: number of records to skip (default: 0)
        - limit: max number of records to return (default: 20)
        - sort_by: field to sort by (options: likes, shares, comments, views, generated_at)
        - order: sort direction (asc, desc) (default: desc)
    """
    try:
        from sqlalchemy.orm import selectinload
        stmt = select(ContentDraft).options(selectinload(ContentDraft.analytics)).outerjoin(PostAnalytics, PostAnalytics.draft_id == ContentDraft.id)
        
        if sort_by:
            sort_by_lower = sort_by.lower()
            if sort_by_lower in ("likes", "views", "shares", "comments"):
                col = getattr(PostAnalytics, sort_by_lower)
                # Nulls can occur if a post doesn't have an analytics record yet
                # We can order with nulls last for desc order to show posts with actual metrics first.
                if order.lower() == "asc":
                    stmt = stmt.order_by(col.asc())
                else:
                    stmt = stmt.order_by(col.desc())
            elif sort_by_lower == "generated_at":
                if order.lower() == "asc":
                    stmt = stmt.order_by(ContentDraft.generated_at.asc())
                else:
                    stmt = stmt.order_by(ContentDraft.generated_at.desc())
            else:
                # Fallback if invalid sort field passed
                stmt = stmt.order_by(ContentDraft.generated_at.desc())
        else:
            # Default order
            stmt = stmt.order_by(ContentDraft.generated_at.desc())
            
        stmt = stmt.offset(skip).limit(limit)
        
        res = await db.execute(stmt)
        drafts = res.scalars().all()
        
        return drafts
    except Exception as e:
        logger.error(f"Error listing posts with analytics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Listing posts with analytics failed: {str(e)}"
        )
