"""cutout.png -> print.3mf (artifact print_3mf): the faithful balloon, ready for a single-colour FDM
printer (Prusa MK3S+: 0.4 mm nozzle, PrusaSlicer). Two objects side by side, pick one in the slicer:

- standing: the whole balloon, HEIGHT_MM tall, its feet sunk into an oval plinth so it doesn't
  tip over. Arms usually need supports.
- lying: the front half on a thin base plate, printed on its back. No supports, hard to break.

One colour can't show the drawing, so its lines are engraved: thin dark strokes in the sticker
(the same black-hat idea as in cleanup), widened to what the nozzle can draw and softened so the
groove has sloped walls.
"""

import io
import zipfile
from pathlib import Path

import cv2
import numpy as np
from manifold3d import CrossSection, Manifold, Mesh

from .balloon import keep_largest, mirrored, sheet, world

HEIGHT_MM = 80.0     # creature height
SPACING = 2          # mesh point spacing in sticker pixels (finer than the 3D view: grooves)
ENGRAVE_MM = 0.6     # depth of the drawn lines
LINE_MM = 1.0        # engraved lines are at least about this wide
BASE_MM = 1.6        # lying: base plate under the front half
PLINTH_MM = 3.0      # standing: plinth thickness ...
SINK_MM = 2.0        # ... and how deep the feet sink into it
GAP_MM = 15.0        # between the two objects on the bed


def run(folder: Path) -> dict[str, str]:
    sticker = cv2.imread(str(folder / "cutout.png"), cv2.IMREAD_UNCHANGED)
    if sticker is None or sticker.ndim != 3 or sticker.shape[2] != 4:
        raise ValueError("cutout.png is missing or has no alpha")
    (folder / "print.3mf").write_bytes(print_3mf(sticker))
    return {"print_3mf": "print.3mf"}


def print_3mf(sticker: np.ndarray) -> bytes:
    mask = keep_largest((sticker[..., 3] >= 128).astype(np.uint8))
    standing, lying = print_meshes(sticker, mask)
    return write_3mf([("standing", *standing), ("lying", *lying)])


def print_meshes(sticker: np.ndarray, mask: np.ndarray):
    """((verts, tris) standing, (verts, tris) lying), millimetres, Z up, each on the bed (Z = 0)."""
    ys = np.nonzero(mask.any(axis=1))[0]
    px_per_mm = (ys.max() - ys.min() + 1) / HEIGHT_MM
    sh = sheet(mask, spacing=SPACING)
    groove = engraving(sticker, mask, px_per_mm)

    xi = np.clip(np.round(sh.pts[:, 0]).astype(int), 0, mask.shape[1] - 1)
    yi = np.clip(np.round(sh.pts[:, 1]).astype(int), 0, mask.shape[0] - 1)
    depth_px = groove[yi, xi] * ENGRAVE_MM * px_per_mm
    # never cut more than a third of the way to the middle: thin parts stay solid
    z = sh.height - np.minimum(depth_px, sh.height / 3)

    return standing_mesh(sh, z, mask), lying_mesh(sh, z, mask, px_per_mm)


def engraving(sticker: np.ndarray, mask: np.ndarray, px_per_mm: float) -> np.ndarray:
    """0..1 per sticker pixel: how deep to engrave. Thin dark strokes, widened and softened."""
    lum = cv2.cvtColor(sticker[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
    k = max(5, round(px_per_mm * 2)) | 1
    thin = cv2.morphologyEx(lum, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    lines = ((thin > 45) & (cv2.erode(mask, np.ones((3, 3), np.uint8)) > 0)).astype(np.uint8)
    r = max(1, round(LINE_MM * px_per_mm / 2 - 1))  # a pen line is ~2-3 px; grow it to LINE_MM
    lines = cv2.dilate(lines, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    return cv2.GaussianBlur(lines.astype(np.float32), (0, 0), max(0.8, px_per_mm * 0.15))


def to_bed(p: np.ndarray) -> np.ndarray:
    """Creature frame (Y up, front +Z) -> printer frame (Z up, front towards -Y): rotate about X."""
    return np.column_stack([p[:, 0], -p[:, 2], p[:, 1]])


def standing_mesh(sh, z, mask):
    xy, zz, faces = mirrored(sh, z)
    body = to_bed(world(xy, zz, mask, HEIGHT_MM))
    body[:, 2] += PLINTH_MM - SINK_MM

    # plinth: an oval around where the feet touch, at least 40% as deep as the creature is tall
    feet = body[body[:, 2] < PLINTH_MM + 2]
    x0, x1 = feet[:, 0].min(), feet[:, 0].max()
    width = x1 - x0 + 12
    depth = max(0.4 * HEIGHT_MM, np.ptp(feet[:, 1]) + 12)
    oval = CrossSection.circle(0.5, 96).scale((width, depth)).translate(((x0 + x1) / 2, feet[:, 1].mean()))
    plinth = Manifold.extrude(oval, PLINTH_MM)

    creature = Manifold(Mesh(vert_properties=np.ascontiguousarray(body, np.float32),
                             tri_verts=np.ascontiguousarray(faces, np.uint32)))
    if creature.status().name != "NoError":
        raise ValueError(f"balloon mesh is not printable: {creature.status()}")
    solid = (creature + plinth).to_mesh()
    return np.array(solid.vert_properties[:, :3], np.float32), np.array(solid.tri_verts, np.uint32)


def lying_mesh(sh, z, mask, px_per_mm):
    """Front half on a base plate: front surface, flat bottom, and a wall around the rim."""
    n = len(sh.pts)
    pts = np.vstack([sh.pts, sh.pts])
    zz = np.concatenate([z + BASE_MM * px_per_mm, np.zeros(n)])
    front = sh.front
    bottom = front[:, [0, 2, 1]] + n

    # the rim: edges used by only one front triangle, walled down to the bottom copy
    e = np.concatenate([front[:, [0, 1]], front[:, [1, 2]], front[:, [2, 0]]])
    key = np.sort(e, axis=1)
    _, inv, counts = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    rim = e[counts[inv.ravel()] == 1]
    a, b = rim[:, 0], rim[:, 1]
    walls = np.vstack([np.column_stack([b, a, a + n]), np.column_stack([b, a + n, b + n])])

    verts = world(pts, zz, mask, HEIGHT_MM)  # Y up, Z = height above the bed already
    return verts, np.vstack([front, bottom, walls])


def write_3mf(objects: list[tuple[str, np.ndarray, np.ndarray]]) -> bytes:
    """3MF (core spec) with one object per entry, placed side by side and resting on the bed."""
    parts, items, x = [], [], 0.0
    for i, (name, v, t) in enumerate(objects, start=1):
        v = np.asarray(v, np.float64)
        v = v - [v[:, 0].min() - x, v[:, 1].min(), v[:, 2].min()]
        x = v[:, 0].max() + GAP_MM
        vs = "".join(f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>' for a, b, c in v)
        ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in np.asarray(t))
        parts.append(f'<object id="{i}" name="{name}" type="model"><mesh><vertices>{vs}</vertices>'
                     f'<triangles>{ts}</triangles></mesh></object>')
        items.append(f'<item objectid="{i}"/>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<metadata name="Application">Monster Maker</metadata>'
             f'<resources>{"".join(parts)}</resources><build>{"".join(items)}</build></model>')
    types = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
             '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
    return buf.getvalue()
