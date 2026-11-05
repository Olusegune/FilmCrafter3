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
