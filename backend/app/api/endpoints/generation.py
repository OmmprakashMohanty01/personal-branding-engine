import httpx
import urllib.parse
import asyncio
import uuid
import os
import json
import time
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.content import ContentDraft
from app.schemas.generation import GenerateRequest, DraftUpdatePayload, DraftResponse, ImageGenerateRequest
from app.services.generation.context import PipelineContext
from app.services.generation.orchestrator import run_pipeline_background
from app.services.publishing.orchestrator import PublishingOrchestrator
from datetime import datetime, timezone

router = APIRouter(prefix="/generation", tags=["Generation"])
logger = logging.getLogger("branding_engine.api.generation")
    # #endregion
pub_orchestrator = PublishingOrchestrator()

@router.get("/live-news", response_model=List[str])
async def get_live_news():
    """Fetch the top 5 trending story titles from Hacker News API."""
    try:
        async with httpx.AsyncClient() as client:
            top_stories_resp = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=5.0)
            top_stories_resp.raise_for_status()
            story_ids = top_stories_resp.json()[:5]
            
            titles = []
            for story_id in story_ids:
                item_resp = await client.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout=3.0)
                if item_resp.status_code == 200:
                    item_data = item_resp.json()
                    title = item_data.get("title")
                    if title:
                        titles.append(title)
            return titles
    except Exception as e:
        # Fallback to standard presets if network request fails
        return [
            "Why simple codebases scale better than complex distributed microservices",
            "A review of using Groq's high-speed inference engine for real-time applications",
            "How consistency and authentic sharing beats high-production templates on LinkedIn",
            "How modern developer AI agents are changing team dynamics and shipping speeds"
        ]

async def generate_metaphorical_image_helper(topic: str, draft_text: str) -> str:
    """Generate an image using the Visual Director and Gemini Image API."""
    from app.services.generation.router import generate_visuals

    logger.info(f"[IMAGE GEN] Requesting Visual Router for topic '{topic}'...")
    image_url = await generate_visuals(draft_text)
    
    if not image_url:
        raise HTTPException(
            status_code=502,
            detail="Image generation service is temporarily unavailable or Visual Director decided no image was needed."
        )
    
    return image_url


@router.post("/generate-image", status_code=status.HTTP_200_OK)
async def generate_image_endpoint(
    payload: ImageGenerateRequest,
    request: Request,
    x_run_id: Optional[str] = Header(None, alias="X-Run-ID")
):
    """Generate a premium metaphorical illustration for a given topic using Hugging Face FLUX.1-schnell."""
    run_id = x_run_id or f"manual_img_{int(time.time())}"
    logger.debug(f"generate_image_endpoint invoked for topic: {payload.topic} [RunID: {run_id}]")
    try:
        topic = payload.topic or "technology branding"
        draft_text = payload.draft_text or ""
        image_url = await generate_metaphorical_image_helper(topic, draft_text)
        return {"status": "success", "image_url": image_url, "message": "Image generated successfully"}
            
    except Exception as e:
        logger.error(f"Image generation failed: {e} [RunID: {run_id}]")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "error", "image_url": None, "message": "Image generation currently unavailable."}
        )

@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def generate_content(
    payload: GenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_run_id: Optional[str] = Header(None, alias="X-Run-ID")
):
    """Generate a LinkedIn post draft asynchronously."""
    run_id = x_run_id or f"manual_gen_{int(time.time())}"
    logger.info(f"Manual generation started for topic: {payload.topic} [RunID: {run_id}]")
    try:
        # Create pending draft
        draft = ContentDraft(
            persona_id=payload.persona_id,
            platform="linkedin",
            content_text="",
            status="GENERATING",
            generated_at=datetime.now(timezone.utc),
            llm_metadata={"topic": payload.topic, "trace_id": run_id}
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)

        # Queue the heavy generation task
        background_tasks.add_task(run_pipeline_background, str(draft.id), payload.topic, payload.persona_id, run_id)
        
        return {"message": "Draft generation started", "draft_id": str(draft.id), "status": "GENERATING"}
    except Exception as e:
        logger.error(f"Failed to start generation: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed to start: {str(e)}")

@router.get("/drafts", response_model=List[DraftResponse])
async def list_drafts(
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """List all drafts in the system."""
    stmt = select(ContentDraft)
    if status_filter:
        stmt = stmt.where(ContentDraft.status == status_filter.upper())
    stmt = stmt.order_by(ContentDraft.generated_at.desc()).offset(skip).limit(limit)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.get("/drafts/{draft_id}", response_model=DraftResponse)
async def get_draft(
    draft_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Fetch a single content draft by UUID."""
    stmt = select(ContentDraft).where(ContentDraft.id == draft_id)
    res = await db.execute(stmt)
    draft = res.scalars().first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft

@router.put("/drafts/{draft_id}", response_model=DraftResponse)
async def update_draft(
    draft_id: str,
    payload: DraftUpdatePayload,
    db: AsyncSession = Depends(get_db),
    x_run_id: Optional[str] = Header(None, alias="X-Run-ID")
):
    """Update the content text and optional image of a draft."""
    run_id = x_run_id or f"manual_upd_{int(time.time())}"
    logger.info(f"Updating draft {draft_id} [RunID: {run_id}]")
    stmt = select(ContentDraft).where(ContentDraft.id == draft_id)
    res = await db.execute(stmt)
    draft = res.scalars().first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    # Truncation Protection
    old_len = len(draft.content_text) if draft.content_text else 0
    new_len = len(payload.content_text) if payload.content_text else 0
    
    if old_len > 500 and new_len < (old_len * 0.4):
        logger.error(f"[TRUNCATION BLOCKED] UI attempted to truncate draft from {old_len} to {new_len} chars.")
        raise HTTPException(
            status_code=422,
            detail=f"Suspicious truncation detected. The new text ({new_len} chars) is less than 40% of the original text ({old_len} chars). If this is intentional, please edit in smaller chunks."
        )
        
    draft.content_text = payload.content_text
    
    from sqlalchemy.orm.attributes import flag_modified
    
    # Save image_url in llm_metadata
    metadata = dict(draft.llm_metadata or {})
    if payload.image_url is not None:
        metadata["image_url"] = payload.image_url
    draft.llm_metadata = metadata
    flag_modified(draft, "llm_metadata")
    
    await db.commit()
    await db.refresh(draft)
    return draft

@router.post("/drafts/{draft_id}/publish", response_model=DraftResponse)
async def publish_draft_endpoint(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    x_run_id: Optional[str] = Header(None, alias="X-Run-ID")
):
    """Immediately publish a draft to LinkedIn."""
    run_id = x_run_id or f"manual_pub_{int(time.time())}"
    logger.info(f"Manual publish initiated for {draft_id} [RunID: {run_id}]")
    import traceback
    try:
        # Real publishing path
        draft = await pub_orchestrator.publish_draft(db, draft_id, trace_id=run_id)
        
        # Check for local image URL gracefully in real publishing path (just in case)
        image_url = (draft.llm_metadata or {}).get("image_url")
        if image_url and ("localhost" in image_url or "127.0.0.1" in image_url):
            print(f"Warning: Local image URL detected in real publish: {image_url}. External APIs cannot download this.")

        return draft
    except HTTPException:
        raise
    except ValueError as e:
        traceback.print_exc()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Publishing failed: {str(e)}")
