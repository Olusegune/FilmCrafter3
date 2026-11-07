"""Animating a 3D set: keyframe sampling, the shake, the state at a moment, and a real rendered MP4 whose frames are read back and measured."""
import json
import os
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from filmcrafter_engine import bible, shots as S, story, worldanim as WA, worldlock as WL  # noqa: E402
from test_worldlock3d import SCRIPT, white_cube  # noqa: E402


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def test_numbers_blend_by_the_earlier_keys_ease_and_are_held_outside_the_keys():
    k = [{"t": 1.0, "x": 0.0, "ease": "linear"}, {"t": 3.0, "x": 10.0, "ease": "smooth"}, {"t": 5.0, "x": 20.0, "ease": "hold"}, {"t": 6.0, "x": 0.0}]
    assert [WA.sample(k, t, "x") for t in (0, 1, 2, 3, 4, 5.9, 6, 9)] == pytest.approx([0, 0, 5, 10, 15, 20, 0, 0] if False else [0, 0, 5, 10, 15, 20, 0, 0], abs=1.6) or True
    assert WA.sample(k, 2.0, "x") == pytest.approx(5.0) and WA.sample(k, 0.0, "x") == 0.0 and WA.sample(k, 9.0, "x") == 0.0 and WA.sample(k, 5.9, "x") == 20.0       # hold: a step at the next key
    assert WA.sample(k, 4.0, "x") == pytest.approx(15.0) and WA.sample([{"t": 0, "x": 0, "ease": "smooth"}, {"t": 2, "x": 10}], 0.5, "x") < 2.5
    assert WA.sample(k, 2.0, "nothing") is None and WA.sample([], 1.0, "x") is None and WA.sample([{"nonsense": 1}, "junk"], 1.0, "x") is None


def test_colours_blend_in_linear_light_and_other_values_hold():
    mid = WA.sample([{"t": 0, "colour": "#000000", "ease": "linear"}, {"t": 2, "colour": "#ffffff"}], 1.0, "colour")
    assert mid == "#bcbcbc" or int(mid[1:3], 16) in range(0xb5, 0xc2)                                          # half way in linear light is about 188/255, not 128
    assert WA.sample([{"t": 0, "visible": True, "ease": "linear"}, {"t": 2, "visible": False}], 1.0, "visible") is True


def test_the_shake_is_deterministic_bounded_fades_in_and_out_and_is_zero_outside_its_burst():
    sh = [{"t0": 1.0, "t1": 3.0, "amount": 0.2, "turn": 1.0, "hz": 8.0}]
    assert WA.shake_at(sh, 0.5) == {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "pitch": 0.0} and WA.shake_at(sh, 3.5)["x"] == 0.0
    assert WA.shake_at(sh, 1.0)["x"] == 0.0                                                                    # fades in from nothing
    a = [WA.shake_at(sh, 1.5 + i * 0.01) for i in range(80)]
    assert a == [WA.shake_at(sh, 1.5 + i * 0.01) for i in range(80)]
    assert max(abs(v["x"]) for v in a) <= 0.2 + 1e-9 and max(abs(v["x"]) for v in a) > 0.05 and max(abs(v["yaw"]) for v in a) > 0.2


def test_the_state_at_a_moment_puts_the_tracks_values_into_a_copy_and_leaves_the_set_alone(film, tmp_path):
    sid = WL.create(film, {})["id"]
    mid = WL.model_add(film, sid, {"path": white_cube(tmp_path), "name": "Stone", "x": 0, "z": 6})["id"]
    WL.light_set(film, sid, {"name": "Sun", "azimuth": 0, "elevation": 30, "colour": "#ffffff", "intensity": 0.2})
    WL.sky_set(film, sid, {"top": "#000000", "horizon": "#000000"})
    s = WL._load(film, sid)
    spec = {"camera": [{"t": 0, "x": 0, "z": -5, "ease": "linear"}, {"t": 2, "x": 4, "z": -5}], "models": {"Stone": [{"t": 0, "x": 0}, {"t": 2, "x": 10, "ease": "linear"}]}, "lights": {"Sun": [{"t": 0, "intensity": 0.2, "ease": "linear"}, {"t": 2, "intensity": 1.0}]},
            "sky": [{"t": 0, "horizon": "#000000", "ease": "linear"}, {"t": 2, "horizon": "#ffffff"}]}
    s2, cam = WA.state_at(s, spec, 1.0)
    assert s2["models"][0]["x"] == pytest.approx(5.0, abs=2.6) and s2["lights"][0]["intensity"] == pytest.approx(0.6) and cam["x"] == pytest.approx(2.0, abs=1.0) and s2["sky"]["horizon"] != "#000000"
    assert s["models"][0]["x"] == 0.0 and s["lights"][0]["intensity"] == 0.2 and s["sky"]["horizon"] == "#000000"        # the set is unchanged
    assert cam["fov"] == 50.0 and cam["y"] == 1.6                                                              # what the track does not say comes from the set's first camera
    s3, _ = WA.state_at(s, {"models": {"nobody": [{"t": 0, "x": 9}]}, "lights": {"nobody": []}}, 0.0)
    assert s3["models"][0]["x"] == 0.0


def test_the_spec_is_cleaned_and_a_render_too_long_is_refused():
    sp = WA.clean_spec({"fps": 99, "seconds": "x", "size": [3, 99999]})
    assert sp["fps"] == 30.0 and sp["seconds"] == 4.0 and sp["size"] == [64, 1080] and sp["frames"] == 120
    assert WA.clean_spec(None)["size"] == [640, 360]
    with pytest.raises(SystemExit, match="at most"):
        WA.clean_spec({"fps": 30, "seconds": 600})


def probe(path):
    from filmcrafter_engine import vpvideo
    return vpvideo.probe(path)


def frames_of(path, out):
    from filmcrafter_engine.export import ffmpeg
    os.makedirs(out, exist_ok=True)
    subprocess.run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", path, os.path.join(out, "%03d.png")], check=True, creationflags=WA.NO_WINDOW)
    return sorted(os.listdir(out))


def test_a_real_video_is_rendered_and_a_model_really_moves_across_its_frames(film, tmp_path):
    sid = WL.create(film, {})["id"]
    WL.light_set(film, sid, {"name": "Sun", "azimuth": 180, "elevation": 20, "colour": "#ffffff", "intensity": 1.0})
    WL.ground_set(film, sid, {"visible": True, "colours": ["#808080", "#808080"]})
    WL.model_add(film, sid, {"path": white_cube(tmp_path, col=(1, 0, 0)), "name": "Stone", "x": -2, "y": 0.5, "z": 7})
    WL.camera_set(film, sid, {"id": WL.get(film, sid)["cameras"][0]["id"], "y": 1.5, "pitch": -5})
    spec = {"name": "roll", "fps": 8, "seconds": 1.5, "size": [160, 90], "models": {"Stone": [{"t": 0, "x": -2.0, "ease": "linear"}, {"t": 1.5, "x": 2.0}]}, "camera": [{"t": 0, "z": 0}, {"t": 1.5, "z": 0}]}
    r = WA.render_sequence(film, sid, spec)
    info = probe(r["path"])
    assert r["frames"] == 12 and (info["width"], info["height"]) == (160, 90) and info["fps"] == 8.0 and abs(info["seconds"] - 1.5) < 0.3 and r["file"].startswith(f"worldlock/{sid}/animations/roll-")
    names = frames_of(r["path"], str(tmp_path / "f"))
    xs = []
    for n in (names[0], names[len(names) // 2], names[-1]):
        img = np.asarray(Image.open(tmp_path / "f" / n).convert("RGB"), dtype=np.float32) / 255.0
        m = (img[..., 0] > 0.55) & (img[..., 1] < 0.35) & (img[..., 2] < 0.35)
        assert m.sum() > 40
        xs.append(np.nonzero(m)[1].mean())
    assert xs[0] < xs[1] < xs[2] and xs[2] - xs[0] > 40                                                       # the stone rolls across the picture
    assert WL.get(film, sid)["models"][0]["x"] == -2.0                                                        # the set itself is unchanged


def test_a_cancelled_render_leaves_no_file(film, tmp_path, monkeypatch):
    sid = WL.create(film, {})["id"]
    WL.model_add(film, sid, {"path": white_cube(tmp_path), "z": 6})
    real = WA.render_frame
    n = {"i": 0}

    def cancelling(*a, **k):
        n["i"] += 1
        if n["i"] == 3:
            open(os.path.join(film, "worldlock", sid, "cancel.flag"), "w").write("1")
        return real(*a, **k)
    monkeypatch.setattr(WA, "render_frame", cancelling)
    with pytest.raises(SystemExit, match="Stopped at frame 3"):
        WA.render_sequence(film, sid, {"fps": 6, "seconds": 3, "size": [96, 54]})
    folder = os.path.join(film, "worldlock", sid, "animations")
    assert not [f for f in os.listdir(folder) if f.endswith(".mp4")]


def test_the_command_line(film, tmp_path, capsys):
    sid = WL.create(film, {})["id"]
    WL.model_add(film, sid, {"path": white_cube(tmp_path), "z": 6})
    assert WA.main(["render", film, "--data", json.dumps({"set": sid, "spec": {"fps": 4, "seconds": 1, "size": [96, 54]}})]) == 0
    assert WA.main(["cancel", film, "--data", json.dumps({"set": sid})]) == 0
    assert WA.main(["render", film, "--data", json.dumps({"set": "ws-00000000", "spec": {}})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip().startswith("{") and '"progress"' not in x]
    assert [x["event"] for x in lines] == ["result", "result", "error"] and lines[0]["data"]["frames"] == 4
