"""Sound design: soundscape profiles and Foley events, turned into the film's ordinary audio cues. Real audio and the real mixer; no provider, no cost."""
import json
import os

import numpy as np
import pytest
import soundfile as sf

from filmcrafter_engine import audiocues as Q, audiolib as AL, audiomix as M, bible, shots as S, sounddesign as SD, story

SCRIPT = ("INT. KITCHEN - NIGHT\n\nRain on a tin roof. MAMA stirs a steaming pot while LILA walks in and drops a basket of oranges on wet pavement. The door slams.\n\nMAMA\nCareful!\n\n"
          "EXT. YARD - DAY\n\nChildren play in the schoolyard.\n")
RATE = M.RATE


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def tone(path, secs, hz=1000, amp=0.3, rate=22050):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    t = np.arange(int(rate * secs)) / rate
    sf.write(path, (amp * np.sin(2 * np.pi * hz * t)).astype("float32"), rate)
    return path


def asset(film, tmp_path, name, secs=1.0, hz=1000, amp=0.3, category=None):
    return AL.import_files(film, "sfx", [tone(str(tmp_path / "src" / name), secs, hz, amp)], category)["assets"][-1]


def shot1(film):
    return next(s for s in S.view(film)["shots"] if int(s["scene"]) == 1)["id"]


def env1(film):
    return next(e for e in bible.load(film)["environments"] if 1 in e["scenes"])["id"]


def cues(film):
    return {c["id"]: c for c in Q.listing(film)["cues"]}


# ---------------------------------------------------------------- suggesting only what the action names

def test_only_sounds_the_written_action_names_are_proposed_with_their_words(film):
    r = SD.suggest(film, shot1(film))
    got = {p["action"]: p for p in r["proposals"]}
    assert set(got) == {"stirring", "footsteps", "impact", "door"}
    assert got["stirring"]["source_object"] == "steaming pot" and got["stirring"]["material"] == "metal" and got["stirring"]["by"] == "MAMA"
    assert got["impact"]["source_object"] == "basket of oranges" and got["impact"]["by"] == "LILA" and got["impact"]["surface"] == "wet pavement" and got["impact"]["intensity"] > got["footsteps"]["intensity"]
    assert got["door"]["by"] == "" and "slams" in got["door"]["motivated_by"]                 # nobody is named in that sentence: nobody is guessed
    assert all(p["motivated_by"] for p in r["proposals"]) and "Only sounds the written action names" in r["note"]


def test_quiet_movement_that_is_not_named_gets_no_sound(film):
    yard = next(s for s in S.view(film)["shots"] if int(s["scene"]) == 2)["id"]
    assert SD.suggest(film, yard)["proposals"] == []


def test_a_busy_action_is_cut_to_the_most_dramatic_few(film):
    c = next(c for c in __import__("filmcrafter_engine.make", fromlist=["x"])._contracts(film) if c["scene"] == 1)
    big = "He slams the door. She drops a plate. He drops a cup. She drops a glass. He knocks over a chair. She stirs a pot. He pours tea. She drags a table. He walks. She runs. He lifts a crate."
    from filmcrafter_engine import shots as SH
    SH.set_fields(film, c["id"], {"action": big})
    out = SD.suggest(film, c["id"])
    assert len(out["proposals"]) <= SD.MAX_EVENTS_PER_SHOT and out["considered"] > len(out["proposals"])
    kinds = {p["action"] for p in out["proposals"]}
    assert "impact (hard)" in kinds or "door" in kinds                                          # the loud, story-changing sounds survive the cut
    assert "handling" not in kinds


def test_suggesting_saves_nothing_and_asks_no_one(film):
    SD.suggest(film, shot1(film))
    assert not os.path.exists(SD._path(film))
    with pytest.raises(SystemExit, match="isn't in the film"):
        SD.suggest(film, "S99-99")


# ---------------------------------------------------------------- distance and side become a level and a balance

def test_distance_intensity_and_side_become_a_level_and_a_balance():
    assert SD.placement({"distance": "near", "intensity": 0.5, "side": "centre"}) == {"gain_db": 0.0, "pan": 0.0}
    assert SD.placement({"distance": "far", "intensity": 0.5, "side": "left"}) == {"gain_db": -14.0, "pan": -0.6}
    assert SD.placement({"distance": "mid", "intensity": 1.0, "side": "right"}) == {"gain_db": -3.0, "pan": 0.6}
    assert SD.placement({"distance": "mid", "level_db": -200})["gain_db"] == Q.GAIN[0]
    assert SD.placement({"distance": "nonsense", "side": "nowhere"}) == {"gain_db": 0.0, "pan": 0.0}


# ---------------------------------------------------------------- profiles belong to the place

def test_a_profile_is_cleaned_and_its_layers_keep_their_ids(film, tmp_path):
    a = asset(film, tmp_path, "rain.wav", 3.0, category="ambience")
    e = env1(film)
    r = SD.profile_set(film, e, {"interior": True, "weather": "heavy rain", "room_size": "huge", "reverb": "cathedral", "materials": ["Tin", "tin", "wood"], "surfaces": ["wet pavement"],
                                 "layers": [{"name": "Rain on the roof", "distance": "near", "level_db": -3, "asset_id": a["id"]}, {"name": "", "distance": "far"}, {"name": "Generator", "distance": "orbit", "level_db": 99}],
                                 "recurring": "the generator coughs now and then"})
    p = r["profile"]
    assert p["interior"] is True and p["room_size"] == "" and p["reverb"] == "" and p["materials"] == ["tin", "wood"]
    assert [l["name"] for l in p["layers"]] == ["Rain on the roof", "Generator"] and p["layers"][1]["distance"] == "mid" and p["layers"][1]["level_db"] == 6.0
    ids = [l["id"] for l in p["layers"]]
    assert all(i.startswith("ly-") for i in ids)
    again = SD.profile_set(film, e, {"layers": [{"id": ids[0], "name": "Rain, softer", "distance": "far", "asset_id": a["id"]}]})["profile"]
    assert again["layers"][0]["id"] == ids[0] and again["layers"][0]["name"] == "Rain, softer"


def test_a_layer_cannot_name_a_sound_that_is_not_in_the_library_and_places_must_exist(film):
    with pytest.raises(SystemExit, match="not in this film's library"):
        SD.profile_set(film, env1(film), {"layers": [{"name": "Rain", "asset_id": "a-00000000"}]})
    with pytest.raises(SystemExit, match="isn't in the Production Bible"):
        SD.profile_set(film, "e_nowhere", {})


def test_layers_are_capped(film):
    r = SD.profile_set(film, env1(film), {"layers": [{"name": f"L{i}"} for i in range(40)]})
    assert len(r["profile"]["layers"]) == SD.MAX_LAYERS


# ---------------------------------------------------------------- events

def test_an_event_is_validated_and_tied_to_a_shot(film):
    s = shot1(film)
    r = SD.event_add(film, {"shot": s, "action": "impact", "source_object": "basket", "distance": "orbit", "side": "up", "intensity": 7, "start": 9999})
    ev = r["events"][0]
    assert ev["scene"] == 1 and ev["distance"] == "mid" and ev["side"] == "centre" and ev["intensity"] == 1.0 and ev["start"] == round(next(x["duration"] for x in S.view(film)["shots"] if x["id"] == s) - 0.1, 2) and ev["approval"] == "suggested" and ev["asset_id"] is None
    assert ev["id"].startswith("fx-") and r["coverage"]["without_sound"] == [ev["id"]]
    for bad in ({"shot": "S99-99", "action": "x"}, {"shot": s, "action": ""}, {"action": "x"}):
        with pytest.raises(SystemExit):
            SD.event_add(film, bad)
    with pytest.raises(SystemExit, match="not in this film's library"):
        SD.event_add(film, {"shot": s, "action": "x", "asset_id": "a-00000000"})


def test_removing_an_event_moves_it_aside_and_takes_its_cue_out_of_the_plan(film, tmp_path):
    a = asset(film, tmp_path, "hit.wav")
    s = shot1(film)
    eid = SD.event_add(film, {"shot": s, "action": "impact", "asset_id": a["id"], "approval": "approved"})["id"]
    SD.to_cues(film, 1)
    cid = SD._load(film)["events"][0]["cue_id"]
    assert cid in cues(film)
    SD.event_remove(film, eid)
    assert SD._load(film)["events"] == [] and SD._load(film)["removed"][0]["id"] == eid and cid not in cues(film)
    assert os.path.isfile(os.path.join(film, *AL.load(film)["assets"][0]["file"].split("/")))      # the sound itself stays
    with pytest.raises(SystemExit, match="isn't in the film"):
        SD.event_update(film, eid, {"note": "x"})
    with pytest.raises(SystemExit, match="not valid"):
        SD.event_remove(film, "../x")


def test_the_library_is_searched_before_anything_is_made(film, tmp_path):
    a = AL.import_files(film, "sfx", [tone(str(tmp_path / "src" / "pot stir.wav"), 1.0)], "foley")["assets"][-1]
    AL.update(film, a["id"], {"tags": ["metal", "stirring"], "description": "a spoon stirring a metal pot"})
    eid = SD.event_add(film, {"shot": shot1(film), "action": "stirring", "source_object": "pot", "material": "metal"})["id"]
    assert [c["id"] for c in SD.candidates(film, eid)["candidates"]] == [a["id"]]


# ---------------------------------------------------------------- into the mix as ordinary cues

def setup_scene(film, tmp_path):
    rain = asset(film, tmp_path, "rain.wav", 2.0, 300, category="ambience")
    hit = asset(film, tmp_path, "hit.wav", 0.5, 1500)
    s = shot1(film)
    SD.profile_set(film, env1(film), {"layers": [{"name": "Rain", "distance": "mid", "level_db": -4, "asset_id": rain["id"]}, {"name": "Generator", "distance": "far"}]})
    eid = SD.event_add(film, {"shot": s, "action": "impact", "source_object": "basket", "start": 1.0, "distance": "near", "side": "left", "intensity": 0.5, "asset_id": hit["id"], "approval": "approved"})["id"]
    return rain, hit, s, eid


def test_layers_and_approved_events_with_sounds_become_cues_and_the_rest_wait(film, tmp_path):
    rain, hit, s, eid = setup_scene(film, tmp_path)
    SD.event_add(film, {"shot": s, "action": "door", "approval": "approved"})              # approved, but no sound yet
    SD.event_add(film, {"shot": s, "action": "step", "asset_id": hit["id"]})               # has a sound, but only suggested
    r = SD.to_cues(film, 1)
    assert len(r["made"]) == 2 and r["updated"] == []
    assert sorted(w["kind"] for w in r["waiting"]) == ["event", "layer"]
    cs = list(cues(film).values())
    amb = next(c for c in cs if c["kind"] == "ambience")
    fx = next(c for c in cs if c["kind"] == "sfx")
    assert amb["shot"] is None and amb["scene"] == 1 and amb["loop"] is True and amb["gain_db"] == -10.0 and amb["approval"] == "approved"
    assert fx["shot"] == s and fx["start"] == 1.0 and fx["gain_db"] == 0.0 and fx["pan"] == -0.6 and fx["loop"] is False and "Foley" in fx["note"]
    assert len(cs) == 2


def test_doing_it_again_updates_the_same_cues_and_a_change_touches_only_its_own(film, tmp_path):
    rain, hit, s, eid = setup_scene(film, tmp_path)
    SD.to_cues(film, 1)
    before = {c["id"]: dict(c) for c in cues(film).values()}
    again = SD.to_cues(film, 1)
    assert again["made"] == [] and len(again["updated"]) == 2 and set(cues(film)) == set(before)
    SD.event_update(film, eid, {"start": 2.5, "side": "right", "distance": "far"})
    SD.to_cues(film, 1)
    after = cues(film)
    ev_cue = SD._load(film)["events"][0]["cue_id"]
    amb_cue = SD._load(film)["profiles"][env1(film)]["layers"][0]["cue_id"]
    assert after[ev_cue]["start"] == 2.5 and after[ev_cue]["pan"] == 0.6 and after[ev_cue]["gain_db"] == -14.0
    assert after[amb_cue]["gain_db"] == before[amb_cue]["gain_db"] and after[amb_cue]["id"] == amb_cue          # the ambience was not touched


def test_the_places_ambience_is_one_scene_wide_cue_whatever_the_camera_does(film, tmp_path):
    rain, hit, s, eid = setup_scene(film, tmp_path)
    SD.to_cues(film, 1)
    amb = next(c for c in cues(film).values() if c["kind"] == "ambience")
    for i in range(3):
        SD.event_add(film, {"shot": s, "action": f"step {i}", "asset_id": hit["id"], "approval": "approved"})
    SD.to_cues(film, 1)
    assert [c["id"] for c in cues(film).values() if c["kind"] == "ambience"] == [amb["id"]]
    assert cues(film)[amb["id"]]["shot"] is None


def test_a_swapped_sound_replaces_the_one_in_the_cue_without_a_second_cue(film, tmp_path):
    rain, hit, s, eid = setup_scene(film, tmp_path)
    SD.to_cues(film, 1)
    other = asset(film, tmp_path, "hit2.wav", 0.4, 900)
    SD.event_update(film, eid, {"asset_id": other["id"]})
    SD.to_cues(film, 1)
    fx = [c for c in cues(film).values() if c["kind"] == "sfx"]
    assert len(fx) == 1 and fx[0]["asset_id"] == other["id"]


def test_the_scene_view_reports_what_is_missing(film, tmp_path):
    rain, hit, s, eid = setup_scene(film, tmp_path)
    SD.event_add(film, {"shot": s, "action": "door"})
    v = SD.scene(film, 1)
    assert v["environment"]["id"] == env1(film) and v["coverage"]["has_profile"] is True and v["coverage"]["events"] == 2 and v["coverage"]["approved"] == 1
    assert len(v["coverage"]["without_sound"]) == 1 and len(v["coverage"]["layers_without_sound"]) == 1
    assert v["events"][0]["placement"]["pan"] in (-0.6, 0.0)
    y = SD.scene(film, 2)
    assert y["coverage"]["has_profile"] is False and y["events"] == []


# ---------------------------------------------------------------- the real mixer: balance and distance

def mix(film, tmp_path):
    out, at = {}, 0.0
    for s in sorted([x for x in S.view(film)["shots"] if x["scene"] == 1], key=lambda x: x["index"]):
        out[s["id"]] = (at, at + s["duration"])
        at += s["duration"]
    base = str(tmp_path / "base.wav")
    sf.write(base, np.zeros((int(RATE * at), 2), dtype="float32"), RATE, subtype="PCM_16")
    o = str(tmp_path / "mixed.wav")
    r = M.mix_cues(film, base, out, at, o, {"ducking_db": 0, "duck_attack": 0.05, "duck_release": 0.2, "target_lufs": None, "peak_db": -0.1, "mute_lanes": [], "solo": None})
    return r, sf.read(o, dtype="float32", always_2d=True)[0], out


def rms(x, a, b, ch):
    seg = x[int(a * RATE):int(b * RATE), ch]
    return float(np.sqrt(np.mean(np.square(seg))))


def test_pan_gains_never_make_a_sound_louder_and_keep_the_centre():
    assert list(M.pan_gains(0)) == [1.0, 1.0]
    left, right = M.pan_gains(-1), M.pan_gains(1)
    assert left[0] == 1.0 and abs(left[1]) < 1e-6 and right[1] == 1.0 and abs(right[0]) < 1e-6
    for p in np.linspace(-1, 1, 21):
        g = M.pan_gains(p)
        assert g.max() <= 1.0 + 1e-6 and g.min() >= -1e-6


@pytest.mark.parametrize("side,left_louder", [("left", True), ("right", False)])
def test_a_foley_sound_panned_to_a_side_is_heard_on_that_side_in_the_finished_mix(film, tmp_path, side, left_louder):
    hit = asset(film, tmp_path, "hit.wav", 1.0, 1500, amp=0.5)
    SD.event_add(film, {"shot": shot1(film), "action": "impact", "start": 1.0, "distance": "near", "side": side, "intensity": 0.5, "asset_id": hit["id"], "approval": "approved"})
    SD.to_cues(film, 1)
    r, x, _ = mix(film, tmp_path)
    assert r and r["cues"] == 1
    l, rr = rms(x, 1.1, 1.8, 0), rms(x, 1.1, 1.8, 1)
    assert (l > rr * 1.5) if left_louder else (rr > l * 1.5)
    assert min(l, rr) > 0.0


def test_a_far_sound_is_quieter_than_a_near_one_by_the_distance_amount(film, tmp_path):
    hit = asset(film, tmp_path, "hit.wav", 1.0, 1500, amp=0.5)
    s = shot1(film)
    SD.event_add(film, {"shot": s, "action": "near", "start": 0.5, "distance": "near", "intensity": 0.5, "asset_id": hit["id"], "approval": "approved"})
    SD.event_add(film, {"shot": s, "action": "far", "start": 3.0, "distance": "far", "intensity": 0.5, "asset_id": hit["id"], "approval": "approved"})
    SD.to_cues(film, 1)
    _, x, _ = mix(film, tmp_path)
    near, far = rms(x, 0.6, 1.4, 0), rms(x, 3.1, 3.9, 0)
    assert 20 * np.log10(near / far) == pytest.approx(14.0, abs=1.0)


def test_cues_made_before_pan_existed_still_mix_in_the_centre(film, tmp_path):
    hit = asset(film, tmp_path, "hit.wav", 1.0, 1500, amp=0.5)
    cid = Q.add(film, {"asset_id": hit["id"], "scene": 1, "shot": shot1(film), "start": 1.0})["id"]
    p = Q._path(film)
    data = json.load(open(p, encoding="utf-8"))
    for c in data["cues"]:
        c.pop("pan", None)
    json.dump(data, open(p, "w", encoding="utf-8"))
    _, x, _ = mix(film, tmp_path)
    assert rms(x, 1.1, 1.8, 0) == pytest.approx(rms(x, 1.1, 1.8, 1), rel=1e-3) and rms(x, 1.1, 1.8, 0) > 0
    assert Q.listing(film)["cues"][0]["id"] == cid


def test_a_cue_pan_must_be_in_range(film, tmp_path):
    hit = asset(film, tmp_path, "hit.wav")
    with pytest.raises(SystemExit, match="pan"):
        Q.add(film, {"asset_id": hit["id"], "scene": 1, "pan": 2})
    cid = Q.add(film, {"asset_id": hit["id"], "scene": 1, "pan": 0.25})["id"]
    assert cues(film)[cid]["pan"] == 0.25


# ---------------------------------------------------------------- command line

def test_the_command_line_answers_with_json(film, capsys):
    assert SD.main(["suggest", film, "--data", json.dumps({"shot": shot1(film)})]) == 0
    assert SD.main(["scene", film, "--data", json.dumps({"scene": 1})]) == 0
    assert SD.main(["suggest", film, "--data", json.dumps({"shot": "../x"})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert [x["event"] for x in lines] == ["result", "result", "error"] and lines[0]["data"]["proposals"]
