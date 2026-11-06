"""The audio quality inspector: real audio with known faults, measured and reported. Real ffmpeg for loudness; nothing is sent anywhere and nothing is changed."""
import hashlib
import json
import os

import numpy as np
import pytest
import soundfile as sf

from filmcrafter_engine import audiocues as Q, audiolib as AL, audioqa as A, bible, shots as S, story, voiceover as V

R = A.RATE
SCRIPT = "".join(f"INT. ROOM {n} - DAY\n\nA small room.\n\nSARAH\n{w}.\n\n" for n, w in enumerate(["One", "Two", "Three", "Four"], 1))


def sine(secs=3.0, hz=220, amp=0.3, rate=R, phase=0.0):
    t = np.arange(int(rate * secs)) / rate
    return (amp * np.sin(2 * np.pi * hz * t + phase)).astype("float32")


def speechlike(secs=4.0, amp=0.25, floor=0.0, seed=1):
    """Bursts of tone with pauses between them, over an optional steady noise: a stand-in for a voice."""
    x = np.zeros(int(R * secs), dtype="float32")
    t = np.arange(len(x)) / R
    for i in range(int(secs * 2)):
        a, b = int(i * 0.5 * R), int((i * 0.5 + 0.3) * R)
        env = np.hanning(b - a)
        x[a:b] += (amp * np.sin(2 * np.pi * (180 + 40 * (i % 3)) * t[a:b]) * env).astype("float32")
    if floor:
        x += np.random.default_rng(seed).normal(0, floor, len(x)).astype("float32")
    return x


def write(path, x, rate=R):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sf.write(path, x, rate)
    return path


def codes(fs):
    return [f["code"] for f in fs]


# ---------------------------------------------------------------- measuring

def test_a_clean_tone_has_nothing_to_report():
    m = A.measure(sine(), R)
    assert m["clip_runs"] == 0 and m["dropout_count"] == 0 and m["click_count"] == 0 and m["silences"] == [] and m["noise_floor_db"] is None and m["dc"] < 0.001 and m["mono_loss_db"] == 0.0
    assert A.findings(m, "effect", "tone") == [] and A.findings(m, "music", "tone") == []


def test_clipping_is_counted_and_a_peak_at_the_ceiling_without_flattening_is_only_a_note():
    flat = np.clip(sine(amp=0.3) * 5, -1, 1)
    m = A.measure(flat, R)
    assert m["clip_runs"] > 20 and m["clip_at"]
    f = A.findings(m, "voice", "x")
    assert f[0]["code"] == "clipping" and f[0]["severity"] == "fix"
    few = sine(amp=0.3)
    few[1000:1010] = 1.0
    assert A.findings(A.measure(few, R), "voice", "x")[0]["severity"] == "look"
    touch = sine(amp=0.3)
    touch[5000] = 0.9995 * 0 + 0.9985
    mm = A.measure(touch, R)
    assert mm["clip_runs"] == 0 and A.findings(mm, "voice", "x")[0] == {"severity": "note", "code": "peak", "where": "x", "what": mm and A.findings(mm, "voice", "x")[0]["what"], "measured": mm["peak_db"], "limit": -0.1}


def test_silent_and_empty_files_are_wrong():
    assert A.findings(A.measure(sine() * 1e-6, R), "voice", "q")[0]["code"] == "silent"
    assert A.findings(A.measure(np.zeros((0, 2), dtype="float32"), R), "voice", "q")[0]["code"] == "empty"


def test_a_short_gap_of_digital_silence_inside_loud_sound_is_a_dropout_and_three_are_wrong():
    x = sine(secs=4.0)
    x[R:R + 400] = 0
    m = A.measure(x, R)
    assert m["dropout_count"] == 1 and 0.99 < m["dropouts"][0]["at"] < 1.01
    assert A.findings(m, "effect", "x")[0]["severity"] == "look"
    for k in (2, 3):
        x[k * R: k * R + 400] = 0
    assert A.findings(A.measure(x, R), "effect", "x")[0]["severity"] == "fix"
    pause = np.concatenate([sine(1.0), np.zeros(R // 2, dtype="float32"), sine(1.0)])
    assert A.measure(pause, R)["dropout_count"] == 0                                   # a half-second pause is a pause, not a dropout


def test_a_sudden_jump_is_a_click_and_a_smooth_sound_has_none():
    x = sine()
    assert A.measure(x, R)["click_count"] == 0
    x[R + 50:] = -x[R + 50:]
    m = A.measure(x, R)
    assert m["click_count"] == 1 and 0.99 < m["clicks_at"][0] < 1.01
    noise = np.random.default_rng(3).normal(0, 0.05, R * 3).astype("float32")
    assert A.measure(noise, R)["click_count"] == 0                                     # rough is not the same as a jump


def test_a_shifted_centre_and_channels_that_cancel_are_reported():
    assert A.findings(A.measure(sine() + 0.05, R), "effect", "x")[0]["code"] == "dc"
    s = sine()
    m = A.measure(np.stack([s, -s], 1), R)
    assert m["mono_loss_db"] < -20 and "mono" in codes(A.findings(m, "effect", "x"))
    assert A.measure(np.stack([s, s], 1), R)["mono_loss_db"] == 0.0
    assert A.measure(np.stack([s, 0.5 * s], 1), R)["mono_loss_db"] > -1


def test_a_long_silence_inside_a_recording_is_worth_a_listen_but_the_ends_are_not():
    gap = np.concatenate([speechlike(1.0), np.zeros(R * 3, dtype="float32"), speechlike(1.0)])
    m = A.measure(gap, R)
    assert [s["where"] for s in m["silences"]] == ["inside"] and m["silences"][0]["length"] >= 2.9
    assert "long_silence" in codes(A.findings(m, "voice", "v"))
    ends = np.concatenate([np.zeros(R * 3, dtype="float32"), speechlike(1.0), np.zeros(R * 3, dtype="float32")])
    me = A.measure(ends, R)
    assert [s["where"] for s in me["silences"]] == ["start", "end"] and "long_silence" not in codes(A.findings(me, "voice", "v"))
    assert "almost_silent" in codes(A.findings(me, "mix", "m"))


def test_steady_noise_under_a_voice_is_found_only_where_there_are_pauses_to_hear_it_in():
    noisy = speechlike(4.0, floor=0.02)
    m = A.measure(noisy, R)
    assert m["noise_floor_db"] is not None and m["noise_floor_db"] > -50
    assert "noise" in codes(A.findings(m, "voice", "v")) and "noise" not in codes(A.findings(m, "effect", "v"))
    assert "noise" not in codes(A.findings(A.measure(speechlike(4.0, floor=0.0005), R), "voice", "v"))
    assert A.measure(sine(), R)["noise_floor_db"] is None                              # a sound that never pauses has no floor to measure


# ---------------------------------------------------------------- files

def test_a_real_file_is_measured_including_loudness_and_true_peak(tmp_path):
    p = write(str(tmp_path / "a.wav"), np.clip(sine(amp=0.9), -1, 1))
    r = A.inspect_file(p, "mix")
    assert r["ok"] and r["loudness"]["lufs"] < 0 and r["loudness"]["true_peak_db"] is not None and r["metrics"]["seconds"] == pytest.approx(3.0, abs=0.05)


def test_loudness_is_compared_with_the_target_only_for_a_mix(tmp_path):
    p = write(str(tmp_path / "a.wav"), sine(amp=0.3))
    lufs = A.inspect_file(p, "mix")["loudness"]["lufs"]
    assert "loudness" not in codes(A.inspect_file(p, "mix", target_lufs=lufs)["findings"])
    r = A.inspect_file(p, "mix", target_lufs=lufs + 6)
    assert "loudness" in codes(r["findings"]) and r["findings"][-1]["limit"] == lufs + 6 or "loudness" in codes(r["findings"])
    assert "loudness" not in codes(A.inspect_file(p, "voice", target_lufs=lufs + 6)["findings"])


def test_a_hot_file_is_flagged_for_its_true_peak(tmp_path):
    p = write(str(tmp_path / "hot.wav"), np.clip(sine(hz=997, amp=1.2), -1, 1))
    assert {"clipping", "true_peak"} <= set(codes(A.inspect_file(p, "mix")["findings"]))


def test_a_missing_or_unreadable_file_is_reported_not_raised(tmp_path):
    assert A.inspect_file(str(tmp_path / "nope.wav"))["findings"][0]["code"] == "missing"
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not sound at all")
    r = A.inspect_file(str(bad))
    assert r["ok"] is False and r["findings"][0]["code"] == "unreadable"


# ---------------------------------------------------------------- the whole film

@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def sarah_shots(film):
    return [s["id"] for s in V.status(film)["shots"] if any(p["lines"] for p in s["people"])][:4]


def attach(film, tmp_path, sid, x, name):
    V.attach(film, sid, "Sarah", write(str(tmp_path / "rec" / name), x), fit=False)


def hashes(d):
    out = {}
    for root, _, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)
            out[p] = hashlib.sha1(open(p, "rb").read()).hexdigest()
    return out


def test_every_recording_is_checked_and_named_by_who_and_where(film, tmp_path):
    ids = sarah_shots(film)
    attach(film, tmp_path, ids[0], speechlike(2.0), "a.wav")
    attach(film, tmp_path, ids[1], np.clip(speechlike(2.0) * 6, -1, 1), "b.wav")
    r = A.film(film)
    voice = [it for it in r["items"] if it["role"] == "voice"]
    assert len(voice) == 2 and r["summary"]["files"] == 2
    bad = next(it for it in voice if it["shot"] == ids[1])
    assert bad["where"] == f"Sarah in {ids[1]}" and "clipping" in codes(bad["findings"]) and r["summary"]["fix"] + r["summary"]["look"] >= 1
    assert "not a quality score" in r["says"] and "How good anything sounds." in r["not_measured"]


def test_a_recording_longer_than_its_shot_is_flagged(film, tmp_path):
    sid = sarah_shots(film)[0]
    dur = float(V._contracts(film)[sid]["generation"]["duration"])
    attach(film, tmp_path, sid, speechlike(dur + 3.0), "long.wav")
    assert "longer_than_shot" in codes(next(it for it in A.film(film)["items"] if it["role"] == "voice")["findings"])


def test_a_line_much_louder_or_quieter_than_the_others_is_a_low_confidence_note(film, tmp_path):
    ids = sarah_shots(film)
    for i, amp in enumerate((0.25, 0.25, 0.25, 0.03)):
        attach(film, tmp_path, ids[i], speechlike(2.0, amp=amp), f"s{i}.wav")
    c = A.film(film)["consistency"]
    out = [x for x in c if x["code"] == "level_outlier"]
    assert len(out) == 1 and out[0]["where"] == f"Sarah in {ids[3]}" and out[0]["confidence"] == "low" and out[0]["severity"] == "note"
    ids2 = sarah_shots(film)[:2]
    assert not [x for x in A.film(film)["consistency"] if x["where"].endswith(ids2[0])]


def test_too_few_lines_to_compare_are_not_compared(film, tmp_path):
    ids = sarah_shots(film)
    attach(film, tmp_path, ids[0], speechlike(2.0, amp=0.25), "a.wav")
    attach(film, tmp_path, ids[1], speechlike(2.0, amp=0.03), "b.wav")
    assert [x for x in A.film(film)["consistency"] if x["code"] == "level_outlier"] == []


def test_more_than_one_voice_or_model_behind_a_persons_lines_is_reported(film, tmp_path):
    ids = sarah_shots(film)
    for i in range(2):
        attach(film, tmp_path, ids[i], speechlike(2.0), f"g{i}.wav")
    meta = V._meta(film)
    gen = os.path.join(film, "voice", "_generated")
    os.makedirs(gen, exist_ok=True)
    for i, (model, vid) in enumerate((("eleven_v4", "AbCdEfGh1234"), ("eleven_multilingual_v2", "ZyXwVu987654"))):
        e = meta["shots"][ids[i]][0]
        e["source"], e["gen"] = "elevenlabs", f"{ids[i]}-m{i}.mp3"
        json.dump({"model": model, "voice_id": vid, "key": "sarah"}, open(os.path.join(gen, f"{ids[i]}-m{i}.json"), "w"))
    V._save_meta(film, meta)
    c = [x for x in A.film(film)["consistency"] if x["code"] == "voice_changed"]
    assert len(c) == 1 and c[0]["severity"] == "look" and c[0]["confidence"] == "high" and "eleven_v4" in c[0]["what"] and "eleven_multilingual_v2" in c[0]["what"]


def test_a_cue_sound_that_starts_at_full_level_with_no_fade_can_click(film, tmp_path):
    sid = sarah_shots(film)[0]
    hit = AL.import_files(film, "sfx", [write(str(tmp_path / "src" / "hit.wav"), sine(1.0, 440, 0.6, phase=np.pi / 2))], None)["assets"][-1]
    cid = Q.add(film, {"asset_id": hit["id"], "scene": 1, "shot": sid, "start": 0.5})["id"]
    f = [x for it in A.film(film)["items"] for x in it["findings"] if x["code"] == "abrupt_edit"]
    assert len(f) == 1 and "fade" in f[0]["what"]
    Q.update(film, cid, {"fade_in": 0.05, "fade_out": 0.05})
    assert not [x for it in A.film(film)["items"] for x in it["findings"] if x["code"] == "abrupt_edit"]
    Q.update(film, cid, {"fade_in": 0, "fade_out": 0, "loop": True})
    assert not [x for it in A.film(film)["items"] for x in it["findings"] if x["code"] == "abrupt_edit"]


def test_a_sound_that_fades_in_from_silence_has_no_abrupt_edit(film, tmp_path):
    hit = AL.import_files(film, "sfx", [write(str(tmp_path / "src" / "soft.wav"), sine(1.0, 440, 0.6) * np.hanning(R).astype("float32"))], None)["assets"][-1]
    Q.add(film, {"asset_id": hit["id"], "scene": 1, "shot": sarah_shots(film)[0]})
    assert not [x for it in A.film(film)["items"] for x in it["findings"] if x["code"] == "abrupt_edit"]


def test_a_finished_film_file_is_inspected_as_a_mix_and_must_be_inside_the_film_or_chosen_by_full_path(film, tmp_path):
    p = write(os.path.join(film, "exports", "cut.wav"), sine(2.0))
    r = A.film(film, "exports/cut.wav")
    assert r["items"][0]["role"] == "mix" and r["items"][0]["where"].startswith("The finished film") and r["items"][0]["loudness"]
    assert A.film(film, p)["items"][0]["role"] == "mix"
    for bad in ("../x.wav", "..\\x.wav", "voice/../../x.wav"):
        with pytest.raises(SystemExit, match="not inside"):
            A.film(film, bad)


def test_the_inspector_changes_nothing(film, tmp_path):
    ids = sarah_shots(film)
    for i in range(3):
        attach(film, tmp_path, ids[i], speechlike(2.0), f"r{i}.wav")
    write(os.path.join(film, "exports", "cut.wav"), sine(1.0))
    before = hashes(film)
    A.film(film, "exports/cut.wav")
    assert hashes(film) == before


def test_a_film_with_no_sound_says_so_plainly(film):
    r = A.film(film)
    assert r["summary"] == {"fix": 0, "look": 0, "note": 0, "files": 0} and r["says"].startswith("Nothing here needs a second listen.")


def test_the_command_line_answers_with_json(film, tmp_path, capsys):
    p = write(os.path.join(film, "exports", "cut.wav"), sine(1.0))
    assert A.main(["film", film, "--data", json.dumps({"file": "exports/cut.wav"})]) == 0
    assert A.main(["inspect", film, "--data", json.dumps({"file": "exports/cut.wav", "role": "voice"})]) == 0
    assert A.main(["inspect", film, "--data", json.dumps({"file": "../x.wav"})]) == 1
    assert A.main(["inspect", film, "--data", "{}"]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert [x["event"] for x in lines] == ["result", "result", "error", "error"] and lines[0]["data"]["summary"]["files"] == 1
