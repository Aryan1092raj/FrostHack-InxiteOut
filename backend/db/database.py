import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# ─── DB Setup ────────────────────────────────────────────────────────────────

DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "campaignx.db")))

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets us access columns by name
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # ── Campaigns Table ──────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            brief TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planning',
            strategy TEXT,         -- JSON string
            emails TEXT,           -- JSON string
            metrics TEXT,          -- JSON string
            iteration INTEGER DEFAULT 1,
            max_iterations INTEGER DEFAULT 3,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # ── Agent Logs Table (bonus points) ─────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            thought TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        )
    """)

    # ── Campaign Reports Table ───────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id TEXT NOT NULL,
            external_campaign_id TEXT,  -- ID returned by CampaignX API
            iteration_number INTEGER DEFAULT 1,
            open_rate REAL DEFAULT 0.0,
            click_rate REAL DEFAULT 0.0,
            total_sent INTEGER DEFAULT 0,
            opens INTEGER DEFAULT 0,
            clicks INTEGER DEFAULT 0,
            raw_report TEXT,            -- full JSON from CampaignX API
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        )
    """)

    # Migration: add columns if they don't exist (idempotent)
    for col in ["opens INTEGER DEFAULT 0", "clicks INTEGER DEFAULT 0",
                "iteration_number INTEGER DEFAULT 1"]:
        col_name = col.split()[0]
        try:
            cursor.execute(f"ALTER TABLE reports ADD COLUMN {col}")
        except Exception:
            pass  # column already exists

    # ── Rate Limit Tracker ───────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_limit_tracker (
            endpoint TEXT NOT NULL,
            call_date TEXT NOT NULL,
            call_count INTEGER DEFAULT 0,
            PRIMARY KEY (endpoint, call_date)
        )
    """)

    # ── Cohort Cache ─────────────────────────────────────────────────────────
    # Never hit the cohort API more than once per day
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cohort_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,         -- full JSON array of customers
            fetched_at TEXT NOT NULL
        )
    """)

    # ── Per-Customer Iteration Events ────────────────────────────────────────
    # Tracks sent/open/click at customer granularity per iteration.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_iteration_events (
            campaign_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            iteration_number INTEGER NOT NULL,
            emailed INTEGER DEFAULT 1,
            opened INTEGER DEFAULT 0,
            clicked INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (campaign_id, customer_id, iteration_number),
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        )
    """)

    conn.commit()
    conn.close()
    print("✅ Database initialized")


# ─── Campaign CRUD ────────────────────────────────────────────────────────────

def create_campaign(campaign_id: str, brief: str) -> Dict[str, Any]:
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO campaigns (id, brief, status, created_at, updated_at)
        VALUES (?, ?, 'planning', ?, ?)
    """, (campaign_id, brief, now, now))
    conn.commit()
    conn.close()
    
    campaign = get_campaign(campaign_id)
    if campaign is None:
        raise RuntimeError("Failed to retrieve created campaign")
    return campaign


def get_campaign(campaign_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _parse_campaign_row(row)


def get_all_campaigns() -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM campaigns ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [_parse_campaign_row(r) for r in rows]


def update_campaign_status(campaign_id: str, status: str):
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        UPDATE campaigns SET status = ?, updated_at = ?
        WHERE id = ?
    """, (status, now, campaign_id))
    conn.commit()
    conn.close()


def update_campaign_strategy(campaign_id: str, strategy: dict):
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        UPDATE campaigns SET strategy = ?, updated_at = ?
        WHERE id = ?
    """, (json.dumps(strategy), now, campaign_id))
    conn.commit()
    conn.close()


def update_campaign_emails(campaign_id: str, emails: list):
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        UPDATE campaigns SET emails = ?, updated_at = ?
        WHERE id = ?
    """, (json.dumps(emails), now, campaign_id))
    conn.commit()
    conn.close()


def update_campaign_metrics(campaign_id: str, metrics: dict):
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        UPDATE campaigns SET metrics = ?, updated_at = ?
        WHERE id = ?
    """, (json.dumps(metrics), now, campaign_id))
    conn.commit()
    conn.close()


def increment_campaign_iteration(campaign_id: str):
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        UPDATE campaigns SET iteration = iteration + 1, updated_at = ?
        WHERE id = ?
    """, (now, campaign_id))
    conn.commit()
    conn.close()


def _parse_campaign_row(row) -> Dict[str, Any]:
    d: Dict[str, Any] = dict(row)
    for field in ["strategy", "emails", "metrics"]:
        if d.get(field):
            d[field] = json.loads(d[field])
        else:
            d[field] = None
    return d


# ─── Agent Logs CRUD ──────────────────────────────────────────────────────────

def save_agent_log(campaign_id: str, agent: str, thought: str):
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO agent_logs (campaign_id, agent, thought, timestamp)
        VALUES (?, ?, ?, ?)
    """, (campaign_id, agent, thought, now))
    conn.commit()
    conn.close()


def get_agent_logs(campaign_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM agent_logs WHERE campaign_id = ?
        ORDER BY timestamp ASC
    """, (campaign_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Reports CRUD ─────────────────────────────────────────────────────────────

def save_report(campaign_id: str, external_id: str, open_rate: float,
                click_rate: float, total_sent: int, raw_report: dict,
                iteration_number: int = 1):
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    computed = raw_report.get("computed_metrics", {})
    opens = computed.get("opens", round((open_rate or 0) * (total_sent or 0)))
    clicks = computed.get("clicks", round((click_rate or 0) * (total_sent or 0)))
    conn.execute("""
        INSERT INTO reports
        (campaign_id, external_campaign_id, iteration_number, open_rate, click_rate,
         total_sent, opens, clicks, raw_report, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (campaign_id, external_id, iteration_number, open_rate, click_rate,
          total_sent, opens, clicks, json.dumps(raw_report), now))
    conn.commit()
    conn.close()


def get_report(campaign_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("""
        SELECT * FROM reports WHERE campaign_id = ?
        ORDER BY fetched_at DESC LIMIT 1
    """, (campaign_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d: Dict[str, Any] = dict(row)
    d["raw_report"] = json.loads(d["raw_report"]) if d["raw_report"] else {}
    return d


def get_reports_by_external_ids(external_ids: List[str]) -> List[Dict[str, Any]]:
    """Fetch raw per-customer report rows for a list of external campaign IDs."""
    if not external_ids:
        return []
    conn = get_connection()
    placeholders = ",".join("?" * len(external_ids))
    rows = conn.execute(
        f"SELECT external_campaign_id, raw_report FROM reports "
        f"WHERE external_campaign_id IN ({placeholders})",
        external_ids
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d: Dict[str, Any] = dict(row)
        d["raw_report"] = json.loads(d["raw_report"]) if d["raw_report"] else {}
        result.append(d)
    return result

def get_all_reports_for_campaign(campaign_id: str) -> List[Dict[str, Any]]:
    """Fetch ALL saved reports for a campaign across all iterations.
    Used by monitor to compute cumulative open/click rates."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT external_campaign_id, open_rate, click_rate,
                  total_sent, opens, clicks
           FROM reports
           WHERE campaign_id = ?
           ORDER BY fetched_at ASC""",
        (campaign_id,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ─── Rate Limit Tracker ───────────────────────────────────────────────────────

def check_and_increment_rate_limit(endpoint: str, max_calls: int = 100) -> bool:
    """Returns True if call is allowed, False if rate limit exceeded."""
    conn = get_connection()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    row = conn.execute("""
        SELECT call_count FROM rate_limit_tracker
        WHERE endpoint = ? AND call_date = ?
    """, (endpoint, today)).fetchone()

    if row is None:
        conn.execute("""
            INSERT INTO rate_limit_tracker (endpoint, call_date, call_count)
            VALUES (?, ?, 1)
        """, (endpoint, today))
        conn.commit()
        conn.close()
        return True

    if row["call_count"] >= max_calls:
        conn.close()
        return False

    conn.execute("""
        UPDATE rate_limit_tracker SET call_count = call_count + 1
        WHERE endpoint = ? AND call_date = ?
    """, (endpoint, today))
    conn.commit()
    conn.close()
    return True


def get_rate_limit_status() -> dict:
    conn = get_connection()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT endpoint, call_count FROM rate_limit_tracker
        WHERE call_date = ?
    """, (today,)).fetchall()
    conn.close()
    return {row["endpoint"]: row["call_count"] for row in rows}


# ─── Cohort Cache ─────────────────────────────────────────────────────────────

def get_cached_cohort() -> list | None:
    """Returns cached cohort if fetched today, else None."""
    conn = get_connection()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    row = conn.execute("""
        SELECT data, fetched_at FROM cohort_cache
        WHERE date(fetched_at) = ?
        ORDER BY fetched_at DESC LIMIT 1
    """, (today,)).fetchone()
    conn.close()
    if not row:
        return None
    return json.loads(row["data"])


def save_cohort_cache(data: list):
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO cohort_cache (data, fetched_at)
        VALUES (?, ?)
    """, (json.dumps(data), now))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# PATCH for backend/db/database.py
# Add this function right after save_cohort_cache()
# ─────────────────────────────────────────────────────────────────────────────

def clear_cohort_cache():
    """Delete ALL rows from cohort_cache so the next call fetches fresh from API.
    Call this once after the preliminary round reset (new 1000-customer cohort)."""
    conn = get_connection()
    conn.execute("DELETE FROM cohort_cache")
    conn.commit()
    conn.close()
    print("✅ Cohort cache cleared — next fetch will hit the live API")


# ─── Per-Customer Retarget Tracking ──────────────────────────────────────────

def record_customers_emailed(campaign_id: str, customer_ids: List[str],
                             iteration_number: int):
    """Idempotently mark customers as emailed in a campaign iteration."""
    if not customer_ids:
        return
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    rows = [
        (campaign_id, cid, iteration_number, 1, 0, 0, now)
        for cid in customer_ids if cid
    ]
    conn.executemany("""
        INSERT INTO customer_iteration_events
        (campaign_id, customer_id, iteration_number, emailed, opened, clicked, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id, customer_id, iteration_number)
        DO UPDATE SET
            emailed = MAX(customer_iteration_events.emailed, excluded.emailed),
            updated_at = excluded.updated_at
    """, rows)
    conn.commit()
    conn.close()


def record_customer_report_events(campaign_id: str, iteration_number: int,
                                  customer_rows: List[Dict[str, Any]]):
    """Idempotently upsert EO/EC outcomes for customers in a campaign iteration."""
    if not customer_rows:
        return

    merged: Dict[str, Dict[str, int]] = {}
    for row in customer_rows:
        cid = str(row.get("customer_id", "")).strip()
        if not cid:
            continue
        opened = 1 if str(row.get("EO", "N")).upper() == "Y" else 0
        clicked = 1 if str(row.get("EC", "N")).upper() == "Y" else 0
        prev = merged.get(cid, {"opened": 0, "clicked": 0})
        merged[cid] = {
            "opened": max(prev["opened"], opened),
            "clicked": max(prev["clicked"], clicked),
        }

    if not merged:
        return

    conn = get_connection()
    now = datetime.utcnow().isoformat()
    rows = [
        (campaign_id, cid, iteration_number, 1, vals["opened"], vals["clicked"], now)
        for cid, vals in merged.items()
    ]
    conn.executemany("""
        INSERT INTO customer_iteration_events
        (campaign_id, customer_id, iteration_number, emailed, opened, clicked, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id, customer_id, iteration_number)
        DO UPDATE SET
            emailed = MAX(customer_iteration_events.emailed, excluded.emailed),
            opened = MAX(customer_iteration_events.opened, excluded.opened),
            clicked = MAX(customer_iteration_events.clicked, excluded.clicked),
            updated_at = excluded.updated_at
    """, rows)
    conn.commit()
    conn.close()


def get_customer_lifecycle_stats(campaign_id: str) -> Dict[str, Dict[str, int]]:
    """Return per-customer cumulative sent/open/click counts for one campaign."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT customer_id,
               SUM(emailed) AS sent_count,
               SUM(opened) AS opened_count,
               SUM(clicked) AS clicked_count
        FROM customer_iteration_events
        WHERE campaign_id = ?
        GROUP BY customer_id
    """, (campaign_id,)).fetchall()
    conn.close()

    return {
        row["customer_id"]: {
            "sent_count": int(row["sent_count"] or 0),
            "opened_count": int(row["opened_count"] or 0),
            "clicked_count": int(row["clicked_count"] or 0),
        }
        for row in rows
    }