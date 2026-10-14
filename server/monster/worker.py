"""CPU worker: claims cpu jobs from the SQLite queue and runs them. Same image as the API.

Runs on the home server next to the API and shares the data volume, so it talks to SQLite
directly. (The GPU worker on the gaming PC will pull over HTTP instead.)
"""

import logging
import os
import signal
import socket
import sqlite3
import threading
import time
import traceback

from . import db, jobs
from .config import load_settings
from .steps import CPU_STEPS, NEXT_STEPS

log = logging.getLogger("monster.worker")
POLL_SECONDS = 1.0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    conn = db.connect(settings.db_path)
    db.init(conn)
    worker_id = f"cpu@{socket.gethostname()}:{os.getpid()}"
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    backfill(conn)
    log.info("worker %s started, data in %s", worker_id, settings.data_dir)
    while not stop.is_set():
        job = jobs.claim(conn, "cpu", worker_id, settings.lease_seconds, settings.max_attempts)
        if job is None:
            stop.wait(POLL_SECONDS)
            continue
        run_one(conn, settings, job, worker_id)
    log.info("worker %s stopped", worker_id)


def backfill(conn) -> None:
    """Queue follow-up steps that were added after a creature was made (e.g. balloon for the
    first monsters): for every finished step, any missing next step gets a job."""
    for step, follow in NEXT_STEPS.items():
        for next_step, kind in follow:
            cur = conn.execute(
                "INSERT INTO jobs (creature_id, step, worker, created_at, updated_at)"
                " SELECT DISTINCT d.creature_id, ?, ?, ?, ? FROM jobs d"
                " WHERE d.step = ? AND d.status = 'done' AND NOT EXISTS"
                "  (SELECT 1 FROM jobs n WHERE n.creature_id = d.creature_id AND n.step = ?)",
                (next_step, kind, time.time(), time.time(), step, next_step),
            )
            if cur.rowcount:
                log.info("backfill: queued %s for %s creatures", next_step, cur.rowcount)


def run_one(conn, settings, job, worker_id: str) -> None:
    step = CPU_STEPS.get(job["step"])
    log.info("job %s: %s for creature %s (attempt %s)", job["id"], job["step"], job["creature_id"], job["attempts"])
    if step is None:
        jobs.fail(conn, job["id"], worker_id, f"unknown cpu step {job['step']!r}")
        return
    folder = settings.creatures_dir / str(job["creature_id"])
    try:
        produced = step(folder)
    except Exception:
        log.exception("job %s failed", job["id"])
        jobs.fail(conn, job["id"], worker_id, traceback.format_exc())
        return
    # artifacts, done and the follow-up steps in one go: a worker that lost its lease adds nothing
    conn.execute("BEGIN IMMEDIATE")
    try:
        for kind, filename in produced.items():
            jobs.add_artifact(conn, job["creature_id"], job["id"], kind, f"{job['creature_id']}/{filename}")
        if not jobs.finish(conn, job["id"], worker_id):
            conn.execute("ROLLBACK")
            log.warning("job %s: lease lost before finishing", job["id"])
            return
        for step_name, kind in NEXT_STEPS.get(job["step"], []):
            jobs.enqueue(conn, job["creature_id"], step_name, kind)
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        log.info("job %s: creature %s was deleted while it ran", job["id"], job["creature_id"])
    except BaseException:
        conn.execute("ROLLBACK")
        raise


if __name__ == "__main__":
    main()
