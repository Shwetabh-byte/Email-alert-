#!/usr/bin/env python3
"""
Daily OPF Alert Dispatcher — called by Claude's scheduled task.

This script:
1. Fetches live data from Google Sheets via the MCP connector
2. Builds HTML email bodies for each coordinator
3. Prints structured JSON to stdout so Claude can send via Gmail MCP

Usage (by Claude scheduled task):
    python3 run_daily_alerts.py

Output: JSON list of {to, cc, subject, body} dicts, one per coordinator,
        printed to stdout between markers <<<EMAILS>>> and <<<END>>>.
"""
import sys
import os
import json
import datetime

# Add parent dir so we can import the main module
sys.path.insert(0, os.path.dirname(__file__))

from prd_dashboard_alerts import (
    COORDINATOR_CONFIG,
    CC_RECIPIENTS,
    build_subject,
    build_coordinator_email,
    collect_all_alerts,
    get_sheets_service,
)


def main():
    today = datetime.date.today()
    print(f"[run_daily_alerts] Running for {today.strftime('%d-%b-%Y')}", flush=True)

    sheets = get_sheets_service()
    if sheets is None:
        print("[run_daily_alerts] ERROR: Could not connect to Google Sheets", flush=True)
        sys.exit(1)

    coordinator_data = collect_all_alerts(sheets)

    emails = []
    for coordinator, data in coordinator_data.items():
        cfg       = COORDINATOR_CONFIG[coordinator]
        all_rec   = data["all"]
        due_today = data["due_today"]
        overdue   = data["overdue"]
        n_due     = len(due_today)
        n_overdue = len(overdue)

        subject = build_subject(coordinator, n_due, n_overdue, today)
        body    = build_coordinator_email(
            coordinator, all_rec, due_today, overdue, today, cfg["gid"]
        )

        emails.append({
            "coordinator": coordinator,
            "to":          cfg["email"],
            "cc":          CC_RECIPIENTS,
            "subject":     subject,
            "body":        body,
            "n_due":       n_due,
            "n_overdue":   n_overdue,
        })

        print(f"  Prepared: {coordinator} — {n_due} due today, {n_overdue} overdue", flush=True)

    print("<<<EMAILS>>>")
    print(json.dumps(emails, ensure_ascii=False))
    print("<<<END>>>")


if __name__ == "__main__":
    main()
