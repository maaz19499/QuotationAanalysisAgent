"""FastAPI application main entry point."""
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from quotation_extraction.api import routers
from quotation_extraction.core.config import settings
from quotation_extraction.core.logging_config import configure_logging, get_logger
from quotation_extraction.models.database import init_db

configure_logging()
logger = get_logger(__name__)

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan events."""
    logger.info("api_startup", app_name=settings.app_name, version=settings.app_version)
    init_db()
    logger.info("database_initialized")
    yield
    logger.info("api_shutdown")

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Standalone Quotation Extraction API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_exception", error=str(exc), path=str(request.url), exc_info=True)
    return JSONResponse(status_code=500, content={"error_code": "INTERNAL_ERROR", "message": str(exc)})

app.include_router(routers.extraction.router, prefix="/api/v1/extract", tags=["Extraction"])
app.include_router(routers.health.router, prefix="/api/v1/health", tags=["Health"])

def main() -> None:
    import uvicorn
    uvicorn.run("quotation_extraction.api.main:app", host=settings.host, port=settings.port, reload=settings.debug)

if __name__ == "__main__":
    main()
