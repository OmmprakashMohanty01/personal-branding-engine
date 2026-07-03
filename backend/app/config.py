import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # App Settings
    ENV: str = "development"
    PROJECT_NAME: str = "AI Personal Branding Engine"
    
    # Database Settings
    # Supports fallback to local SQLite for easy development & testing
    DATABASE_URL: str = "sqlite+aiosqlite:///./branding_engine.db"
    ALEMBIC_DATABASE_URL: Optional[str] = None
    
    # LLM Settings
    LLM_PRIMARY_PROVIDER: str = "groq"
    LLM_FALLBACK_PROVIDERS: str = "gemini,openai"
    
    # API Keys
    GROQ_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    
    # Discovery API Credentials
    NEWS_API_KEY: Optional[str] = None
    REDDIT_CLIENT_ID: Optional[str] = None
    REDDIT_CLIENT_SECRET: Optional[str] = None
    REDDIT_USER_AGENT: str = "ai-personal-branding:v1.0"
    PRODUCT_HUNT_DEVELOPER_TOKEN: Optional[str] = None
    
    # Alerting Settings
    ALERT_WEBHOOK_URL: Optional[str] = None
    ALERT_PROVIDER: str = "discord"
    
    # CORS Settings
    ALLOWED_ORIGINS: str = "*"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
