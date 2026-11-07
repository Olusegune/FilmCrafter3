"""The guided set for a place, on a real film folder: from the place's pictures, from a 3D model, from a Blender file and made in Blender. The Blender tests run only where a real Blender is installed (they are skipped,
not faked, elsewhere)."""
import json
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from filmcrafter_engine import bible, blenderbridge as BB, placeset as P, shots as S, story, worldlock as WL  # noqa: E402
from glbtools import cube_faces, glb  # noqa: E402

SCRIPT = "INT. KITCHEN - DAY\n\nSARAH stirs a pot.\n\nSARAH\nBreakfast is ready.\n"
HAS_BLENDER = BB.status()["found"]
needs_blender = pytest.mark.skipif(not HAS_BLENDER, reason="Blender is not installed here")


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def place_of(d):
    return bible.load(d)["environments"][0]["id"]


def picture(tmp_path, n="bg.png", size=(800, 450), colour=(90, 120, 160)):
    p = str(tmp_path / n)
    Image.new("RGB", size, colour).save(p)
    return p


def cube(tmp_path, n="room.glb", size=2.0):
    p = str(tmp_path / n)
    open(p, "wb").write(glb(cube_faces(size)))
    return p


def test_status_says_what_to_do_first_with_no_pictures_and_with_pictures(film, tmp_path):
    pid = place_of(film)
    s = P.status(film, pid)
    assert s["set"] is None and s["pictures"] == 0 and "Add a picture" in s["next"]
    bible.add_media(film, "environment", pid, picture(tmp_path), "Reference", "master")
    s = P.status(film, pid)
    assert s["pictures"] == 1 and "Make a set from this place's pictures" in s["next"]


def test_from_pictures_refuses_with_no_pictures_and_otherwise_stands_them_in_a_set(film, tmp_path):
    pid = place_of(film)
    with pytest.raises(SystemExit, match="Add a picture to this place first"):
        P.from_pictures(film, pid)
    assert WL.list_sets(film)["sets"] == []                                 # nothing half-made is left behind
    bible.add_media(film, "environment", pid, picture(tmp_path), "Reference", "master")
    bible.add_media(film, "environment", pid, picture(tmp_path, "b.png", (400, 400), (200, 80, 80)), "Reference", "reference")
    r = P.from_pictures(film, pid)
    assert r["set"]["mode"] == "pictures" and r["set"]["pictures"] == 2 and r["set"]["cameras"] == 1
    s = WL.get(film, r["set"]["id"])
    assert s["name"] == bible.load(film)["environments"][0]["name"]
    back = next(a for a in s["assets"] if a["name"] == "Backdrop")
    assert back["z"] == 14 and back["y"] == 0 and back["height"] == 7.2
    assert s["ground"]["visible"] is True
    with pytest.raises(SystemExit, match="already has a set"):
        P.from_pictures(film, pid)


def test_the_view_from_the_camera_actually_shows_the_picture(film, tmp_path):
    pid = place_of(film)
    bible.add_media(film, "environment", pid, picture(tmp_path, colour=(90, 120, 160)), "Reference", "master")
    P.from_pictures(film, pid)
    v = P.preview(film, pid)
    im = Image.open(os.path.join(film, *v["file"].split("/"))).convert("RGB")
    w, h = im.size
    r, g, b = im.getpixel((w // 2, int(h * 0.3)))
    assert abs(r - 90) < 25 and abs(g - 120) < 25 and abs(b - 160) < 25    # the picture's blue, high in the frame (the backdrop stands on the floor)


def test_from_model_stands_it_ahead_of_the_camera_on_the_ground(film, tmp_path):
    pid = place_of(film)
    r = P.from_model(film, pid, cube(tmp_path))
    assert r["set"]["mode"] == "model" and r["set"]["models"] == 1
    s = WL.get(film, r["set"]["id"])
    m = s["models"][0]
    assert s["ground"]["visible"] is True
    (x0, y0, z0), (x1, y1, z1) = m["summary"]["bbox"]
    assert abs(m["x"] + (x0 + x1) / 2) < 1e-6 and abs(m["y"] + y0) < 1e-6 and abs(m["z"] + z0 - 4.0) < 1e-6
    with pytest.raises(SystemExit, match="Choose a .glb"):
        P.unlink(film, pid) and P.from_model(film, pid, str(tmp_path / "nope.glb"))


def test_a_bad_model_leaves_no_link_behind(film, tmp_path):
    pid = place_of(film)
    bad = str(tmp_path / "bad.glb")
    open(bad, "wb").write(b"not a model")
    with pytest.raises(SystemExit):
        P.from_model(film, pid, bad)
    assert P.status(film, pid)["set"] is None


def test_unlink_keeps_the_set_and_lets_the_place_have_another(film, tmp_path):
    pid = place_of(film)
    P.from_model(film, pid, cube(tmp_path))
    first = WL.list_sets(film)["sets"]
    assert len(first) == 1
    assert P.unlink(film, pid)["set"] is None
    assert len(WL.list_sets(film)["sets"]) == 1                              # nothing deleted
    bible.add_media(film, "environment", pid, picture(tmp_path), "Reference", "master")
    assert P.from_pictures(film, pid)["set"]["mode"] == "pictures"
    assert len(WL.list_sets(film)["sets"]) == 2


def test_an_unknown_place_is_refused(film):
    with pytest.raises(SystemExit, match="Choose a place"):
        P.status(film, "e_nope")


def test_without_blender_the_blender_ways_say_so(film, tmp_path, monkeypatch):
    monkeypatch.setattr(BB, "status", lambda: {"found": False, "path": "", "version": "", "note": ""})
    pid = place_of(film)
    with pytest.raises(SystemExit, match="Blender was not found"):
        P.blender_new(film, pid)
    f = str(tmp_path / "x.blend")
    open(f, "wb").write(b"BLENDER")
    with pytest.raises(SystemExit, match="Blender was not found"):
        P.from_blend(film, pid, f)
    assert P.status(film, pid)["set"] is None and WL.list_sets(film)["sets"] == []


def test_a_non_blend_file_is_refused_before_blender_is_started(film, tmp_path):
    pid = place_of(film)
    f = str(tmp_path / "x.txt")
    open(f, "w").write("x")
    with pytest.raises(SystemExit, match="Choose a Blender"):
        P.from_blend(film, pid, f)


@needs_blender
def test_made_in_blender_and_brought_back_keeps_the_place_in_the_set(film, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "open_blender", lambda *a, **k: {"opened": "skipped"})        # the test must not open a window
    pid = place_of(film)
    r = P.blender_new(film, pid)
    assert r["set"]["mode"] == "blender" and r["set"]["blend_saved"] and r["set"]["models"] == 0
    r = P.bring_back(film, pid)
    assert r["set"]["models"] == 1
    s = WL.get(film, r["set"]["id"])
    m = s["models"][0]
    assert m["summary"]["triangles"] > 0 and abs(m["summary"]["size"][0] - 12) < 0.5          # the blank file's 12 m floor, read back through a real Blender
    WL.model_set(film, s["id"], {"id": m["id"], "x": 3.0})
    r = P.bring_back(film, pid)                                                         # again: the new model replaces the old and keeps where it stood
    s = WL.get(film, r["set"]["id"])
    assert len(s["models"]) == 1 and s["models"][0]["x"] == 3.0
    assert P.preview(film, pid)["file"].endswith(".png")


@needs_blender
def test_a_blend_file_becomes_a_set_and_the_original_is_untouched(film, tmp_path):
    pid = place_of(film)
    src = str(tmp_path / "mine.blend")
    script = str(tmp_path / "mk.py")
    open(script, "w").write(P.BLANK_SCRIPT)
    import subprocess
    subprocess.run([BB.status()["path"], "-b", "--factory-startup", "-P", script, "--", src], check=True, capture_output=True, timeout=120)
    before = os.path.getsize(src), os.path.getmtime(src)
    r = P.from_blend(film, pid, src)
    assert r["set"]["mode"] == "blender" and r["set"]["models"] == 1
    assert (os.path.getsize(src), os.path.getmtime(src)) == before
    assert json.load(open(os.path.join(film, "worldlock", "place_sets.json")))[pid]["from_file"] == "mine.blend"
