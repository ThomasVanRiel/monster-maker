"""Is the gaming PC free for us? Checked before every job, and (game check only) while one runs.

- hours: an optional window (and weekdays only) in which the worker may run at all
- games: a process whose command line matches one of the patterns (Steam games run from
  steamapps/common/, Proton games under wine). In Docker this needs `pid: host` to see them.
- VRAM: more than max_other_vram_mb in use on the card before we start means someone else
  (a game we didn't recognise, a video editor) is using it. Only checked while we hold nothing.
"""

import subprocess
from datetime import datetime
from pathlib import Path

from .config import Settings


def in_hours(settings: Settings, now: datetime) -> bool:
    if settings.weekdays_only and now.weekday() >= 5:
        return False
    if not settings.hours:
        return True
    start, end = (_minutes(t) for t in settings.hours.split("-"))
    m = now.hour * 60 + now.minute
    return start <= m < end if start <= end else (m >= start or m < end)  # e.g. 22:00-07:00


def _minutes(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def game_running(patterns: list[str], proc: Path = Path("/proc")) -> str | None:
    """The command line of the first process that looks like a game, or None."""
    if not patterns:
        return None
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:  # gone, or not ours to read
            continue
        if cmd and any(p in cmd for p in patterns):
            return cmd[:200]
    return None


def vram_used_mb() -> int | None:
    """Memory in use on the first GPU, or None when nvidia-smi is missing or fails."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True).stdout
        return int(out.split()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def why_not_now(settings: Settings, now: datetime, proc: Path = Path("/proc"),
                vram=vram_used_mb) -> tuple[str, str | None] | None:
    """None when a job may start, else (state, detail) for the server's parent-mode status."""
    if not in_hours(settings, now):
        return "quiet_hours", settings.hours or "weekend"
    game = game_running(settings.game_patterns, proc)
    if game:
        return "gaming", game
    used = vram()
    if used is None:
        if settings.placeholder:
            return None  # the placeholder step needs no GPU
        return "no_gpu", "nvidia-smi not available"
    if used > settings.max_other_vram_mb:
        return "gpu_busy", f"{used} MB in use"
    return None
