import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.content import Persona
from app.models.optimization import OptimizationFeedback
from app.schemas.optimization import OptimizationResponse, TuneRequest
from app.services.optimization.optimizer import PromptOptimizer

logger = logging.getLogger("branding_engine.api.optimization")

router = APIRouter(prefix="/optimization", tags=["optimization"])
optimizer_service = PromptOptimizer()


@router.post("/tune/{persona_id}", response_model=List[OptimizationResponse])
async def trigger_persona_tune(
    persona_id: str,
    payload: TuneRequest,
    db: AsyncSession = Depends(get_db)
):
    """Triggers the learning loop to analyze historical data and generate optimized system prompts for a persona."""
    # 1. Verify Persona exists
    persona_stmt = select(Persona).where(Persona.id == persona_id)
    persona_res = await db.execute(persona_stmt)
    persona = persona_res.scalars().first()
    if not persona:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Persona with ID {persona_id} not found."
        )
        
    # 2. Determine target platforms
    platforms = ["x", "linkedin", "threads", "substack"]
    if payload.platform:
        plat_lower = payload.platform.lower()
        if plat_lower not in platforms:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid platform '{payload.platform}'. Supported: {platforms}"
            )
        platforms = [plat_lower]
        
    created_optimizations = []
    for platform in platforms:
        try:
            feedback_rec = await optimizer_service.optimize_prompt(db, persona_id, platform)
            created_optimizations.append(feedback_rec)
        except Exception as e:
            logger.error(f"Optimization loop failed for persona {persona_id} on {platform}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Tuning failed for platform {platform}: {str(e)}"
            )
            
    return created_optimizations


@router.get("/history/{persona_id}", response_model=List[OptimizationResponse])
async def list_persona_tuning_history(
    persona_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Retrieves all past and active prompt modifications over time for a specific persona."""
    # 1. Verify Persona exists
    persona_stmt = select(Persona).where(Persona.id == persona_id)
    persona_res = await db.execute(persona_stmt)
    persona = persona_res.scalars().first()
    if not persona:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Persona with ID {persona_id} not found."
        )
        
    # 2. Retrieve history ordered by generated_at descending
    stmt = (
        select(OptimizationFeedback)
        .where(OptimizationFeedback.persona_id == persona_id)
        .order_by(OptimizationFeedback.generated_at.desc())
    )
    res = await db.execute(stmt)
    history = res.scalars().all()
    
    return history
