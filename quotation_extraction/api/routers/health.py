"""Health endpoints."""
from fastapi import APIRouter

router = APIRouter()

@router.get("")
@router.get("/")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "quotation_extraction"}

@router.get("/ready")
async def readiness_check():
    """Readiness check endpoint."""
    return {"status": "ready"}
