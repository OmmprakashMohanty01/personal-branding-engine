import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.models.content import ContentDraft
from app.services.generation.pipeline import ContentGenerationPipeline
from app.services.generation.context import PipelineContext

logger = logging.getLogger("branding_engine.generation.orchestrator")

async def run_pipeline_background(draft_id: str, topic: str, persona_id: str, trace_id: str):
    """
    Background worker to execute the generation pipeline.
    This runs after the initial 202 Accepted response.
    """
    logger.info(f"[BACKGROUND WORKER] Started for draft {draft_id}, topic: '{topic}'")
    
    async with AsyncSessionLocal() as db:
        try:
            # Re-fetch the draft to ensure it exists
            draft = await db.get(ContentDraft, draft_id)
            if not draft:
                logger.error(f"[BACKGROUND WORKER] Draft {draft_id} not found in DB!")
                return
                
            pipeline = ContentGenerationPipeline()
            context = PipelineContext(
                topic=topic,
                db=db,
                persona_id=persona_id,
                trace_id=trace_id,
                draft=draft
            )
            
            # The pipeline will use the passed draft and update its status
            await pipeline.run(context)
            logger.info(f"[BACKGROUND WORKER] Completed for draft {draft_id}")

        except Exception as e:
            logger.error(f"[BACKGROUND WORKER] Failed for draft {draft_id}: {e}", exc_info=True)
            # Fetch draft again in case of detached instance
            draft = await db.get(ContentDraft, draft_id)
            if draft:
                draft.status = "FAILED"
                await db.commit()
