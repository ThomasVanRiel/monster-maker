"""Child process for one step: python -m monster_gpu.run_step <module:function> <inputs.json> <out dir>

A fresh process per job: the model loads, runs and is gone with the process, so the GPU is
completely free again afterwards (the game check relies on that), and a CUDA crash can't take
the worker loop down with it. Writes <out dir>/result.json: {artifact kind: file name}.
"""

import importlib
import json
import sys
from pathlib import Path


def main() -> None:
    target, inputs_json, out = sys.argv[1:4]
    module, func = target.split(":")
    inputs = {k: Path(v) for k, v in json.loads(Path(inputs_json).read_text()).items()}
    out_dir = Path(out)
    produced = getattr(importlib.import_module(module), func)(inputs, out_dir)
    (out_dir / "result.json").write_text(json.dumps(produced))


if __name__ == "__main__":
    main()
