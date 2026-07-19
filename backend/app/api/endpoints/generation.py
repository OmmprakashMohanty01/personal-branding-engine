import httpx
import urllib.parse
import asyncio
import requests
import uuid
import os
import json
import time
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.content import ContentDraft
from app.schemas.generation import GenerateRequest, DraftUpdatePayload, DraftResponse, ImageGenerateRequest
from app.services.generation.orchestrator import GenerationOrchestrator
from app.services.publishing.orchestrator import PublishingOrchestrator

router = APIRouter(prefix="/generation", tags=["Generation"])
logger = logging.getLogger("branding_engine.api.generation")
DEBUG_LOG_PATH = "/Users/ommprakashmohanty/personal-branding-engine/.cursor/debug-5139fb.log"


def _debug_log(location: str, message: str, data: dict, hypothesis_id: str) -> None:
    # #region agent log
    try:
        with open(DEBUG_LOG_PATH, "a") as f:
            f.write(json.dumps({
                "sessionId": "5139fb",
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
                "hypothesisId": hypothesis_id,
                "runId": "pre-fix",
            }) + "\n")
    except Exception:
        pass
    # #endregion
gen_orchestrator = GenerationOrchestrator()
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
    """Helper function to generate a base64 encoded metaphorical illustration image."""
    # #region agent log
    _debug_log(
        "generation.py:generate_metaphorical_image_helper",
        "Helper function invoked",
        {"topic": topic, "draft_text_len": len(draft_text) if draft_text else 0},
        "A",
    )
    # #endregion
    # Asynchronously call the FallbackLLMProvider to write the metaphorical image prompt dynamically
    system_prompt = """
You are a brilliant graphic designer creating thumbnails for a tech blog. 
Read the provided text and write a single, highly detailed image generation prompt (maximum 50 words). 

STRICT RECIPE:
1. Identify the core real-world subject (e.g., Switzerland, Apple, a specific law).
2. Identify the core technology (e.g., internet speed, geolocation, APIs).
3. You MUST visually combine a symbol of the subject with a symbol of the technology in a surreal or striking way.
4. Example: "A glowing fiber optic cable woven into the shape of the Swiss Alps, dark cinematic studio lighting, 8k resolution, macro photography."
5. DO NOT use generic floating glowing dots or plain data streams. Make it specific to the text.
"""
    user_prompt = f"Topic: {topic}\n\nDraft Text: {draft_text}"
    stage_1_prompt = f"{system_prompt}\n\nUser Input/Topic: {user_prompt}"
    
    print(f"Generating dynamic image prompt via LLM for topic: {topic}")
    try:
        from google import genai
        gemini_key = os.getenv("GEMINI_API_KEY") or "mock_gemini_key"
        client = genai.Client(api_key=gemini_key)
        
        interaction = client.interactions.create(
            model="gemini-3.5-flash",
            input=stage_1_prompt
        )
        prompt = interaction.output_text.strip().replace('"', "'")
    except Exception as gemini_err:
        logger.warning(f"[IMAGE GEN FALLBACK] Gemini rate limited, using Cohere for image prompt generation: {gemini_err}")
        try:
            import cohere
            cohere_key = os.getenv("COHERE_API_KEY") or "mock_cohere_key"
            co = cohere.AsyncClientV2(api_key=cohere_key)
            response = await co.chat(
                model="command-a-plus-05-2026",
                messages=[{"role": "user", "content": stage_1_prompt}]
            )
            prompt = next((block.text for block in response.message.content if hasattr(block, "text") and block.text), "").strip().replace('"', "'")
            if not prompt:
                raise ValueError("Empty Cohere response")
        except Exception as cohere_err:
            print(f"[IMAGE GEN FALLBACK FAIL] Both Gemini and Cohere failed: {cohere_err}. Using default prompt.")
            prompt = f"A high-quality, professional, cinematic illustration representing: {topic}"
    print(f"Generated prompt: {prompt}")

    # 1. URL-encode your LLM-generated prompt so it is safe for a web link
    encoded_prompt = urllib.parse.quote(prompt)

    # 2. Construct the keyless Pollinations URL
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"

    max_retries = 2
    for attempt in range(max_retries):
        start_time = time.perf_counter()
        try:
            # 3. Fetch the image asynchronously with shortened timeouts
            limits = httpx.Timeout(20.0, connect=5.0)
            async with httpx.AsyncClient(timeout=limits) as client:
                response = await client.get(image_url)
                
                # Log successful HTTP status and metadata
                logger.info(
                    "pollinations_response",
                    extra={
                        "status": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "content_length": len(response.content),
                        "attempt": attempt + 1,
                    }
                )
                
                # If the API fails, this safely triggers the exception block below
                response.raise_for_status() 
                
                # Validate content-type is an image
                content_type = response.headers.get("content-type", "")
                if not content_type.startswith("image/"):
                    logger.error(
                        f"Unexpected content type: {content_type}. Body: {response.text[:500]}"
                    )
                    raise ValueError(f"Unexpected content type: {content_type}")
                
                image_bytes = response.content
                duration = time.perf_counter() - start_time
                
                logger.info(
                    "Image generation succeeded.",
                    extra={
                        "event": "image_generation_success",
                        "provider": "Pollinations",
                        "duration_sec": duration,
                        "prompt_length": len(prompt),
                        "image_size_kb": len(image_bytes) / 1024,
                        "attempt": attempt + 1,
                        "max_retries": max_retries
                    }
                )
                
                import base64
                encoded_img = base64.b64encode(image_bytes).decode("utf-8")
                return f"data:image/jpeg;base64,{encoded_img}"

        except (httpx.TimeoutException, httpx.HTTPStatusError, ValueError) as e:
            duration = time.perf_counter() - start_time
            is_last_attempt = (attempt == max_retries - 1)
            
            # Treat ValueError (invalid content-type) and TimeoutException as transient/retryable
            is_transient = (
                isinstance(e, httpx.TimeoutException) 
                or isinstance(e, ValueError)
                or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code >= 500)
            )
            
            if is_last_attempt or not is_transient:
                if isinstance(e, httpx.TimeoutException):
                    logger.error(
                        "pollinations_timeout",
                        extra={
                            "event": "image_generation_timeout_fatal",
                            "provider": "Pollinations",
                            "duration_sec": duration,
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "error": str(e)
                        }
                    )
                    raise HTTPException(
                        status_code=504,
                        detail="Image generation request timed out. Please try again."
                    )
                elif isinstance(e, ValueError):
                    logger.error(
                        "pollinations_invalid_content_type_fatal",
                        extra={
                            "event": "image_generation_content_type_fatal",
                            "provider": "Pollinations",
                            "duration_sec": duration,
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "error": str(e)
                        }
                    )
                    raise HTTPException(
                        status_code=502,
                        detail=f"Image generation failed: {str(e)}"
                    )
                else:
                    logger.error(
                        "pollinations_http_error",
                        extra={
                            "event": "image_generation_http_error_fatal",
                            "provider": "Pollinations",
                            "duration_sec": duration,
                            "status_code": e.response.status_code,
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "body": e.response.text[:500]
                        }
                    )
                    status_code = 502 if e.response.status_code >= 500 else 400
                    raise HTTPException(
                        status_code=status_code,
                        detail="Image generation service is temporarily unavailable. Please try again."
                    )
            
            logger.warning(
                f"Transient error occurred during image generation ({e}).",
                extra={
                    "event": "image_generation_transient_error",
                    "provider": "Pollinations",
                    "duration_sec": duration,
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "error": str(e)
                }
            )
            await asyncio.sleep(1.0)

        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(
                "Image generation failed with unexpected error.",
                extra={
                    "event": "image_generation_error_fatal",
                    "provider": "Pollinations",
                    "duration_sec": duration,
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "error": str(e)
                }
            )
            raise HTTPException(
                status_code=500, 
                detail="Image generation failed due to a network error. Please try again."
            )


@router.post("/generate-image", status_code=status.HTTP_200_OK)
async def generate_image_endpoint(
    payload: ImageGenerateRequest,
    request: Request
):
    """Generate a premium metaphorical illustration for a given topic using Hugging Face FLUX.1-schnell."""
    # #region agent log
    _debug_log(
        "generation.py:generate_image_endpoint",
        "Endpoint handler invoked",
        {
            "topic": payload.topic,
            "draft_text_len": len(payload.draft_text) if payload.draft_text else 0,
            "content_type": request.headers.get("content-type"),
        },
        "A",
    )
    # #endregion
    try:
        topic = payload.topic or "technology branding"
        draft_text = payload.draft_text or ""
        image_url = await generate_metaphorical_image_helper(topic, draft_text)
        return {"image_url": image_url, "success": True}
            
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"image_url": None, "success": False, "error": "Image generation currently unavailable."}
        )

@router.post("", response_model=DraftResponse)
async def generate_content(
    payload: GenerateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Generate a LinkedIn post draft using Gemini and Cohere."""
    try:
        orchestrator = GenerationOrchestrator()
        draft = await orchestrator.generate_draft(
            db=db,
            topic=payload.topic,
            persona_id=payload.persona_id
        )
        if draft.llm_metadata:
            metadata = dict(draft.llm_metadata)
            metadata["model"] = "gemini-3.5-flash & cohere"
            draft.llm_metadata = metadata
        return draft
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

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
    db: AsyncSession = Depends(get_db)
):
    """Update the content text and optional image of a draft."""
    stmt = select(ContentDraft).where(ContentDraft.id == draft_id)
    res = await db.execute(stmt)
    draft = res.scalars().first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft.content_text = payload.content_text
    
    # Save image_url in llm_metadata
    metadata = dict(draft.llm_metadata or {})
    if payload.image_url is not None:
        metadata["image_url"] = payload.image_url
    draft.llm_metadata = metadata
    
    await db.commit()
    await db.refresh(draft)
    return draft

@router.post("/drafts/{draft_id}/publish", response_model=DraftResponse)
async def publish_draft_endpoint(
    draft_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Immediately publish a draft to LinkedIn."""
    import traceback
    try:
        # Real publishing path
        draft = await pub_orchestrator.publish_draft(db, draft_id)
        
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
