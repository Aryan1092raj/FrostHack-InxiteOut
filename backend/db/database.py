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
            open_rate REAL DEFAULT 0.0,
            click_rate REAL DEFAULT 0.0,
            total_sent INTEGER DEFAULT 0,
            raw_report TEXT,            -- full JSON from CampaignX API
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
        )
    """)

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
                click_rate: float, total_sent: int, raw_report: dict):
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO reports
        (campaign_id, external_campaign_id, open_rate, click_rate,
         total_sent, raw_report, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (campaign_id, external_id, open_rate, click_rate,
          total_sent, json.dumps(raw_report), now))
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
