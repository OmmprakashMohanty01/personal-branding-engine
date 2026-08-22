import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.models.content import ContentDraft
from app.services.generation.pipeline import ContentGenerationPipeline
from app.services.generation.context import PipelineContext

logger = logging.getLogger("branding_engine.generation.orchestrator")

async def process_visuals_for_draft(draft: ContentDraft, context: PipelineContext):
    """
    Handles Phase 3: Image Generation & Semantic Quality Gate.
    Mutates the draft in-place with the final image and vision score.
    """
    if not context.requires_image:
        return

    from app.services.generation.router import generate_visuals
    from app.services.generation.vision_gate import evaluate_image_alignment
    
    max_retries = 2
    attempts = 0
    final_image_url = None
    final_vision_score = None
    final_vision_reason = None
    
    while attempts <= max_retries:
        logger.info(f"[ORCHESTRATOR] Generating visual (Attempt {attempts + 1}/{max_retries + 1})...")
        # Use fallback on first generation if telemetry says text gen fell back, otherwise normal.
        use_fallback = context.telemetry.fallback_provider_used if attempts == 0 else True 
        image_data_uri = await generate_visuals(draft.content_text, use_fallback=use_fallback)
        
        if not image_data_uri:
            logger.warning("[ORCHESTRATOR] generate_visuals returned None.")
            final_vision_reason = "Image generation failed to return an image."
            break
            
        # Evaluate image
        logger.info("[ORCHESTRATOR] Evaluating image with Vision Gate...")
        vision_result = await evaluate_image_alignment(draft.content_text, image_data_uri)
        
        final_vision_score = vision_result.get("score")
        final_vision_reason = vision_result.get("reason")
        passed = vision_result.get("passed", False)
        
        if passed:
            logger.info(f"[ORCHESTRATOR] Vision Gate PASSED! Score: {final_vision_score}")
            final_image_url = image_data_uri
            break
        else:
            logger.warning(f"[ORCHESTRATOR] Vision Gate FAILED. Reason: {final_vision_reason}")
            attempts += 1
    
    # Assign final results to draft
    if final_image_url:
        draft.llm_metadata["image_url"] = final_image_url
        draft.vision_score = final_vision_score
        draft.vision_reasoning = final_vision_reason
    else:
        logger.warning("[ORCHESTRATOR] Max retries exhausted or image generation completely failed. Downgrading to text-only.")
        draft.llm_metadata["image_url"] = None
        draft.llm_metadata["warning"] = f"Image generation degraded to text-only. Last Vision Gate reason: {final_vision_reason}"
        draft.vision_score = final_vision_score
        draft.vision_reasoning = final_vision_reason

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
            
            # The pipeline will use the passed draft and update its status to GENERATING
            draft = await pipeline.run(context)
            
            # --- PHASE 3: IMAGE GENERATION & SEMANTIC QUALITY GATE ---
            await process_visuals_for_draft(draft, context)
                    
            # Set final status
            draft.status = "DRAFT"
            
            # Since draft.llm_metadata is a JSON field, SQLAlchemy needs to know it was modified
            # if we updated it in place, but SQLAlchemy often tracks dictionary mutations if configured.
            # However, to be safe, reassign it.
            # Using dict() creates a shallow copy which triggers the update event.
            import copy
            draft.llm_metadata = copy.deepcopy(draft.llm_metadata)

            await db.commit()
            
            logger.info(f"[BACKGROUND WORKER] Completed for draft {draft_id}")

        except Exception as e:
            logger.error(f"[BACKGROUND WORKER] Failed for draft {draft_id}: {e}", exc_info=True)
            # Fetch draft again in case of detached instance
            draft = await db.get(ContentDraft, draft_id)
            if draft:
                draft.status = "FAILED"
                await db.commit()
