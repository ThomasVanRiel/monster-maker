import json
import struct
from collections import Counter

import cv2
import numpy as np

from monster.steps import balloon


def sticker(w=300, h=400) -> np.ndarray:
    """A BGRA sticker: an oval body with a bar for arms."""
    s = np.zeros((h, w, 4), np.uint8)
    cv2.ellipse(s, (w // 2, h // 2), (90, 150), 0, 0, 360, (40, 160, 230, 255), -1)
    cv2.rectangle(s, (20, 150), (w - 20, 185), (40, 160, 230, 255), -1)
    s[3, 3] = (46, 42, 59, 70)  # faint sticker outline outside the shape
    return s


def edges(faces):
    return Counter(tuple(sorted(e)) for f in faces for e in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])))


def test_mesh_is_closed_stands_on_the_floor_and_faces_forward():
    mask = (sticker()[..., 3] >= 128).astype(np.uint8)
    pos, uv, faces = balloon.balloon_mesh(mask)
    assert set(edges(faces).values()) == {2}  # every edge shared by two triangles: watertight
    assert abs(pos[:, 1].min()) < 1e-6 and abs(pos[:, 1].max() - balloon.HEIGHT_M) < 0.01
    assert pos[:, 2].max() > 0.02 and abs(pos[:, 2].max() + pos[:, 2].min()) < 1e-6  # puffy, symmetric
    assert uv.min() >= 0 and uv.max() <= 1
    n = balloon.vertex_normals(pos, faces)
    front = pos[:, 2] > pos[:, 2].max() * 0.9
    assert (n[front, 2] > 0.8).all()  # the front points at the viewer


def test_circle_inflates_to_a_flattened_hemisphere():
    m = np.zeros((201, 201), np.uint8)
    cv2.circle(m, (100, 100), 80, 1, -1)
    h = balloon.inflate(m)
    assert abs(h[100, 100] - 80) < 3  # sqrt(4f) of a disc is a hemisphere of the same radius
    assert h[100, 100] > h[100, 160] > h[100, 178] > 0


def test_glb_is_valid_binary_gltf_with_the_drawing_as_texture():
    glb = balloon.balloon_glb(sticker())
    magic, version, total = struct.unpack_from("<4sII", glb)
    assert (magic, version, total) == (b"glTF", 2, len(glb))
    jlen, jtype = struct.unpack_from("<I4s", glb, 12)
    assert jtype == b"JSON"
    doc = json.loads(glb[20:20 + jlen])
    blen, btype = struct.unpack_from("<I4s", glb, 20 + jlen)
    assert btype == b"BIN\0" and doc["buffers"][0]["byteLength"] <= blen
    binary = glb[28 + jlen:]
    for acc in doc["accessors"]:
        view = doc["bufferViews"][acc["bufferView"]]
        size = {"VEC3": 12, "VEC2": 8, "SCALAR": 4}[acc["type"]]
        assert acc["count"] * size == view["byteLength"]
        assert view["byteOffset"] % 4 == 0 and view["byteOffset"] + view["byteLength"] <= len(binary)
    img = doc["bufferViews"][doc["images"][0]["bufferView"]]
    tex = cv2.imdecode(np.frombuffer(binary[img["byteOffset"]:img["byteOffset"] + img["byteLength"]], np.uint8),
                       cv2.IMREAD_COLOR)
    assert tuple(tex[200, 150]) == (40, 160, 230)  # the drawing
    assert tuple(tex[3, 3]) == (255, 255, 255)     # outside the shape is white, not the dark outline


def test_run_writes_balloon_glb(tmp_path):
    cv2.imwrite(str(tmp_path / "cutout.png"), sticker())
    assert balloon.run(tmp_path) == {"mesh_faithful": "faithful.glb"}
    assert (tmp_path / "faithful.glb").read_bytes()[:4] == b"glTF"
