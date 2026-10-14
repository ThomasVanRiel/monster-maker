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
        ("cleanup", "done"), ("balloon", "queued"), ("print_prep", "queued")]
    assert set(c["files"]) == {"photo", "cutout", "mask"}

    for _ in range(2):
        worker.run_one(conn, settings, jobs.claim(conn, "cpu", "test", 60, 3), "test")
    conn.close()
    c = client.get(f"/creatures/{cid}").json()
    assert [j["status"] for j in c["jobs"]] == ["done", "done", "done"]
    assert set(c["files"]) == {"photo", "cutout", "mask", "mesh_faithful", "print_3mf"}
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
    assert steps == ["cleanup", "balloon", "print_prep"]
    conn.close()
