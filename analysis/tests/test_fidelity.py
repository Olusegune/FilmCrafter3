"""Picture fidelity: the measurements follow known degradations, depth of field is not called soft, the original is never touched, and apply/revert are exact."""
import hashlib
import json
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from filmcrafter_engine import fidelity as F


def synth(w=1024, h=683, seed=1):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.float32)
    img[..., 0] = 0.3 + 0.2 * np.sin(xx / 90) + 0.1 * np.sin(yy / 50)
    img[..., 1] = 0.4 + 0.2 * np.cos(xx / 70)
    img[..., 2] = 0.5 + 0.1 * np.sin((xx + yy) / 60)
    for _ in range(50):
        x, y, r = rng.integers(0, w), rng.integers(0, h), rng.integers(15, 70)
        img[(xx - x) ** 2 + (yy - y) ** 2 < r * r] = rng.random(3)
    tex = rng.normal(0, 0.03, (h // 2, w // 2)).astype(np.float32)           # fine surface texture, so there is something to keep sharp
    img += np.asarray(Image.fromarray(tex).resize((w, h), Image.BICUBIC))[..., None]
    return Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))


def save(im, tmp_path, name, **kw):
    p = str(tmp_path / name)
    im.save(p, **kw)
    return p


def row(rep, id):
    return next(r for r in rep["rows"] if r["id"] == id)


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_sharpness_follows_blur_and_never_calls_a_sharp_picture_soft(tmp_path):
    base = synth()
    levels = [row(F.analyze(save(base.filter(ImageFilter.GaussianBlur(s)) if s else base, tmp_path, f"b{s}.png")), "sharpness") for s in (0, 1.5, 4)]
    vals = [r["value"] for r in levels]
    assert vals[0] > vals[1] > vals[2]
    assert levels[0]["level"] == "Good" and levels[2]["level"] == "Soft"


def test_shallow_depth_of_field_is_noted_not_blamed(tmp_path):
    base = synth()
    soft = base.filter(ImageFilter.GaussianBlur(6))
    mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(mask).ellipse((250, 150, 700, 520), fill=255)
    rep = F.analyze(save(Image.composite(base, soft, mask.filter(ImageFilter.GaussianBlur(40))), tmp_path, "dof.png"))
    s = row(rep, "sharpness")
    assert s["level"] == "Good" and s["depth_of_field"] and rep["verdict"] == "ok"


def test_noise_and_jpeg_blocks_are_found_and_levels_are_ordered(tmp_path):
    base = synth()
    rng = np.random.default_rng(3)
    noisy = Image.fromarray(np.clip(np.asarray(base, np.float32) + rng.normal(0, 12, (base.height, base.width, 3)), 0, 255).astype(np.uint8))
    assert row(F.analyze(save(base, tmp_path, "c.png")), "noise")["level"] == "Low"
    assert row(F.analyze(save(noisy, tmp_path, "n.png")), "noise")["level"] in ("Moderate", "High")
    assert F.analyze(save(noisy, tmp_path, "n2.png"))["verdict"] != "ok"
    q = [row(F.analyze(save(base, tmp_path, f"q{k}.jpg", quality=k)), "blocking")["value"] for k in (95, 30, 10)]
    assert q[0] < q[1] < q[2]
    assert row(F.analyze(save(base, tmp_path, "q10.jpg", quality=10)), "blocking")["level"] == "High"


def test_a_plain_or_tiny_picture_says_unknown_rather_than_inventing_a_score(tmp_path):
    rep = F.analyze(save(Image.new("RGB", (400, 300), (120, 120, 120)), tmp_path, "flat.png"))
    assert row(rep, "sharpness")["level"] == "Unknown" and row(rep, "sharpness")["confidence"] == "low"
    assert row(rep, "blocking")["level"] == "Unknown"
    assert rep["not_assessed"] and rep["low_resolution"]


def test_clipping_is_a_measurement_that_admits_it_may_be_intended(tmp_path):
    im = Image.new("RGB", (800, 600), (255, 255, 255))
    ImageDraw.Draw(im).rectangle((100, 100, 400, 400), fill=(90, 120, 160))
    c = row(F.analyze(save(im, tmp_path, "w.png")), "clipping")
    assert c["level"] == "High" and "may be intended" in c["note"]


def test_aspect_names():
    assert F.aspect_name(1920, 1080) == "16:9" and F.aspect_name(1536, 1024) == "3:2" and F.aspect_name(2520, 1080) == "21:9" and F.aspect_name(2390, 1000) == "2.39:1" and F.aspect_name(1000, 700) == "1000:700"


def test_clean_enhance_reduces_noise_without_blowing_out_and_keeps_size_and_alpha():
    base = synth(640, 480)
    rng = np.random.default_rng(5)
    ref = np.asarray(base, np.float32)
    noisy = Image.fromarray(np.clip(ref + rng.normal(0, 10, ref.shape), 0, 255).astype(np.uint8))
    out = F.enhance_image(noisy, 0.5)
    assert out.size == noisy.size

    def mse(a):
        return float(np.mean((ref - np.asarray(a, np.float32)) ** 2))
    assert mse(out) < mse(noisy)                                                    # closer to the clean reference
    assert (np.asarray(out.convert("L")) >= 250).mean() <= (np.asarray(noisy.convert("L")) >= 250).mean() + 0.002
    rgba = noisy.convert("RGBA")
    rgba.putalpha(Image.new("L", noisy.size, 128))
    assert F.enhance_image(rgba, 0.5).getchannel("A").getextrema() == (128, 128)


def test_deblock_lowers_the_block_measure(tmp_path):
    base = synth()
    p = save(base, tmp_path, "j.jpg", quality=25)
    out = F.enhance_image(Image.open(p).convert("RGB"), 0.5)
    after = row(F.analyze(save(out, tmp_path, "j2.png")), "blocking")["value"]
    assert after < row(F.analyze(p), "blocking")["value"] - 0.1


def film(tmp_path):
    d = tmp_path / "film"
    (d / "keyframes").mkdir(parents=True)
    synth(800, 533).filter(ImageFilter.GaussianBlur(2)).save(d / "keyframes" / "S01.png")
    (d / "directed.json").write_text(json.dumps({"scenes": [{"shots": [{"id": "S01"}]}]}))
    (d / "keyframes.json").write_text(json.dumps({"directed": {"S01": "project:keyframes/S01.png"}}))
    return str(d)


def kf(d):
    with open(os.path.join(d, "keyframes.json")) as f:
        return json.load(f)["directed"]["S01"]


def test_enhance_never_touches_the_original_and_apply_revert_are_exact(tmp_path):
    d = film(tmp_path)
    orig = os.path.join(d, "keyframes", "S01.png")
    before = sha(orig)
    it = F.enhance(d, "S01", 0.5)
    assert sha(orig) == before and os.path.isfile(it["output_path"]) and it["output"].startswith("project:fidelity/")
    assert kf(d) == "project:keyframes/S01.png"                                      # nothing switched yet
    F.apply(d, it["id"])
    assert kf(d) == it["output"]
    F.revert(d, "S01")
    assert kf(d) == "project:keyframes/S01.png"
    assert sha(orig) == before
    assert [x["state"] for x in F.status(d)["items"]] == ["reverted"]


def test_apply_refuses_when_the_keyframe_changed_since(tmp_path):
    d = film(tmp_path)
    it = F.enhance(d, "S01")
    with open(os.path.join(d, "keyframes.json"), "w") as f:
        json.dump({"directed": {"S01": "project:keyframes/other.png"}}, f)
    with pytest.raises(SystemExit):
        F.apply(d, it["id"])


def test_paths_outside_the_project_are_refused(tmp_path):
    d = film(tmp_path)
    with open(os.path.join(d, "keyframes.json"), "w") as f:
        json.dump({"directed": {"S01": "project:../../secret.png"}}, f)
    with pytest.raises(SystemExit):
        F.check(d, "S01")


def test_no_keyframe_and_unreadable_picture_give_plain_messages(tmp_path):
    d = film(tmp_path)
    with pytest.raises(SystemExit):
        F.check(d, "S99")
    with open(os.path.join(d, "keyframes", "S01.png"), "wb") as f:
        f.write(b"not a picture")
    with pytest.raises(SystemExit):
        F.check(d, "S01")


# ---- local super-resolution: the program is faked (no model is installed here), so these test our side: arguments, safety, files, ledger ----

class FakeRun:
    def __init__(self, fail=False, rc=0):
        self.calls, self.fail, self.rc = [], fail, rc

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if not self.fail:
            src, out, s = cmd[cmd.index("-i") + 1], cmd[cmd.index("-o") + 1], int(cmd[cmd.index("-s") + 1])
            im = Image.open(src).convert("RGB")
            im.resize((im.width * s, im.height * s), Image.LANCZOS).save(out, format="PNG")

        class P:
            returncode = self.rc
            stdout = stderr = ""
        return P()


@pytest.fixture
def tool(tmp_path, monkeypatch):
    t = tmp_path / "tool"
    (t / "models").mkdir(parents=True)
    exe = t / "realesrgan-ncnn-vulkan.exe"
    exe.write_bytes(b"x")
    for m in ("realesrgan-x4plus", "realesr-animevideov3"):
        (t / "models" / (m + ".param")).write_bytes(b"x")
    monkeypatch.setenv("FILMCRAFTER_REALESRGAN", str(exe))
    fake = FakeRun()
    monkeypatch.setattr(F.subprocess, "run", fake)
    return fake


def test_upscale_says_how_to_install_when_the_tool_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("FILMCRAFTER_REALESRGAN", str(tmp_path / "nope.exe"))
    monkeypatch.setattr(F.shutil, "which", lambda n: None)
    monkeypatch.setattr(F, "local_tool", lambda: None)
    assert F.upscale_status()["available"] is False and "Nothing is downloaded" in F.upscale_status()["help"]
    with pytest.raises(SystemExit, match="Nothing is downloaded"):
        F.upscale(film(tmp_path), "S01")


def test_upscale_runs_tiled_without_a_shell_keeps_the_original_and_applies_and_reverts(tmp_path, tool):
    d = film(tmp_path)
    orig = os.path.join(d, "keyframes", "S01.png")
    before = sha(orig)
    assert F.upscale_status()["available"] and "realesrgan-x4plus" in F.upscale_status()["models"]
    it = F.upscale(d, "S01", 2)
    cmd, kw = tool.calls[0]
    assert isinstance(cmd, list) and cmd[cmd.index("-t") + 1] == str(F.TILE_SIZE) and cmd[cmd.index("-n") + 1] == "realesrgan-x4plus" and not kw.get("shell")
    assert cmd[cmd.index("-s") + 1] == "4"        # a 4x model is always run at 4x (the tool garbles other factors); the result is resized here to the 2x asked for
    assert it["size"] == [1600, 1066] and it["method"] == "local_upscale" and "invents plausible detail" in it["note"]
    assert sha(orig) == before and kf(d) == "project:keyframes/S01.png"
    assert not [f for f in os.listdir(os.path.join(d, "fidelity")) if f.endswith(".tmp.png")]
    F.apply(d, it["id"])
    assert kf(d) == it["output"]
    F.revert(d, "S01")
    assert kf(d) == "project:keyframes/S01.png" and sha(orig) == before


def test_upscale_refuses_bad_scale_unknown_model_and_giant_output(tmp_path, tool):
    d = film(tmp_path)
    with pytest.raises(SystemExit):
        F.upscale(d, "S01", 8)
    with pytest.raises(SystemExit, match="not installed"):
        F.upscale(d, "S01", 2, model="../../evil")
    assert F.upscale(d, "S01", 2, anime=True)["model"] == "realesr-animevideov3"
    Image.new("RGB", (4500, 100), (9, 9, 9)).save(os.path.join(d, "keyframes", "S01.png"))
    with pytest.raises(SystemExit, match="larger than"):
        F.upscale(d, "S01", 2)
    assert len(tool.calls) == 1                                                      # the refused ones never started the program


def test_upscale_failure_changes_nothing(tmp_path, tool):
    d = film(tmp_path)
    tool.fail = True
    with pytest.raises(SystemExit, match="did not finish"):
        F.upscale(d, "S01", 2)
    assert not os.path.isdir(os.path.join(d, "fidelity")) or not [f for f in os.listdir(os.path.join(d, "fidelity")) if f.endswith(".png")]
    assert F.status(d)["items"] == []


# ---- animation master: a separate picture for the video model; the keyframe is untouched ----

def test_master_is_given_to_the_video_model_while_the_keyframe_stays(tmp_path, tool):
    from filmcrafter_engine import render as R
    d = film(tmp_path)
    assert R.approved_keyframe(d, "directed", "S01") == "project:keyframes/S01.png"
    it = F.upscale(d, "S01", 2)
    F.master_set(d, it["id"])
    assert kf(d) == "project:keyframes/S01.png"                                      # the keyframe is still what was approved
    assert R.approved_keyframe(d, "directed", "S01") == it["output"]                  # the video model gets the master
    F.master_clear(d, "S01")
    assert R.approved_keyframe(d, "directed", "S01") == "project:keyframes/S01.png" and F.masters(d) == {"masters": {}}


def test_a_master_is_ignored_once_the_keyframe_changes_or_the_file_is_outside_the_project(tmp_path, tool):
    from filmcrafter_engine import render as R
    d = film(tmp_path)
    it = F.upscale(d, "S01", 2)
    F.master_set(d, it["id"])
    with open(os.path.join(d, "keyframes.json"), "w") as f:
        json.dump({"directed": {"S01": "project:keyframes/S01.png"}}, f)
    outside = tmp_path / "evil.png"
    Image.new("RGB", (10, 10)).save(outside)
    with open(os.path.join(d, "masters.json"), "w") as f:
        json.dump({"directed": {"S01": {"ref": "project:../evil.png", "source": "project:keyframes/S01.png"}}}, f)
    assert R.approved_keyframe(d, "directed", "S01") == "project:keyframes/S01.png"
    F.master_set  # a master from a replaced keyframe is refused
    with open(os.path.join(d, "keyframes.json"), "w") as f:
        json.dump({"directed": {"S01": "project:keyframes/other.png"}}, f)
    with pytest.raises(SystemExit):
        F.master_set(d, it["id"])
