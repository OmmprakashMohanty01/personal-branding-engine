from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field


class GenerateRequest(BaseModel):
    topic: str
    persona_id: Optional[str] = None


class ImageGenerateRequest(BaseModel):
    topic: str
    draft_text: Optional[str] = None


class DraftUpdatePayload(BaseModel):
    content_text: str
    image_url: Optional[str] = None

class VisualStrategyOutput(BaseModel):
    """Output schema for the Visual Strategy Agent."""
    primary_concept: str = Field(..., description="The main concept or idea from the article.")
    secondary_concept: str = Field(..., description="A supporting concept or theme.")
    mood: str = Field(..., description="The emotional tone or mood.")
    visual_metaphor: str = Field(..., description="A visual metaphor representing the concepts.")
    image_prompt: str = Field(..., description="The final cinematic image prompt for Pollinations AI.")

class VisualDirection(BaseModel):
    """Output schema for the Visual Director."""
    visual_type: str = Field(..., description="Must be 'editorial_photo', 'diagram', or 'quote_card'")
    subject: str = Field(...)
    scene: str = Field(...)
    concept: str = Field(...)
    composition: str = Field(...)
    lighting: str = Field(...)
    style: str = Field(...)
    negative_prompt: str = Field(...)

class LLMContentDraft(BaseModel):
    paragraphs: List[str] = Field(
        ..., 
        description="The finished LinkedIn post text broken into an array of 3 to 4 short, punchy paragraphs."
    )
    self_check: str = Field(...)
    quote_hook: str = Field(
        ..., 
        description="A powerful 10-15 word quote extracted directly from the post to be used as a typographic image card."
    )


class DraftResponse(BaseModel):
    id: str
    persona_id: Optional[str] = None
    content_text: str
    status: str
    generated_at: datetime
    llm_metadata: Dict[str, Any]
    vision_score: Optional[int] = None
    vision_reasoning: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AutomationResponse(BaseModel):
    """Strict schema for automation endpoint responses to ensure successful end-to-end execution."""
    status: str
    draft_id: str
    linkedin_post_id: Optional[str] = None
    character_count: int
    image_uploaded: bool
    trace_id: str

