"""The finishing pipeline for a clip made from a set, on real video made with ffmpeg: every stage really runs, the delivered file is read back and checked, an interrupted run resumes, a deleted file is made again,
a clip with strong flicker is calmed (and measured to be), and the validation catches a file that does not match."""
import hashlib
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from filmcrafter_engine import bible, setpipeline as P, shots as S, story, worldlock as WL  # noqa: E402
from filmcrafter_engine.export import ffmpeg  # noqa: E402

SCRIPT = "INT. KITCHEN - DAY\n\nSARAH stirs a pot.\n\nSARAH\nBreakfast is ready.\n"


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def make_clip(film, name="clip.mp4", seconds=2, flicker=False, audio=True):
    out = os.path.join(film, "exports")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, name)
    vf = "eq=brightness='(random(1)-0.5)*0.22':eval=frame" if flicker else "null"
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=24:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", *(["-c:a", "aac"] if audio else []), "-shortest", path]
    subprocess.run(cmd, check=True)
    return "exports/" + name, path


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def test_the_plan_reads_the_clip_and_lists_the_stages(film):
    ref, _ = make_clip(film)
    pl = P.plan(film, ref, {"enhance": True, "look": "film", "profile": "master"})
    assert pl["info"]["width"] == 320 and pl["info"]["height"] == 180 and pl["info"]["frames"] == 48 and pl["info"]["audio"] is True and pl["info"]["fps"] == 24.0
    assert [s["id"] for s in pl["stages"]] == list(P.STAGES) and pl["seconds_estimate"] > 0 and pl["options"]["look"] == "film" and pl["options"]["profile"] == "master"
    assert next(s for s in pl["stages"] if s["id"] == "enhance")["seconds_estimate"] > 0
    assert next(s for s in P.plan(film, ref, {})["stages"] if s["id"] == "enhance")["seconds_estimate"] == 0
    with pytest.raises(SystemExit):
        P.plan(film, "exports/nope.mp4")


def test_a_full_run_delivers_a_file_that_is_read_back_and_checked_and_the_original_is_untouched(film):
    ref, path = make_clip(film)
    before = sha(path)
    r0 = P.start(film, ref, {"enhance": True, "strength": 0.6, "look": "clean", "profile": "web"})
    r = P.run(film, r0["id"])
    assert r["done"] and r["valid"] is True and all(r["stages"][s]["status"] == "done" for s in P.STAGES)
    assert r["stages"]["continuity"]["result"]["skipped"].startswith("This clip is not tied to a set")
    assert r["stages"]["enhance"]["result"]["frames"] == 48 and r["stages"]["enhance"]["result"]["frames_per_second"] > 0
    out = P.VF._inside(film, r["delivered"])
    info = P.probe(out)
    assert info["frames"] == 48 and info["audio"] is True and (info["width"], info["height"]) == (320, 180) and info["codec"] == "h264"
    assert all(c["ok"] for c in r["stages"]["validate"]["result"]["checks"]) and r["total_seconds"] > 0
    assert sha(path) == before                                                 # the clip itself was never written
    names = [c["check"] for c in r["stages"]["validate"]["result"]["checks"]]
    assert "Sound kept" in names and "Starts playing before it is all downloaded" in names


def test_enhancing_changes_the_picture_and_leaving_it_off_does_not(film):
    ref, _ = make_clip(film)
    on = P.run(film, P.start(film, ref, {"enhance": True, "strength": 1.0})["id"])
    off = P.run(film, P.start(film, ref, {"enhance": False})["id"])
    assert off["stages"]["enhance"]["result"]["skipped"] == "Not asked for."
    a, b = P.VF._inside(film, on["stages"]["enhance"]["result"]["output"]), P.VF._inside(film, on["source"])
    from PIL import Image
    import numpy as np
    fa, fb = os.path.join(film, "a.png"), os.path.join(film, "b.png")
    P._frame_at(a, 0.5, fa)
    P._frame_at(b, 0.5, fb)
    assert np.abs(np.asarray(Image.open(fa).convert("L"), dtype=float) - np.asarray(Image.open(fb).convert("L"), dtype=float)).mean() > 0.3


def test_an_interrupted_run_resumes_and_does_not_redo_what_is_done(film, monkeypatch):
    ref, _ = make_clip(film)
    calls = {k: 0 for k in P.STAGES}
    real = dict(P.RUNNERS)

    def counting(name, fail_once=False):
        def f(d, run):
            calls[name] += 1
            if fail_once and calls[name] == 1:
                raise SystemExit("The disk was full.")
            return real[name](d, run)
        return f
    monkeypatch.setattr(P, "RUNNERS", {**{k: counting(k) for k in P.STAGES}, "finish": counting("finish", fail_once=True)})
    r0 = P.start(film, ref, {"enhance": True})
    with pytest.raises(SystemExit, match="Finish and deliver: The disk was full."):
        P.run(film, r0["id"])
    rec = P.get(film, r0["id"])
    assert [rec["stages"][s]["status"] for s in P.STAGES] == ["done", "done", "done", "done", "failed", "pending"] and rec["stages"]["finish"]["error"] == "The disk was full." and not rec["done"]
    r = P.run(film, r0["id"])                                                   # "reopen the project and carry on"
    assert r["done"] and r["valid"]
    assert calls == {"inspect": 1, "continuity": 1, "calm": 1, "enhance": 1, "finish": 2, "validate": 1}


def test_a_file_that_has_gone_missing_is_made_again_on_resume(film):
    ref, _ = make_clip(film)
    r = P.run(film, P.start(film, ref, {"enhance": True})["id"])
    os.remove(P.VF._inside(film, r["stages"]["enhance"]["result"]["output"]))
    rec = P._load(film, None, r["id"])
    rec["done"] = False
    P._save(film, None, rec)
    r2 = P.run(film, r["id"])
    assert os.path.isfile(P.VF._inside(film, r2["stages"]["enhance"]["result"]["output"])) and r2["valid"]


def test_strong_flicker_is_measured_and_calmed_and_the_gain_is_a_number(film):
    ref, _ = make_clip(film, "flick.mp4", seconds=3, flicker=True, audio=False)
    r = P.run(film, P.start(film, ref, {"calm": "auto"})["id"])
    c = r["stages"]["calm"]["result"]
    assert c["flicker"]["score"] >= P.VF.CALM and c["kept"] is True and c["gain"] > 0.05
    assert c["output"].startswith("project:restore/") and r["valid"]
    assert r["stages"]["validate"]["result"]["checks"][-1]["check"] in ("Starts playing before it is all downloaded", "No sound to keep")


def test_calming_can_be_switched_off(film):
    ref, _ = make_clip(film, "flick2.mp4", seconds=2, flicker=True, audio=False)
    r = P.run(film, P.start(film, ref, {"calm": "off"})["id"])
    assert r["stages"]["calm"]["result"]["skipped"] == "Switched off."


def test_the_continuity_stage_counts_the_sets_findings_without_stopping_the_run(film):
    ref, _ = make_clip(film)
    sid = WL.create(film, {"name": "S"})["id"]
    r = P.run(film, P.start(film, ref, {}, sid)["id"], sid)
    c = r["stages"]["continuity"]["result"]
    assert set(c["counts"]) == {"warning", "advice", "note", "deliberate"} and "marked deliberate" in c["advice"] and r["done"]


def test_validation_catches_a_delivered_file_that_does_not_match(film):
    ref, _ = make_clip(film, seconds=2)
    short, _ = make_clip(film, "short.mp4", seconds=1, audio=False)
    r = P.run(film, P.start(film, ref, {})["id"])
    rec = P._load(film, None, r["id"])
    rec["stages"]["finish"]["result"]["output"] = short
    v = P._validate(film, rec)
    failed = [c["check"] for c in v["checks"] if not c["ok"]]
    assert v["ok"] is False and "Same length as the clip" in failed and "Same number of frames" in failed and "Sound kept" in failed


def test_a_stage_that_fails_says_which_and_why_and_keeps_the_earlier_ones(film, monkeypatch):
    ref, _ = make_clip(film)
    real = P.RUNNERS["calm"]
    monkeypatch.setitem(P.RUNNERS, "calm", lambda d, run: (_ for _ in ()).throw(RuntimeError("boom")))
    r0 = P.start(film, ref, {})
    with pytest.raises(SystemExit, match="Calm flicker:"):
        P.run(film, r0["id"])
    rec = P.get(film, r0["id"])
    assert rec["stages"]["inspect"]["status"] == "done" and rec["stages"]["calm"]["status"] == "failed"
    monkeypatch.setitem(P.RUNNERS, "calm", real)
    assert P.run(film, r0["id"])["done"]


def test_run_ids_are_checked_and_runs_are_listed(film):
    ref, _ = make_clip(film)
    for bad in ("", "x", "../../etc/passwd", "pl-ZZZZZZZZ"):
        with pytest.raises(SystemExit, match="not a run"):
            P.get(film, bad)
    with pytest.raises(SystemExit, match="isn't here"):
        P.get(film, "pl-00000000")
    r = P.start(film, ref, {})
    assert P.runs(film)["runs"][0]["id"] == r["id"] and P.runs(film)["runs"][0]["stages"]["inspect"] == "pending"


def test_unknown_options_fall_back_to_safe_ones(film):
    ref, _ = make_clip(film)
    r = P.start(film, ref, {"look": "../../x", "profile": "nope", "calm": "huge", "strength": 99})
    assert r["options"] == {"set": None, "look": "none", "profile": "web", "calm": "auto", "enhance": False, "strength": 1.0}


def test_a_file_outside_the_film_is_refused(film, tmp_path):
    other = tmp_path / "x.mp4"
    other.write_bytes(b"x")
    with pytest.raises(SystemExit):
        P.start(film, str(other), {})


def test_the_command_line(film, capsys):
    ref, _ = make_clip(film)
    assert P.main(["plan", film, "--data", json.dumps({"ref": ref})]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["data"]["info"]["frames"] == 48
    assert P.main(["run", film, "--data", json.dumps({"run": "pl-00000000"})]) == 1
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["event"] == "error"
