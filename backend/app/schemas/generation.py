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


class LLMGenerationOutput(BaseModel):
    """Internal model for parsing the expanded JSON output from Stage 1 LLM.

    Not exposed via API — fields are stored in llm_metadata.
    """

    content_text: str = Field(
        ...,
        description="The fully formatted post text",
    )
    requires_image: bool = Field(
        False,
        description="Whether the post needs an accompanying image",
    )
    image_prompt: Optional[str] = Field(
        None,
        description="Cinematic image description for Pollinations AI",
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

    model_config = ConfigDict(from_attributes=True)
