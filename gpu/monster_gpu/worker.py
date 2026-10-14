"""GPU worker loop: borrows the gaming PC when nobody is gaming, pulls jobs from the home server.

Pull, don't push: the PC opens no ports. Every round it checks it may work (hours, games, VRAM),
asks the server for a job (POST /worker/claim), downloads the inputs, runs the step in a child
process while sending heartbeats, uploads the result and asks again. A game starting mid-job or
SIGTERM (PC shutting down) kills the child and hands the job back; a PC that just vanishes is
covered by the lease running out on the server.
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import gate
from .config import Settings, load_settings
from .steps import PLACEHOLDERS, STEPS

log = logging.getLogger("monster.gpu")
WATCH_SECONDS = 5.0      # how often a running job checks for games, stop and heartbeats
SUFFIX = {"image/png": ".png", "image/jpeg": ".jpg", "model/gltf-binary": ".glb"}


class Worker:
    def __init__(self, settings: Settings, client, stop: threading.Event | None = None,
                 steps: dict[str, str] | None = None, clock: Callable[[], datetime] = datetime.now,
                 proc: Path = Path("/proc"), vram=gate.vram_used_mb):
        self.s = settings
        self.client = client          # httpx.Client with base_url = the server's API
        self.stop = stop or threading.Event()
        self.steps = steps or (PLACEHOLDERS if settings.placeholder else STEPS)
        self.clock, self.proc, self.vram = clock, proc, vram
        self.auth = {"Authorization": f"Bearer {settings.token}"}
        self.child: subprocess.Popen | None = None

    # --- talking to the server -------------------------------------------------------------

    def post(self, path: str, **kw):
        return self.client.post(path, headers=self.auth, **kw)

    def ping(self, state: str, detail: str | None = None) -> None:
        self.post("worker/ping", json={"worker_id": self.s.worker_id, "state": state, "detail": detail})

    def hello(self) -> dict:
        return {"worker_id": self.s.worker_id}

    # --- the loop --------------------------------------------------------------------------

    def loop(self) -> None:
        log.info("worker %s polling %s for %s", self.s.worker_id, self.s.server, ", ".join(self.steps))
        backoff = self.s.poll_seconds
        while not self.stop.is_set():
            try:
                worked = self.tick()
                backoff = self.s.poll_seconds
            except Exception as e:  # server down, network gone: try again later, slower and slower
                log.warning("server unreachable (%s), retrying in %.0f s", e, backoff)
                self.stop.wait(backoff)
                backoff = min(backoff * 2, 600)
                continue
            if not worked:
                self.stop.wait(self.s.poll_seconds)

    def tick(self) -> bool:
        """One round. True when a job was run (ask again right away)."""
        blocked = gate.why_not_now(self.s, self.clock(), self.proc, self.vram)
        if blocked:
            log.debug("not now: %s (%s)", *blocked)
            self.ping(*blocked)
            return False
        r = self.post("worker/claim", json={**self.hello(), "steps": list(self.steps)})
        if r.status_code == 204:
            return False
        r.raise_for_status()
        self.run_job(r.json())
        return True

    def run_job(self, job: dict) -> None:
        jid = job["id"]
        log.info("job %s: %s for creature %s (attempt %s)", jid, job["step"], job["creature_id"], job["attempts"])
        work = Path(tempfile.mkdtemp(prefix=f"monster-job{jid}-"))
        try:
            inputs = self.download(job, work)
            outcome, detail = self.run_child(job, inputs, work)
            if outcome == "done":
                self.upload(job, work, detail)
            elif outcome == "failed":
                log.warning("job %s failed:\n%s", jid, detail)
                self.post(f"worker/jobs/{jid}/fail", json={**self.hello(), "error": detail})
            elif outcome == "release":
                log.info("job %s handed back: %s", jid, detail)
                self.post(f"worker/jobs/{jid}/release", json=self.hello())
            else:  # lost: the server gave it to someone else or the creature was deleted
                log.info("job %s: lease lost, dropped", jid)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def download(self, job: dict, work: Path) -> dict[str, Path]:
        (work / "in").mkdir()
        inputs = {}
        for name, url in job["inputs"].items():
            r = self.client.get(url)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "").split(";")[0]
            path = work / "in" / (name + SUFFIX.get(ctype, ".bin"))
            path.write_bytes(r.content)
            inputs[name] = path
        return inputs

    def run_child(self, job: dict, inputs: dict[str, Path], work: Path) -> tuple[str, str | dict]:
        """Run the step in its own process. Returns (done, {kind: file}), (failed, error),
        (release, why) or (lost, '')."""
        out = work / "out"
        out.mkdir()
        # params: the kid's choices (skin); an older server sends none
        (work / "job.json").write_text(json.dumps(
            {"inputs": {k: str(v) for k, v in inputs.items()}, "params": job.get("params") or {}}))
        log_path = work / "step.log"
        lease = float(job.get("lease_seconds") or 600)
        beat_every = max(WATCH_SECONDS, lease / 3)
        with open(log_path, "wb") as logf:
            self.child = subprocess.Popen(
                [sys.executable, "-m", "monster_gpu.run_step", self.steps[job["step"]],
                 str(work / "job.json"), str(out)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=child_env())
            # the step's own output (model downloads, progress) into the worker's log as well
            tee = threading.Thread(target=_tee, args=(self.child.stdout, logf), daemon=True)
            tee.start()
            last_beat = time.monotonic()
            try:
                while True:
                    try:
                        self.child.wait(WATCH_SECONDS)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    if self.stop.is_set():
                        return "release", "worker stopping"
                    game = gate.game_running(self.s.game_patterns, self.proc)
                    if game:
                        self.ping("gaming", game)
                        return "release", f"game started: {game}"
                    if time.monotonic() - last_beat >= beat_every:
                        r = self.post(f"worker/jobs/{job['id']}/heartbeat", json=self.hello())
                        if r.status_code == 409:
                            return "lost", ""
                        last_beat = time.monotonic()
            finally:
                self.kill_child()
                tee.join(5)
        if self.child.returncode != 0:
            tail = log_path.read_bytes()[-6000:].decode(errors="replace")
            return "failed", f"exit code {self.child.returncode}\n{tail}"
        return "done", json.loads((out / "result.json").read_text())

    def kill_child(self) -> None:
        if self.child and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(20)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()

    def upload(self, job: dict, work: Path, produced: dict[str, str]) -> None:
        files = {kind: (name, (work / "out" / name).read_bytes(), "application/octet-stream")
                 for kind, name in produced.items()}
        for attempt in range(5):
            try:
                r = self.post(f"worker/jobs/{job['id']}/done", data=self.hello(), files=files, timeout=300)
            except Exception as e:  # keep the result: the network may be back in a moment
                log.warning("upload of job %s failed (%s), retrying", job["id"], e)
                if self.stop.wait(10 * (attempt + 1)):
                    break
                continue
            if r.status_code == 409:
                log.info("job %s: finished too late (%s), dropped", job["id"], r.text)
            elif r.status_code >= 400:
                # rejected (too large, not a GLB): the job is ours to fail, or it would sit there
                log.warning("job %s: upload rejected: %s %s", job["id"], r.status_code, r.text)
                self.post(f"worker/jobs/{job['id']}/fail",
                          json={**self.hello(), "error": f"upload rejected: {r.status_code} {r.text}"[:20000]})
            else:
                log.info("job %s: done", job["id"])
            return
        self.post(f"worker/jobs/{job['id']}/release", json=self.hello())


def _tee(pipe, logf) -> None:
    """Copy the child's output to its log file and to our stdout as it comes."""
    out = getattr(sys.stdout, "buffer", None)
    while chunk := os.read(pipe.fileno(), 65536):
        logf.write(chunk)
        if out is not None:
            out.write(chunk)
            out.flush()
    pipe.close()


def child_env() -> dict[str, str]:
    """This package importable in the child whatever the working directory."""
    here = str(Path(__file__).resolve().parents[1])
    path = os.environ.get("PYTHONPATH")
    return {**os.environ, "PYTHONPATH": here + (os.pathsep + path if path else "")}


def main() -> None:
    import httpx

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per poll otherwise
    settings = load_settings()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    with httpx.Client(base_url=settings.server, timeout=60) as client:
        Worker(settings, client, stop).loop()
    log.info("worker %s stopped", settings.worker_id)


if __name__ == "__main__":
    main()
