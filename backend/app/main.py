from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints.trends import router as trends_router
from app.api.endpoints.generation import router as generation_router
from app.api.endpoints.approvals import router as approvals_router
from app.api.endpoints.publishing import router as publishing_router
from app.api.endpoints.analytics import router as analytics_router
from app.api.endpoints.optimization import router as optimization_router
from app.api.endpoints.scheduling import router as scheduling_router
from app.api.endpoints.health import router as health_router
from app.config import settings

app = FastAPI(
    title="Personal Branding Engine API",
    description="Production-grade REST API backend and background orchestration engine automating content curation, generation, optimization, and cross-network publishing.",
    version="1.0"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(trends_router, prefix="/api/v1", tags=["Trends"])
app.include_router(generation_router, prefix="/api/v1", tags=["Generation"])
app.include_router(approvals_router, prefix="/api/v1", tags=["Approvals"])
app.include_router(publishing_router, prefix="/api/v1", tags=["Publishing"])
app.include_router(analytics_router, prefix="/api/v1", tags=["Analytics"])
app.include_router(optimization_router, prefix="/api/v1", tags=["Optimization"])
app.include_router(scheduling_router, prefix="/api/v1", tags=["Scheduling"])
app.include_router(health_router, prefix="/api/v1", tags=["Health"])

@app.get("/health")
async def health_check():
    return {"status": "ok", "project": settings.PROJECT_NAME}
