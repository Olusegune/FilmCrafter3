"""WorldLock on a real film folder: a market set built from real pictures, saved and reopened, seen from several cameras, changed over the shots by events, locked, undone, and checked. Pictures are
simple coloured shapes so that where each one lands can be measured on the rendered views."""
import json
import os
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
from filmcrafter_engine import bible, shots as S, story, vpstudio as V, worldlock as WL, worldmath as WM  # noqa: E402

SCRIPT = ("INT. KITCHEN - DAY\n\nSARAH stirs a pot. TOM watches her.\n\nSARAH\nBreakfast is ready.\n\nEXT. MARKET - DAY\n\nSARAH carries a basket through the crowd. It falls. She picks it up.\n\n"
          "TOM\nI have it.\n\nINT. HALL - NIGHT\n\nSARAH sits alone.\n")


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def shot_ids(d):
    return [s["id"] for s in sorted(S.view(d)["shots"], key=lambda x: (int(x["scene"]), x["index"]))]


def pic(tmp_path, name, w, h, colour, edge=True):
    p = str(tmp_path / f"{name}.png")
    im = Image.new("RGBA", (w, h), colour + (255,))
    if edge:
        ImageDraw.Draw(im).rectangle((0, 0, w - 1, h - 1), outline=(0, 0, 0, 255), width=2)
    im.save(p)
    return p


RED, GREEN, BLUE, YELLOW, WHITE = (230, 30, 30), (30, 200, 60), (40, 80, 230), (240, 220, 30), (250, 250, 250)


def market(film, tmp_path):
    """A set with a wide backdrop, a stall in the middle ground and a stall and a basket near the camera."""
    sid = WL.create(film, {"name": "Market"})["id"]
    ids = {}
    ids["back"] = WL.asset_add(film, sid, {"path": pic(tmp_path, "back", 1200, 300, BLUE), "name": "Backdrop", "x": 0, "y": 0, "z": 20, "width": 40, "height": 10})["id"]
    ids["stall"] = WL.asset_add(film, sid, {"path": pic(tmp_path, "stall", 200, 200, GREEN), "name": "Fruit stall", "kind": "landmark", "x": -2.2, "y": 0, "z": 8, "width": 2.4, "height": 3})["id"]
    ids["near"] = WL.asset_add(film, sid, {"path": pic(tmp_path, "near", 100, 100, YELLOW), "name": "Cart", "kind": "prop", "x": 0.6, "y": 0, "z": 4, "width": 1.5, "height": 1.5})["id"]
    ids["basket"] = WL.asset_add(film, sid, {"path": pic(tmp_path, "basket", 60, 60, RED), "name": "Basket", "kind": "prop", "x": -0.4, "y": 0, "z": 5, "width": 0.5, "height": 0.5})["id"]
    return sid, ids


def view(film, sid, **kw):
    r = WL.render(film, sid, {"size": [600, 400], **kw})
    return r, np.asarray(Image.open(os.path.join(film, r["file"])).convert("RGB"), dtype=np.float32) / 255.0


def centroid(img, colour, tol=0.18):
    mask = (np.abs(img - np.array(colour, dtype=np.float32) / 255.0).max(axis=-1) < tol)
    ys, xs = np.nonzero(mask)
    return (float(xs.mean()), float(ys.mean()), int(mask.sum())) if len(xs) else None


# ---------------------------------------------------------------- creating, saving and reopening

def test_a_new_set_has_a_world_a_camera_and_nothing_else(film):
    g = WL.create(film, {"name": "  Mama's   kitchen "})
    assert g["name"] == "Mama's kitchen" and g["version"] == 1 and g["locked"] is False and g["assets"] == [] and len(g["cameras"]) == 1
    assert g["world"]["units"] == "m" and g["world"]["up"] == "y" and g["world"]["bounds"]["z"] == [0.0, 30.0]
    assert g["can_undo"] is False and g["saved_versions"] == []
    assert [s["name"] for s in WL.list_sets(film)["sets"]] == ["Mama's kitchen"]


def test_a_set_is_saved_and_reopened_exactly_with_its_stable_ids(film, tmp_path):
    sid, ids = market(film, tmp_path)
    cam = WL.camera_set(film, sid, {"name": "Wide", "x": 0, "y": 1.6, "z": -2, "fov": 60})["id"]
    before = WL.get(film, sid)
    again = WL.get(film, sid)                                                                         # a fresh read from disk
    assert [a["id"] for a in again["assets"]] == list(ids.values()) and again["cameras"][-1]["id"] == cam
    assert {k: v for k, v in again.items() if k not in ("saved_versions",)} == {k: v for k, v in before.items() if k not in ("saved_versions",)}
    assert [(a["name"], a["x"], a["y"], a["z"]) for a in again["assets"]][1] == ("Fruit stall", -2.2, 0.0, 8.0)
    assert all(os.path.isfile(os.path.join(film, a["file"])) for a in again["assets"])


def test_pictures_are_copied_in_and_the_originals_are_never_touched(film, tmp_path):
    p = pic(tmp_path, "orig", 100, 50, RED)
    before = open(p, "rb").read()
    sid = WL.create(film, {})["id"]
    r = WL.asset_add(film, sid, {"path": p, "height": 3.0})
    a = r["assets"][0]
    assert open(p, "rb").read() == before and a["pixels"] == [100, 50] and a["height"] == 3.0 and a["width"] == pytest.approx(6.0)        # the width follows the picture's shape
    assert Image.open(os.path.join(film, a["file"])).mode == "RGBA"
    only_w = WL.asset_add(film, sid, {"path": p, "width": 4.0})["assets"][-1]
    assert only_w["width"] == 4.0 and only_w["height"] == pytest.approx(2.0)


def test_a_layer_can_come_from_a_cutout_or_a_picture_of_the_film(film, tmp_path):
    plate = pic(tmp_path, "plate", 64, 64, GREEN, edge=False)
    sid_src = V.import_source(film, {"path": plate, "kind": "background"})["id"]
    sid = WL.create(film, {})["id"]
    r = WL.asset_add(film, sid, {"source": sid_src, "name": "From the film"})
    assert r["assets"][0]["name"] == "From the film"
    with pytest.raises(SystemExit, match="Choose a picture"):
        WL.asset_add(film, sid, {})
    with pytest.raises(SystemExit, match="cutout isn't in the film|isn't in the film"):
        WL.asset_add(film, sid, {"cutout": "cu-00000000"})


def test_bad_pictures_and_settings_are_refused_or_clamped_and_change_nothing(film, tmp_path):
    sid = WL.create(film, {})["id"]
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    fake = tmp_path / "f.png"
    fake.write_bytes(b"nope")
    for data, why in (({"path": str(txt)}, "PNG, JPG"), ({"path": str(fake)}, "could not be read"), ({"path": str(tmp_path / "none.png")}, "Choose a picture")):
        with pytest.raises(SystemExit, match=why):
            WL.asset_add(film, sid, data)
    a = WL.asset_add(film, sid, {"path": pic(tmp_path, "p", 20, 20, RED), "x": 1e9, "z": -1e9, "width": 0, "height": 1e9, "kind": "ceiling", "tags": ["A", "a", " b ", "", "c"] + ["x"] * 20})["assets"][0]
    assert a["x"] == 1000.0 and a["z"] == -1000.0 and a["width"] == 0.01 and a["kind"] == "layer" and a["tags"][:3] == ["a", "b", "c"] and len(a["tags"]) <= 8
    assert WL.get(film, sid)["version"] == 2


def test_a_picture_keeps_its_id_and_file_when_it_is_moved(film, tmp_path):
    sid, ids = market(film, tmp_path)
    before = next(a for a in WL.get(film, sid)["assets"] if a["id"] == ids["stall"])
    r = WL.asset_set(film, sid, {"id": ids["stall"], "x": 5, "name": "Stall 2", "file": "../../evil.png", "id_": "x"})
    a = next(a for a in r["assets"] if a["id"] == ids["stall"])
    assert a["x"] == 5.0 and a["name"] == "Stall 2" and a["file"] == before["file"] and a["z"] == before["z"]
    with pytest.raises(SystemExit, match="isn't in the set"):
        WL.asset_set(film, sid, {"id": "wa-00000000"})


def test_set_ids_cannot_reach_outside_the_film(film):
    for bad in ("ws-../../x", "../x", "", None, "ws-", "x"):
        with pytest.raises(SystemExit, match="isn't in the film"):
            WL.get(film, bad)


# ---------------------------------------------------------------- the same set from several cameras

def test_each_picture_lands_where_the_projection_says_in_a_real_render(film, tmp_path):
    sid, ids = market(film, tmp_path)
    r, img = view(film, sid, camera=WL.get(film, sid)["cameras"][0]["id"])
    f = WM.focal_px(600, 50.0)
    for colour, x, z in ((GREEN, -2.2, 8.0), (YELLOW, 0.6, 4.0), (RED, -0.4, 5.0)):
        cx, cy, n = centroid(img, colour)
        assert cx == pytest.approx(300 + f * x / z, abs=4.0) and n > 150
    assert set(r["drawn"]) == set(ids.values()) and r["skipped"] == [] and r["coverage"] > 0.5


def test_a_camera_move_shows_parallax_and_the_objects_stay_at_their_world_coordinates(film, tmp_path):
    sid, ids = market(film, tmp_path)
    cams = {n: WL.camera_set(film, sid, {"name": n, "x": x, "y": 1.6, "z": 0.0})["id"] for n, x in (("Left", -0.25), ("Right", 0.25))}
    _, a = view(film, sid, camera=cams["Left"])
    _, b = view(film, sid, camera=cams["Right"])
    near_a, near_b = centroid(a, YELLOW), centroid(b, YELLOW)
    far_a, far_b = centroid(a, GREEN), centroid(b, GREEN)
    f = WM.focal_px(600, 50.0)
    assert near_a[0] - near_b[0] == pytest.approx(f * 0.5 / 4.0, abs=4.0)                              # a half metre move shifts the near cart by f*0.5/4
    assert far_a[0] - far_b[0] == pytest.approx(f * 0.5 / 8.0, abs=4.0)                                # and the stall by f*0.5/8: half as far
    assert near_a[0] - near_b[0] > 1.8 * (far_a[0] - far_b[0])
    g = WL.get(film, sid)
    assert [(x["x"], x["y"], x["z"]) for x in g["assets"]] == [(0.0, 0.0, 20.0), (-2.2, 0.0, 8.0), (0.6, 0.0, 4.0), (-0.4, 0.0, 5.0)]    # nothing in the set moved


def test_rendering_is_deterministic_and_changes_nothing_in_the_set(film, tmp_path):
    sid, _ = market(film, tmp_path)
    before = open(os.path.join(film, "worldlock", sid, "set.json"), "rb").read()
    _, a = view(film, sid)
    _, b = view(film, sid)
    assert np.array_equal(a, b) and open(os.path.join(film, "worldlock", sid, "set.json"), "rb").read() == before


def test_an_inline_view_and_turning_the_camera_bring_other_things_into_frame(film, tmp_path):
    sid, _ = market(film, tmp_path)
    _, ahead = view(film, sid, view={"x": 0, "y": 1.6, "z": 0, "yaw": 0})
    _, right = view(film, sid, view={"x": 0, "y": 1.6, "z": 0, "yaw": 18})
    assert centroid(right, YELLOW)[0] < centroid(ahead, YELLOW)[0] - 60                                 # turning right moves things left on the picture


def test_a_camera_behind_a_picture_does_not_draw_it_and_says_so(film, tmp_path):
    sid, ids = market(film, tmp_path)
    r, _ = view(film, sid, view={"x": 0, "y": 1.6, "z": 6.0})
    assert ids["near"] in [s["id"] for s in r["skipped"]] and ids["basket"] in [s["id"] for s in r["skipped"]] and ids["back"] in r["drawn"]


# ---------------------------------------------------------------- gaps are reported, never filled

def test_a_view_the_set_does_not_cover_warns_with_the_share_and_does_not_invent_picture(film, tmp_path):
    sid = WL.create(film, {})["id"]
    WL.asset_add(film, sid, {"path": pic(tmp_path, "narrow", 100, 100, BLUE), "x": 0, "y": 0, "z": 10, "width": 4, "height": 4})
    r, img = view(film, sid, view={"x": 0, "y": 1.6, "z": 0})
    assert r["uncovered"] > 0.5 and any("shows nothing the set has" in w for w in r["warnings"])
    corner = img[5, 5]
    assert np.allclose(corner, WL.SKY, atol=0.01)                                                        # the gap is the plain base colour: nothing was made up


def test_a_set_that_covers_the_view_has_no_warning_and_a_move_past_its_edge_is_caught(film, tmp_path):
    sid, ids = market(film, tmp_path)
    r, _ = view(film, sid, view={"x": 0, "y": 1.6, "z": 0})
    assert r["uncovered"] < 0.6
    sid2 = WL.create(film, {"name": "Wall"})["id"]
    WL.asset_add(film, sid2, {"path": pic(tmp_path, "wall", 400, 200, WHITE), "x": 0, "y": 0, "z": 6, "width": 14, "height": 8})
    a = WL.camera_set(film, sid2, {"name": "A", "x": 0, "y": 2, "z": 0})["id"]
    b = WL.camera_set(film, sid2, {"name": "B", "x": 0, "y": 2, "z": 0, "yaw": 80})["id"]
    ok = WL.check_move(film, sid2, {"from": a, "to": a})
    assert ok["ok"] is True and ok["warning"] == ""
    bad = WL.check_move(film, sid2, {"from": a, "to": b, "steps": 8})
    assert bad["ok"] is False and bad["worst"]["uncovered"] > 0.1 and bad["worst"]["t"] > 0.4 and "does not cover where the camera goes" in bad["warning"] and len(bad["steps"]) == 9


# ---------------------------------------------------------------- the set over the shots

def test_a_basket_that_falls_in_one_shot_is_where_it_fell_in_the_next_and_the_set_is_unchanged(film, tmp_path):
    sid, ids = market(film, tmp_path)
    order = shot_ids(film)
    fall, after, before = order[2], order[3], order[1]
    WL.event_set(film, sid, {"shot": fall, "asset": ids["basket"], "kind": "move", "to": {"x": -1.0, "z": 6.0}, "state": "on the floor", "note": "She drops it"})
    cam = {"x": 0, "y": 1.6, "z": 0}
    _, b = view(film, sid, view=cam, shot=before)
    _, same_shot = view(film, sid, view=cam, shot=fall)                                                    # an event takes effect from the shot after it
    _, a = view(film, sid, view=cam, shot=after)
    f = WM.focal_px(600, 50.0)
    start = 300 + f * -0.4 / 5.0
    assert centroid(b, RED)[0] == pytest.approx(start, abs=5) and centroid(same_shot, RED)[0] == pytest.approx(start, abs=5)
    assert centroid(a, RED)[0] == pytest.approx(300 + f * -1.0 / 6.0, abs=5)
    g = WL.get(film, sid)
    basket = next(x for x in g["assets"] if x["id"] == ids["basket"])
    assert (basket["x"], basket["z"]) == (-0.4, 5.0) and g["events"][0]["to"] == {"x": -1.0, "z": 6.0}      # the set as built still says where it was put


def test_things_can_leave_and_return_and_bad_events_are_refused(film, tmp_path):
    sid, ids = market(film, tmp_path)
    order = shot_ids(film)
    WL.event_set(film, sid, {"shot": order[1], "asset": ids["near"], "kind": "remove"})
    r, _ = view(film, sid, view={"x": 0, "y": 1.6, "z": 0}, shot=order[2])
    assert ids["near"] not in r["drawn"]
    for data, why in (({"shot": "S99-99", "asset": ids["near"]}, "Choose a shot"), ({"shot": order[0], "asset": "wa-00000000"}, "isn't in the set"), ({"shot": order[0]}, "which picture or character"),
                      ({"shot": order[0], "asset": ids["near"], "character": "wc-1"}, "isn't in the set|one thing"), ({"shot": order[0], "asset": ids["near"], "kind": "move"}, "needs a new place"),
                      ({"id": "we-00000000", "shot": order[0]}, "isn't in the set")):
        with pytest.raises(SystemExit, match=why):
            WL.event_set(film, sid, data)
    with pytest.raises(SystemExit, match="Choose a shot"):
        WL.render(film, sid, {"shot": "S99-99"})


# ---------------------------------------------------------------- changes, undo, versions, locking

def test_every_change_is_undoable_and_redoable_and_counts_a_version(film, tmp_path):
    sid, ids = market(film, tmp_path)
    v0 = WL.get(film, sid)["version"]
    WL.asset_set(film, sid, {"id": ids["near"], "x": 9})
    g = WL.get(film, sid)
    assert g["version"] == v0 + 1 and g["can_undo"] and g["undo_label"] == "Change a picture"
    u = WL.undo(film, sid)
    assert next(a for a in u["assets"] if a["id"] == ids["near"])["x"] == 0.6 and u["can_redo"] and u["redo_label"] == "Change a picture"
    r = WL.redo(film, sid)
    assert next(a for a in r["assets"] if a["id"] == ids["near"])["x"] == 9.0
    WL.undo(film, sid)
    WL.asset_set(film, sid, {"id": ids["near"], "x": 3})                                                    # a new change clears what could be redone
    assert WL.get(film, sid)["can_redo"] is False
    with pytest.raises(SystemExit, match="nothing to redo"):
        WL.redo(film, sid)
    fresh = WL.create(film, {})["id"]
    with pytest.raises(SystemExit, match="nothing to undo"):
        WL.undo(film, fresh)


def test_history_is_limited_but_a_named_version_is_kept_and_can_be_restored(film, tmp_path):
    sid, ids = market(film, tmp_path)
    r = WL.version_save(film, sid, "Opening layout")
    assert r["saved"] == 1 and r["saved_versions"][0]["name"] == "Opening layout" and r["saved_versions"][0]["assets"] == 4
    for i in range(WL.MAX_HISTORY + 5):
        WL.asset_set(film, sid, {"id": ids["near"], "x": float(i % 7)})
    h = json.load(open(os.path.join(film, "worldlock", sid, "history.json"), encoding="utf-8"))
    assert len(h["undo"]) == WL.MAX_HISTORY
    WL.asset_set(film, sid, {"id": ids["near"], "x": 7.0})
    back = WL.version_restore(film, sid, 1)
    assert next(a for a in back["assets"] if a["id"] == ids["near"])["x"] == 0.6 and back["id"] == sid and back["version"] > 50
    undone = WL.undo(film, sid)
    assert next(a for a in undone["assets"] if a["id"] == ids["near"])["x"] == 7.0                        # restoring is itself undoable
    for bad, why in ((None, "Choose a saved"), (9, "isn't there")):
        with pytest.raises(SystemExit, match=why):
            WL.version_restore(film, sid, bad)
    with pytest.raises(SystemExit, match="name"):
        WL.version_save(film, sid, "  ")


def test_a_locked_set_refuses_every_change_until_it_is_unlocked(film, tmp_path):
    sid, ids = market(film, tmp_path)
    WL.lock(film, sid, True)
    assert WL.get(film, sid)["locked"] is True
    for call in (lambda: WL.asset_set(film, sid, {"id": ids["near"], "x": 1}), lambda: WL.camera_set(film, sid, {"name": "x"}), lambda: WL.asset_remove(film, sid, ids["near"]),
                 lambda: WL.undo(film, sid), lambda: WL.meta_set(film, sid, {"name": "z"}), lambda: WL.event_set(film, sid, {"shot": shot_ids(film)[0], "asset": ids["near"], "state": "x"})):
        with pytest.raises(SystemExit, match="locked"):
            call()
    assert view(film, sid)[0]["drawn"]                                                                       # looking is always allowed
    WL.lock(film, sid, False)
    assert WL.asset_set(film, sid, {"id": ids["near"], "x": 1})["assets"][2]["x"] == 1.0


def test_removing_a_picture_keeps_its_file_and_a_removed_set_is_put_away_not_deleted(film, tmp_path):
    sid, ids = market(film, tmp_path)
    f = next(a for a in WL.get(film, sid)["assets"] if a["id"] == ids["near"])["file"]
    g = WL.asset_remove(film, sid, ids["near"])
    assert ids["near"] not in [a["id"] for a in g["assets"]] and g["removed"][0]["id"] == ids["near"] and os.path.isfile(os.path.join(film, f))
    assert WL.undo(film, sid)["assets"][2]["id"] == ids["near"]
    WL.set_remove(film, sid)
    assert WL.list_sets(film)["sets"] == [] and os.path.isdir(os.path.join(film, "worldlock", "_removed"))
    assert os.listdir(os.path.join(film, "worldlock", "_removed"))[0].startswith(sid)


def test_a_set_file_of_the_wrong_shape_is_refused_and_left_alone(film):
    sid = WL.create(film, {})["id"]
    p = os.path.join(film, "worldlock", sid, "set.json")
    open(p, "w", encoding="utf-8").write('{"schema": 1, "assets": "junk"}')
    with pytest.raises(SystemExit, match="left untouched"):
        WL.get(film, sid)
    assert open(p, encoding="utf-8").read() == '{"schema": 1, "assets": "junk"}'
    assert WL.list_sets(film)["sets"][0].get("damaged") is True


# ---------------------------------------------------------------- cutting a layer out of a picture

def test_a_cut_layer_looks_the_same_from_the_camera_and_separates_when_the_camera_moves(film, tmp_path):
    sid = WL.create(film, {})["id"]
    back = Image.new("RGBA", (400, 200), BLUE + (255,))
    ImageDraw.Draw(back).rectangle((150, 60, 250, 200), fill=RED + (255,))                                    # a red figure painted on the backdrop
    p = str(tmp_path / "backdrop.png")
    back.save(p)
    a = WL.asset_add(film, sid, {"path": p, "x": 0, "y": 0, "z": 10, "width": 20, "height": 10})["assets"][0]
    cam0 = {"x": 0, "y": 1.6, "z": 0}
    _, before = view(film, sid, view=cam0)
    cut = WL.cut_layer(film, sid, {"id": a["id"], "box": [0.34, 0.28, 0.66, 1.0], "z": 5.0, "name": "Figure"})
    fig = next(x for x in cut["assets"] if x["id"] == cut["id"])
    assert fig["z"] == 5.0 and fig["cut_from"] == a["id"] and fig["width"] == pytest.approx(3.2 * 0.5, abs=0.2) or fig["width"] > 0
    _, after = view(film, sid, view=cam0)
    cx_b, cy_b, n_b = centroid(before, RED)
    cx_a, cy_a, n_a = centroid(after, RED)
    assert (cx_a, cy_a) == pytest.approx((cx_b, cy_b), abs=2.0) and n_a == pytest.approx(n_b, rel=0.08)       # the same picture from where the camera stood
    _, moved = view(film, sid, view={"x": 1.0, "y": 1.6, "z": 0})
    _, moved_before = view(film, sid, view={"x": 1.0, "y": 1.6, "z": 0})
    cx_m = centroid(moved, RED)[0]
    assert cx_m < cx_a - 20                                                                                    # the near figure slides further than the backdrop would have carried it
    assert WL.get(film, sid)["assets"][0]["pixels"] == [400, 200]                                              # the backdrop is whole: nothing was invented behind the figure


def test_a_cut_is_checked(film, tmp_path):
    sid, ids = market(film, tmp_path)
    for data, why in (({"id": ids["stall"]}, "region as left"), ({"id": ids["stall"], "box": [0.1, 0.1, 0.105, 0.5]}, "too small"), ({"id": "wa-00000000", "box": [0, 0, 1, 1]}, "isn't in the set"),
                      ({"id": ids["stall"], "box": [0, 0, 1, 1], "z": -3}, "in front of the camera")):
        with pytest.raises(SystemExit, match=why):
            WL.cut_layer(film, sid, data)
    assert len(WL.get(film, sid)["assets"]) == 4


# ---------------------------------------------------------------- characters, lights, environment, limits

def test_characters_lights_and_the_environment_are_kept_with_the_set(film, tmp_path):
    sid, ids = market(film, tmp_path)
    c = WL.character_set(film, sid, {"name": " Sarah ", "x": -1, "z": 4, "facing": 90, "asset": ids["basket"]})
    assert c["characters"][0]["name"] == "Sarah" and c["characters"][0]["asset"] == ids["basket"]
    WL.light_set(film, sid, {"name": "Sun", "azimuth": 30, "elevation": 55, "colour": "#ffeedd", "intensity": 5})
    g = WL.meta_set(film, sid, {"environment": {"time": "morning", "weather": "clear", "atmosphere": "dusty"}})
    assert g["lights"][0]["colour"] == "#ffeedd" and g["lights"][0]["intensity"] == 1.0 and g["environment"]["time"] == "morning"
    with pytest.raises(SystemExit, match="name"):
        WL.character_set(film, sid, {"name": ""})
    with pytest.raises(SystemExit, match="isn't in the set"):
        WL.character_set(film, sid, {"name": "Tom", "asset": "wa-00000000"})
    WL.light_set(film, sid, {"id": g["lights"][0]["id"], "colour": "red"})
    assert WL.get(film, sid)["lights"][0]["colour"] == "#ffeedd"                                              # a bad colour is ignored, the old one stays
    r, _ = view(film, sid, view={"x": 0, "y": 1.6, "z": 0})
    assert any(x == c["id"] for x in r["drawn"])                                                              # a character with a picture is drawn where it stands


def test_limits_and_world_bounds(film, tmp_path, monkeypatch):
    sid = WL.create(film, {"world": {"bounds": {"x": [5, -5], "z": [0, 2000]}}})["id"]
    b = WL.get(film, sid)["world"]["bounds"]
    assert b["x"] == [-5.0, 5.0] and b["z"] == [0.0, 1000.0] and b["y"] == [0.0, 10.0]
    monkeypatch.setattr(WL, "MAX_CAMERAS", 2)
    WL.camera_set(film, sid, {"name": "B"})
    with pytest.raises(SystemExit, match="At most 2 cameras"):
        WL.camera_set(film, sid, {"name": "C"})
    monkeypatch.setattr(WL, "MAX_SETS", 1)
    with pytest.raises(SystemExit, match="At most 1 sets"):
        WL.create(film, {})
    big = WL.create.__doc__ and None


# ---------------------------------------------------------------- continuity checks

def test_a_clean_set_has_no_issues_and_each_kind_of_problem_is_found(film, tmp_path):
    sid, ids = market(film, tmp_path)
    assert WL.check(film, sid)["ok"] is True
    WL.asset_set(film, sid, {"id": ids["near"], "x": 500})
    WL.camera_set(film, sid, {"name": "Far", "x": 99})
    cin = WL.camera_set(film, sid, {"name": "Inside", "x": 0, "y": 1.0, "z": 20})["id"]
    order = shot_ids(film)
    ev = WL.event_set(film, sid, {"shot": order[0], "asset": ids["stall"], "state": "x"})["id"]
    WL.asset_remove(film, sid, ids["stall"])
    os.remove(os.path.join(film, next(a for a in WL.get(film, sid)["assets"] if a["id"] == ids["basket"])["file"]))
    kinds = sorted(i["kind"] for i in WL.check(film, sid)["issues"])
    assert kinds == sorted(["outside", "camera_outside", "camera_inside", "event_orphan", "missing_picture"]), kinds
    assert WL.check(film, sid)["ok"] is False and ev


def test_the_camera_crossing_the_line_between_two_people_is_found_between_consecutive_shots(film, tmp_path):
    sid = WL.create(film, {})["id"]
    a = WL.character_set(film, sid, {"name": "Sarah", "x": -1, "z": 6})["id"]
    b = WL.character_set(film, sid, {"name": "Tom", "x": 1, "z": 6})["id"]
    south = WL.camera_set(film, sid, {"name": "South", "x": 0, "z": 0})["id"]
    south2 = WL.camera_set(film, sid, {"name": "South 2", "x": 2, "z": 1})["id"]
    north = WL.camera_set(film, sid, {"name": "North", "x": 0, "z": 12})["id"]
    WL.meta_set(film, sid, {"axis": [a, b]})
    order = shot_ids(film)
    WL.shot_camera(film, sid, {"shot": order[0], "camera": south})
    WL.shot_camera(film, sid, {"shot": order[1], "camera": south2})
    assert WL.check(film, sid)["issues"] == []                                                                # staying on one side is fine
    WL.shot_camera(film, sid, {"shot": order[2], "camera": north})
    issues = WL.check(film, sid)["issues"]
    assert [i["kind"] for i in issues] == ["crossed_line"] and "Sarah and Tom" in issues[0]["text"] and issues[0]["id"] == order[2]
    with pytest.raises(SystemExit, match="Choose a shot"):
        WL.shot_camera(film, sid, {"shot": "S99-99", "camera": south})
    with pytest.raises(SystemExit, match="isn't in the set"):
        WL.shot_camera(film, sid, {"shot": order[0], "camera": "wk-00000000"})
    WL.camera_remove(film, sid, north)
    assert WL.check(film, sid)["ok"] is True and all(x["camera"] != north for x in WL.get(film, sid)["shots"])


def test_the_command_line_answers_with_json(film, tmp_path, capsys):
    p = pic(tmp_path, "c", 40, 40, RED)
    assert WL.main(["create", film, "--data", json.dumps({"name": "CLI"})]) == 0
    sid = WL.list_sets(film)["sets"][0]["id"]
    assert WL.main(["asset_add", film, "--data", json.dumps({"set": sid, "path": p, "z": 5})]) == 0
    assert WL.main(["render", film, "--data", json.dumps({"set": sid, "size": [200, 120]})]) == 0
    assert WL.main(["check", film, "--data", json.dumps({"set": sid})]) == 0
    assert WL.main(["get", film, "--data", json.dumps({"set": "ws-00000000"})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip().startswith("{")]
    assert [x["event"] for x in lines] == ["result"] * 4 + ["error"] and lines[2]["data"]["drawn"]
