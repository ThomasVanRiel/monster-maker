"""ai.glb -> print_ai.3mf (artifact print_ai_3mf): the AI version (TRELLIS.2, step ai3d) for the same
printer as print.3mf, standing on the same oval plinth. Offered beside the faithful print, never
instead of it.

TRELLIS meshes look closed but often aren't: small holes, seams split for the texture, shells that
overlap, specks floating beside the body. Rather than repair them, the shape is rebuilt:

1. Scale to HEIGHT_MM and turn it onto the bed, like the balloon.
2. Draw its surface into a voxel grid (VOXEL_MM, finer than the 0.4 mm nozzle).
3. Close gaps up to about 2 * CLOSE_MM. Inside is what the outside can't reach, plus what is walled
   in along 5 of the 6 axis directions: a bigger hole would otherwise leave the body hollow. Pockets
   open on one side only (a wide-open mouth) get filled too.
4. Thicken parts thinner than MIN_WALL_MM (ears, fingers, horns) so they print and don't snap.
5. Keep the largest piece: specks would only fall off.
6. Marching cubes on the lightly smoothed grid gives a new closed surface; simplify it.

One colour can't show the texture, so nothing is engraved.
"""

import json
import struct
from pathlib import Path

import numpy as np
from manifold3d import Manifold, Mesh
from scipy import ndimage
from skimage.measure import marching_cubes

from .print_prep import HEIGHT_MM, on_plinth, to_bed, write_3mf

VOXEL_MM = 0.3        # grid step
CLOSE_MM = 1.0        # holes and slits up to about twice this get closed
MIN_WALL_MM = 1.2     # thinner parts are thickened to about this
SIMPLIFY_MM = 0.05    # surface may move this much when simplified
MAX_VOXELS = 60e6     # bigger grids (very wide creatures) use coarser voxels: RAM on the home server


def run(folder: Path) -> dict[str, str]:
    verts, tris = read_glb((folder / "ai.glb").read_bytes())
    (folder / "print_ai.3mf").write_bytes(print_ai_3mf(verts, tris))
    return {"print_ai_3mf": "print_ai.3mf"}


def print_ai_3mf(verts: np.ndarray, tris: np.ndarray) -> bytes:
    return write_3mf([("standing", *print_mesh(verts, tris))])


def print_mesh(verts: np.ndarray, tris: np.ndarray):
    """(verts, tris) in mm, Z up, on the bed: the rebuilt creature on its plinth."""
    body, faces = rebuild(on_bed(verts), tris)
    return on_plinth(body, faces, "AI")


def on_bed(verts: np.ndarray) -> np.ndarray:
    """Model frame (Y up, front +Z, any size) -> mm on the bed: HEIGHT_MM tall, lowest point at Z = 0."""
    v = np.asarray(verts, np.float64)
    lo, hi = v.min(axis=0), v.max(axis=0)
    s = HEIGHT_MM / max(hi[1] - lo[1], 1e-12)
    v = (v - [(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2]) * s
    return to_bed(v)


def rebuild(verts: np.ndarray, tris: np.ndarray):
    """Any triangle soup -> one closed, thick-enough solid (verts, tris) in the same frame."""
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    voxel = max(VOXEL_MM, (np.prod(hi - lo) / MAX_VOXELS) ** (1 / 3))
    close, wall = CLOSE_MM / voxel, MIN_WALL_MM / 2 / voxel
    pad = int(np.ceil(close + wall)) + 3
    origin = lo - pad * voxel
    shape = tuple(np.ceil((hi - lo) / voxel).astype(int) + 2 * pad + 1)

    surface = np.zeros(shape, bool)
    for p in surface_points(verts, tris, voxel / 2):
        i = np.round((p - origin) / voxel).astype(np.intp)
        surface[i[:, 0], i[:, 1], i[:, 2]] = True

    # closing: grow the surface by `close`, fill what is enclosed, shrink back
    grown = ndimage.distance_transform_edt(~surface) <= close
    del surface
    walled = np.zeros(shape, np.uint8)  # in how many of the 6 axis directions the surface lies ahead
    for axis in range(3):
        walled += np.logical_or.accumulate(grown, axis=axis)
        walled += np.flip(np.logical_or.accumulate(np.flip(grown, axis), axis=axis), axis)
    grown |= walled >= 5
    del walled
    solid = ndimage.distance_transform_edt(ndimage.binary_fill_holes(grown)) > close
    del grown

    # thin parts: what an opening by `wall` removes gets grown by `wall`
    core = ndimage.distance_transform_edt(solid) > wall
    opened = ndimage.distance_transform_edt(~core) <= wall
    del core
    thin = solid & ~opened
    del opened
    if thin.any():
        solid |= ndimage.distance_transform_edt(~thin) <= wall
    del thin

    labels, n = ndimage.label(solid)
    if n == 0:
        raise ValueError("AI mesh has no volume")
    solid = labels == 1 + int(np.argmax(np.bincount(labels.ravel())[1:]))
    del labels

    field = ndimage.gaussian_filter(solid.astype(np.float32), 0.7)
    v, f, _, _ = marching_cubes(field, 0.5, spacing=(voxel,) * 3, allow_degenerate=False)
    v += origin
    m = Manifold(Mesh(vert_properties=np.ascontiguousarray(v, np.float32),
                      tri_verts=np.ascontiguousarray(f[:, [0, 2, 1]], np.uint32)))
    if m.status().name != "NoError":
        raise ValueError(f"rebuilt AI mesh is not closed: {m.status()}")
    m = m.simplify(SIMPLIFY_MM)
    out = m.to_mesh()
    v = np.array(out.vert_properties[:, :3], np.float64)
    v[:, 2] -= v[:, 2].min()  # smoothing lifts the feet a little
    return v, np.array(out.tri_verts, np.uint32)


def surface_points(verts: np.ndarray, tris: np.ndarray, step: float, batch: int = 4_000_000):
    """Points on every triangle, no two neighbours further apart than `step`, in batches."""
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    longest = np.max([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1),
                      np.linalg.norm(a - c, axis=1)], axis=0)
    yield verts
    splits = np.clip(np.ceil(longest / step), 1, 256).astype(int)
    for n in np.unique(splits):
        i, j = np.mgrid[0:n + 1, 0:n + 1]
        keep = i + j <= n
        u, w = i[keep] / n, j[keep] / n                        # barycentric weights of b and c
        sel = np.nonzero(splits == n)[0]
        per = max(1, batch // len(u))
        for k in range(0, len(sel), per):
            t = sel[k:k + per]
            yield (a[t, None] + u[None, :, None] * (b[t] - a[t])[:, None]
                   + w[None, :, None] * (c[t] - a[t])[:, None]).reshape(-1, 3)


def read_glb(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """All triangles of a binary glTF 2.0 scene in scene coordinates: (verts Nx3, tris Mx3)."""
    magic, version, _ = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2:
        raise ValueError("not a binary glTF 2.0 file")
    chunks, off = {}, 12
    while off < len(data):
        length, kind = struct.unpack_from("<II", data, off)
        chunks[kind] = data[off + 8: off + 8 + length]
        off += 8 + length
    gltf = json.loads(chunks[0x4E4F534A])
    binary = chunks.get(0x004E4942, b"")
    if gltf.get("extensionsRequired"):
        raise ValueError(f"unsupported glTF extensions: {gltf['extensionsRequired']}")

    def accessor(i: int) -> np.ndarray:
        acc = gltf["accessors"][i]
        view = gltf["bufferViews"][acc["bufferView"]]
        dtype = np.dtype({5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[acc["componentType"]])
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
        stride = view.get("byteStride") or dtype.itemsize * width
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        raw = np.frombuffer(binary, np.uint8, (acc["count"] - 1) * stride + dtype.itemsize * width, start)
        rows = np.lib.stride_tricks.as_strided(raw, (acc["count"], dtype.itemsize * width), (stride, 1))
        return np.ascontiguousarray(rows).view(dtype).reshape(acc["count"], width)

    def local(node: dict) -> np.ndarray:
        if "matrix" in node:
            return np.array(node["matrix"], np.float64).reshape(4, 4).T  # column-major
        x, y, z, w = node.get("rotation", (0, 0, 0, 1))
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m = np.eye(4)
        m[:3, :3] = r * np.array(node.get("scale", (1, 1, 1)))
        m[:3, 3] = node.get("translation", (0, 0, 0))
        return m

    verts, tris, count = [], [], 0

    def visit(i: int, parent: np.ndarray) -> None:
        nonlocal count
        node = gltf["nodes"][i]
        m = parent @ local(node)
        for prim in gltf["meshes"][node["mesh"]]["primitives"] if "mesh" in node else []:
            if prim.get("mode", 4) != 4:
                continue  # points and lines have no volume
            p = accessor(prim["attributes"]["POSITION"]).astype(np.float64)
            t = (accessor(prim["indices"]).ravel() if "indices" in prim else np.arange(len(p))).reshape(-1, 3)
            verts.append(p @ m[:3, :3].T + m[:3, 3])
            tris.append(t.astype(np.int64) + count)
            count += len(p)
        for child in node.get("children", []):
            visit(child, m)

    scene = gltf["scenes"][gltf.get("scene", 0)]
    for i in scene["nodes"]:
        visit(i, np.eye(4))
    if not tris:
        raise ValueError("glTF file has no triangles")
    return np.vstack(verts), np.vstack(tris)
