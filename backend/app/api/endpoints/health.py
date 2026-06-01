import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.schemas.health import HealthResponse, DeepHealthResponse

logger = logging.getLogger("branding_engine.api.health")

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def shallow_health_check():
    """Standard HTTP health check endpoint for shallow uptime monitoring (200 OK)."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/deep", response_model=DeepHealthResponse)
async def deep_health_check(db: AsyncSession = Depends(get_db)):
    """Verifies that both the API gateway server and the underlying SQL database connection are operational."""
    try:
        # Run a lightweight raw query against the database connection
        await db.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Deep health check database query failure: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed or is unreachable."
        )
