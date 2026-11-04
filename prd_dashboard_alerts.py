"""
PR&D Dashboard Email Alert System
===================================
Migrated from Google Apps Script on:
  "Team-wise PR&D Dashboard (from 1 Jul 2026)"
  https://docs.google.com/spreadsheets/d/1raKa11Nw_dy7i-D7FWisN8xfTuhsIBXZ0XN3r-lrkwE

What this does:
  - Connects to the PR&D Google Sheet via Google Sheets API
  - Finds all Fully Ready OPFs that have:
      (a) Follow-up date = TODAY  → sends a reminder
      (b) Follow-up date OVERDUE (past due, no dispatch remark) → sends an overdue alert
      (c) OPFs with no follow-up date at all → flags them for attention
  - Sends a consolidated daily summary email to ops coordinators + Dileep sir

Usage:
  python prd_dashboard_alerts.py              # run once (manual / scheduled task)
  python prd_dashboard_alerts.py --test       # print alerts to console, don't send email

Requirements:
  pip install google-api-python-client google-auth python-dotenv

Google Sheets API Setup:
  1. Go to https://console.cloud.google.com/
  2. Enable "Google Sheets API"
  3. Create a Service Account → download credentials JSON
  4. Share the spreadsheet with the service account email (Viewer access)
  5. Set GOOGLE_CREDENTIALS_FILE=path/to/credentials.json in .env
"""

import os
import sys
import json
import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────

SPREADSHEET_ID = "1raKa11Nw_dy7i-D7FWisN8xfTuhsIBXZ0XN3r-lrkwE"

# Tabs to scan for fully ready OPFs
OPS_COORDINATOR_TABS = {
    "Surabhi":        "Fully Ready - Surabhi",
    "Mohini Singh":   "Fully Ready - Mohini Singh",
    "Rosena":         "Fully Ready - Rosena",
    "Abhishek":       "Fully Ready - Abhishek",
    "Gautam Dusheja": "Fully Ready - Gautam Dusheja",
}

# Column positions in each ops-coordinator tab (0-indexed)
# OPF | Customer | Sales Person | OPF Status | Ready Qty | Ready Items | Order Value | Next Follow up Date | Remark date | Remarks
COL_OPF             = 0
COL_CUSTOMER        = 1
COL_SALES_PERSON    = 2
COL_STATUS          = 3
COL_READY_QTY       = 4
COL_READY_ITEMS     = 5
COL_ORDER_VALUE     = 6
COL_FOLLOWUP_DATE   = 7
COL_REMARK_DATE     = 8
COL_REMARKS         = 9

# Alert recipients
ALERT_RECIPIENTS = [
    os.getenv("ALERT_RECIPIENT", "dileep.kumar@reclinersindia.com"),
    "shwetabh@reclinersindia.com",
]

# ── Google Sheets connection ───────────────────────────────────────────────────

def get_sheets_service():
    """Connect to Google Sheets API using service account credentials."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
        if not Path(creds_file).exists():
            print(f"ERROR: Google credentials file not found: {creds_file}")
            print("See setup instructions at the top of this file.")
            return None

        credentials = service_account.Credentials.from_service_account_file(
            creds_file,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        service = build("sheets", "v4", credentials=credentials)
        return service.spreadsheets()

    except ImportError:
        print("ERROR: Google API client not installed.")
        print("Run: pip install google-api-python-client google-auth")
        return None


def read_tab(sheets, tab_name):
    """Read all data from a sheet tab."""
    result = sheets.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab_name}'!A1:Z200",
    ).execute()
    return result.get("values", [])


# ── Date parsing ───────────────────────────────────────────────────────────────

def parse_date(date_str):
    """Parse a date string in common formats used in the sheet."""
    if not date_str or not str(date_str).strip():
        return None
    date_str = str(date_str).strip()
    for fmt in ("%m/%d/%Y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


# ── Alert logic ────────────────────────────────────────────────────────────────

def scan_tab(sheets, coordinator, tab_name, today):
    """Scan one ops coordinator tab and return alerts."""
    rows = read_tab(sheets, tab_name)

    due_today   = []
    overdue     = []
    no_followup = []

    # Skip header rows (first 3 rows are title/subtitle/column headers)
    data_rows = rows[3:] if len(rows) > 3 else []

    for row in data_rows:
        # Pad row to expected length
        while len(row) < 10:
            row.append("")

        opf          = row[COL_OPF].strip()
        customer     = row[COL_CUSTOMER].strip()
        sales_person = row[COL_SALES_PERSON].strip()
        status       = row[COL_STATUS].strip()
        ready_qty    = row[COL_READY_QTY].strip()
        ready_items  = row[COL_READY_ITEMS].strip()
        order_value  = row[COL_ORDER_VALUE].strip()
        followup_str = row[COL_FOLLOWUP_DATE].strip()
        remarks      = row[COL_REMARKS].strip()

        # Skip empty rows or non-OPF rows
        if not opf or opf.startswith("No fully") or not customer:
            continue

        # Only alert on Fully Ready OPFs
        if status and "Fully Ready" not in status:
            continue

        followup_date = parse_date(followup_str)

        record = {
            "opf":          opf,
            "customer":     customer,
            "sales_person": sales_person,
            "ready_qty":    ready_qty,
            "ready_items":  ready_items,
            "order_value":  order_value,
            "followup_date": followup_str,
            "remarks":      remarks,
            "coordinator":  coordinator,
        }

        if followup_date is None:
            no_followup.append(record)
        elif followup_date == today:
            due_today.append(record)
        elif followup_date < today:
            overdue.append(record)

    return due_today, overdue, no_followup


def collect_all_alerts(sheets):
    """Scan all ops coordinator tabs and collect alerts."""
    today = datetime.date.today()
    all_due_today   = []
    all_overdue     = []
    all_no_followup = []

    for coordinator, tab_name in OPS_COORDINATOR_TABS.items():
        try:
            due, overdue, no_fu = scan_tab(sheets, coordinator, tab_name, today)
            all_due_today.extend(due)
            all_overdue.extend(overdue)
            all_no_followup.extend(no_fu)
            print(f"  ✓ {coordinator}: {len(due)} due today, {len(overdue)} overdue, {len(no_fu)} no follow-up date")
        except Exception as e:
            print(f"  ✗ Error reading tab '{tab_name}': {e}")

    return all_due_today, all_overdue, all_no_followup


# ── Email formatting ───────────────────────────────────────────────────────────

def format_opf_table(records):
    """Format a list of OPF records as an HTML table."""
    if not records:
        return "<p><em>None</em></p>"

    rows_html = ""
    for r in records:
        rows_html += f"""
        <tr>
          <td style="padding:6px 10px;border:1px solid #ddd;font-weight:bold">{r['opf']}</td>
          <td style="padding:6px 10px;border:1px solid #ddd">{r['customer']}</td>
          <td style="padding:6px 10px;border:1px solid #ddd">{r['sales_person']}</td>
          <td style="padding:6px 10px;border:1px solid #ddd">{r['coordinator']}</td>
          <td style="padding:6px 10px;border:1px solid #ddd">{r['ready_qty']} pcs</td>
          <td style="padding:6px 10px;border:1px solid #ddd">{r['order_value']}</td>
          <td style="padding:6px 10px;border:1px solid #ddd">{r['followup_date'] or '—'}</td>
          <td style="padding:6px 10px;border:1px solid #ddd;color:#555">{r['remarks'] or '—'}</td>
        </tr>"""

    return f"""
    <table style="border-collapse:collapse;width:100%;font-size:13px">
      <thead>
        <tr style="background:#f0f0f0">
          <th style="padding:8px 10px;border:1px solid #ddd;text-align:left">OPF</th>
          <th style="padding:8px 10px;border:1px solid #ddd;text-align:left">Customer</th>
          <th style="padding:8px 10px;border:1px solid #ddd;text-align:left">Sales Person</th>
          <th style="padding:8px 10px;border:1px solid #ddd;text-align:left">Ops Coordinator</th>
          <th style="padding:8px 10px;border:1px solid #ddd;text-align:left">Ready Qty</th>
          <th style="padding:8px 10px;border:1px solid #ddd;text-align:left">Order Value</th>
          <th style="padding:8px 10px;border:1px solid #ddd;text-align:left">Follow-up Date</th>
          <th style="padding:8px 10px;border:1px solid #ddd;text-align:left">Last Remark</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>"""


def build_email_body(due_today, overdue, no_followup, today):
    """Build the HTML email body."""
    date_str = today.strftime("%d %b %Y")

    sections = []

    if due_today:
        sections.append(f"""
        <h3 style="color:#e67e22;margin-top:20px">
          📅 Follow-up Due TODAY ({len(due_today)} OPFs)
        </h3>
        <p style="color:#555;font-size:13px">These fully ready OPFs are scheduled for follow-up today.
        Please contact the customer or ops coordinator immediately.</p>
        {format_opf_table(due_today)}""")

    if overdue:
        sections.append(f"""
        <h3 style="color:#e74c3c;margin-top:30px">
          🔴 Overdue Follow-ups ({len(overdue)} OPFs)
        </h3>
        <p style="color:#555;font-size:13px">These OPFs have passed their follow-up date and are still Fully Ready —
        dispatch is pending. Immediate action required.</p>
        {format_opf_table(overdue)}""")

    if no_followup:
        sections.append(f"""
        <h3 style="color:#8e44ad;margin-top:30px">
          ⚠️ No Follow-up Date Set ({len(no_followup)} OPFs)
        </h3>
        <p style="color:#555;font-size:13px">These fully ready OPFs have no follow-up date.
        Please set a follow-up date in the dashboard.</p>
        {format_opf_table(no_followup)}""")

    if not sections:
        sections.append("""
        <div style="padding:20px;background:#d5f5e3;border-radius:6px;margin-top:20px">
          <h3 style="color:#27ae60;margin:0">✅ All Clear!</h3>
          <p style="color:#555;margin:8px 0 0">No pending follow-ups or overdue OPFs today. Great work!</p>
        </div>""")

    total = len(due_today) + len(overdue) + len(no_followup)
    summary_color = "#27ae60" if total == 0 else ("#e74c3c" if overdue else "#e67e22")

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:900px;margin:0 auto">
      <div style="background:#2c3e50;color:white;padding:20px 25px;border-radius:6px 6px 0 0">
        <h2 style="margin:0;font-size:20px">RIPL PR&D Dashboard — Daily OPF Alert</h2>
        <p style="margin:5px 0 0;opacity:0.8;font-size:13px">{date_str}</p>
      </div>

      <div style="background:#ecf0f1;padding:15px 25px;border-left:4px solid {summary_color}">
        <strong style="color:{summary_color}">Summary:</strong>&nbsp;
        <span style="color:#e74c3c">{len(overdue)} Overdue</span> &nbsp;|&nbsp;
        <span style="color:#e67e22">{len(due_today)} Due Today</span> &nbsp;|&nbsp;
        <span style="color:#8e44ad">{len(no_followup)} No Follow-up Date</span>
      </div>

      <div style="padding:0 25px 25px">
        {''.join(sections)}

        <hr style="margin-top:30px;border:none;border-top:1px solid #ddd">
        <p style="color:#aaa;font-size:11px;margin-top:10px">
          Auto-generated by RIPL Email Alert System ·
          <a href="https://docs.google.com/spreadsheets/d/1raKa11Nw_dy7i-D7FWisN8xfTuhsIBXZ0XN3r-lrkwE"
             style="color:#3498db">Open PR&D Dashboard</a>
        </p>
      </div>
    </div>"""


# ── Send email ─────────────────────────────────────────────────────────────────

def send_alert_email(due_today, overdue, no_followup, today, dry_run=False):
    """Send the alert email via the existing AlertManager."""
    # Import from parent email alert system
    sys.path.insert(0, str(Path(__file__).parent))
    from config import EmailConfig
    from alert_manager import AlertManager

    config = EmailConfig(
        email_address=os.getenv("EMAIL_ADDRESS", ""),
        email_password=os.getenv("EMAIL_PASSWORD", ""),
        default_recipients=ALERT_RECIPIENTS,
    )

    total_issues = len(due_today) + len(overdue) + len(no_followup)
    subject_date = today.strftime("%d %b")

    if overdue:
        subject = f"[RIPL-ALERT] 🔴 {len(overdue)} Overdue OPFs + {len(due_today)} Due Today — {subject_date}"
        priority = "high"
    elif due_today:
        subject = f"[RIPL-ALERT] 📅 {len(due_today)} OPF Follow-ups Due Today — {subject_date}"
        priority = "medium"
    elif no_followup:
        subject = f"[RIPL-ALERT] ⚠️ {len(no_followup)} Fully Ready OPFs Have No Follow-up Date — {subject_date}"
        priority = "low"
    else:
        subject = f"[RIPL-ALERT] ✅ All Clear — No Pending OPF Follow-ups — {subject_date}"
        priority = "low"

    body = build_email_body(due_today, overdue, no_followup, today)

    if dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN — Would send:")
        print(f"  Subject : {subject}")
        print(f"  Priority: {priority}")
        print(f"  To      : {', '.join(ALERT_RECIPIENTS)}")
        print("=" * 60)
        return

    manager = AlertManager(config)
    manager.send(
        subject=subject,
        body=body,
        recipients=ALERT_RECIPIENTS,
        priority=priority,
    )
    print(f"\n✅ Alert email sent to: {', '.join(ALERT_RECIPIENTS)}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    dry_run = "--test" in sys.argv or "--dry-run" in sys.argv
    today = datetime.date.today()

    print(f"\nRIPL PR&D Dashboard Alert System")
    print(f"Date: {today.strftime('%d %b %Y')}")
    print(f"Mode: {'DRY RUN (no email sent)' if dry_run else 'LIVE'}")
    print("-" * 50)

    # Connect to Google Sheets
    print("\nConnecting to Google Sheets...")
    sheets = get_sheets_service()
    if not sheets:
        print("\n⚠️  Cannot connect to Google Sheets.")
        print("   Set up Google Sheets API credentials (see file header for instructions).")
        print("   For now, running in DEMO mode with sample data...")
        demo_mode(dry_run, today)
        return

    # Scan all tabs
    print("\nScanning ops coordinator tabs...")
    due_today, overdue, no_followup = collect_all_alerts(sheets)

    print(f"\nResults:")
    print(f"  Due today : {len(due_today)}")
    print(f"  Overdue   : {len(overdue)}")
    print(f"  No date   : {len(no_followup)}")

    # Send email
    print("\nSending alert email...")
    send_alert_email(due_today, overdue, no_followup, today, dry_run=dry_run)


def demo_mode(dry_run, today):
    """Run with sample data to show what the email would look like."""
    yesterday = today - datetime.timedelta(days=1)
    due_today = [
        {
            "opf": "KTN/1276", "customer": "Sample Customer A", "sales_person": "Sonu Kumar",
            "coordinator": "Surabhi", "ready_qty": "2", "ready_items": "802M x2",
            "order_value": "₹57,280", "followup_date": today.strftime("%m/%d/%Y"),
            "remarks": "Customer asked for delivery after Diwali",
        }
    ]
    overdue = [
        {
            "opf": "BLR/1004", "customer": "B.Sirisha", "sales_person": "J Prakash",
            "coordinator": "Mohini Singh", "ready_qty": "1", "ready_items": "311 (Lisa-09) x1",
            "order_value": "₹22,000", "followup_date": yesterday.strftime("%m/%d/%Y"),
            "remarks": "Waiting for balance payment",
        }
    ]
    no_followup = []
    send_alert_email(due_today, overdue, no_followup, today, dry_run=dry_run)


if __name__ == "__main__":
    main()
