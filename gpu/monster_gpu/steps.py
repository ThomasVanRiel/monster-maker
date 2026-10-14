"""The steps this worker can run, as "module:function" so a step's heavy imports (torch, TRELLIS)
only happen in the child process that runs it.

A step is run(inputs: {name: Path}, out: Path) -> {artifact kind: file name in out}. The server
decides what the inputs and outputs are (server/monster/steps/__init__.py, GPU_STEPS).
"""

STEPS = {
    "ai3d": "monster_gpu.trellis:run",
}

# MONSTER_GPU_PLACEHOLDER=1: same steps without a model, to test the whole round trip (claim,
# download, upload, the tablet showing the AI version) on a machine without TRELLIS or a GPU.
PLACEHOLDERS = {
    "ai3d": "monster_gpu.placeholder:run",
}
