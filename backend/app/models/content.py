import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, JSON, func, Integer
from sqlalchemy.orm import relationship
from app.database import Base

class Persona(Base):
    __tablename__ = "personas"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False)
    tone_description = Column(Text, nullable=False)
    vocabulary_rules = Column(Text, nullable=False)
    formatting_preferences = Column(Text, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationship back to drafts
    drafts = relationship("ContentDraft", back_populates="persona", cascade="all, delete-orphan")


class ContentDraft(Base):
    __tablename__ = "content_drafts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key = Column(String(100), unique=True, nullable=True, index=True)
    persona_id = Column(String(36), ForeignKey("personas.id", ondelete="SET NULL"), nullable=True)
    platform = Column(String(50), default="linkedin", nullable=False)
    content_text = Column(Text, nullable=False)
    status = Column(String(20), default="DRAFT", nullable=False) # 'DRAFT', 'PUBLISHED', 'FAILED'
    generated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    llm_metadata = Column(JSON, default=dict, nullable=False)
    
    # Semantic Quality Gate Metadata
    vision_score = Column(Integer, nullable=True)
    vision_reasoning = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    persona = relationship("Persona", back_populates="drafts")
