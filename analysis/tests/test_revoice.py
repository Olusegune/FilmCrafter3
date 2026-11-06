"""Perform a line yourself and hear it in a character's voice: the engine side, with the voice-conversion program faked. Nothing is downloaded and no model runs here."""
import io
import json
import os

import numpy as np
import pytest
import soundfile as sf

from filmcrafter_engine import bible, cast_voice as C, revoice as R, shots, story, voiceover as V

SCRIPT = "INT. YARD - DAY\n\nA schoolyard.\n\nLILA\nIt looked weird.\n\nCHLOE\n(quietly)\nI know.\n\nLILA\nSee?\n"


def tone(path, secs=4.0, hz=220, amp=0.3):
    t = np.arange(int(22050 * secs)) / 22050
    sf.write(path, (amp * np.sin(2 * np.pi * hz * t)).astype("float32"), 22050)
    return path


class FakeProgram:
    """Stands in for pip and for vc_worker.py. Records every call; the 'conversion' writes a tone of the same length as the performance (or whatever `mode` says)."""
    def __init__(self):
        self.calls, self.mode, self.fail = [], "ok", None

    def __call__(self, args, env=None, timeout=600):
        self.calls.append((list(args), dict(env or {}), timeout))
        if "pip" in args:
            return (1, "", "boom") if self.fail == "pip" else (0, "", "")
        mode = args[2]
        if self.fail == mode:
            return 1, json.dumps({"ok": False, "why": "RuntimeError: nope"}) + "\n", ""
        if mode in ("check", "install"):
            return 0, json.dumps({"ok": True, "versions": {"torch": "2.6.0"}, "device": "cpu"}) + "\n", ""
        req = json.load(open(args[3], encoding="utf-8"))
        info = sf.info(req["source"])
        if self.mode == "silent":
            sf.write(req["out"], np.zeros(int(22050 * info.duration), dtype="float32"), 22050)
        elif self.mode == "short":
            sf.write(req["out"], 0.3 * np.ones(2000, dtype="float32"), 22050)
        elif self.mode == "none":
            pass
        else:
            t = np.arange(int(22050 * info.duration)) / 22050
            sf.write(req["out"], (0.3 * np.sin(2 * np.pi * 330 * t)).astype("float32"), 22050)
        return 0, json.dumps({"ok": True, "rate": 22050}) + "\n", ""


@pytest.fixture
def prog(monkeypatch, tmp_path):
    p = FakeProgram()
    monkeypatch.setattr(R, "_exec", p)
    monkeypatch.setattr(R, "HOME", str(tmp_path / "home"))
    return p


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    shots.breakdown(d)
    return d


@pytest.fixture
def sid(film):
    return V.status(film)["shots"][0]["id"]


@pytest.fixture
def installed(prog):
    R.install(True)
    prog.calls.clear()
    return prog


@pytest.fixture
def files(tmp_path):
    return {"perf": tone(str(tmp_path / "my line.wav"), 4.0, 130), "ref": tone(str(tmp_path / "voice sample.wav"), 8.0, 200), "short": tone(str(tmp_path / "short.wav"), 1.0)}


def with_ref(film, files):
    return R.set_reference(film, "Chloe", files["ref"], consent=True, holder="me", scope="this film only")


# ---------------------------------------------------------------- installing

def test_nothing_is_installed_without_a_yes(prog):
    with pytest.raises(SystemExit):
        R.install(False)
    with pytest.raises(SystemExit):
        R.install("yes")
    assert prog.calls == []
    assert R.runtime_status()["installed"] is False


def test_install_puts_everything_in_one_removable_folder_and_fetches_the_model_only_then(prog):
    s = R.install(True)
    assert s["installed"] and s["versions"] == {"torch": "2.6.0"}
    pip = next(c for c in prog.calls if "pip" in c[0])[0]
    assert "--target" in pip and pip[pip.index("--target") + 1].startswith(R.HOME)
    fetch = next(c for c in prog.calls if c[0][2:3] == ["install"])
    assert "HF_HUB_OFFLINE" not in fetch[1]
    assert all(m.split("==")[0] in " ".join(pip) for m in R.MODEL["packages"])


def test_a_failed_install_is_reported_and_leaves_it_not_installed(prog):
    prog.fail = "pip"
    with pytest.raises(SystemExit, match="could not be installed"):
        R.install(True)
    assert R.runtime_status()["installed"] is False
    prog.fail = "install"
    with pytest.raises(SystemExit, match="model files"):
        R.install(True)
    assert R.runtime_status()["installed"] is False


# ---------------------------------------------------------------- the reference voice and consent

def test_a_real_voice_needs_consent_whose_voice_and_what_for(film, files):
    with pytest.raises(SystemExit, match="owner agrees"):
        R.set_reference(film, "Chloe", files["ref"])
    with pytest.raises(SystemExit, match="whose voice"):
        R.set_reference(film, "Chloe", files["ref"], consent=True)
    with pytest.raises(SystemExit, match="used for"):
        R.set_reference(film, "Chloe", files["ref"], consent=True, holder="me")
    r = R.set_reference(film, "Chloe", files["ref"], consent=True, holder="Ada Obi", scope="this film only")["reference"]
    assert r["source"] == "permission" and r["consent"]["given"] is True and r["holder"] == "Ada Obi"
    assert os.path.isfile(os.path.join(film, *r["file"].split("/")))
    assert R.status(film)["people"][0]["scope"] == "this film only"


def test_a_take_in_the_cast_voice_needs_no_consent(film, sid):
    os.makedirs(os.path.join(film, "voice", "_generated"))
    tone(os.path.join(film, "voice", "_generated", f"{sid}-abc.wav"), 6.0)
    r = R.set_reference(film, "Chloe", f"voice/_generated/{sid}-abc.wav")["reference"]
    assert r["source"] == "film_take" and r["consent"]["given"] is False


def test_a_reference_must_be_a_sensible_length_and_a_real_sound(film, files, tmp_path):
    with pytest.raises(SystemExit, match="seconds long"):
        R.set_reference(film, "Chloe", files["short"], consent=True, holder="me", scope="x")
    bad = tmp_path / "x.wav"
    bad.write_bytes(b"not sound")
    with pytest.raises(SystemExit):
        R.set_reference(film, "Chloe", str(bad), consent=True, holder="me", scope="x")


def test_a_reference_outside_the_film_cannot_be_reached_by_a_relative_path(film):
    for p in ("../x.wav", "voice/../../x.wav", "..\\x.wav"):
        with pytest.raises(SystemExit, match="not inside"):
            R.set_reference(film, "Chloe", p, consent=True, holder="me", scope="x")


def test_replacing_an_approved_characters_reference_needs_a_yes(film, files, monkeypatch):
    with_ref(film, files)
    monkeypatch.setattr(R, "_approved", lambda d, k: True)
    other = tone(os.path.join(os.path.dirname(files["ref"]), "other.wav"), 9.0, 300)
    with pytest.raises(SystemExit, match="approved"):
        R.set_reference(film, "Chloe", other, consent=True, holder="me", scope="x")
    R.set_reference(film, "Chloe", other, consent=True, holder="me", scope="x", replace_approved=True)
    assert any(e["event"] == "reference_replaced" for e in R._records(film)["log"])


def test_taking_consent_back_stops_all_use_and_keeps_the_record(film, sid, files, installed):
    with_ref(film, files)
    R.revoke(film, "Chloe", "asked me to stop")
    with pytest.raises(SystemExit, match="taken back"):
        R.convert(film, sid, "Chloe", files["perf"])
    ref = R.status(film)["people"][0]
    assert ref["revoked"] is True and ref["file"]
    assert os.path.isfile(os.path.join(film, *ref["file"].split("/")))


def test_a_reference_changed_after_consent_is_not_used(film, sid, files, installed):
    r = with_ref(film, files)["reference"]
    with open(os.path.join(film, *r["file"].split("/")), "ab") as f:
        f.write(b"\0\0")
    with pytest.raises(SystemExit, match="was changed"):
        R.convert(film, sid, "Chloe", files["perf"])


# ---------------------------------------------------------------- converting

def test_a_conversion_makes_a_playable_synthetic_take_and_keeps_the_performance(film, sid, files, installed):
    with_ref(film, files)
    before = open(files["perf"], "rb").read()
    r = R.convert(film, sid, "Chloe", files["perf"], performed_by="Dee")
    out = os.path.join(film, *r["take"].split("/"))
    data, rate = sf.read(out)
    assert len(data) / rate == pytest.approx(4.0, abs=0.3) and float(np.abs(data).max()) > 0.05
    side = json.load(open(out[:-4] + ".json", encoding="utf-8"))
    assert side["kind"] == "revoice" and side["synthetic"] is True and side["performed_by"] == "Dee" and side["model"] == "chatterbox-vc" and side["model_licence"] == "MIT"
    assert open(os.path.join(film, *r["performance"].split("/")), "rb").read() == before == open(files["perf"], "rb").read()
    assert r["attached"] is False and V._meta(film)["shots"].get(sid, []) == []         # making a take attaches nothing


def test_the_conversion_runs_with_no_network_for_the_model_library_and_only_the_files_it_needs(film, sid, files, installed):
    with_ref(film, files)
    R.convert(film, sid, "Chloe", files["perf"])
    args, env, _ = installed.calls[-1]
    assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1" and env["PYTHONPATH"].startswith(R._site())
    req = json.load(open(args[3], encoding="utf-8")) if os.path.isfile(args[3]) else None
    assert req is None                                                                     # the request file is removed afterwards


def test_the_same_performance_and_voice_are_never_converted_twice(film, sid, files, installed):
    with_ref(film, files)
    a = R.convert(film, sid, "Chloe", files["perf"])
    n = len(installed.calls)
    b = R.convert(film, sid, "Chloe", files["perf"])
    assert b["cached"] is True and b["take"] == a["take"] and len(installed.calls) == n


def test_a_changed_performance_is_a_new_take_and_the_first_is_kept(film, sid, files, installed, tmp_path):
    with_ref(film, files)
    a = R.convert(film, sid, "Chloe", files["perf"])
    second = tone(str(tmp_path / "again.wav"), 3.0, 150)
    b = R.convert(film, sid, "Chloe", second)
    assert a["take"] != b["take"] and os.path.isfile(os.path.join(film, *a["take"].split("/")))


def test_without_an_install_or_a_reference_nothing_runs(film, sid, files, prog):
    with pytest.raises(SystemExit, match="no reference voice"):
        R.convert(film, sid, "Chloe", files["perf"])
    with_ref(film, files)
    with pytest.raises(SystemExit, match="not installed"):
        R.convert(film, sid, "Chloe", files["perf"])
    assert not any("vc_worker" in c[0][1] for c in prog.calls if len(c[0]) > 1)


@pytest.mark.parametrize("mode,why", [("silent", "silent"), ("short", "different length"), ("none", "could not be changed")])
def test_a_bad_result_is_refused_and_nothing_is_kept(film, sid, files, installed, mode, why):
    with_ref(film, files)
    installed.mode = mode
    with pytest.raises(SystemExit, match=why):
        R.convert(film, sid, "Chloe", files["perf"])
    gen = os.path.join(film, "voice", "_generated")
    assert not os.path.isdir(gen) or [f for f in os.listdir(gen) if "-rv" in f] == []
    assert os.path.isfile(files["perf"])


def test_the_programs_own_error_reaches_the_person_and_the_performance_is_kept(film, sid, files, installed):
    with_ref(film, files)
    installed.fail = "convert"
    with pytest.raises(SystemExit, match="nope.*performance is kept"):
        R.convert(film, sid, "Chloe", files["perf"])


def test_bad_names_and_paths_are_refused(film, sid, files, installed):
    with_ref(film, files)
    for bad in ("../x", "S1/../..", "", "a b"):
        with pytest.raises(SystemExit):
            R.convert(film, bad, "Chloe", files["perf"])
    with pytest.raises(SystemExit, match="no shot"):
        R.convert(film, "S99-99", "Chloe", files["perf"])
    with pytest.raises(SystemExit, match="not inside"):
        R.convert(film, sid, "Chloe", "../../secret.wav")
    with pytest.raises(SystemExit):
        R.convert(film, sid, "", files["perf"])


# ---------------------------------------------------------------- takes beside the spoken ones

def test_the_take_shows_in_the_list_and_is_chosen_without_losing_the_old_one(film, sid, files, installed, tmp_path):
    with_ref(film, files)
    V.attach(film, sid, "Chloe", files["ref"], fit=False)                                   # something is already attached
    r = R.convert(film, sid, "Chloe", files["perf"], performed_by="Dee")
    t = C.takes(film, sid, "Chloe")["takes"]
    assert len(t) == 1 and t[0]["kind"] == "revoice" and t[0]["performed_by"] == "Dee" and t[0]["current"] is False
    res = C.use_take(film, sid, "Chloe", r["take"])
    assert res["take"] == r["take"]
    e = V._meta(film)["shots"][sid][0]
    assert e["source"] == "revoice" and e["synthetic"] is True and "re-voiced" in e["name"]
    assert C.takes(film, sid, "Chloe")["takes"][0]["current"] is True
    removed = os.path.join(film, "voice", "_removed")
    assert os.path.isdir(removed) and os.listdir(removed)                                   # the earlier recording was archived, not deleted


def test_another_persons_take_cannot_be_chosen(film, sid, files, installed):
    with_ref(film, files)
    r = R.convert(film, sid, "Chloe", files["perf"])
    with pytest.raises(SystemExit, match="not one of this line"):
        C.use_take(film, sid, "Lila", r["take"])


# ---------------------------------------------------------------- the command line

def test_the_command_line_answers_with_one_json_line(film, sid, files, installed, capsys):
    assert R.main(["reference", film, "--data", json.dumps({"person": "Chloe", "file": files["ref"], "consent": True, "holder": "me", "scope": "film"})]) == 0
    assert R.main(["convert", film, "--data", json.dumps({"shot": sid, "speaker": "Chloe", "recording": files["perf"]})]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert [x["event"] for x in lines] == ["result", "result"] and lines[1]["data"]["attached"] is False
    assert R.main(["install", film, "--data", "{}"]) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["event"] == "error"
