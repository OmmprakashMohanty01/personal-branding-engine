from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

class ScheduleConfigCreate(BaseModel):
    persona_id: str
    platform: str
    posting_times_json: List[str] # e.g. ["08:00", "12:30", "17:00"]
    timezone: Optional[str] = "UTC"
    is_active: Optional[bool] = True

class ScheduleConfigResponse(BaseModel):
    id: str
    persona_id: str
    platform: str
    posting_times_json: List[str]
    timezone: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)

class ScheduleAssignResponse(BaseModel):
    status: str
    scheduled_count: int

class ScheduleDispatchResponse(BaseModel):
    status: str
    message: str
