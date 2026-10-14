from pathlib import Path

import cv2
import numpy as np
import pytest

from monster.steps import cleanup

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def photo(outline=True, gap=0, shadow=False, tilt=0.0, ruled=None, slant=0) -> np.ndarray:
    """A grey table with a slightly warm sheet of paper and an ellipse 'monster' drawn on it."""
    h, w = 1200, 900
    img = np.full((h, w, 3), (70, 90, 110), np.uint8)  # brownish table
    sheet = np.zeros((h, w), np.uint8)
    corners = np.array([[120, 100], [780, 100 + tilt * 660], [780, 1100], [120, 1100 - tilt * 660]], np.int32)
    cv2.fillConvexPoly(sheet, corners, 1)
    img[sheet > 0] = (215, 222, 230)
    if ruled:  # light blue lines every 30 px as on a school pad, squared: also down; slant px drop
        for y in range(130, 1100, 30):
            cv2.line(img, (120, y), (780, y + slant), (225, 185, 160), 2)
        for x in range(150, 780, 30) if ruled == "squared" else ():
            cv2.line(img, (x, 100), (x, 1100), (225, 185, 160), 2)
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


@pytest.mark.parametrize("kwargs", [{"ruled": "lined"}, {"ruled": "squared"}, {"ruled": "lined", "slant": 25}],
                         ids=["lined", "squared", "slanted"])
def test_ruled_pad_lines_are_paper_not_ink(kwargs):
    cut = cleanup.cutout(photo(**kwargs))
    assert cut.found
    inside, outside = centre_and_outside(cut.mask)
    assert inside == 1 and outside == 0
    assert 0.17 < cut.mask.mean() < 0.30
    s = cut.sticker
    h, w = s.shape[:2]
    assert s[h // 2 - 40:h // 2 + 40, w // 2, :3].min() > 240  # no blue lines across the belly
    assert s[..., :3][s[..., 3] == 255].min() < 140  # the outline is still there


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


def test_run_writes_cutout_mask_and_creature(tmp_path):
    cv2.imwrite(str(tmp_path / "drawing.jpg"), photo())
    assert cleanup.run(tmp_path) == {"cutout": "cutout.png", "mask": "mask.png", "creature": "creature.png"}
    assert cv2.imread(str(tmp_path / "cutout.png"), cv2.IMREAD_UNCHANGED).shape[2] == 4
    mask = cv2.imread(str(tmp_path / "mask.png"), cv2.IMREAD_GRAYSCALE)
    assert set(np.unique(mask)) == {0, 255}
    creature = cv2.imread(str(tmp_path / "creature.png"), cv2.IMREAD_UNCHANGED)
    # the creature alone: same pixel count as the mask (no sticker edge), white where it is clear
    assert creature.shape[2] == 4 and (creature[..., 3] == 255).sum() == (mask == 255).sum()
    assert creature[0, 0, 3] == 0 and creature[0, 0, :3].min() == 255


def lines_through(cut) -> int:
    """How many printed lines of the pad were found running through the creature."""
    rows = np.nonzero(((cut.debug["rules"] > 0) & (cut.mask > 0)).sum(axis=1) > 10)[0]
    return 0 if len(rows) == 0 else 1 + int((np.diff(rows) > 2).sum())


def grey_paper(cut) -> float:
    """Share of the paper inside the sticker (away from the pen) that isn't white: ruling showing through."""
    s = cut.sticker
    g = s[..., :3].min(axis=2)
    near_pen = cv2.dilate((g < 200).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    inner = cv2.erode((s[..., 3] == 255).astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    return float((g[inner & ~near_pen] < 252).mean())


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
    assert not (cut.debug["rules"] & m).any()  # plain paper: no pen stroke taken for a ruled line


def test_monster_2_lined_pad_with_printed_logos():
    """Blue pen on a ruled pad with two printed logos in the header, on a wooden desk."""
    cut = cleanup.cutout(cv2.imread(str(FIXTURES / "monster-2.jpeg")))
    m = cut.mask
    assert cut.found
    n, _, _, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    assert n == 2  # just the zebra: the logos are dropped, the ruled lines never count as ink
    ys, xs = np.nonzero(m)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    assert y0 > 0.2 * m.shape[0]  # nothing from the header
    at = lambda fx, fy: m[int(y0 + fy * (y1 - y0)), int(x0 + fx * (x1 - x0))]
    assert at(0.55, 0.55) == 1   # belly, between the stripes
    assert at(0.8, 0.12) == 1    # head
    assert at(0.95, 0.6) == 0    # beside the mane
    assert lines_through(cut) >= 12  # the ruled lines across the zebra are found ...
    assert grey_paper(cut) < 0.003  # ... and gone from the sticker, soft edges and all


def test_keep_creature_drops_far_pieces_and_keeps_near_ones():
    m = np.zeros((400, 400), np.uint8)
    cv2.circle(m, (200, 250), 80, 1, -1)       # the creature
    cv2.circle(m, (300, 250), 12, 1, -1)       # a hand drawn just beside it
    cv2.rectangle(m, (20, 20), (120, 40), 1, -1)  # a printed logo in the corner
    kept = cleanup.keep_creature(m)
    assert kept[250, 200] == 1 and kept[250, 300] == 1 and kept[30, 70] == 0
