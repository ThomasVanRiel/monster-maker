"""Pipeline steps. Each takes the creature's folder and returns {artifact kind: filename}."""

from collections.abc import Callable
from pathlib import Path

from . import balloon, cleanup, print_prep

CPU_STEPS: dict[str, Callable[[Path], dict[str, str]]] = {
    "cleanup": cleanup.run,
    "balloon": balloon.run,
    "print_prep": print_prep.run,
}

# Steps queued when a step finishes: (step, worker kind).
NEXT_STEPS: dict[str, list[tuple[str, str]]] = {
    "cleanup": [("balloon", "cpu"), ("print_prep", "cpu")],
}
