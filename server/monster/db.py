"""SQLite connection and schema. One file, WAL mode, shared by the API and the CPU worker."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS kids (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    color   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS creatures (
    id            INTEGER PRIMARY KEY,
    kid_id        INTEGER NOT NULL REFERENCES kids(id),
    name          TEXT,
    created_at    REAL NOT NULL,
    chosen_style  TEXT,
    eyes          TEXT NOT NULL DEFAULT '[]',  -- rigging aid: JSON [{x, y, r}] in cutout coordinates (0..1)
    rotation      INTEGER NOT NULL DEFAULT 0   -- quarter turns clockwise applied to the cutout (0-3)
);

CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY,
    creature_id  INTEGER NOT NULL REFERENCES creatures(id) ON DELETE CASCADE,
    step         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'running', 'done', 'failed', 'waiting_for_gpu')),
    worker       TEXT NOT NULL CHECK (worker IN ('cpu', 'gpu')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    leased_by    TEXT,
    lease_until  REAL,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_pick ON jobs(worker, status, id);
CREATE INDEX IF NOT EXISTS jobs_creature ON jobs(creature_id);

CREATE TABLE IF NOT EXISTS artifacts (
    id           INTEGER PRIMARY KEY,
    creature_id  INTEGER NOT NULL REFERENCES creatures(id) ON DELETE CASCADE,
    job_id       INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    kind         TEXT NOT NULL,
    path         TEXT NOT NULL,   -- relative to the creatures dir, e.g. "12/cutout.png"
    created_at   REAL NOT NULL,
    UNIQUE (creature_id, kind)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


# First start: two kids with the prototype's avatar colours. Renamed/recoloured later in parent mode.
DEFAULT_KIDS = [("Kid 1", "#FF8A3D"), ("Kid 2", "#3D7BFF")]


# Columns added after the first deploy: CREATE TABLE IF NOT EXISTS won't add them to an old file.
MIGRATIONS = [
    ("creatures", "rotation", "INTEGER NOT NULL DEFAULT 0"),
]


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, column, decl in MIGRATIONS:
        if column not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            except sqlite3.OperationalError as e:  # the API and the worker start at the same time
                if "duplicate column" not in str(e):
                    raise
    conn.execute("BEGIN IMMEDIATE")
    if conn.execute("SELECT COUNT(*) FROM kids").fetchone()[0] == 0:
        conn.executemany("INSERT INTO kids (name, color) VALUES (?, ?)", DEFAULT_KIDS)
    conn.execute("COMMIT")
