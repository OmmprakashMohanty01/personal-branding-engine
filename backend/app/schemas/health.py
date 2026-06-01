from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str
    timestamp: str

class DeepHealthResponse(BaseModel):
    status: str
    database: str
    timestamp: str
