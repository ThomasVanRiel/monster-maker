import io

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from monster import db, jobs, worker
from monster.api import create_app
from monster.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, lease_seconds=60, max_attempts=3, max_upload_mb=1)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def photo_bytes(w=640, h=480) -> bytes:
    """A white page with a dark scribbled blob, as a JPEG."""
    img = np.full((h, w, 3), 245, np.uint8)
    cv2.circle(img, (w // 2, h // 2), min(w, h) // 4, (40, 120, 220), -1)
    cv2.circle(img, (w // 2, h // 2), min(w, h) // 4, (30, 30, 30), 6)
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


def upload(client, kid_id, data=None):
    return client.post("/creatures", data={"kid_id": kid_id},
                       files={"photo": ("p.jpg", data or photo_bytes(), "image/jpeg")})


def test_kids(client):
    assert [k["color"] for k in client.get("/kids").json()] == ["#FF8A3D", "#3D7BFF"]
    r = client.post("/kids", json={"name": "Mila", "color": "#FF8A3D"})
    assert r.status_code == 201
    assert client.get("/kids").json()[-1] == {"id": 3, "name": "Mila", "color": "#FF8A3D"}
    assert client.post("/kids", json={"name": "X", "color": "red"}).status_code == 422


def test_upload_creates_creature_photo_and_cleanup_job(client, settings):
    kid = client.post("/kids", json={"name": "Mila", "color": "#FF8A3D"}).json()
    r = upload(client, kid["id"])
    assert r.status_code == 201
    c = r.json()
    assert c["kid_id"] == kid["id"]
    assert list(c["files"]) == ["photo"]
    assert [(j["step"], j["status"], j["worker"]) for j in c["jobs"]] == [("cleanup", "queued", "cpu")]
    assert (settings.creatures_dir / str(c["id"]) / "drawing.jpg").is_file()
    assert client.get(c["files"]["photo"].removeprefix("/api")).headers["content-type"] == "image/jpeg"


def test_upload_rejects_bad_input(client):
    assert upload(client, 99).status_code == 404
    kid = client.post("/kids", json={"name": "Mila", "color": "#FF8A3D"}).json()
    assert upload(client, kid["id"], b"not an image").status_code == 415
    assert upload(client, kid["id"], b"x" * (1024 * 1024 + 1)).status_code == 413


def test_worker_turns_photo_into_cutout_then_balloon(client, settings):
    kid = client.post("/kids", json={"name": "Mila", "color": "#FF8A3D"}).json()
    cid = upload(client, kid["id"]).json()["id"]

    conn = db.connect(settings.db_path)
    worker.run_one(conn, settings, jobs.claim(conn, "cpu", "test", 60, 3), "test")
    c = client.get(f"/creatures/{cid}").json()
    assert [(j["step"], j["status"]) for j in c["jobs"]] == [
        ("cleanup", "done"), ("balloon", "queued"), ("print_prep", "queued"), ("ai3d", "waiting_for_gpu")]
    assert set(c["files"]) == {"photo", "cutout", "mask", "creature"}

    for _ in range(2):
        worker.run_one(conn, settings, jobs.claim(conn, "cpu", "test", 60, 3), "test")
    conn.close()
    c = client.get(f"/creatures/{cid}").json()
    assert [j["status"] for j in c["jobs"]] == ["done", "done", "done", "waiting_for_gpu"]
    assert set(c["files"]) == {"photo", "cutout", "mask", "creature", "mesh_faithful", "print_3mf"}
    assert client.get(f"/creatures/{cid}/files/print_3mf").headers["content-type"] == "model/3mf"
    glb = client.get(f"/creatures/{cid}/files/mesh_faithful")
    assert glb.headers["content-type"] == "model/gltf-binary" and glb.content[:4] == b"glTF"
    cutout = Image.open(io.BytesIO(client.get(f"/creatures/{cid}/files/cutout").content))
    assert cutout.mode == "RGBA" and max(cutout.size) <= 440
    alpha = np.asarray(cutout)[..., 3]
    assert alpha[0, 0] == 0 and alpha[alpha.shape[0] // 2, alpha.shape[1] // 2] == 255

    events = client.get(f"/creatures/{cid}/events").text
    assert "event: jobs" in events and '"status": "done"' in events and "event: end" in events


def test_name_and_eyes(client):
    kid = client.post("/kids", json={"name": "Mila", "color": "#FF8A3D"}).json()
    cid = upload(client, kid["id"]).json()["id"]
    r = client.patch(f"/creatures/{cid}", json={"name": "Blob", "eyes": [{"x": 0.4, "y": 0.3, "r": 0.06}]})
    assert r.json()["name"] == "Blob" and r.json()["eyes"] == [{"x": 0.4, "y": 0.3, "r": 0.06}]
    assert client.patch(f"/creatures/{cid}", json={"eyes": [{"x": 2, "y": 0, "r": 0.1}]}).status_code == 422


def test_delete_creature_removes_rows_and_files(client, settings):
    cid = upload(client, 1).json()["id"]
    assert client.delete(f"/creatures/{cid}").status_code == 204
    assert client.get(f"/creatures/{cid}").status_code == 404
    assert not (settings.creatures_dir / str(cid)).exists()
    conn = db.connect(settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()


def test_worker_survives_creature_deleted_mid_job(client, settings):
    cid = upload(client, 1).json()["id"]
    conn = db.connect(settings.db_path)
    job = jobs.claim(conn, "cpu", "test", 60, 3)
    steps = dict(worker.CPU_STEPS)
    try:
        def step_then_delete(f):
            out = steps["cleanup"](f)
            client.delete(f"/creatures/{cid}")
            return out
        worker.CPU_STEPS["cleanup"] = step_then_delete
        worker.run_one(conn, settings, job, "test")  # must not raise
    finally:
        worker.CPU_STEPS.update(steps)
    assert conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
    conn.close()


def test_worker_backfills_steps_added_later(client, settings):
    cid = upload(client, 1).json()["id"]
    conn = db.connect(settings.db_path)
    job = jobs.claim(conn, "cpu", "test", 60, 3)
    jobs.finish(conn, job["id"], "test")  # a cleanup that finished before balloon existed
    worker.backfill(conn)
    worker.backfill(conn)  # only once
    steps = [r[0] for r in conn.execute("SELECT step FROM jobs WHERE creature_id = ? ORDER BY id", (cid,))]
    assert steps == ["cleanup", "balloon", "print_prep", "ai3d"]
    assert conn.execute("SELECT status FROM jobs WHERE step = 'ai3d'").fetchone()[0] == "waiting_for_gpu"
    conn.close()


def test_rotate_turns_cutout_and_eyes_and_redoes_3d_once(client, settings):
    cid = upload(client, 1, photo_bytes(640, 360)).json()["id"]
    conn = db.connect(settings.db_path)
    for _ in range(3):  # cleanup, balloon, print_prep
        worker.run_one(conn, settings, jobs.claim(conn, "cpu", "test", 60, 3), "test")
    client.patch(f"/creatures/{cid}", json={"eyes": [{"x": 0.25, "y": 0.5, "r": 0.05}]})
    before = client.get(f"/creatures/{cid}").json()
    cut0 = np.asarray(Image.open(io.BytesIO(client.get(f"/creatures/{cid}/files/cutout").content)))

    client.post(f"/creatures/{cid}/rotate", json={})
    c = client.post(f"/creatures/{cid}/rotate", json={"turns": 1}).json()  # a second quick tap
    cut2 = np.asarray(Image.open(io.BytesIO(client.get(f"/creatures/{cid}/files/cutout").content)))
    assert np.array_equal(cut2, np.rot90(cut0, -2))  # two quarter turns, lossless
    assert c["rotation"] == 2
    assert c["files"]["cutout"] != before["files"]["cutout"]  # new ?v= so the tablet reloads it
    e = c["eyes"][0]
    assert abs(e["x"] - 0.75) < 1e-9 and abs(e["y"] - 0.5) < 1e-9 and abs(e["r"] - 0.05) < 1e-9
    queued = [j["step"] for j in c["jobs"] if j["status"] == "queued"]
    assert queued == ["balloon", "print_prep"]  # redone once, not once per tap
    conn.close()


def test_rotate_needs_a_cutout(client):
    cid = upload(client, 1).json()["id"]
    assert client.post(f"/creatures/{cid}/rotate", json={}).status_code == 409
    assert client.post("/creatures/999/rotate", json={}).status_code == 404
    assert client.post(f"/creatures/{cid}/rotate", json={"turns": 4}).status_code == 422


def test_rotate_eyes_quarter_turns():
    from monster.api import rotate_eyes
    eye = [{"x": 0.2, "y": 0.1, "r": 0.05}]
    one = rotate_eyes(eye, 200, 100, 1)[0]  # 200 wide, 100 tall -> 100 wide, 200 tall
    assert (round(one["x"], 9), round(one["y"], 9), round(one["r"], 9)) == (0.9, 0.2, 0.1)
    back = rotate_eyes(eye, 200, 100, 4)[0]
    assert all(abs(back[k] - eye[0][k]) < 1e-9 for k in "xyr")


def test_old_database_gets_the_rotation_column(tmp_path):
    import sqlite3
    old = sqlite3.connect(tmp_path / "old.sqlite")
    old.executescript("CREATE TABLE creatures (id INTEGER PRIMARY KEY, kid_id INTEGER NOT NULL, name TEXT,"
                      " created_at REAL NOT NULL, chosen_style TEXT, eyes TEXT NOT NULL DEFAULT '[]');"
                      "INSERT INTO creatures (kid_id, created_at) VALUES (1, 0);")
    old.close()
    conn = db.connect(tmp_path / "old.sqlite")
    db.init(conn)
    db.init(conn)  # idempotent
    assert conn.execute("SELECT rotation FROM creatures").fetchone()[0] == 0
    conn.close()
