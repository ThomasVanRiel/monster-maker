"""Run one GPU step on a local picture, without the server: for trying TRELLIS out on the PC.

    python -m monster_gpu.try_step ai3d path/to/creature.png [out dir]

In the dev stack: docker compose -f compose.dev.yaml --profile gpu run --rm gpu-worker \\
    python -m monster_gpu.try_step ai3d /data/creatures/1/creature.png /data/try
Runs in this process (no child, no game check) and prints how long it took and the peak VRAM.
"""

import importlib
import sys
import time
from pathlib import Path

from .steps import PLACEHOLDERS, STEPS


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    step, image = sys.argv[1], Path(sys.argv[2])
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("try-out")
    out.mkdir(parents=True, exist_ok=True)
    target = (PLACEHOLDERS if "--placeholder" in sys.argv else STEPS)[step]
    module, func = target.split(":")
    t0 = time.monotonic()
    produced = getattr(importlib.import_module(module), func)({"image": image}, out)
    took = time.monotonic() - t0
    for kind, name in produced.items():
        size = (out / name).stat().st_size / 1e6
        print(f"{kind}: {out / name} ({size:.1f} MB)")
    print(f"took {took:.0f} s")
    try:
        import torch
        if torch.cuda.is_available():
            print(f"peak VRAM {torch.cuda.max_memory_allocated() / 2**30:.1f} GB (allocated by torch)")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
