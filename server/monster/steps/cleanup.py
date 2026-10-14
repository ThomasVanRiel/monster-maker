"""Photo -> cutout.png (RGBA, white sticker edge) + mask.png.

Port of segment() and processPhoto() in prototype/index.html, plus a perspective crop to the
paper in front of it:

1. find the paper (Otsu split, largest bright region, holes filled) and straighten it
2. even out the lighting (per-block paper brightness, spread, bilinear per pixel)
3. ink = clearly darker than the local paper, or clearly coloured
4. drop specks
5. close outline gaps, flood from the border; what the outside can't reach is the creature
6. whiten the paper inside the mask, keep crayon colours, add a white sticker edge
7. nothing found: a soft rounded window in the middle of the photo
"""

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

WORK_MAX = 800    # working resolution, as in the prototype
OUT_MAX = 440     # longest side of the final sticker
OUTLINE = (59, 42, 46)  # BGR of the prototype's ink colour #2E2A3B
CROSS = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
PAPER_STEP = 3    # max colour step between neighbouring pixels while growing the paper
INK_DARK = 0.78   # ink: darker than this fraction of the local paper brightness ...
INK_FAINT = 0.90  # ... or this, when connected to the darker ink and thin
INK_CONTRAST = 1.6  # exponent on (pixel / paper) when whitening
PAPER_WHITE = 0.93  # paper at this fraction of its local 90th percentile already counts as white


@dataclass
class Cutout:
    sticker: np.ndarray            # BGRA
    mask: np.ndarray               # uint8 0/1, working resolution (after the perspective crop)
    found: bool                    # False when the fallback window was used
    debug: dict[str, np.ndarray] = field(default_factory=dict)


def run(folder: Path) -> dict[str, str]:
    """Reads folder/drawing.jpg, writes cutout.png and mask.png. Returns {kind: filename}."""
    src = cv2.imread(str(folder / "drawing.jpg"), cv2.IMREAD_COLOR)
    if src is None:
        raise ValueError("drawing.jpg is missing or unreadable")
    cut = cutout(src)
    cv2.imwrite(str(folder / "mask.png"), cut.mask * 255)
    cv2.imwrite(str(folder / "cutout.png"), cut.sticker)
    return {"cutout": "cutout.png", "mask": "mask.png"}


def cutout(src: np.ndarray) -> Cutout:
    h0, w0 = src.shape[:2]
    s = min(1.0, WORK_MAX / max(w0, h0))
    img = cv2.resize(src, (max(1, round(w0 * s)), max(1, round(h0 * s))), interpolation=cv2.INTER_AREA)
    debug = {"photo": img}

    paper = find_paper(img)
    debug["paper"] = paper * 255
    quad = paper_quad(paper)
    if quad is not None:
        img = warp_to_quad(img, quad)
        paper = np.ones(img.shape[:2], np.uint8)
        debug["straightened"] = img

    mask = segment(img, paper, debug)
    h, w = img.shape[:2]
    found = w * h * 0.003 < mask.sum() < w * h * 0.92
    if found:
        img = whiten(img, paper)
    else:
        mask = fallback_mask(h, w)
    debug["mask"] = mask * 255
    return Cutout(make_sticker(img, mask), mask, found, debug)


# 1. the paper ---------------------------------------------------------------------------------

def luminance(img: np.ndarray) -> np.ndarray:
    b, g, r = (img[..., i].astype(np.float32) for i in range(3))
    return 0.299 * r + 0.587 * g + 0.114 * b


def find_paper(img: np.ndarray) -> np.ndarray:
    """The sheet the drawing is on, holes filled. uint8 0/1; the whole photo if no sheet is found.

    A global threshold splits a sheet with a shadow on it in two, so this grows the paper from
    a bright seed near the middle instead: neighbour-to-neighbour steps tolerate soft shading,
    the sharp edge of the sheet stops it. Ink is wiped out first with a grey closing.
    """
    h, w = img.shape[:2]
    k = max(5, round(min(w, h) / 50)) | 1
    smooth = cv2.morphologyEx(img, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    smooth = cv2.medianBlur(smooth, 5)

    lum = luminance(smooth)
    # brightest of a 5x5 grid around the middle, so a dark scribble at the centre isn't the seed
    grid = [(round(w * (0.25 + x / 12)), round(h * (0.25 + y / 12))) for x in range(1, 6) for y in range(1, 6)]
    seed = max(grid, key=lambda p: lum[p[1], p[0]])

    fill = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (1 << 8)
    cv2.floodFill(smooth, fill, seed, 0, (PAPER_STEP,) * 3, (PAPER_STEP,) * 3, flags)
    paper = fill[1:-1, 1:-1]
    paper = 1 - flood_from_border(1 - paper)
    if paper.sum() < 0.2 * w * h:
        return np.ones((h, w), np.uint8)
    return paper


def paper_quad(paper: np.ndarray) -> np.ndarray | None:
    """Four corners (tl, tr, br, bl) of the paper if it looks like a sheet, else None."""
    h, w = paper.shape
    contours, _ = cv2.findContours(paper, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    hull = cv2.convexHull(max(contours, key=cv2.contourArea))
    quad = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
    if len(quad) != 4 or not cv2.isContourConvex(quad):
        return None
    # a real sheet: big, convex, and the quad hugs it. A wrong warp bends the drawing, so when
    # in doubt don't straighten at all.
    area, paper_area = cv2.contourArea(quad), int(paper.sum())
    if area < 0.2 * w * h or paper_area < 0.95 * cv2.contourArea(hull) or abs(area - paper_area) > 0.04 * area:
        return None
    pts = quad.reshape(4, 2).astype(np.float32)
    total, diff = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[total.argmin()], pts[diff.argmin()], pts[total.argmax()], pts[diff.argmax()]])


def warp_to_quad(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = quad
    w = round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    h = round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32)
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(quad, dst), (w, h),
                               flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


# 2-5. segmentation ----------------------------------------------------------------------------

def segment(img: np.ndarray, paper: np.ndarray, debug: dict | None = None):
    """Creature mask, uint8 0/1 (all zero when nothing was found)."""
    debug = {} if debug is None else debug
    h, w = paper.shape
    lum = luminance(img)
    chroma = (img.max(axis=2).astype(np.int16) - img.min(axis=2)).astype(np.float32)

    # keep away from the paper's edge, where shadows and the table look like ink
    er = max(3, round(min(w, h) / 120))
    region = cv2.erode(paper, CROSS, iterations=er, borderType=cv2.BORDER_CONSTANT, borderValue=0)

    light = paper_light(lum, paper)
    debug["light"] = light.astype(np.uint8)

    # clearly darker than the paper, or clearly coloured. Lightly pressed stretches of a line are
    # kept too, where they connect to clearly dark ink (hysteresis, as in Canny) and are thin:
    # the black-hat only sees thin dark strokes, so a shadow next to the outline stays out.
    colour = (chroma > 48) & (lum < light * 0.97)
    strong = (region > 0) & ((lum < light * INK_DARK) | colour)
    k = max(7, round(min(w, h) / 45)) | 1
    thin = cv2.morphologyEx(lum, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    weak = strong | ((region > 0) & (thin > light * (1 - INK_FAINT)))
    ink = keep_touching(weak.astype(np.uint8), strong)
    debug["ink"] = ink * 255

    ink = drop_specks(ink, max(20, round(w * h * 0.00015)))
    debug["ink_clean"] = ink * 255

    return keep_creature(fill_outline(ink, paper, debug))


def keep_creature(mask: np.ndarray) -> np.ndarray:
    """The biggest shape plus pieces close to it. Printed headers, logos and doodles elsewhere on
    the sheet are dark ink too; a creature drawn in a few nearby parts stays whole."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 2:
        return mask
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    reach = max(3, round(min(mask.shape) * 0.04))
    near = cv2.dilate((labels == biggest).astype(np.uint8), cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * reach + 1, 2 * reach + 1)))
    keep = np.zeros(n, bool)
    keep[np.unique(labels[(near > 0) & (labels > 0)])] = True
    return keep[labels].astype(np.uint8)


def fill_outline(ink: np.ndarray, paper: np.ndarray, debug: dict) -> np.ndarray:
    """Close gaps in the outline, flood from the border; what the outside can't reach is the creature.

    Kids leave gaps. Wider closings bridge them, but also glue arms to bodies, so take the
    smallest closing that encloses nearly as much as the widest one. The closing grows the
    shape by g, so shrink it back afterwards and keep the ink itself.
    """
    h, w = ink.shape
    g0 = max(2, round(min(w, h) / 220))
    tries = []
    for g in (g0, 2 * g0, 3 * g0, 4 * g0):
        closed = cv2.dilate(ink, CROSS, iterations=g)
        tries.append((g, (1 - flood_from_border(1 - closed)) & paper))
    most = max(int(f.sum()) for _, f in tries)
    g, filled = next((g, f) for g, f in tries if f.sum() >= 0.8 * most)
    debug["closing"] = np.full((h, w), g * 255 // (4 * g0), np.uint8)
    tight = cv2.erode(filled, CROSS, iterations=g)
    return (tight | (ink & filled)).astype(np.uint8)


def paper_light(lum: np.ndarray, paper: np.ndarray) -> np.ndarray:
    """Paper brightness per pixel: 90th percentile per block, spread by one 3x3 max, bilinear."""
    h, w = lum.shape
    B = max(6, round(min(w, h) / 30))
    bh, bw = -(-h // B), -(-w // B)
    blk = np.full((bh, bw), -1, np.float32)
    for by in range(bh):
        for bx in range(bw):
            sl = (slice(by * B, (by + 1) * B), slice(bx * B, (bx + 1) * B))
            vals = lum[sl][paper[sl] > 0]
            if vals.size:
                blk[by, bx] = np.floor(np.percentile(vals, 90))
    blk = cv2.dilate(blk, np.ones((3, 3), np.uint8), iterations=1, borderType=cv2.BORDER_REPLICATE)
    blk[blk < 0] = 230
    # bilinear: pixel centre x+.5 lands on block coordinate (x+.5)/B - .5, clamped at the edges
    fy = np.clip((np.arange(h) + 0.5) / B - 0.5, 0, bh - 1)
    fx = np.clip((np.arange(w) + 0.5) / B - 0.5, 0, bw - 1)
    mx, my = np.meshgrid(fx.astype(np.float32), fy.astype(np.float32))
    return cv2.remap(blk, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def keep_touching(candidates: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """The 8-connected components of `candidates` that contain at least one seed pixel."""
    _, labels = cv2.connectedComponents(candidates, connectivity=8)
    hit = np.zeros(labels.max() + 1, bool)
    hit[np.unique(labels[seeds & (candidates > 0)])] = True
    hit[0] = False
    return hit[labels].astype(np.uint8)


def drop_specks(ink: np.ndarray, min_area: int) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=4)
    keep = stats[:, cv2.CC_STAT_AREA] >= min_area
    keep[0] = False
    return keep[labels].astype(np.uint8)


def flood_from_border(passable: np.ndarray) -> np.ndarray:
    """Pixels of `passable` reachable (4-connected) from the image border. uint8 0/1."""
    _, labels = cv2.connectedComponents(passable.astype(np.uint8), connectivity=4)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    edge = edge[edge > 0]
    return np.isin(labels, edge).astype(np.uint8)


# 6-7. whitening, sticker and fallback -----------------------------------------------------------

def whiten(img: np.ndarray, paper: np.ndarray) -> np.ndarray:
    """White-balance against the local paper, per channel, so the sheet comes out white whatever
    the room light, and crayon keeps its colour relative to it. A mild curve on the ratio to the
    paper puts back the contrast the camera lost: a pen line looks like a pen line again.
    """
    out = np.empty_like(img)
    for c in range(3):
        ch = img[..., c].astype(np.float32)
        ratio = np.clip(ch / np.maximum(60, PAPER_WHITE * paper_light(ch, paper)), 0, 1)
        out[..., c] = np.round(255 * ratio**INK_CONTRAST).astype(np.uint8)
    return out


def fallback_mask(h: int, w: int) -> np.ndarray:
    """Superellipse window, 72% of the photo, centred (prototype: rx = ry = 0.36)."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = (x - w / 2) / (w * 0.36)
    dy = (y - h / 2) / (h * 0.36)
    return ((dx**4 + dy**4) < 1).astype(np.uint8)


def make_sticker(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Crop to the mask, add a white border with a faint dark outline, scale down. BGRA out."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("empty mask")
    pad = 3
    h, w = mask.shape
    x0, x1 = max(0, xs.min() - pad), min(w - 1, xs.max() + pad)
    y0, y1 = max(0, ys.min() - pad), min(h - 1, ys.max() + pad)
    crop, m = img[y0:y1 + 1, x0:x1 + 1], mask[y0:y1 + 1, x0:x1 + 1]
    ch, cw = m.shape

    r = max(5, round(min(cw, ch) * 0.035))
    off = r + 2
    canvas_m = np.zeros((ch + 2 * off, cw + 2 * off), np.uint8)
    canvas_m[off:off + ch, off:off + cw] = m
    disk = lambda rad: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rad + 1, 2 * rad + 1))
    white = cv2.dilate(canvas_m, disk(r))
    outline = cv2.dilate(canvas_m, disk(r + 2))

    out = np.zeros((*canvas_m.shape, 4), np.uint8)
    out[outline > 0] = (*OUTLINE, round(255 * 0.28))
    out[white > 0] = (255, 255, 255, 255)
    inside = canvas_m > 0
    out[off:off + ch, off:off + cw][m > 0, :3] = crop[m > 0]
    out[inside, 3] = 255

    q = min(1.0, OUT_MAX / max(out.shape[:2]))
    if q < 1:
        out = cv2.resize(out, (max(1, round(out.shape[1] * q)), max(1, round(out.shape[0] * q))),
                         interpolation=cv2.INTER_AREA)
    return out
