import json
import time
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.endpoints.generation import router as generation_router
from app.api.endpoints.publishing import router as publishing_router
from app.api.endpoints.health import router as health_router
from app.api.endpoints.automation import router as automation_router
from app.config import settings

logger = logging.getLogger("branding_engine.main")

app = FastAPI(
    title="Personal Branding Engine API",
    description="Minimal REST API backend and orchestration engine automating LinkedIn content generation and publishing.",
    version="1.0"
)
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.debug(f"Request validation failed for {request.url.path}: {exc.errors()}")
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# CORS Configuration
allowed_origins = [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",")] if settings.ALLOWED_ORIGINS else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True if allowed_origins != ["*"] else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
import os

# Create static files directories if they don't exist
os.makedirs("static/images", exist_ok=True)

# Register routers
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(generation_router, prefix="/api/v1")
app.include_router(publishing_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")
app.include_router(automation_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "ok", "project": settings.PROJECT_NAME}
