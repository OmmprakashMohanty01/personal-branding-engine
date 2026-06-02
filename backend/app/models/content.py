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
    trend_id = Column(String(36), ForeignKey("trends.id", ondelete="CASCADE"), nullable=True)
    persona_id = Column(String(36), ForeignKey("personas.id", ondelete="SET NULL"), nullable=True)
    platform = Column(String(50), nullable=False) # 'linkedin', 'x', 'threads', 'substack'
    content_text = Column(Text, nullable=False)
    status = Column(String(20), default="DRAFT", nullable=False) # 'DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'PUBLISHED'
    generated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    llm_metadata = Column(JSON, default=dict, nullable=False)
    
    feedback_notes = Column(Text, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    final_content = Column(Text, nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True, index=True)
    image_url = Column(String(512), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    trend = relationship("Trend")
    persona = relationship("Persona", back_populates="drafts")
    analytics = relationship("PostAnalytics", back_populates="draft", uselist=False, cascade="all, delete-orphan")


class PostAnalytics(Base):
    __tablename__ = "post_analytics"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    draft_id = Column(String(36), ForeignKey("content_drafts.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    likes = Column(Integer, default=0, nullable=False)
    shares = Column(Integer, default=0, nullable=False)
    comments = Column(Integer, default=0, nullable=False)
    views = Column(Integer, default=0, nullable=False)
    
    last_synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    draft = relationship("ContentDraft", back_populates="analytics")
