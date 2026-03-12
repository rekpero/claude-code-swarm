import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.config import DB_PATH

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    github_repo TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    local_path TEXT NOT NULL,
    base_branch TEXT DEFAULT 'main',
    status TEXT DEFAULT 'active',
    is_monorepo INTEGER DEFAULT 0,
    structure_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workspace_env (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    env_key TEXT NOT NULL,
    env_value TEXT NOT NULL,
    env_file TEXT DEFAULT '.env',
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    UNIQUE(workspace_id, env_key, env_file)
);

CREATE TABLE IF NOT EXISTS workspace_env_sync (
    workspace_id TEXT NOT NULL,
    env_file TEXT NOT NULL,
    disk_mtime REAL NOT NULL,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, env_file),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    agent_id TEXT,
    pr_number INTEGER,
    attempts INTEGER DEFAULT 0,
    workspace_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    UNIQUE(issue_number, workspace_id)
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
    workspace_id TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    error_message TEXT
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
    workspace_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS planning_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    title TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    issue_number INTEGER,
    issue_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS planning_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES planning_sessions(id)
);
"""


def _get_connection() -> sqlite3.Connection:
    """Get a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), timeout=30)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def init_db():
    """Initialize the database schema."""
    conn = _get_connection()

    # Migrate old issues table schema before running CREATE TABLE IF NOT EXISTS
    _migrate_issues_table(conn)

    conn.executescript(SCHEMA)
    # Migrate: add columns if missing (for existing DBs)
    _migrate_add_column(conn, "agents", "pid", "INTEGER")
    _migrate_add_column(conn, "agents", "session_id", "TEXT")
    _migrate_add_column(conn, "agents", "resume_count", "INTEGER DEFAULT 0")
    _migrate_add_column(conn, "agents", "rate_limited_at", "TIMESTAMP")
    _migrate_add_column(conn, "pr_reviews", "comments_json", "TEXT")
    # Multi-workspace migration
    _migrate_add_column(conn, "issues", "workspace_id", "TEXT")
    _migrate_add_column(conn, "agents", "workspace_id", "TEXT")
    _migrate_add_column(conn, "pr_reviews", "workspace_id", "TEXT")
    conn.commit()


def _migrate_issues_table(conn: sqlite3.Connection):
    """Migrate old issues table from issue_number-as-PK to new schema with id PK and composite unique."""
    try:
        # Check if the issues table exists
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='issues'"
        ).fetchone()
        if not row:
            return  # Table doesn't exist yet, CREATE TABLE will handle it

        # Check if the table has the old schema (issue_number as PK, no 'id' column)
        columns = conn.execute("PRAGMA table_info(issues)").fetchall()
        col_names = {c[1] for c in columns}

        if "id" in col_names:
            return  # Already migrated to new schema

        # Old schema detected — recreate with new schema
        conn.executescript("""
            ALTER TABLE issues RENAME TO _issues_old;
            CREATE TABLE issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                agent_id TEXT,
                pr_number INTEGER,
                attempts INTEGER DEFAULT 0,
                workspace_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(issue_number, workspace_id)
            );
            INSERT INTO issues (issue_number, title, status, agent_id, pr_number, attempts, created_at, updated_at)
                SELECT issue_number, title, status, agent_id, pr_number, attempts, created_at, updated_at
                FROM _issues_old;
            DROP TABLE _issues_old;
        """)
    except Exception:
        pass  # If anything goes wrong, let CREATE TABLE IF NOT EXISTS handle it


def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, col_type: str):
    """Add a column to a table if it doesn't exist."""
    try:
        conn.execute(f"SELECT {column} FROM {table} LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()


def _now() -> str:
    return datetime.utcnow().isoformat()


# === Workspace CRUD ===


def create_workspace(
    workspace_id: str,
    name: str,
    github_repo: str,
    repo_url: str,
    local_path: str,
    base_branch: str = "main",
    status: str = "cloning",
):
    conn = _get_connection()
    conn.execute(
        """INSERT INTO workspaces (id, name, github_repo, repo_url, local_path, base_branch, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (workspace_id, name, github_repo, repo_url, local_path, base_branch, status, _now(), _now()),
    )
    conn.commit()


def get_workspace(workspace_id: str) -> dict | None:
    conn = _get_connection()
    row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    return dict(row) if row else None


def get_all_workspaces() -> list[dict]:
    conn = _get_connection()
    rows = conn.execute("SELECT * FROM workspaces ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def get_active_workspaces() -> list[dict]:
    conn = _get_connection()
    rows = conn.execute("SELECT * FROM workspaces WHERE status = 'active' ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def update_workspace(workspace_id: str, **kwargs):
    conn = _get_connection()
    kwargs["updated_at"] = _now()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [workspace_id]
    conn.execute(f"UPDATE workspaces SET {sets} WHERE id = ?", vals)
    conn.commit()


def delete_workspace(workspace_id: str):
    conn = _get_connection()
    conn.execute("DELETE FROM workspace_env WHERE workspace_id = ?", (workspace_id,))
    conn.execute("DELETE FROM agent_events WHERE agent_id IN (SELECT agent_id FROM agents WHERE workspace_id = ?)", (workspace_id,))
    conn.execute("DELETE FROM pr_reviews WHERE workspace_id = ?", (workspace_id,))
    conn.execute("DELETE FROM agents WHERE workspace_id = ?", (workspace_id,))
    conn.execute("DELETE FROM issues WHERE workspace_id = ?", (workspace_id,))
    conn.execute("DELETE FROM planning_messages WHERE session_id IN (SELECT id FROM planning_sessions WHERE workspace_id = ?)", (workspace_id,))
    conn.execute("DELETE FROM planning_sessions WHERE workspace_id = ?", (workspace_id,))
    conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
    conn.commit()


# === Workspace Env CRUD ===


def save_workspace_env(workspace_id: str, env_key: str, env_value: str, env_file: str = ".env"):
    conn = _get_connection()
    conn.execute(
        """INSERT INTO workspace_env (workspace_id, env_key, env_value, env_file)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(workspace_id, env_key, env_file) DO UPDATE SET env_value=excluded.env_value""",
        (workspace_id, env_key, env_value, env_file),
    )
    conn.commit()


def save_workspace_env_bulk(workspace_id: str, env_dict: dict[str, str], env_file: str = ".env"):
    conn = _get_connection()
    # Delete existing keys for this env_file so removed keys don't persist
    conn.execute(
        "DELETE FROM workspace_env WHERE workspace_id = ? AND env_file = ?",
        (workspace_id, env_file),
    )
    for key, value in env_dict.items():
        conn.execute(
            """INSERT INTO workspace_env (workspace_id, env_key, env_value, env_file)
               VALUES (?, ?, ?, ?)""",
            (workspace_id, key, value, env_file),
        )
    conn.commit()


def get_workspace_env(workspace_id: str, env_file: str = ".env") -> dict[str, str]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT env_key, env_value FROM workspace_env WHERE workspace_id = ? AND env_file = ?",
        (workspace_id, env_file),
    ).fetchall()
    return {r["env_key"]: r["env_value"] for r in rows}


def get_workspace_env_files(workspace_id: str) -> list[str]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT DISTINCT env_file FROM workspace_env WHERE workspace_id = ? ORDER BY env_file",
        (workspace_id,),
    ).fetchall()
    return [r["env_file"] for r in rows]


def delete_workspace_env(workspace_id: str, env_key: str, env_file: str = ".env"):
    conn = _get_connection()
    conn.execute(
        "DELETE FROM workspace_env WHERE workspace_id = ? AND env_key = ? AND env_file = ?",
        (workspace_id, env_key, env_file),
    )
    conn.commit()


def delete_workspace_env_file(workspace_id: str, env_file: str):
    conn = _get_connection()
    conn.execute(
        "DELETE FROM workspace_env WHERE workspace_id = ? AND env_file = ?",
        (workspace_id, env_file),
    )
    conn.execute(
        "DELETE FROM workspace_env_sync WHERE workspace_id = ? AND env_file = ?",
        (workspace_id, env_file),
    )
    conn.commit()


def get_env_sync_mtime(workspace_id: str, env_file: str) -> float | None:
    """Get the last-synced disk mtime for a workspace env file."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT disk_mtime FROM workspace_env_sync WHERE workspace_id = ? AND env_file = ?",
        (workspace_id, env_file),
    ).fetchone()
    return row["disk_mtime"] if row else None


def set_env_sync_mtime(workspace_id: str, env_file: str, disk_mtime: float):
    """Record the disk mtime after syncing an env file."""
    conn = _get_connection()
    conn.execute(
        """INSERT INTO workspace_env_sync (workspace_id, env_file, disk_mtime, synced_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(workspace_id, env_file) DO UPDATE SET
             disk_mtime=excluded.disk_mtime, synced_at=excluded.synced_at""",
        (workspace_id, env_file, disk_mtime, _now()),
    )
    conn.commit()


# === Issue CRUD ===


def upsert_issue(issue_number: int, title: str, status: str = "pending", workspace_id: str | None = None):
    conn = _get_connection()
    # SQLite treats NULLs as distinct in UNIQUE constraints, so ON CONFLICT
    # won't fire when workspace_id is NULL. Handle this case explicitly.
    if workspace_id is None:
        existing = conn.execute(
            "SELECT id FROM issues WHERE issue_number = ? AND workspace_id IS NULL",
            (issue_number,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE issues SET title = ?, updated_at = ? WHERE id = ?",
                (title, _now(), existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO issues (issue_number, title, status, workspace_id, created_at, updated_at)
                   VALUES (?, ?, ?, NULL, ?, ?)""",
                (issue_number, title, status, _now(), _now()),
            )
    else:
        conn.execute(
            """INSERT INTO issues (issue_number, title, status, workspace_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(issue_number, workspace_id) DO UPDATE SET
                 title=excluded.title, updated_at=excluded.updated_at""",
            (issue_number, title, status, workspace_id, _now(), _now()),
        )
    conn.commit()


def get_issue(issue_number: int, workspace_id: str | None = None) -> dict | None:
    conn = _get_connection()
    if workspace_id:
        row = conn.execute(
            "SELECT * FROM issues WHERE issue_number = ? AND workspace_id = ?", (issue_number, workspace_id)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM issues WHERE issue_number = ?", (issue_number,)
        ).fetchone()
    return dict(row) if row else None


def get_issues_by_status(status: str, workspace_id: str | None = None) -> list[dict]:
    conn = _get_connection()
    if workspace_id:
        rows = conn.execute(
            "SELECT * FROM issues WHERE status = ? AND workspace_id = ? ORDER BY issue_number", (status, workspace_id)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM issues WHERE status = ? ORDER BY issue_number", (status,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_issues(workspace_id: str | None = None) -> list[dict]:
    conn = _get_connection()
    if workspace_id:
        rows = conn.execute(
            "SELECT * FROM issues WHERE workspace_id = ? ORDER BY issue_number", (workspace_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM issues ORDER BY issue_number"
        ).fetchall()
    return [dict(r) for r in rows]


def update_issue(issue_number: int, workspace_id: str | None = None, **kwargs):
    conn = _get_connection()
    kwargs["updated_at"] = _now()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    if workspace_id:
        vals = list(kwargs.values()) + [issue_number, workspace_id]
        conn.execute(f"UPDATE issues SET {sets} WHERE issue_number = ? AND workspace_id = ?", vals)
    else:
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
    workspace_id: str | None = None,
):
    conn = _get_connection()
    conn.execute(
        """INSERT INTO agents (agent_id, issue_number, pr_number, agent_type, status, worktree_path, branch_name, pid, workspace_id, started_at)
           VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)""",
        (agent_id, issue_number, pr_number, agent_type, worktree_path, branch_name, pid, workspace_id, _now()),
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


def get_all_agents(workspace_id: str | None = None, limit: int = 0, offset: int = 0) -> list[dict]:
    conn = _get_connection()
    base = "SELECT * FROM agents"
    params: list = []
    if workspace_id:
        base += " WHERE workspace_id = ?"
        params.append(workspace_id)
    base += " ORDER BY started_at DESC"
    if limit > 0:
        base += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    rows = conn.execute(base, params).fetchall()
    return [dict(r) for r in rows]


def count_agents(workspace_id: str | None = None) -> int:
    conn = _get_connection()
    if workspace_id:
        row = conn.execute("SELECT COUNT(*) FROM agents WHERE workspace_id = ?", (workspace_id,)).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM agents").fetchone()
    return row[0]


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


def create_pr_review(pr_number: int, iteration: int, comments_count: int, comments_json: str | None = None, workspace_id: str | None = None) -> int:
    conn = _get_connection()
    cursor = conn.execute(
        """INSERT INTO pr_reviews (pr_number, iteration, comments_count, comments_json, workspace_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (pr_number, iteration, comments_count, comments_json, workspace_id, _now()),
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


def get_all_pr_reviews(workspace_id: str | None = None) -> list[dict]:
    conn = _get_connection()
    if workspace_id:
        rows = conn.execute(
            "SELECT * FROM pr_reviews WHERE workspace_id = ? ORDER BY pr_number, iteration", (workspace_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM pr_reviews ORDER BY pr_number, iteration"
        ).fetchall()
    return [dict(r) for r in rows]


# === Metrics ===


# === Planning Sessions ===


def create_planning_session(session_id: str, workspace_id: str):
    conn = _get_connection()
    conn.execute(
        """INSERT INTO planning_sessions (id, workspace_id, status, created_at, updated_at)
           VALUES (?, ?, 'active', ?, ?)""",
        (session_id, workspace_id, _now(), _now()),
    )
    conn.commit()


def get_planning_session(session_id: str) -> dict | None:
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM planning_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return dict(row) if row else None


_PLANNING_SESSION_ALLOWED_COLS = {"status", "title", "issue_number", "issue_url", "updated_at"}


def update_planning_session(session_id: str, **kwargs):
    conn = _get_connection()
    kwargs["updated_at"] = _now()
    invalid = set(kwargs) - _PLANNING_SESSION_ALLOWED_COLS
    if invalid:
        raise ValueError(f"Invalid column(s) for update_planning_session: {invalid}")
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [session_id]
    conn.execute(f"UPDATE planning_sessions SET {sets} WHERE id = ?", vals)
    conn.commit()


def add_planning_message(session_id: str, role: str, content: str):
    conn = _get_connection()
    conn.execute(
        """INSERT INTO planning_messages (session_id, role, content, created_at)
           VALUES (?, ?, ?, ?)""",
        (session_id, role, content, _now()),
    )
    conn.commit()


def get_planning_messages(session_id: str) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM planning_messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_planning_sessions(workspace_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        """SELECT ps.*, (SELECT content FROM planning_messages pm
            WHERE pm.session_id = ps.id AND pm.role = 'user'
            ORDER BY pm.id ASC LIMIT 1) AS first_message
           FROM planning_sessions ps
           WHERE ps.workspace_id = ?
           ORDER BY ps.updated_at DESC
           LIMIT ? OFFSET ?""",
        (workspace_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_planning_session(session_id: str):
    conn = _get_connection()
    conn.execute("DELETE FROM planning_messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM planning_sessions WHERE id = ?", (session_id,))
    conn.commit()


# === Metrics ===


def get_metrics(workspace_id: str | None = None) -> dict:
    conn = _get_connection()

    ws_filter_agents = " AND workspace_id = ?" if workspace_id else ""
    ws_filter_issues = " AND workspace_id = ?" if workspace_id else ""
    ws_params: tuple = (workspace_id,) if workspace_id else ()

    active_agents = conn.execute(
        f"SELECT COUNT(*) FROM agents WHERE status = 'running'{ws_filter_agents}", ws_params
    ).fetchone()[0]

    total_issues = conn.execute(
        f"SELECT COUNT(*) FROM issues WHERE 1=1{ws_filter_issues}", ws_params
    ).fetchone()[0]

    resolved = conn.execute(
        f"SELECT COUNT(*) FROM issues WHERE status = 'resolved'{ws_filter_issues}", ws_params
    ).fetchone()[0]

    pending = conn.execute(
        f"SELECT COUNT(*) FROM issues WHERE status = 'pending'{ws_filter_issues}", ws_params
    ).fetchone()[0]

    in_progress = conn.execute(
        f"SELECT COUNT(*) FROM issues WHERE status = 'in_progress'{ws_filter_issues}", ws_params
    ).fetchone()[0]

    needs_human = conn.execute(
        f"SELECT COUNT(*) FROM issues WHERE status = 'needs_human'{ws_filter_issues}", ws_params
    ).fetchone()[0]

    pr_created = conn.execute(
        f"SELECT COUNT(*) FROM issues WHERE status = 'pr_created'{ws_filter_issues}", ws_params
    ).fetchone()[0]

    avg_turns = conn.execute(
        f"SELECT AVG(turns_used) FROM agents WHERE status = 'completed'{ws_filter_agents}", ws_params
    ).fetchone()[0]

    rate_limited = conn.execute(
        f"SELECT COUNT(*) FROM agents WHERE status = 'rate_limited'{ws_filter_agents}", ws_params
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
