"""The job queue: rows in the jobs table, claimed with a time-limited lease.

A worker claims the oldest runnable job for its kind (cpu/gpu). A job is runnable when it is
queued, or running with an expired lease (its worker vanished). A job whose lease expires after
max_attempts claims is marked failed instead of being handed out again.
"""

import sqlite3
import time
from contextlib import contextmanager


@contextmanager
def _tx(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def enqueue(conn: sqlite3.Connection, creature_id: int, step: str, worker: str) -> int:
    now = time.time()
    cur = conn.execute(
        "INSERT INTO jobs (creature_id, step, worker, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (creature_id, step, worker, now, now),
    )
    return cur.lastrowid


def claim(
    conn: sqlite3.Connection, worker: str, worker_id: str, lease_seconds: float, max_attempts: int
) -> sqlite3.Row | None:
    now = time.time()
    with _tx(conn):
        conn.execute(
            "UPDATE jobs SET status = 'failed', error = 'lease expired too often', leased_by = NULL,"
            " lease_until = NULL, updated_at = ?"
            " WHERE worker = ? AND status = 'running' AND lease_until < ? AND attempts >= ?",
            (now, worker, now, max_attempts),
        )
        return conn.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1, leased_by = ?,"
            " lease_until = ?, error = NULL, updated_at = ?"
            " WHERE id = (SELECT id FROM jobs WHERE worker = ?"
            "   AND (status = 'queued' OR (status = 'running' AND lease_until < ?))"
            "   ORDER BY id LIMIT 1)"
            " RETURNING *",
            (worker_id, now + lease_seconds, now, worker, now),
        ).fetchone()


def extend(conn: sqlite3.Connection, job_id: int, worker_id: str, lease_seconds: float) -> bool:
    """Heartbeat for long steps. False means the lease was lost and the worker should stop."""
    now = time.time()
    cur = conn.execute(
        "UPDATE jobs SET lease_until = ?, updated_at = ?"
        " WHERE id = ? AND status = 'running' AND leased_by = ?",
        (now + lease_seconds, now, job_id, worker_id),
    )
    return cur.rowcount == 1


def finish(conn: sqlite3.Connection, job_id: int, worker_id: str) -> bool:
    return _close(conn, job_id, worker_id, "done", None)


def fail(conn: sqlite3.Connection, job_id: int, worker_id: str, error: str) -> bool:
    return _close(conn, job_id, worker_id, "failed", error[:2000])


def release(conn: sqlite3.Connection, job_id: int, worker_id: str) -> bool:
    """Hand a job back to the queue untouched (worker shutting down)."""
    now = time.time()
    cur = conn.execute(
        "UPDATE jobs SET status = 'queued', attempts = MAX(attempts - 1, 0), leased_by = NULL,"
        " lease_until = NULL, updated_at = ? WHERE id = ? AND status = 'running' AND leased_by = ?",
        (now, job_id, worker_id),
    )
    return cur.rowcount == 1


def _close(conn, job_id, worker_id, status, error) -> bool:
    now = time.time()
    cur = conn.execute(
        "UPDATE jobs SET status = ?, error = ?, leased_by = NULL, lease_until = NULL, updated_at = ?"
        " WHERE id = ? AND status = 'running' AND leased_by = ?",
        (status, error, now, job_id, worker_id),
    )
    return cur.rowcount == 1


def for_creature(conn: sqlite3.Connection, creature_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, step, status, worker, attempts, error, updated_at FROM jobs"
        " WHERE creature_id = ? ORDER BY id",
        (creature_id,),
    ).fetchall()


def add_artifact(conn: sqlite3.Connection, creature_id: int, job_id: int | None, kind: str, path: str) -> None:
    conn.execute(
        "INSERT INTO artifacts (creature_id, job_id, kind, path, created_at) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (creature_id, kind) DO UPDATE SET job_id = excluded.job_id, path = excluded.path,"
        " created_at = excluded.created_at",
        (creature_id, job_id, kind, path, time.time()),
    )
