"""Settings from environment variables (see .env.example at the repo root)."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    lease_seconds: float
    max_attempts: int
    max_upload_mb: int
    worker_token: str = ""   # shared secret for the GPU worker; empty = GPU endpoints switched off

    @property
    def db_path(self) -> Path:
        return self.data_dir / "monster.sqlite"

    @property
    def creatures_dir(self) -> Path:
        return self.data_dir / "creatures"


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(os.environ.get("MONSTER_DATA_DIR", "./data")).resolve(),
        lease_seconds=float(os.environ.get("MONSTER_LEASE_SECONDS", "600")),
        max_attempts=int(os.environ.get("MONSTER_MAX_ATTEMPTS", "3")),
        max_upload_mb=int(os.environ.get("MONSTER_MAX_UPLOAD_MB", "25")),
        worker_token=os.environ.get("MONSTER_WORKER_TOKEN", ""),
    )
