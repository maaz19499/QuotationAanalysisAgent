"""Health and monitoring endpoints."""
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from quotation_intelligence.api.routers.documents import verify_api_key
from quotation_core.core.config import settings
from quotation_core.models.database import get_db_session

router = APIRouter()


@router.get("/ready")
async def readiness_check(
    db_session: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Readiness check - tests database connectivity."""
    try:
        await db_session.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "checks": {
                "database": "ok",
            },
        }
    except Exception as e:
        return {
            "status": "not_ready",
            "checks": {
                "database": f"error: {str(e)}",
            },
        }


@router.get("/live")
async def liveness_check() -> dict:
    """Liveness check - basic health."""
    return {
        "status": "alive",
    }


@router.get("/version")
async def version_info(
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Get version and configuration info."""
    return {
        "version": settings.app_version,
        "environment": settings.environment,
        "features": {
            "llm_enabled": bool(settings.anthropic_api_key),
            "ocr_enabled": settings.enable_ocr_fallback,
            "storage_type": settings.storage_type,
        },
    }
