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
    visual_type: str = Field(..., description="Must be a valid visual category (e.g. EDITORIAL_PHOTOGRAPHY, CONCEPTUAL_SCENE)")
    core_subject: str = Field(...)
    visual_metaphor: str = Field(...)
    scene: str = Field(...)
    composition: str = Field(...)
    lighting: str = Field(...)
    style: str = Field(...)
    negative_prompt: str = Field(...)

class PlatformDrafts(BaseModel):
    linkedin: str = Field(..., description="The LinkedIn post text broken into short, punchy paragraphs (max 3 sentences per paragraph).")
    reddit_title: str = Field(default="", description="Direct, technical, non-clickbait Reddit title.")
    reddit_body: str = Field(default="", description="In-depth technical breakdown in Markdown for engineering subreddits.")
    x: str = Field(default="", description="Punchy standalone post or hook under 280 characters.")
    medium_title: str = Field(default="", description="Compelling long-form engineering essay title.")
    medium_body: str = Field(default="", description="Comprehensive Markdown article with headers, takeaways, and code snippets.")
    dev_to_title: str = Field(default="", description="Developer-focused title.")
    dev_to_body: str = Field(default="", description="Markdown technical article with tags and code blocks.")

    # Backward compatibility: expose 'reddit' as alias for reddit_body
    @property
    def reddit(self) -> str:
        return self.reddit_body

class LLMContentDraft(BaseModel):
    drafts: PlatformDrafts
    self_check: str = Field(...)
    quote_hook: str = Field(
        ..., 
        description="A powerful 10-15 word quote extracted directly from the post to be used as a typographic image card."
    )
    target_subreddit: str = Field(default="ExperiencedDevs", description="Target technical subreddit.")
    tags: List[str] = Field(default=["python", "devops", "programming"], description="Tags for Medium and Dev.to articles.")



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
    publish_statuses: Optional[Dict[str, Any]] = None

