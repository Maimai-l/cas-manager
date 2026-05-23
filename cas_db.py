"""
cas_db.py — Local SQLite layer for CAS Manager.

Tables:
  experiences  — CAS activities (ManageBac CAS IDs)
  reflections  — individual reflection entries
  photos       — photos belonging to album reflections
  drafts       — quick-note → AI draft queue
  schedules    — per-experience placeholder schedule config
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from cas_api import Photo, ReflectionEntry
import cas_paths

DEFAULT_DB = cas_paths.DB_PATH

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiences (
    id            INTEGER PRIMARY KEY,   -- ManageBac CAS activity ID
    name          TEXT    NOT NULL DEFAULT '',
    is_completed  INTEGER NOT NULL DEFAULT 0,
    is_deleted    INTEGER NOT NULL DEFAULT 0,  -- 1 if not seen in latest sync of ManageBac
    proposal_text TEXT,                  -- full plain-text proposal
    lo_names      TEXT    NOT NULL DEFAULT '[]',  -- JSON array of LO description strings
    strand        TEXT    NOT NULL DEFAULT '',
    synced_at     TEXT
);

CREATE TABLE IF NOT EXISTS reflections (
    id             INTEGER PRIMARY KEY,   -- ManageBac reflection ID
    cas_id         INTEGER NOT NULL,
    kind           TEXT    NOT NULL,      -- journal | album | file | website | video | unknown
    group_date     TEXT    NOT NULL DEFAULT '',
    body_html      TEXT,
    lo_ids         TEXT    NOT NULL DEFAULT '[]',  -- JSON array of ints
    is_placeholder INTEGER NOT NULL DEFAULT 0,     -- 0 | 1
    synced_at      TEXT,
    FOREIGN KEY (cas_id) REFERENCES experiences(id)
);

CREATE TABLE IF NOT EXISTS photos (
    id            INTEGER PRIMARY KEY,   -- ManageBac photo ID
    reflection_id INTEGER NOT NULL,
    caption       TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL DEFAULT '',
    s3_url        TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY (reflection_id) REFERENCES reflections(id)
);

CREATE TABLE IF NOT EXISTS drafts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cas_id     INTEGER NOT NULL,
    note       TEXT    NOT NULL,          -- raw user input
    ai_result  TEXT,                      -- AI-generated reflection body
    status     TEXT    NOT NULL DEFAULT 'pending',  -- pending | ready | posted
    created_at TEXT    NOT NULL,
    FOREIGN KEY (cas_id) REFERENCES experiences(id)
);

CREATE TABLE IF NOT EXISTS schedules (
    cas_id         INTEGER PRIMARY KEY,
    enabled        INTEGER NOT NULL DEFAULT 1,   -- 0 | 1
    interval_days  INTEGER NOT NULL DEFAULT 1,   -- create placeholder every N days
    lo_ids         TEXT    NOT NULL DEFAULT '[]',-- JSON array, overrides global config
    last_run_date  TEXT                          -- YYYY-MM-DD, last successful run
);

CREATE TABLE IF NOT EXISTS prompts (
    slot       TEXT PRIMARY KEY,                -- e.g. "reflection.system"
    body       TEXT NOT NULL,                   -- user override; absent row = use code default
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reflections_cas ON reflections(cas_id);
CREATE INDEX IF NOT EXISTS idx_photos_ref      ON photos(reflection_id);
CREATE INDEX IF NOT EXISTS idx_drafts_cas      ON drafts(cas_id);
"""


# ── Connection ────────────────────────────────────────────────────────────────

@contextmanager
def open_db(db_path: Path = DEFAULT_DB) -> Iterator[sqlite3.Connection]:
    """Context manager: open DB, yield connection, commit + close."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path = DEFAULT_DB) -> None:
    """Create all tables and indexes (idempotent). Also runs migrations."""
    with open_db(db_path) as conn:
        conn.executescript(_SCHEMA)
        # Migration: add is_completed if missing (DB created before this column)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(experiences)")}
        if "is_completed" not in cols:
            conn.execute("ALTER TABLE experiences ADD COLUMN is_completed INTEGER NOT NULL DEFAULT 0")
        if "proposal_text" not in cols:
            conn.execute("ALTER TABLE experiences ADD COLUMN proposal_text TEXT")
        if "lo_names" not in cols:
            conn.execute("ALTER TABLE experiences ADD COLUMN lo_names TEXT NOT NULL DEFAULT '[]'")
        if "strand" not in cols:
            conn.execute("ALTER TABLE experiences ADD COLUMN strand TEXT NOT NULL DEFAULT ''")
        if "is_deleted" not in cols:
            conn.execute("ALTER TABLE experiences ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
        # Migration: create schedules table if missing (pre-dates this feature)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                cas_id         INTEGER PRIMARY KEY,
                enabled        INTEGER NOT NULL DEFAULT 1,
                interval_days  INTEGER NOT NULL DEFAULT 1,
                lo_ids         TEXT    NOT NULL DEFAULT '[]',
                last_run_date  TEXT
            )
        """)


# ── Experiences ───────────────────────────────────────────────────────────────

def upsert_experience(conn: sqlite3.Connection,
                      cas_id: int, name: str = "",
                      is_completed: bool = False,
                      proposal_text: Optional[str] = None,
                      lo_names: Optional[list] = None,
                      strand: str = "") -> None:
    conn.execute("""
        INSERT INTO experiences (id, name, is_completed, proposal_text,
                                 lo_names, strand, synced_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name          = CASE WHEN excluded.name != '' THEN excluded.name ELSE name END,
            is_completed  = excluded.is_completed,
            proposal_text = CASE WHEN excluded.proposal_text IS NOT NULL
                                 THEN excluded.proposal_text ELSE proposal_text END,
            lo_names      = CASE WHEN excluded.lo_names != '[]'
                                 THEN excluded.lo_names ELSE lo_names END,
            strand        = CASE WHEN excluded.strand != '' THEN excluded.strand ELSE strand END,
            synced_at     = excluded.synced_at
    """, (cas_id, name, 1 if is_completed else 0,
          proposal_text, json.dumps(lo_names or []), strand, _now()))


def get_experience(conn: sqlite3.Connection, cas_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM experiences WHERE id = ?", (cas_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["lo_names"] = json.loads(d.get("lo_names") or "[]")
    return d


def list_experiences(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM experiences ORDER BY id").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["lo_names"] = json.loads(d.get("lo_names") or "[]")
        result.append(d)
    return result


# ── Reflections ───────────────────────────────────────────────────────────────

def upsert_reflection(conn: sqlite3.Connection,
                      entry: ReflectionEntry, cas_id: int) -> None:
    """Insert or update a reflection from a ReflectionEntry.
    Photos are handled separately via upsert_photo."""
    conn.execute("""
        INSERT INTO reflections (id, cas_id, kind, group_date, body_html, lo_ids,
                                 is_placeholder, synced_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            kind           = excluded.kind,
            group_date     = excluded.group_date,
            body_html      = CASE WHEN excluded.body_html IS NOT NULL
                                  THEN excluded.body_html ELSE body_html END,
            lo_ids         = excluded.lo_ids,
            is_placeholder = CASE WHEN excluded.body_html IS NOT NULL
                                  THEN excluded.is_placeholder ELSE is_placeholder END,
            synced_at      = excluded.synced_at
    """, (
        entry.rid,
        cas_id,
        entry.kind,
        entry.group_date,
        entry.body_html,
        json.dumps(entry.lo_ids),
        1 if entry.is_placeholder else 0,   # never NULL — None → 0
        _now(),
    ))


def upsert_photo(conn: sqlite3.Connection,
                 photo: Photo, reflection_id: int) -> None:
    conn.execute("""
        INSERT INTO photos (id, reflection_id, caption, created_at, s3_url)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            caption    = excluded.caption,
            created_at = excluded.created_at,
            s3_url     = excluded.s3_url
    """, (photo.id, reflection_id, photo.caption, photo.created_at, photo.s3_url))


def delete_reflection_local(conn: sqlite3.Connection, rid: int) -> None:
    """Remove reflection and its photos from local DB."""
    conn.execute("DELETE FROM photos WHERE reflection_id = ?", (rid,))
    conn.execute("DELETE FROM reflections WHERE id = ?", (rid,))


def get_reflection(conn: sqlite3.Connection, rid: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM reflections WHERE id = ?", (rid,)).fetchone()
    if row is None:
        return None
    r = dict(row)
    r["lo_ids"] = json.loads(r["lo_ids"])
    r["photos"] = _get_photos(conn, rid)
    return r


def list_reflections(conn: sqlite3.Connection,
                     cas_id: int,
                     kind: Optional[str] = None,
                     placeholder: Optional[bool] = None) -> list[dict]:
    """List reflections for a CAS activity, with optional filters."""
    q = "SELECT * FROM reflections WHERE cas_id = ?"
    params: list = [cas_id]
    if kind is not None:
        q += " AND kind = ?"
        params.append(kind)
    if placeholder is not None:
        q += " AND is_placeholder = ?"
        params.append(1 if placeholder else 0)
    q += " ORDER BY id DESC"
    rows = conn.execute(q, params).fetchall()
    result = []
    for row in rows:
        r = dict(row)
        r["lo_ids"] = json.loads(r["lo_ids"])
        r["photos"] = _get_photos(conn, r["id"])
        result.append(r)
    return result


def _get_photos(conn: sqlite3.Connection, reflection_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM photos WHERE reflection_id = ? ORDER BY id",
        (reflection_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Sync helpers ──────────────────────────────────────────────────────────────

def sync_entries(conn: sqlite3.Connection,
                 cas_id: int, entries: list[ReflectionEntry],
                 name: str = "", is_completed: bool = False) -> None:
    """Batch upsert a list of ReflectionEntry objects into the DB."""
    upsert_experience(conn, cas_id, name=name, is_completed=is_completed)
    for entry in entries:
        upsert_reflection(conn, entry, cas_id)
        if entry.photos:
            # Replace all photos for this reflection to avoid accumulation
            # (S3 presigned URLs change each fetch, so pseudo-IDs differ)
            with conn:
                conn.execute("DELETE FROM photos WHERE reflection_id = ?", (entry.rid,))
                for photo in entry.photos:
                    upsert_photo(conn, photo, entry.rid)


def mark_experiences_deletion_state(conn: sqlite3.Connection,
                                      live_cas_ids: set[int]) -> tuple[list[int], list[int]]:
    """Compare live_cas_ids against local DB.
    - Mark experiences in DB but not in live as is_deleted=1 (newly disappeared)
    - Mark experiences in live as is_deleted=0 (restored if they were marked deleted)
    Returns (newly_deleted_ids, restored_ids)."""
    local = {r["id"]: r["is_deleted"] for r in conn.execute(
        "SELECT id, is_deleted FROM experiences"
    ).fetchall()}
    newly_deleted = [cid for cid, was_del in local.items()
                     if cid not in live_cas_ids and not was_del]
    restored = [cid for cid, was_del in local.items()
                if cid in live_cas_ids and was_del]
    if newly_deleted:
        conn.executemany(
            "UPDATE experiences SET is_deleted = 1 WHERE id = ?",
            [(cid,) for cid in newly_deleted]
        )
    if restored:
        conn.executemany(
            "UPDATE experiences SET is_deleted = 0 WHERE id = ?",
            [(cid,) for cid in restored]
        )
    return newly_deleted, restored


def get_all_local_rids(conn: sqlite3.Connection, cas_id: int) -> set[int]:
    rows = conn.execute(
        "SELECT id FROM reflections WHERE cas_id = ?", (cas_id,)
    ).fetchall()
    return {r["id"] for r in rows}


def purge_deleted(conn: sqlite3.Connection,
                  cas_id: int, live_rids: set[int]) -> list[int]:
    """Remove reflections that no longer exist on ManageBac."""
    local = get_all_local_rids(conn, cas_id)
    gone = local - live_rids
    for rid in gone:
        delete_reflection_local(conn, rid)
    return list(gone)


# ── Drafts ────────────────────────────────────────────────────────────────────

def add_draft(conn: sqlite3.Connection, cas_id: int, note: str) -> int:
    """Add a raw quick-note draft. Returns the new draft id."""
    cur = conn.execute(
        "INSERT INTO drafts (cas_id, note, status, created_at) VALUES (?, ?, 'pending', ?)",
        (cas_id, note, _now())
    )
    return cur.lastrowid


def get_draft(conn: sqlite3.Connection, draft_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    return dict(row) if row else None


def list_drafts(conn: sqlite3.Connection,
                cas_id: Optional[int] = None,
                status: Optional[str] = None) -> list[dict]:
    q = "SELECT * FROM drafts WHERE 1=1"
    params: list = []
    if cas_id is not None:
        q += " AND cas_id = ?"
        params.append(cas_id)
    if status is not None:
        q += " AND status = ?"
        params.append(status)
    q += " ORDER BY id DESC"
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def update_draft(conn: sqlite3.Connection,
                 draft_id: int,
                 ai_result: Optional[str] = None,
                 status: Optional[str] = None) -> None:
    if ai_result is not None:
        conn.execute("UPDATE drafts SET ai_result = ? WHERE id = ?",
                     (ai_result, draft_id))
    if status is not None:
        conn.execute("UPDATE drafts SET status = ? WHERE id = ?",
                     (status, draft_id))


# ── Schedules ────────────────────────────────────────────────────────────────

def upsert_schedule(conn: sqlite3.Connection, cas_id: int,
                    enabled: bool = True,
                    interval_days: int = 1,
                    lo_ids: Optional[list] = None) -> None:
    conn.execute("""
        INSERT INTO schedules (cas_id, enabled, interval_days, lo_ids)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cas_id) DO UPDATE SET
            enabled       = excluded.enabled,
            interval_days = excluded.interval_days,
            lo_ids        = CASE WHEN excluded.lo_ids != '[]'
                                 THEN excluded.lo_ids ELSE lo_ids END
    """, (cas_id, 1 if enabled else 0, interval_days,
          json.dumps(lo_ids or [])))


def set_schedule_last_run(conn: sqlite3.Connection,
                          cas_id: int, date_str: str) -> None:
    conn.execute("UPDATE schedules SET last_run_date = ? WHERE cas_id = ?",
                 (date_str, cas_id))


def delete_schedule(conn: sqlite3.Connection, cas_id: int) -> None:
    conn.execute("DELETE FROM schedules WHERE cas_id = ?", (cas_id,))


def list_schedules(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("""
        SELECT s.*, e.name, e.is_completed
        FROM schedules s
        LEFT JOIN experiences e ON e.id = s.cas_id
        ORDER BY s.cas_id
    """).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["lo_ids"] = json.loads(d["lo_ids"])
        result.append(d)
    return result


def get_due_schedules(conn: sqlite3.Connection, today: str) -> list[dict]:
    """Return enabled schedules where today is due (based on interval_days)."""
    rows = conn.execute("""
        SELECT s.*, e.name, e.is_completed
        FROM schedules s
        LEFT JOIN experiences e ON e.id = s.cas_id
        WHERE s.enabled = 1
    """).fetchall()

    from datetime import date, timedelta
    today_dt = date.fromisoformat(today)
    due = []
    for r in rows:
        d = dict(r)
        d["lo_ids"] = json.loads(d["lo_ids"])
        last = d.get("last_run_date")
        if last is None:
            due.append(d)  # never run → always due
        else:
            last_dt = date.fromisoformat(last)
            if today_dt >= last_dt + timedelta(days=d["interval_days"]):
                due.append(d)
    return due


# ── Utilities ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def db_stats(conn: sqlite3.Connection) -> dict:
    """Return row counts for all tables."""
    return {
        tbl: conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        for tbl in ("experiences", "reflections", "photos", "drafts")
    }
