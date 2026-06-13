"""Email notification service using smtplib + SSL."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import get_settings

LOGGER = logging.getLogger(__name__)


class EmailService:
    """Sends transactional emails via SMTP. Silently skips if not configured."""

    def send_email(self, to: str, subject: str, html_body: str) -> bool:
        """
        Send an email. Returns True on success, False on failure.
        Silently skips (returns False) if smtp_host is not configured.
        """
        settings = get_settings()
        if not settings.smtp_host:
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_user}>"
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            if settings.smtp_use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    settings.smtp_host, settings.smtp_port, context=context
                ) as server:
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(settings.smtp_user, to, msg.as_string())
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                    server.starttls()
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(settings.smtp_user, to, msg.as_string())

            LOGGER.info("Email sent to %s: %s", to, subject)
            return True
        except Exception as exc:
            LOGGER.warning("Failed to send email to %s: %s", to, exc)
            return False

    def notify_task_complete(
        self,
        user_email: str,
        task_type: str,
        task_id: str,
        result_url: str | None = None,
    ) -> bool:
        """Send a task-completion notification email."""
        subject = f"Your {task_type} task is complete"
        html_body = self._render_task_complete(task_type, task_id, result_url)
        return self.send_email(user_email, subject, html_body)

    def notify_payment_success(
        self,
        user_email: str,
        credits: int,
        order_no: str,
    ) -> bool:
        """Send a payment-success notification email."""
        subject = "Payment confirmed - credits added"
        html_body = self._render_payment_success(credits, order_no)
        return self.send_email(user_email, subject, html_body)

    # ------------------------------------------------------------------
    # HTML templates
    # ------------------------------------------------------------------

    @staticmethod
    def _render_task_complete(
        task_type: str, task_id: str, result_url: str | None
    ) -> str:
        import html as html_mod
        safe_type = html_mod.escape(task_type)
        safe_id = html_mod.escape(task_id)
        link_section = ""
        if result_url and result_url.startswith("https"):
            safe_url = html_mod.escape(result_url)
            link_section = (
                f'<p><a href="{safe_url}" '
                f'style="color:#4f46e5;">View Result</a></p>'
            )
        return f"""\
<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
  <h2 style="color:#111;">Task Complete</h2>
  <p>Your <strong>{safe_type}</strong> task has finished processing.</p>
  <p style="color:#666;font-size:13px;">Task ID: {safe_id}</p>
  {link_section}
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
  <p style="color:#999;font-size:12px;">ShortDrama AI</p>
</div>"""

    @staticmethod
    def _render_payment_success(credits: int, order_no: str) -> str:
        import html as html_mod
        safe_order = html_mod.escape(str(order_no))
        return f"""\
<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
  <h2 style="color:#111;">Payment Successful</h2>
  <p><strong>{credits}</strong> credits have been added to your account.</p>
  <p style="color:#666;font-size:13px;">Order No: {safe_order}</p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
  <p style="color:#999;font-size:12px;">ShortDrama AI</p>
</div>"""


email_service = EmailService()
