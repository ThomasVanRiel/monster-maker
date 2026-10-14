import json
import struct
import zlib

from monster_gpu import placeholder


def tiny_png(w, h) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\0" + b"\xff\x00\x00\xff" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_card_is_a_valid_glb_20cm_tall(tmp_path):
    (tmp_path / "in.png").write_bytes(tiny_png(30, 60))
    assert placeholder.run({"image": tmp_path / "in.png"}, tmp_path) == {"mesh_ai": "ai.glb"}
    glb = (tmp_path / "ai.glb").read_bytes()
    magic, version, length = struct.unpack("<III", glb[:12])
    assert magic == 0x46546C67 and version == 2 and length == len(glb)
    js_len = struct.unpack("<I", glb[12:16])[0]
    gltf = json.loads(glb[20:20 + js_len])
    lo, hi = gltf["accessors"][0]["min"], gltf["accessors"][0]["max"]
    assert abs(hi[1] - 0.20) < 1e-9 and lo[1] == 0 and abs((hi[0] - lo[0]) - 0.10) < 1e-9
