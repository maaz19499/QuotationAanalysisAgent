from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health_check():
    """Health check for standalone api"""
    return {"status": "ok", "app": "quotation_standalone"}
