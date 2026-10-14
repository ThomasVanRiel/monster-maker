"""cutout.png -> faithful.glb (artifact mesh_faithful): the "faithful" 3D creature, the sticker puffed up like a balloon.
Also creature.png -> puffy.png (artifact puffy): the drawing shaded with the same heights, as if lit
from the top left. TRELLIS (the AI 3D step) reads shading as shape; given the flat drawing it
makes a flat card.

The shape is the sticker's opaque area, the drawing is its texture on the front and (mirrored,
as if seen through the paper) on the back. Nothing is invented.

Height: solve  laplace(f) = -1  inside the shape with f = 0 on the outline, then  h = sqrt(4 f).
For a disc that is exactly a hemisphere; thin limbs come out round without the ridges a plain
distance map gives. PUFF flattens it from a sphere towards a pillow.

Mesh: points along the outline (h = 0) plus a grid inside, Delaunay triangles kept where they lie
inside the shape. The back is a mirror copy sharing the outline points, so the mesh is closed
(printing needs that later).
"""

import json
import struct
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve
from scipy.spatial import Delaunay

HEIGHT_M = 0.20   # creature height in AR, metres
PUFF = 0.6        # 1 = round as a ball, smaller = flatter
SPACING = 4       # mesh point spacing in sticker pixels


def run(folder: Path) -> dict[str, str]:
    sticker = cv2.imread(str(folder / "cutout.png"), cv2.IMREAD_UNCHANGED)
    if sticker is None or sticker.ndim != 3 or sticker.shape[2] != 4:
        raise ValueError("cutout.png is missing or has no alpha")
    (folder / "faithful.glb").write_bytes(balloon_glb(sticker))
    produced = {"mesh_faithful": "faithful.glb"}
    creature = cv2.imread(str(folder / "creature.png"), cv2.IMREAD_UNCHANGED)
    if creature is None or creature.ndim != 3 or creature.shape[2] != 4:
        creature = sticker  # made before creature.png existed: shade the sticker, edge and all
    cv2.imwrite(str(folder / "puffy.png"), puffy(creature))
    produced["puffy"] = "puffy.png"
    return produced


LIGHT = np.array([-0.45, -0.55, 0.7]) / np.linalg.norm([-0.45, -0.55, 0.7])  # top left, towards us


def puffy(creature: np.ndarray, puff: float = PUFF) -> np.ndarray:
    """The creature (BGRA, alpha = mask) shaded like a balloon: soft light from the top left,
    darker towards the outline, a small highlight. Colours and lines stay the drawing's. BGRA."""
    mask = keep_largest((creature[..., 3] >= 128).astype(np.uint8))
    h = cv2.GaussianBlur(inflate(mask) * puff, (0, 0), 1.5)
    gy, gx = np.gradient(h)
    n = np.dstack([-gx, -gy, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    half = LIGHT + [0, 0, 1]
    half /= np.linalg.norm(half)
    diffuse = np.clip(n @ LIGHT, 0, 1)
    shine = np.clip(n @ half, 0, 1) ** 40
    rgb = creature[..., :3].astype(np.float32) / 255 * (0.35 + 0.75 * diffuse)[..., None] + 0.35 * shine[..., None]
    out = np.dstack([np.clip(rgb, 0, 1) * 255, mask * 255]).astype(np.uint8)
    out[mask == 0, :3] = 255
    return out


def balloon_glb(sticker: np.ndarray) -> bytes:
    mask = (sticker[..., 3] >= 128).astype(np.uint8)
    mask = keep_largest(mask)
    positions, uvs, faces = balloon_mesh(mask)
    # the rim samples the texture right at the edge, where shrinking the sticker blended in its
    # faint dark outline: keep the outside and the last pixels of the (white) sticker edge white
    texture = sticker[..., :3].copy()
    texture[cv2.erode(mask, np.ones((5, 5), np.uint8)) == 0] = 255
    png = cv2.imencode(".png", texture)[1].tobytes()
    return write_glb(positions, vertex_normals(positions, faces), uvs, faces, png)


def keep_largest(mask: np.ndarray) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    if n < 2:
        raise ValueError("empty sticker")
    return (labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)


def inflate(mask: np.ndarray) -> np.ndarray:
    """Height per pixel (in pixels): sqrt(4 f) with laplace(f) = -1 inside, f = 0 outside."""
    h, w = mask.shape
    inside = mask.astype(bool)
    inside[[0, -1], :] = False
    inside[:, [0, -1]] = False
    idx = np.full((h, w), -1, np.int64)
    n = int(inside.sum())
    idx[inside] = np.arange(n)
    ys, xs = np.nonzero(inside)
    rows, cols, vals = [np.arange(n)], [np.arange(n)], [np.full(n, 4.0)]
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nb = idx[ys + dy, xs + dx]
        ok = nb >= 0
        rows.append(np.arange(n)[ok])
        cols.append(nb[ok])
        vals.append(np.full(ok.sum(), -1.0))
    A = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)).tocsr()
    f = np.zeros((h, w))
    f[inside] = spsolve(A, np.ones(n))
    return np.sqrt(4 * np.maximum(f, 0))


def outline_points(mask: np.ndarray, spacing: float) -> np.ndarray:
    """Points every `spacing` pixels along every outline (outer and holes), as (x, y)."""
    contours, _ = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    pts = []
    for c in contours:
        c = c.reshape(-1, 2).astype(np.float64)
        if len(c) < 3 * spacing:
            continue
        seg = np.linalg.norm(np.diff(np.vstack([c, c[:1]]), axis=0), axis=1)
        arc = np.concatenate([[0], np.cumsum(seg)])
        total = arc[-1]
        at = np.arange(0, total, total / max(3, round(total / spacing)))
        loop = np.vstack([c, c[:1]])
        pts.append(np.column_stack([np.interp(at, arc, loop[:, 0]), np.interp(at, arc, loop[:, 1])]))
    return np.vstack(pts)


@dataclass
class Sheet:
    """One side of the balloon, in sticker pixels: the first n_rim points lie on the outline."""
    pts: np.ndarray      # (N, 2) x, y
    n_rim: int
    front: np.ndarray    # (M, 3) triangles, oriented so the front faces +Z with Y up
    height: np.ndarray   # (N,) puffed height, 0 on the rim


def sheet(mask: np.ndarray, spacing: int = SPACING, puff: float = PUFF) -> Sheet:
    """Spacing is whole pixels: the outline points must not be denser than the grid inside, or
    runs of rim-only triangles appear and dropping them tears the surface."""
    h, w = mask.shape
    height = inflate(mask) * puff

    rim = outline_points(mask, spacing)
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    gy, gx = np.mgrid[spacing // 2:h:spacing, spacing // 2:w:spacing]
    gx, gy = gx.ravel(), gy.ravel()
    keep = dist[gy, gx] > spacing * 0.6  # not too close to the rim, or slivers appear
    inner = np.column_stack([gx[keep], gy[keep]]).astype(np.float64)

    pts = np.vstack([rim, inner])
    tri = Delaunay(pts).simplices
    # keep triangles inside the shape: centroid and edge midpoints on the mask
    inside = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    def on(p):
        x = np.clip(np.round(p[:, 0]).astype(int), 0, w - 1)
        y = np.clip(np.round(p[:, 1]).astype(int), 0, h - 1)
        return inside[y, x] > 0
    a, b, c = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
    ok = on((a + b + c) / 3) & on((a + b) / 2) & on((b + c) / 2) & on((c + a) / 2)
    # a triangle of three rim points is flat at z = 0 and would exist twice, front and back;
    # without it the neighbouring front and back triangles meet and the mesh stays closed
    n_rim = len(rim)
    ok &= (tri >= n_rim).any(axis=1)
    tri = tri[ok]

    z = np.zeros(len(pts))
    xi = np.clip(np.round(inner[:, 0]).astype(int), 0, w - 1)
    yi = np.clip(np.round(inner[:, 1]).astype(int), 0, h - 1)
    z[n_rim:] = height[yi, xi]

    # orient towards +Z (image y points down, so check the sign in world XY)
    ax, ay = pts[tri[:, 1]] - pts[tri[:, 0]], pts[tri[:, 2]] - pts[tri[:, 0]]
    cross = ax[:, 0] * -ay[:, 1] - (-ax[:, 1]) * ay[:, 0]
    front = np.where((cross > 0)[:, None], tri, tri[:, [0, 2, 1]])
    return Sheet(pts, n_rim, front, z)


def mirrored(sh: Sheet, z: np.ndarray):
    """Close a sheet with its mirror image. (xy, zz, faces): the back copies the inner points
    with -z, the rim points are shared."""
    n = len(sh.pts)
    back_of = np.arange(n)
    back_of[sh.n_rim:] = n + np.arange(n - sh.n_rim)
    xy = np.vstack([sh.pts, sh.pts[sh.n_rim:]])
    zz = np.concatenate([z, -z[sh.n_rim:]])
    faces = np.vstack([sh.front, back_of[sh.front[:, [0, 2, 1]]]])
    return xy, zz, faces


def world(xy: np.ndarray, zz: np.ndarray, mask: np.ndarray, height: float) -> np.ndarray:
    """Pixels -> world units, scaled so the shape is `height` tall, feet at Y = 0, centred in X."""
    ys = np.nonzero(mask.any(axis=1))[0]
    xs = np.nonzero(mask.any(axis=0))[0]
    scale = height / (ys.max() - ys.min() + 1)
    cx = (xs.min() + xs.max()) / 2
    return np.column_stack([(xy[:, 0] - cx) * scale, (ys.max() - xy[:, 1]) * scale, zz * scale])


def balloon_mesh(mask: np.ndarray):
    """(positions Nx3 metres, uvs Nx2, faces Mx3) of the closed balloon. Y up, front faces +Z."""
    h, w = mask.shape
    sh = sheet(mask)
    xy, zz, faces = mirrored(sh, sh.height)
    positions = world(xy, zz, mask, HEIGHT_M)
    uvs = np.column_stack([(xy[:, 0] + 0.5) / w, (xy[:, 1] + 0.5) / h])
    return positions.astype(np.float32), uvs.astype(np.float32), faces.astype(np.uint32)


def vertex_normals(positions: np.ndarray, faces: np.ndarray) -> np.ndarray:
    p = positions.astype(np.float64)
    fn = np.cross(p[faces[:, 1]] - p[faces[:, 0]], p[faces[:, 2]] - p[faces[:, 0]])  # area-weighted
    vn = np.zeros_like(p)
    for k in range(3):
        np.add.at(vn, faces[:, k], fn)
    vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
    return vn.astype(np.float32)


def write_glb(positions, normals, uvs, faces, png: bytes) -> bytes:
    """A single textured mesh as binary glTF 2.0."""
    chunks, views = [], []

    def add(data: bytes, target: int | None = None) -> int:
        offset = sum(len(c) for c in chunks)
        chunks.append(data + b"\0" * (-len(data) % 4))
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        views.append(view)
        return len(views) - 1

    ARRAY, ELEMENTS, FLOAT, UINT = 34962, 34963, 5126, 5125
    pos_v = add(positions.tobytes(), ARRAY)
    nrm_v = add(normals.tobytes(), ARRAY)
    uv_v = add(uvs.tobytes(), ARRAY)
    idx_v = add(faces.ravel().tobytes(), ELEMENTS)
    img_v = add(png)
    gltf = {
        "asset": {"version": "2.0", "generator": "monster-maker balloon"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "creature"}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
            "indices": 3, "material": 0}]}],
        "materials": [{
            "name": "drawing",
            "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0, "roughnessFactor": 0.85},
        }],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}],
        "images": [{"bufferView": img_v, "mimeType": "image/png"}],
        "accessors": [
            {"bufferView": pos_v, "componentType": FLOAT, "count": len(positions), "type": "VEC3",
             "min": positions.min(0).tolist(), "max": positions.max(0).tolist()},
            {"bufferView": nrm_v, "componentType": FLOAT, "count": len(normals), "type": "VEC3"},
            {"bufferView": uv_v, "componentType": FLOAT, "count": len(uvs), "type": "VEC2"},
            {"bufferView": idx_v, "componentType": UINT, "count": faces.size, "type": "SCALAR"},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": sum(len(c) for c in chunks)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    binary = b"".join(chunks)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
            + struct.pack("<I4s", len(binary), b"BIN\0") + binary)
