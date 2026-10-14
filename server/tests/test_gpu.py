"""The GPU worker round trip: server endpoints plus the real worker loop (gpu/monster_gpu) with its
placeholder step, talking through the test client instead of the LAN."""

import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from monster import db, jobs, worker
from monster.api import create_app
from monster.config import Settings

from test_api import upload

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gpu"))
from monster_gpu.config import Settings as GpuSettings  # noqa: E402
from monster_gpu.worker import Worker  # noqa: E402

TOKEN = "s3cret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, lease_seconds=60, max_attempts=3, max_upload_mb=1, worker_token=TOKEN)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def cleaned_creature(client, settings) -> int:
    """A creature whose cpu steps have all run, so only the GPU steps are left: imagine waits."""
    cid = upload(client, 1).json()["id"]
    conn = db.connect(settings.db_path)
    while (job := jobs.claim(conn, "cpu", "test", 60, 3)) is not None:
        worker.run_one(conn, settings, job, "test")
    conn.close()
    return cid


def gpu_worker(client, tmp_path, **kw) -> Worker:
    (tmp_path / "proc").mkdir(exist_ok=True)
    s = GpuSettings(server="http://testserver/", token=TOKEN, worker_id="gpu@test", steps=["imagine", "ai3d"],
                    placeholder=True, game_patterns=["steamapps/common/"], **kw)
    return Worker(s, client, proc=tmp_path / "proc", vram=lambda: 300)


def test_worker_endpoints_need_the_token(client, settings, tmp_path):
    body = {"worker_id": "w"}
    assert client.post("/worker/claim", json=body).status_code == 401
    assert client.post("/worker/claim", json=body, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/worker/claim", json=body, headers=AUTH).status_code == 204
    off = Settings(data_dir=tmp_path / "off", lease_seconds=60, max_attempts=3, max_upload_mb=1)
    with TestClient(create_app(off)) as c:
        assert c.post("/worker/claim", json=body, headers=AUTH).status_code == 503


def test_round_trip_with_placeholder_step(client, settings, tmp_path):
    cid = cleaned_creature(client, settings)
    c = client.get(f"/creatures/{cid}").json()
    assert c["jobs"][-1]["step"] == "imagine" and c["jobs"][-1]["status"] == "waiting_for_gpu"
    assert "event: end" in client.get(f"/creatures/{cid}/events").text  # waiting counts as settled
    assert client.get("/gpu").json()["waiting"] == 1

    w = gpu_worker(client, tmp_path)
    assert w.tick() is True   # imagine
    c = client.get(f"/creatures/{cid}").json()
    assert [(j["step"], j["status"]) for j in c["jobs"]][-2:] == [("imagine", "done"), ("ai3d", "waiting_for_gpu")]
    png = client.get(c["files"]["imagined"].removeprefix("/api"))
    assert png.headers["content-type"] == "image/png"
    assert w.tick() is True   # ai3d, from the imagined picture
    assert w.tick() is False  # nothing left

    c = client.get(f"/creatures/{cid}").json()
    assert c["jobs"][-1]["step"] == "ai3d" and c["jobs"][-1]["status"] == "done"
    glb = client.get(c["files"]["mesh_ai"].removeprefix("/api"))
    assert glb.headers["content-type"] == "model/gltf-binary" and glb.content[:4] == b"glTF"
    status = client.get("/gpu").json()
    assert status["waiting"] == 0 and status["workers"][0]["id"] == "gpu@test"
    assert status["workers"][0]["state"] == "ready"

    r = client.patch(f"/creatures/{cid}", json={"chosen_style": "ai"})
    assert r.json()["chosen_style"] == "ai"
    assert client.patch(f"/creatures/{cid}", json={"chosen_style": "fancy"}).status_code == 422


def test_rotate_drops_the_ai_version_and_waits_for_a_new_one(client, settings, tmp_path):
    cid = cleaned_creature(client, settings)
    w = gpu_worker(client, tmp_path)
    w.tick()
    w.tick()
    c = client.post(f"/creatures/{cid}/rotate", json={}).json()
    assert "mesh_ai" not in c["files"] and "imagined" not in c["files"]
    client.post(f"/creatures/{cid}/rotate", json={})
    conn = db.connect(settings.db_path)
    while (job := jobs.claim(conn, "cpu", "test", 60, 3)) is not None:  # balloon (twice), print
        worker.run_one(conn, settings, job, "test")
    conn.close()
    c = client.get(f"/creatures/{cid}").json()
    waiting = [j["step"] for j in c["jobs"] if j["status"] == "waiting_for_gpu"]
    assert waiting == ["imagine"]  # once, however often it was turned


def test_new_skin_makes_the_ai_version_again_and_goes_with_the_job(client, settings, tmp_path):
    cid = cleaned_creature(client, settings)
    assert client.get(f"/creatures/{cid}").json()["skin"] == "toy"
    claim = client.post("/worker/claim", json={"worker_id": "w"}, headers=AUTH).json()
    assert claim["step"] == "imagine" and claim["params"] == {"skin": "toy"}
    client.post(f"/worker/jobs/{claim['id']}/release", json={"worker_id": "w"}, headers=AUTH)

    w = gpu_worker(client, tmp_path)
    w.tick()  # imagine; ai3d waits
    c = client.patch(f"/creatures/{cid}", json={"skin": "slimy"}).json()
    assert c["skin"] == "slimy" and "imagined" in c["files"]  # the old one stays until the new is made
    client.patch(f"/creatures/{cid}", json={"skin": "slimy"})
    c = client.patch(f"/creatures/{cid}", json={"skin": "candy"}).json()
    waiting = [j["step"] for j in c["jobs"] if j["status"] == "waiting_for_gpu"]
    assert waiting == ["imagine"]  # the old ai3d is dropped, imagine waits once
    claim = client.post("/worker/claim", json={"worker_id": "w"}, headers=AUTH).json()
    assert claim["params"] == {"skin": "candy"}  # read when claimed: the last pick wins
    assert client.patch(f"/creatures/{cid}", json={"skin": "lava"}).status_code == 422


def test_skin_before_cleanup_waits_for_it(client, settings):
    cid = upload(client, 1).json()["id"]
    c = client.patch(f"/creatures/{cid}", json={"skin": "fluffy"}).json()
    assert c["skin"] == "fluffy" and [j["step"] for j in c["jobs"]] == ["cleanup"]


def test_gaming_pc_reports_and_does_not_claim(client, settings, tmp_path):
    cleaned_creature(client, settings)
    w = gpu_worker(client, tmp_path)
    game = tmp_path / "proc" / "4242"
    game.mkdir()
    (game / "cmdline").write_bytes(b"/games/steamapps/common/Celeste/Celeste\0")
    assert w.tick() is False
    status = client.get("/gpu").json()
    assert status["waiting"] == 1 and status["workers"][0]["state"] == "gaming"


def test_game_starting_mid_job_hands_it_back(client, settings, tmp_path, monkeypatch):
    cid = cleaned_creature(client, settings)
    w = gpu_worker(client, tmp_path)
    monkeypatch.setattr("monster_gpu.worker.WATCH_SECONDS", 0.05)
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))  # for the child process
    w.steps = {"imagine": "gpu_slow_step:run"}

    def start_game():
        game = tmp_path / "proc" / "4242"
        game.mkdir()
        (game / "cmdline").write_bytes(b"/games/steamapps/common/Hades/Hades\0")

    threading.Timer(0.3, start_game).start()
    assert w.tick() is True
    assert w.child.returncode is not None  # stopped, not left running
    job = client.get(f"/creatures/{cid}").json()["jobs"][-1]
    assert job["status"] == "waiting_for_gpu" and job["attempts"] == 0
    assert client.get("/gpu").json()["workers"][0]["state"] == "gaming"


def test_step_failure_is_reported(client, settings, tmp_path):
    cid = cleaned_creature(client, settings)
    w = gpu_worker(client, tmp_path)
    w.steps = {"imagine": "monster_gpu.no_such_module:run"}
    assert w.tick() is True
    job = client.get(f"/creatures/{cid}").json()["jobs"][-1]
    assert job["status"] == "failed" and "no_such_module" in job["error"]


def test_done_upload_is_checked(client, settings):
    cid = cleaned_creature(client, settings)
    job = client.post("/worker/claim", json={"worker_id": "w"}, headers=AUTH).json()
    assert job["inputs"] == {"image": job["inputs"]["image"]}
    assert job["step"] == "imagine" and job["inputs"]["image"].startswith(f"creatures/{cid}/files/creature?v=")
    done = f"/worker/jobs/{job['id']}/done"
    png = b"\x89PNG\r\n\x1a\n...."
    assert client.post(done, data={"worker_id": "other"}, files={"imagined": ("a.png", png)},
                       headers=AUTH).status_code == 409
    assert client.post(done, data={"worker_id": "w"}, files={"evil": ("a.png", png)},
                       headers=AUTH).status_code == 422
    assert client.post(done, data={"worker_id": "w"}, files={"imagined": ("a.png", b"<html>")},
                       headers=AUTH).status_code == 415
    assert client.post(f"/worker/jobs/{job['id']}/heartbeat", json={"worker_id": "w"}, headers=AUTH).status_code == 204
    assert client.post(done, data={"worker_id": "w"}, files={"imagined": ("a.png", png)},
                       headers=AUTH).status_code == 204
    assert (settings.creatures_dir / str(cid) / "imagined.png").read_bytes() == png
    assert not list((settings.creatures_dir / str(cid)).glob(".*.upload"))
    assert client.post(f"/worker/jobs/{job['id']}/heartbeat", json={"worker_id": "w"}, headers=AUTH).status_code == 409

    job = client.post("/worker/claim", json={"worker_id": "w"}, headers=AUTH).json()
    assert job["step"] == "ai3d" and job["inputs"]["image"].startswith(f"creatures/{cid}/files/imagined?v=")
    done = f"/worker/jobs/{job['id']}/done"
    assert client.post(done, data={"worker_id": "w"}, files={"mesh_ai": ("a.glb", b"<html>")},
                       headers=AUTH).status_code == 415
    assert client.post(done, data={"worker_id": "w"}, files={"mesh_ai": ("a.glb", b"glTF....")},
                       headers=AUTH).status_code == 204
    assert (settings.creatures_dir / str(cid) / "ai.glb").read_bytes() == b"glTF...."


def test_job_without_inputs_is_failed_and_skipped(client, settings):
    cid = cleaned_creature(client, settings)
    conn = db.connect(settings.db_path)
    conn.execute("DELETE FROM artifacts WHERE creature_id = ? AND kind IN ('creature', 'cutout')", (cid,))
    conn.close()
    assert client.post("/worker/claim", json={"worker_id": "w"}, headers=AUTH).status_code == 204
    job = client.get(f"/creatures/{cid}").json()["jobs"][-1]
    assert job["status"] == "failed" and "missing inputs: image" in job["error"]


def test_backfill_moves_ai3d_behind_imagine(client, settings):
    """Creatures from before imagine: ai3d waited for the balloon's puffy.png. It is dropped and
    comes back once imagine has made the film character."""
    cid = cleaned_creature(client, settings)
    conn = db.connect(settings.db_path)
    conn.execute("DELETE FROM jobs WHERE creature_id = ? AND step = 'imagine'", (cid,))
    jobs.enqueue(conn, cid, "ai3d", "gpu")
    worker.backfill(conn)
    waiting = [r["step"] for r in conn.execute(
        "SELECT step FROM jobs WHERE creature_id = ? AND status = 'waiting_for_gpu'", (cid,))]
    conn.close()
    assert waiting == ["imagine"]
