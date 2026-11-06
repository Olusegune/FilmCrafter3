"""Keying and compositing, measured against pictures whose true answer is known: a subject with soft hair-like edges and green spill is mixed over a noisy, uneven green screen in linear light,
so the true transparency and the true subject colour are known and the key can be scored against them. These are synthetic plates made for the test, not photographs."""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from filmcrafter_engine import keying as K

W, H = 320, 400
SCREEN = np.array([0.10, 0.72, 0.20], dtype=np.float32)


def subject_mask(blur=2.2):
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    d.ellipse((100, 110, 220, 250), fill=255)                  # head and shoulders
    d.rectangle((110, 230, 210, 380), fill=255)                # body
    for i in range(40):                                        # fine strands out of the head
        x = 105 + i * 2.8
        d.line((x, 118, x + (i % 7 - 3) * 6, 80 - (i % 5) * 5), fill=255, width=1)
    return np.asarray(m.filter(ImageFilter.GaussianBlur(blur)), dtype=np.float32) / 255.0


def subject_colour(alpha):
    s = np.zeros((H, W, 3), dtype=np.float32)
    s[...] = [0.80, 0.55, 0.45]
    s[230:, :] = [0.70, 0.12, 0.15]
    return s


def make_plate(seed=1, spill=0.0, vignette=0.15, noise=0.008, hole=False):
    rng = np.random.default_rng(seed)
    a = subject_mask()
    if hole:
        yy, xx = np.mgrid[0:H, 0:W]
        a = a * (1 - ((xx - 160) ** 2 + (yy - 300) ** 2 < 14 ** 2))
    s = subject_colour(a)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    light = 1.0 - vignette * ((xx - W / 2) ** 2 / (W / 2) ** 2 + (yy - H / 2) ** 2 / (H / 2) ** 2) * 0.5
    screen = SCREEN[None, None, :] * light[..., None]
    if spill:
        near = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(7)), dtype=np.float32) / 255.0
        edge = np.clip(a - near, 0, 1) * -1 + np.clip(1 - near, 0, 1) * a                              # strongest just inside the edge
        s = s + spill * np.clip(edge * 3, 0, 1)[..., None] * np.array([0.0, 0.5, 0.0], dtype=np.float32)
    ls, lk = K.to_linear(np.clip(s, 0, 1)), K.to_linear(screen)
    mixed = K.to_srgb(ls * a[..., None] + lk * (1 - a[..., None]))
    mixed = np.clip(mixed + rng.normal(0, noise, mixed.shape).astype(np.float32), 0, 1)
    return mixed.astype(np.float32), a, np.clip(s, 0, 1)


def edge_of(a):
    return (a > 0.03) & (a < 0.97)


def spill_of(rgba, k=1):
    e = edge_of(rgba[..., 3])
    px = rgba[..., :3][e]
    return float(np.maximum(px[:, k] - px[:, [0, 2]].mean(axis=1), 0).mean())


# ---------------------------------------------------------------- looking at the plate

def test_a_clean_even_screen_is_usable_and_the_screen_colour_is_found():
    plate, _, _ = make_plate()
    r = K.analyze_plate(plate)
    assert r["usable"] and r["screen"] == "green" and r["border_on_screen"] > 0.95
    assert np.allclose(r["color"], SCREEN * 0.93, atol=0.08)                                              # the vignette darkens the border a little
    assert "clean, even screen" in r["notes"][0]


def test_a_blue_screen_is_recognised():
    plate, _, _ = make_plate()
    blue = plate[..., [0, 2, 1]]
    r = K.analyze_plate(blue)
    assert r["screen"] == "blue" and r["usable"]


def test_a_grey_background_is_not_a_screen():
    grey = np.full((H, W, 3), 0.5, np.float32)
    r = K.analyze_plate(grey)
    assert not r["usable"] and r["screen"] in ("green", "blue", "other") and any("not a clear green or blue" in n for n in r["notes"])


def test_an_uneven_screen_is_flagged_with_numbers():
    plate, _, _ = make_plate(vignette=0.0)
    ramp = np.linspace(0.0, 1.0, W, dtype=np.float32)[None, :, None]
    bad = np.clip(plate * 0.3 + (plate * ramp[..., [0, 0, 0]]) * 0.7 + np.array([0.15, 0, 0.15], np.float32) * ramp, 0, 1)    # the screen's colour drifts across the picture
    r = K.analyze_plate(bad)
    assert not r["usable"] or r["spread"] > 0.04
    assert any("varies" in n or "uneven" in n or "Only" in n or "not a clear" in n for n in r["notes"])


def test_a_subject_that_reaches_the_edge_is_flagged():
    plate, _, _ = make_plate()
    plate[:, :W // 3] = [0.8, 0.5, 0.4]                                                                    # a wall of skin colour down one side
    r = K.analyze_plate(plate)
    assert not r["usable"] and r["border_on_screen"] < 0.85 and any("Only" in n for n in r["notes"])


# ---------------------------------------------------------------- the key against the truth

def test_the_key_finds_the_subject_and_the_soft_edge():
    plate, truth, _ = make_plate(spill=1.0)
    rgba, rep = K.key(plate, {"similarity": 0.06})
    a = rgba[..., 3]
    inside, outside = truth > 0.99, truth < 0.01
    assert (a[inside] > 0.97).mean() > 0.97 and (a[outside] < 0.03).mean() > 0.97
    e = edge_of(truth)
    assert float(np.abs(a[e] - truth[e]).mean()) < 0.12                                                    # the soft edge is kept, not cut hard
    assert 0.2 < rep["subject"] < 0.5 and rep["removed"] > 0.4 and rep["plate"]["usable"]


def test_the_key_keeps_the_hair_strands_and_a_hard_threshold_would_lose_them():
    plate, truth, _ = make_plate()
    rgba, _ = K.key(plate, {"similarity": 0.06})
    hair = np.zeros_like(truth, dtype=bool)
    hair[:105, :] = truth[:105, :] > 0.05
    found = float((rgba[..., 3][hair] > 0.05).mean())
    assert found > 0.85
    hard, _ = K.key(plate, {"similarity": 0.25, "softness": 0.0})
    assert float((hard[..., 3][hair] > 0.05).mean()) < found                                               # a hard threshold loses more of it


def test_brightness_changes_in_the_screen_do_not_leak_into_the_subject():
    plate, truth, _ = make_plate(vignette=0.5)
    rgba, _ = K.key(plate, {"similarity": 0.07})
    assert float((rgba[..., 3][truth < 0.01] > 0.05).mean()) < 0.03


def test_decontamination_and_despill_remove_the_green_from_the_edge():
    plate, truth, _ = make_plate(spill=1.2)
    raw, _ = K.key(plate, {"similarity": 0.06, "despill": 0.0, "decontaminate": False})
    clean, rep = K.key(plate, {"similarity": 0.06, "despill": 0.9, "decontaminate": True})
    assert spill_of(raw) > 0.02 and spill_of(clean) < spill_of(raw) * 0.35
    assert rep["edge_spill"] < 0.03


def test_decontamination_recovers_the_subject_colour_at_the_edge():
    plate, truth, true_colour = make_plate()
    raw, _ = K.key(plate, {"similarity": 0.06, "despill": 0.0, "decontaminate": False})
    fixed, _ = K.key(plate, {"similarity": 0.06, "despill": 0.0, "decontaminate": True})
    e = (truth > 0.2) & (truth < 0.8)
    err_raw = float(np.abs(raw[..., :3][e] - true_colour[e]).mean())
    err_fixed = float(np.abs(fixed[..., :3][e] - true_colour[e]).mean())
    assert err_fixed < err_raw * 0.6                                                                       # much closer to the real subject colour than the raw mix


def test_no_colour_is_kept_where_there_is_nothing():
    plate, truth, _ = make_plate()
    rgba, _ = K.key(plate)
    assert np.abs(rgba[..., :3][rgba[..., 3] < 0.001]).max() == 0.0


# ---------------------------------------------------------------- refining

def test_erode_shrinks_dilate_grows_feather_softens():
    a = np.zeros((60, 60), np.float32)
    a[20:40, 20:40] = 1.0
    assert K.refine(a, erode=2).sum() < a.sum() and K.refine(a, dilate=2).sum() > a.sum()
    soft = K.refine(a, feather=3)
    assert ((soft > 0.05) & (soft < 0.95)).sum() > ((a > 0.05) & (a < 0.95)).sum()
    assert np.allclose(K.refine(a), a, atol=1 / 255)                                                       # nothing asked, nothing changed


def test_holes_are_filled_only_when_enclosed_and_only_when_asked():
    a = np.zeros((60, 60), np.float32)
    a[10:50, 10:50] = 1.0
    a[28:32, 28:32] = 0.0                                                                                  # a hole inside
    a[10:50, 5:8] = 0.0
    kept = K.refine(a)
    filled = K.refine(a, fill_holes=True)
    assert kept[30, 30] == 0.0 and filled[30, 30] == 1.0
    assert filled[5, 5] == 0.0 and filled[30, 6] == 0.0                                                    # the outside, and the gap that reaches it, stay empty


def test_levels_clip_the_ramp():
    a = np.linspace(0, 1, 100, dtype=np.float32).reshape(1, 100)
    out = K.refine(a, clip_black=0.3, clip_white=0.7)
    assert out[0, 10] == 0.0 and out[0, 90] == 1.0 and 0.2 < out[0, 50] < 0.8


def test_settings_are_checked_and_limited():
    p = K.clean_params({"screen": "red", "similarity": 9, "softness": -1, "erode": 99, "dilate": "x", "feather": 1e9, "despill": 5, "color": [1, 2], "clip_black": 0.8, "clip_white": 0.82, "fill_holes": 1})
    assert p["screen"] == "green" and p["similarity"] == 0.6 and p["softness"] == 0.0 and p["erode"] == 12 and p["dilate"] == 0 and p["feather"] == 20.0 and p["despill"] == 1.0
    assert p["color"] is None and (p["clip_black"], p["clip_white"]) == (0.0, 1.0) and p["fill_holes"] is True
    assert K.clean_params(None) == K.clean_params({})
    assert K.clean_params({"color": [0.1, 0.9, 5]})["color"] == [0.1, 0.9, 1.0]


def test_a_picture_that_is_too_large_is_refused(monkeypatch):
    monkeypatch.setattr(K, "MAX_PIXELS", 1000)
    with pytest.raises(SystemExit, match="too large"):
        K.load(Image.new("RGB", (100, 100)))


# ---------------------------------------------------------------- compositing

def cutout(seed=2):
    plate, truth, colour = make_plate(seed=seed)
    return np.concatenate([colour, truth[..., None]], axis=-1).astype(np.float32), truth, colour


def test_a_soft_edged_subject_over_white_and_black_matches_the_true_composite_with_no_halo():
    rgba, truth, colour = cutout()
    for level in (0.0, 1.0):
        bg = np.full((H, W, 3), level, np.float32)
        out = K.composite(bg, [{"rgba": rgba, "x": 0.5, "y": 1.0, "scale": 1.0, "anchor": "bottom"}])
        ideal = K.to_srgb(K.to_linear(colour) * truth[..., None] + K.to_linear(bg) * (1 - truth[..., None]))
        e = edge_of(truth)
        assert float(np.abs(out - ideal)[e].mean()) < 0.02
    # the same cutout composited the naive way, in the encoded values with straight alpha, is further from the truth over white
    bg = np.ones((H, W, 3), np.float32)
    naive = rgba[..., :3] * rgba[..., 3:4] + bg * (1 - rgba[..., 3:4])
    ideal = K.to_srgb(K.to_linear(colour) * truth[..., None] + K.to_linear(bg) * (1 - truth[..., None]))
    good = K.composite(bg, [{"rgba": rgba, "x": 0.5, "y": 1.0, "scale": 1.0, "anchor": "bottom"}])
    e = edge_of(truth)
    assert np.abs(good - ideal)[e].mean() < np.abs(naive - ideal)[e].mean()


def test_a_cutout_lands_where_it_is_told_at_the_size_it_is_told():
    rgba = np.zeros((100, 60, 4), np.float32)
    rgba[..., :3], rgba[..., 3] = 1.0, 1.0
    out = K.transform_layer(rgba, (400, 300), x=0.5, y=0.8, scale=1.0)
    ys, xs = np.nonzero(out[..., 3] > 0.5)
    assert abs((xs.min() + xs.max()) / 2 - 200) <= 1 and abs(ys.max() - 240) <= 1 and abs((ys.max() - ys.min() + 1) - 100) <= 2
    half = K.transform_layer(rgba, (400, 300), x=0.5, y=0.8, scale=0.5)
    ys2, xs2 = np.nonzero(half[..., 3] > 0.5)
    assert abs((ys2.max() - ys2.min() + 1) - 50) <= 2 and abs((xs2.max() - xs2.min() + 1) - 30) <= 2


def test_rotation_and_flip():
    rgba = np.zeros((100, 60, 4), np.float32)
    rgba[:, :30, 0], rgba[:, :30, 3] = 1.0, 1.0                                                           # red left half
    r90 = K.transform_layer(rgba, (400, 400), x=0.5, y=0.5, scale=1.0, rotation=90, anchor=(0.5, 0.5))
    ys, xs = np.nonzero(r90[..., 3] > 0.5)
    assert (xs.max() - xs.min() + 1) in range(98, 103) and (ys.max() - ys.min() + 1) in range(28, 33)    # now wide and short
    flipped = K.transform_layer(rgba, (400, 400), x=0.5, y=0.5, scale=1.0, flip=True, anchor=(0.5, 0.5))
    ys, xs = np.nonzero(flipped[..., 3] > 0.5)
    assert xs.mean() > 200                                                                                 # the red half is on the right after a flip


def test_a_layer_can_go_partly_or_wholly_off_the_picture_without_error():
    rgba, _, _ = cutout()
    bg = np.full((H, W, 3), 0.3, np.float32)
    assert K.composite(bg, [{"rgba": rgba, "x": 1.4, "y": 1.2, "scale": 1.0}]).shape == bg.shape
    assert np.allclose(K.composite(bg, [{"rgba": rgba, "x": 5.0, "y": 5.0, "scale": 1.0}]), bg)


def test_opacity_blends_and_layer_order_puts_the_later_one_on_top():
    red = np.zeros((50, 50, 4), np.float32)
    red[..., 0], red[..., 3] = 1.0, 1.0
    blue = red.copy()
    blue[..., 0], blue[..., 2] = 0.0, 1.0
    bg = np.zeros((100, 100, 3), np.float32)
    top_blue = K.composite(bg, [{"rgba": red, "x": 0.5, "y": 0.75, "scale": 1.0}, {"rgba": blue, "x": 0.5, "y": 0.75, "scale": 1.0}])
    assert top_blue[50, 50, 2] > 0.99 and top_blue[50, 50, 0] < 0.01
    half = K.composite(bg, [{"rgba": red, "x": 0.5, "y": 0.75, "scale": 1.0, "opacity": 0.5}])
    assert 0.6 < half[50, 50, 0] < 0.8                                                                     # half in linear light, so brighter than 0.5 once encoded


def test_a_contact_shadow_darkens_the_ground_at_the_feet_and_nowhere_else():
    rgba, _, _ = cutout()
    bg = np.full((H, W, 3), 0.8, np.float32)
    lit = K.composite(bg, [{"rgba": rgba, "x": 0.5, "y": 0.9, "scale": 0.8, "shadow": None}])
    shaded = K.composite(bg, [{"rgba": rgba, "x": 0.5, "y": 0.9, "scale": 0.8, "shadow": {"strength": 0.6, "blur": 6, "squash": 0.3}}])
    diff = (lit - shaded).mean(axis=-1)
    ys, xs = np.nonzero(diff > 0.02)
    assert len(ys) > 0 and abs(ys.mean() - 0.9 * H) < 25 and abs(xs.mean() - 0.5 * W) < 40               # at the feet
    assert float(diff[: int(0.7 * H)].max()) < 0.01                                                        # not up the body
    none = K.composite(bg, [{"rgba": rgba, "x": 0.5, "y": 0.9, "scale": 0.8, "shadow": {"strength": 0}}])
    assert np.allclose(none, lit)


def test_colour_match_pulls_the_subject_toward_the_picture_and_zero_leaves_it():
    rgba, _, _ = cutout()
    warm_bg = np.full((H, W, 3), [0.9, 0.55, 0.2], np.float32)
    inside = rgba[..., 3] > 0.5
    before = rgba[..., :3][inside].mean(axis=0)
    m = K.color_match(rgba, warm_bg, 0.8)
    after = m[..., :3][inside].mean(axis=0)
    assert abs(after[0] - warm_bg[0, 0, 0]) < abs(before[0] - warm_bg[0, 0, 0]) and abs(after[2] - warm_bg[0, 0, 2]) < abs(before[2] - warm_bg[0, 0, 2])
    assert np.array_equal(K.color_match(rgba, warm_bg, 0.0), rgba)
    assert np.array_equal(m[..., 3], rgba[..., 3])                                                         # the cutout's shape is never changed by a colour match


def test_a_green_screen_subject_goes_onto_a_different_picture_end_to_end():
    plate, truth, colour = make_plate(seed=5, spill=1.0)
    rgba, rep = K.key(plate, {"similarity": 0.06})
    street = np.full((H, W, 3), [0.55, 0.5, 0.45], np.float32)
    street[: H // 2] = [0.4, 0.55, 0.75]
    out = K.composite(street, [{"rgba": rgba, "x": 0.5, "y": 1.0, "scale": 1.0, "anchor": "bottom", "shadow": {"strength": 0.3}, "match": 0.3}])
    ideal = K.to_srgb(K.to_linear(colour) * truth[..., None] + K.to_linear(street) * (1 - truth[..., None]))
    far = (truth < 0.01) & (np.arange(H)[:, None] < H * 0.85)
    assert float(np.abs(out - ideal)[far].mean()) < 0.01                                                   # the background is the new picture, untouched
    e = edge_of(truth)
    green = np.maximum(out[..., 1] - out[..., [0, 2]].mean(axis=-1), 0)
    ideal_green = np.maximum(ideal[..., 1] - ideal[..., [0, 2]].mean(axis=-1), 0)
    assert float(green[e].mean()) < float(ideal_green[e].mean()) + 0.02                                    # no green fringe beyond what the street itself has


def test_rgba_png_round_trip_keeps_straight_alpha(tmp_path):
    rgba, _, _ = cutout()
    p = str(tmp_path / "c.png")
    K.save_rgba(rgba, p)
    im = Image.open(p)
    assert im.mode == "RGBA" and im.size == (W, H)
    back = K.load_rgba(p)
    assert float(np.abs(back - rgba).max()) < 1 / 255 + 1e-3


def test_the_feet_anchor_stands_the_subject_on_the_line_not_the_picture_edge():
    rgba = np.zeros((200, 100, 4), np.float32)
    rgba[40:160, 30:70] = 1.0                                                                              # a subject with space round it
    assert K.anchor_of(rgba, "feet") == pytest.approx((0.5, 0.8)) and K.anchor_of(rgba, "bottom") == (0.5, 1.0) and K.anchor_of(rgba, "centre") == (0.5, 0.5)
    out = K.composite(np.zeros((300, 300, 3), np.float32), [{"rgba": rgba, "x": 0.5, "y": 0.9, "scale": 1.0}])
    ys, xs = np.nonzero(out.sum(axis=-1) > 0.5)
    assert abs(ys.max() - 270) <= 1 and abs((xs.min() + xs.max()) / 2 - 150) <= 1                          # the feet are at 90% of the height, the centre at the middle
    assert K.anchor_of(np.zeros((10, 10, 4), np.float32), "feet") == (0.5, 1.0)                            # nothing to find: the bottom
