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

class LLMGenerationOutput(BaseModel):
    """Internal model for parsing the expanded JSON output from Stage 1 LLM.

    Not exposed via API — fields are stored in llm_metadata.
    """

    content_text: str = Field(
        ...,
        description="The fully formatted post text",
    )
    requires_image: bool = Field(
        True,
        description="Whether the post needs an accompanying image",
    )
    mermaid_diagram: Optional[str] = Field(
        None,
        description="Mermaid flowchart diagram code if visual diagram is needed",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Nested metadata containing post_type, hook_style, audience, goal, etc.",
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

