"""
automation.py
=============
Automated Content Draft & Daily Publishing Endpoint with Idempotency,
Constant-Time Secret Authentication, and Pipeline Integration.
"""

import datetime
import hmac
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import text

from app.api.endpoints.generation import generate_metaphorical_image_helper
from app.config import settings
from app.database import get_db
from app.models.content import ContentDraft
from app.schemas.generation import DraftResponse
from app.services.generation.context import PipelineContext
from app.services.generation.orchestrator import GenerationOrchestrator
from app.services.generation.pipeline import ContentGenerationPipeline
from app.services.publishing.orchestrator import PublishingOrchestrator

router = APIRouter(prefix="/automation", tags=["Automation"])
logger = logging.getLogger("branding_engine.api.automation")

DAILY_SCHEDULE = {
    0: "Write an engaging post analyzing a piece of breaking AI news.",
    1: "Write a 'Build in Public' post about a coding challenge.",
    2: "Write a Technical Tutorial or Framework breakdown.",
    3: "Write a Career or Productivity Insight for software engineers.",
    4: "Write a Tool or Software Review.",
    5: "Write about Weekly Wins or Lessons Learned.",
}


def verify_cron_secret(
    request: Request,
    cron_secret_key: Optional[str] = None,
    x_cron_secret: Optional[str] = None,
) -> None:
    """Verify Cron Secret using constant-time comparison to prevent timing attacks."""
    expected_secret = settings.CRON_SECRET_KEY or settings.API_CRON_SECRET or os.getenv("CRON_SECRET_KEY") or os.getenv("API_CRON_SECRET")
    if not expected_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CRON_SECRET_KEY is not configured on the server.",
        )

    provided_secret = (
        x_cron_secret
        or cron_secret_key
        or request.headers.get("cron_secret_key")
        or request.headers.get("CRON_SECRET_KEY")
        or request.headers.get("x-cron-secret-key")
        or request.headers.get("x-cron-secret")
        or request.query_params.get("cron_secret_key")
        or request.query_params.get("CRON_SECRET_KEY")
        or request.query_params.get("cron_secret")
    )

    is_valid = (
        provided_secret is not None
        and expected_secret is not None
        and hmac.compare_digest(provided_secret.encode("utf-8"), expected_secret.encode("utf-8"))
    )

    if not is_valid:
        logger.warning("[DAILY AUTOMATION] Unauthorized access attempt - missing or invalid cron secret key.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid Cron Secret Key.",
        )


async def check_today_idempotency(db: AsyncSession) -> bool:
    """Check if a draft or post has already been generated today (max 1/day limit)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    today_start = datetime.datetime(now.year, now.month, now.day, tzinfo=datetime.timezone.utc)

    stmt = select(func.count(ContentDraft.id)).where(ContentDraft.generated_at >= today_start)
    res = await db.execute(stmt)
    count = res.scalar() or 0

    return count > 0


@router.post("/daily", response_model=DraftResponse)
async def generate_daily(
    request: Request,
    cron_secret_key: Optional[str] = Query(None, alias="cron_secret_key"),
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
    db: AsyncSession = Depends(get_db),
):
    """Production automated daily generation endpoint with idempotency checks and pipeline execution."""
    verify_cron_secret(request, cron_secret_key, x_cron_secret)

    weekday = datetime.datetime.today().weekday()
    if weekday == 6:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"detail": "Sunday: Rest day, no post generated today."},
        )

    # Idempotency Check: max 1 post per calendar day
    already_generated = await check_today_idempotency(db)
    if already_generated:
        logger.info("[DAILY AUTOMATION IDEMPOTENCY] Post already generated today. Skipping duplicate run.")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"detail": "Idempotency Guard: A post has already been generated today."},
        )

    topic = DAILY_SCHEDULE.get(weekday)
    if not topic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No prompt mapped for today's weekday.",
        )

    try:
        trace_id = str(uuid.uuid4())
        
        # Advisory lock: Ensure only one automation job runs globally at a time
        lock_acquired = await db.execute(text(f"SELECT pg_try_advisory_xact_lock({settings.AUTOMATION_DAILY_PUBLISH_LOCK_ID})"))
        if not lock_acquired.scalar():
            logger.warning(f"[DAILY AUTOMATION] Another generation process is currently running. Dropping request. trace_id={trace_id}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Another automation process is currently running. Please try again later."},
            )

        pipeline = ContentGenerationPipeline()
        context = PipelineContext(topic=topic, db=db, trace_id=trace_id)
        
        # generate the draft but do not commit to db (flush instead)
        draft = await pipeline.run(context, commit_db=False)
        
        if not settings.AUTO_PUBLISH_ENABLED:
            logger.info(f"[DAILY AUTOMATION] Auto-publish is disabled via AUTO_PUBLISH_ENABLED=False. Committing draft {draft.id} without publishing. trace_id={trace_id}")
            await db.commit()
            return draft
            
        if not settings.ENABLE_LINKEDIN_PUBLISHING:
            logger.info(f"[DAILY AUTOMATION] LinkedIn publishing is disabled via ENABLE_LINKEDIN_PUBLISHING=False. Committing draft {draft.id} without publishing. trace_id={trace_id}")
            await db.commit()
            return draft
        
        # publish directly within the same transaction to guarantee atomicity
        publishing_orchestrator = PublishingOrchestrator()
        published_draft = await publishing_orchestrator.publish_draft(db, draft.id, trace_id=trace_id)
        
        logger.info(
            f"[DAILY AUTOMATION SUCCESS] "
            f"Trace: {context.trace_id}, Draft: {draft.id}, "
            f"Provider Latency: {context.telemetry.provider_latency_ms}ms, "
            f"Retries: {context.telemetry.retry_count}, "
            f"Fallback: {context.telemetry.fallback_provider_used}, "
            f"Status: {published_draft.status}"
        )
        return published_draft
    except Exception as e:
        logger.error(f"[DAILY AUTOMATION ERROR] Failed daily generation: {e}")
        # Explicitly rollback the transaction if an error occurs to maintain atomicity
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Daily automation draft generation failed: {str(e)}",
        )


@router.post("/daily-draft", response_model=DraftResponse)
async def generate_daily_draft(
    request: Request,
    cron_secret_key: Optional[str] = Query(None, alias="cron_secret_key"),
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
    db: AsyncSession = Depends(get_db),
):
    """Backward-compatible endpoint for legacy GitHub Actions daily draft workflow."""
    verify_cron_secret(request, cron_secret_key, x_cron_secret)

    weekday = datetime.datetime.today().weekday()
    if weekday == 6:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"detail": "Sunday: Rest day, no post generated today."},
        )

    topic = DAILY_SCHEDULE.get(weekday)
    if not topic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No prompt mapped for today's weekday.",
        )

    try:
        orchestrator = GenerationOrchestrator()
        draft = await orchestrator.generate_draft(db=db, topic=topic, persona_id=None)

        try:
            image_url = await generate_metaphorical_image_helper(topic, draft.content_text)
            metadata = dict(draft.llm_metadata or {})
            metadata["image_url"] = image_url
            draft.llm_metadata = metadata

            await db.commit()
            await db.refresh(draft)
        except Exception as img_err:
            logger.error(f"[DAILY AUTOMATION] Image generation failed: {img_err}")

        return draft
    except Exception as e:
        logger.error(f"[DAILY AUTOMATION ERROR] Failed daily generation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Daily automation draft generation failed: {str(e)}",
        )

@router.get("/dashboard")
async def get_automation_dashboard(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, description="Number of recent automations to retrieve"),
):
    """Retrieve a summary of recent daily automation runs for operational monitoring."""
    stmt = select(ContentDraft).order_by(ContentDraft.generated_at.desc()).limit(limit)
    res = await db.execute(stmt)
    drafts = res.scalars().all()
    
    dashboard_data = []
    for d in drafts:
        meta = d.llm_metadata or {}
        telemetry = meta.get("telemetry", {})
        
        dashboard_data.append({
            "draft_id": d.id,
            "status": d.status,
            "topic": d.topic,
            "generated_at": d.generated_at.isoformat() if d.generated_at else None,
            "published": d.status == "PUBLISHED",
            "linkedin_urn": meta.get("linkedin_post_id"),
            "published_url": meta.get("published_url"),
            "image_generated": bool(meta.get("image_url")),
            "fallback_used": telemetry.get("fallback_provider_used"),
            "retries": telemetry.get("retry_count", 0),
            "generation_time_ms": telemetry.get("total_duration_ms", 0),
            "trace_id": meta.get("trace_id"),
        })
        
    return JSONResponse(status_code=200, content={"dashboard": dashboard_data})
