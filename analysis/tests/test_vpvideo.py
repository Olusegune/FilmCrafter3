"""Virtual production video, measured on a real encoded video: a subject moving across a noisy green screen is drawn with a known transparency in every frame, encoded to H.264 with the usual
chroma subsampling (so edges are really blurred by the codec), then keyed, smoothed, exported with alpha, composed with keyframes and rendered back to a video. These are synthetic clips made for the
test, not camera footage."""
import json
import os
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(__file__))
from filmcrafter_engine import bible, keying as K, shots as S, story, vpstudio as V, vpvideo as VV  # noqa: E402

SCRIPT = "INT. ROOM - DAY\n\nA small room.\n\nSARAH\nHello there.\n"
W, H, FPS, N = 192, 144, 12, 24
SCREEN = np.array([0.10, 0.72, 0.20], dtype=np.float32)


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def truth_alpha(i):
    m = Image.new("L", (W, H), 0)
    x = 40 + i * 4
    ImageDraw.Draw(m).ellipse((x, 30, x + 50, 120), fill=255)
    return np.asarray(m.filter(ImageFilter.GaussianBlur(1.5)), dtype=np.float32) / 255.0


def frame(i, rng, noise=0.06):
    a = truth_alpha(i)
    subject = np.zeros((H, W, 3), np.float32)
    subject[...] = [0.80, 0.50, 0.40]
    subject[80:] = [0.65, 0.12, 0.16]
    screen = np.broadcast_to(SCREEN * (1.0 - 0.06 * np.linspace(0, 1, W, dtype=np.float32)[None, :, None]), (H, W, 3))
    mixed = K.to_srgb(K.to_linear(subject) * a[..., None] + K.to_linear(screen) * (1 - a[..., None]))
    return np.clip(mixed + rng.normal(0, noise, mixed.shape).astype(np.float32), 0, 1)


def encode(frames_dir, out, crf=14):
    subprocess.run([VV._ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(frames_dir, "%03d.png"), "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p", out],
                   check=True, creationflags=VV.NO_WINDOW)


@pytest.fixture(scope="module")
def clip_mp4(tmp_path_factory):
    base = tmp_path_factory.mktemp("clip")
    fd = base / "frames"
    fd.mkdir()
    rng = np.random.default_rng(3)
    for i in range(N):
        Image.fromarray((frame(i, rng) * 255 + 0.5).astype(np.uint8)).save(fd / f"{i + 1:03d}.png")
    out = str(base / "subject.mp4")
    encode(str(fd), out)
    return out


@pytest.fixture(scope="module")
def street_mp4(tmp_path_factory):
    base = tmp_path_factory.mktemp("street")
    for i in range(N):
        a = np.full((H, W, 3), [0.45, 0.50, 0.55], np.float32)
        a[: H // 2] = [0.40, 0.55, 0.75]
        a[:, int(i * 2) % W: int(i * 2) % W + 6] = 0.9                                                   # a bar sweeping across so the background really moves
        Image.fromarray((a * 255 + 0.5).astype(np.uint8)).save(base / f"{i + 1:03d}.png")
    out = str(base / "street.mp4")
    encode(str(base), out)
    return out


# ---------------------------------------------------------------- what this computer can do, and bringing a clip in

def test_the_video_tool_is_asked_what_it_can_encode():
    c = VV.capabilities()
    assert c["png"] and c["h264"] and c["prores4444"] and c["webm"] and "never offered" in c["note"]


def test_a_clip_is_probed_and_copied_in_once(film, clip_mp4):
    r = VV.import_clip(film, {"path": clip_mp4, "name": "Sarah walks"})
    s = r["sources"][0]
    assert s["clip"] is True and (s["width"], s["height"]) == (W, H) and s["fps"] == FPS and abs(s["seconds"] - N / FPS) < 0.2 and s["frames"] == N and r["already_there"] is False
    assert os.path.getsize(os.path.join(film, s["file"])) == os.path.getsize(clip_mp4)
    assert VV.import_clip(film, {"path": clip_mp4})["already_there"] is True and len(V.get(film)["sources"]) == 1


def test_files_that_are_not_usable_clips_are_refused(film, tmp_path, clip_mp4, monkeypatch):
    junk = tmp_path / "x.mp4"
    junk.write_bytes(b"not a video")
    txt = tmp_path / "a.txt"
    txt.write_text("hi")
    for data, why in (({"path": ""}, "Choose a video"), ({"path": str(txt)}, "MP4, MOV"), ({"path": str(junk)}, "no video|could not read")):
        with pytest.raises(SystemExit, match=why):
            VV.import_clip(film, data)
    monkeypatch.setattr(VV, "MAX_SECONDS", 0.5)
    with pytest.raises(SystemExit, match="clips up to"):
        VV.import_clip(film, {"path": clip_mp4})


# ---------------------------------------------------------------- keying a clip

def key(film, clip_mp4, **extra):
    sid = VV.import_clip(film, {"path": clip_mp4})["id"]
    return sid, VV.key_clip(film, {"source": sid, "name": "Sarah", **extra})


def alpha_frame(film, c, i):
    return np.asarray(Image.open(os.path.join(film, os.path.dirname(c["seq"]), f"{i:05d}.png")).convert("RGBA"))[..., 3].astype(np.float32) / 255.0


def test_every_frame_is_keyed_to_a_real_rgba_png_close_to_the_truth_even_after_h264(film, clip_mp4):
    sid, r = key(film, clip_mp4, params={"similarity": 0.07}, temporal=0.0)
    c = r["cutouts"][0]
    assert c["kind"] == "clip" and c["frames"] == N and c["fps"] == FPS and (c["width"], c["height"]) == (W, H) and c["source"] == sid
    errs, solid, back = [], [], []
    for i in (1, 6, 12, 18, 24):
        a = alpha_frame(film, c, i)
        t = truth_alpha(i - 1)
        errs.append(float(np.abs(a - t).mean()))
        solid.append(float((a[t > 0.99] > 0.9).mean()))
        back.append(float((a[t < 0.01] < 0.1).mean()))
    assert max(errs) < 0.02 and min(solid) > 0.93 and min(back) > 0.97
    assert Image.open(os.path.join(film, c["rgba"])).mode == "RGBA" and Image.open(os.path.join(film, c["mask"])).mode == "L"
    n_masks = len([f for f in os.listdir(os.path.join(film, os.path.dirname(os.path.dirname(c["seq"])), "masks")) if f.endswith(".png")])
    assert n_masks == N


def test_one_set_of_settings_is_used_for_the_whole_clip(film, clip_mp4):
    _, r = key(film, clip_mp4, temporal=0.0)
    p = r["cutouts"][0]["params"]
    assert p["color"] is not None and len(p["color"]) == 3 and p["softness"] is not None and 0.02 < p["softness"] < 0.6                   # worked out once, then fixed
    assert abs(p["color"][1] - SCREEN[1]) < 0.12 and p["color"][1] > p["color"][0] and p["color"][1] > p["color"][2]
    given = VV.key_clip(film, {"source": r["cutouts"][0]["source"], "params": {"color": [0.0, 0.8, 0.0], "softness": 0.2}, "temporal": 0})["cutouts"][-1]["params"]
    assert given["color"] == [0.0, 0.8, 0.0] and given["softness"] == 0.2                                                                # what the person set is kept


def test_temporal_smoothing_reduces_flicker_without_smearing_the_motion(film, clip_mp4):
    sid = VV.import_clip(film, {"path": clip_mp4})["id"]
    tight = {"similarity": 0.02}                                                                                                              # a tight key on a noisy screen: the edge of the screen flickers
    raw = VV.key_clip(film, {"source": sid, "temporal": 0.0, "params": tight})["report"]
    smooth_r = VV.key_clip(film, {"source": sid, "temporal": 0.5, "params": tight})
    smooth = smooth_r["report"]
    assert raw["flicker_before"] > 0.01 and raw["flicker_after"] == raw["flicker_before"]
    assert smooth["flicker_after"] < smooth["flicker_before"] * 0.6                                                                          # clearly calmer
    c = smooth_r["cutouts"][-1]
    for i in (8, 16):                                                                                                                         # the moving subject is still where it was
        a, t = alpha_frame(film, c, i), truth_alpha(i - 1)
        mass = a * (t > 0.01)                                                                                                                  # measured on the subject, ignoring leftover specks on the screen
        cm = (mass * np.arange(W)[None, :]).sum() / mass.sum()
        tm = (t * np.arange(W)[None, :]).sum() / t.sum()
        assert abs(cm - tm) < 1.0 and float(np.abs(a - t)[t > 0.99].mean()) < 0.05


def test_a_picture_is_not_a_clip_and_a_clip_needs_the_clip_action(film, clip_mp4, tmp_path):
    img = tmp_path / "p.png"
    Image.fromarray(np.zeros((20, 20, 3), np.uint8)).save(img)
    pid = V.import_source(film, {"path": str(img)})["id"]
    with pytest.raises(SystemExit, match="is a picture, not a clip"):
        VV.key_clip(film, {"source": pid})
    with pytest.raises(SystemExit, match="virtual production folder"):
        VV.key_clip(film, {"source": "vs-00000000"})


def test_too_many_frames_are_refused_before_any_work(film, clip_mp4, monkeypatch):
    sid = VV.import_clip(film, {"path": clip_mp4})["id"]
    monkeypatch.setattr(VV, "MAX_FRAMES", 10)
    with pytest.raises(SystemExit, match="keys at most 10"):
        VV.key_clip(film, {"source": sid})
    assert V.get(film)["cutouts"] == [] and not os.path.isdir(os.path.join(film, "vp", "cutouts"))


def test_a_cancel_request_stops_at_the_next_frame_and_leaves_no_half_made_cutout(film, clip_mp4, monkeypatch):
    sid = VV.import_clip(film, {"path": clip_mp4})["id"]
    real = K.key
    seen = {"n": 0}

    def key_and_cancel(rgb, p=None):
        seen["n"] += 1
        if seen["n"] == 3:
            VV.cancel(film)
        return real(rgb, p)
    monkeypatch.setattr(K, "key", key_and_cancel)
    with pytest.raises(SystemExit, match="Stopped at frame 3 of 24"):
        VV.key_clip(film, {"source": sid, "temporal": 0})
    assert V.get(film)["cutouts"] == []
    assert not any(os.scandir(os.path.join(film, "vp", "cutouts"))) if os.path.isdir(os.path.join(film, "vp", "cutouts")) else True
    assert not os.path.exists(os.path.join(film, "vp", "cancel.flag"))
    monkeypatch.setattr(K, "key", real)
    assert len(VV.key_clip(film, {"source": sid, "temporal": 0})["cutouts"]) == 1                                                             # and the next job runs normally


# ---------------------------------------------------------------- alpha export, read back

@pytest.fixture
def keyed(film, clip_mp4):
    sid, r = key(film, clip_mp4, params={"similarity": 0.07}, temporal=0.3)
    return film, r["cutouts"][0]


def test_a_png_sequence_is_exported_with_alpha(keyed):
    film, c = keyed
    r = VV.export_clip(film, {"id": c["id"], "format": "png"})
    files = sorted(os.listdir(r["path"]))
    assert len(files) == N and files[0] == "frame_00001.png" and r["has_alpha"] is True and r["alpha_error"] < 0.001 and r["fps"] == FPS
    assert Image.open(os.path.join(r["path"], files[0])).mode == "RGBA"


@pytest.mark.parametrize("fmt,ext", [("prores4444", ".mov"), ("webm", ".webm")])
def test_alpha_video_is_encoded_decoded_back_and_its_transparency_matches_the_mask(keyed, fmt, ext):
    film, c = keyed
    r = VV.export_clip(film, {"id": c["id"], "format": fmt})
    assert r["path"].endswith(ext) and os.path.getsize(r["path"]) > 1000
    assert r["has_alpha"] is True and r["alpha_error"] is not None and r["alpha_error"] < 0.04
    assert "transparency survived" in r["note"]


def test_an_unknown_format_is_a_png_sequence_and_a_still_cutout_is_refused(film, keyed, tmp_path):
    f, c = keyed
    assert VV.export_clip(f, {"id": c["id"], "format": "mp4"})["format"] == "png"                                                              # transparent H.264 is never made
    img = tmp_path / "p.png"
    Image.fromarray(np.zeros((20, 20, 3), np.uint8)).save(img)
    plate, _, _ = (None, None, None)
    with pytest.raises(SystemExit, match="isn't in the film"):
        VV.export_clip(f, {"id": "cu-00000000"})


# ---------------------------------------------------------------- keyframes

def test_keyframes_are_cleaned_and_interpolated():
    k = K.clean_keys([{"t": 2, "x": 1.0, "ease": "smooth"}, {"t": 0, "x": 0.0, "opacity": 0.5}, {"t": "x"}, {"t": 1}, {"t": 5, "scale": 99, "rotation": 1e9}, "junk", {"t": -1, "x": 1}, {"t": 2, "y": 0.2, "x": 0.9}])
    assert [x["t"] for x in k] == [0.0, 2.0, 5.0] and k[1]["x"] == 0.9 and k[2]["scale"] == 8.0 and k[2]["rotation"] == 360.0                      # sorted, limited, the later of two at one time wins
    assert K.interp(k, 1.0, "x") == pytest.approx(0.45) and K.interp(k, -3, "x") == 0.0 and K.interp(k, 9, "x") == 0.9 and K.interp(k, 1, "y") == 0.2 and K.interp(k, 1, "rotation") == 360.0
    assert K.interp([{"t": 0, "x": 0, "ease": "hold"}, {"t": 2, "x": 1}], 1.99, "x") == 0.0 and K.interp([{"t": 0, "x": 0, "ease": "smooth"}, {"t": 2, "x": 1}], 0.5, "x") < 0.25
    assert K.interp([], 1, "x") is None and len(K.clean_keys([{"t": i, "x": 0.5} for i in range(200)])) == K.MAX_KEYS


def test_a_layer_follows_its_keyframes_over_its_own_settings():
    base = {"x": 0.2, "y": 0.9, "scale": 0.5, "rotation": 10, "opacity": 1.0, "keys": [{"t": 0, "x": 0.2}, {"t": 2, "x": 0.8}]}
    st = VV.layer_state(base, 1.0)
    assert st["x"] == pytest.approx(0.5) and st["y"] == 0.9 and st["scale"] == 0.5 and st["rotation"] == 10


# ---------------------------------------------------------------- composing in motion

def compose(film, keyed_cut, street_mp4=None, bg_still=None, **layer):
    bg = None
    if street_mp4:
        bg = VV.import_clip(film, {"path": street_mp4, "kind": "background", "name": "Street"})["id"]
    base_layer = {"cutout": keyed_cut["id"], "x": 0.3, "y": 1.0, "scale": 0.8, "anchor": "bottom", "shadow": None, "keys": [{"t": 0, "x": 0.2}, {"t": 1.0, "x": 0.8}], **layer}
    return VV.V.compose_set(film, {"name": "Walk", "background": bg, "size": [W, H], "layers": [base_layer]})["id"]


def test_a_composition_keeps_keyframes_start_and_loop(keyed, street_mp4):
    film, c = keyed
    cp = compose(film, c, street_mp4, start=0.5, loop=True)
    layer = next(x for x in V.get(film)["compositions"] if x["id"] == cp)["layers"][0]
    assert layer["start"] == 0.5 and layer["loop"] is True and [k["t"] for k in layer["keys"]] == [0.0, 1.0] and layer["keys"][1]["x"] == 0.8
    again = V.compose_set(film, {"id": cp, "layers": [{**layer, "keys": [{"t": 3, "x": 9}], "start": -4}]})["compositions"][0]["layers"][0]
    assert again["keys"] == [{"t": 3.0, "ease": "linear", "x": 3.0}] and again["start"] == 0.0


def test_a_single_frame_of_a_moving_composition_is_drawn_at_the_time_asked(keyed, street_mp4):
    film, c = keyed
    cp = compose(film, c, street_mp4)

    def subject_centre(t):
        out = V.render(film, cp, t)
        img = np.asarray(Image.open(os.path.join(film, out["file"])).convert("RGB"), dtype=np.float32) / 255.0
        warm = (img[..., 0] > img[..., 2] + 0.15) & (img[..., 0] > 0.5)
        ys, xs = np.nonzero(warm)
        return xs.mean() if len(xs) else None
    early, late = subject_centre(0.0), subject_centre(0.9)
    assert early is not None and late is not None and late > early + 40                                                                         # the keyframes moved it across


def test_a_video_is_rendered_over_a_moving_background_with_the_subject_moving(keyed, street_mp4):
    film, c = keyed
    cp = compose(film, c, street_mp4)
    r = VV.render_video(film, {"id": cp, "fps": 12, "seconds": 1.5})
    full = os.path.join(film, r["file"])
    info = VV.probe(full)
    assert r["frames"] == 18 and (info["width"], info["height"]) == (W, H) and abs(info["seconds"] - 1.5) < 0.2 and info["fps"] == 12.0 and r["format"] == "mp4"
    out = os.path.join(os.path.dirname(full), "check")
    os.makedirs(out)
    subprocess.run([VV._ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", full, os.path.join(out, "%03d.png")], check=True, creationflags=VV.NO_WINDOW)
    first = np.asarray(Image.open(os.path.join(out, "001.png")).convert("RGB"), dtype=np.float32) / 255.0
    last = np.asarray(Image.open(os.path.join(out, "018.png")).convert("RGB"), dtype=np.float32) / 255.0
    assert float(np.abs(first - last).mean()) > 0.01                                                                                            # it moves
    sky = first[5, 5]
    assert abs(sky[2] - 0.75) < 0.12 and sky[1] > sky[0] - 0.05                                                                                  # the street's sky, not the green screen
    assert V.get(film)["compositions"][0]["last_video"] == r["file"]


def test_a_png_sequence_render_and_the_limits(keyed):
    film, c = keyed
    cp = compose(film, c)
    r = VV.render_video(film, {"id": cp, "fps": 6, "seconds": 1, "format": "png"})
    folder = os.path.join(film, r["file"])
    assert len(os.listdir(folder)) == 6 and r["format"] == "png"
    with pytest.raises(SystemExit, match="renders at most"):
        VV.render_video(film, {"id": cp, "fps": 30, "seconds": 30})
    with pytest.raises(SystemExit, match="isn't in the film"):
        VV.render_video(film, {"id": "cp-00000000"})


def test_a_cancelled_render_leaves_no_half_made_file(keyed, monkeypatch):
    film, c = keyed
    cp = compose(film, c)
    real = VV.compose_at
    seen = {"n": 0}

    def slow(*a, **k):
        seen["n"] += 1
        if seen["n"] == 4:
            VV.cancel(film)
        return real(*a, **k)
    monkeypatch.setattr(VV, "compose_at", slow)
    with pytest.raises(SystemExit, match="Stopped at frame 4"):
        VV.render_video(film, {"id": cp, "fps": 12, "seconds": 2})
    assert not [f for f in os.listdir(os.path.join(film, "vp", "renders")) if f.startswith(cp)] if os.path.isdir(os.path.join(film, "vp", "renders")) else True
    assert not os.path.exists(os.path.join(film, "vp", "cancel.flag"))


def test_the_command_line_answers_with_json(film, clip_mp4, capsys):
    assert VV.main(["capabilities", film]) == 0
    assert VV.main(["import_clip", film, "--data", json.dumps({"path": clip_mp4})]) == 0
    assert VV.main(["cancel", film]) == 0
    assert VV.main(["key_clip", film, "--data", json.dumps({"source": "vs-00000000"})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip().startswith("{")]
    assert [x["event"] for x in lines] == ["result", "result", "result", "error"] and lines[0]["data"]["png"] is True
