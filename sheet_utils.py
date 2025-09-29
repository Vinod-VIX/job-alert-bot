# sheet_utils.py
import logging
import os
import json
from typing import List, Dict, Tuple
from datetime import datetime, date

import gspread
from oauth2client.service_account import ServiceAccountCredentials

import config

log = logging.getLogger("sheet_utils")

# --- Google auth setup ---
SHEET_ID = getattr(config, "SHEET_ID", None)
GOOGLE_SHEET_NAME = getattr(config, "GOOGLE_SHEET_NAME", None)  # fallback
SHEET_NAME = getattr(config, "SHEET_NAME", "Sheet1")

DATE_FORMATS = config.DATE_FORMATS
OUTPUT_DATE_FORMAT = getattr(config, "OUTPUT_DATE_FORMAT", "%d/%m/%Y")

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# 🔑 Load credentials either from environment variable (Render) or local file (Windows/Linux)
try:
    if os.getenv("GOOGLE_CREDENTIALS_JSON"):
        # Render: credentials stored as JSON string in environment variable
        creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
        CREDS = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, SCOPE)
    else:
        # Local: credentials.json file on disk
        GOOGLE_CREDENTIALS_FILE = getattr(config, "GOOGLE_CREDENTIALS_FILE", "E:/credentials.json")
        CREDS = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, SCOPE)
except Exception as e:
    raise RuntimeError(f"❌ Failed to load Google credentials: {e}")

GC = gspread.authorize(CREDS)

# === HEADERS must match your Google Sheet exactly ===
HEADERS = [
    "Job Title",
    "Last Date",
    "Age Limit",
    "Qualification",
    "Experience",
    "Apply Link",
    "Source",   # ✅ Keep Source column
]

def _open_worksheet():
    if SHEET_ID:
        sh = GC.open_by_key(SHEET_ID)
    elif GOOGLE_SHEET_NAME:
        sh = GC.open(GOOGLE_SHEET_NAME)
    else:
        raise RuntimeError("No SHEET_ID or GOOGLE_SHEET_NAME found in config.py")
    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_NAME, rows=200, cols=len(HEADERS))
    return ws

def ensure_headers(ws):
    values = ws.get_all_values()
    if not values or not values[0]:
        ws.update([HEADERS])
        return
    current = [c.strip() for c in values[0]]
    if current != HEADERS:
        ws.delete_rows(1)
        ws.insert_row(HEADERS, 1)

def canonicalize_row(row: Dict[str, object]) -> Dict[str, str]:
    norm = { (k or "").strip(): (v if v is not None else "") for k, v in row.items() }
    out = {}
    for h in HEADERS:
        found_key = None
        for k in norm.keys():
            if k.strip().lower() == h.lower():
                found_key = k
                break
        out[h] = str(norm.get(found_key, "")).strip() if found_key else ""
    return out

def parse_indian_date(s: str):
    if not s:
        return None
    s = str(s).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    try:
        return datetime.strptime(s, "%d %b %Y").date()
    except Exception:
        return None

def build_job_id(title: str, last_date: str) -> str:
    return f"{(title or '').strip().lower()}|{(last_date or '').strip()}"

def read_sheet_rows() -> List[Tuple[int, Dict[str, str]]]:
    ws = _open_worksheet()
    ensure_headers(ws)
    recs = ws.get_all_records()
    rows = []
    for idx, r in enumerate(recs, start=2):
        rows.append((idx, canonicalize_row(r)))
    return rows

def remove_expired_rows(rows_with_idx: List[tuple]) -> List[tuple]:
    ws = _open_worksheet()
    today = date.today()
    expired_indices = []
    for row_idx, row in rows_with_idx:
        ld = parse_indian_date(row.get("Last Date", ""))
        if ld is not None and ld < today:
            expired_indices.append(row_idx)

    if expired_indices:
        expired_indices.sort(reverse=True)
        for ri in expired_indices:
            try:
                ws.delete_rows(ri)
            except Exception as e:
                log.warning("Failed to delete row %s: %s", ri, e)
        log.info("Deleted %d expired rows from sheet.", len(expired_indices))

    recs = ws.get_all_records()
    rows = []
    for idx, r in enumerate(recs, start=2):
        rows.append((idx, canonicalize_row(r)))
    return rows

def append_new_jobs(jobs: List[Dict[str, str]]):
    if not jobs:
        return

    ws = _open_worksheet()
    ensure_headers(ws)

    existing = ws.get_all_records()
    existing_ids = set(
        build_job_id(str(r.get("Job Title","")), str(r.get("Last Date","")))
        for r in existing
    )

    rows_to_add = []
    for j in jobs:
        title = (j.get("title") or "").strip()
        last  = (j.get("last_date") or "").strip()
        jid = build_job_id(title, last)
        if not title or jid in existing_ids:
            continue

        rows_to_add.append([
            title,
            last,
            (j.get("age") or "").strip(),
            (j.get("qualification") or "").strip(),
            (j.get("experience") or "").strip(),
            (j.get("link") or "").strip(),
            (j.get("source") or "").strip(),   # ✅ include source
        ])

    if rows_to_add:
        ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")
        log.info("Appended %d new job rows.", len(rows_to_add))
    else:
        log.info("No new rows to append (after dedupe).")
