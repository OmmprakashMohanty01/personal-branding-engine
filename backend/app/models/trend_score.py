import uuid
from sqlalchemy import Column, String, Float, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.database import Base

class TrendScore(Base):
    __tablename__ = "trend_scores"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trend_id = Column(String(36), ForeignKey("trends.id", ondelete="CASCADE"), nullable=False)
    raw_score = Column(Float, default=0.0, nullable=False)
    final_score = Column(Float, default=0.0, index=True, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationship back to Trend (allows 1-to-many relationship)
    trend = relationship("Trend", back_populates="scores")
