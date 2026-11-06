"""Professional audio export: stems, mixes, Broadcast WAV, cue sheet and OpenTimelineIO, written and read back. Real audio, real ffmpeg, the real mixer; nothing is sent anywhere."""
import csv
import hashlib
import json
import os
import subprocess

import numpy as np
import pytest
import soundfile as sf

from filmcrafter_engine import adrsync, audiocues as Q, audiolib as AL, audiomix as M, bible, edit_time as T, proaudio as P, shots as S, sounddesign as SD, story, voiceover as V

R = 44100
SCRIPT = "".join(f"INT. ROOM {n} - DAY\n\nA small room.\n\nSARAH\n{w}.\n\n" for n, w in enumerate(["One", "Two"], 1))


def tone(secs, hz, amp=0.3, rate=R):
    t = np.arange(int(rate * secs)) / rate
    return (amp * np.sin(2 * np.pi * hz * t)).astype("float32")


def speech(secs=3.0, amp=0.3, seed=1):
    rng = np.random.default_rng(seed)
    x = np.zeros(int(R * secs), dtype="float32")
    t = np.arange(len(x)) / R
    pos = 0.1
    while pos < secs - 0.5:
        n = rng.uniform(0.1, 0.35)
        a, b = int(pos * R), int((pos + n) * R)
        x[a:b] += (amp * np.sin(2 * np.pi * rng.uniform(150, 260) * t[a:b]) * np.hanning(b - a)).astype("float32")
        pos += n + rng.uniform(0.05, 0.3)
    return x + rng.normal(0, 3e-4, len(x)).astype("float32")


def write(path, x, rate=R):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sf.write(path, x, rate)
    return path


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "My Film", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def shot_ids(film):
    return sorted([s for s in S.view(film)["shots"]], key=lambda s: (int(s["scene"]), s["index"]))


def asset(film, tmp_path, name, secs, hz, amp=0.3, category=None, kind="sfx"):
    return AL.import_files(film, kind, [write(str(tmp_path / "src" / name), tone(secs, hz, amp))], category)["assets"][-1]


@pytest.fixture
def full(film, tmp_path):
    """A film with a voice line in two shots, an effect, a Foley sound, ambience and music, each at its own time and pitch."""
    sh = shot_ids(film)
    first, second = sh[0]["id"], sh[1]["id"]
    for sid, seed in ((first, 1), (second, 2)):
        V.attach(film, sid, "Sarah", write(str(tmp_path / "rec" / f"{sid}.wav"), speech(3.0, seed=seed)), fit=False)
    fx = asset(film, tmp_path, "fx.wav", 0.5, 900)
    foley = asset(film, tmp_path, "foley.wav", 0.5, 1500)
    rain = asset(film, tmp_path, "rain.wav", 2.0, 300, 0.1, "ambience")
    theme = asset(film, tmp_path, "theme.wav", 3.0, 600, 0.2, kind="music")
    Q.add(film, {"asset_id": fx["id"], "scene": 1, "shot": first, "start": 4.0})
    SD.event_add(film, {"shot": first, "action": "impact", "source_object": "basket", "start": 2.0, "asset_id": foley["id"], "approval": "approved"})
    SD.to_cues(film, 1)
    Q.add(film, {"asset_id": rain["id"], "scene": 1})
    Q.add(film, {"asset_id": theme["id"], "scene": 1, "shot": first, "start": 5.5})
    return film


def read(path):
    return sf.read(path, dtype="float32", always_2d=True)


def rms(x, rate, a, b, ch=0):
    seg = x[int(a * rate):int(b * rate), ch]
    return float(np.sqrt(np.mean(np.square(seg)))) if len(seg) else 0.0


def sha(path):
    return hashlib.sha1(open(path, "rb").read()).hexdigest()


# ---------------------------------------------------------------- the settings

def test_the_settings_are_checked_and_cleaned():
    s = P.clean_spec(None)
    assert s["rate"] == 48000 and s["bits"] == 24 and s["bwf"] is True and s["stems"] == list(P.STEMS) and s["mixes"] == ["final", "me"] and s["target_lufs"] is None and s["peak_db"] == -1.0
    assert P.clean_spec({"stems": ["music", "junk"], "mixes": [], "rate": 96000, "bits": 32, "target_lufs": -23, "peak_db": -2, "bwf": False})["stems"] == ["music"]
    for bad in ({"rate": 22050}, {"rate": True}, {"bits": 8}, {"target_lufs": -5}, {"target_lufs": "loud"}, {"peak_db": 0}, {"peak_db": -20}, {"stems": [], "mixes": []}, {"stems": "dialogue", "mixes": "x"}):
        with pytest.raises(SystemExit):
            P.clean_spec(bad)


def test_a_start_timecode_must_exist_at_the_films_frame_rate():
    f = T.FPS_24
    assert P.parse_tc("00:00:00:00", f) == 0.0 and P.parse_tc("01:00:00:00", f) == 3600.0 and P.parse_tc("00:00:01:12", f) == 1.5
    for bad in ("1:00:00", "00:00:00:24", "00:60:00:00", "aa:00:00:00", "", "00:00:00:000", "-1:00:00:00"):
        with pytest.raises(SystemExit):
            P.parse_tc(bad, f)


def test_the_master_gain_reaches_the_target_unless_the_ceiling_says_no():
    quiet = {"lufs": -30.0, "true_peak_db": -12.0}
    g = P.master_gain(quiet, 0.25, -23.0, -1.0)
    assert g == {"gain_db": 7.0, "capped": False, "reached": -23.0, "why": ""}
    hot = {"lufs": -20.0, "true_peak_db": -2.0}
    g = P.master_gain(hot, 0.8, -16.0, -1.0)
    assert g["gain_db"] == 1.0 and g["capped"] is True and g["reached"] == -19.0 and "ceiling won" in g["why"]
    assert P.master_gain(hot, 0.8, None, -1.0)["gain_db"] == 0.0
    over = {"lufs": -10.0, "true_peak_db": 1.0}
    g = P.master_gain(over, 1.2, None, -1.0)
    assert g["gain_db"] == -2.0 and "turned down 2.0 dB" in g["why"]
    assert P.master_gain(None, 0.0, -23, -1)["gain_db"] == 0.0


# ---------------------------------------------------------------- Broadcast WAV

def test_a_broadcast_chunk_is_written_read_back_and_leaves_the_sound_untouched(tmp_path):
    src = write(str(tmp_path / "a.wav"), np.stack([tone(1.0, 440), tone(1.0, 660)], 1), 48000)
    before, _ = read(src)
    P.add_bext(src, P.bext_chunk("Film - DIALOGUE", "FilmCrafter", "FCabc", "2026-11-06", "10:00:00", 172800000, "A=PCM,F=48000,W=24,M=stereo,T=FilmCrafter\r\n", {"lufs": -23.4, "range_lu": 6.0, "true_peak_db": -1.2}))
    b = P.read_bext(src)
    assert b["description"] == "Film - DIALOGUE" and b["originator"] == "FilmCrafter" and b["reference"] == "FCabc" and b["time_reference"] == 172800000 and b["version"] == 2
    assert b["loudness"] == -23.4 and b["true_peak"] == -1.2 and b["coding_history"].startswith("A=PCM,F=48000")
    after, rate = read(src)
    assert rate == 48000 and np.array_equal(before, after)
    P.add_bext(src, P.bext_chunk("Replaced", "FilmCrafter", "x", "2026-11-06", "10:00:00", 5, "A=PCM\r\n"))
    assert P.read_bext(src)["description"] == "Replaced" and P.read_bext(src)["time_reference"] == 5 and P.read_bext(src)["loudness"] is None
    assert open(src, "rb").read().count(b"bext") == 1
    ff = subprocess.run([P._ffmpeg(), "-hide_banner", "-i", src, "-f", "ffmetadata", "-"], capture_output=True, text=True).stdout     # another program reads it too
    assert "time_reference=5" in ff and "originator_reference=x" in ff


def test_a_file_that_is_not_a_wav_is_refused_and_not_damaged(tmp_path):
    p = tmp_path / "x.wav"
    p.write_bytes(b"not a wav file at all")
    with pytest.raises(SystemExit, match="not a WAV"):
        P.add_bext(str(p), P.bext_chunk("a", "b", "c", "d", "e", 0, ""))
    assert p.read_bytes() == b"not a wav file at all" and P.read_bext(str(p)) is None


# ---------------------------------------------------------------- planning

def test_the_plan_says_which_lanes_have_sound_and_which_do_not(full):
    p = P.plan(full, {"rate": 48000})
    assert p["lanes"] == {"dialogue": "yes", "foley": "yes", "sfx": "yes", "ambience": "yes", "music": "yes"} and p["files"] == 7 and p["estimated_bytes"] > 0 and p["shots"] == len(shot_ids(full))
    M.set_settings(full, {"mute_lanes": ["music"]})
    assert P.plan(full)["lanes"]["music"] == "left out in your mix settings"


def test_a_film_with_no_sound_is_refused_plainly(film):
    assert all(v == "no sound" for v in P.plan(film)["lanes"].values())
    with pytest.raises(SystemExit, match="no sound to export"):
        P.export(film)
    assert not os.path.isdir(os.path.join(film, "cache", "pro-audio")) or not os.listdir(os.path.join(film, "cache", "pro-audio"))


# ---------------------------------------------------------------- the export

def test_the_folder_has_stems_mixes_cue_sheet_timeline_and_report_and_every_file_reads_back(full):
    r = P.export(full, {"start_tc": "01:00:00:00"})
    folder = r["folder"]
    assert r["ok"] is True and r["problems"] == [] and os.path.basename(folder).startswith("My Film ")
    assert sorted(os.listdir(os.path.join(folder, "stems"))) == [f"{i} {n}.wav" for i, n in ((1, "DIALOGUE"), (2, "FOLEY"), (3, "EFFECTS"), (4, "AMBIENCE"), (5, "MUSIC"))] or len(os.listdir(os.path.join(folder, "stems"))) == 5
    assert len(os.listdir(os.path.join(folder, "mixes"))) == 2
    for name in ("README.txt", "report.json", "My Film cue sheet.csv", "My Film cue sheet.json", "My Film audio.otio"):
        assert os.path.isfile(os.path.join(folder, name)), name
    rep = json.load(open(os.path.join(folder, "report.json"), encoding="utf-8"))
    assert rep["ok"] and rep["start_tc"] == "01:00:00:00" and rep["not_checked"] and len(rep["stems"]) == 5 and len(rep["mixes"]) == 2
    duration = rep["seconds"]
    for f in [*rep["stems"], *rep["mixes"]]:
        info = sf.info(os.path.join(folder, *f["file"].split("/")))
        assert info.samplerate == 48000 and info.subtype == "PCM_24" and info.channels == 2 and abs(info.duration - duration) < 0.05
        b = P.read_bext(os.path.join(folder, *f["file"].split("/")))
        assert b["time_reference"] == 3600 * 48000 and b["originator"] == "FilmCrafter"                       # the start timecode, in samples
        meta = subprocess.run([P._ffmpeg(), "-hide_banner", "-i", os.path.join(folder, *f["file"].split("/")), "-f", "ffmetadata", "-"], capture_output=True, text=True).stdout
        assert f"time_reference={3600 * 48000}" in meta
    assert "none." in open(os.path.join(folder, "README.txt"), encoding="utf-8").read()


def band(x, rate, a, b, hz):
    """How much of a sound between seconds a and b is at one frequency (the size of that bin of its spectrum, per sample)."""
    seg = x[int(a * rate):int(b * rate), 0] * np.hanning(int(b * rate) - int(a * rate))
    spec = np.abs(np.fft.rfft(seg)) / max(1, len(seg))
    k = int(round(hz * len(seg) / rate))
    return float(np.max(spec[max(0, k - 3):k + 4]))


def test_each_lane_holds_only_its_own_sound(full):
    r = P.export(full, {"mixes": []})
    folder = r["folder"]
    stems = {os.path.basename(f)[3:-4]: read(os.path.join(folder, f)) for f in r["stems"]}
    rate = stems["DIALOGUE"][1]
    dx, fo, ef, mu, am = (stems[k][0] for k in ("DIALOGUE", "FOLEY", "EFFECTS", "MUSIC", "AMBIENCE"))
    # the Foley sound is a 1500 Hz tone at 2 s, the ordinary effect a 900 Hz tone at 4 s, the music 600 Hz from 5.5 s, the rain 300 Hz all through; the voice is 150-260 Hz
    assert band(fo, rate, 2.05, 2.45, 1500) > 0.02 and band(dx, rate, 2.05, 2.45, 1500) < 0.001 and band(ef, rate, 2.05, 2.45, 1500) < 0.001 and band(mu, rate, 2.05, 2.45, 1500) < 0.001
    assert band(ef, rate, 4.05, 4.45, 900) > 0.02 and band(fo, rate, 4.05, 4.45, 900) < 0.001 and band(dx, rate, 4.05, 4.45, 900) < 0.001
    assert band(mu, rate, 5.6, 5.9, 600) > 0.02 and band(ef, rate, 5.6, 5.9, 600) < 0.001 and band(fo, rate, 5.6, 5.9, 600) < 0.001
    assert rms(dx, rate, 0.0, 2.0) > 0.01 and rms(fo, rate, 0.0, 1.9) < 0.001 and rms(mu, rate, 0.0, 5.0) < 0.001 and rms(am, rate, 0.5, 2.0) > 0.01


def test_the_mix_is_the_sum_of_the_stems_times_one_gain_and_the_me_has_no_dialogue(full):
    r = P.export(full, {"bits": 32, "bwf": False, "target_lufs": -23.0})
    folder = r["folder"]
    rep = json.load(open(os.path.join(folder, "report.json"), encoding="utf-8"))
    stems = {s["lane"]: read(os.path.join(folder, *s["file"].split("/")))[0] for s in rep["stems"]}
    final = next(m for m in rep["mixes"] if m["kind"] == "final")
    me = next(m for m in rep["mixes"] if m["kind"] == "me")
    fx, _ = read(os.path.join(folder, *final["file"].split("/")))
    n = min(len(fx), *(len(v) for v in stems.values()))
    total = sum(v[:n] for v in stems.values()) * 10 ** (final["master_gain_db"] / 20)
    assert np.max(np.abs(total - fx[:n])) < 2e-3
    mx, rate = read(os.path.join(folder, *me["file"].split("/")))
    first = next(iter(P.film_times(full)[0].values()))
    assert rms(fx, rate, first[0], first[0] + 3.0) > rms(mx, rate, first[0], first[0] + 3.0) * 1.5 and me["stems_in"] == ["foley", "sfx", "ambience", "music"]
    assert "dialogue" in final["stems_in"]


def test_the_final_mix_reaches_the_loudness_target_and_stays_under_the_ceiling(full):
    r = P.export(full, {"target_lufs": -23.0, "peak_db": -1.0})
    final = next(m for m in r["mixes"] if "FINAL" in m["file"])
    from filmcrafter_engine.export import measure_loudness
    m = measure_loudness(os.path.join(r["folder"], *final["file"].split("/")))
    assert final["capped"] is False and abs(m["lufs"] - (-23.0)) < 0.6 and m["true_peak_db"] <= -0.9 and final["lufs"] == pytest.approx(-23.0, abs=0.05)
    b = P.read_bext(os.path.join(r["folder"], *final["file"].split("/")))
    assert b["loudness"] == pytest.approx(final["lufs"], abs=0.02)


def test_a_loud_mix_is_turned_down_to_the_ceiling_and_the_report_says_so(full, tmp_path):
    loud = asset(full, tmp_path, "loud.wav", 3.0, 700, 0.95, kind="music")
    for k in range(3):
        Q.add(full, {"asset_id": loud["id"], "scene": 1, "shot": shot_ids(full)[0]["id"], "start": 0.5 + k * 0.1})
    r = P.export(full, {"peak_db": -3.0})
    final = next(m for m in r["mixes"] if "FINAL" in m["file"])
    assert final["master_gain_db"] < 0 and final["capped"] is True and "turned down" in final["note"] and final["true_peak_db"] <= -2.9


def test_the_16_bit_and_96_khz_and_plain_wav_choices_are_honoured(full):
    r = P.export(full, {"rate": 96000, "bits": 16, "bwf": False, "stems": ["dialogue"], "mixes": []})
    f = os.path.join(r["folder"], *r["stems"][0].split("/"))
    info = sf.info(f)
    assert info.samplerate == 96000 and info.subtype == "PCM_16" and P.read_bext(f) is None and len(r["stems"]) == 1 and r["mixes"] == []


def test_a_lane_left_out_in_the_mix_settings_gets_no_stem_and_says_why(full):
    M.set_settings(full, {"mute_lanes": ["ambience"]})
    r = P.export(full)
    assert not any("AMBIENCE" in s for s in r["stems"]) and "mix settings" in r["lanes_without_sound"]["ambience"]


def test_a_moved_line_is_placed_where_it_was_moved_in_the_dialogue_stem(full):
    first = shot_ids(full)[0]["id"]

    def onset():
        r = P.export(full, {"stems": ["dialogue"], "mixes": []})
        x, rate = read(os.path.join(r["folder"], *r["stems"][0].split("/")))
        return float(np.argmax(np.abs(x[:, 0]) > 0.01)) / rate
    a = onset()
    adrsync.nudge(full, first, "Sarah", frames=12)
    assert onset() == pytest.approx(a + 0.5, abs=0.03)


def test_the_export_changes_nothing_in_the_film_and_leaves_no_scratch_files(full):
    skip = (os.sep + "exports" + os.sep, os.sep + "cache" + os.sep)

    def hashes():
        return {os.path.join(r, f): sha(os.path.join(r, f)) for r, _, fs in os.walk(full) for f in fs if not any(s in os.path.join(r, f) for s in skip)}
    before = hashes()
    P.export(full)
    assert hashes() == before
    assert not os.path.isdir(os.path.join(full, "cache", "pro-audio")) or not os.listdir(os.path.join(full, "cache", "pro-audio"))


# ---------------------------------------------------------------- the cue sheet

def test_the_cue_sheet_lists_every_voice_line_and_sound_with_timecode_origin_and_licence(full, tmp_path):
    a = asset(full, tmp_path, "=cmd.wav", 0.5, 800)
    AL.update(full, a["id"], {"name": "=HYPERLINK(evil)", "licence": {"source": "Sound Co", "note": "paid, 2026", "commercial": "yes"}})
    Q.add(full, {"asset_id": a["id"], "scene": 1, "shot": shot_ids(full)[0]["id"], "start": 1.0})
    r = P.export(full, {"start_tc": "01:00:00:00", "stems": ["dialogue"], "mixes": []})
    rows = list(csv.DictReader(open(os.path.join(r["folder"], "My Film cue sheet.csv"), encoding="utf-8-sig")))
    lanes = [x["Lane"] for x in rows]
    assert lanes.count("DIALOGUE") == 2 and {"FOLEY", "EFFECTS", "AMBIENCE", "MUSIC"} <= set(lanes)
    assert all(x["TC in"].startswith("01:00:") for x in rows) and rows[0]["TC in"] == "01:00:00:00"
    evil = next(x for x in rows if "HYPERLINK" in x["Name"])
    assert evil["Name"].startswith("'=") and evil["Licence source"] == "Sound Co" and evil["Commercial use"] == "yes" and evil["Licence note / voice"] == "paid, 2026" and evil["Origin"] == "imported"
    assert all(x["Name"][:1] not in "=+-@" for x in rows if x["Name"])
    dlg = next(x for x in rows if x["Lane"] == "DIALOGUE")
    assert dlg["Name"] == "Sarah" and dlg["Origin"] == "recording" and dlg["Shot"]
    js = json.load(open(os.path.join(r["folder"], "My Film cue sheet.json"), encoding="utf-8"))
    assert len(js["rows"]) == len(rows) and "licence" in js["columns"]


# ---------------------------------------------------------------- OpenTimelineIO

def test_the_timeline_opens_in_the_real_opentimelineio_library_and_points_at_copied_originals(full):
    otio = pytest.importorskip("opentimelineio")
    r = P.export(full, {"start_tc": "01:00:00:00", "stems": [], "mixes": ["final"]})
    tl = otio.adapters.read_from_file(os.path.join(r["folder"], "My Film audio.otio"))
    tracks = list(tl.tracks)
    assert {t.name for t in tracks} >= {"DIALOGUE", "FOLEY", "EFFECTS", "AMBIENCE", "MUSIC"} and all(t.kind == "Audio" for t in tracks)
    assert tl.global_start_time.to_seconds() == 3600.0
    clips = [c for t in tracks for c in t.find_clips()]
    assert len(clips) >= 6
    for c in clips:
        ref = c.media_reference
        assert os.path.isfile(os.path.join(r["folder"], ref.target_url)) and c.source_range.duration.value > 0
    for t in tracks:                                                                      # one sound at a time on a track
        assert t.duration().value >= 0
    amb = next(t for t in tracks if t.name.startswith("AMBIENCE"))
    assert len(list(amb.find_clips())) >= 2                                                # a looping sound is laid end to end over its span


def test_overlapping_sounds_on_one_lane_go_to_more_than_one_track(full, tmp_path):
    otio = pytest.importorskip("opentimelineio")
    fx = asset(full, tmp_path, "fx2.wav", 2.0, 1100)
    for k in range(2):
        Q.add(full, {"asset_id": fx["id"], "scene": 1, "shot": shot_ids(full)[0]["id"], "start": 6.0 + k * 0.5})
    r = P.export(full, {"stems": [], "mixes": ["final"]})
    tl = otio.adapters.read_from_file(os.path.join(r["folder"], "My Film audio.otio"))
    assert {"EFFECTS 1", "EFFECTS 2"} <= {t.name for t in tl.tracks}


def test_no_media_copies_means_no_timeline_and_the_rest_still_works(full):
    r = P.export(full, {"media": False, "stems": ["music"], "mixes": []})
    assert r["otio"] is None and not os.path.isdir(os.path.join(r["folder"], "media")) and r["ok"]


# ---------------------------------------------------------------- the command line

def test_the_command_line_answers_with_json(full, film, capsys):
    assert P.main(["plan", full, "--data", json.dumps({"rate": 48000})]) == 0
    assert P.main(["export", full, "--data", json.dumps({"stems": ["music"], "mixes": []})]) == 0
    assert P.main(["export", full, "--data", json.dumps({"rate": 12345})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip() and x.startswith("{")]
    results = [x for x in lines if x["event"] in ("result", "error")]
    assert [x["event"] for x in results] == ["result", "result", "error"] and results[1]["data"]["ok"] is True
