"""Picture fidelity: a quality check before animating, and a careful clean-up that never touches the original.

Free, local and deterministic: only numpy and Pillow, nothing is sent anywhere, and nothing is billed.

  analyze   Measures a picture (sharpness, noise, clipping, JPEG blocking, exposure, contrast, size) and says what it found, how sure it is, and whether a clean-up is worth it.
            Measurements are not verdicts on taste: a softly focused background is reported as depth of field, not as a defect, and clipped whites are flagged as "may be intended".
            Faces and hands are NOT assessed (that needs a model); the report says so.
  enhance   Clean Enhance: gentle noise and block clean-up, edge-safe sharpening and a touch of local contrast. It cannot add detail that is not in the picture; it only cleans and
            sharpens what is there. The result is a new PNG in the project's fidelity folder, with the measurements before and after. The original file is never changed.
  apply     Use the cleaned picture as the shot's keyframe (the original stays and "revert" brings it back).
  revert    Back to the original keyframe.
  upscale   Local super-resolution with a Real-ESRGAN tool the user has installed (realesrgan-ncnn-vulkan). Free, on this computer, tiled so it fits a 12 GB card. Never downloads anything.
  master_set / master_clear   Choose a cleaned or enlarged copy as the shot's ANIMATION MASTER: the picture the video model is given. The keyframe is left as it is (it stays what you approved and what the storyboard
            shows); render.approved_keyframe hands the master to the video model while the keyframe is unchanged, and the keyframe when there is no master.
  status    What has been cleaned in this project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

import numpy as np
from PIL import Image, ImageFilter

from . import render as R
from .safe import file_name

FOLDER = "fidelity"
LEDGER = "fidelity.json"
MAX_SIDE = 2048            # larger pictures are measured on a reduced copy (said in the report)
TILE = 64
SOFT, OK = 0.16, 0.30      # edge-retention thresholds, tuned on synthetic ladders in the tests
ASPECTS = [("1:1", 1.0), ("4:5", 0.8), ("3:4", 0.75), ("2:3", 2 / 3), ("9:16", 9 / 16), ("9:21", 9 / 21), ("5:4", 1.25), ("4:3", 4 / 3), ("3:2", 1.5), ("16:10", 1.6), ("16:9", 16 / 9), ("2:1", 2.0), ("21:9", 21 / 9), ("2.39:1", 2.39)]


def emit(**kw) -> None:
    R.emit(**kw)


# ---------------------------------------------------------------- reading

def _open(path: str) -> Image.Image:
    try:
        im = Image.open(path)
        im.load()
    except Exception:
        raise SystemExit("That picture could not be opened.")
    return im


def _luma(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("RGB").convert("L"), dtype=np.float32) / 255.0


def _small(im: Image.Image) -> tuple[Image.Image, float]:
    w, h = im.size
    s = MAX_SIDE / max(w, h)
    if s >= 1:
        return im, 1.0
    return im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS), s


def _blur_box(a: np.ndarray, k: int, axis: int) -> np.ndarray:
    c = np.cumsum(np.pad(a, [(k // 2 + 1, k // 2) if i == axis else (0, 0) for i in range(2)], mode="edge"), axis=axis)
    n = a.shape[axis]
    hi = np.take(c, range(k, k + n), axis=axis)
    lo = np.take(c, range(0, n), axis=axis)
    return (hi - lo) / k


def _grad(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    gx = np.abs(np.diff(y, axis=1, prepend=y[:, :1]))
    gy = np.abs(np.diff(y, axis=0, prepend=y[:1, :]))
    return gx, gy


# ---------------------------------------------------------------- measurements

def _retention(y: np.ndarray, scale: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Per tile: how much edge strength survives a re-blur (sharp edges lose a lot, soft ones almost nothing), and how much edge there is at all.

    The re-blur size follows the picture size so a big picture and its thumbnail read alike."""
    k = 5 if max(y.shape) <= 1100 else 7
    gx, gy = _grad(y)
    g = gx + gy
    yb = _blur_box(_blur_box(y, k, 0), k, 1)
    bx, by = _grad(yb)
    gb = bx + by
    h, w = y.shape
    th, tw = h // TILE, w // TILE
    if th < 2 or tw < 2:
        return np.zeros(0), np.zeros(0)
    gt = g[:th * TILE, :tw * TILE].reshape(th, TILE, tw, TILE).sum(axis=(1, 3))
    bt = gb[:th * TILE, :tw * TILE].reshape(th, TILE, tw, TILE).sum(axis=(1, 3))
    ret = np.where(gt > 1e-6, np.clip((gt - bt) / np.maximum(gt, 1e-6), 0, 1), 0)
    strength = gt / (TILE * TILE)
    return ret.ravel(), strength.ravel()


def _noise_sigma(y: np.ndarray) -> tuple[float, float]:
    """Immerkaer's estimate on the flat parts only (in 0-255 units), and the share of the picture that was flat enough to trust."""
    a = y * 255.0
    if min(a.shape) < 8:
        return 0.0, 0.0
    c = (a[:-2, :-2] - 2 * a[:-2, 1:-1] + a[:-2, 2:] - 2 * a[1:-1, :-2] + 4 * a[1:-1, 1:-1] - 2 * a[1:-1, 2:] + a[2:, :-2] - 2 * a[2:, 1:-1] + a[2:, 2:])
    gx, gy = _grad(y)
    g = (gx + gy)[1:-1, 1:-1] * 255.0
    flat = g < np.percentile(g, 40)
    share = float(flat.mean())
    if flat.sum() < 400:
        return 0.0, 0.0
    sig = float(np.mean(np.abs(c[flat])) * np.sqrt(np.pi / 2) / 6.0)
    return sig, share


def _blockiness(y: np.ndarray) -> tuple[float, bool]:
    """How much stronger the steps are across 8-pixel borders than inside them (1.0 = no grid). Also whether the picture was big enough to tell."""
    h, w = y.shape
    if min(h, w) < 64:
        return 1.0, False
    dx = np.abs(np.diff(y, axis=1))
    dy = np.abs(np.diff(y, axis=0))
    out = []
    for d, axis_len in ((dx, w - 1), (dy, h - 1)):
        arr = d if d is dx else d.T
        n = (arr.shape[1] // 8) * 8
        cols = arr[:, :n]
        pos = np.arange(n) % 8
        edge = cols[:, pos == 7]
        inner = cols[:, pos == 3]      # the control step sits 4 pixels away, so a picture that was enlarged 2x or 4x (steps repeating every 2 or 4 pixels) does not read as a grid
        low = inner.mean(axis=0).mean() if inner.size else 0
        # use only the quiet steps, so real edges in the picture do not look like a grid
        cap = float(np.percentile(cols, 98))     # real edges land on borders and interiors alike (1 in 8 on a border), so they cancel; only the extreme tail is trimmed
        e = edge[edge <= cap]
        i = inner[inner <= cap]
        if e.size == 0 or i.size == 0 or i.mean() < 0.0015:     # a smooth gradient or a flat fill has no texture to show a grid in: say "can't tell", never guess
            continue
        out.append(float((e.mean() + 1e-4) / (i.mean() + 1e-4)))    # a tiny floor, so an all-flat block interior (heavy JPEG) reads as a strong grid instead of being skipped
    return (float(np.mean(out)) if out else 1.0), bool(out)


def aspect_name(w: int, h: int) -> str:
    r = w / h
    best = min(ASPECTS, key=lambda a: abs(np.log(r / a[1])))
    return best[0] if abs(np.log(r / best[1])) < 0.03 else f"{w}:{h}"


def _level(v: float, cuts: tuple[float, float], names=("Low", "Moderate", "High")) -> str:
    return names[0] if v < cuts[0] else names[1] if v < cuts[1] else names[2]


def analyze(path: str) -> dict:
    """The honest report: every row is a measurement of this picture, with how sure the measurement is."""
    im0 = _open(path)
    w, h = im0.size
    im, scale = _small(im0)
    y = _luma(im)
    rows: list[dict] = []

    # sharpness, with depth of field told apart from a soft picture
    ret, strength = _retention(y)
    textured = strength > 0.012 if ret.size else np.zeros(0, bool)
    faint = strength > 0.003 if ret.size else np.zeros(0, bool)      # counts the soft parts too, for telling depth of field from a soft picture
    if ret.size and textured.sum() >= 4:
        r = ret[textured]
        top = float(np.percentile(r, 85))
        low = float(np.percentile(r, 15))
        share_soft = float((ret[faint] < SOFT).mean()) if faint.sum() else 0.0
        if top < SOFT:
            s_level, note = "Soft", "No part of the picture has crisp edges; it looks out of focus or smoothed."
        elif top < OK:
            s_level, note = "Moderate", "The sharpest parts are only gently defined."
        else:
            s_level, note = "Good", "The sharpest area has crisp edges."
        dof = top >= OK and share_soft >= 0.25
        if dof:
            note += " Other areas are much softer: that looks like intended depth of field, not a defect."
        conf = "high" if textured.sum() >= 16 else "medium"
        rows.append({"id": "sharpness", "label": "Sharpness", "level": s_level, "value": round(top, 3), "confidence": conf, "note": note, "depth_of_field": bool(dof)})
        fine = float(np.std(y - _blur_box(_blur_box(y, 3, 0), 3, 1)))
    else:
        rows.append({"id": "sharpness", "label": "Sharpness", "level": "Unknown", "value": None, "confidence": "low", "note": "There is too little detail (a plain or very small picture) to judge focus.", "depth_of_field": False})
        fine = 0.0

    # noise
    sig, share = _noise_sigma(y)
    n_level = _level(sig, (1.6, 4.5))
    rows.append({"id": "noise", "label": "Noise", "level": n_level, "value": round(sig, 2), "confidence": "high" if share > 0.3 and min(y.shape) >= 256 else "low",
                 "note": {"Low": "Clean.", "Moderate": "Some grain in the flat areas.", "High": "Visible grain or speckle in the flat areas."}[n_level]})

    # compression blocks
    blk, known = _blockiness(np.asarray(im0.convert("L"), dtype=np.float32) / 255.0 if max(w, h) <= MAX_SIDE else y)
    if known and scale == 1.0:
        b_level = "Low" if blk < 1.12 else "Moderate" if blk < 1.3 else "High"
        rows.append({"id": "blocking", "label": "Compression blocks", "level": b_level, "value": round(blk, 3), "confidence": "medium",
                     "note": {"Low": "No 8×8 block pattern found.", "Moderate": "A faint 8×8 block pattern from JPEG compression.", "High": "A clear 8×8 block pattern from JPEG compression."}[b_level]})
    else:
        rows.append({"id": "blocking", "label": "Compression blocks", "level": "Unknown", "value": None, "confidence": "low",
                     "note": "Blocks can only be seen on a picture at its original size; this one was reduced or is too small to tell."})

    # clipping and exposure (measurements; whether they are wrong is the artist's call)
    hi_clip, lo_clip = float((y >= 0.98).mean()), float((y <= 0.02).mean())
    mean = float(y.mean())
    c_level = _level(max(hi_clip, lo_clip), (0.02, 0.08))
    cn = []
    if hi_clip >= 0.02: cn.append(f"{hi_clip * 100:.0f}% of the picture is pure white")
    if lo_clip >= 0.02: cn.append(f"{lo_clip * 100:.0f}% is pure black")
    rows.append({"id": "clipping", "label": "Clipped highlights and shadows", "level": c_level, "value": round(max(hi_clip, lo_clip), 3), "confidence": "high",
                 "note": ("; ".join(cn) + ". This may be intended (a bright sky, a night scene).") if cn else "Highlights and shadows keep their detail."})
    e_level = "Dark" if mean < 0.22 else "Bright" if mean > 0.78 else "Balanced"
    rows.append({"id": "exposure", "label": "Exposure", "level": e_level, "value": round(mean, 3), "confidence": "high",
                 "note": {"Dark": "Overall dark; fine if the scene is a night scene.", "Bright": "Overall bright.", "Balanced": "Evenly exposed."}[e_level]})
    spread = float(np.percentile(y, 95) - np.percentile(y, 5))
    k_level = "Low" if spread < 0.22 else "Moderate" if spread < 0.45 else "Good"
    rows.append({"id": "contrast", "label": "Contrast", "level": k_level, "value": round(spread, 3), "confidence": "high",
                 "note": {"Low": "The tones sit close together: flat or hazy.", "Moderate": "A moderate tonal range.", "Good": "A full tonal range."}[k_level]})
    rows.append({"id": "texture", "label": "Fine texture", "level": "Rich" if fine > 0.03 else "Moderate" if fine > 0.012 else "Smooth", "value": round(fine, 4),
                 "confidence": "medium", "note": "The amount of fine detail. A smooth look can be a style choice (clean 3D, anime)."})

    low_res = min(w, h) < 720
    problems = [r["id"] for r in rows if (r["id"] == "sharpness" and r["level"] == "Soft") or (r["id"] == "noise" and r["level"] == "High") or (r["id"] == "blocking" and r["level"] == "High")]
    mild = [r["id"] for r in rows if (r["id"] == "sharpness" and r["level"] == "Moderate") or (r["id"] == "noise" and r["level"] == "Moderate") or (r["id"] == "blocking" and r["level"] == "Moderate")]
    if problems:
        verdict, action = "recommended", "Clean Enhance is recommended before animating."
    elif mild:
        verdict, action = "optional", "Optional: Clean Enhance can tidy this up."
    else:
        verdict, action = "ok", "Ready to animate. No clean-up needed."
    if low_res:
        action += f" The picture is small ({w}×{h}); an upscaler gives more than a clean-up here."
    return {
        "width": w, "height": h, "aspect": aspect_name(w, h), "format": (im0.format or "").upper(), "analysed_at": f"{im.size[0]}×{im.size[1]}", "reduced": scale < 1.0,
        "rows": rows, "verdict": verdict, "action": action, "low_resolution": low_res,
        "not_assessed": ["Faces and hands (needs an image model)", "Whether the picture suits the story"],
    }


# ---------------------------------------------------------------- clean enhance

def _min_max(a: np.ndarray, r: int = 2) -> tuple[np.ndarray, np.ndarray]:
    lo = hi = a
    for axis in (0, 1):
        stack_lo, stack_hi = [], []
        for s in range(-r, r + 1):
            sh = np.roll(lo, s, axis=axis)
            stack_lo.append(sh)
            stack_hi.append(np.roll(hi, s, axis=axis))
        lo, hi = np.min(stack_lo, axis=0), np.max(stack_hi, axis=0)
    return lo, hi


def _deblock(y: np.ndarray, amount: float) -> np.ndarray:
    out = y.copy()
    for axis in (1, 0):
        a = out if axis == 1 else out.T
        n = a.shape[1]
        for c in range(7, n - 1, 8):
            d = a[:, c + 1] - a[:, c]
            m = np.abs(d) < 0.1                      # a small step on a block border is a seam; a big one is a real edge
            a[m, c] += d[m] * 0.45 * amount
            a[m, c + 1] -= d[m] * 0.45 * amount
        if axis == 0:
            out = a.T
    return out


def enhance_image(im: Image.Image, strength: float = 0.5, report: dict | None = None) -> Image.Image:
    strength = float(min(1.0, max(0.0, strength)))
    alpha = im.getchannel("A") if im.mode in ("RGBA", "LA") else None
    rgb = im.convert("RGB")
    ycc = np.asarray(rgb.convert("YCbCr"), dtype=np.float32) / 255.0
    y, cb, cr = ycc[..., 0].copy(), ycc[..., 1], ycc[..., 2]
    w, h = rgb.size
    rep = report or analyze_array(y, w, h)
    sig = rep.get("noise", 0.0)
    ys = np.asarray(Image.fromarray((np.clip(y, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5)), dtype=np.float32) / 255.0   # grain must not look like an edge
    gx, gy = _grad(ys)
    edge = np.clip((gx + gy) / 0.04, 0, 1)                                # 0 flat .. 1 strong edge

    # 1. noise: smooth the flat parts and the colour, leave the edges alone
    if sig > 1.2 and strength > 0:
        base = min(1.0, (sig - 1.0) / 4.0) * (0.5 + 0.5 * strength)
        u8 = Image.fromarray((np.clip(y, 0, 1) * 255).astype(np.uint8))
        smooth = 0.5 * np.asarray(u8.filter(ImageFilter.MedianFilter(3)), dtype=np.float32) / 255.0 + 0.5 * np.asarray(u8.filter(ImageFilter.GaussianBlur(1.1)), dtype=np.float32) / 255.0
        wt = base * (1 - edge) ** 2
        y = y * (1 - wt) + smooth * wt
    for ch in (cb, cr):
        if sig > 1.2 and strength > 0:
            bl = _blur_box(_blur_box(ch, 3, 0), 3, 1)
            ch[...] = ch * (1 - 0.5 * strength) + bl * 0.5 * strength
    # 2. compression blocks
    if rep.get("blocking", 1.0) > 1.12 and strength > 0:
        y = _deblock(y, min(1.0, strength + 0.2))
    # 3. sharpening that cannot make halos: boosted, then held inside the local range
    r = max(0.7, max(w, h) / 1800.0)
    blur = np.asarray(Image.fromarray((np.clip(y, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(r)), dtype=np.float32) / 255.0
    detail = y - blur
    floor = max(0.004, sig * 1.5 / 255.0)
    detail = np.where(np.abs(detail) > floor, detail, 0)                   # grain is not detail: do not sharpen it
    calm = max(0.3, 1.0 - sig / 8.0) * (0.2 if rep.get("blocking", 1.0) > 1.15 else 1.0)    # grain and block seams are not detail: sharpen them less
    sharp = y + detail * (0.35 + 1.1 * strength) * calm
    lo, hi = _min_max(y, 2)
    sharp = np.clip(sharp, lo - 0.02, hi + 0.02)
    # 4. a little local contrast in the midtones
    big = np.asarray(Image.fromarray((np.clip(y, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(max(8, max(w, h) / 60))), dtype=np.float32) / 255.0
    mid = 1 - np.abs(y - 0.5) * 2
    sharp = sharp + (y - big) * 0.18 * strength * np.clip(mid, 0, 1)
    out = np.stack([np.clip(sharp, 0, 1), np.clip(cb, 0, 1), np.clip(cr, 0, 1)], axis=-1)
    res = Image.fromarray((out * 255 + 0.5).astype(np.uint8), "YCbCr").convert("RGB")
    if alpha is not None:
        res.putalpha(alpha)
    return res


def analyze_array(y: np.ndarray, w: int, h: int) -> dict:
    sig, _ = _noise_sigma(y)
    blk, known = _blockiness(y)
    return {"noise": sig, "blocking": blk if known else 1.0}


def _sha(path: str) -> str:
    hs = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            hs.update(chunk)
    return hs.hexdigest()


# ---------------------------------------------------------------- project plumbing

def _ledger(d: str) -> list[dict]:
    data = R._read(os.path.join(d, LEDGER), []) or []
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def _local(d: str, ref: str) -> str:
    rel = ref[len(R.PROJECT_MEDIA):] if ref.startswith(R.PROJECT_MEDIA) else ref
    path = os.path.normpath(os.path.join(d, rel))
    if not path.startswith(os.path.normpath(d) + os.sep):
        raise SystemExit("That file is not inside the project.")
    if not os.path.isfile(path):
        raise SystemExit("That picture isn't in the project any more.")
    return path


def keyframe_ref(d: str, shot: str) -> tuple[str, str]:
    """(plan name, the shot's approved keyframe reference)."""
    plan = R._load_plan(d)[0]
    ref = ((R._read(os.path.join(d, "keyframes.json"), {}) or {}).get(plan) or {}).get(shot)
    if not ref:
        raise SystemExit("This shot has no approved keyframe yet.")
    return plan, ref


def check(d: str, shot: str) -> dict:
    plan, ref = keyframe_ref(d, shot)
    return {"shot": shot, "ref": ref, "report": analyze(_local(d, ref))}


def enhance(d: str, shot: str, strength: float = 0.5) -> dict:
    plan, ref = keyframe_ref(d, shot)
    src = _local(d, ref)
    before_sha = _sha(src)
    im = _open(src)
    before = analyze(src)
    out_im = enhance_image(im, strength)
    folder = os.path.join(d, FOLDER)
    os.makedirs(folder, exist_ok=True)
    item_id = uuid.uuid4().hex[:10]
    out = os.path.join(folder, f"{file_name(shot)}_{item_id}_clean.png")
    kw = {}
    if im.info.get("icc_profile"):
        kw["icc_profile"] = im.info["icc_profile"]
    tmp = f"{out}.{os.getpid()}.tmp"
    out_im.save(tmp, format="PNG", **kw)
    os.replace(tmp, out)
    after = analyze(out)
    if _sha(src) != before_sha:
        raise SystemExit("The original changed while it was being cleaned. Nothing was saved.")
    item = {"id": item_id, "shot": shot, "plan": plan, "source": ref, "source_sha256": before_sha, "output": R.PROJECT_MEDIA + os.path.relpath(out, d).replace(os.sep, "/"),
            "strength": strength, "state": "ready", "created": int(time.time()), "size": [out_im.size[0], out_im.size[1]], "before": _brief(before), "after": _brief(after)}
    items = _ledger(d)
    items.append(item)
    R._write(os.path.join(d, LEDGER), items[-200:])
    return {**item, "source_path": src, "output_path": out, "before_report": before, "after_report": after, "note": "Clean Enhance tidies and sharpens what is already there. It does not add new detail."}


def _brief(rep: dict) -> dict:
    return {r["id"]: {"level": r["level"], "value": r["value"]} for r in rep["rows"]}

# ---- local super-resolution (optional; needs the user's own realesrgan-ncnn-vulkan install) ----

UPSCALE_TIMEOUT = 1800
MAX_OUT_SIDE = 8192
TILE_SIZE = 200          # pixels per tile: keeps memory low (a 12 GB card is comfortable; 0 would let the tool choose)
INSTALL_HELP = ("Local upscaling needs the free Real-ESRGAN ncnn-vulkan tool. Download it from the Real-ESRGAN project's releases, unzip it, then set the FILMCRAFTER_REALESRGAN "
                "environment variable to the realesrgan-ncnn-vulkan program (its models folder must sit next to it), or put the folder at engine/tools/realesrgan. Nothing is downloaded for you.")


def local_tool() -> str | None:
    """The upscaler program, if one is installed. Looked up only in places the user controls."""
    names = ("realesrgan-ncnn-vulkan.exe", "realesrgan-ncnn-vulkan")
    cands = [os.environ.get("FILMCRAFTER_REALESRGAN", "")]
    here = os.path.dirname(os.path.abspath(__file__))
    cands += [os.path.join(here, "..", "tools", "realesrgan", n) for n in names]
    cands += [shutil.which(n) or "" for n in names]
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def upscale_status() -> dict:
    exe = local_tool()
    if not exe:
        return {"available": False, "models": [], "help": INSTALL_HELP}
    mdir = os.path.join(os.path.dirname(exe), "models")
    models = sorted(f[:-6] for f in os.listdir(mdir) if f.endswith(".param")) if os.path.isdir(mdir) else []
    return {"available": bool(models), "tool": exe, "models": models, "tile": TILE_SIZE,
            "help": "" if models else "The tool was found but its models folder is empty. Put the model files (.param and .bin) in the models folder next to it."}


def _pick_model(models: list[str], model: str | None, anime: bool) -> str:
    if model:
        if model not in models:
            raise SystemExit("That upscaling model is not installed.")
        return model
    want = ["realesr-animevideov3", "realesrgan-x4plus-anime"] if anime else ["realesrgan-x4plus", "realesr-animevideov3"]
    for m in want:
        if m in models:
            return m
    return models[0]


def upscale(d: str, shot: str, scale: int = 2, model: str | None = None, anime: bool = False) -> dict:
    """Make a larger copy of a shot's keyframe with the local tool. The original is never written; "apply" and "revert" work as for Clean Enhance."""
    if scale not in (2, 3, 4):
        raise SystemExit("Choose 2x, 3x or 4x.")
    st = upscale_status()
    if not st["available"]:
        raise SystemExit(st["help"])
    plan, ref = keyframe_ref(d, shot)
    src = _local(d, ref)
    before_sha = _sha(src)
    im = _open(src)
    if max(im.size) * scale > MAX_OUT_SIDE:
        raise SystemExit(f"{scale}x would make this picture larger than {MAX_OUT_SIDE} pixels on a side. Choose a smaller factor.")
    name = _pick_model(st["models"], model, anime)
    folder = os.path.join(d, FOLDER)
    os.makedirs(folder, exist_ok=True)
    item_id = uuid.uuid4().hex[:10]
    out = os.path.join(folder, f"{file_name(shot)}_{item_id}_up{scale}x.png")
    tmp = f"{out}.{os.getpid()}.tmp.png"
    cmd = [st["tool"], "-i", src, "-o", tmp, "-n", name, "-s", str(scale), "-t", str(TILE_SIZE), "-f", "png"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=UPSCALE_TIMEOUT, cwd=os.path.dirname(st["tool"]))
    except subprocess.TimeoutExpired:
        raise SystemExit("The upscaler took too long and was stopped. Nothing was changed.")
    except OSError as e:
        raise SystemExit(f"The upscaler could not start: {e}")
    if proc.returncode != 0 or not os.path.isfile(tmp):
        if os.path.isfile(tmp):
            os.remove(tmp)
        raise SystemExit("The upscaler did not finish (the graphics card may be unsupported or out of memory). Nothing was changed.")
    try:
        with Image.open(tmp) as chk:
            chk.verify()
        os.replace(tmp, out)
    except Exception:
        if os.path.isfile(tmp):
            os.remove(tmp)
        raise SystemExit("The upscaler made a file that could not be read. Nothing was changed.")
    if _sha(src) != before_sha:
        raise SystemExit("The original changed while it was being upscaled. Nothing was saved.")
    out_im = _open(out)
    if out_im.size[0] < im.size[0] or out_im.size[1] < im.size[1]:
        os.remove(out)
        raise SystemExit("The upscaler returned a smaller picture. Nothing was changed.")
    before, after = analyze(src), analyze(out)
    item = {"id": item_id, "shot": shot, "plan": plan, "source": ref, "source_sha256": before_sha, "output": R.PROJECT_MEDIA + os.path.relpath(out, d).replace(os.sep, "/"),
            "method": "local_upscale", "model": name, "scale": scale, "strength": 0, "state": "ready", "created": int(time.time()), "size": [out_im.size[0], out_im.size[1]],
            "before": _brief(before), "after": _brief(after)}
    items = _ledger(d)
    items.append(item)
    R._write(os.path.join(d, LEDGER), items[-200:])
    return {**item, "source_path": src, "output_path": out, "before_report": before, "after_report": after,
            "note": f"Made {out_im.size[0]}x{out_im.size[1]} from {im.size[0]}x{im.size[1]} on this computer with {name}. A model invents plausible detail: look closely at faces, hands and text before using it."}


MASTERS = "masters.json"


def master_set(d: str, item_id: str) -> dict:
    items = _ledger(d)
    it = next((x for x in items if x.get("id") == item_id), None)
    if not it:
        raise SystemExit("That picture is not available.")
    _local(d, it["output"])
    plan, shot = it["plan"], it["shot"]
    cur = (R._read(os.path.join(d, "keyframes.json"), {}) or {}).get(plan, {}).get(shot)
    if cur != it["source"]:
        raise SystemExit("This shot's keyframe was changed after the picture was made. Make it again from the current keyframe.")
    m = R._read(os.path.join(d, MASTERS), {}) or {}
    m.setdefault(plan, {})[shot] = {"ref": it["output"], "source": it["source"], "item": item_id, "method": it.get("method", "clean"), "size": it.get("size")}
    R._write(os.path.join(d, MASTERS), m)
    return {"shot": shot, "master": it["output"], "keyframe": it["source"]}


def master_clear(d: str, shot: str) -> dict:
    m = R._read(os.path.join(d, MASTERS), {}) or {}
    gone = [p for p in list(m) if m[p].pop(shot, None) is not None]
    for p in list(m):
        if not m[p]:
            del m[p]
    R._write(os.path.join(d, MASTERS), m)
    return {"shot": shot, "cleared": bool(gone)}


def masters(d: str) -> dict:
    return {"masters": R._read(os.path.join(d, MASTERS), {}) or {}}


def apply(d: str, item_id: str) -> dict:
    items = _ledger(d)
    it = next((x for x in items if x.get("id") == item_id and x.get("state") in ("ready", "reverted")), None)
    if not it:
        raise SystemExit("That cleaned picture is not available.")
    _local(d, it["output"])
    path = os.path.join(d, "keyframes.json")
    data = R._read(path, {}) or {}
    cur = (data.get(it["plan"]) or {}).get(it["shot"])
    if cur != it["source"] and cur != it["output"]:
        raise SystemExit("This shot's keyframe was changed after the check. Run the check again.")
    data.setdefault(it["plan"], {})[it["shot"]] = it["output"]
    R._write(path, data)
    it["state"] = "applied"
    R._write(os.path.join(d, LEDGER), items)
    return {"shot": it["shot"], "using": it["output"]}


def revert(d: str, shot: str) -> dict:
    items = _ledger(d)
    it = next((x for x in reversed(items) if x.get("shot") == shot and x.get("state") == "applied"), None)
    if not it:
        raise SystemExit("There is no cleaned picture in use for this shot.")
    path = os.path.join(d, "keyframes.json")
    data = R._read(path, {}) or {}
    data.setdefault(it["plan"], {})[shot] = it["source"]
    R._write(path, data)
    it["state"] = "reverted"
    R._write(os.path.join(d, LEDGER), items)
    return {"shot": shot, "restored": it["source"]}


def status(d: str, shot: str | None = None) -> dict:
    return {"items": [x for x in _ledger(d) if not shot or x.get("shot") == shot][-30:]}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="filmcrafter-fidelity")
    ap.add_argument("action", choices=["check", "enhance", "apply", "revert", "status", "upscale_status", "upscale", "master_set", "master_clear", "masters"])
    ap.add_argument("project")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data)
        if a.action == "check": res = check(a.project, str(x["shot"]))
        elif a.action == "enhance": res = enhance(a.project, str(x["shot"]), float(x.get("strength", 0.5)))
        elif a.action == "upscale_status": res = upscale_status()
        elif a.action == "upscale": res = upscale(a.project, str(x["shot"]), int(x.get("scale", 2)), x.get("model"), bool(x.get("anime", False)))
        elif a.action == "master_set": res = master_set(a.project, str(x["id"]))
        elif a.action == "master_clear": res = master_clear(a.project, str(x["shot"]))
        elif a.action == "masters": res = masters(a.project)
        elif a.action == "apply": res = apply(a.project, str(x["id"]))
        elif a.action == "revert": res = revert(a.project, str(x["shot"]))
        else: res = status(a.project, x.get("shot"))
        print(json.dumps({"event": "result", "data": res}, ensure_ascii=False), flush=True)
        return 0
    except SystemExit as e:
        print(json.dumps({"event": "error", "message": str(e)}), flush=True)
        return 1
    except Exception as e:
        from .errtext import plain
        print(json.dumps({"event": "error", "message": plain(e)}), flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
