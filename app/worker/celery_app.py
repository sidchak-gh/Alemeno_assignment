from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "txn_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,            # don't mark the task done until it actually finishes
    worker_prefetch_multiplier=1,   # grab one task at a time, not a batch
    result_expires=86400,
)
