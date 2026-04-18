"""Standalone mode API endpoints - synchronous processing without database."""
import base64
import os
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status

from quotation_intelligence.api.routers.documents import verify_api_key
from quotation_intelligence.core.logging_config import get_logger
from quotation_intelligence.extraction.llm_service import LLMExtractionError
from quotation_intelligence.extraction.pipeline import ExtractionPipeline
from quotation_intelligence.models.schemas import (
    DocumentUploadRequest,
    ErrorResponse,
    ExtractionSummary,
    ProcessingStatus,
    SyncExtractionResponse,
)
from quotation_intelligence.services.storage_service import (
    FileValidationError,
    StorageService,
)

logger = get_logger(__name__)
router = APIRouter()


@router.post(
    "/extract",
    response_model=SyncExtractionResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def extract_sync(
    request_data: DocumentUploadRequest,
    request: Request,
    api_key: str = Depends(verify_api_key),
) -> SyncExtractionResponse:
    """
    Extract structured data from a PDF synchronously (standalone mode).

    This endpoint processes PDFs immediately and returns results directly,
    without persisting to database or using Celery queues.

    - No PostgreSQL required
    - No Redis required
    - No Celery required
    - Results returned immediately (not polled later)

    Set ANTHROPIC_API_KEY environment variable for LLM-powered extraction.
    """
    start_time = time.time()
    temp_file_path: str | None = None

    try:
        # Handle file upload
        if request_data.base64_upload:
            upload = request_data.base64_upload

            # Decode base64
            try:
                decoded = base64.b64decode(upload.file_content_base64)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid base64 encoding: {e}",
                ) from e

            # Validate and save to temp file
            storage = StorageService()
            storage.validate_file(decoded, upload.file_name, "application/pdf")

            # Create temp file
            with tempfile.NamedTemporaryFile(
                suffix=".pdf",
                delete=False,
                prefix="quotation_",
            ) as tmp:
                tmp.write(decoded)
                temp_file_path = tmp.name

            logger.info(
                "standalone_upload_received",
                file_name=upload.file_name,
                size_bytes=len(decoded),
                temp_path=temp_file_path,
            )

        elif request_data.local_upload:
            upload = request_data.local_upload
            temp_file_path = upload.file_path

            # Validate file exists
            if not Path(temp_file_path).exists():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File not found: {temp_file_path}",
                )

            logger.info(
                "standalone_local_file",
                file_path=temp_file_path,
            )

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No upload data provided",
            )

        # Process through pipeline (synchronous, no database)
        pipeline = ExtractionPipeline()
        result = pipeline.process_sync(temp_file_path)

        processing_time = time.time() - start_time

        # Calculate confidence summary
        confidence_summary = ExtractionSummary(
            line_item_count=len(result.line_items),
            high_confidence_count=sum(
                1 for item in result.line_items
                if item.calculate_overall_confidence() >= 0.9
            ),
            medium_confidence_count=sum(
                1 for item in result.line_items
                if 0.7 <= item.calculate_overall_confidence() < 0.9
            ),
            low_confidence_count=sum(
                1 for item in result.line_items
                if 0.5 <= item.calculate_overall_confidence() < 0.7
            ),
            average_confidence=result.get_overall_confidence(),
            missing_fields=result.get_missing_fields(),
        )

        # Determine status based on confidence
        if result.get_overall_confidence() >= 0.9 and not confidence_summary.missing_fields:
            result_status = ProcessingStatus.COMPLETED
        elif result.get_overall_confidence() >= 0.7:
            result_status = ProcessingStatus.COMPLETED
        elif result.get_overall_confidence() >= 0.5:
            result_status = ProcessingStatus.PARTIAL
        else:
            result_status = ProcessingStatus.FAILED

        logger.info(
            "standalone_extraction_complete",
            processing_time_seconds=processing_time,
            line_items=len(result.line_items),
            confidence=result.get_overall_confidence(),
            status=result_status.value,
        )

        from quotation_intelligence.extraction.excel_exporter import generate_crm_pre_qt_excel
        
        excel_bytes = generate_crm_pre_qt_excel(result.to_export_dict())
        excel_b64 = base64.b64encode(excel_bytes).decode('utf-8')

        return SyncExtractionResponse(
            status=result_status,
            data=excel_b64,
            confidence_summary=confidence_summary,
            processing_time_seconds=round(processing_time, 2),
            extraction_errors=result.extraction_errors or [],
        )

    except FileValidationError as e:
        logger.warning("standalone_file_validation_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    except ValueError as e:
        logger.error("standalone_processing_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extraction failed: {e}",
        ) from e

    except LLMExtractionError as e:
        logger.error("standalone_llm_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"LLM service unavailable: {e}",
        ) from e

    except Exception as e:
        logger.error("standalone_unexpected_error", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during extraction",
        ) from e

    finally:
        # Clean up temp file if we created it
        if temp_file_path and request_data.base64_upload:
            try:
                os.unlink(temp_file_path)
                logger.debug("temp_file_cleaned_up", path=temp_file_path)
            except OSError as e:
                logger.warning("temp_file_cleanup_failed", path=temp_file_path, error=str(e))
