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


class XAccount(Base):
    __tablename__ = "x_accounts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=True)
    twitter_id = Column(String(100), nullable=False)
    username = Column(String(100), nullable=False)
    
    # Store credentials encrypted using AES-256-GCM symmetric key (Fernet wrapper)
    access_token = Column(String(1024), nullable=False)
    refresh_token = Column(String(1024), nullable=True)
    
    expires_at = Column(DateTime(timezone=True), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ThreadsAccount(Base):
    __tablename__ = "threads_accounts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=True)
    threads_user_id = Column(String(100), nullable=False)
    username = Column(String(100), nullable=False)
    
    # Store credentials encrypted using AES-256-GCM symmetric key (Fernet wrapper)
    # This stores the long-lived 60-day token
    access_token = Column(String(1024), nullable=False)
    
    expires_at = Column(DateTime(timezone=True), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SubstackAccount(Base):
    __tablename__ = "substack_accounts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=True)
    newsletter_name = Column(String(100), nullable=False)
    secret_email_address = Column(String(255), nullable=False)
    author_email = Column(String(255), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
