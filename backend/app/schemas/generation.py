from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class GenerateRequest(BaseModel):
    platforms: List[str]
    persona_id: Optional[str] = None

class TweakRequest(BaseModel):
    feedback: str

class GeneratedPost(BaseModel):
    content_text: str
    requires_image: bool
    image_prompt: Optional[str] = None

class DraftResponse(BaseModel):
    id: str
    trend_id: Optional[str] = None
    persona_id: Optional[str] = None
    platform: str
    content_text: str
    status: str
    image_url: Optional[str] = None
    generated_at: datetime
    llm_metadata: Dict[str, Any]
    feedback_notes: Optional[str] = None
    approved_at: Optional[datetime] = None
    final_content: Optional[str] = None

    class Config:
        from_attributes = True
