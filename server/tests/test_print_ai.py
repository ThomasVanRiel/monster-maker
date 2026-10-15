import io
import json
import re
import struct
import zipfile
from collections import Counter

import numpy as np
from manifold3d import Manifold, Mesh

from monster.steps import balloon, print_ai, print_prep


def sphere(centre, r, n=24):
    """A UV sphere as a triangle soup: no shared vertices, like a mesh split at its texture seams."""
    th, ph = np.meshgrid(np.linspace(0, np.pi, n + 1), np.linspace(0, 2 * np.pi, 2 * n + 1), indexing="ij")
    p = np.stack([np.sin(th) * np.cos(ph), np.cos(th), np.sin(th) * np.sin(ph)], -1) * r + centre
    quads = [(p[i, j], p[i + 1, j], p[i + 1, j + 1], p[i, j + 1]) for i in range(n) for j in range(2 * n)]
    return np.array([t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))])


def box(lo, hi):
    lo, hi = np.array(lo, float), np.array(hi, float)
    c = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)]) * (hi - lo) + lo
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return np.array([t for a, b, cc, d in faces for t in ((c[a], c[b], c[cc]), (c[a], c[cc], c[d]))])


def messy_creature():
    """Like a TRELLIS result, metres, Y up, 0.2 m tall: a body and a head that overlap, a hole in
    the body, a paper-thin ear, a speck floating beside it."""
    body = sphere((0, 0.06, 0), 0.06)
    body = body[np.linalg.norm(body.mean(axis=1) - (0.06, 0.06, 0), axis=1) > 0.012]  # a hole on the side
    head = sphere((0, 0.15, 0), 0.05)
    ear = box((0.02, 0.18, -0.0002), (0.06, 0.2, 0.0002))   # 0.4 mm thick: 0.16 mm once printed
    speck = sphere((0, 0.1, 0.1), 0.004, n=6)  # in front: keeps the centring in x
    soup = np.concatenate([body, head, ear, speck])
    return soup.reshape(-1, 3), np.arange(len(soup) * 3).reshape(-1, 3)


def glb(verts, tris) -> bytes:
    v = verts.astype(np.float32)
    return balloon.write_glb(v, np.zeros_like(v), np.zeros((len(v), 2), np.float32),
                             tris.astype(np.uint32), b"\x89PNG\r\n\x1a\n")


def test_read_glb_applies_node_transforms():
    v, t = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32), np.array([[0, 1, 2]])
    data = glb(v, t)
    n = int.from_bytes(data[12:16], "little")
    gltf = json.loads(data[20:20 + n])
    gltf["nodes"] = [{"children": [1], "translation": [5, 0, 0]}, gltf["nodes"][0] | {"scale": [2, 2, 2]}]
    head = json.dumps(gltf).encode()
    head += b" " * (-len(head) % 4)
    body = data[20 + n:]
    data = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(head) + len(body)) + \
        struct.pack("<II", len(head), 0x4E4F534A) + head + body
    verts, tris = print_ai.read_glb(data)
    assert np.allclose(verts, [[5, 0, 0], [7, 0, 0], [5, 2, 0]]) and tris.tolist() == [[0, 1, 2]]


def test_messy_mesh_becomes_one_closed_solid_on_a_plinth():
    verts, tris = print_ai.print_mesh(*messy_creature())
    edges = Counter(tuple(sorted(e)) for t in tris for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])))
    assert set(edges.values()) == {2}
    m = Manifold(Mesh(vert_properties=np.ascontiguousarray(verts, np.float32),
                      tri_verts=np.ascontiguousarray(tris, np.uint32)))
    assert m.status().name == "NoError" and len(m.decompose()) == 1  # the speck is gone
    assert abs(verts[:, 2].min()) < 1e-3
    tall = verts[:, 2].max()
    assert abs(tall - (print_prep.HEIGHT_MM + print_prep.PLINTH_MM - print_prep.SINK_MM)) < 0.5
    assert np.ptp(verts[:, 1]) >= 0.4 * print_prep.HEIGHT_MM

    # 80 mm tall: body r 24 mm, head r 20 mm, 50 mm apart; the hole is closed, so the body is solid
    spheres = 4 / 3 * np.pi * (24 ** 3 + 20 ** 3)
    assert 0.9 * spheres < m.volume() < 1.3 * spheres
    # the ear is still there and thick enough to print: a cut through it is no thinner than ~1 mm
    ear = m.slice(print_prep.PLINTH_MM - print_prep.SINK_MM + 76)  # 76 mm up: ear, above the head
    xs = [p for poly in ear.to_polygons() for p in poly if p[0] > 13]  # head is 12 mm wide there
    assert xs, "the ear was lost"
    ys = np.array(xs)[:, 1]
    assert np.ptp(ys) > 0.9 * print_ai.MIN_WALL_MM


def test_run_writes_print_ai_3mf(tmp_path):
    (tmp_path / "ai.glb").write_bytes(glb(*messy_creature()))
    assert print_ai.run(tmp_path) == {"print_ai_3mf": "print_ai.3mf"}
    with zipfile.ZipFile(io.BytesIO((tmp_path / "print_ai.3mf").read_bytes())) as z:
        model = z.read("3D/3dmodel.model").decode()
    assert re.findall(r'<object id="\d+" name="(\w+)"', model) == ["standing"]
