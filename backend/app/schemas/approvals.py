from typing import Optional
from pydantic import BaseModel

class ApproveRequest(BaseModel):
    edited_content: Optional[str] = None

class RejectRequest(BaseModel):
    reason: str

class ReviseRequest(BaseModel):
    feedback_notes: str
