"""creature.png -> imagined.png (artifact imagined): the drawing reimagined as a character from an
animated film, cut out, for TRELLIS to make the AI 3D version from (step ai3d, trellis.py).

TRELLIS copies the picture it gets: from the drawing (or the balloon-shaded puffy.png) it made a
puffed-up drawing without character. A picture that already looks like a 3D film character gives
it volume, faces and materials to copy. The kid's faithful balloon stays beside it.

- FLUX.2 [klein] 4B (Apache 2.0, black-forest-labs/FLUX.2-klein-4B), an image-edit model: the
  drawing goes in as the reference, the prompt asks for the same creature in film style. Distilled:
  4 steps, guidance 1. Transformer (4B) plus its Qwen3-4B text encoder are ~16 GB in bf16, so by
  default each moves to the GPU only while it runs (MONSTER_IMAGINE_OFFLOAD=0: all on the GPU).
- Cut out with BiRefNet (MIT, ZhengPeng7/BiRefNet): TRELLIS needs the alpha, and its own remover
  (BRIA RMBG-2.0) is gated and non-commercial.

Runs in a child process per job (run_step.py), so everything here is loaded and freed per job.
"""

import gc
import logging
import os
from pathlib import Path

log = logging.getLogger("monster.gpu.imagine")

MODEL = os.environ.get("MONSTER_IMAGINE_MODEL", "black-forest-labs/FLUX.2-klein-4B")
MODEL_REVISION = os.environ.get("MONSTER_IMAGINE_REVISION", "e7b7dc27f91deacad38e78976d1f2b499d76a294")
CUTOUT_MODEL = "ZhengPeng7/BiRefNet"
CUTOUT_REVISION = "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4"  # its code runs (trust_remote_code): pinned
# Names no kind of creature and no body parts: "monster", "horns, teeth", "big eyes" and "facing the
# viewer" turned a zebra and a many-legged giraffe into the same horned, front-facing pastel monster.
# {skin} is what the kid picked on the 3D screen (SKINS); a MONSTER_IMAGINE_PROMPT without it gets
# the skin at the end. "Soft stylised materials" alone made every creature fluffy.
PROMPT = os.environ.get("MONSTER_IMAGINE_PROMPT") or (
    "Turn this drawing into a character from a 3D animated film. Keep exactly what is drawn: "
    "the same creature, pose, viewpoint, proportions and patterns, with the same body parts and "
    "nothing added. Keep the colours of the drawing; parts left uncoloured get the natural colours "
    "of what is drawn. Rounded, appealing volumes. {skin} "
    "The whole body in frame, centred on a plain white background, soft even light, no shadow, no text."
)
# The server's list (server/monster/steps/__init__.py, SKINS); an unknown name gets the default.
SKINS = {
    "toy": "Make it a smooth, glossy vinyl toy figure.",
    "fluffy": "Give it soft, fluffy fur, like a plush toy.",
    "slimy": "Make it out of shiny, wobbly, slightly see-through slime, glistening and a bit drippy.",
    "scaly": "Cover it in shiny overlapping scales, like a friendly dragon.",
    "knitted": "Make it knitted from chunky wool yarn, like a crocheted amigurumi toy.",
    "clay": "Make it from modelling clay, like a stop-motion puppet, with soft thumbprints in the clay.",
    "candy": "Make it out of sweets: glossy hard candy, gummy jelly and sugar icing.",
    "metal": "Make it a robot of polished, painted metal plates with little rivets.",
}
DEFAULT_SKIN = "toy"
STEPS = int(os.environ.get("MONSTER_IMAGINE_STEPS", "4"))
SEED = int(os.environ.get("MONSTER_IMAGINE_SEED", "42"))
OFFLOAD = os.environ.get("MONSTER_IMAGINE_OFFLOAD", "1") not in ("0", "false", "no")
SIZE = 1024      # the reference picture and the result
MARGIN = 0.12    # white space around the drawing, so the character has room to grow


def run(inputs: dict[str, Path], out: Path, params: dict | None = None) -> dict[str, str]:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    import torch
    from PIL import Image

    reference = on_white_square(Image.open(inputs["image"]), SIZE, MARGIN)
    picture = imagine(reference, prompt((params or {}).get("skin")))
    gc.collect()
    torch.cuda.empty_cache()
    rgba = crop_to_alpha(cut_out(picture))
    rgba.save(out / "imagined.png")
    log.info("peak VRAM %.1f GB (allocated by torch; nvidia-smi shows a bit more)",
             torch.cuda.max_memory_allocated() / 2**30)
    return {"imagined": "imagined.png"}


def on_white_square(image, size: int, margin: float):
    """The creature (alpha = its mask) centred on a white square, `margin` free on every side."""
    from PIL import Image

    image = image.convert("RGBA")
    box = image.getchannel("A").getbbox()
    if box:
        image = image.crop(box)
    inner = round(size * (1 - 2 * margin))
    scale = inner / max(image.size)
    image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                         Image.LANCZOS)
    square = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    square.alpha_composite(image, ((size - image.width) // 2, (size - image.height) // 2))
    return square.convert("RGB")


def prompt(skin: str | None) -> str:
    words = SKINS.get(skin or DEFAULT_SKIN, SKINS[DEFAULT_SKIN])
    return PROMPT.replace("{skin}", words) if "{skin}" in PROMPT else f"{PROMPT} {words}"


def imagine(reference, prompt: str):
    import torch
    from diffusers import Flux2KleinPipeline

    log.info("loading %s", MODEL)
    pipe = Flux2KleinPipeline.from_pretrained(MODEL, revision=MODEL_REVISION, torch_dtype=torch.bfloat16)
    if OFFLOAD:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
    log.info("imagining (%s steps, seed %s): %s", STEPS, SEED, prompt)
    picture = pipe(
        image=reference, prompt=prompt, height=SIZE, width=SIZE,
        num_inference_steps=STEPS, guidance_scale=1.0,
        generator=torch.Generator("cpu").manual_seed(SEED),
    ).images[0]
    del pipe
    return picture


def cut_out(picture):
    """The film character with an alpha mask from BiRefNet."""
    import torch
    from torchvision import transforms
    from transformers import AutoModelForImageSegmentation

    log.info("cutting out with %s", CUTOUT_MODEL)
    model = AutoModelForImageSegmentation.from_pretrained(
        CUTOUT_MODEL, revision=CUTOUT_REVISION, trust_remote_code=True)
    model.to("cuda").eval().half()
    prep = transforms.Compose([
        transforms.Resize((1024, 1024)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    with torch.no_grad():
        pred = model(prep(picture).unsqueeze(0).to("cuda").half())[-1].sigmoid()[0, 0].float().cpu()
    del model
    mask = transforms.ToPILImage()(pred).resize(picture.size)
    rgba = picture.convert("RGBA")
    rgba.putalpha(mask)
    return rgba


def crop_to_alpha(rgba, pad: float = 0.04, min_fraction: float = 0.01):
    """Crop to the character (a little room around it). Fails when the mask is all but empty: then
    the model drew something the cutout can't find, and the faithful version stays on its own."""
    alpha = rgba.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    box = alpha.getbbox()
    filled = sum(alpha.histogram()[255:]) / (rgba.width * rgba.height)
    if box is None or filled < min_fraction:
        raise RuntimeError(f"no character found in the imagined picture ({filled:.1%} of it)")
    p = round(pad * max(box[2] - box[0], box[3] - box[1]))
    return rgba.crop((max(0, box[0] - p), max(0, box[1] - p),
                      min(rgba.width, box[2] + p), min(rgba.height, box[3] + p)))
