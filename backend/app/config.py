import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Settings
    ENV: str = "development"
    PROJECT_NAME: str = "AI Personal Branding Engine"

    # Feature Flags & Rollout Switches
    ENABLE_PIPELINE: bool = True
    ENABLE_MEMORY: bool = True
    ENABLE_DEDUP: bool = True
    ENABLE_VALIDATION: bool = True
    AUTO_PUBLISH_ENABLED: bool = False
    ENABLE_LINKEDIN_PUBLISHING: bool = True
    SIMULATION_MODE: bool = False
    EMERGENCY_STOP: bool = False

    # Security & Secret Settings
    CRON_SECRET_KEY: Optional[str] = None
    API_CRON_SECRET: Optional[str] = None

    # Circuit Breaker & Resilience Settings
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    CIRCUIT_BREAKER_RECOVERY_TIME_SECONDS: int = 60
    AUTOMATION_DAILY_PUBLISH_LOCK_ID: int = 1001

    # Database Settings
    DATABASE_URL: str = "sqlite+aiosqlite:///./branding_engine.db"
    ALEMBIC_DATABASE_URL: Optional[str] = None

    # LLM Settings
    LLM_PRIMARY_PROVIDER: str = "groq"
    LLM_FALLBACK_PROVIDERS: str = "gemini,openai"

    # API Keys
    GROQ_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    COHERE_API_KEY: Optional[str] = None

    # Discovery API Credentials
    NEWS_API_KEY: Optional[str] = None
    REDDIT_CLIENT_ID: Optional[str] = None
    REDDIT_CLIENT_SECRET: Optional[str] = None
    REDDIT_USER_AGENT: str = "ai-personal-branding:v1.0"
    PRODUCT_HUNT_DEVELOPER_TOKEN: Optional[str] = None

    # Reddit Publishing Credentials
    REDDIT_USERNAME: Optional[str] = None
    REDDIT_PASSWORD: Optional[str] = None
    REDDIT_TARGET_SUBREDDIT: Optional[str] = None

    # LinkedIn OAuth Credentials
    LINKEDIN_CLIENT_ID: Optional[str] = None
    LINKEDIN_CLIENT_SECRET: Optional[str] = None
    LINKEDIN_REDIRECT_URI: Optional[str] = None

    # X (Twitter) API Credentials
    TWITTER_API_KEY: Optional[str] = None
    TWITTER_API_SECRET: Optional[str] = None
    TWITTER_ACCESS_TOKEN: Optional[str] = None
    TWITTER_ACCESS_SECRET: Optional[str] = None

    # Medium Integration Token
    MEDIUM_INTEGRATION_TOKEN: Optional[str] = None

    # Dev.to API Key
    DEVTO_API_KEY: Optional[str] = None

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
