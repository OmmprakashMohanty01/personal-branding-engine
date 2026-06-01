from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict

class OptimizationResponse(BaseModel):
    id: str
    persona_id: str
    platform: str
    optimized_system_prompt: str
    generated_at: datetime
    is_active: bool
    
    model_config = ConfigDict(from_attributes=True)

class TuneRequest(BaseModel):
    platform: Optional[str] = None # Optional platform string to tune a single platform
