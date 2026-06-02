from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from app.api.endpoints.scheduling import verify_cron_secret
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.database import get_db, AsyncSessionLocal
from app.models.trend import Trend
from app.models.trend_score import TrendScore
from app.models.content import ContentDraft, Persona
from app.schemas.generation import GenerateRequest, TweakRequest, DraftResponse
from app.services.generation.orchestrator import GenerationOrchestrator

router = APIRouter(prefix="/generation", tags=["generation"])
orchestrator = GenerationOrchestrator()

async def run_batch_generation_background():
    """Background task to fetch top 5 unresolved trends and generate drafts."""
    # Start fresh database session for background task safety
    async with AsyncSessionLocal() as db:
        try:
            # 1. Subquery trends that already have content drafts
            draft_trends_stmt = select(ContentDraft.trend_id).where(ContentDraft.trend_id.is_not(None))
            draft_trends_res = await db.execute(draft_trends_stmt)
            existing_trend_ids = set(draft_trends_res.scalars().all())
            
            # 2. Get latest TrendScore subquery
            latest_score_subq = select(
                TrendScore.trend_id,
                func.max(TrendScore.created_at).label("max_created")
            ).group_by(TrendScore.trend_id).subquery()
            
            # 3. Query trends with their scores
            stmt = select(Trend, TrendScore).join(
                TrendScore, Trend.id == TrendScore.trend_id
            ).join(
                latest_score_subq,
                (TrendScore.trend_id == latest_score_subq.c.trend_id) & (TrendScore.created_at == latest_score_subq.c.max_created)
            ).order_by(TrendScore.final_score.desc())
            
            res = await db.execute(stmt)
            all_trends = res.all()
            
            # Filter top 5 unresolved trends
            unresolved = []
            for trend, score in all_trends:
                if trend.id not in existing_trend_ids:
                    unresolved.append(trend)
                if len(unresolved) == 5:
                    break
                    
            if not unresolved:
                import logging
                logging.getLogger("branding_engine").info("No unresolved trends found for batch generation.")
                return
                
            # Default platforms: x, linkedin, threads, substack
            default_platforms = ["x", "linkedin", "threads", "substack"]
            
            for trend in unresolved:
                for platform in default_platforms:
                    try:
                        await orchestrator.generate_draft(
                            db=db,
                            trend_id=trend.id,
                            platform=platform
                        )
                    except Exception as e:
                        import logging
                        logging.getLogger("branding_engine").error(
                            f"Failed to generate batch draft for platform {platform} on trend {trend.id}: {e}"
                        )
        except Exception as e:
            import logging
            logging.getLogger("branding_engine").error(f"Batch generation pipeline error: {e}", exc_info=True)


@router.post("/trend/{trend_id}", response_model=List[DraftResponse])
async def generate_trend_drafts(
    trend_id: str,
    payload: GenerateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Generate drafts for a specific trend on specified platforms."""
    drafts = []
    for platform in payload.platforms:
        try:
            draft = await orchestrator.generate_draft(
                db=db,
                trend_id=trend_id,
                platform=platform,
                persona_id=payload.persona_id
            )
            drafts.append(draft)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Generation failed for platform {platform}: {str(e)}")
            
    return drafts

@router.post("/batch", status_code=status.HTTP_202_ACCEPTED)
async def generate_batch_drafts(
    background_tasks: BackgroundTasks,
    _ = Depends(verify_cron_secret)
):
    """Trigger background batch generation of drafts for the top 5 unresolved trends."""
    background_tasks.add_task(run_batch_generation_background)
    return {"status": "batch_generation_scheduled", "message": "Batch draft generation has been scheduled."}

@router.get("/drafts", response_model=List[DraftResponse])
async def list_drafts(
    status: Optional[str] = None,
    platform: Optional[str] = None,
    trend_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """List and filter content drafts with pagination support."""
    stmt = select(ContentDraft)
    
    if status:
        stmt = stmt.where(ContentDraft.status == status.upper())
    if platform:
        stmt = stmt.where(ContentDraft.platform == platform.lower())
    if trend_id:
        stmt = stmt.where(ContentDraft.trend_id == trend_id)
        
    stmt = stmt.order_by(ContentDraft.generated_at.desc()).offset(skip).limit(limit)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.put("/drafts/{draft_id}/regenerate", response_model=DraftResponse)
async def regenerate_draft(
    draft_id: str,
    payload: TweakRequest,
    db: AsyncSession = Depends(get_db)
):
    """Regenerate an existing draft utilizing specific tweak guidelines."""
    # Find draft
    stmt = select(ContentDraft).where(ContentDraft.id == draft_id)
    res = await db.execute(stmt)
    draft = res.scalars().first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
        
    try:
        # Re-run orchestrator generation flow using the feedback parameters
        new_draft_data = await orchestrator.generate_draft(
            db=db,
            trend_id=draft.trend_id,
            platform=draft.platform,
            persona_id=draft.persona_id,
            feedback=payload.feedback
        )
        
        # Merge contents and delete the newly created one to overwrite the existing one
        draft.content_text = new_draft_data.content_text
        draft.llm_metadata = new_draft_data.llm_metadata
        draft.status = "DRAFT" # Reset status to DRAFT on regeneration
        draft.generated_at = new_draft_data.generated_at
        
        # Clean up the duplicate draft created by generate_draft
        await db.delete(new_draft_data)
        await db.commit()
        
        return draft
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Regeneration failed: {str(e)}")
