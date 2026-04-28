"""Standalone extraction endpoints (no Celery/DB)."""
import asyncio
import base64
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from quotation_extraction.core.security import verify_api_key
from quotation_extraction.core.logging_config import get_logger
from quotation_extraction.extraction.pipeline import ExtractionPipeline
from quotation_extraction.extraction.excel_exporter import generate_crm_pre_qt_excel
from quotation_extraction.models.schemas import DocumentUploadRequest
from quotation_extraction.models.database import Document, ProcessingStatus, async_session_maker
from quotation_extraction.services.session_manager import SessionManager
from quotation_extraction.services.storage_service import StorageService

logger = get_logger(__name__)
router = APIRouter()

session_manager = SessionManager()
storage = StorageService()

@router.post("/async", status_code=status.HTTP_202_ACCEPTED)
async def extract_async(
    request_data: DocumentUploadRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(verify_api_key)
) -> dict[str, str]:
    """Upload PDF for background extraction."""
    session_id = str(uuid.uuid4())
    file_path = ""
    
    try:
        if request_data.base64_upload:
            file_name = request_data.base64_upload.file_name
            file_path = storage.save_from_base64(
                request_data.base64_upload.file_content_base64,
                file_name,
                session_id
            )
        elif request_data.local_upload:
            file_name = request_data.local_upload.file_path.split("/")[-1]
            file_path = storage.save_from_local_path(
                request_data.local_upload.file_path,
                file_name,
                session_id
            )
            
        session_manager.init_session(session_id, file_name)
        
        # Persist to database
        if async_session_maker:
            async with async_session_maker() as db:
                doc = Document(
                    session_id=session_id,
                    file_name=file_name,
                    file_path=file_path,
                    status=ProcessingStatus.PENDING
                )
                db.add(doc)
                await db.commit()
                
        background_tasks.add_task(_process_extraction_bg, session_id, file_path)
        
        return {
            "session_id": session_id,
            "status": "pending",
            "message": "Processing started in background."
        }
        
    except Exception as e:
        logger.error("upload_failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sync", status_code=status.HTTP_200_OK)
async def extract_sync(
    request_data: DocumentUploadRequest,
    api_key: str = Depends(verify_api_key)
) -> dict[str, Any]:
    """Upload PDF and wait for extraction (blocking)."""
    session_id = str(uuid.uuid4())
    file_path = ""
    
    try:
        if request_data.base64_upload:
            file_name = request_data.base64_upload.file_name
            file_path = storage.save_from_base64(
                request_data.base64_upload.file_content_base64,
                file_name,
                session_id
            )
        elif request_data.local_upload:
            file_name = request_data.local_upload.file_path.split("/")[-1]
            file_path = storage.save_from_local_path(
                request_data.local_upload.file_path,
                file_name,
                session_id
            )
            
        pipeline = ExtractionPipeline()
        result = await pipeline.process_sync(file_path)
        
        extracted_dict = result.to_export_dict()
        
        # Automatically generate Excel file for sync response
        try:
            excel_bytes = generate_crm_pre_qt_excel(extracted_dict)
            extracted_dict["excel_base64"] = base64.b64encode(excel_bytes).decode('utf-8')
        except Exception as e:
            logger.error("sync_excel_generation_failed", error=str(e))
            extracted_dict["excel_base64"] = None

        # Cleanup
        session_manager.cleanup_session(session_id)
        
        return extracted_dict
        
    except Exception as e:
        logger.error("sync_extract_failed", error=str(e))
        session_manager.cleanup_session(session_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{session_id}")
async def get_status(session_id: str, api_key: str = Depends(verify_api_key)):
    """Check status of an async extraction."""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# The export_excel endpoint has been removed as the excel is now returned in the status directly


async def _process_extraction_bg(session_id: str, file_path: str):
    """Background task for extraction."""
    import json
    session_manager.update_session(session_id, "processing")
    
    if async_session_maker:
        async with async_session_maker() as db:
            from sqlalchemy import select
            result_doc = await db.execute(select(Document).where(Document.session_id == session_id))
            doc = result_doc.scalar_one_or_none()
            if doc:
                doc.status = ProcessingStatus.PROCESSING
                await db.commit()
                
    try:
        pipeline = ExtractionPipeline()
        result = await pipeline.process_sync(file_path)
        
        extracted_dict = result.to_export_dict()
        
        # Automatically generate Excel file
        try:
            excel_bytes = generate_crm_pre_qt_excel(extracted_dict)
            excel_b64 = base64.b64encode(excel_bytes).decode('utf-8')
        except Exception as e:
            logger.error("excel_generation_failed", error=str(e))
            excel_b64 = None
            
        session_manager.update_session(session_id, "completed", result=extracted_dict, excel_base64=excel_b64)
        
        if async_session_maker:
            async with async_session_maker() as db:
                from sqlalchemy import select
                result_doc = await db.execute(select(Document).where(Document.session_id == session_id))
                doc = result_doc.scalar_one_or_none()
                if doc:
                    doc.status = ProcessingStatus.COMPLETED
                    doc.extracted_data = json.dumps(extracted_dict)
                    await db.commit()
                    
    except Exception as e:
        logger.error("bg_extraction_failed", session_id=session_id, error=str(e), exc_info=True)
        session_manager.update_session(session_id, "failed", error=str(e))
        
        if async_session_maker:
            async with async_session_maker() as db:
                from sqlalchemy import select
                result_doc = await db.execute(select(Document).where(Document.session_id == session_id))
                doc = result_doc.scalar_one_or_none()
                if doc:
                    doc.status = ProcessingStatus.FAILED
                    doc.error_message = str(e)
                    await db.commit()
    finally:
        # We don't clean up the session data json, just the temp files if we want, 
        # but the JSON result is needed for polling.
        pass
