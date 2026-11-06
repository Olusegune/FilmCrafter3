"""The geometry of a WorldLock set: world coordinates, a pinhole camera, the picture a flat layer makes, and the state of the set over time. Pure numpy and Pillow: no film, no files of the film, no network
(reusable by any application, Pulseframe included).

Conventions, fixed and written down because everything else depends on them:

* **World.** Metres. X is to the right, Y is up, Z is forward into the set. The origin is where the set's author put it (usually the middle of the floor at the front). Right-handed when seen with Y up.
* **A layer** (a flat picture standing in the set) faces back toward the camera's rest direction: it lies in a plane of constant Z. Its anchor is the middle of its bottom edge, at (x, y, z); it is `width` metres
  wide and `height` metres tall.
* **A camera** has a position (x, y, z), a *yaw* (degrees, turning right is positive, 0 looks along +Z), a *pitch* (degrees, looking up is positive) and a horizontal field of view in degrees. Roll is not used.
* **Projection** is a pinhole: a point is moved into camera space (translate by the camera position, undo the yaw, undo the pitch), and lands at `sx = W/2 + f * xc / zc`, `sy = H/2 - f * yc / zc` with
  `f = (W/2) / tan(fov/2)`. A point at or behind the near plane (0.05 m) is not drawn.

The same inputs always give the same outputs: there is no randomness and no hidden state.

What this is not: it is not a 3D renderer. A layer is a flat picture, so it has no sides and nothing behind it. Moving the camera shows exactly what the pictures cover and nothing more; where they do not
cover the view, the gap is reported (`coverage`) and never filled in with invented picture.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image

NEAR = 0.05


def _num(x, lo: float, hi: float, default: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if v != v or v in (float("inf"), float("-inf")):
        return default
    return min(hi, max(lo, v))


# ---------------------------------------------------------------- the camera

def focal_px(width: int, fov_deg: float) -> float:
    return (width / 2.0) / math.tan(math.radians(fov_deg) / 2.0)


def to_camera(p: tuple[float, float, float], cam: dict) -> tuple[float, float, float]:
    """A world point in the camera's own space (x right, y up, z forward)."""
    x, y, z = p[0] - cam["x"], p[1] - cam["y"], p[2] - cam["z"]
    yaw, pitch = math.radians(cam.get("yaw", 0.0)), math.radians(cam.get("pitch", 0.0))
    cy, sy = math.cos(yaw), math.sin(yaw)
    x, z = x * cy - z * sy, x * sy + z * cy                    # undo the yaw (turn the world the other way)
    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = y * cp - z * sp, y * sp + z * cp                    # undo the pitch
    return x, y, z


def project(p: tuple[float, float, float], cam: dict, size: tuple[int, int]) -> tuple[float, float, float] | None:
    """A world point on a picture of `size`: (sx, sy, depth), or None when it is at or behind the near plane."""
    W, H = size
    xc, yc, zc = to_camera(p, cam)
    if zc <= NEAR:
        return None
    f = focal_px(W, cam.get("fov", 50.0))
    return (W / 2.0 + f * xc / zc, H / 2.0 - f * yc / zc, zc)


def layer_corners(a: dict) -> list[tuple[float, float, float]]:
    """The four corners of a layer in the world: top-left, top-right, bottom-right, bottom-left as seen from the camera at rest."""
    x, y, z, w, h = a["x"], a["y"], a["z"], a["width"], a["height"]
    return [(x - w / 2, y + h, z), (x + w / 2, y + h, z), (x + w / 2, y, z), (x - w / 2, y, z)]


def homography(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> np.ndarray:
    """The 3x3 matrix that carries the four `src` points onto the four `dst` points."""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    h = np.linalg.solve(np.array(A, dtype=np.float64), np.array(b, dtype=np.float64))
    return np.append(h, 1.0).reshape(3, 3)


def draw_layer(rgba: np.ndarray, a: dict, cam: dict, size: tuple[int, int]) -> np.ndarray | None:
    """One layer as the camera sees it: a straight-alpha RGBA picture the size of the view (premultiplied while it is resampled, so edges have no halo), or None when any corner is behind the
    camera's near plane or the layer is wholly outside the view."""
    W, H = size
    pts = [project(c, cam, size) for c in layer_corners(a)]
    if any(p is None for p in pts):
        return None
    dst = [(p[0], p[1]) for p in pts]
    xs, ys = [p[0] for p in dst], [p[1] for p in dst]
    if max(xs) < 0 or min(xs) > W or max(ys) < 0 or min(ys) > H or (max(xs) - min(xs)) > 20 * W or (max(ys) - min(ys)) > 20 * H:
        return None
    h, w = rgba.shape[:2]
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    Hm = homography(dst, src)                                                                      # output pixel -> source pixel (what PIL asks for)
    coeffs = tuple(float(v) for v in (Hm / Hm[2, 2]).flatten()[:8])
    pm = rgba.copy()
    pm[..., :3] *= pm[..., 3:4]
    out = []
    for i in range(4):
        ch = Image.fromarray(np.ascontiguousarray(pm[..., i], dtype=np.float32), "F")
        out.append(np.asarray(ch.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BILINEAR), dtype=np.float32))
    res = np.stack(out, axis=-1)
    al = np.clip(res[..., 3], 0, 1)
    res[..., :3] = np.where(al[..., None] > 1e-4, res[..., :3] / np.maximum(al[..., None], 1e-4), 0.0)
    res[..., 3] = al
    return np.clip(res, 0, 1)


def coverage(alpha_layers: list[np.ndarray], size: tuple[int, int]) -> float:
    """The share of the view covered by at least some picture (1.0 means nothing is missing). Pictures stack, so a pixel's cover is 1 - the product of what each layer leaves uncovered."""
    W, H = size
    left = np.ones((H, W), np.float32)
    for a in alpha_layers:
        left *= 1.0 - a
    return float(1.0 - left.mean())


def uncovered(alpha_layers: list[np.ndarray], size: tuple[int, int], threshold: float = 0.02) -> float:
    """The share of the view where the set has (almost) nothing: the gap a camera move has exposed."""
    W, H = size
    left = np.ones((H, W), np.float32)
    for a in alpha_layers:
        left *= 1.0 - a
    return float((left > 1.0 - threshold).mean())


# ---------------------------------------------------------------- the state of the set over time

def state_at(assets: list[dict], characters: list[dict], events: list[dict], shot_order: list[str], shot: str | None) -> tuple[list[dict], list[dict]]:
    """The assets and characters as they stand at the start of `shot`: the set as built, then every event of an earlier shot (and of this shot, when `inclusive`) applied in shot order. The set's own
    definition is never changed; this returns copies. An event names an asset or a character and either moves it (`to`), gives it a state ("on the floor"), removes it or makes it appear."""
    pos = {s: i for i, s in enumerate(shot_order)}
    cut = pos.get(shot, len(shot_order)) if shot is not None else len(shot_order)
    a = {x["id"]: dict(x) for x in assets}
    c = {x["id"]: dict(x) for x in characters}
    for e in sorted((e for e in events if pos.get(e.get("shot"), 1 << 30) < cut), key=lambda e: (pos.get(e.get("shot"), 1 << 30), e.get("order", 0))):
        pool = a if e.get("asset") in a else c if e.get("character") in c else None
        target = e.get("asset") if pool is a else e.get("character")
        if pool is None or target not in pool:
            continue
        item = pool[target]
        kind = e.get("kind")
        if kind == "remove":
            item["present"] = False
        elif kind == "appear":
            item["present"] = True
        if isinstance(e.get("to"), dict):
            for k in ("x", "y", "z", "facing"):
                if k in e["to"]:
                    item[k] = e["to"][k]
        if e.get("state"):
            item["state"] = e["state"]
    return [x for x in a.values() if x.get("present", True)], [x for x in c.values() if x.get("present", True)]


def side_of_axis(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> int:
    """Which side of the line from A to B the point P is on, in the floor plan (x, z): +1, -1, or 0 on the line."""
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    return 1 if cross > 1e-9 else -1 if cross < -1e-9 else 0
