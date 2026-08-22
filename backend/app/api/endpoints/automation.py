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
from app.schemas.generation import DraftResponse, AutomationResponse
from app.services.generation.context import PipelineContext
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


import sqlalchemy
from sqlalchemy.exc import IntegrityError

async def check_today_idempotency(db: AsyncSession, idempotency_key: str) -> Optional[ContentDraft]:
    """Check if a draft exists for the given idempotency key."""
    stmt = select(ContentDraft).where(ContentDraft.idempotency_key == idempotency_key)
    res = await db.execute(stmt)
    return res.scalars().first()

@router.post("/daily", response_model=AutomationResponse)
async def generate_daily(
    request: Request,
    cron_secret_key: Optional[str] = Query(None, alias="cron_secret_key"),
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
    x_run_id: Optional[str] = Header(None, alias="X-Run-ID"),
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

    now = datetime.datetime.now(datetime.timezone.utc)
    idempotency_key = f"daily-automation-{now.strftime('%Y-%m-%d')}"

    # Idempotency Check: max 1 post per calendar day
    existing_draft = await check_today_idempotency(db, idempotency_key)
    if existing_draft:
        if existing_draft.status == "PUBLISHED":
            logger.info("[DAILY AUTOMATION IDEMPOTENCY] Post already generated and published today. Skipping duplicate run.")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"detail": "Idempotency Guard: A post has already been generated and published today."},
            )
        elif existing_draft.status == "GENERATING":
            logger.warning("[DAILY AUTOMATION] Another generation process is currently running or crashed. Returning 429.")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Another automation process is currently running. Please try again later."},
            )
        # If DRAFT or FAILED, we fall through and retry publishing.
        logger.info(f"[DAILY AUTOMATION RESUMPTION] Found existing draft {existing_draft.id} with status {existing_draft.status}. Resuming publish.")

    if not existing_draft:
        try:
            # Create a placeholder to lock this date globally across all workers
            new_draft = ContentDraft(
                idempotency_key=idempotency_key,
                status="GENERATING",
                content_text="",
                platform="linkedin",
                generated_at=now,
                llm_metadata={}
            )
            db.add(new_draft)
            await db.commit()
            await db.refresh(new_draft)
            existing_draft = new_draft
        except IntegrityError:
            # Another request inserted the idempotency key exactly at the same time
            await db.rollback()
            logger.warning("[DAILY AUTOMATION CONCURRENCY] Concurrent request beat us to the idempotency key.")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Another automation process just started running. Please try again later."},
            )

    topic = DAILY_SCHEDULE.get(weekday)
    if not topic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No prompt mapped for today's weekday.",
        )

    run_id = x_run_id or str(uuid.uuid4())
    automation_start_time = datetime.datetime.now(datetime.timezone.utc)
    is_resumed_draft = False
    
    try:
        draft = existing_draft
        
        # Only run generation if we haven't generated yet
        if draft.status == "GENERATING" or not draft.content_text:
            pipeline = ContentGenerationPipeline()
            # We pass run_id as trace_id for downstream logging correlation
            context = PipelineContext(topic=topic, db=db, trace_id=run_id, draft=draft)
            
            # HARDCODE OVERRIDE: Force image generation for all daily automated posts
            context.requires_image = True
            
            # generate the draft and commit to db (checkpoint)
            draft = await pipeline.run(context, commit_db=True)
            
            from app.services.generation.orchestrator import process_visuals_for_draft
            await process_visuals_for_draft(draft, context)
            
            # Ensure run_id is persisted in llm_metadata
            meta = dict(draft.llm_metadata or {})
            meta["run_id"] = run_id
            draft.llm_metadata = meta
            
            import copy
            draft.llm_metadata = copy.deepcopy(draft.llm_metadata)
            await db.commit()
        else:
            is_resumed_draft = True

        
        if not settings.AUTO_PUBLISH_ENABLED:
            logger.info(f"[DAILY AUTOMATION] Auto-publish is disabled via AUTO_PUBLISH_ENABLED=False. Skipping publishing for {draft.id}. [RunID: {run_id}]")
            return AutomationResponse(
                status="draft_created",
                draft_id=draft.id,
                character_count=len(draft.content_text),
                image_uploaded=bool(draft.llm_metadata.get("image_url")),
                trace_id=run_id
            )
            
        if not settings.ENABLE_LINKEDIN_PUBLISHING:
            logger.info(f"[DAILY AUTOMATION] LinkedIn publishing is disabled via ENABLE_LINKEDIN_PUBLISHING=False. Skipping publishing for {draft.id}. [RunID: {run_id}]")
            return AutomationResponse(
                status="draft_created",
                draft_id=draft.id,
                character_count=len(draft.content_text),
                image_uploaded=bool(draft.llm_metadata.get("image_url")),
                trace_id=run_id
            )
        
        # publish! The orchestrator handles its own commit/rollback inside publish_draft
        publishing_orchestrator = PublishingOrchestrator()
        publish_start_time = datetime.datetime.now(datetime.timezone.utc)
        published_draft = await publishing_orchestrator.publish_draft(db, draft.id, trace_id=run_id)
        publish_latency_ms = (datetime.datetime.now(datetime.timezone.utc) - publish_start_time).total_seconds() * 1000
        automation_duration_ms = (datetime.datetime.now(datetime.timezone.utc) - automation_start_time).total_seconds() * 1000
        
        telemetry = draft.llm_metadata.get("telemetry", {})
        
        # Distinguishing Draft ID (payload PK) vs Idempotency Key (daily semantic lock)
        logger.info(
            f"[DAILY AUTOMATION SUCCESS] "
            f"[RunID: {run_id}] Draft: {draft.id}, IdempotencyKey: {draft.idempotency_key}, "
            f"IsResumed: {is_resumed_draft}, "
            f"Provider Latency: {telemetry.get('provider_latency_ms', 0)}ms, "
            f"Publish Latency: {publish_latency_ms:.1f}ms, "
            f"Total Duration: {automation_duration_ms:.1f}ms, "
            f"Retries: {telemetry.get('retry_count', 0)}, "
            f"Fallback: {telemetry.get('fallback_provider_used')}, "
            f"Status: {published_draft.status}"
        )
        metadata = published_draft.llm_metadata or {}
        return AutomationResponse(
            status=published_draft.status,
            draft_id=published_draft.id,
            linkedin_post_id=metadata.get("linkedin_post_id"),
            character_count=len(published_draft.content_text),
            image_uploaded=bool(metadata.get("image_url")),
            trace_id=run_id
        )
    except Exception as e:
        logger.error(f"[DAILY AUTOMATION ERROR] Failed daily generation: {e} [RunID: {run_id if 'run_id' in locals() else 'N/A'}]")
        # The pipeline and orchestrator handle their own atomic commits, so we rollback any uncommitted state
        await db.rollback()
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
            "trace_id": meta.get("trace_id") or meta.get("run_id"),
            "run_id": meta.get("run_id"),
        })
        
    return JSONResponse(status_code=200, content={"dashboard": dashboard_data})
