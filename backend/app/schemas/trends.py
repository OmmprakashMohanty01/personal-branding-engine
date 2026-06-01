from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

class TrendPayload(BaseModel):
    canonical_url: str
    title: str
    summary: Optional[str] = None
    topic: str
    published_at: datetime
    metadata_json: Dict[str, Any] = Field(default_factory=dict)

class TrendResponse(BaseModel):
    id: str
    canonical_url: str
    title: str
    summary: Optional[str] = None
    topic: str
    published_at: datetime
    metadata_json: Dict[str, Any]
    final_score: float
    raw_score: float

    class Config:
        from_attributes = True
