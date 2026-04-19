import base64
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

# Import core modules from the DB version structure
from quotation_core.core.security import verify_api_key
from quotation_core.core.logging_config import get_logger
from quotation_core.extraction.llm_service import LLMExtractionError
from quotation_core.extraction.pipeline import ExtractionPipeline
from quotation_core.models.schemas import DocumentUploadRequest, ErrorResponse, ExtractionSummary, ProcessingStatus
from quotation_core.services.storage_service import FileValidationError, StorageService

from quotation_intelligence_standalone.common_utils import (
    save_session_state, get_session_state,
    create_session_workspace, delete_session_workspace
)

logger = get_logger(__name__)
router = APIRouter()


def _process_extraction_bg(
    session_id: str,
    temp_file_path: str | None = None,
    decoded_bytes: bytes | None = None,
    is_base64: bool = False
):
    """Background task logic for extracting document outside main event loop."""
    actual_temp_path = None
    start_time = time.time()
    
    try:
        # Re-save status as processing now that the thread has picked up the job
        save_session_state(session_id, {"status": ProcessingStatus.PROCESSING.value})
        
        # Define the exact workspace assigned to this session
        workspace_path = create_session_workspace(session_id)
        
        if is_base64 and decoded_bytes:
            with tempfile.NamedTemporaryFile(dir=workspace_path, suffix=".pdf", delete=False, prefix="quotation_") as tmp:
                tmp.write(decoded_bytes)
                actual_temp_path = tmp.name
        else:
            # If it's a local upload, we still need to process it, but the local_upload path is outside the workspace.
            # We will copy it into the workspace to unify the cleanup pattern!
            import shutil
            if temp_file_path and Path(temp_file_path).exists():
                new_path = workspace_path / Path(temp_file_path).name
                shutil.copy2(temp_file_path, new_path)
                actual_temp_path = str(new_path)
            else:
                actual_temp_path = temp_file_path

        if not actual_temp_path or not Path(actual_temp_path).exists():
            save_session_state(session_id, {"status": ProcessingStatus.FAILED.value, "error": "File not found"})
            return

        # Synchronous execution
        pipeline = ExtractionPipeline()
        result = pipeline.process_sync(actual_temp_path)

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

        # Generate excel bytes
        from quotation_core.extraction.excel_exporter import generate_crm_pre_qt_excel
        excel_bytes = generate_crm_pre_qt_excel(result.to_export_dict())
        excel_b64 = base64.b64encode(excel_bytes).decode('utf-8')

        # Final determination of status based on confidence
        if result.get_overall_confidence() >= 0.9 and not confidence_summary.missing_fields:
            result_status = ProcessingStatus.COMPLETED.value
        elif result.get_overall_confidence() >= 0.7:
            result_status = ProcessingStatus.COMPLETED.value
        elif result.get_overall_confidence() >= 0.5:
            result_status = ProcessingStatus.PARTIAL.value
        else:
            result_status = ProcessingStatus.FAILED.value

        save_session_state(session_id, {
            "status": result_status,
            "excel_base64": excel_b64,
            "processing_time_seconds": round(processing_time, 2),
            "confidence": result.get_overall_confidence(),
            "extraction_errors": result.extraction_errors or []
        })

    except Exception as e:
        logger.error(f"bg_processing_error session={session_id}", exc_info=True)
        save_session_state(session_id, {
            "status": ProcessingStatus.FAILED.value,
            "error": str(e)
        })
    finally:
        # Atomic guaranteed removal of all workflow files related to this session.
        delete_session_workspace(session_id)


@router.post(
    "/extract/async",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
    },
)
async def extract_async(
    request_data: DocumentUploadRequest,
    background_tasks: BackgroundTasks,
    session_id: str | None = None,
    api_key: str = Depends(verify_api_key),
):
    """
    Asynchronously extracts data from a PDF, queuing it using native BackgroundTasks.
    Requires no separate Celery worker. Use GET /status/{session_id} to poll.
    """
    if not session_id:
        session_id = str(uuid4())

    try:
        if request_data.base64_upload:
            upload = request_data.base64_upload
            
            try:
                decoded = base64.b64decode(upload.file_content_base64)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid base64 encoding: {e}")

            # Validate basic parameters
            storage = StorageService()
            storage.validate_file(decoded, upload.file_name, "application/pdf")
            
            # Queue extraction locally
            save_session_state(session_id, {"status": ProcessingStatus.PENDING.value})
            background_tasks.add_task(_process_extraction_bg, session_id, decoded_bytes=decoded, is_base64=True)
            
        elif request_data.local_upload:
            upload = request_data.local_upload
            
            if not Path(upload.file_path).exists():
                raise HTTPException(status_code=400, detail=f"File not found: {upload.file_path}")
            
            save_session_state(session_id, {"status": ProcessingStatus.PENDING.value})
            background_tasks.add_task(_process_extraction_bg, session_id, temp_file_path=upload.file_path, is_base64=False)
            
        else:
            raise HTTPException(status_code=400, detail="No upload data provided")

        return {
            "session_id": session_id,
            "status": ProcessingStatus.PENDING.value,
            "message": "Document queued for background processing without external broker."
        }

    except FileValidationError as e:
        logger.warning(f"validation_error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"unexpected_submission_error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Unexpected error starting queue")


@router.get(
    "/status/{session_id}",
    responses={
        404: {"model": ErrorResponse},
    },
)
async def get_status(
    session_id: str,
    api_key: str = Depends(verify_api_key)
):
    """
    Polls the JSON tracking store for status updates and returns base64 output if completed.
    Calling this operation triggers a cleanup check on old sessions.
    """
    state_dt = get_session_state(session_id)
    if not state_dt:
        raise HTTPException(
            status_code=404,
            detail="Session ID not found or has been expired and completely scrubbed."
        )

    return state_dt
