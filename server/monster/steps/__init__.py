"""Pipeline steps. Each takes the creature's folder and returns {artifact kind: filename}."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import balloon, cleanup, print_prep

CPU_STEPS: dict[str, Callable[[Path], dict[str, str]]] = {
    "cleanup": cleanup.run,
    "balloon": balloon.run,
    "print_prep": print_prep.run,
}


@dataclass(frozen=True)
class GpuStep:
    """A step the GPU worker on the gaming PC runs. It downloads `inputs` (the first artifact kind
    the creature has, per input name) and uploads `outputs`; the server picks the file names."""
    inputs: dict[str, tuple[str, ...]]
    outputs: dict[str, str]          # artifact kind -> file name in the creature's folder
    max_mb: int = 24                 # per uploaded file; the host's nginx stops bodies over 25 MB


GPU_STEPS: dict[str, GpuStep] = {
    # AI 3D (TRELLIS.2) beside the faithful balloon. creature.png has no sticker edge; creatures
    # made before it existed fall back to the sticker.
    "ai3d": GpuStep(inputs={"image": ("creature", "cutout")}, outputs={"mesh_ai": "ai.glb"}),
}

# Steps queued when a step finishes: (step, worker kind).
NEXT_STEPS: dict[str, list[tuple[str, str]]] = {
    "cleanup": [("balloon", "cpu"), ("print_prep", "cpu"), ("ai3d", "gpu")],
}
