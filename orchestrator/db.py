import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.config import DB_PATH

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS issues (
    issue_number INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    agent_id TEXT,
    pr_number INTEGER,
    attempts INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    issue_number INTEGER,
    pr_number INTEGER,
    agent_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    worktree_path TEXT,
    branch_name TEXT,
    pid INTEGER,
    turns_used INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    error_message TEXT,
    FOREIGN KEY (issue_number) REFERENCES issues(issue_number)
);

CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    event_type TEXT,
    event_data TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE TABLE IF NOT EXISTS pr_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_number INTEGER NOT NULL,
    iteration INTEGER NOT NULL,
    comments_count INTEGER,
    comments_json TEXT,
    agent_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);
"""


def _get_connection() -> sqlite3.Connection:
    """Get a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), timeout=30)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """Initialize the database schema."""
    conn = _get_connection()
    conn.executescript(SCHEMA)
    # Migrate: add columns if missing (for existing DBs)
    _migrate_add_column(conn, "agents", "pid", "INTEGER")
    _migrate_add_column(conn, "agents", "session_id", "TEXT")
    _migrate_add_column(conn, "agents", "resume_count", "INTEGER DEFAULT 0")
    _migrate_add_column(conn, "agents", "rate_limited_at", "TIMESTAMP")
    _migrate_add_column(conn, "pr_reviews", "comments_json", "TEXT")
    conn.commit()


def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, col_type: str):
    """Add a column to a table if it doesn't exist."""
    try:
        conn.execute(f"SELECT {column} FROM {table} LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()


def _now() -> str:
    return datetime.utcnow().isoformat()


# === Issue CRUD ===


def upsert_issue(issue_number: int, title: str, status: str = "pending"):
    conn = _get_connection()
    conn.execute(
        """INSERT INTO issues (issue_number, title, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(issue_number) DO UPDATE SET
             title=excluded.title, updated_at=excluded.updated_at""",
        (issue_number, title, status, _now(), _now()),
    )
    conn.commit()


def get_issue(issue_number: int) -> dict | None:
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM issues WHERE issue_number = ?", (issue_number,)
    ).fetchone()
    return dict(row) if row else None


def get_issues_by_status(status: str) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM issues WHERE status = ? ORDER BY issue_number", (status,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_issues() -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM issues ORDER BY issue_number"
    ).fetchall()
    return [dict(r) for r in rows]


def update_issue(issue_number: int, **kwargs):
    conn = _get_connection()
    kwargs["updated_at"] = _now()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [issue_number]
    conn.execute(f"UPDATE issues SET {sets} WHERE issue_number = ?", vals)
    conn.commit()


# === Agent CRUD ===


def create_agent(
    agent_id: str,
    issue_number: int,
    agent_type: str,
    worktree_path: str,
    branch_name: str,
    pr_number: int | None = None,
    pid: int | None = None,
):
    conn = _get_connection()
    conn.execute(
        """INSERT INTO agents (agent_id, issue_number, pr_number, agent_type, status, worktree_path, branch_name, pid, started_at)
           VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?)""",
        (agent_id, issue_number, pr_number, agent_type, worktree_path, branch_name, pid, _now()),
    )
    conn.commit()


def get_agent(agent_id: str) -> dict | None:
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    return dict(row) if row else None


def get_running_agents() -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM agents WHERE status = 'running' ORDER BY started_at"
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_agents() -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM agents ORDER BY started_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_rate_limited_agents() -> list[dict]:
    """Get all agents currently in rate_limited status."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM agents WHERE status = 'rate_limited' ORDER BY rate_limited_at"
    ).fetchall()
    return [dict(r) for r in rows]


def update_agent(agent_id: str, **kwargs):
    conn = _get_connection()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [agent_id]
    conn.execute(f"UPDATE agents SET {sets} WHERE agent_id = ?", vals)
    conn.commit()


def finish_agent(agent_id: str, status: str, error_message: str | None = None):
    update_agent(
        agent_id,
        status=status,
        finished_at=_now(),
        error_message=error_message,
    )


# === Agent Events ===


def insert_event(agent_id: str, event_type: str, event_data: str):
    conn = _get_connection()
    conn.execute(
        """INSERT INTO agent_events (agent_id, event_type, event_data, timestamp)
           VALUES (?, ?, ?, ?)""",
        (agent_id, event_type, event_data, _now()),
    )
    conn.commit()


def get_agent_events(agent_id: str, since_id: int = 0, limit: int = 100) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        """SELECT * FROM agent_events
           WHERE agent_id = ? AND id > ?
           ORDER BY id
           LIMIT ?""",
        (agent_id, since_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_agent_turn_count(agent_id: str) -> int:
    """Count assistant events (turns) for an agent from the events table."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM agent_events WHERE agent_id = ? AND event_type = 'assistant'",
        (agent_id,),
    ).fetchone()
    return row[0] if row else 0


# === PR Reviews ===


def create_pr_review(pr_number: int, iteration: int, comments_count: int, comments_json: str | None = None) -> int:
    conn = _get_connection()
    cursor = conn.execute(
        """INSERT INTO pr_reviews (pr_number, iteration, comments_count, comments_json, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (pr_number, iteration, comments_count, comments_json, _now()),
    )
    conn.commit()
    return cursor.lastrowid


def get_pr_reviews(pr_number: int) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM pr_reviews WHERE pr_number = ? ORDER BY iteration",
        (pr_number,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest_pr_review(pr_number: int) -> dict | None:
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM pr_reviews WHERE pr_number = ? ORDER BY iteration DESC LIMIT 1",
        (pr_number,),
    ).fetchone()
    return dict(row) if row else None


def update_pr_review(review_id: int, **kwargs):
    conn = _get_connection()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [review_id]
    conn.execute(f"UPDATE pr_reviews SET {sets} WHERE id = ?", vals)
    conn.commit()


def get_all_pr_reviews() -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM pr_reviews ORDER BY pr_number, iteration"
    ).fetchall()
    return [dict(r) for r in rows]


# === Metrics ===


def get_metrics() -> dict:
    conn = _get_connection()

    active_agents = conn.execute(
        "SELECT COUNT(*) FROM agents WHERE status = 'running'"
    ).fetchone()[0]

    total_issues = conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]

    resolved = conn.execute(
        "SELECT COUNT(*) FROM issues WHERE status = 'resolved'"
    ).fetchone()[0]

    pending = conn.execute(
        "SELECT COUNT(*) FROM issues WHERE status = 'pending'"
    ).fetchone()[0]

    in_progress = conn.execute(
        "SELECT COUNT(*) FROM issues WHERE status = 'in_progress'"
    ).fetchone()[0]

    needs_human = conn.execute(
        "SELECT COUNT(*) FROM issues WHERE status = 'needs_human'"
    ).fetchone()[0]

    pr_created = conn.execute(
        "SELECT COUNT(*) FROM issues WHERE status = 'pr_created'"
    ).fetchone()[0]

    avg_turns = conn.execute(
        "SELECT AVG(turns_used) FROM agents WHERE status = 'completed'"
    ).fetchone()[0]

    rate_limited = conn.execute(
        "SELECT COUNT(*) FROM agents WHERE status = 'rate_limited'"
    ).fetchone()[0]

    return {
        "active_agents": active_agents,
        "total_issues": total_issues,
        "resolved": resolved,
        "pending": pending,
        "in_progress": in_progress,
        "needs_human": needs_human,
        "pr_created": pr_created,
        "avg_turns": round(avg_turns, 1) if avg_turns else 0,
        "rate_limited": rate_limited,
    }
