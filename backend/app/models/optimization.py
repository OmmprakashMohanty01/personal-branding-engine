import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base

class OptimizationFeedback(Base):
    __tablename__ = "optimization_feedbacks"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    platform = Column(String(50), nullable=False) # 'linkedin', 'x', 'threads', 'substack'
    persona_id = Column(String(36), ForeignKey("personas.id", ondelete="CASCADE"), nullable=False, index=True)
    optimized_system_prompt = Column(Text, nullable=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationship back to Persona
    persona = relationship("Persona", backref="optimizations")
