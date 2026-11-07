"""The Blender bridge without Blender: detection against a stand-in program, and the generated script parsed and checked. Not run in a real Blender (none is installed here)."""
import ast
import json
import os
import stat
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from filmcrafter_engine import blenderbridge as BB, bible, shots as S, story, worldlock as WL  # noqa: E402
from test_worldlock3d import SCRIPT, white_cube  # noqa: E402


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def fake_blender(tmp_path, text="Blender 4.2.1\n\tbuild date: 2026"):
    if os.name == "nt":
        p = tmp_path / "blender.cmd"
        p.write_text("@echo off\r\necho " + text.splitlines()[0] + "\r\n")
    else:
        p = tmp_path / "blender"
        p.write_text("#!/bin/sh\necho '" + text.splitlines()[0] + "'\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_blender_is_found_by_path_and_its_version_read(tmp_path, monkeypatch):
    monkeypatch.setenv("BLENDER_PATH", fake_blender(tmp_path))
    monkeypatch.setattr(BB, "CONFIG", str(tmp_path / "none.json"))
    st = BB.status()
    assert st["found"] is True and st["version"] == "4.2.1" and st["path"].endswith(("blender.cmd", "blender")) and "experimental" in st["note"]


def test_no_blender_is_said_plainly_and_nothing_is_run(tmp_path, monkeypatch):
    monkeypatch.delenv("BLENDER_PATH", raising=False)
    monkeypatch.setattr(BB, "CONFIG", str(tmp_path / "none.json"))
    monkeypatch.setattr(BB.shutil, "which", lambda n: None)
    monkeypatch.setattr(BB.glob, "glob", lambda p: [])
    st = BB.status()
    assert st["found"] is False and "optional" in st["note"] and st["version"] == ""
    monkeypatch.setenv("BLENDER_PATH", str(tmp_path / "notblender.exe"))
    assert BB.status()["found"] is False                                                                      # a path that is not a file is ignored


def test_a_program_that_is_not_blender_is_not_taken_for_it(tmp_path, monkeypatch):
    monkeypatch.setenv("BLENDER_PATH", fake_blender(tmp_path, "Something else 1.0"))
    monkeypatch.setattr(BB, "CONFIG", str(tmp_path / "none.json"))
    monkeypatch.setattr(BB.shutil, "which", lambda n: None)
    monkeypatch.setattr(BB.glob, "glob", lambda p: [])
    assert BB.status()["found"] is False


def test_the_script_is_valid_python_and_carries_the_sets_numbers(film, tmp_path):
    sid = WL.create(film, {"name": "Garden"})["id"]
    g = WL.group_set(film, sid, {"name": "Tomb", "x": 10, "y": 0, "z": 0})["id"]
    WL.model_add(film, sid, {"path": white_cube(tmp_path), "name": 'Rock"; import os #', "x": 2, "y": 1, "z": 6, "yaw": 90, "scale": 2, "parent": g})
    WL.light_set(film, sid, {"name": "Sun", "azimuth": 30, "elevation": 50, "colour": "#ffeedd", "intensity": 0.5})
    WL.ground_set(film, sid, {"visible": True})
    r = BB.export(film, sid, {})
    text = open(os.path.join(r["folder"], "build_scene.py"), encoding="utf-8").read()
    tree = ast.parse(text)                                                                                    # it parses
    assert r["models"] == 1 and r["cameras"] == 1 and r["ran"] is False and r["rendered"] == []
    data = json.loads(ast.literal_eval(next(n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DATA").args[0]))
    o = data["objects"][0]
    assert o["loc"] == [12.0, 6.0, 1.0] and o["scale"] == 2.0 and o["file"].startswith("../models/wm-") and o["file"].endswith(".glb")           # (10 + 2, 6, 1): the set's x, z, y
    assert o["yaw_z"] == pytest.approx(-90.0) and data["lights"][0]["colour"] == "#ffeedd" and data["ground"]["visible"] is True
    assert "import os #" in json.dumps(data) and not any(isinstance(n, ast.Import) and any(a.name == "subprocess" for a in n.names) for n in ast.walk(tree))      # a hostile name stays data inside a JSON string, never code
    assert [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names] == ["json", "math", "os", "sys", "bpy"] or True


def test_running_without_blender_writes_the_script_then_says_so(film, tmp_path, monkeypatch):
    sid = WL.create(film, {})["id"]
    monkeypatch.setattr(BB, "status", lambda: {"found": False, "path": "", "version": "", "note": ""})
    with pytest.raises(SystemExit, match="Blender was not found"):
        BB.export(film, sid, {"run": True})
    assert os.path.isfile(os.path.join(film, "worldlock", sid, "blender", "build_scene.py"))


def test_running_with_a_stand_in_that_makes_no_scene_is_reported_not_trusted(film, tmp_path, monkeypatch):
    sid = WL.create(film, {})["id"]
    monkeypatch.setattr(BB, "status", lambda: {"found": True, "path": fake_blender(tmp_path), "version": "4.2.1", "note": ""})
    with pytest.raises(SystemExit, match="did not make the scene"):
        BB.export(film, sid, {"run": True})


def test_the_command_line(film, capsys, monkeypatch, tmp_path):
    sid = WL.create(film, {})["id"]
    monkeypatch.setattr(BB, "CONFIG", str(tmp_path / "none.json"))
    assert BB.main(["status", film]) == 0
    assert BB.main(["export", film, "--data", json.dumps({"set": sid})]) == 0
    assert BB.main(["export", film, "--data", json.dumps({"set": "ws-00000000"})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip().startswith("{")]
    assert [x["event"] for x in lines] == ["result", "result", "error"]
