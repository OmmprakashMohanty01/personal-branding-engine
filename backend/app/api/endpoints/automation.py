import logging
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.generation.orchestrator import GenerationOrchestrator
from app.api.endpoints.generation import generate_metaphorical_image_helper
from app.schemas.generation import DraftResponse

router = APIRouter(prefix="/automation", tags=["Automation"])
logger = logging.getLogger("branding_engine.api.automation")

DAILY_SCHEDULE = {
    0: "AI News + Analysis",
    1: "Build in Public / Project Progress",
    2: "Technical Tutorial / Framework",
    3: "Career or Productivity Insight",
    4: "Tool or Software Review",
    5: "Weekly Wins or Lessons Learned"
}

@router.post("/daily-draft", response_model=DraftResponse)
async def generate_daily_draft(
    x_cron_secret: str = Header(..., description="API key to authorize Render Cron Job"),
    db: AsyncSession = Depends(get_db)
):
    """Secured endpoint to generate a daily draft based on the content strategy schedule."""
    # Verify CRON_SECRET_KEY
    expected_secret = os.getenv("CRON_SECRET_KEY")
    if not expected_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CRON_SECRET_KEY is not configured on the server."
        )
    if x_cron_secret != expected_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid Cron Secret Key."
        )
        
    weekday = datetime.today().weekday()
    if weekday == 6: # Sunday
        raise HTTPException(
            status_code=status.HTTP_200_OK,
            detail="Sunday: Rest day, no automated post draft generated."
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
