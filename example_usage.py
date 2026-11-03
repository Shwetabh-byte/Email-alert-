"""
Example usage of the Email Alert System.

Run:  python example_usage.py
Requires environment variables (see .env.example).
"""

import os
from dotenv import load_dotenv

load_dotenv()  # Load .env file if present

from config import EmailConfig
from alert_manager import AlertManager


def handle_server_alert(alert: dict):
    """Custom handler for server alerts."""
    print(f"\n🔴 SERVER ALERT RECEIVED")
    print(f"   From    : {alert['sender']}")
    print(f"   Subject : {alert['subject']}")
    print(f"   Priority: {alert['priority']}")
    print(f"   Body    : {alert['body'][:200]}...")


def handle_low_stock_alert(alert: dict):
    """Custom handler for inventory/stock alerts."""
    print(f"\n🟠 STOCK ALERT RECEIVED")
    print(f"   Subject : {alert['subject']}")
    print(f"   Received: {alert['received_at']}")


def main():
    # ── Configure ─────────────────────────────────────────────────────────────
    config = EmailConfig(
        email_address=os.getenv("EMAIL_ADDRESS", "your_email@gmail.com"),
        email_password=os.getenv("EMAIL_PASSWORD", "your_app_password"),
        default_recipients=[os.getenv("ALERT_RECIPIENT", "recipient@example.com")],
        subject_prefix="[RIPL-ALERT]",
        poll_interval=60,
    )

    manager = AlertManager(config)

    # ── Register Receiving Rules ───────────────────────────────────────────────
    manager.on(
        name="server_down",
        keyword="server down",
        handler=handle_server_alert,
        priority="critical",
    )

    manager.on(
        name="low_stock",
        keyword="low stock",
        handler=handle_low_stock_alert,
        priority="high",
    )

    manager.on(
        name="payment_received",
        keyword="payment received",
        priority="medium",
        # No handler — just logs it
    )

    # ── Send Example Alerts ───────────────────────────────────────────────────
    print("Sending test alerts...\n")

    manager.send_critical(
        subject="Server Down",
        body="Production server at 192.168.1.1 is unreachable.\nDowntime started: 14:32 IST.",
    )

    manager.send_high(
        subject="Low Stock Warning",
        body="Recliner Model RX-200 stock is below 10 units. Reorder needed.",
    )

    manager.send(
        subject="Payment Received",
        body="Invoice #INV-2026-0089 paid by Cinepolis Delhi. Amount: ₹1,45,000.",
        priority="low",
    )

    # Bulk send example
    manager.send_bulk([
        {"subject": "KPI Reminder", "body": "Weekly KPI review due tomorrow.", "priority": "low"},
        {"subject": "Deadline Alert", "body": "Project X deadline is today 6 PM.", "priority": "high"},
    ])

    print("\nAll test alerts sent.")
    print("\nStarting inbox polling (press Ctrl+C to stop)...")

    # ── Start Polling for Incoming Alerts ─────────────────────────────────────
    manager.start(poll_interval=30)

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping alert system...")
        manager.stop()
        print("Done.")


if __name__ == "__main__":
    main()
