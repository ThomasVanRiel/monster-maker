from pathlib import Path

import cv2
import numpy as np
import pytest

from monster.steps import cleanup

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def photo(outline=True, gap=0, shadow=False, tilt=0.0) -> np.ndarray:
    """A grey table with a slightly warm sheet of paper and an ellipse 'monster' drawn on it."""
    h, w = 1200, 900
    img = np.full((h, w, 3), (70, 90, 110), np.uint8)  # brownish table
    sheet = np.zeros((h, w), np.uint8)
    corners = np.array([[120, 100], [780, 100 + tilt * 660], [780, 1100], [120, 1100 - tilt * 660]], np.int32)
    cv2.fillConvexPoly(sheet, corners, 1)
    img[sheet > 0] = (215, 222, 230)
    if outline:
        cv2.ellipse(img, (450, 600), (180, 260), 0, 0, 360, (90, 80, 80), 7)
        if gap:  # a gap in the outline on the right-hand side
            cv2.rectangle(img, (620, 600 - gap // 2), (640, 600 + gap // 2), (215, 222, 230), -1)
    if shadow:  # soft shadow over the left part of the sheet, across the outline
        ramp = np.clip((np.arange(w) - 200) / 300, 0, 1).astype(np.float32)
        img = (img * (0.72 + 0.28 * ramp)[None, :, None]).astype(np.uint8)
    noise = np.random.default_rng(1).normal(0, 2, img.shape)
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def centre_and_outside(mask):
    h, w = mask.shape
    return mask[h // 2, w // 2], mask[h // 20, w // 20]


@pytest.mark.parametrize("kwargs", [{}, {"gap": 10}, {"shadow": True}, {"tilt": 0.05}],
                         ids=["plain", "gap", "shadow", "tilted"])
def test_ellipse_is_cut_out_filled(kwargs):
    cut = cleanup.cutout(photo(**kwargs))
    assert cut.found
    inside, outside = centre_and_outside(cut.mask)
    assert inside == 1 and outside == 0
    # the ellipse covers about pi*180*260 / (660*1000) = 22% of the sheet
    assert 0.17 < cut.mask.mean() < 0.30


def test_blank_sheet_falls_back_to_window():
    cut = cleanup.cutout(photo(outline=False))
    assert not cut.found
    assert cut.sticker.shape[2] == 4


def test_sticker_is_white_paper_with_a_dark_line():
    cut = cleanup.cutout(photo())
    s = cut.sticker
    h, w = s.shape[:2]
    assert s[h // 2, w // 2, 3] == 255 and s[0, 0, 3] == 0
    assert s[h // 2, w // 2, :3].min() > 240  # warm paper comes out white
    assert s[..., :3][s[..., 3] == 255].min() < 140  # the outline is still there


def test_run_writes_cutout_and_mask(tmp_path):
    cv2.imwrite(str(tmp_path / "drawing.jpg"), photo())
    assert cleanup.run(tmp_path) == {"cutout": "cutout.png", "mask": "mask.png"}
    assert cv2.imread(str(tmp_path / "cutout.png"), cv2.IMREAD_UNCHANGED).shape[2] == 4
    assert set(np.unique(cv2.imread(str(tmp_path / "mask.png"), cv2.IMREAD_GRAYSCALE))) == {0, 255}


def test_monster_1_real_photo():
    """Thin grey pen, shadow over the left half, gap at the left armpit, faint stroke on the head."""
    cut = cleanup.cutout(cv2.imread(str(FIXTURES / "monster-1.jpeg")))
    m = cut.mask
    assert cut.found
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    assert n == 2  # one piece: no shadow blobs, no floating eyes
    ys, xs = np.nonzero(m)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    at = lambda fx, fy: m[int(y0 + fy * (y1 - y0)), int(x0 + fx * (x1 - x0))]
    assert at(0.5, 0.55) == 1    # body (the armpit gap is closed)
    assert at(0.5, 0.15) == 1    # head (the faint stroke counts)
    assert at(0.95, 0.42) == 1   # right hand
    assert at(0.5, 0.9) == 0     # between the legs
    assert at(0.25, 0.2) == 0    # beside the head
