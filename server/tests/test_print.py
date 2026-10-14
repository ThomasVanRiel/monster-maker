import io
import re
import zipfile
from collections import Counter

import cv2
import numpy as np
from manifold3d import Manifold, Mesh

from monster.steps import print_prep
from test_balloon import sticker


def drawn_sticker():
    """The test sticker on white, with a dark pen line across the belly."""
    s = sticker()
    s[s[..., 3] == 255, :3] = 255
    cv2.line(s, (110, 230), (190, 230), (40, 40, 40, 255), 3)
    return s


def meshes():
    s = drawn_sticker()
    mask = (s[..., 3] >= 128).astype(np.uint8)
    return s, mask, print_prep.print_meshes(s, mask)


def test_both_versions_are_closed_solids_resting_on_the_bed():
    _, _, versions = meshes()
    for verts, tris in versions:
        edges = Counter(tuple(sorted(e)) for t in tris for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])))
        assert set(edges.values()) == {2}
        m = Manifold(Mesh(vert_properties=np.ascontiguousarray(verts, np.float32),
                          tri_verts=np.ascontiguousarray(tris, np.uint32)))
        assert m.status().name == "NoError" and m.volume() > 0
        assert abs(verts[:, 2].min()) < 1e-3


def test_standing_is_creature_height_on_a_plinth_and_lying_is_flat():
    _, _, ((sv, _), (lv, _)) = meshes()
    tall = sv[:, 2].max()
    assert abs(tall - (print_prep.HEIGHT_MM + print_prep.PLINTH_MM - print_prep.SINK_MM)) < 1
    assert np.ptp(sv[:, 1]) >= 0.4 * print_prep.HEIGHT_MM  # plinth deep enough not to tip over
    assert abs(np.ptp(lv[:, 1]) - print_prep.HEIGHT_MM) < 1 and lv[:, 2].max() < 25


def test_pen_line_is_engraved(monkeypatch):
    s, mask, (_, (lv, lt)) = meshes()
    groove = print_prep.engraving(s, mask, px_per_mm=mask.any(axis=1).sum() / print_prep.HEIGHT_MM)
    assert groove[230, 150] > 0.9 and groove[200, 150] < 0.05
    monkeypatch.setattr(print_prep, "ENGRAVE_MM", 0.0)
    _, _, (_, (flat, _)) = meshes()
    # same mesh points, so compare the top surface point by point with an unengraved version
    dz = flat[:, 2] - lv[:, 2]
    ys = np.nonzero(mask.any(axis=1))[0]
    line_y = (ys.max() - 230) * print_prep.HEIGHT_MM / len(ys)
    # the band must be wider than the mesh spacing (~0.4 mm here), or it holds no points at all
    # top surface only: the flat bottom plate has the same x/y and never moves
    on_line = (np.abs(lv[:, 1] - line_y) < 0.3) & (np.abs(lv[:, 0]) < 5) & (lv[:, 2] > print_prep.BASE_MM)
    assert on_line.sum() > 5
    assert dz[on_line].mean() > 0.4  # ENGRAVE_MM is 0.6, softened at the groove's edges
    far = np.abs(lv[:, 1] - line_y) > 5
    assert np.abs(dz[far]).max() < 1e-6  # nothing else moved


def test_3mf_holds_both_objects_in_millimetres():
    data = print_prep.print_3mf(drawn_sticker())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= set(z.namelist())
        model = z.read("3D/3dmodel.model").decode()
    assert 'unit="millimeter"' in model
    assert re.findall(r'<object id="\d+" name="(\w+)"', model) == ["standing", "lying"]
    assert model.count("<item ") == 2


def test_run_writes_print_3mf(tmp_path):
    cv2.imwrite(str(tmp_path / "cutout.png"), drawn_sticker())
    assert print_prep.run(tmp_path) == {"print_3mf": "print.3mf"}
    assert zipfile.is_zipfile(tmp_path / "print.3mf")
