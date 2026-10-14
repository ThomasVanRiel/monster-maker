"""HTTP API for the tablet (and, from Phase 2, the GPU worker). Served behind Caddy under /api."""

import asyncio
import io
import json
import shutil
import sqlite3
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from . import db, jobs
from .config import Settings, load_settings

TERMINAL = {"done", "failed"}


class KidIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class Eye(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    r: float = Field(gt=0, le=0.5)


class CreatureUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    eyes: list[Eye] | None = Field(default=None, max_length=6)


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

    def creature_or_404(conn: sqlite3.Connection, creature_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM creatures WHERE id = ?", (creature_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "no such creature")
        return row

    def creature_out(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
        job_rows = jobs.for_creature(conn, row["id"])
        kinds = [a["kind"] for a in conn.execute(
            "SELECT kind FROM artifacts WHERE creature_id = ? ORDER BY id", (row["id"],))]
        return {
            "id": row["id"],
            "kid_id": row["kid_id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "chosen_style": row["chosen_style"],
            "eyes": json.loads(row["eyes"]),
            "files": {k: f"/api/creatures/{row['id']}/files/{k}" for k in kinds},
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
                        if all(j["status"] in TERMINAL for j in snap):
                            yield "event: end\ndata: {}\n\n"
                            return
                    await asyncio.sleep(0.5)
            finally:
                conn.close()

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
