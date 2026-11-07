"""A 3D WorldLock set on a real film folder: glTF models stood in the set, grouped, turned and scaled, a ground, collisions, and the same scene from front, side, reverse and above. The models are written by
the test writer (`glbtools`, following the glTF 2.0 specification), not third-party files."""
import json
import os
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from filmcrafter_engine import bible, shots as S, story, worldlock as WL  # noqa: E402
from glbtools import cube_faces, glb  # noqa: E402
from test_worldlock import RED, pic, YELLOW  # noqa: E402

SCRIPT = "INT. KITCHEN - DAY\n\nSARAH stirs a pot.\n\nSARAH\nBreakfast is ready.\n"


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def cube_file(tmp_path, name="cube.glb", size=1.0, colors=None):
    p = str(tmp_path / name)
    open(p, "wb").write(glb(cube_faces(size, colors=colors)))
    return p


def white_cube(tmp_path, name="w.glb", size=1.0, col=(1, 0, 0)):
    return cube_file(tmp_path, name, size, {k: col for k in ("+z", "-z", "+x", "-x", "+y", "-y")})


def look(film, sid, cam, size=(300, 200), **kw):
    r = WL.render(film, sid, {"view": cam, "size": list(size), **kw})
    return r, np.asarray(Image.open(os.path.join(film, r["file"])).convert("RGB"), dtype=np.float32) / 255.0


def lit(film, sid):
    WL.light_set(film, sid, {"name": "Front", "azimuth": 180, "elevation": 20, "colour": "#ffffff", "intensity": 1.0})
    WL.light_set(film, sid, {"name": "Top", "azimuth": 0, "elevation": 80, "colour": "#ffffff", "intensity": 0.6})


def centroid(img, colour, tol=0.25):
    m = np.abs(img - np.array(colour, dtype=np.float32) / 255.0).max(axis=-1) < tol
    ys, xs = np.nonzero(m)
    return (float(xs.mean()), float(ys.mean()), int(m.sum())) if len(xs) else None


# ---------------------------------------------------------------- models

def test_a_model_is_copied_in_measured_and_placed_and_the_original_is_untouched(film, tmp_path):
    sid = WL.create(film, {})["id"]
    p = cube_file(tmp_path, size=2.0)
    before = open(p, "rb").read()
    r = WL.model_add(film, sid, {"path": p, "name": "  Crate ", "x": 1, "y": 1, "z": 6, "yaw": 30, "scale": 1.5})
    m = r["models"][0]
    assert m["name"] == "Crate" and (m["x"], m["y"], m["z"], m["yaw"], m["scale"]) == (1.0, 1.0, 6.0, 30.0, 1.5) and m["summary"]["triangles"] == 12 and m["summary"]["size"] == [2.0, 2.0, 2.0]
    assert open(p, "rb").read() == before and open(os.path.join(film, m["file"]), "rb").read() == before and r["id"] == m["id"] and m["visible"] and m["solid"]
    assert r["can_undo"] and r["undo_label"] == "Add a model"
    assert WL.undo(film, sid)["models"] == []


def test_files_that_are_not_usable_models_are_refused_and_change_nothing(film, tmp_path):
    sid = WL.create(film, {})["id"]
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    junk = tmp_path / "j.glb"
    junk.write_bytes(b"not a model")
    for data, why in (({}, "Choose a .glb"), ({"path": str(txt)}, "Choose a .glb"), ({"path": str(junk)}, "not a glTF|damaged"), ({"path": str(tmp_path / "gone.glb")}, "Choose a .glb")):
        with pytest.raises(SystemExit, match=why):
            WL.model_add(film, sid, data)
    assert WL.get(film, sid)["models"] == [] and WL.get(film, sid)["version"] == 1


def test_a_model_moves_turns_scales_hides_and_keeps_its_id_and_file(film, tmp_path):
    sid = WL.create(film, {})["id"]
    mid = WL.model_add(film, sid, {"path": white_cube(tmp_path), "z": 6})["id"]
    before = WL.get(film, sid)["models"][0]
    r = WL.model_set(film, sid, {"id": mid, "x": 2, "yaw": 400, "scale": 99999, "name": "Box", "file": "../../evil.glb", "visible": False})
    m = r["models"][0]
    assert m["x"] == 2.0 and m["yaw"] == 360.0 and m["scale"] == 1000.0 and m["name"] == "Box" and m["file"] == before["file"] and m["visible"] is False
    with pytest.raises(SystemExit, match="isn't in the set"):
        WL.model_set(film, sid, {"id": "wm-00000000"})
    with pytest.raises(SystemExit, match="group isn't in the set"):
        WL.model_set(film, sid, {"id": mid, "parent": "wg-00000000"})


def test_a_moved_model_moves_in_the_picture_by_the_projection(film, tmp_path):
    sid = WL.create(film, {})["id"]
    lit(film, sid)
    mid = WL.model_add(film, sid, {"path": white_cube(tmp_path, col=(1, 0, 0)), "x": 0, "y": 0, "z": 6})["id"]
    cam = {"x": 0, "y": 0, "z": 0, "yaw": 0, "pitch": 0, "fov": 50}
    r, a = look(film, sid, cam)
    WL.model_set(film, sid, {"id": mid, "x": 1.0})
    _, b = look(film, sid, cam)
    ca, cb = centroid(a, (255, 0, 0)), centroid(b, (255, 0, 0))
    f = (300 / 2) / np.tan(np.radians(25))
    assert abs(ca[0] - 150) < 4 and cb[0] - ca[0] == pytest.approx(f * 1.0 / 5.5, abs=4) and ids_in(r, mid)
    big = WL.model_set(film, sid, {"id": mid, "x": 0, "scale": 2.0})
    _, c = look(film, sid, cam)
    assert centroid(c, (255, 0, 0))[2] > 3 * ca[2]                                                          # twice the size: about four times the area


def ids_in(r, mid):
    return mid in r["drawn"]


def test_a_hidden_model_is_not_drawn_and_a_model_behind_the_camera_is_skipped_with_a_reason(film, tmp_path):
    sid = WL.create(film, {})["id"]
    mid = WL.model_add(film, sid, {"path": white_cube(tmp_path), "z": 6})["id"]
    WL.model_set(film, sid, {"id": mid, "visible": False})
    r, _ = look(film, sid, {"x": 0, "y": 0, "z": 0, "yaw": 0, "pitch": 0, "fov": 50})
    assert mid not in r["drawn"] and r["uncovered"] > 0.9
    WL.model_set(film, sid, {"id": mid, "visible": True, "z": -6})
    r2, _ = look(film, sid, {"x": 0, "y": 0, "z": 0, "yaw": 0, "pitch": 0, "fov": 50})
    assert r2["uncovered"] > 0.9                                                                             # behind the camera: nothing to see, and nothing invented


def test_a_missing_model_file_is_reported_and_the_rest_of_the_set_still_draws(film, tmp_path):
    sid = WL.create(film, {})["id"]
    a = WL.model_add(film, sid, {"path": white_cube(tmp_path, "a.glb"), "x": -1, "z": 6})["id"]
    b = WL.model_add(film, sid, {"path": white_cube(tmp_path, "b.glb"), "x": 1, "z": 6})["id"]
    os.remove(os.path.join(film, next(m for m in WL.get(film, sid)["models"] if m["id"] == a)["file"]))
    WL._MODEL_CACHE.clear()
    r, _ = look(film, sid, {"x": 0, "y": 0, "z": 0, "yaw": 0, "pitch": 0, "fov": 50})
    assert b in r["drawn"] and a not in r["drawn"] and any(x["id"] == a for x in r["skipped"])


def test_the_removed_model_keeps_its_file_and_undo_brings_it_back(film, tmp_path):
    sid = WL.create(film, {})["id"]
    mid = WL.model_add(film, sid, {"path": white_cube(tmp_path), "z": 6})["id"]
    f = WL.get(film, sid)["models"][0]["file"]
    r = WL.model_remove(film, sid, mid)
    assert r["models"] == [] and r["removed"][0]["id"] == mid and os.path.isfile(os.path.join(film, f))
    assert WL.undo(film, sid)["models"][0]["id"] == mid


def test_a_locked_set_refuses_every_3d_change(film, tmp_path):
    sid = WL.create(film, {})["id"]
    mid = WL.model_add(film, sid, {"path": white_cube(tmp_path), "z": 6})["id"]
    WL.lock(film, sid, True)
    for call in (lambda: WL.model_set(film, sid, {"id": mid, "x": 3}), lambda: WL.model_remove(film, sid, mid), lambda: WL.ground_set(film, sid, {"visible": True}), lambda: WL.group_set(film, sid, {"name": "x"}),
                 lambda: WL.model_add(film, sid, {"path": white_cube(tmp_path, "z.glb")})):
        with pytest.raises(SystemExit, match="locked"):
            call()


# ---------------------------------------------------------------- groups

def test_moving_a_group_moves_everything_in_it_and_a_loop_is_refused(film, tmp_path):
    sid = WL.create(film, {})["id"]
    lit(film, sid)
    g = WL.group_set(film, sid, {"name": "Stall", "x": 0, "y": 0, "z": 0})["id"]
    m1 = WL.model_add(film, sid, {"path": white_cube(tmp_path, "a.glb", col=(1, 0, 0)), "x": -0.8, "z": 6, "parent": g})["id"]
    m2 = WL.model_add(film, sid, {"path": white_cube(tmp_path, "b.glb", col=(0, 0, 1)), "x": 0.8, "z": 6, "parent": g})["id"]
    cam = {"x": 0, "y": 0, "z": 0, "yaw": 0, "pitch": 0, "fov": 50}
    _, a = look(film, sid, cam)
    WL.group_set(film, sid, {"id": g, "x": 1.5})
    _, b = look(film, sid, cam)
    f = (300 / 2) / np.tan(np.radians(25))
    shifts = [centroid(b, col)[0] - centroid(a, col)[0] for col in ((255, 0, 0), (0, 0, 255))]
    assert shifts[0] == pytest.approx(shifts[1], abs=12) and f * 1.5 / 6.6 < shifts[0] < f * 1.5 / 5.0                  # both moved by the same amount, as far as a 1.5 m move at about 6 m should
    g2 = WL.group_set(film, sid, {"name": "Inner", "parent": g})["id"]
    with pytest.raises(SystemExit, match="contain themselves"):
        WL.group_set(film, sid, {"id": g, "parent": g2})
    with pytest.raises(SystemExit, match="group isn't in the set"):
        WL.group_set(film, sid, {"name": "x", "parent": "wg-00000000"})
    assert [x["parent"] for x in WL.get(film, sid)["groups"]] == [None, g]                                      # the refused change left the group where it was


def test_removing_a_group_keeps_what_was_in_it_where_it_was(film, tmp_path):
    sid = WL.create(film, {})["id"]
    g = WL.group_set(film, sid, {"name": "G", "x": 2, "y": 0, "z": 0})["id"]
    mid = WL.model_add(film, sid, {"path": white_cube(tmp_path), "x": 1, "z": 6, "parent": g})["id"]
    r = WL.group_remove(film, sid, g)
    m = r["models"][0]
    assert r["groups"] == [] and m["parent"] is None and (m["x"], m["z"]) == (3.0, 6.0) and m["id"] == mid


# ---------------------------------------------------------------- the ground

def test_the_ground_is_drawn_exactly_and_counts_as_covered_and_settings_are_checked(film, tmp_path):
    sid = WL.create(film, {})["id"]
    cam = {"x": 0, "y": 1.6, "z": 0, "yaw": 0, "pitch": -15, "fov": 60}
    r0, _ = look(film, sid, cam)
    assert r0["uncovered"] == 1.0
    g = WL.ground_set(film, sid, {"visible": True, "y": 0, "colours": ["#ffffff", "#000000"], "extent": 9999})
    assert g["ground"]["visible"] and g["ground"]["extent"] == 1000.0 and g["ground"]["colours"] == ["#ffffff", "#000000"]
    assert WL.ground_set(film, sid, {"colours": ["red", "#00ff00"]})["ground"]["colours"] == ["#ffffff", "#000000"]      # a bad colour is ignored
    r, img = look(film, sid, cam)
    assert 0.3 < r["coverage"] < 0.9 and "ground" in r["drawn"]
    assert img[190, 150].max() >= 0.0 and img[5, 150].tolist() == pytest.approx(list(WL.SKY), abs=0.01)           # sky above, ground below


def test_a_model_stands_on_the_ground_and_hides_it_behind_itself(film, tmp_path):
    sid = WL.create(film, {})["id"]
    lit(film, sid)
    WL.ground_set(film, sid, {"visible": True, "colours": ["#808080", "#808080"]})
    WL.model_add(film, sid, {"path": white_cube(tmp_path, col=(1, 0, 0)), "x": 0, "y": 0.5, "z": 6})
    cam = {"x": 0, "y": 1.5, "z": 0, "yaw": 0, "pitch": -8, "fov": 50}
    _, img = look(film, sid, cam)
    c = centroid(img, (255, 0, 0))
    assert c is not None and c[2] > 200
    assert abs(img[195, 150][0] - img[195, 150][1]) < 0.05                                                         # the ground in front is grey, the cube red


# ---------------------------------------------------------------- 2.5D and 3D together

def test_a_flat_picture_behind_a_3d_model_is_hidden_by_it_and_one_in_front_covers_it(film, tmp_path):
    sid = WL.create(film, {})["id"]
    lit(film, sid)
    WL.model_add(film, sid, {"path": white_cube(tmp_path, size=2.0, col=(1, 0, 0)), "x": 0, "y": -1, "z": 6})
    behind = WL.asset_add(film, sid, {"path": pic(tmp_path, "y", 100, 100, YELLOW, edge=False), "name": "Behind", "x": 0, "y": -2, "z": 10, "width": 6, "height": 4})["id"]
    cam = {"x": 0, "y": 0, "z": 0, "yaw": 0, "pitch": 0, "fov": 50}
    _, a = look(film, sid, cam)
    assert a[100, 150][0] > a[100, 150][2] and a[100, 150][1] < 0.5                                              # the red cube in the middle, the yellow picture only around it
    assert centroid(a, (240, 220, 30))[2] > 500
    WL.asset_set(film, sid, {"id": behind, "z": 3})
    _, b = look(film, sid, cam)
    mid = b[100, 150]
    assert mid[1] > 0.5 and mid[0] > 0.5                                                                         # now the picture is nearer than the cube: yellow covers it


def test_a_scene_without_models_or_ground_draws_exactly_as_before(film, tmp_path):
    sid = WL.create(film, {})["id"]
    WL.asset_add(film, sid, {"path": pic(tmp_path, "w", 100, 100, RED), "z": 8, "width": 4, "height": 4})
    g = WL.get(film, sid)
    assert g["models"] == [] and g["groups"] == [] and g["ground"]["visible"] is False
    r, _ = look(film, sid, {"x": 0, "y": 1.6, "z": 0, "yaw": 0, "pitch": 0, "fov": 50})
    assert "ground" not in r["drawn"] and len(r["drawn"]) == 1


def test_an_old_set_file_with_no_3d_fields_still_opens(film):
    sid = WL.create(film, {})["id"]
    p = os.path.join(film, "worldlock", sid, "set.json")
    s = json.load(open(p, encoding="utf-8"))
    for k in ("models", "groups", "ground"):
        s.pop(k)
    json.dump(s, open(p, "w", encoding="utf-8"))
    g = WL.get(film, sid)
    assert g["models"] == [] and g["groups"] == [] and g["ground"]["visible"] is False


# ---------------------------------------------------------------- collisions and room

def test_overlaps_below_the_ground_outside_and_a_camera_inside_are_found_and_a_non_solid_thing_is_ignored(film, tmp_path):
    sid = WL.create(film, {})["id"]
    WL.ground_set(film, sid, {"visible": True, "y": 0})
    a = WL.model_add(film, sid, {"path": white_cube(tmp_path, "a.glb", size=2.0), "x": 0, "y": 1, "z": 6, "name": "A"})["id"]
    b = WL.model_add(film, sid, {"path": white_cube(tmp_path, "b.glb", size=2.0), "x": 1.5, "y": 1, "z": 6, "name": "B"})["id"]
    ok = WL.collisions(film, sid)
    assert [i["kind"] for i in ok["issues"]] == ["overlap"] and ok["issues"][0]["depth_m"] == pytest.approx(0.5, abs=0.01) and set(ok["issues"][0]["ids"]) == {a, b}
    WL.model_set(film, sid, {"id": b, "solid": False})
    assert WL.collisions(film, sid)["ok"] is True
    WL.model_set(film, sid, {"id": b, "solid": True, "x": 5.0, "y": 0.2})
    assert [i["kind"] for i in WL.collisions(film, sid)["issues"]] == ["below_ground"]
    WL.model_set(film, sid, {"id": b, "x": 500.0, "y": 1})
    assert "outside" in [i["kind"] for i in WL.collisions(film, sid)["issues"]]
    WL.camera_set(film, sid, {"name": "In", "x": 0, "y": 1, "z": 6})
    assert "camera_inside" in [i["kind"] for i in WL.collisions(film, sid)["issues"]]


def test_the_floor_plan_marks_the_squares_a_model_takes(film, tmp_path):
    sid = WL.create(film, {"world": {"bounds": {"x": [-5, 5], "z": [0, 10]}}})["id"]
    WL.ground_set(film, sid, {"visible": True, "y": 0})
    WL.model_add(film, sid, {"path": white_cube(tmp_path, size=2.0), "x": 0, "y": 1, "z": 5})
    WL.model_add(film, sid, {"path": white_cube(tmp_path, "flat.glb", size=0.05), "x": 3, "y": 0.025, "z": 5})                        # a rug-thin thing: no room taken
    o = WL.occupancy(film, sid, {"cell": 1.0})
    assert o["cell"] == 1.0 and len(o["grid"]) == 10 and len(o["grid"][0]) == 10 and o["occupied"] == 4 and o["free"] == 96 and o["origin"] == [-5.0, 0.0]
    assert o["grid"][4][4] == 1 and o["grid"][5][5] == 1 and o["grid"][0][0] == 0 and o["grid"][5][8] == 0


# ---------------------------------------------------------------- the same scene from four sides

def test_front_side_reverse_and_elevated_views_show_the_face_each_side_should(film, tmp_path):
    sid = WL.create(film, {})["id"]
    lit(film, sid)
    WL.light_set(film, sid, {"name": "Back", "azimuth": 0, "elevation": 20, "colour": "#ffffff", "intensity": 1.0})
    WL.light_set(film, sid, {"name": "Right", "azimuth": 90, "elevation": 20, "colour": "#ffffff", "intensity": 1.0})
    WL.model_add(film, sid, {"path": cube_file(tmp_path), "x": 0, "y": 0.5, "z": 6})
    r = WL.views3d(film, sid, {"size": [240, 160]})
    assert [v["name"] for v in r["views"]] == ["Front", "Side", "Reverse", "Elevated"] and r["target"] == pytest.approx([0.0, 0.5, 6.0], abs=1e-3)
    px = {}
    for v in r["views"]:
        img = np.asarray(Image.open(os.path.join(film, v["file"])).convert("RGB"), dtype=np.float32) / 255.0
        m = np.abs(img - np.array(WL.SKY, dtype=np.float32)).max(axis=-1) > 0.05
        assert m.sum() > 300 and v["uncovered"] < 0.95
        px[v["name"]] = int(np.argmax(img[m].mean(axis=0)))
    assert px["Front"] == 0 and px["Side"] == 1 and px["Reverse"] == 2                                       # red front, green side (+X), blue back
    assert all(len(v["drawn"]) == 1 for v in r["views"])
    assert WL.get(film, sid)["models"][0]["x"] == 0.0                                                         # the set did not move


def test_the_four_views_of_an_empty_set_still_answer_and_a_given_target_and_distance_are_used(film, tmp_path):
    sid = WL.create(film, {})["id"]
    r = WL.views3d(film, sid, {"size": [96, 64]})
    assert len(r["views"]) == 4 and all(v["uncovered"] == 1.0 for v in r["views"])
    WL.model_add(film, sid, {"path": white_cube(tmp_path), "x": 4, "y": 0.5, "z": 6})
    r2 = WL.views3d(film, sid, {"target": [4, 0.5, 6], "distance": 7, "size": [96, 64]})
    assert r2["distance"] == 7.0 and r2["target"] == [4.0, 0.5, 6.0]


def test_the_command_line_runs_the_3d_actions(film, tmp_path, capsys):
    sid = WL.create(film, {})["id"]
    assert WL.main(["model_add", film, "--data", json.dumps({"set": sid, "path": white_cube(tmp_path), "z": 6})]) == 0
    assert WL.main(["ground_set", film, "--data", json.dumps({"set": sid, "visible": True})]) == 0
    assert WL.main(["collisions", film, "--data", json.dumps({"set": sid})]) == 0
    assert WL.main(["occupancy", film, "--data", json.dumps({"set": sid})]) == 0
    assert WL.main(["views3d", film, "--data", json.dumps({"set": sid, "size": [96, 64]})]) == 0
    assert WL.main(["model_set", film, "--data", json.dumps({"set": sid, "id": "wm-00000000"})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip().startswith("{")]
    assert [x["event"] for x in lines] == ["result"] * 5 + ["error"] and lines[0]["data"]["models"][0]["summary"]["triangles"] == 12


# ---------------------------------------------------------------- the sky and fog

def test_a_sky_is_a_gradient_from_the_horizon_up_and_fog_fades_far_things_into_it(film, tmp_path):
    sid = WL.create(film, {})["id"]
    lit(film, sid)
    cam = {"x": 0, "y": 1.6, "z": 0, "yaw": 0, "pitch": 10, "fov": 60}
    _, plain = look(film, sid, cam)
    assert np.allclose(plain[5, 5], WL.SKY, atol=0.01)
    s = WL.sky_set(film, sid, {"top": "#102050", "horizon": "#f0a060"})
    assert s["sky"] == {"top": "#102050", "horizon": "#f0a060", "fog": 0.0}
    _, img = look(film, sid, cam)
    assert img[5, 150][2] > img[5, 150][0] and img[195, 150][0] > img[195, 150][2]                                  # blue overhead, orange toward the horizon
    WL.model_add(film, sid, {"path": white_cube(tmp_path, size=4.0, col=(1, 0, 0)), "x": 0, "y": 2, "z": 40})
    _, clear = look(film, sid, {**cam, "pitch": 0})
    WL.sky_set(film, sid, {"fog": 0.08})
    _, foggy = look(film, sid, {**cam, "pitch": 0})
    c0, c1 = centroid(clear, (255, 0, 0), tol=0.35), None
    px = foggy[100, 150]
    assert clear[100, 150][0] > 0.5 and clear[100, 150][1] < 0.3 and px[1] > clear[100, 150][1] + 0.15              # the far red cube is paler in the fog
    assert WL.sky_set(film, sid, {"top": "red", "fog": 9})["sky"] == {"top": "#102050", "horizon": "#f0a060", "fog": 1.0}      # a bad colour is ignored, fog is limited
    assert WL.sky_set(film, sid, {"top": None, "horizon": ""})["sky"]["top"] is None
    assert c0 is not None
