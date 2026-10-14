"""Child process for one step: python -m monster_gpu.run_step <module:function> <job.json> <out dir>

A fresh process per job: the model loads, runs and is gone with the process, so the GPU is
completely free again afterwards (the game check relies on that), and a CUDA crash can't take
the worker loop down with it. job.json: {"inputs": {name: path}, "params": {...}} (the kid's
choices, e.g. the skin). Writes <out dir>/result.json: {artifact kind: file name}.
"""

import importlib
import json
import sys
from pathlib import Path


def main() -> None:
    target, job_json, out = sys.argv[1:4]
    module, func = target.split(":")
    job = json.loads(Path(job_json).read_text())
    inputs = {k: Path(v) for k, v in job["inputs"].items()}
    out_dir = Path(out)
    produced = getattr(importlib.import_module(module), func)(inputs, out_dir, job["params"])
    (out_dir / "result.json").write_text(json.dumps(produced))


if __name__ == "__main__":
    main()
