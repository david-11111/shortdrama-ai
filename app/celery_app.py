from __future__ import annotations

from celery import Celery

from app.config import get_settings


def _load_settings():
    return get_settings()


settings = _load_settings()

celery_app = Celery("shortdrama_ai")
celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    imports=(
        "app.tasks.video_tasks",
        "app.tasks.image_tasks",
        "app.tasks.text_tasks",
        "app.tasks.tts_tasks",
        "app.tasks.director_tasks",
        "app.tasks.admin_tasks",
        "app.tasks.notification_tasks",
    ),
    task_routes={
        "app.tasks.video_tasks.*": {"queue": "video"},
        "app.tasks.image_tasks.*": {"queue": "image"},
        "app.tasks.text_tasks.*": {"queue": "text"},
        "app.tasks.tts_tasks.*": {"queue": "text"},
        "app.tasks.director_tasks.director_chat_task": {"queue": "text"},
        "app.tasks.director_tasks.director_script_task": {"queue": "text"},
        "app.tasks.director_tasks.director_prepare_task": {"queue": "default"},
        "app.tasks.director_tasks.director_produce_task": {"queue": "default"},
        "app.tasks.director_tasks.director_reference_images_task": {"queue": "image"},
        "app.tasks.admin_tasks.*": {"queue": "admin"},
        "app.tasks.notification_tasks.*": {"queue": "default"},
    },
    task_default_queue="default",
    task_ignore_result=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=900,
    task_soft_time_limit=600,
    broker_transport_options={
        "priority_steps": list(range(10)),
        "queue_order_strategy": "priority",
    },
    beat_schedule={
        "key-pool-refresh": {
            "task": "app.tasks.admin_tasks.refresh_key_pool_state",
            "schedule": 60,
        },
        "credit-reservation-sweep": {
            "task": "app.tasks.admin_tasks.expire_credit_reservations",
            "schedule": 300,
        },
        "stale-task-cleanup": {
            "task": "app.tasks.admin_tasks.cleanup_stale_tasks",
            "schedule": 300,
            "kwargs": {
                "running_timeout_minutes": 120,
                "queued_timeout_minutes": 30,
            },
        },
        "work-queue-processor": {
            "task": "app.tasks.admin_tasks.process_work_queue",
            "schedule": 5,
        },
        "orphan-task-reconciler": {
            "task": "app.tasks.admin_tasks.reconcile_orphaned_tasks",
            "schedule": 60,
            "kwargs": {
                "queued_timeout_seconds": 180,
                "max_attempts": 3,
                "batch_size": 50,
            },
        },
    },
)

app = celery_app
