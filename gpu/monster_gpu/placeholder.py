"""Stand-in for the AI 3D step: the drawing on a thin standing card, 20 cm tall. No model, no GPU,
standard library only. Lets the parent test the GPU round trip before TRELLIS is set up."""

import json
import struct
from pathlib import Path

HEIGHT_M = 0.20
THICK_M = 0.004


def run(inputs: dict[str, Path], out: Path) -> dict[str, str]:
    png = inputs["image"].read_bytes()
    (out / "ai.glb").write_bytes(card_glb(png))
    return {"mesh_ai": "ai.glb"}


def png_size(png: bytes) -> tuple[int, int]:
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("input is not a PNG")
    return struct.unpack(">II", png[16:24])


def card_glb(png: bytes) -> bytes:
    w, h = png_size(png)
    hw, t = HEIGHT_M * w / h / 2, THICK_M / 2
    # front (z+) and back (z-, mirrored, as seen through the paper); Y up, feet on the floor
    pos = [(-hw, 0, t), (hw, 0, t), (hw, HEIGHT_M, t), (-hw, HEIGHT_M, t),
           (hw, 0, -t), (-hw, 0, -t), (-hw, HEIGHT_M, -t), (hw, HEIGHT_M, -t)]
    nrm = [(0, 0, 1)] * 4 + [(0, 0, -1)] * 4
    uv = [(0, 1), (1, 1), (1, 0), (0, 0), (1, 1), (0, 1), (0, 0), (1, 0)]
    idx = [0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]

    def floats(rows):
        return b"".join(struct.pack("<%df" % len(r), *r) for r in rows)

    chunks = [floats(pos), floats(nrm), floats(uv), struct.pack("<12H", *idx), png]
    views, offset, binary = [], 0, b""
    for c in chunks:
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(c)})
        c += b"\0" * (-len(c) % 4)
        binary += c
        offset += len(c)
    gltf = {
        "asset": {"version": "2.0", "generator": "monster-maker placeholder"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                                    "indices": 3, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0,
                                                "roughnessFactor": 0.9},
                       "alphaMode": "MASK", "alphaCutoff": 0.5}],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9729}],
        "images": [{"bufferView": 4, "mimeType": "image/png"}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3",
             "min": [-hw, 0, -t], "max": [hw, HEIGHT_M, t]},
            {"bufferView": 1, "componentType": 5126, "count": 8, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": 8, "type": "VEC2"},
            {"bufferView": 3, "componentType": 5123, "count": 12, "type": "SCALAR"},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": len(binary)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body
