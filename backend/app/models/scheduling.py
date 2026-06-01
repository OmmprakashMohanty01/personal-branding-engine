import uuid
from sqlalchemy import Column, String, JSON, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class ScheduleConfig(Base):
    __tablename__ = "schedule_configs"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    persona_id = Column(String(36), ForeignKey("personas.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String(50), nullable=False) # 'linkedin', 'x', 'threads', 'substack'
    posting_times_json = Column(JSON, nullable=False) # e.g. ["08:00", "12:30", "17:00"]
    timezone = Column(String(100), default="UTC", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationship back to Persona
    persona = relationship("Persona", backref="schedules")
