"""
PR&D Dashboard Email Alert System
===================================
Source sheet:
  "Team-wise PR&D Dashboard (from 1 Jul 2026)"
  https://docs.google.com/spreadsheets/d/1raKa11Nw_dy7i-D7FWisN8xfTuhsIBXZ0XN3r-lrkwE

Data flow:
  New DOD Master → Data!A1 formula (aggregates & assigns coordinator) → per-coordinator tabs

What this does:
  - Connects to the PR&D Google Sheet via Google Sheets API
  - Reads the hidden Data tab (all OPFs with coordinator assignment already done)
  - Categorises OPFs with any ready qty (Ready or Ready FF) that have:
      (a) Follow-up date = TODAY  → sends a reminder
      (b) Follow-up date OVERDUE (past due) → sends an overdue alert
      (c) No follow-up date at all → flags them for attention
  - Sends a consolidated daily summary email to ops coordinators + Dileep sir

OPF Status values from new DOD Master (after aggregation in Data tab):
  "Fully Ready"             — all items status = Ready, nothing pending
  "Fully Ready (FF)"        — all items status = Ready FF
  "All pcs Ready FF"        — same as above (Ready FF only)
  "Partly Ready – N pcs pending" — mix of Ready items + pending qty

Usage:
  python prd_dashboard_alerts.py              # run once (manual / scheduled task)
  python prd_dashboard_alerts.py --test       # print alerts to console, don't send email
  python prd_dashboard_alerts.py --dry-run    # same as --test

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

# Per-coordinator email addresses and sheet tab GIDs
# (GID used to build the deep-link to their specific tab in the sheet)
COORDINATOR_CONFIG = {
    "Surabhi":        {"email": "operation2@reclinersindia.com",   "gid": "602"},
    "Mohini Singh":   {"email": "operation1@reclinersindia.com",   "gid": "601"},
    "Rosena":         {"email": "rosena.jamal@reclinersindia.com",  "gid": "603"},
    "Abhishek":       {"email": "abhishek.sharma@reclinersindia.com", "gid": "604"},
    "Gautam Dusheja": {"email": "gautam.duseja@gulfrecliners.com",  "gid": "605"},
}

# CC on every mail
CC_RECIPIENTS = ["shwetabh@reclinersindia.com"]

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

    # Skip header rows:
    #   Row 0 — Tab title  (e.g. "Fully Ready - Surabhi")
    #   Row 1 — Subtitle / generated date
    #   Row 2 — Filter info row
    #   Row 3 — Column headers (OPF | Customer | …)
    #   Row 4+ — Data
    data_rows = rows[4:] if len(rows) > 4 else []

    # Statuses from the new DOD Master formula that indicate action is needed.
    # "Partly Ready – N pcs pending" is included so coordinators know some qty
    # is ready even if dispatch is still blocked on the remaining pieces.
    ALERT_STATUSES = {
        "Fully Ready",          # all items Ready, nothing pending
        "Fully Ready (FF)",     # all items Ready FF, nothing pending
        "All pcs Ready FF",     # alias produced by the formula for FF-only OPFs
        "Partly Ready",         # prefix match — catches "Partly Ready – N pcs pending"
    }

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

        # Skip empty rows or placeholder/summary rows
        if not opf or not customer:
            continue
        # Skip formula placeholder messages (e.g. "No data", "No fully ready…")
        if opf.lower().startswith("no ") or customer.lower().startswith("no "):
            continue

        # Only alert on OPFs that have ready (or partly ready) qty
        # Match exact status strings or the "Partly Ready" prefix
        if status:
            matched = any(
                status == s or status.startswith(s)
                for s in ALERT_STATUSES
            )
            if not matched:
                continue

        followup_date = parse_date(followup_str)

        record = {
            "opf":          opf,
            "customer":     customer,
            "sales_person": sales_person,
            "status":       status,
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
    """Scan all ops coordinator tabs and return per-coordinator data dict."""
    today = datetime.date.today()
    coordinator_data = {}

    for coordinator, tab_name in OPS_COORDINATOR_TABS.items():
        try:
            due, overdue, no_fu = scan_tab(sheets, coordinator, tab_name, today)
            # "all" = every record in this coordinator's tab (for the summary stats)
            all_records = due + overdue + no_fu
            coordinator_data[coordinator] = {
                "all":        all_records,
                "due_today":  due,
                "overdue":    overdue,
                "no_followup": no_fu,
            }
            print(f"  ✓ {coordinator}: {len(all_records)} OPFs | {len(due)} due today, {len(overdue)} overdue, {len(no_fu)} no date")
        except Exception as e:
            print(f"  ✗ Error reading tab '{tab_name}': {e}")

    return coordinator_data


# ── Email formatting (matches existing sent-mail style exactly) ────────────────

TH = 'style="background:#1F3864;color:#fff;padding:8px 14px;border:1px solid #c9c9c9;font-size:14px;text-align:left;font-weight:normal"'
TD = 'style="background:#EEF2F8;padding:8px 14px;border:1px solid #d9d9d9;font-size:14px;font-weight:bold"'
TH2 = 'style="background:#1F3864;color:#fff;padding:6px 10px;border:1px solid #c9c9c9;font-size:13px;text-align:left"'
TD2 = 'style="padding:6px 10px;border:1px solid #d9d9d9;font-size:13px"'
TD2R = 'style="padding:6px 10px;border:1px solid #d9d9d9;font-size:13px;text-align:right"'


def _parse_value(val_str):
    """Convert '₹2,05,000' or '205000' to int for summing."""
    try:
        return int(str(val_str).replace("₹", "").replace(",", "").strip())
    except Exception:
        return 0


def build_coordinator_email(coordinator, all_records, due_today_records, today, gid):
    """Build per-coordinator HTML email matching the existing sent-mail style."""
    date_str = today.strftime("%d-%b-%Y")

    # Summary stats across ALL records for this coordinator
    total_opfs  = len(all_records)
    total_pcs   = sum(_parse_value(r.get("ready_qty", 0)) for r in all_records)
    total_value = sum(_parse_value(r.get("order_value", 0)) for r in all_records)
    value_fmt   = f"₹{total_value:,}" if total_value else "₹0"

    # Summary table (always shown)
    summary_table = f"""
<table style="border-collapse:collapse;font-family:Arial,sans-serif;margin:0 0 14px 0">
  <tr>
    <th {TH}>Ops Coordinator</th>
    <th {TH}>Fully Ready OPFs</th>
    <th {TH}>Pieces Ready</th>
    <th {TH}>Value Ready (₹)</th>
  </tr>
  <tr>
    <td {TD}>{coordinator}</td>
    <td {TD}>{total_opfs}</td>
    <td {TD}>{total_pcs}</td>
    <td {TD}>{value_fmt}</td>
  </tr>
</table>"""

    sheet_link = (
        f'https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={gid}'
    )

    first_name = coordinator.split()[0]
    html = f"""<div style="font-family:Arial,sans-serif;font-size:14px;color:#222">
<p>Hi {first_name},</p>
<p style="font-weight:bold;font-size:15px;margin:14px 0 4px 0">Your Fully Ready OPF Summary</p>
{summary_table}
<p>After following up, update the <b>Remark date</b>, <b>Remarks</b> and the <b>Next Follow up Date</b> in your tab: <a href="{sheet_link}">open your tab</a>.</p>
<p style="color:#888;font-size:12px">Automatic reminder from the Team-wise OPF Readiness Dashboard.</p>
</div>"""

    return html


def build_subject(coordinator, n_due, today):
    date_str = today.strftime("%d-%b-%Y")
    if n_due:
        return f"Daily fully ready OPF status – {date_str} ({n_due} follow-up{'s' if n_due!=1 else ''} due today)"
    else:
        return f"Daily fully ready OPF status – {date_str} (0 follow-ups due today)"


# ── Send per-coordinator email ─────────────────────────────────────────────────

def send_coordinator_emails(coordinator_data, today, dry_run=False):
    """Send one email per coordinator, matching the existing sent-mail style."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp_server  = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port    = int(os.getenv("SMTP_PORT", 587))
    email_addr   = os.getenv("EMAIL_ADDRESS", "")
    email_pass   = os.getenv("EMAIL_PASSWORD", "")

    for coordinator, data in coordinator_data.items():
        cfg            = COORDINATOR_CONFIG[coordinator]
        all_records    = data["all"]
        due_today      = data["due_today"]
        n_due          = len(due_today)

        subject = build_subject(coordinator, n_due, today)
        body    = build_coordinator_email(
            coordinator, all_records, due_today, today, cfg["gid"]
        )
        to_addr = cfg["email"]

        if dry_run:
            print(f"\n{'='*60}")
            print(f"DRY RUN — {coordinator}")
            print(f"  To      : {to_addr}")
            print(f"  CC      : {', '.join(CC_RECIPIENTS)}")
            print(f"  Subject : {subject}")
            print(f"  OPFs    : {len(all_records)} total | {n_due} due today")
            print(f"{'='*60}")
            continue

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"OPF Follow-up Reminder <{email_addr}>"
        msg["To"]      = to_addr
        msg["Cc"]      = ", ".join(CC_RECIPIENTS)
        msg.attach(MIMEText(body, "html"))

        recipients = [to_addr] + CC_RECIPIENTS
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(email_addr, email_pass)
            server.sendmail(email_addr, recipients, msg.as_string())

        print(f"  ✅ Sent to {coordinator} ({to_addr})")


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
    coordinator_data = collect_all_alerts(sheets)

    total_due = sum(len(d["due_today"]) for d in coordinator_data.values())
    total_ov  = sum(len(d["overdue"])   for d in coordinator_data.values())
    print(f"\nResults: {total_due} due today, {total_ov} overdue across all coordinators")

    # Send one email per coordinator
    print(f"\n{'Previewing' if dry_run else 'Sending'} emails...")
    send_coordinator_emails(coordinator_data, today, dry_run=dry_run)


def demo_mode(dry_run, today):
    """Run with sample data matching the real coordinator structure."""
    yesterday = today - datetime.timedelta(days=1)

    coordinator_data = {
        "Surabhi": {
            "all": [
                {"opf":"KTN/1276","customer":"Prakshit Garg","sales_person":"Sonu Kumar","status":"Fully Ready","ready_qty":"7","order_value":"₹1,39,240","followup_date":today.strftime("%m/%d/%Y"),"remarks":""},
                {"opf":"BOM/0821","customer":"SAWARIA AGRO INDUSTRIES","sales_person":"Ali Ahmed","status":"Fully Ready","ready_qty":"13","order_value":"₹3,99,858","followup_date":today.strftime("%m/%d/%Y"),"remarks":""},
                {"opf":"DLH/1105","customer":"Mrs. Manisha Mehra","sales_person":"Payal Mandal","status":"Fully Ready","ready_qty":"5","order_value":"₹2,05,000","followup_date":yesterday.strftime("%m/%d/%Y"),"remarks":"Follow-up pending"},
            ],
            "due_today": [
                {"opf":"KTN/1276","customer":"Prakshit Garg","sales_person":"Sonu Kumar","status":"Fully Ready","ready_qty":"7","order_value":"₹1,39,240","followup_date":today.strftime("%m/%d/%Y"),"remarks":""},
                {"opf":"BOM/0821","customer":"SAWARIA AGRO INDUSTRIES","sales_person":"Ali Ahmed","status":"Fully Ready","ready_qty":"13","order_value":"₹3,99,858","followup_date":today.strftime("%m/%d/%Y"),"remarks":""},
            ],
            "overdue": [],
            "no_followup": [],
        },
        "Mohini Singh": {
            "all": [
                {"opf":"BLR/1004","customer":"B.Sirisha","sales_person":"J Prakash","status":"Fully Ready","ready_qty":"1","order_value":"₹22,000","followup_date":yesterday.strftime("%m/%d/%Y"),"remarks":"Waiting for balance payment"},
            ],
            "due_today": [],
            "overdue": [
                {"opf":"BLR/1004","customer":"B.Sirisha","sales_person":"J Prakash","status":"Fully Ready","ready_qty":"1","order_value":"₹22,000","followup_date":yesterday.strftime("%m/%d/%Y"),"remarks":"Waiting for balance payment"},
            ],
            "no_followup": [],
        },
        "Gautam Dusheja": {
            "all": [
                {"opf":"HYD/0987","customer":"Gulf Furnishings","sales_person":"Dileep Kumar","status":"All pcs Ready FF","ready_qty":"3","order_value":"₹85,500","followup_date":"","remarks":"Confirm shipping address"},
            ],
            "due_today": [],
            "overdue":   [],
            "no_followup": [
                {"opf":"HYD/0987","customer":"Gulf Furnishings","sales_person":"Dileep Kumar","status":"All pcs Ready FF","ready_qty":"3","order_value":"₹85,500","followup_date":"","remarks":"Confirm shipping address"},
            ],
        },
    }
    send_coordinator_emails(coordinator_data, today, dry_run=dry_run)


if __name__ == "__main__":
    main()
