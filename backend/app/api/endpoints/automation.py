import logging
import os
import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.generation.orchestrator import GenerationOrchestrator
from app.api.endpoints.generation import generate_metaphorical_image_helper
from app.schemas.generation import DraftResponse

router = APIRouter(prefix="/automation", tags=["Automation"])
logger = logging.getLogger("branding_engine.api.automation")

DAILY_SCHEDULE = {
    0: "Write an engaging post analyzing a piece of breaking AI news.",
    1: "Write a 'Build in Public' post about a coding challenge.",
    2: "Write a Technical Tutorial or Framework breakdown.",
    3: "Write a Career or Productivity Insight for software engineers.",
    4: "Write a Tool or Software Review.",
    5: "Write about Weekly Wins or Lessons Learned."
}

@router.post("/daily-draft", response_model=DraftResponse)
async def generate_daily_draft(
    request: Request,
    cron_secret_key: Optional[str] = Query(None, alias="cron_secret_key"),
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
    db: AsyncSession = Depends(get_db)
):
    """Secured endpoint to generate a daily draft based on the content strategy schedule."""
    logger.info(
        "Automation endpoint reached",
        extra={
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        },
    )
    # Verify API_CRON_SECRET or CRON_SECRET_KEY
    expected_secret = os.getenv("CRON_SECRET_KEY") or os.getenv("API_CRON_SECRET")
    logger.info(
        "CRON SECRET DEBUG",
        extra={
            "has_secret": expected_secret is not None,
            "length": len(expected_secret) if expected_secret else 0,
            "starts_with": expected_secret[:6] if expected_secret else None,
        },
    )
    if not expected_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CRON_SECRET_KEY is not configured on the server."
        )
        
    # Get secret from header or query parameters
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
    
    logger.info(
        "REQUEST SECRET",
        extra={
            "provided_length": len(provided_secret) if provided_secret else 0,
            "provided_prefix": provided_secret[:6] if provided_secret else None,
        },
    )
    
    if not provided_secret or provided_secret != expected_secret:
        logger.warning(
            "[DAILY AUTOMATION] Unauthorized access attempt - missing or invalid cron secret key.",
            extra={
                "client_ip": request.client.host if request.client else None,
                "has_provided_secret": bool(provided_secret),
                "provided_length": len(provided_secret) if provided_secret else 0,
                "expected_length": len(expected_secret) if expected_secret else 0,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid Cron Secret Key."
        )
        
    # Determine the day of the week
    weekday = datetime.datetime.today().weekday()
    if weekday == 6: # Sunday
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"detail": "Sunday: Rest day, no post generated today."}
        )
        
    topic = DAILY_SCHEDULE.get(weekday)
    if not topic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No prompt mapped for today's weekday."
        )
        
    logger.info(f"[DAILY AUTOMATION] Triggered for weekday {weekday}. Selected Topic: {topic}")
    
    try:
        orchestrator = GenerationOrchestrator()
        
        # 1. Generate the text draft using sequential LLM pipeline
        draft = await orchestrator.generate_draft(
            db=db,
            topic=topic,
            persona_id=None # Default persona
        )
        
        # 2. Generate the metaphorical image illustration using the helper
        try:
            image_url = await generate_metaphorical_image_helper(topic, draft.content_text)
            
            # Save image_url in llm_metadata
            metadata = dict(draft.llm_metadata or {})
            metadata["image_url"] = image_url
            metadata["model"] = "gemini-3.5-flash & cohere"
            draft.llm_metadata = metadata
            
            # Commit image attachment to database
            await db.commit()
            await db.refresh(draft)
            logger.info("[DAILY AUTOMATION] Metaphorical image successfully generated and saved to draft metadata.")
        except Exception as img_err:
            logger.error(f"[DAILY AUTOMATION] Image generation failed, proceeding with text-only draft: {img_err}")
            
        return draft
    except Exception as e:
        logger.error(f"[DAILY AUTOMATION ERROR] Failed daily generation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Daily automation draft generation failed: {str(e)}"
        )
