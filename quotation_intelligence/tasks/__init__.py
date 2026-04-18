"""Celery task definitions."""

from quotation_intelligence.tasks.celery_app import celery_app
from quotation_intelligence.tasks.processing_tasks import process_document_task

__all__ = ["celery_app", "process_document_task"]
