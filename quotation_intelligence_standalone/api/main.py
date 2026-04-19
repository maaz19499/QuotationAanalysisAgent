from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quotation_intelligence_standalone.api.routers import health, standalone_endpoints
from quotation_core.core.config import settings

# Dedicated app specifically for standalone execution
app = FastAPI(
    title=f"{settings.app_name} (Standalone Version)",
    description="In-Memory / JSON tracked standalone agent for fast, zero-dependency processing.",
    version="1.0.0",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routing setup
app.include_router(health.router, tags=["Health"])
app.include_router(standalone_endpoints.router, prefix="/api/v1/standalone", tags=["Standalone Processing"])
