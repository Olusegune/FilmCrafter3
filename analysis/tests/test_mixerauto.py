"""Mixer automation: volume curves per lane, per cue and for the master, groups, markers and crossfades. Measured on real audio through the real mixer, the voice mixer and the pro export."""
import json
import os

import numpy as np
import pytest
import soundfile as sf

from filmcrafter_engine import audiocues as Q, audiolib as AL, audiomix as M, bible, proaudio as P, shots as S, story, voiceover as V

R = M.RATE
SCRIPT = "INT. ROOM - DAY\n\nA small room.\n\nSARAH\nHello there.\n"


def tone(path, secs, hz=500, amp=0.3):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    t = np.arange(int(R * secs)) / R
    sf.write(path, (amp * np.sin(2 * np.pi * hz * t)).astype("float32"), R)
    return path


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def asset(film, tmp_path, name, secs=8.0, hz=500, amp=0.3, kind="sfx", category=None):
    return AL.import_files(film, kind, [tone(str(tmp_path / "src" / name), secs, hz, amp)], category)["assets"][-1]


def times(film):
    out, at = {}, 0.0
    for s in sorted(S.view(film)["shots"], key=lambda x: (int(x["scene"]), x["index"])):
        out[s["id"]] = (at, at + float(s["duration"]))
        at += float(s["duration"])
    return out, at


def first_shot(film):
    return sorted(S.view(film)["shots"], key=lambda x: (int(x["scene"]), x["index"]))[0]["id"]


def mix(film, tmp_path, base=None, st=None, name="mixed.wav"):
    t, dur = times(film)
    out = str(tmp_path / name)
    if base is None:
        base = str(tmp_path / "silence.wav")
        sf.write(base, np.zeros((int(dur * R), 2), dtype="float32"), R, subtype="PCM_16")
    r = M.mix_cues(film, base, t, dur, out, {**M.settings(film), "ducking_db": 0, "target_lufs": None, **(st or {})})
    return r, (sf.read(out, dtype="float32", always_2d=True)[0] if r and r.get("path") else None)


def rms(x, a, b, ch=0):
    seg = x[int(a * R):int(b * R), ch]
    return float(np.sqrt(np.mean(np.square(seg)))) if len(seg) else 0.0


def db(a, b):
    return 20 * np.log10(max(a, 1e-9) / max(b, 1e-9))


# ---------------------------------------------------------------- cleaning and the curve itself

def test_points_are_checked_sorted_and_limited():
    c = M.clean_points([{"t": 3, "db": -6}, {"t": 1, "db": 0, "curve": "smooth"}, {"t": 1, "db": -2, "curve": "nonsense"}, {"t": -1, "db": 0}, {"t": 5, "db": 99}, {"t": "x", "db": 1}, "junk", {"t": 2}])
    assert c == [{"t": 1.0, "db": -2.0, "curve": "linear"}, {"t": 3.0, "db": -6.0, "curve": "linear"}]
    assert len(M.clean_points([{"t": i, "db": 0} for i in range(500)])) == M.MAX_POINTS
    assert M.clean_points(None) == [] and M.clean_points("x") == []


def test_the_curve_holds_before_and_after_and_follows_each_points_shape_between():
    pts = [{"t": 1.0, "db": -20.0, "curve": "linear"}, {"t": 3.0, "db": 0.0, "curve": "smooth"}, {"t": 5.0, "db": -12.0, "curve": "hold"}, {"t": 7.0, "db": -30.0, "curve": "linear"}]

    def at(t):
        return 20 * np.log10(float(M.auto_gain(pts, t, 1)[0]))
    assert at(0.0) == pytest.approx(-20, abs=0.01) and at(1.0) == pytest.approx(-20, abs=0.01)                      # held before the first point
    assert at(2.0) == pytest.approx(-10, abs=0.01)                                                              # linear in dB: halfway
    assert at(4.0) == pytest.approx(-6, abs=0.01)                                                               # smooth: also halfway at the middle...
    assert at(3.4) < at(3.0) and at(3.4) == pytest.approx(0 + (-12) * (0.2 * 0.2 * (3 - 0.4)), abs=0.05)         # ...but eased at the ends
    assert at(6.0) == pytest.approx(-12, abs=0.01) and at(6.99) == pytest.approx(-12, abs=0.01)                  # hold: a step at the next point
    assert at(7.0) == pytest.approx(-30, abs=0.01) and at(100.0) == pytest.approx(-30, abs=0.01)                 # held after the last
    assert float(M.auto_gain(None, 0, 4)[0]) == 1.0 and len(M.auto_gain(pts, 0, 0)) == 0
    assert M.auto_gain([{"t": 2.0, "db": -6.0}], 0, 3).tolist() == pytest.approx([10 ** (-6 / 20)] * 3, rel=1e-5)


# ---------------------------------------------------------------- the settings

def test_setting_a_curve_snaps_to_frames_and_clearing_removes_it(film):
    s = M.set_automation(film, "music", [{"t": 1.01, "db": -10}, {"t": 2.0, "db": 0, "curve": "smooth"}])
    pts = s["automation"]["music"]
    assert [p["t"] for p in pts] == [1.0, 2.0] and pts[1]["curve"] == "smooth"
    assert M.set_automation(film, "music", [{"t": 1.03, "db": -10}])["automation"]["music"][0]["t"] == pytest.approx(25 / 24, abs=1e-4)
    assert "automation" in M.settings(film) and M.set_automation(film, "music", [])["automation"] == {}


def test_a_bad_curve_is_refused_and_changes_nothing(film):
    M.set_automation(film, "sfx", [{"t": 1, "db": -3}])
    for lane, pts, why in (("pan", [], "Choose master"), ("sfx", [{"t": 1, "db": 99}], "level"), ("sfx", [{"t": -1, "db": 0}], "time"), ("sfx", [{"t": 1}], "needs a time"), ("sfx", "x", "at most"),
                           ("sfx", [{"t": i, "db": 0} for i in range(201)], "at most")):
        with pytest.raises(SystemExit, match=why):
            M.set_automation(film, lane, pts)
    assert M.settings(film)["automation"]["sfx"][0]["db"] == -3.0


def test_a_mix_file_from_before_has_no_curves_groups_or_markers_and_damaged_ones_are_ignored(film):
    s = M.settings(film)
    assert s["automation"] == {} and s["groups"] == {} and s["markers"] == []
    json.dump({"schema": 1, "automation": {"music": "junk", "nowhere": [{"t": 1, "db": 0}], "sfx": [{"t": 1, "db": -3}]}, "groups": {"a": 5, "b": {"gain_db": "x"}}, "markers": [{"t": "x"}, 4]},
              open(M._path(film), "w", encoding="utf-8")) if os.makedirs(os.path.dirname(M._path(film)), exist_ok=True) is None else None
    s = M.settings(film)
    assert list(s["automation"]) == ["sfx"] and list(s["groups"]) == ["b"] and s["groups"]["b"] == {"gain_db": 0.0, "muted": False} and s["markers"] == []


# ---------------------------------------------------------------- in the real mix

def test_a_lane_curve_rides_the_lanes_level_in_the_finished_mix(film, tmp_path):
    a = asset(film, tmp_path, "m.wav", 8.0, 500)
    Q.add(film, {"asset_id": a["id"], "scene": 1, "shot": first_shot(film), "start": 0.0, "kind": "music"})
    _, flat = mix(film, tmp_path, name="flat.wav")
    M.set_automation(film, "music", [{"t": 1.0, "db": -30.0}, {"t": 5.0, "db": 0.0}])
    _, ride = mix(film, tmp_path, name="ride.wav")
    for t, want in ((0.5, -30.0), (3.0, -15.0), (5.5, 0.0)):
        assert db(rms(ride, t - 0.2, t + 0.2), rms(flat, t - 0.2, t + 0.2)) == pytest.approx(want, abs=1.0)


def test_a_cues_own_curve_counts_from_the_start_of_the_sound_and_the_lane_curve_from_the_start_of_the_film(film, tmp_path):
    a = asset(film, tmp_path, "m.wav", 6.0, 500)
    Q.add(film, {"asset_id": a["id"], "scene": 1, "shot": first_shot(film), "start": 2.0, "auto": [{"t": 0.0, "db": 0}, {"t": 2.0, "db": -20}, {"t": 4.0, "db": -20}]})
    _, x = mix(film, tmp_path)
    assert db(rms(x, 4.0, 4.4), rms(x, 2.1, 2.5)) == pytest.approx(-17.0, abs=2.5)                                 # the first half second of the sound is still at -1 to -5 dB, then -20
    c = Q.listing(film)["cues"][0]
    assert c["auto"][1] == {"t": 2.0, "db": -20.0, "curve": "linear"}


def test_the_master_curve_rides_everything_including_the_song_and_a_stem_is_before_it(film, tmp_path):
    a = asset(film, tmp_path, "m.wav", 8.0, 500, 0.2)
    Q.add(film, {"asset_id": a["id"], "scene": 1, "shot": first_shot(film), "start": 0.0})
    t, dur = times(film)
    song = str(tmp_path / "song.wav")
    sf.write(song, np.stack([tone(str(tmp_path / "s.wav"), dur, 220, 0.3), tone(str(tmp_path / "s2.wav"), dur, 220, 0.3)], 1) if False else np.tile(sf.read(tone(str(tmp_path / "s.wav"), dur, 220, 0.3))[0][:, None], (1, 2)), R)
    _, flat = mix(film, tmp_path, base=song, name="f.wav")
    M.set_automation(film, "master", [{"t": 2.0, "db": 0.0, "curve": "hold"}, {"t": 2.5, "db": -20.0}])
    _, ride = mix(film, tmp_path, base=song, name="r.wav")
    assert db(rms(ride, 0.5, 1.5), rms(flat, 0.5, 1.5)) == pytest.approx(0.0, abs=0.3)
    assert db(rms(ride, 3.0, 4.0), rms(flat, 3.0, 4.0)) == pytest.approx(-20.0, abs=0.5)                       # the song went down too
    _, stem = mix(film, tmp_path, base=song, st={"raw_float": True}, name="stem.wav")
    assert db(rms(stem, 3.0, 4.0), rms(flat, 3.0, 4.0)) == pytest.approx(0.0, abs=0.3)                          # a stem is the mix before the master stage


def test_a_master_curve_applies_even_when_no_cue_is_planned(film, tmp_path):
    t, dur = times(film)
    song = tone(str(tmp_path / "song.wav"), dur, 220, 0.3)
    out = str(tmp_path / "o.wav")
    assert M.mix_cues(film, song, t, dur, out) is None                                                        # nothing planned, no curve: the soundtrack is left alone
    M.set_automation(film, "master", [{"t": 0.0, "db": -12.0}])
    r = M.mix_cues(film, song, t, dur, out, {**M.settings(film), "target_lufs": None, "ducking_db": 0})
    assert r and r["path"] and db(rms(sf.read(out, dtype="float32", always_2d=True)[0], 1, 2), 0.3 / np.sqrt(2)) == pytest.approx(-12.0, abs=0.6)


def test_the_dialogue_curve_rides_the_voices_only_and_not_the_song(film, tmp_path):
    sid = first_shot(film)
    dlg = next(s["id"] for s in V.status(film)["shots"] if any(p["lines"] for p in s["people"]))
    V.attach(film, dlg, "Sarah", tone(str(tmp_path / "rec.wav"), 3.0, 300, 0.4), fit=False)
    rd = os.path.join(film, "render")
    os.makedirs(rd, exist_ok=True)
    V.to_render(film, rd)
    t, dur = times(film)
    song = str(tmp_path / "song.wav")
    sf.write(song, np.tile(sf.read(tone(str(tmp_path / "s.wav"), dur, 800, 0.2))[0][:, None], (1, 2)), R)
    a, b = t[dlg]

    def voice_and_song(name):
        out = str(tmp_path / name)
        assert V.mix_into(rd, song, [{"shot": dlg, "start": a, "end": b}], dur, out)["recordings"] == 1
        x = sf.read(out, dtype="float32", always_2d=True)[0]
        seg = x[int((a + 0.2) * R):int((a + 2.5) * R), 0]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) / len(seg)
        k = lambda hz: float(np.max(spec[int(hz * len(seg) / R) - 3:int(hz * len(seg) / R) + 4]))
        return k(300), k(800)
    v0, s0 = voice_and_song("a.wav")
    M.set_automation(film, "dialogue", [{"t": 0.0, "db": -20.0}])
    v1, s1 = voice_and_song("b.wav")
    assert db(v1, v0) == pytest.approx(-20.0, abs=1.0) and db(s1, s0) == pytest.approx(0.0, abs=0.3)


# ---------------------------------------------------------------- groups

def test_a_groups_level_and_mute_reach_the_mix_and_removing_it_gives_the_levels_back(film, tmp_path):
    a = asset(film, tmp_path, "m.wav", 4.0, 500)
    cid = Q.add(film, {"asset_id": a["id"], "scene": 1, "shot": first_shot(film), "start": 0.0, "group": "  Rain   bed "})["id"]
    assert Q.listing(film)["cues"][0]["group"] == "Rain bed"
    _, base = mix(film, tmp_path, name="a.wav")
    M.set_group(film, "Rain bed", gain_db=-6)
    _, quiet = mix(film, tmp_path, name="b.wav")
    assert db(rms(quiet, 1, 2), rms(base, 1, 2)) == pytest.approx(-6.0, abs=0.2)
    M.set_group(film, "Rain bed", muted=True)
    r, _ = mix(film, tmp_path, name="c.wav")
    assert r is None or r.get("none")                                                                          # nothing left to hear
    assert M.placements(film, times(film)[0], times(film)[1])[0] == []
    M.remove_group(film, "Rain bed")
    _, back = mix(film, tmp_path, name="d.wav")
    assert db(rms(back, 1, 2), rms(base, 1, 2)) == pytest.approx(0.0, abs=0.1)
    assert Q.listing(film)["cues"][0]["group"] == "Rain bed"                                                    # the cue keeps its name, with no group to follow


def test_groups_are_named_limited_and_checked(film):
    for bad in ("", "   "):
        with pytest.raises(SystemExit, match="name"):
            M.set_group(film, bad)
    with pytest.raises(SystemExit, match="between"):
        M.set_group(film, "x", gain_db=99)
    with pytest.raises(SystemExit, match="no group"):
        M.remove_group(film, "nope")
    for i in range(M.MAX_GROUPS):
        M.set_group(film, f"g{i}", gain_db=0)
    with pytest.raises(SystemExit, match="at most"):
        M.set_group(film, "one too many")


def test_a_cue_curve_and_group_are_checked_when_set(film, tmp_path):
    a = asset(film, tmp_path, "m.wav", 2.0)
    cid = Q.add(film, {"asset_id": a["id"], "scene": 1})["id"]
    with pytest.raises(SystemExit, match="at most 50"):
        Q.update(film, cid, {"auto": [{"t": i, "db": 0} for i in range(51)]})
    for bad in ({"t": 1}, {"t": 1, "db": 99}, {"t": -1, "db": 0}):
        with pytest.raises(SystemExit):
            Q.update(film, cid, {"auto": [bad]})
    Q.update(film, cid, {"auto": [{"t": 1, "db": -3}], "group": "x" * 100})
    c = Q.listing(film)["cues"][0]
    assert c["auto"] == [{"t": 1.0, "db": -3.0, "curve": "linear"}] and len(c["group"]) == 40


# ---------------------------------------------------------------- crossfades

def test_a_crossfade_overlaps_two_sounds_and_the_real_mix_hands_over_smoothly(film, tmp_path):
    sid = first_shot(film)
    a = asset(film, tmp_path, "a.wav", 2.0, 400, 0.3)
    b = asset(film, tmp_path, "b.wav", 2.0, 1600, 0.3)
    ca = Q.add(film, {"asset_id": a["id"], "scene": 1, "shot": sid, "start": 0.0})["id"]
    cb = Q.add(film, {"asset_id": b["id"], "scene": 1, "shot": sid, "start": 2.0})["id"]
    r = M.crossfade(film, ca, cb, 1.0)
    assert r["b_starts"] == 1.0
    cues = {c["id"]: c for c in Q.listing(film)["cues"]}
    assert cues[ca]["fade_out"] == 1.0 and cues[cb]["fade_in"] == 1.0 and cues[cb]["start"] == 1.0
    _, x = mix(film, tmp_path)

    def band(a_, b_, hz):
        seg = x[int(a_ * R):int(b_ * R), 0]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) / len(seg)
        return float(np.max(spec[int(hz * len(seg) / R) - 3:int(hz * len(seg) / R) + 4]))
    assert band(0.1, 0.7, 400) > 0.05 and band(0.1, 0.7, 1600) < 0.001 and band(2.3, 2.9, 1600) > 0.05 and band(2.3, 2.9, 400) < 0.001      # clear of the overlap: each alone
    mid_a, mid_b = band(1.4, 1.6, 400), band(1.4, 1.6, 1600)
    assert mid_a == pytest.approx(mid_b, rel=0.25) and 0.4 < mid_a / band(0.1, 0.7, 400) < 0.7                # halfway through: both at about half


def test_a_crossfade_needs_two_cues_in_one_place_that_are_longer_than_the_fade(film, tmp_path):
    sid = first_shot(film)
    a = asset(film, tmp_path, "a.wav", 4.0)
    short = asset(film, tmp_path, "s.wav", 0.5)
    c1 = Q.add(film, {"asset_id": a["id"], "scene": 1, "shot": sid, "start": 0.0})["id"]
    c2 = Q.add(film, {"asset_id": a["id"], "scene": 1, "start": 4.0})["id"]                                    # anchored to the scene, not the shot
    c3 = Q.add(film, {"asset_id": short["id"], "scene": 1, "shot": sid, "start": 4.0})["id"]
    with pytest.raises(SystemExit, match="same shot or the same scene"):
        M.crossfade(film, c1, c2, 1.0)
    with pytest.raises(SystemExit, match="longer than the crossfade"):
        M.crossfade(film, c1, c3, 1.0)
    with pytest.raises(SystemExit, match="two different cues"):
        M.crossfade(film, c1, c1, 1.0)
    with pytest.raises(SystemExit, match="two different cues"):
        M.crossfade(film, c1, "q-00000000", 1.0)
    for bad in (0, 20, "x"):
        with pytest.raises(SystemExit):
            M.crossfade(film, c1, c3, bad)
    assert Q.listing(film)["cues"][0]["fade_out"] == 0                                                         # nothing was changed by the refusals


# ---------------------------------------------------------------- markers

def test_markers_are_named_snapped_sorted_limited_and_removable(film):
    M.marker_add(film, 12.0, "Rain starts")
    M.marker_add(film, 1.01, " Door  slam ")
    s = M.settings(film)
    assert [(m["t"], m["name"]) for m in s["markers"]] == [(1.0, "Door slam"), (12.0, "Rain starts")]
    for bad in ((1, ""), (-1, "x"), ("x", "x"), (99999, "x")):
        with pytest.raises(SystemExit):
            M.marker_add(film, *bad)
    assert [m["name"] for m in M.marker_remove(film, 0)["markers"]] == ["Rain starts"]
    for bad in (5, -1, True, "0"):
        with pytest.raises(SystemExit, match="not there"):
            M.marker_remove(film, bad)
    for i in range(M.MAX_MARKERS - 1):
        M.marker_add(film, i, f"m{i}")
    with pytest.raises(SystemExit, match="at most"):
        M.marker_add(film, 1, "too many")


# ---------------------------------------------------------------- in the audio export

@pytest.fixture
def exported(film, tmp_path):
    dlg = next(s["id"] for s in V.status(film)["shots"] if any(p["lines"] for p in s["people"]))
    V.attach(film, dlg, "Sarah", tone(str(tmp_path / "rec.wav"), 3.0, 300, 0.4), fit=False)
    a = asset(film, tmp_path, "m.wav", 8.0, 600, 0.2, kind="music")
    Q.add(film, {"asset_id": a["id"], "scene": 1, "shot": first_shot(film), "start": 0.0})
    return film


def test_the_export_follows_the_lane_curves_markers_and_the_master_curve(exported):
    def load(res):
        stems = {os.path.basename(f)[3:-4]: sf.read(os.path.join(res["folder"], f), dtype="float32", always_2d=True) for f in res["stems"]}
        return stems, sf.read(os.path.join(res["folder"], res["mixes"][0]["file"]), dtype="float32", always_2d=True)
    base = P.export(exported, {"bits": 32, "bwf": False, "stems": ["dialogue", "music"], "mixes": ["final"], "peak_db": -0.1})
    s0, f0 = load(base)                                                                                          # read before the second export replaces the folder
    M.set_automation(exported, "music", [{"t": 0.0, "db": -20.0}])
    M.set_automation(exported, "master", [{"t": 1.0, "db": 0.0, "curve": "hold"}, {"t": 1.0417, "db": -12.0}])
    M.marker_add(exported, 2.0, "Hit")
    r = P.export(exported, {"bits": 32, "bwf": False, "stems": ["dialogue", "music"], "mixes": ["final"], "peak_db": -0.1})
    s1, f1 = load(r)
    seg = lambda st, a, b: float(np.sqrt(np.mean(np.square(st[0][int(a * st[1]):int(b * st[1]), 0]))))
    assert db(seg(s1["MUSIC"], 3, 4), seg(s0["MUSIC"], 3, 4)) == pytest.approx(-20.0, abs=1.0)                  # the music curve is in the music stem
    assert db(seg(s1["DIALOGUE"], 0.3, 0.8), seg(s0["DIALOGUE"], 0.3, 0.8)) == pytest.approx(0.0, abs=0.3)         # the dialogue stem is as it was
    assert db(seg(f1, 0.3, 0.8), seg(f0, 0.3, 0.8)) == pytest.approx(-20.0, abs=1.0)                              # before the master drop: the music curve alone
    assert db(seg(f1, 3, 4), seg(f0, 3, 4)) == pytest.approx(-12.0, abs=2.0)                                     # after it: the master curve on the voices (the music is further down)
    rows = list(__import__("csv").DictReader(open(os.path.join(r["folder"], [x for x in os.listdir(r["folder"]) if x.endswith("cue sheet.csv")][0]), encoding="utf-8-sig")))
    assert [x["Name"] for x in rows if x["Lane"] == "MARKER"] == ["Hit"]


def test_the_markers_are_in_the_real_opentimelineio_file(exported):
    otio = pytest.importorskip("opentimelineio")
    M.marker_add(exported, 2.0, "Hit")
    r = P.export(exported, {"stems": [], "mixes": ["final"]})
    tl = otio.adapters.read_from_file(os.path.join(r["folder"], [f for f in os.listdir(r["folder"]) if f.endswith(".otio")][0]))
    assert [m.name for m in tl.tracks.markers] == ["Hit"] and tl.tracks.markers[0].marked_range.start_time.to_seconds() == pytest.approx(2.0, abs=0.05)


# ---------------------------------------------------------------- the command line

def test_the_command_line_answers_with_json(film, capsys):
    assert M.main(["automation_set", film, "--data", json.dumps({"lane": "music", "points": [{"t": 1, "db": -6}]})]) == 0
    assert M.main(["group_set", film, "--data", json.dumps({"name": "A", "gain_db": -3})]) == 0
    assert M.main(["marker_add", film, "--data", json.dumps({"t": 2, "name": "Hit"})]) == 0
    assert M.main(["marker_remove", film, "--data", json.dumps({"index": 0})]) == 0
    assert M.main(["group_remove", film, "--data", json.dumps({"name": "A"})]) == 0
    assert M.main(["automation_set", film, "--data", json.dumps({"lane": "nope", "points": []})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip().startswith("{")]
    assert [x["event"] for x in lines] == ["result"] * 5 + ["error"] and lines[0]["data"]["automation"]["music"][0]["db"] == -6.0
