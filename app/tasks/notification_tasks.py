"""Celery tasks for sending email notifications."""

from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.services.email import email_service

LOGGER = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.notification_tasks.send_email_task", queue="default")
def send_email_task(to: str, subject: str, html_body: str) -> bool:
    """
    Celery task that sends an email via the EmailService.
    Failures are caught and logged; they never propagate to the caller.
    """
    try:
        return email_service.send_email(to, subject, html_body)
    except Exception as exc:
        LOGGER.warning("send_email_task failed for %s: %s", to, exc)
        return False
