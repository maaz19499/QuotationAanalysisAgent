"""Celery application configuration."""
from celery import Celery

from quotation_intelligence.core.config import settings
from quotation_intelligence.core.logging_config import configure_logging

configure_logging()

celery_app = Celery(
    "quotation_intelligence",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["quotation_intelligence.tasks.processing_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.processing_timeout_seconds,
    task_soft_time_limit=settings.processing_timeout_seconds - 10,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    result_expires=86400,  # Results expire after 1 day
)

# Optional: Configure task routes
celery_app.conf.task_routes = {
    "quotation_intelligence.tasks.processing_tasks.*": {"queue": "extraction"},
}
