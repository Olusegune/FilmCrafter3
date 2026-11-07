"""The continuity inspector on a real film and a real set: every finding is built from a situation made on purpose and checked against what the geometry says. The picture comparison is checked on pictures made from
the set's own render, so the right answer is known."""
import json
import os
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from filmcrafter_engine import bible, setcontinuity as SC, shots as S, story, worldlock as WL  # noqa: E402
from test_worldlock import BLUE, GREEN, RED, YELLOW, pic, shot_ids  # noqa: E402

SCRIPT = "INT. KITCHEN - DAY\n\nSARAH stirs a pot. TOM watches her.\n\nSARAH\nBreakfast is ready.\n\nEXT. MARKET - DAY\n\nSARAH carries a basket.\n\nINT. HALL - NIGHT\n\nSARAH sits alone.\n"


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


@pytest.fixture
def world(film, tmp_path):
    """Two cameras: A looks along +z (at the basket and Sarah); B looks the other way (at nothing but the far wall behind it)."""
    sid = WL.create(film, {"name": "Market"})["id"]
    ids = {}
    ids["wall"] = WL.asset_add(film, sid, {"path": pic(tmp_path, "wall", 600, 200, BLUE), "name": "Wall", "y": 0, "z": 14, "width": 30, "height": 8})["id"]
    ids["basket"] = WL.asset_add(film, sid, {"path": pic(tmp_path, "bk", 80, 60, YELLOW), "name": "Basket", "kind": "prop", "x": 1.0, "y": 0, "z": 6, "width": 0.8, "height": 0.6})["id"]
    ids["pic"] = WL.asset_add(film, sid, {"path": pic(tmp_path, "sp", 60, 120, RED), "name": "Sarah picture", "kind": "prop", "x": 50, "z": 50, "width": 0.5, "height": 1.7})["id"]
    ids["sarah"] = WL.character_set(film, sid, {"name": "Sarah", "x": -1.5, "z": 6.0, "facing": 90, "asset": ids["pic"]})["id"]
    camA = WL.camera_set(film, sid, {"name": "A", "x": 0, "y": 1.6, "z": 0, "yaw": 0, "fov": 60})
    ids["A"] = camA["cameras"][-1]["id"] if camA["cameras"][-1]["name"] == "A" else next(c["id"] for c in camA["cameras"] if c["name"] == "A")
    camB = WL.camera_set(film, sid, {"name": "B", "x": 0, "y": 1.6, "z": -10, "yaw": 180, "fov": 60})
    ids["B"] = next(c["id"] for c in camB["cameras"] if c["name"] == "B")
    return sid, ids


def use(film, sid, shot, cam):
    WL.shot_camera(film, sid, {"shot": shot, "camera": cam})


def kinds(r, live=True):
    return sorted({f["kind"] for f in r["findings"] if not (live and f["overridden"])})


def test_the_timeline_says_what_is_where_and_what_the_camera_sees(film, world):
    sid, ids = world
    order = shot_ids(film)
    use(film, sid, order[0], ids["A"])
    use(film, sid, order[1], ids["B"])
    r = SC.inspect(film, sid)
    assert [t["shot"] for t in r["timeline"]] == order
    t0 = r["timeline"][0]
    assert t0["camera"]["name"] == "A"
    basket = next(t for t in t0["things"] if t["name"] == "Basket")
    assert basket["in_frame"] is True and basket["x"] == 1.0
    assert next(t for t in r["timeline"][1]["things"] if t["name"] == "Basket")["in_frame"] is False        # camera B looks the other way
    assert order[2] in r["shots_without_camera"] and r["basis"].startswith("Worked out from the set's own data")


def test_a_change_where_the_camera_does_not_look_is_called_off_screen(film, world):
    sid, ids = world
    order = shot_ids(film)
    use(film, sid, order[0], ids["A"])
    use(film, sid, order[1], ids["B"])
    use(film, sid, order[2], ids["A"])
    WL.event_set(film, sid, {"shot": order[1], "asset": ids["basket"], "kind": "move", "to": {"x": -1.0, "z": 6.0}, "state": "on the floor"})
    r = SC.inspect(film, sid)
    f = next(f for f in r["findings"] if f["kind"] == "unseen_change")
    assert f["shots"] == [order[1]] and "off screen" in f["text"] and f["severity"] == "advice" and "Basket" in f["text"]


def test_a_change_the_camera_does_see_is_not_a_finding(film, world):
    sid, ids = world
    order = shot_ids(film)
    for o in order[:3]:
        use(film, sid, o, ids["A"])
    WL.event_set(film, sid, {"shot": order[1], "asset": ids["basket"], "kind": "move", "to": {"x": -1.0, "z": 6.0}, "state": "on the floor"})
    assert "unseen_change" not in kinds(SC.inspect(film, sid))


def test_something_that_leaves_between_two_shots_unseen_is_a_warning(film, world):
    sid, ids = world
    order = shot_ids(film)
    use(film, sid, order[0], ids["A"])
    use(film, sid, order[1], ids["B"])
    WL.event_set(film, sid, {"shot": order[1], "asset": ids["basket"], "kind": "remove"})
    f = next(f for f in SC.inspect(film, sid)["findings"] if f["kind"] == "vanishes")
    assert f["severity"] == "warning" and f["shots"] == [order[0], order[1]]


def test_something_that_arrives_unseen_is_a_warning(film, world):
    sid, ids = world
    order = shot_ids(film)
    WL.event_set(film, sid, {"shot": order[0], "asset": ids["basket"], "kind": "remove"})        # gone from the start (shot 1's end)
    WL.event_set(film, sid, {"shot": order[1], "asset": ids["basket"], "kind": "appear", "to": {"x": 1.0, "z": 6.0}})
    use(film, sid, order[0], ids["A"])
    use(film, sid, order[1], ids["B"])
    use(film, sid, order[2], ids["A"])
    r = SC.inspect(film, sid)
    assert "appears" in kinds(r)


def test_screen_direction_reverses_when_the_camera_swings_round_without_the_person_turning(film, world):
    sid, ids = world
    order = shot_ids(film)
    WL.character_set(film, sid, {"id": ids["sarah"], "x": 1.0, "z": 6.0})
    use(film, sid, order[0], ids["A"])
    WL.camera_set(film, sid, {"id": ids["B"], "x": 0, "y": 1.6, "z": 12, "yaw": 180})
    use(film, sid, order[1], ids["B"])
    r = SC.inspect(film, sid)
    f = next(f for f in r["findings"] if f["kind"] == "reversed")
    assert "faces right on screen" in f["text"] and "left in shot" in f["text"] and f["severity"] == "warning"


def test_a_person_who_turns_between_shots_does_not_reverse(film, world):
    sid, ids = world
    order = shot_ids(film)
    use(film, sid, order[0], ids["A"])
    WL.camera_set(film, sid, {"id": ids["B"], "x": 0, "y": 1.6, "z": 12, "yaw": 180})
    use(film, sid, order[1], ids["B"])
    WL.event_set(film, sid, {"shot": order[0], "character": ids["sarah"], "kind": "move", "to": {"facing": -90}, "state": "turns"})
    assert "reversed" not in kinds(SC.inspect(film, sid))


def test_people_named_by_the_film_shot_are_checked_against_the_set_and_the_camera(film, world):
    sid, ids = world
    order = shot_ids(film)
    names = {o: [c.lower() for c in next(x for x in S.view(film)["shots"] if x["id"] == o)["characters"]] for o in order}
    shot = next(o for o in order if "sarah" in names[o])
    use(film, sid, shot, ids["B"])                       # Sarah is named but camera B looks away from her
    r = SC.inspect(film, sid)
    assert any(f["kind"] == "out_of_frame" and f["shots"] == [shot] for f in r["findings"])
    tom = next((o for o in order if "tom" in names[o]), None)
    if tom:
        assert any(f["kind"] == "not_in_set" and f["thing"].lower() == "tom" for f in r["findings"])


def test_a_camera_that_sees_nothing_is_a_warning(film, world):
    sid, ids = world
    order = shot_ids(film)
    WL.camera_set(film, sid, {"id": ids["B"], "x": 0, "y": 1.6, "z": -30, "yaw": 180})
    use(film, sid, order[0], ids["B"])
    f = next(f for f in SC.inspect(film, sid)["findings"] if f["kind"] == "empty_view")
    assert f["severity"] == "warning" and "sees nothing" in f["text"]


def test_events_that_contradict_each_other_are_found(film, world):
    sid, ids = world
    order = shot_ids(film)
    WL.event_set(film, sid, {"shot": order[0], "asset": ids["basket"], "kind": "move", "to": {"x": 3.0, "z": 6.0}, "order": 1})
    WL.event_set(film, sid, {"shot": order[0], "asset": ids["basket"], "kind": "move", "to": {"x": -3.0, "z": 6.0}, "order": 1})
    WL.event_set(film, sid, {"shot": order[1], "asset": ids["pic"], "kind": "remove", "order": 1})
    WL.event_set(film, sid, {"shot": order[2], "asset": ids["pic"], "kind": "remove", "order": 1})
    r = SC.inspect(film, sid)
    assert sum(f["kind"] == "conflict" for f in r["findings"]) == 2
    assert any("already gone" in f["text"] for f in r["findings"])


def test_the_sets_own_checks_are_part_of_the_inspection(film, world):
    sid, ids = world
    order = shot_ids(film)
    WL.meta_set(film, sid, {"axis": [ids["sarah"], ids["sarah"]]})
    r = SC.inspect(film, sid)                                         # a set with something wrong WorldLock already knows about still reports
    assert isinstance(r["findings"], list) and r["counts"]["deliberate"] == 0


def test_a_finding_can_be_marked_deliberate_and_stays_marked_without_changing_the_set(film, world):
    sid, ids = world
    order = shot_ids(film)
    use(film, sid, order[0], ids["A"])
    use(film, sid, order[1], ids["B"])
    WL.event_set(film, sid, {"shot": order[1], "asset": ids["basket"], "kind": "remove"})
    before = WL.get(film, sid)["version"]
    r = SC.inspect(film, sid)
    f = next(f for f in r["findings"] if f["kind"] == "vanishes")
    n = r["counts"]["warning"]
    r2 = SC.override(film, sid, f["key"], "She takes it off screen on purpose.")
    g = next(x for x in r2["findings"] if x["key"] == f["key"])
    assert g["overridden"] and g["note"] == "She takes it off screen on purpose." and r2["counts"]["warning"] == n - 1 and r2["counts"]["deliberate"] == 1
    assert SC.inspect(film, sid)["counts"]["deliberate"] == 1                                       # it is kept
    assert WL.get(film, sid)["version"] == before                                                    # the set is untouched
    r3 = SC.override(film, sid, f["key"], on=False)
    assert r3["counts"]["deliberate"] == 0 and r3["counts"]["warning"] == n


def test_a_made_up_key_is_refused(film, world):
    sid, _ = world
    for bad in ("", "x", "ck-zzzzzzzzzz", "ck-123", "../../etc"):
        with pytest.raises(SystemExit, match="not a finding"):
            SC.override(film, sid, bad, "x")


def test_a_set_with_no_cameras_in_shots_has_nothing_to_check_but_says_so(film, world):
    sid, _ = world
    r = SC.inspect(film, sid)
    assert r["counts"]["warning"] == 0 and len(r["shots_without_camera"]) == len(shot_ids(film))


def test_comparing_the_sets_own_picture_with_itself_says_the_layout_matches(film, world, tmp_path):
    sid, ids = world
    order = shot_ids(film)
    use(film, sid, order[0], ids["A"])
    own = WL.render(film, sid, {"camera": ids["A"], "shot": order[0], "size": [480, 270]})["file"]
    r = SC.compare(film, sid, order[0], own)
    assert r["layout_match"] > 0.99 and r["mean_difference"] < 0.01 and "alike" in r["words"] and r["note"].startswith("Advisory only")
    assert Image.open(os.path.join(film, *r["file"].split("/"))).size == (480 * 3, 270)


def test_a_different_picture_differs_and_the_viewer_says_where(film, world, tmp_path):
    sid, ids = world
    order = shot_ids(film)
    use(film, sid, order[0], ids["A"])
    own = Image.open(os.path.join(film, *WL.render(film, sid, {"camera": ids["A"], "shot": order[0], "size": [480, 270]})["file"].split("/"))).convert("RGB")
    other = np.zeros((270, 480, 3), dtype=np.uint8)
    other[:, :] = (200, 40, 40)                                           # a flat red picture: nothing in it where the set has things
    p = str(tmp_path / "gen.png")
    Image.fromarray(other).save(p)
    r = SC.compare(film, sid, order[0], p)
    assert r["mean_difference"] > 0.15 and r["layout_match"] < 0.3 and "quite different" in r["words"] and r["most_different"] in ("top left", "top", "top right", "left", "middle", "right", "bottom left", "bottom", "bottom right")


def test_compare_refuses_what_it_cannot_use(film, world, tmp_path):
    sid, ids = world
    order = shot_ids(film)
    with pytest.raises(SystemExit, match="no camera in the set"):
        SC.compare(film, sid, order[0], str(tmp_path / "x.png"))
    use(film, sid, order[0], ids["A"])
    with pytest.raises(SystemExit, match="Choose a picture"):
        SC.compare(film, sid, order[0], str(tmp_path / "nope.png"))
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a picture")
    with pytest.raises(SystemExit, match="could not be read"):
        SC.compare(film, sid, order[0], str(bad))


def test_the_command_line(film, world, capsys):
    sid, _ = world
    assert SC.main(["inspect", film, "--data", json.dumps({"set": sid})]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["event"] == "result" and "timeline" in out["data"]
    assert SC.main(["override", film, "--data", json.dumps({"set": sid, "key": "nope"})]) == 1
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["event"] == "error"


def test_a_picture_that_draws_a_person_is_not_reported_as_outside_the_set(film, world):
    sid, ids = world
    r = SC.inspect(film, sid)                                  # Sarah's picture is parked at x=50 on purpose
    assert not any(f["kind"] == "set_outside" and f["thing"] == ids["pic"] for f in r["findings"])
