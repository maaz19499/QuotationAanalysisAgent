"""Celery tasks for document processing."""
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from quotation_core.core.config import settings
from quotation_core.core.logging_config import get_logger
from quotation_core.extraction.pipeline import ExtractionPipeline
from quotation_core.models.database import (
    AsyncSessionLocal,
    Document,
    ProcessingStatus,
)
from quotation_core.models.extraction import QuotationExtracted
from quotation_intelligence.tasks.celery_app import celery_app

logger = get_logger(__name__)


class DatabaseTask(Task):
    """Base Celery task with database session management."""

    _session = None

    async def get_session(self):
        """Get async database session."""
        if self._session is None:
            self._session = AsyncSessionLocal()
        return self._session


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    max_retries=settings.llm_max_retries,
    default_retry_delay=60,
)
def process_document_task(self: DatabaseTask, document_id: str, file_path: str) -> dict:
    """
    Process a document through the extraction pipeline.

    This is a Celery task that runs asynchronously.
    """
    import asyncio

    # Run async processing
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(
            _async_process_document(document_id, file_path)
        )
        
        import shutil
        from pathlib import Path
        try:
            # Delete DB workflow workspace when finished successfully!
            shutil.rmtree(Path(file_path).parent)
        except Exception as e:
            logger.error(f"Failed to delete DB workspace {file_path}: {e}")
            
        return result

    except SoftTimeLimitExceeded:
        logger.error("processing_soft_time_limit_exceeded", document_id=document_id)
        loop.run_until_complete(_mark_failed(document_id, "Processing timeout"))
        
        import shutil
        from pathlib import Path
        try:
            shutil.rmtree(Path(file_path).parent)
        except Exception:
            pass
            
        raise

    except Exception as exc:
        logger.error(
            "processing_failed",
            document_id=document_id,
            error=str(exc),
            exc_info=True,
        )

        # Retry with exponential backoff
        retry_count = self.request.retries
        if retry_count < settings.llm_max_retries:
            logger.info("retrying_processing", document_id=document_id, attempt=retry_count + 1)
            raise self.retry(
                exc=exc,
                countdown=60 * (2 ** retry_count),  # Exponential backoff
            )
        else:
            loop.run_until_complete(_mark_failed(document_id, f"Max retries exceeded: {exc}"))
            
            import shutil
            from pathlib import Path
            try:
                shutil.rmtree(Path(file_path).parent)
            except Exception:
                pass
                
            raise

    finally:
        loop.close()


async def _async_process_document(document_id: str, file_path: str) -> dict:
    """Async processing implementation."""
    async with AsyncSessionLocal() as session:
        try:
            # Get document
            from sqlalchemy.future import select

            result = await session.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()

            if not document:
                logger.error("document_not_found", document_id=document_id)
                return {"error": "Document not found", "document_id": document_id}

            if document.status == ProcessingStatus.PROCESSING:
                logger.warning("document_already_processing", document_id=document_id)
                return {"error": "Document already being processed", "document_id": document_id}

            # Process through pipeline
            pipeline = ExtractionPipeline()
            final_status = await pipeline.process_document(file_path, document, session)

            return {
                "document_id": document_id,
                "status": final_status.value,
                "success": final_status in (ProcessingStatus.COMPLETED, ProcessingStatus.PARTIAL),
            }

        except Exception as e:
            await session.rollback()
            logger.error("async_processing_error", document_id=document_id, error=str(e))
            raise


async def _mark_failed(document_id: str, error_message: str) -> None:
    """Mark document as failed."""
    async with AsyncSessionLocal() as session:
        try:
            from sqlalchemy.future import select

            result = await session.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()

            if document:
                document.status = ProcessingStatus.FAILED
                document.error_message = error_message
                from datetime import datetime

                document.processing_completed_at = datetime.utcnow()
                await session.commit()

        except Exception as e:
            logger.error("failed_to_mark_failed", document_id=document_id, error=str(e))
            await session.rollback()


@celery_app.task
def cleanup_old_documents(older_than_days: int = 30) -> dict:
    """
    Clean up old processed documents.

    This task can be scheduled to run periodically.
    """
    import asyncio

    async def _cleanup():
        from datetime import datetime, timedelta

        from sqlalchemy import delete

        from quotation_core.models.database import Document, ProcessingStatus

        cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)

        async with AsyncSessionLocal() as session:
            try:
                # Delete old completed documents
                stmt = (
                    delete(Document)
                    .where(Document.status == ProcessingStatus.COMPLETED)
                    .where(Document.processing_completed_at < cutoff_date)
                )
                result = await session.execute(stmt)
                deleted_count = result.rowcount
                await session.commit()

                logger.info("cleanup_completed", deleted_count=deleted_count, cutoff=cutoff_date)
                return {"deleted_count": deleted_count}

            except Exception as e:
                await session.rollback()
                logger.error("cleanup_failed", error=str(e))
                raise

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_cleanup())
    finally:
        loop.close()
