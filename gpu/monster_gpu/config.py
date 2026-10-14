"""Settings from environment variables (see .env.example at the repo root, "gaming PC")."""

import os
import socket
from dataclasses import dataclass, field


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    server: str                     # the home server's API, e.g. https://monster.example.com/api/
    token: str                      # MONSTER_WORKER_TOKEN, same value as on the server
    worker_id: str
    steps: list[str]                # steps this worker runs
    poll_seconds: float = 30.0
    max_other_vram_mb: int = 2048   # more than this in use by others: someone is gaming
    game_patterns: list[str] = field(default_factory=list)  # substrings of a game's command line
    hours: str = ""                 # e.g. "08:00-18:00"; empty = any time
    weekdays_only: bool = False
    placeholder: bool = False       # fake AI step (no model): test the plumbing on any machine


def load_settings() -> Settings:
    server = os.environ.get("MONSTER_SERVER", "")
    if not server:
        raise SystemExit("set MONSTER_SERVER to the home server's API, e.g. https://monster.example.com/api")
    token = os.environ.get("MONSTER_WORKER_TOKEN", "")
    if not token:
        raise SystemExit("set MONSTER_WORKER_TOKEN (the same value as in the home server's .env)")
    return Settings(
        server=server.rstrip("/") + "/",
        token=token,
        worker_id=os.environ.get("MONSTER_WORKER_ID") or f"gpu@{socket.gethostname()}",
        steps=_list(os.environ.get("MONSTER_GPU_STEPS", "ai3d")),
        poll_seconds=float(os.environ.get("MONSTER_POLL_SECONDS", "30")),
        max_other_vram_mb=int(os.environ.get("MONSTER_MAX_OTHER_VRAM_MB", "2048")),
        # Steam games live under steamapps/common; Proton/Wine games show up as wine processes.
        game_patterns=_list(os.environ.get(
            "MONSTER_GAME_PATTERNS", "steamapps/common/,wine64-preloader,wineserver,gamescope")),
        hours=os.environ.get("MONSTER_GPU_HOURS", ""),
        weekdays_only=os.environ.get("MONSTER_GPU_WEEKDAYS_ONLY", "") in ("1", "true", "yes"),
        placeholder=os.environ.get("MONSTER_GPU_PLACEHOLDER", "") in ("1", "true", "yes"),
    )
