"""HTTP API for the tablet and the GPU worker (/worker/...). Served behind Caddy under /api."""

import asyncio
import io
import json
import os
import secrets
import shutil
import sqlite3
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from . import db, jobs
from .config import Settings, load_settings
from .steps import DEFAULT_SKIN, GPU_STEPS, NEXT_STEPS, SKINS

# The events stream ends once every job is here. A GPU job waiting for the gaming PC counts: it
# may wait for days, and the tablet shows that as sleeping, not as busy.
SETTLED = {"done", "failed", "waiting_for_gpu"}
# Turned with the drawing; the AI model is thrown away and made again from the turned drawing.
ROTATED_KINDS = ("cutout", "mask", "creature")


class KidIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class Eye(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    r: float = Field(gt=0, le=0.5)


class Rotate(BaseModel):
    turns: int = Field(default=1, ge=1, le=3)  # quarter turns clockwise


def rotate_eyes(eyes: list[dict], w: int, h: int, turns: int) -> list[dict]:
    """Eye marks (0..1 of the cutout, r relative to its width) after turning a w x h cutout."""
    for _ in range(turns):
        eyes = [{"x": 1 - e["y"], "y": e["x"], "r": e["r"] * w / h} for e in eyes]
        w, h = h, w
    return eyes


class CreatureUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    eyes: list[Eye] | None = Field(default=None, max_length=6)
    chosen_style: Literal["faithful", "ai"] | None = None  # the 3D version the kid picked
    skin: Literal[SKINS] | None = None  # what the AI version is made of; a new one makes it again


WorkerState = Field(max_length=40, pattern=r"^[a-z_]+$")


class WorkerHello(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)


class WorkerPing(WorkerHello):
    state: str = WorkerState            # ready, gaming, quiet_hours, ...
    detail: str | None = Field(default=None, max_length=200)


class WorkerClaim(WorkerHello):
    steps: list[str] | None = None      # the steps this worker can run; None = all GPU steps


class WorkerFail(WorkerHello):
    error: str = Field(max_length=20000)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.creatures_dir.mkdir(parents=True, exist_ok=True)
        conn = db.connect(settings.db_path)
        db.init(conn)
        conn.close()
        yield

    app = FastAPI(title="Monster Maker", root_path="/api", lifespan=lifespan)

    def get_conn() -> Iterator[sqlite3.Connection]:
        conn = db.connect(settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def worker_auth(authorization: Annotated[str | None, Header()] = None) -> None:
        """The GPU worker sends `Authorization: Bearer <MONSTER_WORKER_TOKEN>`. The LAN is the only
        credential for the tablet, but uploads that become a kid's 3D model need a bit more."""
        if not settings.worker_token:
            raise HTTPException(503, "GPU worker endpoints are switched off (no MONSTER_WORKER_TOKEN)")
        if not secrets.compare_digest(authorization or "", f"Bearer {settings.worker_token}"):
            raise HTTPException(401, "bad worker token")

    Worker = Depends(worker_auth)

    def seen(conn: sqlite3.Connection, worker_id: str, state: str, detail: str | None = None) -> None:
        conn.execute(
            "INSERT INTO workers (id, kind, state, detail, last_seen) VALUES (?, 'gpu', ?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET state = excluded.state, detail = excluded.detail,"
            " last_seen = excluded.last_seen",
            (worker_id, state, detail, time.time()))

    def leased_job(conn: sqlite3.Connection, job_id: int, worker_id: str) -> sqlite3.Row:
        job = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND worker = 'gpu' AND status = 'running' AND leased_by = ?",
            (job_id, worker_id)).fetchone()
        if job is None:
            raise HTTPException(409, "lease lost")  # expired and handed out again, or creature deleted
        return job

    def creature_or_404(conn: sqlite3.Connection, creature_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM creatures WHERE id = ?", (creature_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such creature")
        return row

    def creature_out(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
        job_rows = jobs.for_creature(conn, row["id"])
        # ?v= changes whenever a file is rewritten (e.g. rotated), so the tablet doesn't show a stale copy
        files = {a["kind"]: f"/api/creatures/{row['id']}/files/{a['kind']}?v={int(a['created_at'] * 1000)}"
                 for a in conn.execute(
                     "SELECT kind, created_at FROM artifacts WHERE creature_id = ? ORDER BY id", (row["id"],))}
        return {
            "id": row["id"],
            "kid_id": row["kid_id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "chosen_style": row["chosen_style"],
            "eyes": json.loads(row["eyes"]),
            "rotation": row["rotation"],
            "skin": row["skin"] or DEFAULT_SKIN,
            "files": files,
            "jobs": [dict(j) for j in job_rows],
        }

    @app.get("/health")
    def health(conn: Conn):
        conn.execute("SELECT 1")
        return {"ok": True}

    @app.get("/kids")
    def list_kids(conn: Conn):
        return [dict(r) for r in conn.execute("SELECT * FROM kids ORDER BY id")]

    @app.post("/kids", status_code=201)
    def add_kid(kid: KidIn, conn: Conn):
        cur = conn.execute("INSERT INTO kids (name, color) VALUES (?, ?)", (kid.name, kid.color))
        return {"id": cur.lastrowid, **kid.model_dump()}

    @app.get("/creatures")
    def list_creatures(conn: Conn, kid_id: int | None = None):
        if kid_id is None:
            rows = conn.execute("SELECT * FROM creatures ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM creatures WHERE kid_id = ? ORDER BY id DESC", (kid_id,)).fetchall()
        return [creature_out(conn, r) for r in rows]

    @app.post("/creatures", status_code=201)
    def upload(conn: Conn, kid_id: Annotated[int, Form()], photo: Annotated[UploadFile, File()]):
        if conn.execute("SELECT 1 FROM kids WHERE id = ?", (kid_id,)).fetchone() is None:
            raise HTTPException(404, "no such kid")
        limit = settings.max_upload_mb * 1024 * 1024
        data = photo.file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, "photo too large")
        try:
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        except (UnidentifiedImageError, OSError):
            raise HTTPException(415, "not an image")

        conn.execute("BEGIN IMMEDIATE")
        try:
            cid = conn.execute(
                "INSERT INTO creatures (kid_id, created_at) VALUES (?, ?)", (kid_id, time.time())
            ).lastrowid
            folder = settings.creatures_dir / str(cid)
            folder.mkdir(parents=True, exist_ok=True)
            img.save(folder / "drawing.jpg", "JPEG", quality=92)
            jobs.add_artifact(conn, cid, None, "photo", f"{cid}/drawing.jpg")
            jobs.enqueue(conn, cid, "cleanup", "cpu")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            shutil.rmtree(settings.creatures_dir / str(cid), ignore_errors=True)
            raise
        return creature_out(conn, creature_or_404(conn, cid))

    @app.get("/creatures/{creature_id}")
    def get_creature(creature_id: int, conn: Conn):
        return creature_out(conn, creature_or_404(conn, creature_id))

    @app.patch("/creatures/{creature_id}")
    def update_creature(creature_id: int, body: CreatureUpdate, conn: Conn):
        creature_or_404(conn, creature_id)
        if body.name is not None:
            conn.execute("UPDATE creatures SET name = ? WHERE id = ?", (body.name.strip() or None, creature_id))
        if body.eyes is not None:
            eyes = json.dumps([e.model_dump() for e in body.eyes])
            conn.execute("UPDATE creatures SET eyes = ? WHERE id = ?", (eyes, creature_id))
        if body.chosen_style is not None:
            conn.execute("UPDATE creatures SET chosen_style = ? WHERE id = ?", (body.chosen_style, creature_id))
        if body.skin is not None:
            reskin(conn, creature_id, body.skin)
        return creature_out(conn, creature_or_404(conn, creature_id))

    def reskin(conn: sqlite3.Connection, creature_id: int, skin: str) -> None:
        """A new skin: imagine runs again (it reads the skin when the GPU worker claims it), then
        ai3d. The old AI version stays until the new one is there; the gaming PC may be off for days."""
        conn.execute("BEGIN IMMEDIATE")
        try:
            old = conn.execute("SELECT skin FROM creatures WHERE id = ?", (creature_id,)).fetchone()["skin"]
            conn.execute("UPDATE creatures SET skin = ? WHERE id = ?", (skin, creature_id))
            cleaned = conn.execute(  # before that, cleanup queues imagine itself
                "SELECT 1 FROM artifacts WHERE creature_id = ? AND kind IN ('creature', 'cutout')",
                (creature_id,)).fetchone()
            if cleaned and (old or DEFAULT_SKIN) != skin:
                # an ai3d still waiting would only make the old skin in 3D
                conn.execute("DELETE FROM jobs WHERE creature_id = ? AND step = 'ai3d' AND status = 'waiting_for_gpu'",
                             (creature_id,))
                if not conn.execute(  # one waiting is enough: the skin is read at claim time
                        "SELECT 1 FROM jobs WHERE creature_id = ? AND step = 'imagine' AND status = 'waiting_for_gpu'",
                        (creature_id,)).fetchone():
                    jobs.enqueue(conn, creature_id, "imagine", "gpu")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    @app.post("/creatures/{creature_id}/rotate")
    def rotate_creature(creature_id: int, body: Rotate, conn: Conn):
        """Turn a drawing that was made sideways. Quarter turns are lossless, so the cutout and
        mask are turned in place right away; the 3D models and print file are made again."""
        row = creature_or_404(conn, creature_id)
        paths = {a["kind"]: settings.creatures_dir / a["path"] for a in conn.execute(
            f"SELECT kind, path FROM artifacts WHERE creature_id = ? AND kind IN ({', '.join('?' * len(ROTATED_KINDS))})",
            (creature_id, *ROTATED_KINDS))}
        if "cutout" not in paths:
            raise HTTPException(409, "no cutout yet")
        h, w = cv2.imread(str(paths["cutout"]), cv2.IMREAD_UNCHANGED).shape[:2]
        for path in paths.values():
            img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            tmp = path.with_suffix(".tmp" + path.suffix)
            cv2.imwrite(str(tmp), np.ascontiguousarray(np.rot90(img, -body.turns)))
            os.replace(tmp, path)  # the worker may be reading it
        eyes = rotate_eyes(json.loads(row["eyes"]), w, h, body.turns)

        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("UPDATE creatures SET rotation = (rotation + ?) % 4, eyes = ? WHERE id = ?",
                         (body.turns, json.dumps(eyes), creature_id))
            for kind, path in paths.items():
                jobs.add_artifact(conn, creature_id, None, kind, f"{creature_id}/{path.name}")
            # the AI version of the sideways drawing would stay until the gaming PC is on again
            conn.execute("DELETE FROM artifacts WHERE creature_id = ? AND kind IN ('imagined', 'mesh_ai')",
                         (creature_id,))
            queued = {r["step"] for r in conn.execute(
                "SELECT step FROM jobs WHERE creature_id = ? AND status IN ('queued', 'waiting_for_gpu')",
                (creature_id,))}
            for step, kind in NEXT_STEPS["cleanup"]:
                if step not in queued:  # several quick taps: one redo is enough
                    jobs.enqueue(conn, creature_id, step, kind)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return creature_out(conn, creature_or_404(conn, creature_id))

    @app.delete("/creatures/{creature_id}", status_code=204)
    def delete_creature(creature_id: int, conn: Conn):
        creature_or_404(conn, creature_id)
        conn.execute("DELETE FROM creatures WHERE id = ?", (creature_id,))
        shutil.rmtree(settings.creatures_dir / str(creature_id), ignore_errors=True)

    @app.get("/creatures/{creature_id}/files/{kind}")
    def get_file(creature_id: int, kind: str, conn: Conn):
        row = conn.execute(
            "SELECT path FROM artifacts WHERE creature_id = ? AND kind = ?", (creature_id, kind)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "no such file")
        path = (settings.creatures_dir / row["path"]).resolve()
        if not path.is_relative_to(settings.creatures_dir) or not path.is_file():
            raise HTTPException(404, "no such file")
        # AR viewers check the type; slicers want a file name
        media = {".glb": "model/gltf-binary", ".3mf": "model/3mf"}.get(path.suffix)
        return FileResponse(path, media_type=media, headers={"Cache-Control": "no-cache"})

    @app.get("/creatures/{creature_id}/events")
    async def creature_events(creature_id: int, request: Request):
        """Server-sent events: one `jobs` event whenever a job of this creature changes,
        then `end` once every job has finished or failed."""
        conn = db.connect(settings.db_path)
        try:
            creature_or_404(conn, creature_id)
        except HTTPException:
            conn.close()
            raise

        async def stream():
            last = None
            try:
                while not await request.is_disconnected():
                    snap = [dict(j) for j in await asyncio.to_thread(jobs.for_creature, conn, creature_id)]
                    if snap != last:
                        last = snap
                        yield f"event: jobs\ndata: {json.dumps(snap)}\n\n"
                        if all(j["status"] in SETTLED for j in snap):
                            yield "event: end\ndata: {}\n\n"
                            return
                    await asyncio.sleep(0.5)
            finally:
                conn.close()

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- GPU worker (gaming PC). It pulls: claim, download inputs, heartbeat, upload, ask again. ---

    @app.post("/worker/ping", dependencies=[Worker], status_code=204)
    def worker_ping(body: WorkerPing, conn: Conn):
        """Check-in while not claiming (gaming, quiet hours, ...), for the parent-mode status."""
        seen(conn, body.worker_id, body.state, body.detail)

    @app.post("/worker/claim", dependencies=[Worker])
    def worker_claim(body: WorkerClaim, conn: Conn):
        """The oldest waiting GPU job with its input URLs (relative to /api), or 204."""
        steps = [s for s in (body.steps if body.steps is not None else GPU_STEPS) if s in GPU_STEPS]
        seen(conn, body.worker_id, "ready")
        for _ in range(20):  # skip jobs whose inputs are gone
            job = jobs.claim(conn, "gpu", body.worker_id, settings.lease_seconds, settings.max_attempts, steps)
            if job is None:
                return Response(status_code=204)
            have = {a["kind"]: a["created_at"] for a in conn.execute(
                "SELECT kind, created_at FROM artifacts WHERE creature_id = ?", (job["creature_id"],))}
            inputs, missing = {}, []
            for name, kinds in GPU_STEPS[job["step"]].inputs.items():
                kind = next((k for k in kinds if k in have), None)
                if kind is None:
                    missing.append(name)
                else:
                    inputs[name] = f"creatures/{job['creature_id']}/files/{kind}?v={int(have[kind] * 1000)}"
            if missing:
                jobs.fail(conn, job["id"], body.worker_id, f"missing inputs: {', '.join(missing)}")
                continue
            seen(conn, body.worker_id, "working", f"{job['step']} for creature {job['creature_id']}")
            skin = conn.execute("SELECT skin FROM creatures WHERE id = ?", (job["creature_id"],)).fetchone()["skin"]
            return {"id": job["id"], "creature_id": job["creature_id"], "step": job["step"],
                    "attempts": job["attempts"], "lease_seconds": settings.lease_seconds, "inputs": inputs,
                    "params": {"skin": skin or DEFAULT_SKIN}}
        return Response(status_code=204)

    @app.post("/worker/jobs/{job_id}/heartbeat", dependencies=[Worker], status_code=204)
    def worker_heartbeat(job_id: int, body: WorkerHello, conn: Conn):
        if not jobs.extend(conn, job_id, body.worker_id, settings.lease_seconds):
            raise HTTPException(409, "lease lost")

    @app.post("/worker/jobs/{job_id}/release", dependencies=[Worker], status_code=204)
    def worker_release(job_id: int, body: WorkerHello, conn: Conn):
        """Hand the job back untouched (a game started, the PC is shutting down)."""
        jobs.release(conn, job_id, body.worker_id)

    @app.post("/worker/jobs/{job_id}/fail", dependencies=[Worker], status_code=204)
    def worker_fail(job_id: int, body: WorkerFail, conn: Conn):
        jobs.fail(conn, job_id, body.worker_id, body.error)

    @app.post("/worker/jobs/{job_id}/done", dependencies=[Worker], status_code=204)
    async def worker_done(job_id: int, request: Request):
        """Multipart: worker_id, plus one file per output artifact kind of the step."""
        form = await request.form(max_files=8, max_fields=8, max_part_size=1024 * 1024)
        worker_id = form.get("worker_id")
        if not isinstance(worker_id, str):
            raise HTTPException(422, "worker_id missing")
        conn = db.connect(settings.db_path)
        tmps: list = []
        try:
            job = leased_job(conn, job_id, worker_id)
            spec = GPU_STEPS[job["step"]]
            uploads = {k: v for k, v in form.items() if k != "worker_id"}
            if set(uploads) != set(spec.outputs) or any(isinstance(v, str) for v in uploads.values()):
                raise HTTPException(422, f"expected files: {', '.join(sorted(spec.outputs))}")
            folder = settings.creatures_dir / str(job["creature_id"])
            if not folder.is_dir():
                raise HTTPException(409, "creature deleted")
            limit = spec.max_mb * 1024 * 1024
            for kind, upload in uploads.items():
                data = await upload.read(limit + 1)
                if len(data) > limit:
                    raise HTTPException(413, f"{kind} too large")
                name = spec.outputs[kind]
                if name.endswith(".glb") and data[:4] != b"glTF":
                    raise HTTPException(415, f"{kind} is not a GLB file")
                if name.endswith(".png") and data[:8] != b"\x89PNG\r\n\x1a\n":
                    raise HTTPException(415, f"{kind} is not a PNG file")
                tmp = folder / f".{name}.upload"
                tmp.write_bytes(data)
                tmps.append((tmp, folder / name))
            leased_job(conn, job_id, worker_id)  # still ours after the upload?
            for tmp, final in tmps:
                os.replace(tmp, final)
            try:
                ok = jobs.complete(conn, job, worker_id, spec.outputs, NEXT_STEPS.get(job["step"], []))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "creature deleted")
            if not ok:
                raise HTTPException(409, "lease lost")
            seen(conn, worker_id, "ready")
        finally:
            for tmp, _ in tmps:
                tmp.unlink(missing_ok=True)
            conn.close()

    @app.get("/gpu")
    def gpu_status(conn: Conn):
        """For parent mode: is the gaming PC around, and how much is waiting for it."""
        counts = dict(conn.execute(
            "SELECT status, COUNT(*) FROM jobs WHERE worker = 'gpu' AND status IN ('waiting_for_gpu', 'running')"
            " GROUP BY status").fetchall())
        workers = [dict(r) for r in conn.execute(
            "SELECT id, state, detail, last_seen FROM workers WHERE kind = 'gpu' ORDER BY last_seen DESC")]
        return {"enabled": bool(settings.worker_token), "waiting": counts.get("waiting_for_gpu", 0),
                "running": counts.get("running", 0), "workers": workers, "now": time.time()}

    return app


app = create_app()
