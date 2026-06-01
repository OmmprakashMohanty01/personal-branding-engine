from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel, ConfigDict

class TopTrendResponse(BaseModel):
    trend_id: str
    title: str
    topic: str
    canonical_url: str
    score: float
    post_count: int

class DashboardMetricsResponse(BaseModel):
    total_drafts_generated: int
    approval_rate: float
    platform_distribution: Dict[str, int]
    top_performing_trends: List[TopTrendResponse]

class SyncResponse(BaseModel):
    status: str
    message: str

class PostAnalyticsResponse(BaseModel):
    likes: int
    shares: int
    comments: int
    views: int
    last_synced_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class PostWithAnalyticsResponse(BaseModel):
    id: str
    trend_id: Optional[str] = None
    persona_id: Optional[str] = None
    platform: str
    content_text: str
    status: str
    generated_at: datetime
    approved_at: Optional[datetime] = None
    final_content: Optional[str] = None
    analytics: Optional[PostAnalyticsResponse] = None

    model_config = ConfigDict(from_attributes=True)
