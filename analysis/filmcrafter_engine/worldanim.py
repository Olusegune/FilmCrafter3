"""Animating a WorldLock set: a timeline of keyframes for the camera, for models, for lights and for the sky, rendered frame by frame with the set's own 3D renderer into an H.264 video.

Nothing in the set is changed: each frame is made from a copy of the set with that moment's values put in. A track is a list of keys `{t, <fields>, ease}` (seconds; `ease` is linear, smooth or hold, as for
layer keyframes). Between two keys a number moves the way the earlier key says; colours are blended in linear light. Before the first key and after the last, the value is held.

  camera   x, y, z, yaw, pitch, fov                       (the first key's fields not given fall back to the set's first saved camera)
  models   {model id or name: [{t, x, y, z, yaw, pitch, roll, scale, visible}]}
  lights   {light id or name: [{t, azimuth, elevation, intensity, colour}]}
  sky      [{t, top, horizon, fog}]
  ambient  [{t, v}]                                          how much fill light reaches the shadows (0 to 1)
  shake    [{t0, t1, amount (metres), turn (degrees), hz}]   a deterministic hand-held or earthquake shake added to the camera

Deterministic: the same spec gives the same frames. Rendering is on the CPU and slow in proportion to frames, size and triangles; progress is reported and a cancel request stops it at the next frame.
"""
from __future__ import annotations

import copy
import json
import math
import os
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image

from . import keying as K
from . import vpstudio as V
from . import worldlock as WL

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
MAX_FRAMES = 2400
EASES = ("linear", "smooth", "hold")


def emit(**kw) -> None:
    V.emit(**kw)


def _ease(u: float, how: str) -> float:
    return u * u * (3 - 2 * u) if how == "smooth" else u


def sample(keys: list[dict], t: float, field: str):
    """The value of one field of a track at time `t`: held before the first key and after the last; between keys it moves as the earlier key's `ease` says. None when no key sets it. Numbers are blended;
    colours (`#rrggbb`) are blended in linear light; anything else (visible) holds the earlier key's value."""
    pts = [(k["t"], k[field], k.get("ease", "smooth")) for k in sorted((k for k in keys if isinstance(k, dict) and "t" in k and field in k), key=lambda k: k["t"])]
    if not pts:
        return None
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, v0, ease), (t1, v1, _) in zip(pts, pts[1:]):
        if t < t1:
            if ease == "hold":
                return v0
            u = _ease((t - t0) / max(t1 - t0, 1e-9), ease)
            if isinstance(v0, (int, float)) and isinstance(v1, (int, float)) and not isinstance(v0, bool):
                return v0 + (v1 - v0) * u
            if isinstance(v0, str) and isinstance(v1, str) and v0.startswith("#") and v1.startswith("#") and len(v0) == len(v1) == 7:
                a = K.to_linear(np.array([int(v0[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]))
                b = K.to_linear(np.array([int(v1[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]))
                c = np.clip(K.to_srgb(a + (b - a) * u), 0, 1)
                return "#" + "".join(f"{int(round(x * 255)):02x}" for x in c)
            return v0
    return pts[-1][1]


def shake_at(shakes: list[dict], t: float) -> dict:
    """A deterministic camera shake at time `t`: the sum of the active bursts, each a few sines of different speeds so it does not look like a single wobble, fading in and out over a tenth of a second."""
    out = {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "pitch": 0.0}
    for i, s in enumerate(shakes or []):
        t0, t1 = float(s.get("t0", 0)), float(s.get("t1", 0))
        if not (t0 <= t <= t1) or t1 <= t0:
            continue
        edge = min(1.0, (t - t0) / 0.1, (t1 - t) / 0.1)
        a, turn, hz = float(s.get("amount", 0.05)), float(s.get("turn", 0.3)), float(s.get("hz", 9.0))
        ph = i * 1.7
        w = 2 * math.pi * hz * t
        out["x"] += edge * a * (math.sin(w + ph) * 0.6 + math.sin(w * 1.9 + ph * 2) * 0.4)
        out["y"] += edge * a * (math.sin(w * 1.3 + ph + 1) * 0.6 + math.sin(w * 2.3 + ph) * 0.4)
        out["z"] += edge * a * 0.3 * math.sin(w * 0.7 + ph)
        out["yaw"] += edge * turn * math.sin(w * 1.1 + ph + 2)
        out["pitch"] += edge * turn * math.sin(w * 1.5 + ph + 3)
    return out


def state_at(s: dict, spec: dict, t: float) -> tuple[dict, dict]:
    """The set (a copy, with this moment's model, light and sky values in) and the camera at time `t`."""
    s2 = copy.deepcopy(s)
    for key, tr in (spec.get("models") or {}).items():
        m = next((m for m in s2["models"] if m["id"] == key or m["name"] == key), None)
        if not m or not isinstance(tr, list):
            continue
        for f in ("x", "y", "z", "yaw", "pitch", "roll", "scale", "visible"):
            v = sample(tr, t, f)
            if v is not None:
                m[f] = v
    for key, tr in (spec.get("lights") or {}).items():
        l = next((l for l in s2["lights"] if l["id"] == key or l["name"] == key), None)
        if not l or not isinstance(tr, list):
            continue
        for f in ("azimuth", "elevation", "intensity", "colour"):
            v = sample(tr, t, f)
            if v is not None:
                l[f] = v
    amb = spec.get("ambient")
    if isinstance(amb, list):
        v = sample(amb, t, "v")
        if v is not None:
            s2["ambient"] = float(v)
    sk = spec.get("sky")
    if isinstance(sk, list):
        for f in ("top", "horizon", "fog"):
            v = sample(sk, t, f)
            if v is not None:
                s2["sky"][f] = v
    base = (s["cameras"][0] if s["cameras"] else {"x": 0, "y": 1.6, "z": 0, "yaw": 0, "pitch": 0, "fov": 50})
    cam = {k: base.get(k, 0.0) for k in ("x", "y", "z", "yaw", "pitch", "fov")}
    tr = (spec.get("camera") or [])
    for f in cam:
        v = sample(tr, t, f) if isinstance(tr, list) else None
        if v is not None:
            cam[f] = v
    sh = shake_at(spec.get("shake") or [], t)
    for f in ("x", "y", "z", "yaw", "pitch"):
        cam[f] += sh[f]
    cam["pitch"] = max(-85.0, min(85.0, cam["pitch"]))
    return s2, cam


def clean_spec(spec: dict) -> dict:
    sp = spec if isinstance(spec, dict) else {}
    fps = V._n(sp.get("fps"), 1, 30, 12.0)
    secs = V._n(sp.get("seconds"), 0.5, 600, 4.0)
    w = int(V._n((sp.get("size") or [640, 360])[0] if isinstance(sp.get("size"), list) and len(sp["size"]) == 2 else 640, 64, 1920, 640)) // 2 * 2
    h = int(V._n((sp.get("size") or [640, 360])[1] if isinstance(sp.get("size"), list) and len(sp["size"]) == 2 else 360, 64, 1080, 360)) // 2 * 2
    n = int(round(fps * secs))
    if n > MAX_FRAMES:
        raise SystemExit(f"That is {n} frames: at most {MAX_FRAMES} in one render. Render it in parts.")
    return {**sp, "fps": fps, "seconds": secs, "size": [w, h], "frames": n}


def render_frame(d: str, s: dict, spec: dict, i: int) -> np.ndarray:
    t = i / spec["fps"]
    s2, cam = state_at(s, spec, t)
    out, _, _, _ = WL._draw(d, s2, cam, tuple(spec["size"]), None)
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


def _worker(args):
    d, s, spec, i = args
    return i, render_frame(d, s, spec, i)


def render_sequence(d: str, sid: str, spec: dict, *, workers: int = 1) -> dict:
    """Render the animation to an H.264 MP4 under `worldlock/<set>/animations/`. `workers` frames are drawn at once (processes) when more than 1. Returns the file, the frame count and the time taken."""
    V._film(d)
    s = WL._load(d, sid)
    sp = clean_spec(spec)
    name = V._t(sp.get("name") or "animation", 40).replace(" ", "-") or "animation"
    rel = f"worldlock/{sid}/animations/{name}-{int(time.time())}.mp4"
    full = V._inside(d, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    from .export import ffmpeg
    W, H = sp["size"]
    proc = subprocess.Popen([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{sp['fps']}", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf",
                             str(int(V._n(sp.get("crf"), 10, 35, 17))), "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart", full], stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=NO_WINDOW)
    t0 = time.time()
    cancel = os.path.join(V._inside(d, f"worldlock/{sid}"), "cancel.flag")
    try:
        os.remove(cancel)
    except OSError:
        pass
    try:
        if workers > 1:
            import multiprocessing as mp
            with mp.get_context("spawn").Pool(workers) as pool:
                for i, frame in pool.imap(_worker, ((d, s, sp, i) for i in range(sp["frames"])), chunksize=2):
                    if os.path.exists(cancel):
                        raise SystemExit(f"Stopped at frame {i} of {sp['frames']}. The half-made video was removed.")
                    proc.stdin.write(frame.tobytes())
                    if i % 6 == 0:
                        emit(event="progress", stage="drawing frames", progress=round(0.97 * i / sp["frames"], 3))
        else:
            for i in range(sp["frames"]):
                if os.path.exists(cancel):
                    raise SystemExit(f"Stopped at frame {i} of {sp['frames']}. The half-made video was removed.")
                proc.stdin.write(render_frame(d, s, sp, i).tobytes())
                if i % 4 == 0:
                    emit(event="progress", stage="drawing frames", progress=round(0.97 * i / sp["frames"], 3))
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait() != 0 or not os.path.isfile(full):
            raise SystemExit("The video could not be written: " + (err.strip().splitlines()[-1] if err.strip() else "the video tool stopped."))
    except BaseException:
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.kill()
        proc.wait()
        try:
            os.remove(full)
        except OSError:
            pass
        raise
    emit(event="progress", stage="done", progress=1.0)
    return {"file": rel, "path": full, "frames": sp["frames"], "fps": sp["fps"], "seconds": round(sp["frames"] / sp["fps"], 3), "size": sp["size"], "took": round(time.time() - t0, 1)}


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["render", "cancel"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        if a.action == "cancel":
            V._film(d)
            WL._load(d, x.get("set", ""))
            open(os.path.join(V._inside(d, f"worldlock/{x['set']}"), "cancel.flag"), "w").write(str(time.time()))
            res = {"cancelled": True}
        else:
            res = render_sequence(d, x.get("set", ""), x.get("spec") or {}, workers=int(V._n(x.get("workers"), 1, 16, 1)))
        emit(event="result", data=res)
        return 0
    except SystemExit as e:
        emit(event="error", message=str(e))
        return 1
    except Exception as e:
        emit(event="error", message=__import__("filmcrafter_engine.errtext", fromlist=["plain"]).plain(e))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
