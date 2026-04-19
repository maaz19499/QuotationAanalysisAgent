"""Document processing endpoints."""
import base64
import tempfile
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from quotation_core.core.config import settings
from quotation_core.core.logging_config import get_logger
from quotation_core.models.database import Document, ExtractionResult, ProcessingStatus, get_db_session
from quotation_core.models.schemas import (
    DocumentDetailResponse,
    DocumentResponse,
    DocumentUploadBase64,
    DocumentUploadLocal,
    DocumentUploadRequest,
    ErrorResponse,
    ProcessingResponse,
)
from quotation_core.services.storage_service import (
    FileValidationError,
    StorageError,
    StorageService,
)
from quotation_intelligence.tasks.processing_tasks import process_document_task

logger = get_logger(__name__)
router = APIRouter()


from quotation_core.core.security import verify_api_key


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


@router.get(
    "/{document_id}/export/excel",
    response_model=dict,
)
async def export_document_excel(
    document_id: UUID,
    db_session: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Export document extraction results to Excel."""
    from sqlalchemy.orm import selectinload

    result = await db_session.execute(
        select(Document)
        .options(selectinload(Document.extraction_result).selectinload(ExtractionResult.line_items))
        .where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if not document.extraction_result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document extraction is not yet complete",
        )

    # Reconstruct data dictionary to match what to_export_dict() returns
    extraction = document.extraction_result
    
    export_dict = {
        "supplier_name": extraction.supplier_name,
        "quotation_number": extraction.quotation_number,
        "quotation_date": extraction.quotation_date,
        "currency": extraction.currency,
        "subtotal": extraction.subtotal,
        "tax_amount": extraction.tax_amount,
        "total_amount": extraction.total_amount,
        "line_items": [
            {
                "line_number": item.line_number,
                "product_code": item.product_code,
                "description": item.description,
                "quantity": item.quantity,
                "unit_of_measure": item.unit_of_measure,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
            }
            for item in extraction.line_items
        ],
        "metadata": {
            "line_item_count": len(extraction.line_items),
            "extraction_errors": extraction.extraction_errors or [],
        },
    }

    try:
        from quotation_core.extraction.excel_exporter import generate_crm_pre_qt_excel
        excel_bytes = generate_crm_pre_qt_excel(export_dict)
        excel_b64 = base64.b64encode(excel_bytes).decode('utf-8')
        return {"filename": f"{document.file_name}_export.xlsx", "excel_base64": excel_b64}
    except Exception as e:
        logger.error("excel_export_failed", document_id=str(document_id), error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate Excel export: {e}"
        ) from e
