import httpx
import requests
import uuid
import os
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

@router.post("/generate-image", status_code=status.HTTP_200_OK)
async def generate_image_endpoint(
    payload: ImageGenerateRequest,
    request: Request
):
    """Generate a premium metaphorical illustration for a given topic using Hugging Face FLUX.1-schnell."""
    try:
        hf_api_key = os.getenv("HUGGINGFACE_API_KEY")
        if not hf_api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="HUGGINGFACE_API_KEY is missing from environment. Please add it to your .env file."
            )
        
        hf_api_key = hf_api_key.strip('"').strip("'")
        topic = payload.topic or "technology branding"
        draft_text = payload.draft_text or ""
        
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
        
        from google import genai
        gemini_key = os.getenv("GEMINI_API_KEY") or "mock_gemini_key"
        client = genai.Client(api_key=gemini_key)
        
        print(f"Generating dynamic image prompt via LLM for topic: {topic}")
        stage_1_prompt = f"{system_prompt}\n\nUser Input/Topic: {user_prompt}"
        interaction = client.interactions.create(
            model="gemini-3.5-flash",
            input=stage_1_prompt
        )
        prompt = interaction.output_text.strip().replace('"', "'")
        print(f"Generated prompt: {prompt}")

        headers = {"Authorization": f"Bearer {hf_api_key}"}
        hf_payload = {"inputs": prompt}
        MODEL_ID = "black-forest-labs/FLUX.1-schnell"
        hf_url = f"https://router.huggingface.co/hf-inference/models/{MODEL_ID}"

        print(f"Attempting to reach: {hf_url}")

        # Synchronous requests call to avoid macOS async DNS bug
        resp = requests.post(hf_url, json=hf_payload, headers=headers, timeout=30.0)
        
        print("Status:", resp.status_code)
        print("Body:", resp.text[:500])
        
        if resp.status_code == 503:
            raise HTTPException(
                status_code=503,
                detail="Hugging Face model is loading. Please try again in a few seconds."
            )
        
        if resp.status_code != 200:
            error_detail = resp.text
            try:
                error_detail = resp.json().get("error", resp.text)
            except:
                pass
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"Hugging Face API error: {error_detail}"
            )
        
        os.makedirs("static/images", exist_ok=True)
        
        filename = f"generated_{uuid.uuid4().hex}.jpg"
        filepath = os.path.join("static/images", filename)
        with open(filepath, "wb") as f:
            f.write(resp.content)
        
        base_url = str(request.base_url).rstrip("/")
        image_url = f"{base_url}/static/images/{filename}"
        return {"image_url": image_url}
            
    except HTTPException as he:
        print("IMAGE GEN ERROR TRACEBACK:", str(he.detail))
        raise he
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print("IMAGE GEN ERROR TRACEBACK:", str(e))
        print(tb)
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")

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
    except ValueError as e:
        traceback.print_exc()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Publishing failed: {str(e)}")
