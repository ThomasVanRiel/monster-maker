"""imagined.png -> ai.glb (artifact mesh_ai): TRELLIS.2 (MIT, microsoft/TRELLIS.2-4B) turns the
drawing reimagined as an animated-film character (step imagine, imagine.py) into a 3D model.
Shown beside the faithful balloon, never instead of it; the kid picks.

Runs in a child process per job (run_step.py), so everything here is loaded and freed per job.

- The input comes cut out (BiRefNet, in the imagine step). TRELLIS uses an image's alpha as is, so
  its own background remover (BRIA RMBG-2.0: gated, non-commercial licence) is never needed and is
  not even downloaded.
- 16 GB VRAM: TRELLIS.2 is tested on 24 GB+. Its low-VRAM mode (on by default) keeps the models
  in RAM and moves each to the GPU only while it runs: slower, but small. With it off
  (MONSTER_TRELLIS_LOW_VRAM=0) everything stays on the GPU. Running out of memory retries with
  low-VRAM on, then at 512, before giving up. The log ends with the peak VRAM used.
- The result is scaled like the faithful balloon (20 cm tall, standing on the floor, centred) so
  the two look like siblings in the viewer and in AR.
"""

import gc
import logging
import math
import os
from pathlib import Path

log = logging.getLogger("monster.gpu.trellis")

MODEL = os.environ.get("MONSTER_TRELLIS_MODEL", "microsoft/TRELLIS.2-4B")
PIPELINE = os.environ.get("MONSTER_TRELLIS_PIPELINE", "1024_cascade")  # 512, 1024, 1024_cascade, 1536_cascade
FACES = int(os.environ.get("MONSTER_AI_FACES", "150000"))      # after decimation: light enough for a tablet
TEXTURE = int(os.environ.get("MONSTER_AI_TEXTURE", "2048"))
SEED = int(os.environ.get("MONSTER_AI_SEED", "42"))
LOW_VRAM = os.environ.get("MONSTER_TRELLIS_LOW_VRAM", "1") not in ("0", "false", "no")
YAW_DEG = float(os.environ.get("MONSTER_AI_YAW_DEG", "0"))     # turn the result if it faces away
HEIGHT_M = 0.20  # same as the faithful balloon (server/monster/steps/balloon.py)


def run(inputs: dict[str, Path], out: Path) -> dict[str, str]:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    import torch
    from PIL import Image

    image = Image.open(inputs["image"]).convert("RGBA")
    pipeline = load_pipeline(LOW_VRAM)
    # (low VRAM, resolution) to try in turn when the GPU runs out of memory
    tries = [(LOW_VRAM, PIPELINE)] + ([(True, PIPELINE)] if not LOW_VRAM else [])
    if PIPELINE != "512":
        tries.append((True, "512"))
    for i, (low, kind) in enumerate(tries):
        try:
            if low and not pipeline.low_vram:
                to_low_vram(pipeline)
            mesh = generate(pipeline, image, kind)
            break
        except torch.cuda.OutOfMemoryError:
            if i == len(tries) - 1:
                raise
            log.warning("out of GPU memory at %s (low VRAM %s), trying %s (low VRAM %s)",
                        kind, low, tries[i + 1][1], tries[i + 1][0])
            gc.collect()
            torch.cuda.empty_cache()
    glb = to_glb(mesh)
    del mesh, pipeline
    fit(glb)
    (out / "ai.glb").write_bytes(glb.export(file_type="glb"))
    log.info("peak VRAM %.1f GB (allocated by torch; nvidia-smi shows a bit more)",
             torch.cuda.max_memory_allocated() / 2**30)
    return {"mesh_ai": "ai.glb"}


class _NoBackgroundRemoval:
    """Stands in for TRELLIS's background remover: our input always has its alpha."""

    def to(self, *_):
        pass

    cuda = cpu = to

    def __call__(self, image):
        raise RuntimeError("input image has no alpha; expected imagined.png")


def load_pipeline(low_vram: bool):
    import trellis2.pipelines.rembg as rembg
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    rembg.BiRefNet = lambda **_: _NoBackgroundRemoval()  # from_pretrained looks it up by name
    log.info("loading %s", MODEL)
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(MODEL)
    pipeline.low_vram = low_vram
    pipeline.cuda()  # with low VRAM this only picks the device; the models move as they run
    return pipeline


def to_low_vram(pipeline) -> None:
    """Back to RAM: from now on each model is on the GPU only while it runs."""
    import torch

    log.info("switching to low-VRAM mode")
    for m in pipeline.models.values():
        m.cpu()
    pipeline.image_cond_model.cpu()
    pipeline.low_vram = True
    torch.cuda.empty_cache()


def generate(pipeline, image, pipeline_type: str):
    log.info("generating at %s", pipeline_type)
    mesh = pipeline.run(image, seed=SEED, pipeline_type=pipeline_type)[0]
    mesh.simplify(16777216)  # nvdiffrast limit, as in TRELLIS.2's example.py
    return mesh


def to_glb(mesh):
    """TRELLIS's own export: remesh, decimate, UV-unwrap and bake the PBR texture. Y up."""
    import o_voxel

    return o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs, coords=mesh.coords,
        attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=FACES, texture_size=TEXTURE,
        remesh=True, remesh_band=1, remesh_project=0,
    )


def fit(mesh) -> None:
    """In place: HEIGHT_M tall, lowest point on the floor (y = 0), centred on x and z."""
    import numpy as np

    if YAW_DEG:
        a = math.radians(YAW_DEG)
        rot = np.eye(4)
        rot[0, 0], rot[0, 2], rot[2, 0], rot[2, 2] = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
        mesh.apply_transform(rot)
    lo, hi = mesh.bounds
    s = HEIGHT_M / max(hi[1] - lo[1], 1e-9)
    t = np.eye(4)
    t[:3, :3] *= s
    t[:3, 3] = [-(lo[0] + hi[0]) / 2 * s, -lo[1] * s, -(lo[2] + hi[2]) / 2 * s]
    mesh.apply_transform(t)
