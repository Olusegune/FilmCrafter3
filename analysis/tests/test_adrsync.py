"""Timing and ADR: placement in frames, dub-fit, lining up with the picture's sound, ADR retakes. Real audio, real ffmpeg, the real mixer; nothing is sent anywhere."""
import hashlib
import json
import os

import numpy as np
import pytest
import soundfile as sf

from filmcrafter_engine import adrsync as A, bible, cast_voice as C, edit_time as T, shots as S, story, voiceover as V

R = A.RATE
SCRIPT = "INT. ROOM - DAY\n\nA small room.\n\nSARAH\nWe should go.\n"


def speech(secs=4.0, seed=1, amp=0.3):
    """Bursts of tone with irregular pauses: a stand-in for a spoken line whose loudness has a shape."""
    rng = np.random.default_rng(seed)
    x = np.zeros(int(R * secs), dtype="float32")
    t = np.arange(len(x)) / R
    pos = 0.1
    while pos < secs - 0.5:
        n = rng.uniform(0.1, 0.35)
        a, b = int(pos * R), int((pos + n) * R)
        x[a:b] += (amp * np.sin(2 * np.pi * rng.uniform(150, 260) * t[a:b]) * np.hanning(b - a)).astype("float32")
        pos += n + rng.uniform(0.05, 0.3)
    return x + rng.normal(0, 3e-4, len(x)).astype("float32")          # a room is never digitally silent


def write(path, x):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sf.write(path, x, R)
    return path


def fingerprint(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


@pytest.fixture
def sid(film):
    return next(s["id"] for s in V.status(film)["shots"] if any(p["lines"] for p in s["people"]))


def attach(film, sid, tmp_path, x, name="line.wav", shot_seconds=None):
    if shot_seconds:
        S.set_fields(film, sid, {"generation": {"duration": shot_seconds}})
    V.attach(film, sid, "Sarah", write(str(tmp_path / "rec" / name), x), fit=False)
    return os.path.join(film, "voice", sid, "sarah.wav")


# ---------------------------------------------------------------- frames and timecode

def test_frames_and_seconds_agree_at_the_common_rates():
    f24, f2398, f25 = T.FPS_24, T.FrameRate(24000, 1001), T.FrameRate(25, 1)
    assert A.seconds_to_frames(0.5, f24) == 12 and A.seconds_to_frames(-0.5, f24) == -12 and A.seconds_to_frames(0.0, f24) == 0
    assert A.seconds_to_frames(1.0, f25) == 25 and A.seconds_to_frames(1.0, f2398) == 24
    assert A.frames_to_seconds(24, f24) == 1.0 and A.frames_to_seconds(24, f2398) == pytest.approx(1.001, abs=1e-9)
    assert A.frames_to_seconds(-12, f24) == -0.5
    for fr in (-30, -1, 0, 1, 7, 100):
        for f in (f24, f2398, f25):
            assert A.seconds_to_frames(A.frames_to_seconds(fr, f), f) == fr          # a whole number of frames goes there and back exactly


def test_timecode_inside_a_shot():
    assert A.tc(61.5, T.FPS_24) == "00:01:01:12" and A.tc(0, T.FPS_24) == "00:00:00:00" and A.tc(-0.5, T.FPS_24) == "-00:00:00:12"


def test_the_film_frame_rate_comes_from_the_film_or_is_24(film):
    assert A.film_fps(film) == T.FPS_24
    m = json.load(open(os.path.join(film, "film.json"), encoding="utf-8"))
    m["fps"] = [24000, 1001]
    json.dump(m, open(os.path.join(film, "film.json"), "w", encoding="utf-8"))
    assert A.film_fps(film) == T.FrameRate(24000, 1001)
    m["fps"] = "nonsense"
    json.dump(m, open(os.path.join(film, "film.json"), "w", encoding="utf-8"))
    assert A.film_fps(film) == T.FPS_24


# ---------------------------------------------------------------- where a line sits

def test_a_lines_timing_is_shown_in_frames_and_timecode(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(3.0), shot_seconds=5.0)
    g = A.get(film, sid, "Sarah")
    assert g["fps"] == [24, 1] and g["fps_label"] == "24" and g["recording"]["seconds"] == pytest.approx(3.0, abs=0.05) and g["shot_seconds"] == 5.0
    assert g["offset_frames"] == 0 and g["starts"] == "00:00:00:00" and g["ends"] == "00:00:03:00" and g["shot_ends"] == "00:00:05:00" and g["runs_past_shot"] is False
    assert g["fit"]["class"] == "fits" and g["adr"] == {"needs": False, "reason": ""}


def test_moving_a_line_by_frames_changes_only_the_record_and_is_exact(film, sid, tmp_path):
    rec = attach(film, sid, tmp_path, speech(3.0), shot_seconds=5.0)
    before = fingerprint(rec)
    g = A.nudge(film, sid, "Sarah", frames=2)
    assert g["offset_frames"] == 2 and g["offset_seconds"] == pytest.approx(2 / 24, abs=1e-4) and g["starts"] == "00:00:00:02"
    assert A.nudge(film, sid, "Sarah", frames=10)["offset_frames"] == 12 and A.nudge(film, sid, "Sarah", frames=-4)["offset_frames"] == 8
    g = A.nudge(film, sid, "Sarah", to_frame=-12)
    assert g["offset_frames"] == -12 and g["starts_before_shot"] is True and g["starts"] == "-00:00:00:12"
    assert A.offset_seconds(film, sid, "sarah") == -0.5
    assert fingerprint(rec) == before                                                              # the recording itself is never touched
    A.nudge(film, sid, "Sarah", to_frame=0)
    assert A.offset_frames(film, sid, "sarah") == 0 and A._load(film)["lines"] == {}


def test_a_line_that_would_run_past_its_shot_is_flagged(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(3.0), shot_seconds=4.0)
    assert A.get(film, sid, "Sarah")["runs_past_shot"] is False
    assert A.nudge(film, sid, "Sarah", frames=36)["runs_past_shot"] is True


def test_bad_moves_and_names_are_refused(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(3.0), shot_seconds=5.0)
    for bad in (True, 1.5, "2", [1]):
        with pytest.raises(SystemExit, match="whole number"):
            A.nudge(film, sid, "Sarah", frames=bad)
    with pytest.raises(SystemExit, match="how many frames"):
        A.nudge(film, sid, "Sarah")
    with pytest.raises(SystemExit, match="at most 5"):
        A.nudge(film, sid, "Sarah", to_frame=121)
    with pytest.raises(SystemExit, match="at most 5"):
        A.nudge(film, sid, "Sarah", frames=-121)
    for shot in ("../x", "", "S99-99"):
        with pytest.raises(SystemExit):
            A.get(film, shot, "Sarah")
    with pytest.raises(SystemExit, match="no recording"):
        A.get(film, sid, "Nobody")
    with pytest.raises(SystemExit, match="Choose who"):
        A.get(film, sid, "")


def test_a_moved_line_is_heard_where_it_was_moved_in_the_real_mix(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(2.0, amp=0.4), shot_seconds=6.0)
    rd = os.path.join(film, "render")
    os.makedirs(rd, exist_ok=True)

    def onset(frames, start=1.0):
        A.nudge(film, sid, "Sarah", to_frame=frames)
        assert V.to_render(film, rd) == 1
        row = V.for_shot(rd, sid)[0]
        assert ("offset" in row) == (frames != 0)
        base = str(tmp_path / "base.wav")
        sf.write(base, np.zeros((R * 10, 2), dtype="float32"), R, subtype="PCM_16")
        out = str(tmp_path / f"mix{frames}.wav")
        assert V.mix_into(rd, base, [{"shot": sid, "start": start, "end": start + 6.0}], 10.0, out)["recordings"] == 1
        x = sf.read(out, dtype="float32", always_2d=True)[0]
        return float(np.argmax(np.abs(x[:, 0]) > 0.01)) / R
    plain = onset(0)
    assert plain == pytest.approx(1.0 + 0.1, abs=0.05)                                              # the line's own first sound, at the shot's start
    assert onset(12) == pytest.approx(plain + 0.5, abs=0.02)                                          # twelve frames later
    assert onset(-12) == pytest.approx(plain - 0.5, abs=0.02)                                         # twelve frames earlier: it starts before its picture
    assert onset(0) == pytest.approx(plain, abs=0.01)


# ---------------------------------------------------------------- dub-fit

def test_the_fit_plan_says_what_would_make_a_line_fit_and_how_natural_it_would_sound(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(4.0), shot_seconds=5.0)
    p = A.fit_plan(film, sid, "Sarah", target_seconds=3.8)
    assert p["class"] == "natural" and 1.0 < p["tempo"] <= 1.08 and "natural" in p["words"]
    assert A.fit_plan(film, sid, "Sarah", target_seconds=3.5)["class"] == "audible"
    t = A.fit_plan(film, sid, "Sarah", target_seconds=2.0)
    assert t["class"] == "too_much" and "Shorten the line" in t["words"]
    assert A.fit_plan(film, sid, "Sarah")["class"] == "fits"
    A.nudge(film, sid, "Sarah", frames=115)
    assert A.fit_plan(film, sid, "Sarah")["class"] == "no_room"
    for bad in (0.1, 500, True, "x"):
        with pytest.raises(SystemExit, match="between 0.3 and 120"):
            A.fit_plan(film, sid, "Sarah", target_seconds=bad)


def test_a_fitted_take_is_made_with_the_right_length_and_the_same_pitch_and_the_original_is_kept(film, sid, tmp_path):
    rec = attach(film, sid, tmp_path, np.concatenate([speech(2.0)[:int(R * 0.1)] * 0, (0.3 * np.sin(2 * np.pi * 440 * np.arange(int(R * 3.9)) / R)).astype("float32")]), shot_seconds=5.0)
    before = fingerprint(rec)
    r = A.fit_make(film, sid, "Sarah", target_seconds=3.75)
    out = os.path.join(film, *r["take"].split("/"))
    x, rate = sf.read(out, dtype="float32", always_2d=True)
    assert len(x) / rate == pytest.approx(4.0 / r["tempo"], abs=0.1) and r["tempo"] == pytest.approx(4.0 / 3.75, abs=0.01) and r["natural"] is True and r["attached"] is False
    seg = x[int(rate * 0.5): int(rate * 2.5), 0]
    peak_hz = np.argmax(np.abs(np.fft.rfft(seg * np.hanning(len(seg))))) * rate / len(seg)
    assert peak_hz == pytest.approx(440, abs=5)                                                        # faster, not higher
    side = json.load(open(out[:-4] + ".json", encoding="utf-8"))
    assert side["kind"] == "dubfit" and side["key"] == "sarah" and side["tempo"] == r["tempo"] and side["source_sha256"] and "pitch kept" in side["note"]
    assert fingerprint(rec) == before
    assert V._meta(film)["shots"][sid][0]["file"].endswith("sarah.wav") and V._meta(film)["shots"][sid][0].get("source") != "dubfit"


def test_the_same_fit_is_never_made_twice_and_nothing_is_made_when_it_already_fits(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(4.0), shot_seconds=5.0)
    a = A.fit_make(film, sid, "Sarah", target_seconds=3.8)
    b = A.fit_make(film, sid, "Sarah", target_seconds=3.8)
    assert b["cached"] is True and b["take"] == a["take"]
    with pytest.raises(SystemExit, match="already fits"):
        A.fit_make(film, sid, "Sarah", target_seconds=4.5)


def test_a_change_that_would_sound_wrong_is_refused_unless_insisted_on(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(4.0), shot_seconds=5.0)
    with pytest.raises(SystemExit, match="too much"):
        A.fit_make(film, sid, "Sarah", target_seconds=2.5)
    with pytest.raises(SystemExit, match="too much"):
        A.fit_make(film, sid, "Sarah", tempo=0.8)
    r = A.fit_make(film, sid, "Sarah", target_seconds=2.5, allow_extreme=True)
    assert r["natural"] is False and r["tempo"] > 1.15
    for bad in (True, "fast", 0.3, 3.0):
        with pytest.raises(SystemExit, match="between 0.5 and 2"):
            A.fit_make(film, sid, "Sarah", tempo=bad)
    with pytest.raises(SystemExit, match="not a change"):
        A.fit_make(film, sid, "Sarah", tempo=1.0)


def test_a_fitted_take_is_chosen_like_any_take_and_the_old_recording_is_archived(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(4.0), shot_seconds=5.0)
    r = A.fit_make(film, sid, "Sarah", target_seconds=3.8)
    t = C.takes(film, sid, "Sarah")["takes"]
    assert len(t) == 1 and t[0]["kind"] == "dubfit" and "pitch kept" in t[0]["note"] and t[0]["current"] is False
    C.use_take(film, sid, "Sarah", r["take"])
    e = V._meta(film)["shots"][sid][0]
    assert e["source"] == "dubfit" and "fitted to the shot" in e["name"]
    assert C.takes(film, sid, "Sarah")["takes"][0]["current"] is True
    removed = os.path.join(film, "voice", "_removed")
    assert os.path.isdir(removed) and os.listdir(removed)


# ---------------------------------------------------------------- lining up

def test_the_shift_that_lines_two_sounds_up_is_found_in_either_direction():
    g = speech(4.0)
    for lag in (0.37, -0.25, 0.0, 1.2):
        r = np.concatenate([np.zeros(int(lag * R), dtype="float32"), g]) if lag > 0 else g[int(-lag * R):]
        e = A.estimate_shift(g, r)
        assert e["ok"] and e["reliable"] and e["shift_seconds"] == pytest.approx(-lag, abs=0.02)


def test_an_unrelated_sound_is_not_a_confident_match_and_a_flat_one_is_refused():
    e = A.estimate_shift(speech(4.0, seed=1), speech(4.0, seed=9))
    assert e["ok"] and e["reliable"] is False
    assert A.estimate_shift(speech(4.0), np.full(R * 4, 0.1, dtype="float32"))["ok"] is False
    assert A.estimate_shift(speech(0.05), speech(0.05))["ok"] is False


def test_a_line_is_lined_up_with_a_guide_and_applying_the_suggestion_makes_it_line_up(film, sid, tmp_path):
    g = speech(4.0)
    write(os.path.join(film, "guide.wav"), g)
    late = np.concatenate([np.zeros(int(0.3 * R), dtype="float32"), g])
    attach(film, sid, tmp_path, late, shot_seconds=6.0)
    s = A.align(film, sid, "Sarah", guide="guide.wav")
    assert s["reliable"] and s["move_to_frame"] == -7 and s["move_by_frames"] == -7 and "7 frames earlier" in s["words"] and s["guide"] == "guide.wav"
    A.nudge(film, sid, "Sarah", to_frame=s["move_to_frame"])
    again = A.align(film, sid, "Sarah", guide="guide.wav")                                           # asked again after applying it: nothing left to move
    assert again["move_to_frame"] == -7 and again["move_by_frames"] == 0 and "already lines up" in again["words"]
    assert A.get(film, sid, "Sarah")["offset_frames"] == -7


def test_without_a_picture_sound_or_a_guide_there_is_nothing_to_line_up_with(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(3.0), shot_seconds=5.0)
    with pytest.raises(SystemExit, match="no picture sound"):
        A.align(film, sid, "Sarah")
    for bad in ("../x.wav", "..\\x.wav", "voice/../../x.wav"):
        with pytest.raises(SystemExit, match="not inside"):
            A.align(film, sid, "Sarah", guide=bad)


# ---------------------------------------------------------------- ADR

def test_a_line_can_be_marked_for_adr_with_a_reason_and_unmarked(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(3.0), shot_seconds=5.0)
    g = A.adr_mark(film, sid, "Sarah", True, "  dog barking   outside ")
    assert g["adr"] == {"needs": True, "reason": "dog barking outside"}
    ls = A.adr_list(film)
    assert ls["marked"] == 1 and ls["lines"][0]["marked"] is True and "you marked it: dog barking outside" in ls["lines"][0]["reasons"]
    assert A.adr_mark(film, sid, "Sarah", False)["adr"]["needs"] is False and A.adr_list(film)["lines"] == []


def test_the_list_also_names_recordings_the_audio_inspector_would_replace(film, sid, tmp_path):
    attach(film, sid, tmp_path, np.clip(speech(3.0) * 8, -1, 1), shot_seconds=5.0)
    row = A.adr_list(film)["lines"][0]
    assert row["marked"] is False and any("flattened" in r for r in row["reasons"]) and "not a verdict" in A.adr_list(film)["note"]


def test_an_adr_retake_is_a_new_take_beside_the_others_and_the_original_is_kept_as_it_came(film, sid, tmp_path):
    rec = attach(film, sid, tmp_path, speech(3.0), shot_seconds=5.0)
    before = fingerprint(rec)
    new = write(str(tmp_path / "adr" / "take2.wav"), speech(3.2, seed=5))
    r = A.adr_take(film, sid, "Sarah", new, performed_by="Dee", note="in the booth")
    out = os.path.join(film, *r["take"].split("/"))
    data, rate = sf.read(out)
    assert len(data) / rate == pytest.approx(3.2, abs=0.05) and r["attached"] is False and r["original"].startswith("voice/_adr/")
    assert fingerprint(os.path.join(film, *r["original"].split("/"))) == fingerprint(new)
    side = json.load(open(out[:-4] + ".json", encoding="utf-8"))
    assert side["kind"] == "adr" and side["performed_by"] == "Dee" and side["note"] == "in the booth" and side["original_sha256"]
    assert fingerprint(rec) == before and V._meta(film)["shots"][sid][0]["file"].endswith("sarah.wav")


def test_the_same_adr_recording_is_not_added_twice_and_a_bad_one_is_refused(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(3.0), shot_seconds=5.0)
    new = write(str(tmp_path / "adr" / "t.wav"), speech(3.0, seed=4))
    a = A.adr_take(film, sid, "Sarah", new)
    assert A.adr_take(film, sid, "Sarah", new)["cached"] is True and A.adr_take(film, sid, "Sarah", new)["take"] == a["take"]
    silent = write(str(tmp_path / "adr" / "s.wav"), np.zeros(R, dtype="float32"))
    with pytest.raises(SystemExit, match="silent"):
        A.adr_take(film, sid, "Sarah", silent)
    bad = tmp_path / "adr" / "b.wav"
    bad.write_bytes(b"not sound")
    with pytest.raises(SystemExit):
        A.adr_take(film, sid, "Sarah", str(bad))
    with pytest.raises(SystemExit, match="not inside"):
        A.adr_take(film, sid, "Sarah", "../../x.wav")


def test_an_adr_take_is_chosen_like_any_take_and_the_list_counts_it(film, sid, tmp_path):
    attach(film, sid, tmp_path, speech(3.0), shot_seconds=5.0)
    A.adr_mark(film, sid, "Sarah", True, "noise")
    r = A.adr_take(film, sid, "Sarah", write(str(tmp_path / "adr" / "t.wav"), speech(3.0, seed=7)), performed_by="Dee")
    t = C.takes(film, sid, "Sarah")["takes"]
    assert t[0]["kind"] == "adr" and t[0]["performed_by"] == "Dee" and A.adr_list(film)["lines"][0]["adr_takes"] == 1
    C.use_take(film, sid, "Sarah", r["take"])
    e = V._meta(film)["shots"][sid][0]
    assert e["source"] == "adr" and "ADR retake" in e["name"]
    assert os.listdir(os.path.join(film, "voice", "_removed"))


# ---------------------------------------------------------------- the command line

def test_the_command_line_answers_with_json(film, sid, tmp_path, capsys):
    attach(film, sid, tmp_path, speech(3.0), shot_seconds=5.0)
    assert A.main(["get", film, "--data", json.dumps({"shot": sid, "speaker": "Sarah"})]) == 0
    assert A.main(["nudge", film, "--data", json.dumps({"shot": sid, "speaker": "Sarah", "frames": 3})]) == 0
    assert A.main(["fit_plan", film, "--data", json.dumps({"shot": sid, "speaker": "Sarah", "target_seconds": 2.0})]) == 0
    assert A.main(["adr_list", film]) == 0
    assert A.main(["nudge", film, "--data", json.dumps({"shot": sid, "speaker": "Sarah", "frames": 1.5})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert [x["event"] for x in lines] == ["result", "result", "result", "result", "error"] and lines[1]["data"]["offset_frames"] == 3
