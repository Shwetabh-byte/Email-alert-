"""
Alert Manager — unified interface for sending and receiving email alerts.
"""

import logging
from typing import Callable, Optional

from config import EmailConfig, AlertRule
from alert_sender import AlertSender
from alert_receiver import AlertReceiver

logger = logging.getLogger(__name__)


class AlertManager:
    """
    High-level interface that combines AlertSender and AlertReceiver.

    Usage:
        manager = AlertManager(config)
        manager.send("Server down", "CPU at 100%", priority="critical")
        manager.on("server_down", keyword="Server down", handler=my_handler)
        manager.start()
    """

    def __init__(self, config: Optional[EmailConfig] = None):
        self.config = config or EmailConfig()
        self.sender = AlertSender(self.config)
        self.receiver = AlertReceiver(self.config)

    # ── Sending ──────────────────────────────────────────────────────────────

    def send(
        self,
        subject: str,
        body: str,
        recipients: Optional[list] = None,
        priority: str = "medium",
        attachments: Optional[list] = None,
    ) -> bool:
        """Send a single alert email."""
        return self.sender.send_alert(
            subject=subject,
            body=body,
            recipients=recipients,
            priority=priority,
            attachments=attachments,
        )

    def send_critical(self, subject: str, body: str, recipients: Optional[list] = None) -> bool:
        """Shortcut for critical-priority alerts."""
        return self.send(subject, body, recipients, priority="critical")

    def send_high(self, subject: str, body: str, recipients: Optional[list] = None) -> bool:
        """Shortcut for high-priority alerts."""
        return self.send(subject, body, recipients, priority="high")

    def send_low(self, subject: str, body: str, recipients: Optional[list] = None) -> bool:
        """Shortcut for low-priority alerts."""
        return self.send(subject, body, recipients, priority="low")

    def send_bulk(self, alerts: list) -> dict:
        """Send multiple alerts in a single SMTP session."""
        return self.sender.send_bulk_alerts(alerts)

    # ── Receiving ─────────────────────────────────────────────────────────────

    def on(
        self,
        name: str,
        keyword: str,
        handler: Optional[Callable] = None,
        priority: str = "medium",
        forward_to: Optional[list] = None,
        auto_reply: bool = False,
        auto_reply_message: str = "",
    ):
        """
        Register a rule to handle incoming alerts matching a keyword.

        Args:
            name: Unique name for this rule.
            keyword: Text to match in subject or body.
            handler: Callback function(alert_data: dict) to invoke on match.
            priority: Expected priority level for logging.
            forward_to: Forward matching alerts to these addresses.
            auto_reply: Send an auto-reply when matched.
            auto_reply_message: Message body for the auto-reply.
        """
        rule = AlertRule(
            name=name,
            keyword=keyword,
            priority=priority,
            forward_to=forward_to,
            auto_reply=auto_reply,
            auto_reply_message=auto_reply_message,
        )
        self.receiver.add_rule(rule, handler)

    def fetch(self) -> list[dict]:
        """Manually fetch and process unread alerts once."""
        return self.receiver.fetch_unread()

    def start(self, poll_interval: Optional[int] = None):
        """Start background polling for incoming alerts."""
        self.receiver.start_polling(poll_interval)

    def stop(self):
        """Stop background polling."""
        self.receiver.stop_polling()
