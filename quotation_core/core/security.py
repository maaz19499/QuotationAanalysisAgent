from fastapi import HTTPException, Request, status
from quotation_core.core.config import settings

def verify_api_key(request: Request) -> str:
    """Verify API key from header."""
    api_key = request.headers.get(settings.api_key_header)

    # In development, allow missing API keys
    if settings.environment == "development" and not api_key:
        return "dev-key"

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
        )

    # Validate API key (in production, check against database)
    if settings.environment == "production":
        # TODO: Validate against stored keys
        if api_key != settings.secret_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

    return api_key
