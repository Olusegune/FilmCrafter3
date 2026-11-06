"""The cutout studio on a real film folder: pictures brought in, a green-screen plate checked and keyed, the cutout exported as RGBA, composed onto another picture, rendered. Plates are synthetic
pictures with a known answer (see test_keying), saved as real PNG and JPG files."""
import json
import os
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import test_keying as TK  # noqa: E402
from filmcrafter_engine import bible, shots as S, story, vpstudio as V  # noqa: E402

SCRIPT = "INT. ROOM - DAY\n\nA small room.\n\nSARAH\nHello there.\n"


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def save(tmp_path, name, arr):
    p = str(tmp_path / name)
    Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)).save(p)
    return p


@pytest.fixture
def plate_png(tmp_path):
    plate, truth, colour = TK.make_plate(spill=1.0)
    return save(tmp_path, "plate.png", plate), truth, colour


def street(tmp_path, w=TK.W, h=TK.H):
    a = np.full((h, w, 3), [0.55, 0.5, 0.45], np.float32)
    a[: h // 2] = [0.4, 0.55, 0.75]
    return save(tmp_path, "street.jpg", a)


# ---------------------------------------------------------------- bringing pictures in

def test_a_picture_is_copied_in_once_and_the_original_is_untouched(film, plate_png):
    path, _, _ = plate_png
    before = open(path, "rb").read()
    r = V.import_source(film, {"path": path, "kind": "plate", "name": "  Sarah   on green "})
    s = r["sources"][0]
    assert s["kind"] == "plate" and s["name"] == "Sarah on green" and (s["width"], s["height"]) == (TK.W, TK.H) and r["already_there"] is False
    assert open(os.path.join(film, s["file"]), "rb").read() == before and open(path, "rb").read() == before
    again = V.import_source(film, {"path": path, "kind": "plate"})
    assert again["already_there"] is True and len(again["sources"]) == 1 and again["id"] == s["id"]
    assert len(V.import_source(film, {"path": path, "kind": "background"})["sources"]) == 2                    # the same picture as another kind is another entry


def test_pictures_that_cannot_be_used_are_refused(film, tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("hello")
    fake = tmp_path / "fake.png"
    fake.write_bytes(b"not a picture at all")
    for data, why in (({"path": ""}, "Choose a picture"), ({"path": str(tmp_path / "nope.png")}, "Choose a picture"), ({"path": str(txt)}, "PNG, JPG"), ({"path": str(fake)}, "could not be read")):
        with pytest.raises(SystemExit, match=why):
            V.import_source(film, data)
    assert V.get(film)["sources"] == []


def test_a_picture_too_big_is_refused(film, tmp_path, monkeypatch):
    p = save(tmp_path, "big.png", np.zeros((50, 50, 3), np.float32))
    monkeypatch.setattr(V, "MAX_SIDE", 40)
    with pytest.raises(SystemExit, match="limit is 40 pixels"):
        V.import_source(film, {"path": p})


def test_it_refuses_a_folder_that_is_not_a_film(tmp_path):
    with pytest.raises(SystemExit, match="isn't a FilmCrafter film"):
        V.get(str(tmp_path))


# ---------------------------------------------------------------- the key and the cutout

def test_a_plate_is_checked_before_it_is_keyed_and_nothing_is_saved_by_checking(film, plate_png):
    sid = V.import_source(film, {"path": plate_png[0]})["id"]
    before = open(os.path.join(film, "vp", "vp.json"), "rb").read()
    r = V.plate_check(film, sid)
    assert r["usable"] and r["screen"] == "green" and r["source"] == sid
    assert open(os.path.join(film, "vp", "vp.json"), "rb").read() == before
    with pytest.raises(SystemExit, match="virtual production folder"):
        V.plate_check(film, "vs-00000000")


def test_the_key_makes_a_real_rgba_png_and_a_mask_that_match_the_truth(film, plate_png):
    path, truth, colour = plate_png
    sid = V.import_source(film, {"path": path})["id"]
    r = V.key(film, {"source": sid, "name": "Sarah", "params": {"similarity": 0.06}})
    c = r["cutouts"][0]
    assert c["name"] == "Sarah" and c["source"] == sid and c["params"]["similarity"] == 0.06 and (c["width"], c["height"]) == (TK.W, TK.H)
    rgba = Image.open(os.path.join(film, c["rgba"]))
    mask = Image.open(os.path.join(film, c["mask"]))
    assert rgba.mode == "RGBA" and mask.mode == "L" and rgba.size == mask.size == (TK.W, TK.H)
    a = np.asarray(rgba)[..., 3] / 255.0
    assert float(np.abs(a - truth)[TK.edge_of(truth)].mean()) < 0.12 and (a[truth > 0.99] > 0.97).mean() > 0.97
    assert np.array_equal(np.asarray(mask), np.asarray(rgba)[..., 3])                                          # the mask is the transparency alone
    assert r["report"]["plate"]["usable"] and 0.2 < c["report"]["subject"] < 0.5 and c["report"]["edge_spill"] < 0.06
    assert open(path, "rb").read() == open(os.path.join(film, V.get(film)["sources"][0]["file"]), "rb").read()  # the plate is untouched


def test_keying_again_keeps_both_cutouts(film, plate_png):
    sid = V.import_source(film, {"path": plate_png[0]})["id"]
    a = V.key(film, {"source": sid, "name": "tight", "params": {"erode": 2}})["id"]
    b = V.key(film, {"source": sid, "name": "soft", "params": {"dilate": 3}})["id"]
    g = V.get(film)
    assert [c["id"] for c in g["cutouts"]] == [a, b] and g["cutouts"][0]["params"]["erode"] == 2 and g["cutouts"][1]["params"]["dilate"] == 3
    ma = np.asarray(Image.open(os.path.join(film, g["cutouts"][0]["mask"])), dtype=float).sum()
    mb = np.asarray(Image.open(os.path.join(film, g["cutouts"][1]["mask"])), dtype=float).sum()
    assert ma < mb                                                                                              # an eroded cutout is smaller than a grown one


def test_key_needs_a_known_source_and_clamps_wild_settings(film, plate_png):
    with pytest.raises(SystemExit, match="virtual production folder"):
        V.key(film, {"source": "vs-00000000"})
    sid = V.import_source(film, {"path": plate_png[0]})["id"]
    c = V.key(film, {"source": sid, "params": {"erode": 999, "similarity": "x", "screen": "red", "despill": 7}})["cutouts"][0]
    assert c["params"]["erode"] == 12 and c["params"]["similarity"] == 0.06 and c["params"]["screen"] == "green" and c["params"]["despill"] == 1.0


def test_a_bad_plate_still_keys_but_says_what_is_wrong(film, tmp_path):
    grey = save(tmp_path, "grey.png", np.full((TK.H, TK.W, 3), 0.5, np.float32))
    sid = V.import_source(film, {"path": grey})["id"]
    r = V.key(film, {"source": sid})
    assert not r["report"]["plate"]["usable"] and any("not a clear green or blue" in n for n in r["report"]["notes"])


def test_removing_a_cutout_moves_it_aside_keeps_its_files_and_takes_it_out_of_compositions(film, plate_png):
    sid = V.import_source(film, {"path": plate_png[0]})["id"]
    cid = V.key(film, {"source": sid})["id"]
    cp = V.compose_set(film, {"name": "A", "layers": [{"cutout": cid}]})["id"]
    r = V.cutout_remove(film, cid)
    assert r["cutouts"] == [] and r["compositions"][0]["layers"] == [] and r["compositions"][0]["id"] == cp
    saved = json.load(open(os.path.join(film, "vp", "vp.json"), encoding="utf-8"))
    assert saved["removed"][0]["kind"] == "cutout" and os.path.isfile(os.path.join(film, saved["removed"][0]["item"]["rgba"]))
    with pytest.raises(SystemExit, match="isn't in the film"):
        V.cutout_remove(film, cid)


# ---------------------------------------------------------------- export

def test_export_writes_a_real_rgba_png_and_a_mask_and_reads_them_back(film, plate_png):
    sid = V.import_source(film, {"path": plate_png[0]})["id"]
    cid = V.key(film, {"source": sid, "name": "Sarah / the *lead*?"})["id"]
    r = V.export(film, cid)
    assert r["has_alpha"] is True and 0.3 < r["transparent_share"] < 0.9
    for k in ("rgba", "mask"):
        assert os.path.isfile(os.path.join(film, r["files"][k])) and r["files"][k].startswith("exports/virtual-production/")
    assert Image.open(os.path.join(film, r["files"]["rgba"])).mode == "RGBA"
    assert all(ch not in os.path.basename(r["files"]["rgba"]) for ch in '/\\*?:"<>|') and "H.264" in r["note"]
    with pytest.raises(SystemExit, match="isn't in the film"):
        V.export(film, "cu-00000000")


# ---------------------------------------------------------------- compositions and the render

def test_a_cutout_goes_onto_a_different_background_and_the_render_is_a_real_picture(film, plate_png, tmp_path):
    path, truth, colour = plate_png
    plate = V.import_source(film, {"path": path})["id"]
    bg = V.import_source(film, {"path": street(tmp_path), "kind": "background"})["id"]
    cut = V.key(film, {"source": plate, "params": {"similarity": 0.06}})["id"]
    cp = V.compose_set(film, {"name": "Street", "background": bg, "size": [TK.W, TK.H], "layers": [{"cutout": cut, "x": 0.5, "y": 1.0, "scale": 1.0, "anchor": "bottom", "shadow": {"strength": 0.3}, "match": 0.2}]})["id"]
    r = V.render(film, cp)
    assert r["layers"] == 1 and r["missing"] == [] and (r["width"], r["height"]) == (TK.W, TK.H)
    out = np.asarray(Image.open(os.path.join(film, r["file"])).convert("RGB"), dtype=np.float32) / 255.0
    sky = out[10, 10]
    assert abs(sky[2] - 0.75) < 0.04 and abs(sky[0] - 0.4) < 0.04                                              # the new background, not the green
    far = out[5:60, 5:60]
    assert float(np.maximum(far[..., 1] - far[..., [0, 2]].mean(axis=-1), 0).mean()) < 0.1
    ys, xs = np.nonzero(truth > 0.99)
    centre = out[int(ys.mean()), int(xs.mean())]
    assert centre[0] > centre[2]                                                                               # the subject is there, in warm colours (skin or shirt), not the blue street
    assert V.get(film)["compositions"][0]["last_render"] == r["file"]


def test_a_render_with_no_background_uses_the_colour_and_a_moved_subject_moves(film, plate_png):
    sid = V.import_source(film, {"path": plate_png[0]})["id"]
    cut = V.key(film, {"source": sid, "params": {"similarity": 0.06}})["id"]
    cp = V.compose_set(film, {"background": None, "colour": [0, 0, 0], "size": [400, 300], "layers": [{"cutout": cut, "x": 0.25, "y": 1.0, "scale": 0.5}]})["id"]
    out = np.asarray(Image.open(os.path.join(film, V.render(film, cp)["file"])), dtype=np.float32)
    lit = out.sum(axis=-1) > 30
    ys, xs = np.nonzero(lit)
    assert abs(xs.mean() - 100) < 25 and ys.max() >= 295                                                       # at a quarter of the way across, standing on the bottom edge
    assert (lit.sum() / lit.size) < 0.2


def test_composition_settings_are_checked_and_limited(film, plate_png):
    sid = V.import_source(film, {"path": plate_png[0]})["id"]
    cut = V.key(film, {"source": sid})["id"]
    cp = V.compose_set(film, {"size": [999999, 2], "layers": [{"cutout": cut, "x": 99, "scale": 999, "rotation": 1e9, "opacity": -4, "match": 5, "shadow": {"strength": 9, "blur": -1, "squash": 0, "spread": 99}}]})
    comp = cp["compositions"][0]
    assert comp["size"] == [V.MAX_SIDE, 16] and comp["colour"] == [0.1, 0.1, 0.1]
    layer = comp["layers"][0]
    assert layer["x"] == 3.0 and layer["scale"] == 8.0 and layer["rotation"] == 360.0 and layer["opacity"] == 0.0 and layer["match"] == 1.0
    assert layer["shadow"] == {"strength": 1.0, "blur": 0.0, "squash": 0.05, "spread": 3.0}
    for data, why in (({"layers": [{"cutout": "cu-00000000"}]}, "isn't in the film"), ({"background": "../../etc/passwd"}, "virtual production folder"), ({"size": [5]}, "width and a height"),
                      ({"layers": [{"cutout": cut}] * (V.MAX_LAYERS + 1)}, "At most"), ({"id": "cp-00000000"}, "isn't in the film")):
        with pytest.raises(SystemExit, match=why):
            V.compose_set(film, data)
    assert len(V.get(film)["compositions"]) == 1


def test_a_composition_can_be_changed_in_place_and_removed_without_losing_it(film, plate_png):
    sid = V.import_source(film, {"path": plate_png[0]})["id"]
    cut = V.key(film, {"source": sid})["id"]
    cp = V.compose_set(film, {"name": "One", "layers": [{"cutout": cut}]})["id"]
    V.compose_set(film, {"id": cp, "name": "Two"})
    g = V.get(film)
    assert len(g["compositions"]) == 1 and g["compositions"][0]["name"] == "Two" and len(g["compositions"][0]["layers"]) == 1
    V.compose_remove(film, cp)
    assert V.get(film)["compositions"] == []
    assert json.load(open(os.path.join(film, "vp", "vp.json"), encoding="utf-8"))["removed"][0]["item"]["name"] == "Two"
    with pytest.raises(SystemExit, match="isn't in the film"):
        V.render(film, cp)


def test_a_render_survives_a_cutout_that_was_removed_after_it_was_placed(film, plate_png):
    sid = V.import_source(film, {"path": plate_png[0]})["id"]
    cut = V.key(film, {"source": sid})["id"]
    cp = V.compose_set(film, {"size": [64, 64], "layers": [{"cutout": cut}]})["id"]
    V.cutout_remove(film, cut)
    r = V.render(film, cp)
    assert r["layers"] == 0 and os.path.isfile(os.path.join(film, r["file"]))


# ---------------------------------------------------------------- the words for a plate, files from outside, damage

def test_the_plate_prompt_asks_for_a_clean_screen_and_sends_nothing():
    r = V.plate_prompt({"subject": "a woman in a red coat", "screen": "green", "framing": "half", "light": "left", "angle": "low", "movement": "turn"})
    assert r["sent"] is False and r["screen"] == "green"
    for w in ("a woman in a red coat", "waist up", "#00B140", "camera left", "low camera angle", "turns slowly", "No green in the subject"):
        assert w in r["prompt"]
    assert any("Check the screen" in n for n in r["notes"]) and any("blue screen" in n for n in r["notes"])
    blue = V.plate_prompt({"subject": "a robot", "screen": "blue", "junk": 1})
    assert "#0047BB" in blue["prompt"] and "No blue in the subject" in blue["prompt"]
    with pytest.raises(SystemExit, match="who or what"):
        V.plate_prompt({"subject": "  "})


def test_a_record_pointing_outside_the_film_is_never_followed(film, plate_png):
    sid = V.import_source(film, {"path": plate_png[0]})["id"]
    p = os.path.join(film, "vp", "vp.json")
    data = json.load(open(p, encoding="utf-8"))
    data["sources"][0]["file"] = "../../outside.png"
    json.dump(data, open(p, "w", encoding="utf-8"))
    with pytest.raises(SystemExit, match="not inside the film"):
        V.plate_check(film, sid)


def test_a_record_of_the_wrong_shape_is_refused_and_left_alone(film):
    p = os.path.join(film, "vp", "vp.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write('{"schema": 1, "sources": "junk"}')
    with pytest.raises(SystemExit, match="left untouched"):
        V.get(film)
    assert open(p, encoding="utf-8").read() == '{"schema": 1, "sources": "junk"}'


def test_the_command_line_answers_with_json(film, plate_png, capsys):
    assert V.main(["import", film, "--data", json.dumps({"path": plate_png[0]})]) == 0
    sid = V.get(film)["sources"][0]["id"]
    assert V.main(["plate_check", film, "--data", json.dumps({"source": sid})]) == 0
    assert V.main(["key", film, "--data", json.dumps({"source": sid})]) == 0
    assert V.main(["plate_prompt", film, "--data", json.dumps({"subject": "x"})]) == 0
    assert V.main(["key", film, "--data", json.dumps({"source": "vs-00000000"})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip().startswith("{")]
    assert [x["event"] for x in lines] == ["result"] * 4 + ["error"] and lines[1]["data"]["usable"] is True
