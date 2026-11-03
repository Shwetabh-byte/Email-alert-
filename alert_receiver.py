"""
Email Alert Receiver Module.
Monitors inbox via IMAP and processes incoming alert emails.
"""

import imaplib
import email
import logging
import time
import threading
from datetime import datetime
from email.header import decode_header
from typing import Callable, Optional

from config import EmailConfig, AlertRule

logger = logging.getLogger(__name__)


class AlertReceiver:
    """Monitors email inbox and processes incoming alerts."""

    def __init__(self, config: EmailConfig):
        self.config = config
        self.rules: list[AlertRule] = []
        self.handlers: dict[str, Callable] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
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

    def add_rule(self, rule: AlertRule, handler: Optional[Callable] = None):
        """
        Add a rule for processing incoming alerts.

        Args:
            rule: AlertRule defining what to match.
            handler: Optional callback function(alert_data: dict) to invoke on match.
        """
        self.rules.append(rule)
        if handler:
            self.handlers[rule.name] = handler
        logger.info("Rule added: '%s' (keyword: '%s')", rule.name, rule.keyword)

    def _connect(self) -> imaplib.IMAP4_SSL:
        """Establish IMAP connection."""
        mail = imaplib.IMAP4_SSL(self.config.imap_server, self.config.imap_port)
        mail.login(self.config.email_address, self.config.email_password)
        logger.info("Connected to IMAP server %s", self.config.imap_server)
        return mail

    def _decode_header_value(self, value: str) -> str:
        """Decode encoded email header values."""
        decoded_parts = decode_header(value)
        result = ""
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result += part.decode(charset or "utf-8", errors="replace")
            else:
                result += part
        return result

    def _parse_email(self, raw_email: bytes) -> dict:
        """Parse raw email bytes into a structured dict."""
        msg = email.message_from_bytes(raw_email)

        subject = self._decode_header_value(msg.get("Subject", ""))
        sender = self._decode_header_value(msg.get("From", ""))
        date_str = msg.get("Date", "")
        priority = msg.get("X-Alert-Priority", "unknown")
        timestamp = msg.get("X-Alert-Timestamp", "")

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        body = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        )
                        break
                    except Exception:
                        pass
        else:
            try:
                body = msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or "utf-8", errors="replace"
                )
            except Exception:
                body = str(msg.get_payload())

        return {
            "subject": subject,
            "sender": sender,
            "date": date_str,
            "body": body,
            "priority": priority,
            "alert_timestamp": timestamp,
            "received_at": datetime.now().isoformat(),
            "raw": msg,
        }

    def _match_rules(self, alert_data: dict) -> list[AlertRule]:
        """Find all rules that match the given alert."""
        matches = []
        text_to_check = (
            f"{alert_data['subject']} {alert_data['body']}".lower()
        )

        for rule in self.rules:
            if rule.keyword.lower() in text_to_check:
                matches.append(rule)
                logger.info(
                    "Rule matched: '%s' for alert: '%s'",
                    rule.name,
                    alert_data["subject"],
                )

        return matches

    def _process_alert(self, alert_data: dict):
        """Process a matched alert through all matching rules."""
        matched_rules = self._match_rules(alert_data)

        if not matched_rules:
            logger.info(
                "No rules matched for alert: '%s'", alert_data["subject"]
            )
            return

        for rule in matched_rules:
            # Call registered handler
            if rule.name in self.handlers:
                try:
                    self.handlers[rule.name](alert_data)
                except Exception as e:
                    logger.error(
                        "Handler '%s' raised an error: %s", rule.name, e
                    )

            # Log the match
            logger.info(
                "[RECEIVED ALERT] Rule='%s' | Priority='%s' | Subject='%s' | From='%s'",
                rule.name,
                alert_data.get("priority", "unknown"),
                alert_data["subject"],
                alert_data["sender"],
            )

    def fetch_unread(self) -> list[dict]:
        """
        Fetch and parse all unread alert emails from inbox.

        Returns:
            List of parsed alert dicts.
        """
        alerts = []
        try:
            mail = self._connect()
            mail.select("inbox")

            # Search for unread emails with the alert prefix
            search_criteria = f'(UNSEEN SUBJECT "{self.config.subject_prefix}")'
            status, messages = mail.search(None, search_criteria)

            if status != "OK" or not messages[0]:
                logger.info("No new alert emails found.")
                mail.logout()
                return alerts

            for msg_id in messages[0].split():
                try:
                    status, msg_data = mail.fetch(msg_id, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = msg_data[0][1]
                    alert_data = self._parse_email(raw_email)
                    alerts.append(alert_data)
                    self._process_alert(alert_data)

                    # Mark as read
                    mail.store(msg_id, "+FLAGS", "\\Seen")

                except Exception as e:
                    logger.error("Error processing email ID %s: %s", msg_id, e)

            mail.logout()
            logger.info("Fetched %d new alert(s).", len(alerts))

        except Exception as e:
            logger.error("IMAP connection error: %s", e)

        return alerts

    def start_polling(self, interval: Optional[int] = None):
        """
        Start background polling for new alerts.

        Args:
            interval: Polling interval in seconds (defaults to config value).
        """
        interval = interval or self.config.poll_interval
        self._running = True

        def poll_loop():
            logger.info("Alert polling started (every %ds).", interval)
            while self._running:
                try:
                    self.fetch_unread()
                except Exception as e:
                    logger.error("Polling error: %s", e)
                time.sleep(interval)

        self._thread = threading.Thread(target=poll_loop, daemon=True)
        self._thread.start()

    def stop_polling(self):
        """Stop the background polling thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Alert polling stopped.")
