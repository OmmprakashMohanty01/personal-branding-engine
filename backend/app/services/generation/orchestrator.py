"""
orchestrator.py
===============
Synchronous generation orchestrator — replaces the old BackgroundTasks pattern.

Provides `run_pipeline_sync()` as the single entry point for both manual
and automated generation. Manages an explicit database state machine:

    PENDING → GENERATING → DRAFT_READY → MEDIA_UPLOADING → MEDIA_VALIDATED

Each state transition is committed to the database immediately so that
crashes at any point leave a recoverable breadcrumb.
"""

import copy
import logging
import time
import traceback

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentDraft
from app.services.generation.pipeline import ContentGenerationPipeline
from app.services.generation.context import PipelineContext

logger = logging.getLogger("branding_engine.generation.orchestrator")


async def _update_draft_status(db: AsyncSession, draft: ContentDraft, new_status: str):
    """Atomically update draft status and commit."""
    draft.status = new_status
    await db.commit()
    await db.refresh(draft)
    logger.info(f"[STATE MACHINE] Draft {draft.id} → {new_status}")


async def process_visuals_for_draft(draft: ContentDraft, context: PipelineContext, db: AsyncSession):
    """
    Handles image generation using the simplified Pollinations + Pillow router.
    Updates draft status through MEDIA_UPLOADING → MEDIA_VALIDATED.
    Mutates the draft in-place with the final image URL.
    """
    if not context.requires_image:
        return

    # ── MEDIA_UPLOADING ──
    await _update_draft_status(db, draft, "MEDIA_UPLOADING")

    from app.services.generation.router import generate_visuals

    img_start = time.time()
    logger.info("[ORCHESTRATOR] Generating visual via simplified router...")

    # Use fallback (skip Pollinations, go straight to Pillow) if text gen already fell back
    use_fallback = bool(context.telemetry.fallback_provider_used)
    draft_data = {
        "quote_hook": context.quote_hook,
        "post_content": draft.content_text,
    }
    image_data_uri = await generate_visuals(draft_data, use_fallback=use_fallback)

    context.telemetry.image_generation_latency_ms = round((time.time() - img_start) * 1000, 2)

    if image_data_uri:
        logger.info(f"[ORCHESTRATOR] Visual generated successfully in {context.telemetry.image_generation_latency_ms}ms")
        draft.llm_metadata = copy.deepcopy(draft.llm_metadata or {})
        draft.llm_metadata["image_url"] = image_data_uri
    else:
        logger.warning("[ORCHESTRATOR] Visual generation returned None. Proceeding as text-only.")
        draft.llm_metadata = copy.deepcopy(draft.llm_metadata or {})
        draft.llm_metadata["image_url"] = None
        draft.llm_metadata["warning"] = "Image generation failed. Publishing as text-only."

    # ── MEDIA_VALIDATED ──
    await _update_draft_status(db, draft, "MEDIA_VALIDATED")


async def run_pipeline_sync(
    db: AsyncSession,
    draft: ContentDraft,
    topic: str,
    persona_id: str | None,
    trace_id: str,
) -> ContentDraft:
    """Synchronous pipeline execution — the single entry point for generation.

    Runs the full generation + visual pipeline inline (no BackgroundTasks).
    Manages explicit state transitions committed to DB at each step.

    State machine:
        PENDING → GENERATING → DRAFT_READY → MEDIA_UPLOADING → MEDIA_VALIDATED

    Args:
        db: Active database session.
        draft: Pre-created ContentDraft record (status=PENDING).
        topic: The topic/prompt for content generation.
        persona_id: Optional persona UUID.
        trace_id: Correlation ID for logging.

    Returns:
        The fully updated ContentDraft with status=MEDIA_VALIDATED (or DRAFT_READY if no image).

    Raises:
        Exception: Re-raises any pipeline error after marking the draft as FAILED.
    """
    logger.info(f"[SYNC PIPELINE] Started for draft {draft.id}, topic: '{topic}', trace: {trace_id}")

    try:
        # ── GENERATING ──
        await _update_draft_status(db, draft, "GENERATING")

        pipeline = ContentGenerationPipeline()
        context = PipelineContext(
            topic=topic,
            db=db,
            persona_id=persona_id,
            trace_id=trace_id,
            draft=draft,
        )
        context.requires_image = True

        # Run the LLM generation pipeline (commits internally)
        draft = await pipeline.run(context, commit_db=True)

        # ── DRAFT_READY ──
        await _update_draft_status(db, draft, "DRAFT_READY")

        # ── PHASE 2: IMAGE GENERATION ──
        await process_visuals_for_draft(draft, context, db)

        logger.info(
            f"[SYNC PIPELINE] Completed for draft {draft.id}. "
            f"Final status: {draft.status}"
        )
        return draft

    except Exception as e:
        logger.error(f"[SYNC PIPELINE CRASH] Pipeline failed for draft {draft.id}: {e}")
        logger.error(traceback.format_exc())

        # Mark as FAILED — try to commit, but don't crash if DB is broken
        try:
            draft.status = "FAILED"
            # Store the failure stage in metadata for diagnostics
            meta = copy.deepcopy(draft.llm_metadata or {})
            meta["failure_error"] = str(e)
            draft.llm_metadata = meta
            await db.commit()
            await db.refresh(draft)
        except Exception as db_err:
            logger.error(f"[SYNC PIPELINE] Failed to mark draft as FAILED: {db_err}")

        raise
