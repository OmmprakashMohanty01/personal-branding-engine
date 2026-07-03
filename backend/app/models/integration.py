import uuid
from sqlalchemy import Column, String, DateTime, func
from app.database import Base

class LinkedInAccount(Base):
    __tablename__ = "linkedin_accounts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=True) # links to user profile id
    linkedin_person_urn = Column(String(100), nullable=False) # e.g. urn:li:person:abc123XYZ
    
    # Store credentials encrypted using AES-256-GCM symmetric key
    access_token = Column(String(1024), nullable=False)
    refresh_token = Column(String(1024), nullable=True)
    
    expires_at = Column(DateTime(timezone=True), nullable=False)
    refresh_expires_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
