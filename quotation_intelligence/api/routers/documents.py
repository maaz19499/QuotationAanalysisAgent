"""Document processing endpoints."""
import base64
import tempfile
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from quotation_intelligence.core.config import settings
from quotation_intelligence.core.logging_config import get_logger
from quotation_intelligence.models.database import Document, ProcessingStatus, get_db_session
from quotation_intelligence.models.schemas import (
    DocumentDetailResponse,
    DocumentResponse,
    DocumentUploadBase64,
    DocumentUploadLocal,
    DocumentUploadRequest,
    ErrorResponse,
    ProcessingResponse,
)
from quotation_intelligence.services.storage_service import (
    FileValidationError,
    StorageError,
    StorageService,
)
from quotation_intelligence.tasks.processing_tasks import process_document_task

logger = get_logger(__name__)
router = APIRouter()


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


@router.post(
    "/upload",
    response_model=ProcessingResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
    },
)
async def upload_document(
    request_data: DocumentUploadRequest,
    db_session: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(verify_api_key),
) -> ProcessingResponse:
    """
    Upload a PDF quotation for processing.

    Supports either Base64-encoded content (production) or local file path (development).
    """
    storage = StorageService()
    document = None

    try:
        if request_data.base64_upload:
            # Handle Base64 upload
            upload = request_data.base64_upload

            # Decode to check validity
            try:
                decoded = base64.b64decode(upload.file_content_base64)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid base64 encoding",
                )

            # Validate and save
            storage.validate_file(decoded, upload.file_name, "application/pdf")
            file_path = storage.save_from_base64(
                upload.file_content_base64,
                upload.file_name,
                "application/pdf",
            )

            # Create document record
            document = Document(
                file_name=upload.file_name,
                file_path=file_path,
                file_size_bytes=len(decoded),
                mime_type="application/pdf",
                status=ProcessingStatus.PENDING,
            )

        elif request_data.local_upload:
            # Handle local file path upload
            upload = request_data.local_upload

            if settings.environment == "production":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Local file upload not allowed in production",
                )

            # Save to storage
            file_path = storage.save_from_local_path(upload.file_path)

            # Create document record
            document = Document(
                file_name=upload.file_path.split("/")[-1],
                file_path=file_path,
                mime_type="application/pdf",
                status=ProcessingStatus.PENDING,
            )

        if not document:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No upload data provided",
            )

        # Save to database
        db_session.add(document)
        await db_session.flush()

        # Queue for processing
        process_document_task.delay(str(document.id), document.file_path)

        logger.info(
            "document_uploaded",
            document_id=str(document.id),
            api_key=api_key[:8] + "...",
        )

        return ProcessingResponse(
            document_id=document.id,
            status=ProcessingStatus.PENDING,
            message="Document queued for processing",
            estimated_completion_time="10-30 seconds",
        )

    except FileValidationError as e:
        logger.warning("file_validation_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except StorageError as e:
        logger.error("storage_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store file",
        ) from e


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    responses={
        404: {"model": ErrorResponse},
    },
)
async def get_document(
    document_id: UUID,
    db_session: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(verify_api_key),
) -> DocumentDetailResponse:
    """Get document details and extraction results."""
    result = await db_session.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return DocumentDetailResponse.model_validate(document)


@router.get(
    "/",
    response_model=list[DocumentResponse],
)
async def list_documents(
    status_filter: ProcessingStatus | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db_session: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(verify_api_key),
) -> list[DocumentResponse]:
    """List documents with optional status filter."""
    query = select(Document).order_by(Document.uploaded_at.desc())

    if status_filter:
        query = query.where(Document.status == status_filter)

    query = query.limit(limit).offset(offset)

    result = await db_session.execute(query)
    documents = result.scalars().all()

    return [DocumentResponse.model_validate(doc) for doc in documents]


@router.post(
    "/{document_id}/reprocess",
    response_model=ProcessingResponse,
)
async def reprocess_document(
    document_id: UUID,
    db_session: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(verify_api_key),
) -> ProcessingResponse:
    """Re-process a document."""
    result = await db_session.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Reset status
    document.status = ProcessingStatus.PENDING
    document.error_message = None
    document.retry_count += 1
    await db_session.commit()

    # Re-queue
    process_document_task.delay(str(document.id), document.file_path)

    return ProcessingResponse(
        document_id=document.id,
        status=ProcessingStatus.PENDING,
        message="Document re-queued for processing",
    )
