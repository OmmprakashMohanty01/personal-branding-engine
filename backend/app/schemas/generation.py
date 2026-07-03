from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict

class GenerateRequest(BaseModel):
    topic: str
    persona_id: Optional[str] = None

class ImageGenerateRequest(BaseModel):
    topic: str
    draft_text: Optional[str] = None

class DraftUpdatePayload(BaseModel):
    content_text: str
    image_url: Optional[str] = None

class DraftResponse(BaseModel):
    id: str
    persona_id: Optional[str] = None
    content_text: str
    status: str
    generated_at: datetime
    llm_metadata: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)

