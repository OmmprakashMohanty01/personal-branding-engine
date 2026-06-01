import uuid
from sqlalchemy import Column, String, Boolean, DateTime, func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base

class TrendSource(Base):
    __tablename__ = "trend_sources"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False)
    source_url = Column(String(255), nullable=False)
    connector_type = Column(String(50), nullable=False) # 'rss', 'api', 'scraping'
    is_active = Column(Boolean, default=True, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationship back to trends
    trends = relationship("Trend", back_populates="source", cascade="all, delete-orphan")
