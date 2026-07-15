import json
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.endpoints.generation import router as generation_router
from app.api.endpoints.publishing import router as publishing_router
from app.api.endpoints.health import router as health_router
from app.api.endpoints.automation import router as automation_router
from app.config import settings

app = FastAPI(
    title="Personal Branding Engine API",
    description="Minimal REST API backend and orchestration engine automating LinkedIn content generation and publishing.",
    version="1.0"
)

DEBUG_LOG_PATH = "/Users/ommprakashmohanty/personal-branding-engine/.cursor/debug-5139fb.log"


def _debug_log(location: str, message: str, data: dict, hypothesis_id: str) -> None:
    # #region agent log
    try:
        with open(DEBUG_LOG_PATH, "a") as f:
            f.write(json.dumps({
                "sessionId": "5139fb",
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
                "hypothesisId": hypothesis_id,
                "runId": "pre-fix",
            }) + "\n")
    except Exception:
        pass
    # #endregion


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # #region agent log
    body_preview = None
    if request.url.path.endswith("/generate-image"):
        try:
            body_bytes = await request.body()
            body_preview = body_bytes.decode("utf-8")[:500]
        except Exception as e:
            body_preview = f"<read error: {e}>"
    _debug_log(
        "main.py:validation_exception_handler",
        "Request validation failed",
        {
            "path": request.url.path,
            "method": request.method,
            "query_params": dict(request.query_params),
            "content_type": request.headers.get("content-type"),
            "body_preview": body_preview,
            "errors": exc.errors(),
        },
        "A,B,C,D,E",
    )
    # #endregion
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
