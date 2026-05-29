from celery import Celery
from celery.schedules import crontab

from backend.core.config import settings

celery_app = Celery(
    "researchflow",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_BROKER_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600 * 24 * 7,
    task_default_queue="researchflow",
)

celery_app.conf.beat_schedule = {
    "cleanup-expired-every-6-hours": {
        "task": "cleanup_expired",
        "schedule": crontab(minute=0, hour="*/6"),
    },
}

celery_app.autodiscover_tasks(
    ["backend.worker.tasks_parse", "backend.worker.tasks_report", "backend.worker.tasks_cleanup"],
)
