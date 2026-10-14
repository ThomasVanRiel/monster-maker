import time

import pytest

from monster import db, jobs


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.sqlite")
    db.init(c)
    c.execute("INSERT INTO creatures (id, kid_id, created_at) VALUES (1, 1, 0)")
    yield c
    c.close()


def status(conn, job_id):
    return conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]


def test_claim_oldest_for_worker_kind(conn):
    gpu = jobs.enqueue(conn, 1, "ai3d", "gpu")
    a = jobs.enqueue(conn, 1, "cleanup", "cpu")
    jobs.enqueue(conn, 1, "cleanup", "cpu")
    job = jobs.claim(conn, "cpu", "w1", 60, 3)
    assert job["id"] == a and job["status"] == "running" and job["attempts"] == 1
    assert status(conn, gpu) == "waiting_for_gpu"


def test_gpu_jobs_wait_for_the_gpu_and_go_back_there(conn):
    j = jobs.enqueue(conn, 1, "ai3d", "gpu")
    assert jobs.claim(conn, "cpu", "c", 60, 3) is None
    assert jobs.claim(conn, "gpu", "g", 60, 3, steps=["other"]) is None
    assert jobs.claim(conn, "gpu", "g", 60, 3, steps=[]) is None
    assert jobs.claim(conn, "gpu", "g", 60, 3, steps=["ai3d"])["id"] == j
    assert jobs.release(conn, j, "g")
    assert status(conn, j) == "waiting_for_gpu"


def test_running_job_is_not_claimed_twice(conn):
    jobs.enqueue(conn, 1, "cleanup", "cpu")
    assert jobs.claim(conn, "cpu", "w1", 60, 3) is not None
    assert jobs.claim(conn, "cpu", "w2", 60, 3) is None


def test_expired_lease_is_reclaimed_and_old_worker_cannot_finish(conn):
    j = jobs.enqueue(conn, 1, "cleanup", "cpu")
    jobs.claim(conn, "cpu", "w1", -1, 3)  # lease already expired
    again = jobs.claim(conn, "cpu", "w2", 60, 3)
    assert again["id"] == j and again["attempts"] == 2
    assert not jobs.finish(conn, j, "w1")
    assert jobs.finish(conn, j, "w2")
    assert status(conn, j) == "done"


def test_gives_up_after_max_attempts(conn):
    j = jobs.enqueue(conn, 1, "cleanup", "cpu")
    for _ in range(2):
        assert jobs.claim(conn, "cpu", "w", -1, 2) is not None
    assert jobs.claim(conn, "cpu", "w", -1, 2) is None
    assert status(conn, j) == "failed"


def test_release_returns_job_without_using_an_attempt(conn):
    j = jobs.enqueue(conn, 1, "cleanup", "cpu")
    jobs.claim(conn, "cpu", "w1", 60, 3)
    assert jobs.release(conn, j, "w1")
    job = jobs.claim(conn, "cpu", "w2", 60, 3)
    assert job["id"] == j and job["attempts"] == 1


def test_extend_keeps_lease(conn):
    j = jobs.enqueue(conn, 1, "cleanup", "cpu")
    jobs.claim(conn, "cpu", "w1", 0.01, 3)
    assert jobs.extend(conn, j, "w1", 60)
    time.sleep(0.02)
    assert jobs.claim(conn, "cpu", "w2", 60, 3) is None
    assert not jobs.extend(conn, j, "w2", 60)
