from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class GenerateRequest(BaseModel):
    platforms: List[str]
    persona_id: Optional[str] = None

class TweakRequest(BaseModel):
    feedback: str

class DraftResponse(BaseModel):
    id: str
    trend_id: Optional[str] = None
    persona_id: Optional[str] = None
    platform: str
    content_text: str
    status: str
    generated_at: datetime
    llm_metadata: Dict[str, Any]
    feedback_notes: Optional[str] = None
    approved_at: Optional[datetime] = None
    final_content: Optional[str] = None

    class Config:
        from_attributes = True
