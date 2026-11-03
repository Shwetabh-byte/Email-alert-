# Email Alert System

A Python system for **sending and receiving email alerts** via SMTP/IMAP. Built for process monitoring, operations alerts, and automated notifications.

## Features

- ✅ Send alerts with priority levels (low / medium / high / critical)
- ✅ Auto-formatted subject lines with priority tags
- ✅ HTML + plain-text email bodies
- ✅ File attachments support
- ✅ Bulk sending in a single SMTP session
- ✅ IMAP inbox monitoring (polling-based)
- ✅ Rule-based alert routing with custom handlers
- ✅ Background polling thread
- ✅ Structured logging to file + console
- ✅ Works with Gmail, Outlook, or any SMTP/IMAP provider

## Project Structure

```
email-alert-system/
├── config.py           # Configuration dataclasses
├── alert_sender.py     # SMTP sending logic
├── alert_receiver.py   # IMAP receiving & rule matching
├── alert_manager.py    # Unified high-level API
├── example_usage.py    # Full working example
├── requirements.txt
├── .env.example        # Environment variable template
└── .gitignore
```

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env with your email and App Password
```

> **Gmail users:** Create an App Password at  
> https://myaccount.google.com/apppasswords  
> (requires 2FA enabled on your Google account)

### 3. Run the example

```bash
python example_usage.py
```

## Usage

### Sending Alerts

```python
from config import EmailConfig
from alert_manager import AlertManager

config = EmailConfig(
    email_address="you@gmail.com",
    email_password="your_app_password",
    default_recipients=["team@yourcompany.com"],
)

manager = AlertManager(config)

# Send by priority
manager.send_critical("Server Down", "Production server is unreachable.")
manager.send_high("Low Stock", "Item RX-200 has fewer than 10 units.")
manager.send("Payment Received", "Invoice #1234 paid.", priority="low")

# Send with attachment
manager.send(
    subject="Daily Report",
    body="See attached report.",
    attachments=["/path/to/report.pdf"],
    priority="medium",
)

# Bulk send
manager.send_bulk([
    {"subject": "Alert A", "body": "Message A", "priority": "high"},
    {"subject": "Alert B", "body": "Message B", "priority": "low"},
])
```

### Receiving Alerts

```python
def my_handler(alert: dict):
    print(f"Got alert: {alert['subject']}")
    print(f"Priority : {alert['priority']}")
    print(f"Body     : {alert['body']}")

# Register a rule — triggers when 'server down' appears in subject/body
manager.on(
    name="server_monitor",
    keyword="server down",
    handler=my_handler,
    priority="critical",
)

# Start background polling every 60 seconds
manager.start(poll_interval=60)

# Or fetch manually (one-shot)
alerts = manager.fetch()
```

## Alert Priority Levels

| Priority | Email Header | Use Case |
|----------|-------------|----------|
| `critical` | X-Priority: 1 | System down, data loss |
| `high` | X-Priority: 2 | Threshold breach, urgent action |
| `medium` | X-Priority: 3 | Standard notifications |
| `low` | X-Priority: 5 | FYI, informational |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EMAIL_ADDRESS` | — | Your email address |
| `EMAIL_PASSWORD` | — | App password (not login password) |
| `SMTP_SERVER` | `smtp.gmail.com` | SMTP server |
| `SMTP_PORT` | `587` | SMTP port |
| `IMAP_SERVER` | `imap.gmail.com` | IMAP server |
| `IMAP_PORT` | `993` | IMAP port |
| `SUBJECT_PREFIX` | `[ALERT]` | Subject prefix for filtering |
| `POLL_INTERVAL` | `60` | Polling interval in seconds |
| `LOG_FILE` | `alerts.log` | Log output file |

## Using with Other Providers

**Outlook / Microsoft 365:**
```
SMTP_SERVER=smtp.office365.com
SMTP_PORT=587
IMAP_SERVER=outlook.office365.com
IMAP_PORT=993
```

**Yahoo Mail:**
```
SMTP_SERVER=smtp.mail.yahoo.com
SMTP_PORT=587
IMAP_SERVER=imap.mail.yahoo.com
IMAP_PORT=993
```
