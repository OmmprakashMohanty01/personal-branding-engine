import os
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db, AsyncSessionLocal
from app.models.scheduling import ScheduleConfig
from app.schemas.scheduling import (
    ScheduleAssignResponse,
    ScheduleDispatchResponse,
    ScheduleConfigCreate,
    ScheduleConfigResponse
)
from app.services.scheduling.queue import QueueManager
from app.services.scheduling.dispatch import DispatchService

logger = logging.getLogger("branding_engine.api.scheduling")

router = APIRouter(prefix="/scheduling", tags=["scheduling"])
queue_manager = QueueManager()
dispatch_service = DispatchService()

async def verify_cron_secret(x_cron_secret: str = Header(..., alias="X-Cron-Secret")):
    """Security dependency to verify X-Cron-Secret header matches API_CRON_SECRET env."""
    cron_secret = os.getenv("API_CRON_SECRET", "super_secret_cron_key_123")
    if x_cron_secret != cron_secret:
        logger.warning(f"Unauthorized scheduled dispatch trigger attempt with header: '{x_cron_secret[:5]}...'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid cron trigger secret."
        )

async def run_dispatch_background():
    """Background task to scan and execute mature publishes safely."""
    logger.info("Executing background dispatch for mature scheduled drafts.")
    async with AsyncSessionLocal() as db:
        try:
            await dispatch_service.dispatch_mature_posts(db)
        except Exception as e:
            logger.error(f"Error executing background scheduled dispatch: {e}", exc_info=True)


@router.post("/assign", response_model=ScheduleAssignResponse)
async def assign_optimal_times(db: AsyncSession = Depends(get_db)):
    """Triggers the QueueManager to assign optimal posting times to all approved, unscheduled drafts."""
    try:
        count = await queue_manager.assign_schedules(db)
        return {
            "status": "scheduled",
            "scheduled_count": count
        }
    except Exception as e:
        logger.error(f"Failed to assign posting schedules: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scheduling assignment failed: {str(e)}"
        )


@router.post("/dispatch", response_model=ScheduleDispatchResponse, status_code=status.HTTP_202_ACCEPTED)
async def dispatch_mature_schedules(
    background_tasks: BackgroundTasks,
    _ = Depends(verify_cron_secret)
):
    """Secure serverless dispatch webhook. Triggers background publication of mature schedules instantly."""
    background_tasks.add_task(run_dispatch_background)
    return {
        "status": "dispatch_scheduled",
        "message": "Dispatch of mature scheduled drafts has been successfully triggered in the background."
    }


@router.post("/configs", response_model=ScheduleConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_schedule_config(
    payload: ScheduleConfigCreate,
    db: AsyncSession = Depends(get_db)
):
    """Utility route to set or update posting schedules for a persona and platform."""
    try:
        # Check if active config already exists
        stmt = (
            select(ScheduleConfig)
            .where(
                ScheduleConfig.persona_id == payload.persona_id,
                ScheduleConfig.platform == payload.platform.lower(),
                ScheduleConfig.is_active == True
            )
        )
        res = await db.execute(stmt)
        config = res.scalars().first()
        
        if config:
            config.posting_times_json = payload.posting_times_json
            config.timezone = payload.timezone or "UTC"
            config.is_active = payload.is_active if payload.is_active is not None else True
        else:
            config = ScheduleConfig(
                persona_id=payload.persona_id,
                platform=payload.platform.lower(),
                posting_times_json=payload.posting_times_json,
                timezone=payload.timezone or "UTC",
                is_active=payload.is_active if payload.is_active is not None else True
            )
            db.add(config)
            
        await db.commit()
        await db.refresh(config)
        return config
    except Exception as e:
        logger.error(f"Failed to save ScheduleConfig: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to configure scheduling parameters: {str(e)}"
        )
