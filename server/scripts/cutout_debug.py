"""Run the cutout on photos and save every stage side by side, to see where a drawing goes wrong.

    uv run python scripts/cutout_debug.py ../tests/fixtures/*.jpeg [-o out_dir]

Writes <name>.debug.png (stages in a row) and <name>.cutout.png next to each other in out_dir.
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

from monster.steps.cleanup import cutout

TILE_H = 480


def tile(img: np.ndarray, label: str) -> np.ndarray:
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:  # sticker: put it on a checkerboard-ish grey
        a = img[..., 3:].astype(np.float32) / 255
        img = (img[..., :3] * a + 160 * (1 - a)).astype(np.uint8)
    s = TILE_H / img.shape[0]
    img = cv2.resize(img, (max(1, round(img.shape[1] * s)), TILE_H), interpolation=cv2.INTER_AREA)
    cv2.putText(img, label, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    return np.pad(img, ((0, 0), (0, 6), (0, 0)), constant_values=255)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("photos", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("cutout-debug"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for path in args.photos:
        src = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if src is None:
            print(f"{path}: unreadable")
            continue
        cut = cutout(src)
        row = [tile(v, k) for k, v in cut.debug.items()] + [tile(cut.sticker, "sticker")]
        cv2.imwrite(str(args.out / f"{path.stem}.debug.png"), np.hstack(row))
        cv2.imwrite(str(args.out / f"{path.stem}.cutout.png"), cut.sticker)
        print(f"{path}: {'found' if cut.found else 'FALLBACK'}, mask {cut.mask.mean():.1%} of the sheet")


if __name__ == "__main__":
    main()
