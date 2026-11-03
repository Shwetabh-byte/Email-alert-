"""
Email Alert Sender Module.
Handles composing and sending alert emails via SMTP.
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from typing import Optional
from pathlib import Path

from config import EmailConfig

logger = logging.getLogger(__name__)


class AlertSender:
    """Sends email alerts via SMTP."""

    def __init__(self, config: EmailConfig):
        self.config = config
        self._setup_logging()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(self.config.log_file),
                logging.StreamHandler(),
            ],
        )

    def _connect(self) -> smtplib.SMTP:
        """Establish SMTP connection."""
        server = smtplib.SMTP(self.config.smtp_server, self.config.smtp_port)
        if self.config.smtp_use_tls:
            server.starttls()
        server.login(self.config.email_address, self.config.email_password)
        logger.info("Connected to SMTP server %s", self.config.smtp_server)
        return server

    def send_alert(
        self,
        subject: str,
        body: str,
        recipients: Optional[list] = None,
        priority: str = "medium",
        html_body: Optional[str] = None,
        attachments: Optional[list] = None,
    ) -> bool:
        """
        Send an alert email.

        Args:
            subject: Email subject (prefix is auto-added).
            body: Plain text body.
            recipients: List of recipient emails. Falls back to config defaults.
            priority: Alert priority — low, medium, high, critical.
            html_body: Optional HTML version of the body.
            attachments: Optional list of file paths to attach.

        Returns:
            True if sent successfully, False otherwise.
        """
        recipients = recipients or self.config.default_recipients
        if not recipients:
            logger.error("No recipients specified and no defaults configured.")
            return False

        full_subject = f"{self.config.subject_prefix} [{priority.upper()}] {subject}"

        msg = MIMEMultipart("alternative")
        msg["From"] = self.config.default_sender
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = full_subject
        msg["X-Priority"] = self._priority_header(priority)
        msg["X-Alert-Timestamp"] = datetime.now().isoformat()
        msg["X-Alert-Priority"] = priority

        # Plain text part
        full_body = self._format_body(body, priority)
        msg.attach(MIMEText(full_body, "plain"))

        # HTML part (optional)
        if html_body:
            msg.attach(MIMEText(html_body, "html"))
        else:
            msg.attach(MIMEText(self._text_to_html(full_body, priority), "html"))

        # Attachments
        if attachments:
            for filepath in attachments:
                self._attach_file(msg, filepath)

        try:
            server = self._connect()
            server.sendmail(self.config.email_address, recipients, msg.as_string())
            server.quit()
            logger.info(
                "Alert sent: '%s' to %s [priority: %s]",
                subject,
                recipients,
                priority,
            )
            return True
        except Exception as e:
            logger.error("Failed to send alert: %s", e)
            return False

    def send_bulk_alerts(self, alerts: list) -> dict:
        """
        Send multiple alerts in one SMTP session.

        Args:
            alerts: List of dicts with keys: subject, body, recipients (optional),
                    priority (optional).

        Returns:
            Dict with 'sent' and 'failed' counts.
        """
        results = {"sent": 0, "failed": 0}

        try:
            server = self._connect()

            for alert in alerts:
                recipients = alert.get("recipients", self.config.default_recipients)
                subject = (
                    f"{self.config.subject_prefix} "
                    f"[{alert.get('priority', 'medium').upper()}] "
                    f"{alert['subject']}"
                )

                msg = MIMEMultipart()
                msg["From"] = self.config.default_sender
                msg["To"] = ", ".join(recipients)
                msg["Subject"] = subject

                body = self._format_body(
                    alert["body"], alert.get("priority", "medium")
                )
                msg.attach(MIMEText(body, "plain"))

                try:
                    server.sendmail(
                        self.config.email_address, recipients, msg.as_string()
                    )
                    results["sent"] += 1
                    logger.info("Bulk alert sent: '%s'", alert["subject"])
                except Exception as e:
                    results["failed"] += 1
                    logger.error(
                        "Failed to send bulk alert '%s': %s", alert["subject"], e
                    )

            server.quit()
        except Exception as e:
            logger.error("SMTP connection failed during bulk send: %s", e)

        return results

    def _format_body(self, body: str, priority: str) -> str:
        """Format the alert body with metadata."""
        separator = "=" * 50
        return (
            f"{separator}\n"
            f"  ALERT NOTIFICATION\n"
            f"  Priority: {priority.upper()}\n"
            f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{separator}\n\n"
            f"{body}\n\n"
            f"{separator}\n"
            f"This is an automated alert from Email Alert System.\n"
        )

    def _text_to_html(self, text: str, priority: str) -> str:
        """Convert plain text alert to styled HTML."""
        color_map = {
            "low": "#2196F3",
            "medium": "#FF9800",
            "high": "#F44336",
            "critical": "#9C27B0",
        }
        color = color_map.get(priority, "#FF9800")

        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px;">
            <div style="border-left: 4px solid {color}; padding: 15px;
                        background: #f9f9f9; border-radius: 4px;">
                <h2 style="color: {color}; margin-top: 0;">
                    ⚠ Alert — {priority.upper()}
                </h2>
                <p style="color: #333; white-space: pre-wrap;">{text}</p>
                <hr style="border: 1px solid #ddd;">
                <small style="color: #999;">
                    Sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                    by Email Alert System
                </small>
            </div>
        </body>
        </html>
        """

    def _priority_header(self, priority: str) -> str:
        """Map priority to email X-Priority header value."""
        mapping = {"critical": "1", "high": "2", "medium": "3", "low": "5"}
        return mapping.get(priority, "3")

    def _attach_file(self, msg: MIMEMultipart, filepath: str):
        """Attach a file to the email."""
        path = Path(filepath)
        if not path.exists():
            logger.warning("Attachment not found: %s", filepath)
            return

        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition", f"attachment; filename={path.name}"
            )
            msg.attach(part)
