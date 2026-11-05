"""Video finishing: flicker is measured (not guessed), fades/cuts/motion are not called flicker, restore is measurably calmer and leaves the original alone, profiles produce real files."""
import hashlib
import json
import os
import subprocess

import numpy as np
import pytest

from filmcrafter_engine import videofinish as V


def make_clip(path, gains, w=160, h=90, fps=24, audio=True):
    rng = np.random.default_rng(2)
    yy, xx = np.mgrid[0:h, 0:w]
    base = (90 + 60 * np.sin(xx / 17.0) + 30 * np.cos(yy / 11.0) + rng.normal(0, 2, (h, w))).astype(np.float32)
    frames = []
    for i, g in enumerate(gains):
        f = base.copy()
        x0 = 10 + (i * 2) % (w - 40)
        f[30:60, x0:x0 + 30] = 220                                                    # a moving block, so there is real motion
        frames.append(np.clip(f * g, 0, 255).astype(np.uint8))
    raw = np.stack(frames)
    cmd = [V.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={len(gains) / fps}"]
    cmd += ["-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-shortest"] if audio else []) + [str(path)]
    subprocess.run(cmd, input=raw.tobytes(), check=True, capture_output=True)


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("film")
    (d / "exports").mkdir()
    n = 72
    rng = np.random.default_rng(7)
    make_clip(d / "exports" / "steady.mp4", [1.0] * n)
    make_clip(d / "exports" / "fade.mp4", list(np.linspace(1.0, 0.5, n)))
    make_clip(d / "exports" / "cut.mp4", [1.0] * 36 + [0.45] * 36)
    make_clip(d / "exports" / "flicker.mp4", list(1.0 + rng.uniform(-0.12, 0.12, n)))
    return str(d)


def lvl(d, name):
    return V.flicker(d, f"exports/{name}.mp4")["report"]


def test_steady_fade_and_cut_are_not_called_flicker_and_real_flicker_is(clips):
    s, f, c, k = (lvl(clips, n) for n in ("steady", "fade", "cut", "flicker"))
    assert s["level"] == "Calm" and f["level"] == "Calm" and c["level"] == "Calm"        # motion, a slow fade and a hard cut are not flicker
    assert k["level"] in ("Noticeable", "Strong") and k["score"] > 3 * max(s["score"], 0.2)
    assert "treated as cuts" in c["note"]


def test_too_few_frames_say_unknown(tmp_path):
    (tmp_path / "a").mkdir()
    make_clip(tmp_path / "a" / "x.mp4", [1.0] * 4, audio=False)
    r = V.flicker(str(tmp_path), "a/x.mp4")["report"]
    assert r["level"] == "Unknown" and r["confidence"] == "low"


def test_restore_is_measurably_calmer_keeps_audio_and_never_touches_the_original(clips):
    src = os.path.join(clips, "exports", "flicker.mp4")
    before = sha(src)
    r = V.restore(clips, "exports/flicker.mp4", "balanced")
    assert sha(src) == before and os.path.isfile(r["output_path"]) and r["output"].startswith("project:restore/")
    assert r["after"]["score"] < r["before"]["score"] and r["better"] is True
    probe = subprocess.run([V.ffmpeg(), "-i", r["output_path"]], capture_output=True, text=True).stderr
    assert "Audio:" in probe
    assert V.status(clips)["restored"][-1]["id"] == r["id"]
    assert not [f for f in os.listdir(os.path.join(clips, "restore")) if ".tmp" in f]


def test_restore_of_an_already_steady_video_does_not_claim_a_gain(clips):
    r = V.restore(clips, "exports/steady.mp4", "gentle")
    assert r["better"] is False and "keep the original" in r["note"]


def test_finish_makes_real_files_in_each_profile_and_keeps_the_original(clips):
    src = os.path.join(clips, "exports", "steady.mp4")
    before = sha(src)
    for prof in ("web", "small", "h265", "master"):
        r = V.finish(clips, "exports/steady.mp4", "film" if prof == "web" else "none", prof)
        assert os.path.getsize(r["output_path"]) > 1000 and r["output"].startswith("project:finish/") and r["output_path"].endswith(".mp4")
    assert sha(src) == before
    r = V.finish(clips, "exports/steady.mp4", "clean", "prores")
    assert r["output_path"].endswith(".mov") and os.path.getsize(r["output_path"]) > 1000


def test_files_outside_the_film_and_unknown_choices_are_refused(clips, tmp_path):
    for bad in ("../x.mp4", "C:/Windows/notepad.exe", "exports/missing.mp4", "project:../../etc/passwd"):
        with pytest.raises(SystemExit):
            V.flicker(clips, bad)
    with pytest.raises(SystemExit):
        V.finish(clips, "exports/steady.mp4", "../../evil", "web")
    with pytest.raises(SystemExit):
        V.restore(clips, "exports/steady.mp4", "extreme")


def test_videos_lists_exports_and_presets_name_everything(clips):
    assert [v["name"] for v in V.videos(clips)["videos"]] and {p["id"] for p in V.presets()["profiles"]} >= {"web", "prores", "master"}
