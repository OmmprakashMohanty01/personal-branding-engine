import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import relationship
from app.database import Base

class Trend(Base):
    __tablename__ = "trends"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id = Column(String(36), ForeignKey("trend_sources.id", ondelete="CASCADE"), nullable=True)
    canonical_url = Column(String(512), unique=True, index=True, nullable=False)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=True)
    topic = Column(String(100), index=True, nullable=False)
    published_at = Column(DateTime(timezone=True), index=True, nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationships
    source = relationship("TrendSource", back_populates="trends")
    scores = relationship("TrendScore", back_populates="trend", cascade="all, delete-orphan")
