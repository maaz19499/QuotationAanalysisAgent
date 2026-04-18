"""FastAPI application main entry point."""
import contextlib
from collections.abc import AsyncIterator

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from quotation_intelligence.api import routers
from quotation_intelligence.core.config import settings
from quotation_intelligence.core.logging_config import configure_logging, get_logger

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=1.0 if settings.environment == "production" else 0.1,
    )

configure_logging()
logger = get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan events."""
    logger.info(
        "api_startup",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )

    yield

    logger.info("api_shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Convert PDF quotations to structured data using AI + rule-based extraction",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    openapi_url="/openapi.json" if settings.environment != "production" else None,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions."""
    logger.error(
        "unhandled_exception",
        error=str(exc),
        path=str(request.url),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_ERROR",
            "message": "An internal error occurred. Please try again later.",
        },
    )


# Health check
@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
    }


# Include routers
app.include_router(routers.documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(routers.exports.router, prefix="/api/v1/exports", tags=["Exports"])
app.include_router(routers.health.router, prefix="/api/v1/health", tags=["Health"])
app.include_router(routers.standalone.router, prefix="/api/v1/standalone", tags=["Standalone (No DB)"])


def main() -> None:
    """Entry point for running the API server."""
    import uvicorn

    uvicorn.run(
        "quotation_intelligence.api.main:app",
        host=settings.host,
        port=settings.port,
        # workers=settings.api_workers,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
