"""
Configuration for Email Alert System.
Copy config_example.py to config.py and fill in your credentials.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EmailConfig:
    """Email server configuration."""

    # SMTP settings (for sending)
    smtp_server: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_use_tls: bool = True

    # IMAP settings (for receiving)
    imap_server: str = os.getenv("IMAP_SERVER", "imap.gmail.com")
    imap_port: int = int(os.getenv("IMAP_PORT", "993"))
    imap_use_ssl: bool = True

    # Credentials
    email_address: str = os.getenv("EMAIL_ADDRESS", "")
    email_password: str = os.getenv("EMAIL_PASSWORD", "")  # Use App Password for Gmail

    # Alert defaults
    default_sender: str = os.getenv("DEFAULT_SENDER", "")
    default_recipients: list = field(default_factory=list)

    # Polling interval for receiving alerts (seconds)
    poll_interval: int = int(os.getenv("POLL_INTERVAL", "60"))

    # Alert subject prefix
    subject_prefix: str = os.getenv("SUBJECT_PREFIX", "[ALERT]")

    # Log file
    log_file: str = os.getenv("LOG_FILE", "alerts.log")

    def __post_init__(self):
        if not self.default_sender:
            self.default_sender = self.email_address


@dataclass
class AlertRule:
    """Defines a rule for processing incoming alerts."""

    name: str
    keyword: str  # Keyword to match in subject or body
    priority: str = "medium"  # low, medium, high, critical
    callback: Optional[str] = None  # Python function path to call
    forward_to: Optional[list] = None  # Forward matching alerts to these addresses
    auto_reply: bool = False
    auto_reply_message: str = ""
