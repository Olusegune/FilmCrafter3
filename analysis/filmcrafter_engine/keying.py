"""Cutting a subject out of a green or blue screen, and putting it on a different picture. Pure numpy and Pillow: no film, no files of the film, no network. Reusable by any application.

What is done, in order, and why:

1. **Look at the plate** (`analyze_plate`). A generated or filmed "green screen" is not always a clean, even colour. The border of the picture is read for the screen colour and for how
   even it is, and the answer says whether a key is likely to work, with the numbers. Nothing is assumed.
2. **Key** (`key`). The distance of every pixel's colour from the screen colour is measured in the chroma plane only (Cb and Cr, BT.709), so a darker or lighter patch of the same screen
   (a shadow, a vignette) still counts as screen. Inside the *similarity* radius a pixel is screen (transparent); outside the *softness* radius it is subject (opaque); between them the
   transparency is a smooth ramp, which is what keeps hair and soft edges.
3. **Refine** (`refine`). Optional grow or shrink of the cutout (erode / dilate), filling of enclosed holes, and a feather of the edge, all on the transparency only.
4. **Clean the colour** (`decontaminate`, `despill`). Along the edge a pixel is a mix of subject and screen. The screen's share is removed from the colour (in linear light), and the screen's
   channel is limited so no green or blue fringe is left on the subject.
5. **Composite** (`composite`). Subject over picture in *linear light* with premultiplied alpha (so no dark or light halos), with a transform (place, scale, rotate, flip), an optional
   contact shadow and an optional colour match to the picture under it.

What this does not do: it does not know what a person is (no segmentation model, no depth), so it cannot cut a subject out of a picture with no screen; green that is *on* the subject
(a green jacket) is keyed out with the screen unless it is far enough from the screen colour; and a plate whose screen is uneven or noisy will give a poor key. Those cases are what
`analyze_plate` is there to warn about. Models for them (segmentation, matting) are optional adapters that are installed deliberately and are not part of this module.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

MAX_PIXELS = 40_000_000
SCREENS = ("green", "blue")


# ---------------------------------------------------------------- colour helpers (sRGB <-> linear, BT.709 chroma)

def _num(x, lo: float, hi: float, default: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if v != v or v in (float("inf"), float("-inf")):
        return default
    return min(hi, max(lo, v))


def to_linear(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * (c ** (1 / 2.4)) - 0.055)


def chroma(rgb: np.ndarray) -> np.ndarray:
    """Cb and Cr (BT.709, full range, 0 at grey) of an sRGB image 0..1, shape (..., 2)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return np.stack([(b - y) / 1.8556, (r - y) / 1.5748], axis=-1)


def load(path_or_image) -> np.ndarray:
    """An image as float RGB 0..1 (transparency dropped). Refuses a picture too large to work on."""
    im = path_or_image if isinstance(path_or_image, Image.Image) else Image.open(path_or_image)
    if im.width * im.height > MAX_PIXELS:
        raise SystemExit(f"That picture is {im.width} by {im.height}: too large to work on (the limit is {MAX_PIXELS // 1_000_000} megapixels).")
    return np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0


# ---------------------------------------------------------------- 1. looking at the plate

def screen_color(rgb: np.ndarray, border: float = 0.06, screen: str | None = None) -> np.ndarray:
    """The screen colour: the median of a frame of pixels around the edge that look like the chosen screen (all of them when none is chosen)."""
    h, w = rgb.shape[:2]
    t = max(2, int(min(h, w) * border))
    ring = np.concatenate([rgb[:t].reshape(-1, 3), rgb[-t:].reshape(-1, 3), rgb[t:-t, :t].reshape(-1, 3), rgb[t:-t, -t:].reshape(-1, 3)])
    if screen in SCREENS:
        k = 1 if screen == "green" else 2
        other = [i for i in range(3) if i != k]
        pick = ring[:, k] > ring[:, other].max(axis=1) + 0.08
        if pick.sum() >= max(50, len(ring) // 50):
            ring = ring[pick]
    return np.median(ring, axis=0)


def analyze_plate(rgb: np.ndarray, screen: str | None = None) -> dict:
    """Is this plate a screen a key can work on? Reads the border for the screen colour and how even it is. Gives the numbers and the plain verdict."""
    key = screen_color(rgb, screen=screen)
    k = int(np.argmax(key))
    kind = "green" if k == 1 else "blue" if k == 2 else "other"
    other = [i for i in range(3) if i != k]
    saturation = float(key[k] - key[other].max())
    h, w = rgb.shape[:2]
    t = max(2, int(min(h, w) * 0.06))
    ring_mask = np.zeros((h, w), dtype=bool)
    ring_mask[:t], ring_mask[-t:], ring_mask[:, :t], ring_mask[:, -t:] = True, True, True, True
    cc = chroma(rgb)
    kc = chroma(key.reshape(1, 1, 3))[0, 0]
    dist = np.linalg.norm(cc - kc, axis=-1)
    near = dist[ring_mask]
    on_screen = float((near < 0.08).mean())
    spread = float(np.percentile(near, 90))
    notes, ok = [], True
    if kind == "other" or saturation < 0.12:
        ok = False
        notes.append("The border is not a clear green or blue. Pick the screen colour yourself, or generate the plate again.")
    if on_screen < 0.85:
        ok = False
        notes.append(f"Only {on_screen:.0%} of the border is the screen colour: the subject or a different background reaches the edge, or the screen is uneven.")
    if spread > 0.07:
        ok = False
        notes.append("The screen colour varies a lot across the border: expect holes and ragged edges. A more even plate will key much better.")
    elif spread > 0.04:
        notes.append("The screen is a little uneven: raise the softness a little and check the edge.")
    if ok and not notes:
        notes.append("A clean, even screen: a key should work well.")
    return {"screen": kind, "color": [round(float(x), 4) for x in key], "saturation": round(saturation, 3), "border_on_screen": round(on_screen, 3), "spread": round(spread, 3), "usable": ok, "notes": notes,
            "width": int(w), "height": int(h)}


# ---------------------------------------------------------------- 2. keying

DEFAULTS = {"screen": "green", "color": None, "similarity": 0.06, "softness": None, "erode": 0, "dilate": 0, "feather": 0.0, "fill_holes": False, "despill": 0.8, "decontaminate": True, "clip_black": 0.0, "clip_white": 1.0}


def clean_params(p: dict | None) -> dict:
    """Key settings, each checked and limited; anything not given gets its default."""
    x = dict(DEFAULTS)
    p = p if isinstance(p, dict) else {}
    if p.get("screen") in SCREENS:
        x["screen"] = p["screen"]
    col = p.get("color")
    if isinstance(col, (list, tuple)) and len(col) == 3:
        x["color"] = [round(_num(c, 0.0, 1.0, 0.0), 4) for c in col]
    x["similarity"] = round(_num(p.get("similarity"), 0.0, 0.6, DEFAULTS["similarity"]), 3)
    x["softness"] = None if p.get("softness") in (None, "", "auto") else round(_num(p.get("softness"), 0.0, 0.6, 0.15), 3)          # None: worked out from the plate
    x["erode"] = int(_num(p.get("erode"), 0, 12, 0))
    x["dilate"] = int(_num(p.get("dilate"), 0, 12, 0))
    x["feather"] = round(_num(p.get("feather"), 0.0, 20.0, 0.0), 2)
    x["fill_holes"] = bool(p.get("fill_holes", False))
    x["despill"] = round(_num(p.get("despill"), 0.0, 1.0, DEFAULTS["despill"]), 2)
    x["decontaminate"] = bool(p.get("decontaminate", True))
    x["clip_black"] = round(_num(p.get("clip_black"), 0.0, 0.9, 0.0), 2)
    x["clip_white"] = round(_num(p.get("clip_white"), 0.1, 1.0, 1.0), 2)
    if x["clip_white"] <= x["clip_black"] + 0.05:
        x["clip_black"], x["clip_white"] = 0.0, 1.0
    return x


def auto_hi(d: np.ndarray, similarity: float) -> float:
    """Where the ramp ends (a chroma distance), worked out from the picture: 90% of the distance the weaker-coloured fifth of the subject's pixels have from the screen."""
    far = d[d > similarity + 0.12]
    ref = float(np.percentile(far, 20)) if far.size > 50 else similarity + 0.3                      # the weaker-coloured parts of the subject decide: they must come out solid too
    return max(similarity + 0.05, min(0.9 * ref, similarity + 0.6))


def calibrate(frames: list[np.ndarray], params: dict | None = None) -> dict:
    """Settings that hold for a whole clip: the screen colour and the ramp width are worked out once from several frames (their medians) and then fixed, so every frame is keyed the same way
    and the edge does not breathe from frame to frame. Settings the person gave (a colour, a softness) are kept."""
    p = clean_params(params)
    if not frames:
        return p
    if p["color"] is None:
        p["color"] = [round(float(x), 4) for x in np.median(np.stack([screen_color(f, screen=p["screen"]) for f in frames]), axis=0)]
    if p["softness"] is None:
        kc = chroma(np.array(p["color"], dtype=np.float32).reshape(1, 1, 3))[0, 0]
        his = [auto_hi(np.linalg.norm(chroma(f) - kc, axis=-1), p["similarity"]) for f in frames]
        p["softness"] = round(float(np.median(his)) - p["similarity"], 4)
    return p


def raw_alpha(rgb: np.ndarray, key: np.ndarray, similarity: float, softness: float | None) -> np.ndarray:
    """0 on the screen, 1 on the subject, a straight ramp between: the chroma distance from the screen colour, ignoring brightness. A pixel that is half subject and half screen is about half
    way from the screen colour to the subject's colour, so the ramp is straight. When `softness` is None the ramp ends at 90% of the distance the weaker-coloured fifth of the subject's pixels have from the
    screen (so a strongly coloured subject and a pale one both come out fully solid inside), worked out from the plate; a number sets the width of the ramp by hand."""
    d = np.linalg.norm(chroma(rgb) - chroma(key.reshape(1, 1, 3))[0, 0], axis=-1)
    if softness is None:
        hi = auto_hi(d, similarity)
    else:
        hi = similarity + max(softness, 1e-4)
    return np.clip((d - similarity) / (hi - similarity), 0.0, 1.0)


def refine(alpha: np.ndarray, erode: int = 0, dilate: int = 0, feather: float = 0.0, fill_holes: bool = False, clip_black: float = 0.0, clip_white: float = 1.0) -> np.ndarray:
    """Clean the transparency: levels, fill enclosed holes, shrink, grow, feather. Order matters and is fixed: levels, holes, erode, dilate, feather."""
    a = np.clip((alpha - clip_black) / max(clip_white - clip_black, 1e-3), 0.0, 1.0)
    im = Image.fromarray((a * 255 + 0.5).astype(np.uint8), "L")
    if fill_holes:
        solid = im.point(lambda v: 255 if v >= 128 else 0)
        padded = ImageChops.invert(solid)
        w, h = padded.size
        canvas = Image.new("L", (w + 2, h + 2), 255)
        canvas.paste(padded, (1, 1))
        ImageDraw.floodfill(canvas, (0, 0), 128)                                                       # what is reached from outside is real background
        outside = np.asarray(canvas)[1:-1, 1:-1] == 128
        holes = (np.asarray(padded) == 255) & ~outside                                                  # enclosed and transparent
        arr = np.asarray(im).copy()
        arr[holes] = 255
        im = Image.fromarray(arr, "L")
    for _ in range(int(erode)):
        im = im.filter(ImageFilter.MinFilter(3))
    for _ in range(int(dilate)):
        im = im.filter(ImageFilter.MaxFilter(3))
    if feather > 0:
        im = im.filter(ImageFilter.GaussianBlur(feather))
    return np.asarray(im, dtype=np.float32) / 255.0


def despill(rgb: np.ndarray, screen: str, amount: float) -> np.ndarray:
    """Limit the screen's channel to the average of the other two (so a subject has no green or blue cast), by `amount` (0 leaves it, 1 removes all excess)."""
    k = 1 if screen == "green" else 2
    other = [i for i in range(3) if i != k]
    out = rgb.copy()
    cap = rgb[..., other].mean(axis=-1)
    excess = np.maximum(rgb[..., k] - cap, 0.0)
    out[..., k] = rgb[..., k] - excess * amount
    return out


def decontaminate(rgb: np.ndarray, alpha: np.ndarray, key: np.ndarray) -> np.ndarray:
    """Remove the screen's share of the colour from the edge: a pixel C is subject S and screen K mixed, C = a*S + (1-a)*K, so S = (C - (1-a)*K) / a, worked out in linear light."""
    lin, kl = to_linear(rgb), to_linear(key.reshape(1, 1, 3))[0, 0]
    a = np.maximum(alpha, 1e-3)[..., None]
    sub = (lin - (1 - a) * kl) / a
    edge = ((alpha > 0.003) & (alpha < 0.997))[..., None]
    sub = np.where(edge, np.clip(sub, 0.0, 1.0), lin)
    return to_srgb(sub)


def key(rgb: np.ndarray, params: dict | None = None) -> tuple[np.ndarray, dict]:
    """Cut the subject out of a plate. Returns the picture as straight (unassociated) RGBA float 0..1, and a report of what was done and what to look at."""
    p = clean_params(params)
    plate = analyze_plate(rgb, p["screen"])
    kcol = np.array(p["color"], dtype=np.float32) if p["color"] else np.array(plate["color"], dtype=np.float32)
    a = raw_alpha(rgb, kcol, p["similarity"], p["softness"])
    a = refine(a, p["erode"], p["dilate"], p["feather"], p["fill_holes"], p["clip_black"], p["clip_white"])
    colour = decontaminate(rgb, a, kcol) if p["decontaminate"] else rgb
    colour = despill(colour, p["screen"], p["despill"]) if p["despill"] > 0 else colour
    out = np.concatenate([np.clip(colour, 0, 1), a[..., None]], axis=-1).astype(np.float32)
    out[..., :3] *= (a > 0.002)[..., None]                                                               # no colour is kept where there is nothing: it would only fringe later
    return out, report(out, p, plate)


def report(rgba: np.ndarray, p: dict, plate: dict) -> dict:
    """What the key produced, in numbers a person can act on: how much is subject, how much is half-transparent edge, how much green is left on the edge."""
    a = rgba[..., 3]
    total = a.size
    solid, empty = float((a > 0.98).sum()) / total, float((a < 0.02).sum()) / total
    edge = (a > 0.02) & (a < 0.98)
    k = 1 if p["screen"] == "green" else 2
    other = [i for i in range(3) if i != k]
    if edge.any():
        e = rgba[..., :3][edge]
        spill = float(np.maximum(e[:, k] - e[:, other].mean(axis=1), 0).mean())
    else:
        spill = 0.0
    notes = list(plate["notes"])
    if solid < 0.01:
        notes.append("Almost nothing was kept as subject: lower the similarity, or the screen colour is wrong.")
    if empty < 0.05:
        notes.append("Almost nothing was removed: raise the similarity, or pick the screen colour from the plate.")
    if spill > 0.03:
        notes.append("There is still screen colour on the edge: raise despill, or erode the edge by one pixel.")
    return {"subject": round(solid, 4), "removed": round(empty, 4), "soft_edge": round(float(edge.sum()) / total, 4), "edge_spill": round(spill, 4), "plate": plate, "params": p, "notes": notes}


# ---------------------------------------------------------------- 5. compositing

def save_rgba(rgba: np.ndarray, path: str) -> None:
    """A straight-alpha RGBA PNG (what editors and compositors read)."""
    Image.fromarray((np.clip(rgba, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA").save(path, "PNG")


def load_rgba(path: str) -> np.ndarray:
    im = Image.open(path)
    if im.width * im.height > MAX_PIXELS:
        raise SystemExit("That picture is too large to work on.")
    return np.asarray(im.convert("RGBA"), dtype=np.float32) / 255.0


def transform_layer(rgba: np.ndarray, size: tuple[int, int], *, x: float = 0.5, y: float = 0.5, scale: float = 1.0, rotation: float = 0.0, flip: bool = False, anchor: tuple[float, float] = (0.5, 1.0)) -> np.ndarray:
    """Place a layer on a canvas of `size` (width, height). `x` and `y` are where the layer's anchor lands, as a share of the canvas (0..1); `scale` is of the layer's own size; `rotation` is degrees
    clockwise about the anchor; the default anchor is the bottom centre (the feet). Premultiplied before it is resampled, so edges do not get dark or light halos."""
    W, H = size
    h, w = rgba.shape[:2]
    pm = rgba.copy()
    pm[..., :3] *= pm[..., 3:4]
    if flip:
        pm = pm[:, ::-1]
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    chans = [Image.fromarray(np.ascontiguousarray(pm[..., i]), "F").resize((nw, nh), Image.BICUBIC) for i in range(4)]
    ax, ay = (1 - anchor[0] if flip else anchor[0]) * nw, anchor[1] * nh
    # a canvas big enough to rotate about the anchor, then put the anchor where it belongs
    r = int(math.ceil(math.hypot(nw, nh))) * 2
    big = Image.new("F", (r, r), 0.0)
    out = []
    for c in chans:
        b = big.copy()
        b.paste(c, (int(r / 2 - ax), int(r / 2 - ay)))
        b = b.rotate(-rotation, resample=Image.BICUBIC, center=(r / 2, r / 2))
        canvas = Image.new("F", (W, H), 0.0)
        canvas.paste(b, (int(round(x * W - r / 2)), int(round(y * H - r / 2))))
        out.append(np.asarray(canvas, dtype=np.float32))
    res = np.stack(out, axis=-1)
    a = np.clip(res[..., 3], 0, 1)
    res[..., :3] = np.where(a[..., None] > 1e-4, res[..., :3] / np.maximum(a[..., None], 1e-4), 0.0)       # back to straight alpha
    res[..., 3] = a
    return np.clip(res, 0, 1)


def over(fg: np.ndarray, bg_rgb: np.ndarray, opacity: float = 1.0) -> np.ndarray:
    """Straight RGBA `fg` over an RGB picture, in linear light with premultiplied alpha. Returns RGB 0..1 (sRGB)."""
    a = np.clip(fg[..., 3:4], 0, 1) * opacity
    f, b = to_linear(fg[..., :3]), to_linear(bg_rgb)
    return to_srgb(f * a + b * (1 - a))


def contact_shadow(rgba: np.ndarray, size: tuple[int, int], *, x: float, y: float, scale: float, strength: float = 0.45, blur: float = 8.0, squash: float = 0.25, spread: float = 1.0) -> np.ndarray:
    """A soft shadow on the ground at the subject's feet: the subject's outline, flattened and blurred, centred where the feet are. An approximation (a flat ground, light from above), not a render
    of the real light: it grounds the subject, it does not match a particular light. Returns an alpha layer (H, W)."""
    W, H = size
    h, w = rgba.shape[:2]
    a = rgba[..., 3]
    ys, xs = np.nonzero(a > 0.5)
    if len(xs) == 0:
        return np.zeros((H, W), np.float32)
    x0, x1 = xs.min(), xs.max() + 1
    low = int(max(1, (ys.max() - ys.min()) * 0.12))                                                       # the lowest slice of the subject is what touches the ground
    foot = a[max(0, ys.max() - low): ys.max() + 1, x0:x1]
    fw = max(1, int(round((x1 - x0) * scale * spread)))
    fh = max(2, int(round(fw * squash * 0.5)))
    im = Image.fromarray((foot.max(axis=0, keepdims=True).repeat(fh, axis=0) * 255).astype(np.uint8), "L").resize((fw, fh), Image.BICUBIC)
    pad = int(blur * 3) + 2
    canvas = Image.new("L", (W + 2 * pad, H + 2 * pad), 0)
    cx = int(round(x * W)) - fw // 2 + pad
    cy = int(round(y * H)) - fh // 2 + pad
    canvas.paste(im, (cx, cy))
    if blur > 0:
        canvas = canvas.filter(ImageFilter.GaussianBlur(blur))
    return (np.asarray(canvas.crop((pad, pad, pad + W, pad + H)), dtype=np.float32) / 255.0) * strength


def color_match(fg: np.ndarray, bg_rgb: np.ndarray, strength: float = 0.5) -> np.ndarray:
    """Pull the subject's colour toward the picture it sits on: mean and spread of each channel in linear light, only where the subject is. `strength` 0 leaves it, 1 matches fully."""
    a = fg[..., 3] > 0.5
    if not a.any() or strength <= 0:
        return fg
    lf, lb = to_linear(fg[..., :3]), to_linear(bg_rgb)
    out = lf.copy()
    for c in range(3):
        mf, sf = lf[..., c][a].mean(), lf[..., c][a].std() + 1e-4
        mb, sb = lb[..., c].mean(), lb[..., c].std() + 1e-4
        matched = (lf[..., c] - mf) / sf * (0.5 * sf + 0.5 * sb) + mf + (mb - mf) * 0.5                     # half way in spread and in level, so it is a pull and not a repaint
        out[..., c] = lf[..., c] * (1 - strength) + matched * strength
    res = fg.copy()
    res[..., :3] = to_srgb(np.clip(out, 0, 1))
    return res


def anchor_of(rgba: np.ndarray, how: str = "feet") -> tuple[float, float]:
    """Where a layer is held when it is placed, as a share of the layer's picture. "feet": the middle of the subject's width and the bottom of the subject (not of the picture, which has space
    round it); "bottom": the middle of the bottom edge of the picture; "centre": the middle of the picture."""
    if how == "centre":
        return (0.5, 0.5)
    if how == "bottom":
        return (0.5, 1.0)
    h, w = rgba.shape[:2]
    ys, xs = np.nonzero(rgba[..., 3] > 0.5)
    if len(xs) == 0:
        return (0.5, 1.0)
    return (float((xs.min() + xs.max() + 1) / 2 / w), float((ys.max() + 1) / h))


def composite(bg_rgb: np.ndarray, layers: list[dict]) -> np.ndarray:
    """Layers bottom to top over a background. Each layer is {rgba, x, y, scale, rotation, flip, opacity, anchor: "feet"|"bottom"|"centre" (or a pair), shadow: {...} | None, match: float}; (x, y) is where the anchor lands. Returns RGB 0..1."""
    H, W = bg_rgb.shape[:2]
    out = bg_rgb.copy()
    for L in layers:
        rgba = L["rgba"]
        placed_at = dict(x=float(L.get("x", 0.5)), y=float(L.get("y", 1.0)), scale=float(L.get("scale", 1.0)))
        want = L.get("anchor", "feet")
        anchor = tuple(want) if isinstance(want, (tuple, list)) else anchor_of(rgba, want)
        sh = L.get("shadow")
        if sh and float(sh.get("strength", 0)) > 0:
            sa = contact_shadow(rgba, (W, H), **placed_at, strength=float(sh["strength"]), blur=float(sh.get("blur", 8)), squash=float(sh.get("squash", 0.25)), spread=float(sh.get("spread", 1.0)))
            out = to_srgb(to_linear(out) * (1 - sa[..., None]))                                           # black laid over: multiply by what is left
        fg = rgba if not L.get("match") else color_match(rgba, out, float(L["match"]))
        placed = transform_layer(fg, (W, H), x=placed_at["x"], y=placed_at["y"], scale=placed_at["scale"], rotation=float(L.get("rotation", 0)), flip=bool(L.get("flip", False)),
                                 anchor=anchor)
        out = over(placed, out, float(L.get("opacity", 1.0)))
    return np.clip(out, 0, 1)


# ---------------------------------------------------------------- motion: keyframes for a layer

KEY_FIELDS = ("x", "y", "scale", "rotation", "opacity")
KEY_LIMITS = {"x": (-2.0, 3.0), "y": (-2.0, 3.0), "scale": (0.02, 8.0), "rotation": (-360.0, 360.0), "opacity": (0.0, 1.0)}
EASES = ("linear", "smooth", "hold")
MAX_KEYS = 50


def clean_keys(keys) -> list[dict]:
    """Keyframes for a layer: a time (seconds, 0 to an hour) and any of x, y, scale, rotation, opacity, each limited, and how to get to the next key (straight, eased, or a jump). Sorted by time; a key
    with no time or no value is dropped; two at the same time keep the later."""
    out: dict[float, dict] = {}
    for k in (keys if isinstance(keys, list) else [])[: MAX_KEYS * 2]:
        if not isinstance(k, dict):
            continue
        try:
            t = float(k.get("t"))
        except (TypeError, ValueError):
            continue
        if t != t or t < 0 or t > 3600:
            continue
        item: dict = {"t": round(t, 3), "ease": k.get("ease") if k.get("ease") in EASES else "linear"}
        for f in KEY_FIELDS:
            if f in k:
                lo, hi = KEY_LIMITS[f]
                item[f] = round(_num(k[f], lo, hi, (lo + hi) / 2 if f != "scale" else 1.0), 4)
        if len(item) > 2:
            out[item["t"]] = item
    return [out[t] for t in sorted(out)][:MAX_KEYS]


def interp(keys: list[dict], t: float, field: str):
    """The value of one field at time `t`, or None when no key sets it. Held before the first key and after the last; between two keys it moves the way the earlier key says."""
    pts = [(k["t"], k[field], k.get("ease", "linear")) for k in keys if field in k]
    if not pts:
        return None
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, v0, ease), (t1, v1, _) in zip(pts, pts[1:]):
        if t < t1:
            if ease == "hold":
                return v0
            u = (t - t0) / max(t1 - t0, 1e-9)
            u = u * u * (3 - 2 * u) if ease == "smooth" else u
            return v0 + (v1 - v0) * u
    return pts[-1][1]
