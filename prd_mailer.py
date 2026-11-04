"""
PR&D Dashboard mails — moved here from the Google Apps Script on
"Team-wise PR&D Dashboard (from 1 Jul 2026)".

Three mails, same content, recipients and timing as the Apps Script sent:

  morning    ~9 AM IST, every day  -> each ops coordinator (Mohini, Surabhi, Abhishek, Gautam)
             "Daily fully ready OPF status – <date> (N follow-ups due today)"
             Always sent, even when nothing is due.
  afternoon  ~4 PM IST, every day  -> same coordinators, ONLY if some OPFs that were due
             today still have no Remark date of today.
             "Reminder: follow-ups still pending today – <date> (N OPFs)"
  weekly     ~10 AM IST, Mondays   -> Dileep ji + Sandeep ji
             "Weekly Fully Ready OPF Dashboard – <date>"

Where the data comes from (read-only):
  * 'Remarks Log' tab  – Next Follow up Date / Remark date per OPF (the same store the
                         sheet uses, so follow-ups stay correct even while tabs re-sort)
  * 'Data' tab         – which OPFs are Fully Ready, with coordinator, qty, value
  * 'Fully Ready Dashboard' – the summary numbers shown in every mail

Usage
  python prd_mailer.py morning            # send (needs .env / GitHub secrets)
  python prd_mailer.py afternoon
  python prd_mailer.py weekly
  python prd_mailer.py morning --draft    # write HTML drafts to drafts/, send nothing
  python prd_mailer.py morning --to-me    # send every mail to TEST_TO only, subject tagged [TEST]
  python prd_mailer.py morning --draft --date 2026-11-12 --snapshot snapshot.json

Environment
  EMAIL_ADDRESS, EMAIL_PASSWORD      Gmail address + App Password (SMTP)
  GOOGLE_CREDENTIALS_JSON            service-account key (JSON text)   — or —
  GOOGLE_CREDENTIALS_FILE            path to that key file
  TEST_TO                            address for --to-me (default: shwetabh@reclinersindia.com)
"""

import argparse
import datetime as dt
import html
import json
import os
import re
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Configuration (mirrors the Apps Script) ──────────────────────────────────
SPREADSHEET_ID = "1raKa11Nw_dy7i-D7FWisN8xfTuhsIBXZ0XN3r-lrkwE"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
DASHBOARD_GID = 300

TABS = {
    # tab name:                     (coordinator email,                     mail?, gid)
    "Fully Ready - Mohini Singh":   ("operation1@reclinersindia.com",        True,  601),
    "Fully Ready - Surabhi":        ("operation2@reclinersindia.com",        True,  602),
    "Fully Ready - Rosena":         ("rosena.jamal@reclinersindia.com",      False, 603),
    "Fully Ready - Abhishek":       ("abhishek.sharma@reclinersindia.com",   True,  604),
    "Fully Ready - Gautam Dusheja": ("gautam.duseja@gulfrecliners.com",      True,  605),
}
WEEKLY_TO = ["dileep.kumar@reclinersindia.com", "sandeep.malhotra@reclinersindia.com"]
MAIL_CC = []                      # e.g. ["shwetabh@reclinersindia.com"]
REMINDER_FROM_NAME = "OPF Follow-up Reminder"
WEEKLY_FROM_NAME = "Shwetabh – OPF Dashboard"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# ── Styles (copied from the Apps Script mails) ───────────────────────────────
TH = 'style="background:#1F3864;color:#fff;padding:6px 10px;border:1px solid #c9c9c9;font-size:13px;text-align:left"'
TD = 'style="padding:6px 10px;border:1px solid #d9d9d9;font-size:13px"'
TDR = 'style="padding:6px 10px;border:1px solid #d9d9d9;font-size:13px;text-align:right"'
TH_BIG = 'style="background:#1F3864;color:#fff;padding:8px 14px;border:1px solid #c9c9c9;font-size:14px;text-align:left;font-weight:normal"'
TD_BIG = 'style="background:#EEF2F8;padding:8px 14px;border:1px solid #d9d9d9;font-size:14px;font-weight:bold"'
TD_TOT = 'style="padding:6px 10px;border:1px solid #d9d9d9;font-size:13px;font-weight:bold;background:#EEF2F8"'
TBL = 'style="border-collapse:collapse;margin:6px 0 18px 0"'


# ── Helpers ──────────────────────────────────────────────────────────────────
def esc(s):
    return html.escape(str(s if s is not None else ""), quote=False)


def num(x):
    if isinstance(x, (int, float)):
        return float(x)
    s = re.sub(r"[^0-9.\-]", "", str(x or ""))
    try:
        return float(s) if s not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def inr(v):
    """Indian grouping: 2746264 -> ₹27,46,264"""
    n = int(round(num(v)))
    neg, s = n < 0, str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = head + "," + tail
    return ("-₹" if neg else "₹") + s


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(v):
    """Accepts sheet serials, 11/3/2026 (M/D/YYYY, how the sheet stores them),
    03-Nov-2026, 2026-11-03."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(v))
    s = str(v).strip()
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})[A-Za-z]*-(\d{2,4})$", s)
    if m:
        y = int(m.group(3)); y += 2000 if y < 100 else 0
        return dt.date(y, MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        y = int(m.group(3)); y += 2000 if y < 100 else 0
        try:
            return dt.date(y, int(m.group(1)), int(m.group(2)))      # M/D/YYYY (sheet locale en_US)
        except ValueError:
            return dt.date(y, int(m.group(2)), int(m.group(1)))
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def fmt_day(d):
    return d.strftime("%d-%b-%Y")


# ── Reading the sheet ────────────────────────────────────────────────────────
RANGES = {
    "log": "'Remarks Log'!A1:G2000",
    "data": "Data!A1:I2000",
    "kpi": "'Fully Ready Dashboard'!B6:J6",
    "coord": "'Fully Ready Dashboard'!B9:E16",
    "mgr": "'Fully Ready Dashboard'!I9:L40",
}


def read_from_api():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = os.getenv("GOOGLE_CREDENTIALS_JSON")
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    if info:
        creds = service_account.Credentials.from_service_account_info(json.loads(info), scopes=scopes)
    else:
        path = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
        creds = service_account.Credentials.from_service_account_file(path, scopes=scopes)
    api = build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()
    res = api.values().batchGet(spreadsheetId=SPREADSHEET_ID, ranges=list(RANGES.values())).execute()
    return {k: vr.get("values", []) for k, vr in zip(RANGES, res["valueRanges"])}


def load(snapshot=None, tries=6, wait=60):
    """The sheet's linked data sometimes reloads for a minute and shows 0 everywhere.
    Never mail zeros: retry, and give up (exit 2) if it does not come back."""
    for attempt in range(1, tries + 1):
        raw = json.load(open(snapshot, encoding="utf-8")) if snapshot else read_from_api()
        data_rows = [r for r in raw["data"][1:] if r and r[0].strip()]
        total = num((raw["kpi"][0] if raw["kpi"] else ["0"])[0])
        if data_rows and total > 0:
            return raw
        if snapshot:
            break
        print(f"Sheet still loading (attempt {attempt}/{tries}) – waiting {wait}s…")
        time.sleep(wait)
    print("ERROR: dashboard shows no data – no mail sent.")
    sys.exit(2)


def build_model(raw):
    data = {}
    for r in raw["data"][1:]:
        r = r + [""] * (9 - len(r))
        if r[0].strip():
            data[r[0].strip()] = {"opf": r[0].strip(), "cust": r[1].strip(), "sp": r[2].strip(),
                                  "status": r[3].strip(), "qty": num(r[4]), "val": num(r[6]),
                                  "coord": r[8].strip()}
    log = []
    for r in raw["log"][1:]:
        r = r + [""] * (7 - len(r))
        if r[0].strip() and r[1].strip():
            log.append({"tab": r[0].strip(), "opf": r[1].strip(),
                        "fu": parse_date(r[2]), "rd": parse_date(r[3])})
    coord_rows = [r + [""] * (4 - len(r)) for r in raw["coord"][1:] if r and r[0].strip()]
    mgr_rows = [r + [""] * (4 - len(r)) for r in raw["mgr"][1:] if r and r[0].strip()]
    k = (raw["kpi"][0] if raw["kpi"] else []) + [""] * 9
    kpi = {"opfs": k[0], "pieces": k[2], "value": k[4], "salespersons": k[8]}
    return data, log, coord_rows, mgr_rows, kpi


# ── Mail bodies ──────────────────────────────────────────────────────────────
def summary_block(coord, coord_rows):
    row = next((r for r in coord_rows if r[0].strip().lower() == coord.lower()), None)
    if not row:
        return ""
    head = "".join(f"<th {TH_BIG}>{h}</th>" for h in
                   ["Ops Coordinator", "Fully Ready OPFs", "Pieces Ready", "Value Ready (₹)"])
    cells = "".join(f"<td {TD_BIG}>{esc(c)}</td>" for c in row[:4])
    return ('<p style="font-weight:bold;font-size:15px;margin:14px 0 4px 0">Your Fully Ready OPF Summary</p>'
            '<table style="border-collapse:collapse;font-family:Arial,sans-serif;margin:0 0 14px 0">'
            f"<tr>{head}</tr><tr>{cells}</tr></table>")


def reminder_html(coord, rows, pending_only, day_txt, link, coord_rows):
    first = coord.split()[0]
    out = ['<div style="font-family:Arial,sans-serif;font-size:14px;color:#222">',
           f"<p>Hi {esc(first)},</p>", summary_block(coord, coord_rows)]
    if rows:
        intro = (f"These fully ready OPFs were due for follow-up today ({day_txt}) and no remark has been entered yet:"
                 if pending_only else f"These fully ready OPFs are due for follow-up today ({day_txt}):")
        out.append(f"<p>{intro}</p>")
        out.append('<table style="border-collapse:collapse;font-family:Arial,sans-serif;margin:10px 0"><tr>'
                   + "".join(f"<th {TH}>{h}</th>" for h in ["S.No", "Sales Person", "Customer", "Ready Qty", "Order Value"])
                   + "</tr>")
        tq = tv = 0
        for i, r in enumerate(rows, 1):
            tq += r["qty"]; tv += r["val"]
            out.append(f"<tr><td {TDR}>{i}</td><td {TD}>{esc(r['sp'])}</td><td {TD}>{esc(r['cust'])}</td>"
                       f"<td {TDR}>{int(r['qty'])}</td><td {TDR}>{inr(r['val'])}</td></tr>")
        out.append(f"<tr><td {TD}></td><td {TD}><b>Total</b></td><td {TD}></td>"
                   f"<td {TDR}><b>{int(tq)}</b></td><td {TDR}><b>{inr(tv)}</b></td></tr></table>")
    else:
        out.append(f"<p>No follow-ups are due today ({day_txt}).</p>")
    out.append("<p>After following up, update the <b>Remark date</b>, <b>Remarks</b> and the "
               f'<b>Next Follow up Date</b> in your tab: <a href="{link}">open your tab</a>.</p>'
               '<p style="color:#888;font-size:12px">Automatic reminder from the Team-wise OPF Readiness Dashboard.</p></div>')
    return "".join(out)


def weekly_html(day_txt, kpi, coord_rows, mgr_rows):
    link = f"{SHEET_URL}#gid={DASHBOARD_GID}"
    tile = ('<td style="padding:10px 16px;border:1px solid #d9d9d9;text-align:center">'
            '<div style="font-size:11px;color:#555">{}</div>'
            '<div style="font-size:20px;font-weight:bold;color:#1F3864">{}</div></td>')
    tiles = "".join(tile.format(a, esc(b)) for a, b in [
        ("FULLY READY OPFs", kpi["opfs"]), ("PIECES READY", kpi["pieces"]),
        ("VALUE READY TO DISPATCH", kpi["value"]), ("SALESPERSONS WITH READY OPFs", kpi["salespersons"])])
    hd = 'style="background:#1F3864;color:#fff;padding:6px 10px;border:1px solid #c9c9c9;font-size:13px;text-align:left"'

    def table(header, rows, ncol):
        h = "<tr>" + "".join(f"<td {hd}>{x}</td>" for x in header) + "</tr>"
        b = ""
        for r in rows:
            st = TD_TOT if r[0].strip().lower() == "total" else TD
            b += "<tr>" + "".join(f"<td {st}>{esc(c)}</td>" for c in r[:ncol]) + "</tr>"
        return f"<table {TBL}>{h}{b}</table>"

    coord_tbl = table(["Ops Coordinator", "Fully Ready OPFs", "Pieces Ready", "Value Ready (₹)"],
                      [r for r in coord_rows if r[0].strip().lower() != "no ops coordinator"], 4)
    mgr_tbl = table(["Team Manager", "Fully Ready OPFs", "Pieces Ready"], mgr_rows, 3)
    return ('<div style="font-family:Arial,sans-serif;color:#222"><p>Dear Sir,</p>'
            f"<p>Please find below the weekly summary of the Team-wise Fully Ready OPF Dashboard as on {day_txt}.</p>"
            f"<table {TBL}><tr>{tiles}</tr></table>"
            f'<p style="font-weight:bold;margin:0">By Ops Coordinator</p>{coord_tbl}'
            f'<p style="font-weight:bold;margin:0">By Team Manager</p>{mgr_tbl}'
            f'<p><a href="{link}" style="background:#1F3864;color:#fff;padding:8px 14px;text-decoration:none;border-radius:4px">Open the live dashboard</a></p>'
            f'<p style="font-size:12px;color:#666">Link: {link}</p><p>Regards,<br>Shwetabh</p></div>')


def html_to_text(h):
    t = re.sub(r"<(br|/p|/tr|/table)[^>]*>", "\n", h)
    t = re.sub(r"</t[dh]>", " ", t)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(re.sub(r"\n\s*\n+", "\n\n", t)).strip()


# ── Building the mail list ───────────────────────────────────────────────────
def plan_reminders(model, today, pending_only):
    data, log, coord_rows, _, _ = model
    day_txt = fmt_day(today)
    mails = []
    for tab, (email, mail_on, gid) in TABS.items():
        if not mail_on:
            continue
        coord = tab.replace("Fully Ready - ", "")
        seen, rows = set(), []
        for e in log:
            if e["tab"] != tab or e["fu"] != today or e["opf"] in seen:
                continue
            if pending_only and e["rd"] == today:
                continue                                   # remark already entered today
            d = data.get(e["opf"])
            if not d or d["status"] != "Fully Ready" or d["coord"] != coord:
                continue                                   # dispatched / no longer fully ready / moved
            seen.add(e["opf"]); rows.append(d)
        rows.sort(key=lambda r: (r["sp"] + r["cust"]).lower())
        if pending_only and not rows:
            continue                                       # 4 PM mail only when something is pending
        n = len(rows)
        if pending_only:
            subject = f"Reminder: follow-ups still pending today – {day_txt} ({n} OPF{'' if n == 1 else 's'})"
        else:
            subject = f"Daily fully ready OPF status – {day_txt} ({n} follow-up{'' if n == 1 else 's'} due today)"
        link = f"{SHEET_URL}#gid={gid}"
        mails.append({"key": coord, "to": [email], "cc": MAIL_CC, "from_name": REMINDER_FROM_NAME,
                      "subject": subject,
                      "html": reminder_html(coord, rows, pending_only, day_txt, link, coord_rows)})
    return mails


def plan_weekly(model, today):
    _, _, coord_rows, mgr_rows, kpi = model
    day_txt = fmt_day(today)
    return [{"key": "Weekly", "to": WEEKLY_TO, "cc": [], "from_name": WEEKLY_FROM_NAME,
             "subject": f"Weekly Fully Ready OPF Dashboard – {day_txt}",
             "html": weekly_html(day_txt, kpi, coord_rows, mgr_rows)}]


# ── Sending ──────────────────────────────────────────────────────────────────
def send_all(mails, test_to=None):
    sender = os.getenv("EMAIL_ADDRESS", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    if not sender or not password:
        print("ERROR: EMAIL_ADDRESS / EMAIL_PASSWORD not set."); sys.exit(1)
    server = smtplib.SMTP(os.getenv("SMTP_SERVER", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587")))
    server.starttls(); server.login(sender, password)
    try:
        for m in mails:
            to = [test_to] if test_to else m["to"]
            cc = [] if test_to else m["cc"]
            msg = MIMEMultipart("alternative")
            msg["From"] = formataddr((m["from_name"], sender))
            msg["To"] = ", ".join(to)
            if cc:
                msg["Cc"] = ", ".join(cc)
            msg["Subject"] = (f"[TEST – {m['key']}] " if test_to else "") + m["subject"]
            msg.attach(MIMEText(html_to_text(m["html"]), "plain", "utf-8"))
            msg.attach(MIMEText(m["html"], "html", "utf-8"))
            server.sendmail(sender, to + cc, msg.as_string())
            print(f"Sent: {msg['Subject']}  ->  {', '.join(to + cc)}")
    finally:
        server.quit()


def write_drafts(mails, mode, today, out="drafts"):
    Path(out).mkdir(exist_ok=True)
    for m in mails:
        name = f"{today.isoformat()}_{mode}_{m['key'].replace(' ', '_')}.html"
        head = (f'<div style="font-family:Arial;font-size:13px;color:#444;border-bottom:1px solid #ddd;padding:8px 0;margin-bottom:12px">'
                f"<b>From:</b> {esc(m['from_name'])} &lt;{esc(os.getenv('EMAIL_ADDRESS', 'shwetabh@reclinersindia.com'))}&gt;<br>"
                f"<b>To:</b> {esc(', '.join(m['to']))}<br>"
                + (f"<b>Cc:</b> {esc(', '.join(m['cc']))}<br>" if m["cc"] else "")
                + f"<b>Subject:</b> {esc(m['subject'])}</div>")
        Path(out, name).write_text(f'<!doctype html><meta charset="utf-8"><title>{esc(m["subject"])}</title>'
                                   f'<body style="max-width:820px;margin:20px auto">{head}{m["html"]}</body>',
                                   encoding="utf-8")
        print(f"Draft: {out}/{name}   [{m['subject']}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["morning", "afternoon", "weekly"])
    ap.add_argument("--draft", action="store_true", help="write HTML drafts, send nothing")
    ap.add_argument("--to-me", action="store_true", help="send everything to TEST_TO only")
    ap.add_argument("--date", help="pretend today is YYYY-MM-DD (drafts/testing)")
    ap.add_argument("--snapshot", help="read sheet data from a JSON file instead of the API")
    a = ap.parse_args()

    today = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(IST).date()
    model = build_model(load(a.snapshot))
    mails = plan_weekly(model, today) if a.mode == "weekly" else plan_reminders(model, today, a.mode == "afternoon")
    if not mails:
        print("Nothing to send."); return
    if a.draft:
        write_drafts(mails, a.mode, today)
    else:
        send_all(mails, test_to=(os.getenv("TEST_TO", "shwetabh@reclinersindia.com") if a.to_me else None))


if __name__ == "__main__":
    main()
