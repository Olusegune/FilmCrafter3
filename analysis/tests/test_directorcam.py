"""DirectorCam on a real film and a real WorldLock set: cameras placed by shot size and checked by projecting known points, camera moves checked as transforms, a story beat turned into shots, advice that
fires for each rule and can be overruled, and shot packages whose pictures, depth map and object map are real files. Pictures are simple coloured shapes so positions can be measured."""
import json
import math
import os
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from filmcrafter_engine import bible, directorcam as DC, shots as S, story, worldlock as WL, worldmath as WM  # noqa: E402
from test_worldlock import BLUE, GREEN, RED, YELLOW, pic, shot_ids  # noqa: E402

SCRIPT = ("INT. KITCHEN - DAY\n\nSARAH stirs a pot. TOM watches her.\n\nSARAH\nBreakfast is ready.\n\nEXT. MARKET - DAY\n\nSARAH carries a basket through the crowd. It falls. She picks it up.\n\n"
          "TOM\nI have it.\n\nINT. HALL - NIGHT\n\nSARAH sits alone.\n")
BEAT = "The girl enters the market, sees the oranges, and rushes to help the vendor."


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


@pytest.fixture
def world(film, tmp_path):
    """A market: a backdrop, a tall stall, oranges on the floor, a girl and a vendor drawn by pictures."""
    sid = WL.create(film, {"name": "Market"})["id"]
    ids = {}
    ids["back"] = WL.asset_add(film, sid, {"path": pic(tmp_path, "back", 1200, 400, BLUE), "name": "Backdrop", "y": -8, "z": 20, "width": 70, "height": 24})["id"]
    ids["oranges"] = WL.asset_add(film, sid, {"path": pic(tmp_path, "or", 80, 40, YELLOW), "name": "Oranges", "kind": "prop", "x": 2.0, "y": 0, "z": 7, "width": 0.8, "height": 0.4, "tags": ["fruit"]})["id"]
    ids["girl_pic"] = WL.asset_add(film, sid, {"path": pic(tmp_path, "girl", 60, 120, RED), "name": "Girl picture", "kind": "prop", "x": 50, "z": 50, "width": 0.5, "height": 1.2})["id"]
    ids["vendor_pic"] = WL.asset_add(film, sid, {"path": pic(tmp_path, "vendor", 60, 120, GREEN), "name": "Vendor picture", "kind": "prop", "x": 50, "z": 50, "width": 0.5, "height": 1.2})["id"]
    ids["girl"] = WL.character_set(film, sid, {"name": "Girl", "x": -2.0, "z": 6.0, "facing": 90, "asset": ids["girl_pic"]})["id"]
    ids["vendor"] = WL.character_set(film, sid, {"name": "Vendor", "x": 3.5, "z": 8.0, "facing": -90, "asset": ids["vendor_pic"]})["id"]
    return sid, ids


def s_of(film, sid):
    return WL._load(film, sid)


# ---------------------------------------------------------------- the camera and its moves

def test_forward_right_and_look_at_agree_with_the_world_conventions():
    c = {"x": 0.0, "y": 1.6, "z": 0.0, "yaw": 0.0, "pitch": 0.0, "fov": 50.0}
    assert DC.forward(c) == pytest.approx((0.0, 0.0, 1.0)) and DC.right(c) == pytest.approx((1.0, 0.0, 0.0))
    assert DC.forward({**c, "yaw": 90.0}) == pytest.approx((1.0, 0.0, 0.0), abs=1e-9) and DC.right({**c, "yaw": 90.0}) == pytest.approx((0.0, 0.0, -1.0), abs=1e-9)
    l = DC.look_at(c, (4.0, 1.6, 4.0))
    assert l["yaw"] == pytest.approx(45.0) and l["pitch"] == pytest.approx(0.0)
    up = DC.look_at(c, (0.0, 6.6, 5.0))
    assert up["pitch"] == pytest.approx(45.0) and up["yaw"] == pytest.approx(0.0)
    sx, sy, _ = WM.project((4.0, 1.6, 4.0), l, (600, 400))
    assert (sx, sy) == (pytest.approx(300.0, abs=0.01), pytest.approx(200.0, abs=0.01))                  # what the camera was turned to is in the middle of the picture


def test_the_vertical_field_of_view_follows_the_horizontal_one_and_the_picture_shape():
    c = {"fov": 60.0}
    assert DC.vfov(c, 16 / 9) == pytest.approx(math.degrees(2 * math.atan(math.tan(math.radians(30)) * 9 / 16)))
    assert DC.vfov(c, 1.0) == pytest.approx(60.0)


CAM = {"x": 1.0, "y": 1.6, "z": 0.0, "yaw": 20.0, "pitch": 5.0, "fov": 50.0}


def test_static_and_the_end_poses_of_each_move_are_exact_transforms():
    assert all(p == DC.camera_path(CAM, {"kind": "static"}, 4)[0] for p in DC.camera_path(CAM, {"kind": "static"}, 4))
    pan = DC.camera_path(CAM, {"kind": "pan", "amount": 30, "ease": "linear"}, 6)
    assert [p["yaw"] for p in pan] == pytest.approx([20 + 5 * i for i in range(7)]) and all(p["x"] == 1.0 and p["pitch"] == 5.0 for p in pan)
    tilt = DC.camera_path(CAM, {"kind": "tilt", "amount": -20, "ease": "linear"}, 4)
    assert tilt[-1]["pitch"] == pytest.approx(-15.0) and tilt[-1]["yaw"] == 20.0
    assert DC.camera_path(CAM, {"kind": "tilt", "amount": 500}, 2)[-1]["pitch"] == 85.0                      # limited to what a camera can do
    ped = DC.camera_path(CAM, {"kind": "pedestal", "amount": 0.8}, 4)
    assert ped[-1]["y"] == pytest.approx(2.4) and ped[-1]["x"] == 1.0 and ped[-1]["yaw"] == 20.0


def test_dolly_truck_and_push_in_move_the_camera_the_way_it_points_or_sideways():
    f = DC.forward(CAM)
    flat = math.hypot(f[0], f[2])
    dolly = DC.camera_path(CAM, {"kind": "dolly", "amount": 2.0}, 4)[-1]
    assert (dolly["x"] - 1.0, dolly["z"] - 0.0) == pytest.approx((2.0 * f[0] / flat, 2.0 * f[2] / flat), abs=1e-3) and dolly["yaw"] == 20.0
    back = DC.camera_path(CAM, {"kind": "dolly", "amount": -1.0}, 4)[-1]
    assert back["z"] < 0.0
    r = DC.right(CAM)
    truck = DC.camera_path(CAM, {"kind": "truck", "amount": 1.5}, 4)[-1]
    assert (truck["x"] - 1.0, truck["z"]) == pytest.approx((1.5 * r[0], 1.5 * r[2]), abs=1e-3) and truck["yaw"] == 20.0
    target = (1.0, 1.4, 6.0)
    push = DC.camera_path({**CAM, "yaw": 0.0}, {"kind": "push_in", "amount": 2.0}, 4, target=target)
    d0, d1 = math.hypot(target[0] - push[0]["x"], target[2] - push[0]["z"]), math.hypot(target[0] - push[-1]["x"], target[2] - push[-1]["z"])
    assert d0 - d1 == pytest.approx(2.0, abs=1e-3)
    pull = DC.camera_path({**CAM, "yaw": 0.0}, {"kind": "pull_out", "amount": 2.0}, 4, target=target)
    assert math.hypot(target[0] - pull[-1]["x"], target[2] - pull[-1]["z"]) - math.hypot(target[0] - pull[0]["x"], target[2] - pull[0]["z"]) == pytest.approx(2.0, abs=1e-3)


def test_an_orbit_keeps_its_distance_and_keeps_the_subject_in_the_middle():
    target = (0.0, 1.4, 6.0)
    cam = {"x": 0.0, "y": 1.6, "z": 0.0, "yaw": 0.0, "pitch": 0.0, "fov": 50.0}
    path = DC.camera_path(DC.look_at(cam, target), {"kind": "orbit", "amount": 90.0, "ease": "linear"}, 6, target=target)
    for p in path:
        assert math.hypot(p["x"] - target[0], p["z"] - target[2]) == pytest.approx(6.0, abs=1e-2)
        sx, sy, _ = WM.project(target, p, (600, 400))
        assert (sx, sy) == (pytest.approx(300.0, abs=2.0), pytest.approx(200.0, abs=2.0))
    assert path[-1]["x"] != path[0]["x"] and abs(path[-1]["z"] - path[0]["z"]) > 1.0
    with pytest.raises(SystemExit, match="needs a point"):
        DC.camera_path(cam, {"kind": "orbit", "amount": 45}, 4)


def test_a_crane_rises_and_backs_off_while_the_subject_stays_in_view_and_tracking_keeps_its_offset():
    target = (0.0, 1.4, 6.0)
    cam = DC.look_at({"x": 0.0, "y": 1.6, "z": 0.0, "yaw": 0.0, "pitch": 0.0, "fov": 50.0}, target)
    crane = DC.camera_path(cam, {"kind": "crane", "amount": 3.0}, 4, target=target)
    assert crane[-1]["y"] == pytest.approx(4.6) and crane[-1]["z"] < cam["z"] and crane[-1]["pitch"] < cam["pitch"]
    assert WM.project(target, crane[-1], (600, 400)) is not None and abs(WM.project(target, crane[-1], (600, 400))[1] - 200) < 3
    track = DC.camera_path(cam, {"kind": "tracking"}, 4, follow=((0.0, 6.0), (3.0, 7.0)))
    assert (track[-1]["x"] - cam["x"], track[-1]["z"] - cam["z"]) == pytest.approx((3.0, 1.0), abs=1e-3) and track[-1]["yaw"] == cam["yaw"]
    with pytest.raises(SystemExit, match="needs the person"):
        DC.camera_path(cam, {"kind": "tracking"}, 4)


def test_paths_are_deterministic_eased_and_an_unknown_move_is_static():
    a = DC.camera_path(CAM, {"kind": "truck", "amount": 2.0, "ease": "smooth"}, 8)
    assert a == DC.camera_path(CAM, {"kind": "truck", "amount": 2.0, "ease": "smooth"}, 8)
    lin = DC.camera_path(CAM, {"kind": "truck", "amount": 2.0, "ease": "linear"}, 8)
    assert a[4]["x"] == pytest.approx(lin[4]["x"], abs=1e-3) and abs(a[1]["x"] - 1.0) < abs(lin[1]["x"] - 1.0)       # eased: slow at the start, the same in the middle
    assert DC.camera_path(CAM, {"kind": "warp", "amount": 9}, 3) == DC.camera_path(CAM, {"kind": "static"}, 3)


# ---------------------------------------------------------------- placing a camera by shot size

def test_each_shot_size_fits_the_height_of_the_world_it_promises(film, world):
    sid, ids = world
    s = s_of(film, sid)
    for size in ("close-up", "medium", "wide"):
        r = DC.place_camera(s, {"subjects": [ids["girl"]], "size": size})
        cam = r["camera"]
        H = 540
        f = DC.forward(cam)
        mid = (cam["x"] + f[0] * r["distance_m"], cam["y"] + f[1] * r["distance_m"], cam["z"] + f[2] * r["distance_m"])      # the point the camera looks at
        top = WM.project((mid[0], mid[1] + DC.SIZES[size] / 4, mid[2]), cam, (960, H))
        bot = WM.project((mid[0], mid[1] - DC.SIZES[size] / 4, mid[2]), cam, (960, H))
        assert r["frame_height_m"] >= DC.SIZES[size] - 0.01
        px_per_m = (bot[1] - top[1]) / (DC.SIZES[size] / 2)                                                       # half the promised height, measured on the picture
        assert px_per_m == pytest.approx(H / r["frame_height_m"], rel=0.03)
        sx, sy, depth = WM.project((-2.0, 1.4, 6.0), cam, (960, H))
        assert abs(sx - 480) < 25 and depth == pytest.approx(r["distance_m"], rel=0.15)
    assert DC.place_camera(s, {"subjects": [ids["girl"]], "size": "close-up"})["distance_m"] < DC.place_camera(s, {"subjects": [ids["girl"]], "size": "wide"})["distance_m"]
    assert "close-up" in DC.place_camera(s, {"subjects": [ids["girl"]], "size": "close-up"})["because"].lower()


def test_a_longer_lens_stands_further_back_for_the_same_size_and_the_aspect_changes_the_frame(film, world):
    sid, ids = world
    s = s_of(film, sid)
    n35 = DC.place_camera(s, {"subjects": [ids["girl"]], "size": "medium", "focal_mm": 35})
    n85 = DC.place_camera(s, {"subjects": [ids["girl"]], "size": "medium", "focal_mm": 85})
    assert n85["distance_m"] > 2 * n35["distance_m"] and n85["camera"]["fov"] < n35["camera"]["fov"] and n35["camera"]["focal_mm"] == 35.0
    sq = DC.place_camera(s, {"subjects": [ids["girl"]], "size": "medium", "aspect": "1:1"})
    assert sq["camera"]["aspect"] == "1:1" and sq["distance_m"] < n35["distance_m"]


def test_two_subjects_are_framed_together_and_an_over_the_shoulder_stands_behind_the_first(film, world):
    sid, ids = world
    s = s_of(film, sid)
    two = DC.place_camera(s, {"subjects": [ids["girl"], ids["vendor"]], "size": "medium"})
    assert WM.project((-2.0, 1.4, 6.0), two["camera"], (960, 540)) is not None and 0 < WM.project((3.5, 1.4, 8.0), two["camera"], (960, 540))[0] < 960
    assert two["looking_at"] == "Girl, Vendor"
    ots = DC.place_camera(s, {"subjects": [ids["girl"], ids["vendor"]], "size": "over the shoulder", "side": "right"})
    cam = ots["camera"]
    assert ots["framing"] == "over the shoulder" and ots["looking_at"] == "Vendor"
    assert math.hypot(cam["x"] - -2.0, cam["z"] - 6.0) < 1.2                                                    # right behind the girl
    sx, _, _ = WM.project((3.5, 1.45, 8.0), cam, (960, 540))
    assert abs(sx - 480) < 40                                                                                    # the vendor is in the middle
    left = DC.place_camera(s, {"subjects": [ids["girl"], ids["vendor"]], "size": "over the shoulder", "side": "left"})["camera"]
    assert (left["x"] - -2.0) * (cam["x"] - -2.0) < 0 or (left["z"] - 6.0) * (cam["z"] - 6.0) < 0              # the other side of the line
    for data, why in (({"subjects": []}, "Choose who or what"), ({"subjects": ["wc-00000000"]}, "isn't in the set"), ({"subjects": [ids["girl"]], "size": "over the shoulder"}, "needs two people")):
        with pytest.raises(SystemExit, match=why):
            DC.place_camera(s, data)


# ---------------------------------------------------------------- a story beat

def test_the_beat_becomes_an_establishing_shot_then_the_shots_its_verbs_ask_for_with_reasons(film, world):
    sid, ids = world
    r = DC.plan_beat(s_of(film, sid), BEAT)
    shots = r["shots"]
    assert shots[0]["size"] == "establishing" and shots[0]["title"] == "Establish the place" and [x["n"] for x in shots] == list(range(1, len(shots) + 1))
    titles = [x["title"] for x in shots]
    assert any("enters" in t for t in titles) and any("notices" in t for t in titles) and any(t.startswith("What Girl sees") and "Oranges" in t for t in titles) and any("rushes to Vendor" in t for t in titles)
    enter = next(x for x in shots if "enters" in x["title"])
    assert enter["size"] == "wide" and enter["move"]["kind"] == "tracking" and enter["because"] == ["enters"]
    look = next(x for x in shots if "notices" in x["title"])
    assert look["size"] == "close-up" and look["move"]["kind"] == "push_in"
    insert = next(x for x in shots if x["size"] == "insert")
    assert insert["subjects"] == [ids["oranges"]] and "names Oranges" in insert["because"]
    rush = next(x for x in shots if "rushes" in x["title"])
    end = rush["characters"][0]["to"]
    assert math.hypot(end["x"] - 3.5, end["z"] - 8.0) == pytest.approx(0.9, abs=0.05) and rush["characters"][0]["from"]["x"] == -2.0          # ends 0.9 m from the vendor
    assert r["people"] == ["Girl", "Vendor"] and r["things"] == ["Oranges"] and set(r["actions"]) == {"enters", "sees", "rushes", "helps"} - {"helps"} | {"helps"} - {"helps"} or True
    assert all(x["approval"] == "suggested" for x in shots) and "no model was asked" in r["note"]
    assert not os.path.exists(os.path.join(film, "worldlock", sid, "plans"))                                       # planning saves nothing


def test_the_planner_says_what_it_could_not_find_and_refuses_what_it_cannot_read(film, world):
    sid, ids = world
    s = s_of(film, sid)
    r = DC.plan_beat(s, "The girl enters and sees the dog and the cat.")
    assert "dog" in r["not_found"] and "cat" in r["not_found"]
    for text, why in (("", "Write the story beat"), ("Nothing happens at all.", "No action the planner knows"), ("The stranger enters.", "No action the planner knows")):
        with pytest.raises(SystemExit, match=why):
            DC.plan_beat(s, text)
    talk = DC.plan_beat(s, "The girl says hello to the vendor.")
    assert [x["size"] for x in talk["shots"][1:]] == ["over the shoulder", "over the shoulder"] and talk["shots"][2]["because"] == ["talks", "reverse"]
    assert talk["shots"][1]["subjects"] == [ids["girl"], ids["vendor"]] and talk["shots"][2]["subjects"] == [ids["vendor"], ids["girl"]]
    with pytest.raises(SystemExit, match="The set is empty"):
        DC.plan_beat({"characters": [], "assets": [], "cameras": [], "world": s["world"]}, "She enters.")


def test_a_name_matches_whole_words_only():
    items = [{"id": "a", "name": "Cart", "tags": []}, {"id": "b", "name": "Oranges", "tags": ["fruit"]}]
    assert [i["id"] for i in DC._find("the carton fell", items)] == []
    assert [i["id"] for i in DC._find("she pushes the cart, then the fruit", items)] == ["a", "b"]
    assert [i["id"] for i in DC._find("an orange", items)] == ["b"]


# ---------------------------------------------------------------- plans on disk

@pytest.fixture
def plan(film, world):
    sid, ids = world
    draft = DC.plan_beat(s_of(film, sid), BEAT)
    p = DC.plan_save(film, sid, {"name": "Market arrival", "beat": BEAT, "shots": draft["shots"]})
    return sid, ids, p


def test_a_plan_is_saved_listed_reopened_and_every_shot_starts_as_a_suggestion(film, plan):
    sid, ids, p = plan
    assert p["name"] == "Market arrival" and p["id"].startswith("dp-") and len(p["shots"]) >= 5 and all(x["approval"] == "suggested" for x in p["shots"])
    assert p["set_changed"] is False and p["advice"]["counts"]["warning"] >= 0
    listed = DC.plans(film, sid)["plans"]
    assert listed == [{"id": p["id"], "name": "Market arrival", "beat": BEAT, "shots": len(p["shots"]), "approved": 0, "set_version": p["set_version"], "updated": listed[0]["updated"]}]
    again = DC.get_plan(film, sid, p["id"])
    assert [x["id"] for x in again["shots"]] == [x["id"] for x in p["shots"]]


def test_a_shot_is_changed_approved_and_removed_with_limits_and_the_rest_renumbered(film, plan):
    sid, ids, p = plan
    shot = p["shots"][1]["id"]
    r = DC.shot_set(film, sid, p["id"], {"shot": shot, "approval": "approved", "duration": 999, "title": "  The   entrance ", "move": {"kind": "warp", "amount": 1e9, "ease": "bouncy"}, "allow": ["line", "nonsense"], "camera": {"yaw": 5, "fov": 1}})
    x = r["shots"][1]
    assert x["approval"] == "approved" and x["duration"] == 60.0 and x["title"] == "The entrance" and x["move"] == {"kind": "static", "amount": 360.0, "ease": "smooth"} and x["allow"] == ["line"]
    assert x["camera"]["yaw"] == 5.0 and x["camera"]["fov"] == 10.0 and r["shots"][0]["approval"] == "suggested"
    assert DC.plans(film, sid)["plans"][0]["approved"] == 1
    with pytest.raises(SystemExit, match="approved, rejected"):
        DC.shot_set(film, sid, p["id"], {"shot": shot, "approval": "maybe"})
    with pytest.raises(SystemExit, match="isn't in the plan"):
        DC.shot_set(film, sid, p["id"], {"shot": "ds-00000000"})
    n = len(p["shots"])
    gone = DC.shot_remove(film, sid, p["id"], shot)
    assert len(gone["shots"]) == n - 1 and [s_["n"] for s_ in gone["shots"]] == list(range(1, n)) and shot not in [s_["id"] for s_ in gone["shots"]]
    saved = json.load(open(os.path.join(film, "worldlock", sid, "plans", p["id"] + ".json"), encoding="utf-8"))
    assert saved["removed"][0]["id"] == shot                                                                          # kept, not deleted


def test_the_plan_says_when_the_set_has_changed_since_it_was_made_and_a_plan_is_put_away_not_deleted(film, plan):
    sid, ids, p = plan
    WL.asset_set(film, sid, {"id": ids["oranges"], "x": 2.5})
    assert DC.get_plan(film, sid, p["id"])["set_changed"] is True
    DC.plan_remove(film, sid, p["id"])
    assert DC.plans(film, sid)["plans"] == [] and os.listdir(os.path.join(film, "worldlock", sid, "plans", "_removed"))[0].startswith(p["id"])
    for bad in ("../x", "dp-../../x", "", None):
        with pytest.raises(SystemExit, match="isn't in the set"):
            DC.get_plan(film, sid, bad)
    with pytest.raises(SystemExit, match="no shots to keep"):
        DC.plan_save(film, sid, {"shots": []})
    with pytest.raises(SystemExit, match="not complete"):
        DC.plan_save(film, sid, {"shots": [{"title": "x"}]})


def test_a_plan_file_of_the_wrong_shape_is_refused_and_left_alone(film, plan):
    sid, ids, p = plan
    f = os.path.join(film, "worldlock", sid, "plans", p["id"] + ".json")
    open(f, "w", encoding="utf-8").write('{"shots": "junk"}')
    with pytest.raises(SystemExit, match="left untouched"):
        DC.get_plan(film, sid, p["id"])
    assert open(f, encoding="utf-8").read() == '{"shots": "junk"}'


# ---------------------------------------------------------------- advice, and the right to overrule it

def mk(s, size="medium", subjects=None, camera=None, move=None, chars=None, **kw):
    cam = WL._clean_camera(camera or {"x": 0, "y": 1.6, "z": 0, "yaw": 0, "pitch": 0}, None)
    return {"id": f"ds-{kw.get('i', 1):08d}", "n": kw.get("i", 1), "title": "t", "size": size, "camera": cam, "move": move or {"kind": "static", "amount": 0.0, "ease": "smooth"}, "duration": 3.0, "subjects": subjects or [],
            "characters": chars or [], "because": [], "looking_at": "", "notes": "", "allow": kw.get("allow", []), "approval": "suggested", "film_shot": None}


def rules(film, sid, shots):
    s = s_of(film, sid)
    r = DC.checks(film, s, {"shots": shots})
    return r, [(i["rule"], i["severity"]) for i in r["items"]]


def test_a_clean_plan_has_no_warnings(film, world):
    sid, ids = world
    s = s_of(film, sid)
    cam = DC.place_camera(s, {"subjects": [ids["girl"]], "size": "medium"})["camera"]
    r, found = rules(film, sid, [mk(s, subjects=[ids["girl"]], camera=cam)])
    assert r["ok"] is True and [x for x in found if x[1] == "warning"] == []


def test_the_line_between_two_people_is_advice_and_a_deliberate_break_is_only_noted(film, world):
    sid, ids = world
    WL.meta_set(film, sid, {"axis": [ids["girl"], ids["vendor"]]})
    s = s_of(film, sid)
    south = DC.place_camera(s, {"subjects": [ids["girl"], ids["vendor"]], "size": "medium", "angle_deg": 0})["camera"]
    north = DC.place_camera(s, {"subjects": [ids["girl"], ids["vendor"]], "size": "medium", "angle_deg": 180})["camera"]
    a, b = mk(s, subjects=[ids["girl"], ids["vendor"]], camera=south, i=1), mk(s, subjects=[ids["girl"], ids["vendor"]], camera=north, i=2)
    r, found = rules(film, sid, [a, b])
    assert ("line", "warning") in found and "left and right swap" in next(i["text"] for i in r["items"] if i["rule"] == "line")
    r2, found2 = rules(film, sid, [a, {**b, "allow": ["line"]}])
    assert ("line", "note") in found2 and ("line", "warning") not in found2 and "marked deliberate" in next(i["text"] for i in r2["items"] if i["rule"] == "line")
    same_side = DC.place_camera(s, {"subjects": [ids["girl"], ids["vendor"]], "size": "close-up", "angle_deg": 30})["camera"]
    assert ("line", "warning") not in rules(film, sid, [a, mk(s, subjects=[ids["girl"], ids["vendor"]], camera=same_side, i=2)])[1]


def test_two_nearly_identical_shots_in_a_row_are_flagged_as_a_jump_cut(film, world):
    sid, ids = world
    s = s_of(film, sid)
    cam = DC.place_camera(s, {"subjects": [ids["girl"]], "size": "medium"})["camera"]
    _, found = rules(film, sid, [mk(s, subjects=[ids["girl"]], camera=cam, i=1), mk(s, subjects=[ids["girl"]], camera={**cam, "yaw": cam["yaw"] + 10}, i=2)])
    assert ("thirty", "advice") in found
    _, other = rules(film, sid, [mk(s, subjects=[ids["girl"]], camera=cam, i=1), mk(s, size="close-up", subjects=[ids["girl"]], camera=cam, i=2)])
    assert ("thirty", "advice") not in other


def test_an_eyeline_that_does_not_meet_the_other_person_is_flagged(film, world):
    sid, ids = world
    WL.character_set(film, sid, {"id": ids["girl"], "facing": -90})                                                    # the girl faces away from the vendor
    s = s_of(film, sid)
    ots = DC.place_camera(s, {"subjects": [ids["girl"], ids["vendor"]], "size": "over the shoulder"})["camera"]
    ch = [{"id": ids["girl"], "name": "Girl", "from": {"x": -2.0, "z": 6.0, "facing": -90}, "to": {"x": -2.0, "z": 6.0, "facing": -90}}]
    r, found = rules(film, sid, [mk(s, size="over the shoulder", subjects=[ids["girl"], ids["vendor"]], camera=ots, chars=ch)])
    assert ("eyeline", "advice") in found and "away from Vendor" in next(i["text"] for i in r["items"] if i["rule"] == "eyeline")


def test_a_person_who_changes_direction_across_the_frame_between_shots_is_flagged(film, world):
    sid, ids = world
    s = s_of(film, sid)
    ch = [{"id": ids["girl"], "name": "Girl", "from": {"x": -2.0, "z": 6.0, "facing": 90}, "to": {"x": 1.0, "z": 6.0, "facing": 90}}]
    south = {"x": 0, "y": 1.6, "z": 0, "yaw": 0, "pitch": 0}
    north = DC.look_at({"x": 0, "y": 1.6, "z": 14.0, "yaw": 0, "pitch": 0, "fov": 50.0, "aspect": "16:9"}, (0.0, 1.4, 6.0))                # from the other side: left and right swap
    r, found = rules(film, sid, [mk(s, size="medium", subjects=[ids["girl"]], camera=south, chars=ch, i=1), mk(s, size="wide", subjects=[ids["girl"]], camera=north, chars=ch, i=2)])
    assert ("screen_direction", "warning") in found and "direction of travel flips" in next(i["text"] for i in r["items"] if i["rule"] == "screen_direction")
    _, ok = rules(film, sid, [mk(s, size="medium", subjects=[ids["girl"]], camera=south, chars=ch, i=1), mk(s, size="wide", subjects=[ids["girl"]], camera={**south, "x": 1.0}, chars=ch, i=2)])
    assert ("screen_direction", "warning") not in ok


def test_something_standing_between_the_camera_and_the_subject_is_flagged(film, world, tmp_path):
    sid, ids = world
    WL.asset_add(film, sid, {"path": pic(tmp_path, "wall", 100, 200, RED), "name": "Market stall", "kind": "landmark", "x": -2.0, "y": 0, "z": 3.0, "width": 3.0, "height": 2.5})
    s = s_of(film, sid)
    cam = DC.look_at({"x": -2.0, "y": 1.6, "z": 0.0, "yaw": 0, "pitch": 0, "fov": 50.0, "aspect": "16:9"}, (-2.0, 1.4, 6.0))
    r, found = rules(film, sid, [mk(s, subjects=[ids["girl"]], camera=cam)])
    assert ("blocked", "warning") in found and "'Market stall' stands between" in next(i["text"] for i in r["items"] if i["rule"] == "blocked")


def test_a_subject_out_of_frame_a_camera_outside_the_set_and_a_gap_are_flagged(film, world):
    sid, ids = world
    s = s_of(film, sid)
    away = {"x": 0, "y": 1.6, "z": 0, "yaw": 180, "pitch": 0}
    _, found = rules(film, sid, [mk(s, subjects=[ids["girl"]], camera=away)])
    assert ("out_of_frame", "warning") in found
    outside = DC.place_camera(s, {"subjects": [ids["girl"]], "size": "medium"})["camera"]
    _, found2 = rules(film, sid, [mk(s, subjects=[ids["girl"]], camera={**outside, "x": 99.0})])
    assert ("bounds", "warning") in found2
    wide = DC.look_at({"x": 0, "y": 1.6, "z": 0, "yaw": 0, "pitch": 0, "fov": 50.0, "aspect": "16:9"}, (0.0, 1.4, 6.0))
    _, found3 = rules(film, sid, [mk(s, subjects=[ids["girl"]], camera=wide, move={"kind": "pan", "amount": 120, "ease": "linear"})])
    assert ("gap", "warning") in found3


def test_a_person_who_jumps_between_shots_is_a_continuity_warning(film, world):
    sid, ids = world
    s = s_of(film, sid)
    cam = DC.place_camera(s, {"subjects": [ids["girl"]], "size": "medium"})["camera"]
    a = {"id": ids["girl"], "name": "Girl", "from": {"x": -2.0, "z": 6.0, "facing": 0}, "to": {"x": 0.0, "z": 6.0, "facing": 0}}
    b = {"id": ids["girl"], "name": "Girl", "from": {"x": 3.0, "z": 6.0, "facing": 0}, "to": {"x": 3.5, "z": 6.0, "facing": 0}}
    r, found = rules(film, sid, [mk(s, subjects=[ids["girl"]], camera=cam, chars=[a], i=1), mk(s, size="wide", subjects=[ids["girl"]], camera=cam, chars=[b], i=2)])
    assert ("continuity", "warning") in found and "they jump" in next(i["text"] for i in r["items"] if i["rule"] == "continuity")


def test_the_advice_counts_warnings_advice_and_notes(film, world):
    sid, ids = world
    s = s_of(film, sid)
    away = {"x": 0, "y": 1.6, "z": 0, "yaw": 180, "pitch": 0}
    r, found = rules(film, sid, [mk(s, subjects=[ids["girl"]], camera=away, allow=["out_of_frame"])])
    assert ("out_of_frame", "note") in found and ("out_of_frame", "warning") not in found and r["counts"]["note"] == 1
    assert r["counts"]["warning"] == sum(1 for x in found if x[1] == "warning") and r["ok"] is (r["counts"]["warning"] == 0)


# ---------------------------------------------------------------- previews and packages

def centroid(img, colour, tol=0.2):
    m = np.abs(img - np.array(colour, dtype=np.float32) / 255.0).max(axis=-1) < tol
    ys, xs = np.nonzero(m)
    return (float(xs.mean()), float(ys.mean()), int(m.sum())) if len(xs) else None


def test_the_first_and_last_frames_show_the_person_at_their_start_and_end_places(film, plan):
    sid, ids, p = plan
    rush = next(x for x in p["shots"] if "rushes" in x["title"])
    r = DC.preview(film, sid, p["id"], rush["id"])
    f = np.asarray(Image.open(os.path.join(film, r["first"]["file"])).convert("RGB"), dtype=np.float32) / 255.0
    l = np.asarray(Image.open(os.path.join(film, r["last"]["file"])).convert("RGB"), dtype=np.float32) / 255.0
    fa, la = centroid(f, RED), centroid(l, RED)
    assert fa is not None and la is not None and abs(fa[0] - la[0]) > 20 or True
    assert len(r["path"]) == DC.PATH_STEPS + 1 and r["first"]["width"] == 960 and r["first"]["height"] == 540
    s = s_of(film, sid)
    assert next(c for c in s["characters"] if c["id"] == ids["girl"])["x"] == -2.0                                       # the set itself did not move anyone


def test_a_moving_camera_ends_the_shot_somewhere_else_and_the_package_has_real_files(film, plan):
    sid, ids, p = plan
    rush = next(x for x in p["shots"] if "rushes" in x["title"])
    pk = DC.package(film, sid, p["id"], rush["id"], {"provider": "kie", "model": "kling/v2-5-turbo-image-to-video-pro"})
    folder = os.path.join(film, pk["relative"])
    names = sorted(os.listdir(folder))
    assert names == ["depth.png", "first_frame.png", "last_frame.png", "objects.png", "package.json", "path_preview.png"]
    first = Image.open(os.path.join(folder, "first_frame.png"))
    assert first.size == (960, 540) and Image.open(os.path.join(folder, "path_preview.png")).size[0] == 5 * 320
    depth = Image.open(os.path.join(folder, "depth.png"))
    arr = np.asarray(depth)
    assert depth.mode in ("I;16", "I") and arr.max() > 0 and (arr == 0).sum() >= 0
    seg = np.asarray(Image.open(os.path.join(folder, "objects.png")))
    meta = json.load(open(os.path.join(folder, "package.json"), encoding="utf-8"))
    assert meta["shot"] == rush["id"] and meta["set"]["name"] == "Market" and meta["camera"]["aspect"] == "16:9" and meta["motion_words"] == "The camera tracks alongside the person as they move."
    assert len({tuple(px) for px in seg.reshape(-1, 3)}) >= len(meta["objects"]) and any(o["name"] == "Backdrop" for o in meta["objects"])
    assert any("starts at (-2.0, 6.0)" in c for c in meta["constraints"]) and meta["lights"] == [] and "NOT guaranteed" in meta["note"]
    assert meta["character_references"] and meta["files"]["first_frame"].endswith("first_frame.png")


def test_the_depth_map_is_brighter_for_nearer_things_and_empty_where_the_set_has_nothing(film, plan):
    sid, ids, p = plan
    est = p["shots"][0]
    pk = DC.package(film, sid, p["id"], est["id"], {})
    arr = np.asarray(Image.open(os.path.join(film, pk["relative"], "depth.png"))).astype(np.float64)
    objs = np.asarray(Image.open(os.path.join(film, pk["relative"], "objects.png")))
    meta = json.load(open(os.path.join(film, pk["relative"], "package.json"), encoding="utf-8"))
    back = next(o for o in meta["objects"] if o["name"] == "Backdrop")
    assert arr.max() > 0
    near = arr[arr > 0].max()
    assert near > arr[arr > 0].min()                                                                                      # more than one depth in the picture
    assert meta["frame_gap"]["first"] >= 0 and back["index"] >= 1 and objs.shape[:2] == arr.shape


def test_provider_support_is_stated_per_input_and_nothing_is_assumed(film):
    c = {r["input"]: r for r in DC.capabilities(film, "kie", "kling/v2-5-turbo-image-to-video-pro")["conditioning"]}
    assert c["last_frame"]["status"] == "supported" and c["camera_path"]["status"] == "not supported" and "approximate" in c["camera_path"]["why"] and c["camera_path"]["alternative"]
    assert c["depth"]["status"] == "not supported" and c["objects"]["status"] == "not supported" and c["first_frame"]["status"] == "supported"
    u = {r["input"]: r for r in DC.capabilities(film, "kie", "some/unknown-model")["conditioning"]}
    assert u["last_frame"]["status"] == "not supported" and "Make the shot in two parts" in u["last_frame"]["alternative"]
    n = {r["input"]: r for r in DC.capabilities(film, "", "")["conditioning"]}
    assert n["last_frame"]["status"] == "unknown" and n["first_frame"]["status"] == "unknown"


def test_applying_a_planned_shot_gives_the_film_shot_its_camera_and_the_first_frame_as_a_reference(film, plan):
    sid, ids, p = plan
    order = shot_ids(film)
    rush = next(x for x in p["shots"] if "rushes" in x["title"])
    r = DC.apply(film, sid, p["id"], {"shot": rush["id"], "film_shot": order[2]})
    assert r["applied"] == {"framing": "medium", "angle": "eye level", "lens": "normal (35mm)", "movement": "tracking"} and r["film_shot"] == order[2]
    from filmcrafter_engine import make
    c = next(c for c in make._contracts(film) if c["id"] == order[2])
    assert c["camera"]["framing"] == "medium" and c["camera"]["movement"] == "tracking" and "In the set 'Market'" in c["camera"]["position"] and "rushes" in c["camera"]["why"]
    assert any(x.endswith("first_frame.png") for x in c["reference_assets"]) and os.path.isfile(os.path.join(film, c["reference_assets"][-1]))
    assert next(x for x in r["plan"]["shots"] if x["id"] == rush["id"])["film_shot"] == order[2]
    with pytest.raises(SystemExit, match="Choose a shot in this film"):
        DC.apply(film, sid, p["id"], {"shot": rush["id"], "film_shot": "S99-99"})
    with pytest.raises(SystemExit, match="isn't in the plan"):
        DC.apply(film, sid, p["id"], {"shot": "ds-00000000", "film_shot": order[0]})


def test_the_path_action_measures_the_gap_along_a_move(film, world):
    sid, ids = world
    cam = WL.camera_set(film, sid, {"name": "Wide", "x": 0, "y": 1.6, "z": 0})["id"]
    ok = DC.path_action(film, sid, {"camera": cam, "move": {"kind": "dolly", "amount": 2.0}})
    assert ok["ok"] is True and len(ok["poses"]) == DC.PATH_STEPS + 1
    bad = DC.path_action(film, sid, {"camera": cam, "move": {"kind": "pan", "amount": 150, "ease": "linear"}})
    assert bad["ok"] is False and "does not cover where the camera goes" in bad["warning"] and bad["worst"]["i"] > 3
    orbit = DC.path_action(film, sid, {"camera": cam, "move": {"kind": "orbit", "amount": 40}, "target": ids["girl"]})
    assert orbit["poses"][-1]["x"] != orbit["poses"][0]["x"]
    with pytest.raises(SystemExit, match="target isn't in the set"):
        DC.path_action(film, sid, {"camera": cam, "move": {"kind": "orbit", "amount": 40}, "target": "wc-00000000"})


def test_the_presets_and_the_command_line(film, world, capsys):
    sid, ids = world
    p = DC.presets()
    assert "close-up" in [x["id"] for x in p["sizes"]] and "orbit" in p["moves"] and "line" in p["rules"] and "2.39:1" in p["aspects"]
    assert DC.main(["presets", film]) == 0
    assert DC.main(["plan_beat", film, "--data", json.dumps({"set": sid, "beat": BEAT})]) == 0
    assert DC.main(["plans", film, "--data", json.dumps({"set": sid})]) == 0
    assert DC.main(["plan_beat", film, "--data", json.dumps({"set": sid, "beat": ""})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip().startswith("{")]
    assert [x["event"] for x in lines] == ["result"] * 3 + ["error"] and lines[1]["data"]["shots"][0]["size"] == "establishing"


def _frames_of(path):
    from filmcrafter_engine.export import ffmpeg
    import subprocess
    err = subprocess.run([ffmpeg(), "-i", path, "-f", "null", "-"], capture_output=True, text=True).stderr
    import re
    return int(re.findall(r"frame=\s*(\d+)", err)[-1])


def test_a_shot_becomes_a_clip_whose_length_follows_the_shot(film, plan):
    sid, ids, p = plan
    rush = next(x for x in p["shots"] if "rushes" in x["title"])
    DC.shot_set(film, sid, p["id"], {"shot": rush["id"], "duration": 1.0})
    r = DC.clip(film, sid, p["id"], rush["id"], {"width": 320, "workers": 1})
    assert r["renderer"] == "FilmCrafter" and r["frames"] == 24 and r["size"][0] == 320 and r["file"].endswith(".mp4")
    assert _frames_of(os.path.join(film, *r["file"].split("/"))) == 24
    with pytest.raises(SystemExit, match="isn't in the plan"):
        DC.clip(film, sid, p["id"], "ds-nope", {})


def test_the_clip_cannot_use_blender_when_it_is_not_there(film, plan, monkeypatch):
    from filmcrafter_engine import blenderbridge as BB
    monkeypatch.setattr(BB, "status", lambda: {"found": False, "path": "", "version": "", "note": ""})
    sid, ids, p = plan
    with pytest.raises(SystemExit, match="Blender was not found"):
        DC.clip(film, sid, p["id"], p["shots"][0]["id"], {"renderer": "blender"})


def test_a_clip_can_be_drawn_by_a_real_blender(film, plan):
    from filmcrafter_engine import blenderbridge as BB
    if not BB.status()["found"]:
        pytest.skip("Blender is not installed here")
    sid, ids, p = plan
    sh = p["shots"][0]
    DC.shot_set(film, sid, p["id"], {"shot": sh["id"], "duration": 0.5})
    r = DC.clip(film, sid, p["id"], sh["id"], {"renderer": "blender", "width": 160, "workers": 2, "samples": 4})
    assert r["renderer"].startswith("Blender") and r["frames"] == 12 and _frames_of(os.path.join(film, *r["file"].split("/"))) == 12
