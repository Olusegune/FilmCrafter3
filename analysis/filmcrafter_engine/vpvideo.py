"""Virtual production, part 2: video. Key a green-screen clip into frames with transparency, export them with alpha, and render a composition in which cutouts move.

  * **Clip keying.** A clip is cut into frames (at most 30 a second, 720 frames, 30 seconds). The screen colour and the edge ramp are worked out *once* from several frames and then fixed
    (`keying.calibrate`), so every frame is keyed the same way. An optional temporal smoothing then blends each frame's transparency with its neighbours, *less where an edge is moving*, to calm
    flicker without smearing motion. The report gives the flicker (how much the transparency changes from frame to frame where the picture itself did not) before and after.
  * **Alpha export.** A PNG sequence, ProRes 4444 (.mov) and VP9 with alpha (.webm), each only if the ffmpeg in this app can really encode it (`capabilities` asks it), and each read back: a frame is
    decoded and its transparency compared with the mask. Transparent H.264 does not exist and is never offered.
  * **Composition in motion.** A layer can be a still cutout or a keyed clip, starts at a time, can loop, and carries keyframes (place, size, turn, opacity, each moving straight, eased, or jumping). The
    background can be a still or a clip. `render_video` writes an H.264 MP4 (or a PNG sequence), checks for a cancel request between frames, and reports progress.

What this does not do: no segmentation or matting model (so no clip without a screen), no tracking, no motion blur, and the keyed clip is only as good as the screen. Frames are held on disk, so a clip
is limited by the frame count, not by memory. Rendering is slow in proportion to size and frames (a 720-frame 1080p render takes minutes), which is why it can be cancelled.

  python -m filmcrafter_engine.vpvideo <capabilities|import_clip|key_clip|export_clip|render_video|cancel> <film> --data '{...}'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import numpy as np
from PIL import Image

from . import keying as K
from . import safeio
from . import vpstudio as V

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
MAX_FILE = 500 * 1024 * 1024
MAX_FRAMES, MAX_SECONDS, MAX_FPS, MAX_VIDEO_SIDE = 720, 30.0, 30, 1920
FORMATS = ("png", "prores4444", "webm")


def emit(**kw) -> None:
    V.emit(**kw)


def _ffmpeg() -> str:
    from .export import ffmpeg
    return ffmpeg()


def _run(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", *args], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise SystemExit("FilmCrafter could not run its video tool.")


# ---------------------------------------------------------------- what this computer's ffmpeg can really do

def capabilities() -> dict:
    """Which alpha formats this app's ffmpeg can encode. Asked, not assumed."""
    try:
        out = subprocess.run([_ffmpeg(), "-hide_banner", "-encoders"], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    have = {m.group(1) for m in re.finditer(r"^\s*[VAS][\w.]{5}\s+(\S+)", out, re.M)}
    return {"png": "png" in have, "prores4444": "prores_ks" in have, "webm": "libvpx-vp9" in have, "h264": "libx264" in have,
            "note": "Transparent H.264 MP4 does not exist, so it is never offered. A PNG sequence works everywhere."}


def probe(path: str) -> dict:
    try:
        err = subprocess.run([_ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60).stderr
    except (OSError, subprocess.SubprocessError):
        raise SystemExit("FilmCrafter could not read that file.")
    if not re.search(r"Stream #\d+:\d+.*: Video:", err):
        raise SystemExit("That file has no video FilmCrafter can read.")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    f = re.search(r"Video:.*?(\d+(?:\.\d+)?) fps", err)
    sz = re.search(r"Video:.*?[ ,](\d{2,5})x(\d{2,5})", err)
    if not (m and f and sz) or secs <= 0:
        raise SystemExit("FilmCrafter could not read the length, size or speed of that video.")
    return {"seconds": round(secs, 3), "fps": float(f.group(1)), "width": int(sz.group(1)), "height": int(sz.group(2))}


# ---------------------------------------------------------------- bringing a clip in

def import_clip(d: str, data: dict) -> dict:
    """Copy a video into the film as a clip (a plate with a screen, or a background). The original is never touched; the same clip twice is kept once."""
    V._film(d)
    src = str(data.get("path") or "")
    if not src or not os.path.isfile(src):
        raise SystemExit("Choose a video file.")
    if os.path.splitext(src)[1].lower() not in VIDEO_EXTS:
        raise SystemExit("Choose an MP4, MOV, WebM, MKV, AVI or M4V video.")
    if os.path.getsize(src) > MAX_FILE:
        raise SystemExit("That file is larger than 500 MB.")
    info = probe(src)
    if info["seconds"] > MAX_SECONDS:
        raise SystemExit(f"That video is {info['seconds']:.0f} s long: this version works on clips up to {MAX_SECONDS:.0f} s. Cut it shorter first.")
    if max(info["width"], info["height"]) > 4096:
        raise SystemExit("That video is larger than 4096 pixels on a side.")
    sha = hashlib.sha1(open(src, "rb").read(), usedforsecurity=False).hexdigest()
    kind = data.get("kind") if data.get("kind") in ("plate", "background") else "plate"
    name = V._t(data.get("name") or os.path.splitext(os.path.basename(src))[0], 60) or "clip"
    ext = os.path.splitext(src)[1].lower()
    holder: dict = {}

    def change(r):
        old = next((s for s in r["sources"] if s.get("sha1") == sha and s.get("kind") == kind and s.get("clip")), None)
        if old:
            holder["id"], holder["same"] = old["id"], True
            return
        if len(r["sources"]) >= V.MAX_SOURCES:
            raise SystemExit(f"At most {V.MAX_SOURCES} pictures and clips.")
        sid = f"vs-{uuid.uuid4().hex[:8]}"
        rel = f"vp/sources/{sid}{ext}"
        full = V._inside(d, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        shutil.copyfile(src, full)
        r["sources"].append({"id": sid, "kind": kind, "clip": True, "name": name, "file": rel, "sha1": sha, "width": info["width"], "height": info["height"], "fps": info["fps"], "seconds": info["seconds"],
                             "frames": int(round(info["fps"] * info["seconds"])), "bytes": os.path.getsize(src), "added": time.time()})
        holder["id"], holder["same"] = sid, False
    V._update(d, change)
    return {**V.get(d), "id": holder["id"], "already_there": holder["same"]}


def _extract(src: str, out_dir: str, fps: float, side: int) -> list[str]:
    """The frames of a video as PNG files, at `fps`, no wider than `side`."""
    os.makedirs(out_dir, exist_ok=True)
    r = _run(["-i", src, "-vf", f"fps={fps},scale='min({side},iw)':-2", "-frames:v", str(MAX_FRAMES + 1), os.path.join(out_dir, "%05d.png")])
    files = sorted(f for f in os.listdir(out_dir) if f.endswith(".png"))
    if r.returncode != 0 or not files:
        raise SystemExit("FilmCrafter could not read the frames of that video.")
    return [os.path.join(out_dir, f) for f in files]


def _cancel_path(d: str) -> str:
    return os.path.join(d, "vp", "cancel.flag")


def _cancelled(d: str) -> bool:
    return os.path.exists(_cancel_path(d))


def cancel(d: str) -> dict:
    """Ask a running key or render to stop at the next frame. Free. The request is cleared when the next job starts."""
    V._film(d)
    os.makedirs(os.path.dirname(_cancel_path(d)), exist_ok=True)
    open(_cancel_path(d), "w").write(str(time.time()))
    return {"cancelled": True}


def _clear_cancel(d: str) -> None:
    try:
        os.remove(_cancel_path(d))
    except OSError:
        pass


# ---------------------------------------------------------------- keying a clip

def _alpha_of(fdir: str, i: int) -> np.ndarray:
    return np.asarray(Image.open(os.path.join(fdir, f"{i + 1:05d}.png")).convert("RGBA"), dtype=np.float32)[..., 3] / 255.0


def _jitter(fdir: str, n: int) -> float:
    """How much the transparency jitters from frame to frame: the difference between a frame and the average of its two neighbours, over the pixels where those two neighbours agree (so a real
    moving edge, where they differ, is not counted as flicker). 0 is perfectly calm."""
    if n < 3:
        return 0.0
    a0, a1 = _alpha_of(fdir, 0), _alpha_of(fdir, 1)
    total, count = 0.0, 0
    for i in range(2, n):
        a2 = _alpha_of(fdir, i)
        agree = np.abs(a2 - a0) < 0.1
        k = int(agree.sum())
        if k:
            total += float(np.abs(a1 - 0.5 * (a0 + a2))[agree].sum())
            count += k
        a0, a1 = a1, a2
    return total / count if count else 0.0


def key_clip(d: str, data: dict) -> dict:
    """Key every frame of a clip into RGBA PNGs with transparency. Settings are worked out once for the whole clip. `temporal` (0 to 1) blends each frame's transparency with its neighbours where
    nothing is moving, to calm flicker. Progress is reported; a cancel request stops it and removes only the half-made output of this run."""
    V._film(d)
    _clear_cancel(d)
    r0 = V._load(d)
    s0 = V._source(r0, str(data.get("source") or ""))
    if not s0.get("clip"):
        raise SystemExit("That is a picture, not a clip: use Cut out for pictures.")
    fps = V._n(data.get("fps"), 1, MAX_FPS, min(float(s0["fps"]), MAX_FPS))
    n_expect = int(round(float(s0["seconds"]) * fps))
    if n_expect > MAX_FRAMES:
        raise SystemExit(f"That is {n_expect} frames at {fps:.0f} a second: this version keys at most {MAX_FRAMES}. Choose a lower speed or a shorter clip.")
    temporal = round(V._n(data.get("temporal"), 0, 1, 0.5), 2)
    cid = f"cu-{uuid.uuid4().hex[:8]}"
    rel = f"vp/cutouts/{cid}"
    base = V._inside(d, rel)
    fdir, mdir = os.path.join(base, "frames"), os.path.join(base, "masks")
    tmp = tempfile.mkdtemp(prefix="fc-keyclip-")
    try:
        files = _extract(V._inside(d, s0["file"]), tmp, fps, MAX_VIDEO_SIDE)
        if len(files) > MAX_FRAMES:
            raise SystemExit(f"That is more than {MAX_FRAMES} frames: choose a lower speed or a shorter clip.")
        n = len(files)
        sample = sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1})
        params = K.calibrate([K.load(files[i]) for i in sample], data.get("params") if isinstance(data.get("params"), dict) else {})
        os.makedirs(fdir, exist_ok=True)
        os.makedirs(mdir, exist_ok=True)
        prev_rgb = None
        subj, removed, soft, spill = 0.0, 0.0, 0.0, 0.0
        first_report = None
        for i, f in enumerate(files):
            if _cancelled(d):
                shutil.rmtree(base, ignore_errors=True)
                _clear_cancel(d)
                raise SystemExit(f"Stopped at frame {i} of {n}. Nothing was kept from this run.")
            rgb = K.load(f)
            rgba, rep = K.key(rgb, params)
            if first_report is None:
                first_report = rep
            K.save_rgba(rgba, os.path.join(fdir, f"{i + 1:05d}.png"))
            subj, removed, soft, spill = subj + rep["subject"], removed + rep["removed"], soft + rep["soft_edge"], spill + rep["edge_spill"]
            prev_rgb = rgb
            if i % 5 == 0:
                emit(event="progress", stage="keying frames", progress=round(0.8 * i / n, 3))
        flicker_before = _jitter(fdir, n)
        flicker_after = flicker_before
        if temporal > 0 and n >= 3:
            _smooth_alpha(d, fdir, mdir, files, n, temporal)
            flicker_after = _jitter(fdir, n)
        else:
            for i in range(n):
                a = np.asarray(Image.open(os.path.join(fdir, f"{i + 1:05d}.png")).convert("RGBA"))[..., 3]
                Image.fromarray(a, "L").save(os.path.join(mdir, f"{i + 1:05d}.png"), "PNG")
        emit(event="progress", stage="writing the record", progress=0.97)
    except BaseException:
        if os.path.isdir(base) and not any(c.get("id") == cid for c in V._load(d)["cutouts"]):
            shutil.rmtree(base, ignore_errors=True)                                                  # only this run's own unfinished output
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    notes = list(first_report["plate"]["notes"]) + ([] if flicker_after < 0.01 else ["The edge still flickers a little: raise the smoothing, or check that the screen is evenly lit."])
    report = {"subject": round(subj / n, 4), "removed": round(removed / n, 4), "soft_edge": round(soft / n, 4), "edge_spill": round(spill / n, 4), "plate": first_report["plate"], "notes": notes,
              "flicker_before": round(flicker_before, 5), "flicker_after": round(flicker_after, 5)}
    name = V._t(data.get("name") or f"{s0['name']} cutout", 60) or "cutout"

    def change(r):
        V._source(r, s0["id"])
        if len(r["cutouts"]) >= V.MAX_CUTOUTS:
            raise SystemExit(f"At most {V.MAX_CUTOUTS} cutouts.")
        r["cutouts"].append({"id": cid, "kind": "clip", "name": name, "source": s0["id"], "params": params, "temporal": temporal, "report": report, "rgba": f"{rel}/frames/00001.png", "mask": f"{rel}/masks/00001.png",
                             "seq": f"{rel}/frames/%05d.png", "frames": n, "fps": fps, "seconds": round(n / fps, 3), "width": int(prev_rgb.shape[1]), "height": int(prev_rgb.shape[0]), "created": time.time()})
    V._update(d, change)
    emit(event="progress", stage="done", progress=1.0)
    return {**V.get(d), "id": cid, "report": report}


def _smooth_alpha(d: str, fdir: str, mdir: str, files: list[str], n: int, w0: float) -> None:
    """Blend each frame's transparency with its two neighbours, by `w0`, less where it is changing quickly between the neighbours (a moving edge). Works from the original transparency of the
    neighbours, so a frame is never filtered by an already filtered one. Writes the frames and the masks."""
    alpha_of = lambda i: _alpha_of(fdir, i)  # noqa: E731
    prev, cur = alpha_of(0), alpha_of(0)
    nxt = alpha_of(1)
    for i in range(n):
        if i > 0:
            prev, cur = cur, nxt
            nxt = alpha_of(i + 1) if i + 1 < n else cur
        lo, hi = (prev if i > 0 else cur), (nxt if i + 1 < n else cur)
        motion = np.clip(np.abs(hi - lo) * 4.0, 0.0, 1.0)
        w = w0 * (1.0 - motion)
        sm = cur * (1 - w) + 0.5 * (lo + hi) * w
        path = os.path.join(fdir, f"{i + 1:05d}.png")
        im = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0
        im[..., 3] = sm
        im[..., :3] *= (sm > 0.002)[..., None]
        K.save_rgba(im, path)
        Image.fromarray((sm * 255 + 0.5).astype(np.uint8), "L").save(os.path.join(mdir, f"{i + 1:05d}.png"), "PNG")
        if i % 5 == 0:
            emit(event="progress", stage="calming the edge", progress=round(0.8 + 0.17 * i / n, 3))


# ---------------------------------------------------------------- exporting a keyed clip with alpha

def _decode_alpha(path: str, fmt: str, out_png: str) -> np.ndarray | None:
    """Decode the first frame of an exported clip back to RGBA, to see whether the transparency survived."""
    pre = ["-c:v", "libvpx-vp9"] if fmt == "webm" else []
    r = _run([*pre, "-i", path, "-frames:v", "1", "-pix_fmt", "rgba", out_png], timeout=120)
    if r.returncode != 0 or not os.path.isfile(out_png):
        return None
    return np.asarray(Image.open(out_png).convert("RGBA"))[..., 3].astype(np.float32) / 255.0


def export_clip(d: str, data: dict) -> dict:
    """Write a keyed clip with transparency: a PNG sequence, ProRes 4444 or VP9 with alpha (only where this app's ffmpeg can encode it), then decode a frame back and compare its transparency with the mask."""
    V._film(d)
    c = V._cutout(V._load(d), str(data.get("id") or ""))
    if c.get("kind") != "clip":
        raise SystemExit("That is a still cutout: use Export PNG for stills.")
    fmt = data.get("format") if data.get("format") in FORMATS else "png"
    caps = capabilities()
    if not caps.get(fmt):
        raise SystemExit("This computer's video tool cannot make that format. Use a PNG sequence.")
    stem = re.sub(r"[^A-Za-z0-9 _.-]+", "", c["name"]).strip() or c["id"]
    out_dir = V._inside(d, "exports/virtual-production")
    os.makedirs(out_dir, exist_ok=True)
    frames_dir = V._inside(d, os.path.dirname(c["seq"]))
    fps = float(c["fps"])
    mask0 = np.asarray(Image.open(V._inside(d, c["mask"])).convert("L"), dtype=np.float32) / 255.0
    if fmt == "png":
        folder = os.path.join(out_dir, f"{stem} {c['id']} frames")
        os.makedirs(folder, exist_ok=True)
        for i in range(1, c["frames"] + 1):
            shutil.copyfile(os.path.join(frames_dir, f"{i:05d}.png"), os.path.join(folder, f"frame_{i:05d}.png"))
        a = np.asarray(Image.open(os.path.join(folder, "frame_00001.png")).convert("RGBA"))[..., 3].astype(np.float32) / 255.0
        return {"id": c["id"], "format": fmt, "path": folder, "file": f"exports/virtual-production/{os.path.basename(folder)}", "frames": c["frames"], "fps": fps, "has_alpha": bool(a.min() < 1.0),
                "alpha_error": round(float(np.abs(a - mask0).mean()), 5), "note": "A PNG sequence with straight alpha, numbered from 1. Import it as an image sequence at the frame rate shown."}
    ext = ".mov" if fmt == "prores4444" else ".webm"
    out = os.path.join(out_dir, f"{stem} {c['id']}{ext}")
    codec = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-vendor", "apl0"] if fmt == "prores4444" else ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", "-crf", "20", "-b:v", "0"]
    emit(event="progress", stage="encoding", progress=0.2)
    r = _run(["-y", "-framerate", f"{fps}", "-i", os.path.join(frames_dir, "%05d.png"), *codec, out], timeout=1800)
    if r.returncode != 0 or not os.path.isfile(out):
        raise SystemExit("The video could not be written: " + (r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "the video tool stopped."))
    tmp = tempfile.mkdtemp(prefix="fc-alphacheck-")
    try:
        a = _decode_alpha(out, fmt, os.path.join(tmp, "f.png"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    has = bool(a is not None and a.min() < 0.98)
    err = round(float(np.abs(a - mask0).mean()), 5) if a is not None and a.shape == mask0.shape else None
    return {"id": c["id"], "format": fmt, "path": out, "file": f"exports/virtual-production/{os.path.basename(out)}", "frames": c["frames"], "fps": fps, "has_alpha": has, "alpha_error": err,
            "note": ("Read back: the transparency survived." if has else "Read back: NO transparency found in the exported file. Use the PNG sequence instead.") +
                    (" ProRes 4444 opens in most editors; VP9 alpha opens in browsers and some editors." )}


# ---------------------------------------------------------------- a composition that moves

class Frames:
    """The frames of one still or clip, read from disk when asked for (a few kept), never all at once."""

    def __init__(self, paths: list[str] | None = None, still: np.ndarray | None = None, fps: float = 24.0):
        self.paths, self.still, self.fps, self.cache = paths or [], still, fps, {}

    def __len__(self) -> int:
        return 1 if self.still is not None else len(self.paths)

    def get(self, i: int, rgba: bool) -> np.ndarray:
        if self.still is not None:
            return self.still
        i = min(max(i, 0), len(self.paths) - 1)
        if i not in self.cache:
            if len(self.cache) > 6:
                self.cache.pop(next(iter(self.cache)))
            self.cache[i] = K.load_rgba(self.paths[i]) if rgba else K.load(self.paths[i])
        return self.cache[i]


def _background(d: str, r: dict, comp: dict, W: int, H: int, fps: float, tmp: str) -> tuple[Frames | None, np.ndarray]:
    base = np.zeros((H, W, 3), np.float32)
    base[...] = comp["colour"]
    if not comp.get("background"):
        return None, base
    s = V._source(r, comp["background"])
    if s.get("clip"):
        files = _extract(V._inside(d, s["file"]), os.path.join(tmp, "bg"), fps, MAX_VIDEO_SIDE)
        return Frames(paths=files, fps=fps), base
    img = Image.fromarray((V._open_source(d, s) * 255 + 0.5).astype(np.uint8)).resize((W, H), Image.LANCZOS)
    return Frames(still=np.asarray(img, dtype=np.float32) / 255.0), base


def _layer_frames(d: str, r: dict, comp: dict) -> list[tuple[dict, dict, Frames]]:
    out = []
    for l in comp["layers"]:
        c = next((c for c in r["cutouts"] if c["id"] == l["cutout"]), None)
        if not c:
            continue
        if c.get("kind") == "clip":
            fdir = V._inside(d, os.path.dirname(c["seq"]))
            out.append((l, c, Frames(paths=[os.path.join(fdir, f"{i:05d}.png") for i in range(1, c["frames"] + 1)], fps=float(c["fps"]))))
        else:
            out.append((l, c, Frames(still=K.load_rgba(V._inside(d, c["rgba"])))))
    return out


def layer_state(l: dict, t: float) -> dict:
    """A layer's place, size, turn and opacity at time `t`: its own settings, moved by its keyframes."""
    keys = l.get("keys") or []
    st = {f: l.get(f, {"x": 0.5, "y": 1.0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}[f]) for f in K.KEY_FIELDS}
    for f in K.KEY_FIELDS:
        v = K.interp(keys, t, f)
        if v is not None:
            st[f] = v
    return st


def compose_at(d: str, r: dict, comp: dict, t: float, bg: Frames | None, base: np.ndarray, layers: list[tuple[dict, dict, Frames]], fps: float) -> np.ndarray:
    """One frame of a composition at time `t` seconds."""
    W, H = comp["size"][0], comp["size"][1]
    if bg is not None:
        base = bg.get(int(t * bg.fps), False) if bg.still is None else bg.still
        if base.shape[:2] != (H, W):
            base = np.asarray(Image.fromarray((base * 255 + 0.5).astype(np.uint8)).resize((W, H), Image.LANCZOS), dtype=np.float32) / 255.0
    placed = []
    for l, c, fr in layers:
        local = t - float(l.get("start", 0.0))
        if local < 0:
            continue
        if c.get("kind") == "clip":
            idx = int(local * fr.fps)
            if l.get("loop") and len(fr):
                idx %= len(fr)
            elif idx >= len(fr):
                idx = len(fr) - 1
        else:
            idx = 0
        st = layer_state(l, t)
        placed.append({**l, **st, "rgba": fr.get(idx, True)})
    return K.composite(base, placed)


def render_video(d: str, data: dict) -> dict:
    """Render a composition over time to an H.264 MP4 (or a PNG sequence). Cutouts move by their keyframes; clips play from their start time; a cancel request stops it at the next frame."""
    V._film(d)
    _clear_cancel(d)
    r = V._load(d)
    comp = next((c for c in r["compositions"] if c.get("id") == str(data.get("id") or "")), None)
    if not comp:
        raise SystemExit("That composition isn't in the film.")
    fps = V._n(data.get("fps"), 1, MAX_FPS, 24.0)
    ends = [float(l.get("start", 0)) + (next((c["seconds"] for c in r["cutouts"] if c["id"] == l["cutout"] and c.get("kind") == "clip"), 0) or 0) for l in comp["layers"]]
    ends += [max([k["t"] for k in (l.get("keys") or [])] or [0]) for l in comp["layers"]]
    default = max(ends + [2.0])
    secs = V._n(data.get("seconds"), 0.5, MAX_SECONDS, min(default, MAX_SECONDS))
    n = int(round(secs * fps))
    if n > MAX_FRAMES:
        raise SystemExit(f"That is {n} frames: this version renders at most {MAX_FRAMES}. Choose a lower speed or a shorter time.")
    W, H = (int(comp["size"][0]) // 2 * 2, int(comp["size"][1]) // 2 * 2)
    scale = min(1.0, MAX_VIDEO_SIDE / max(W, H))
    W, H = max(2, int(W * scale) // 2 * 2), max(2, int(H * scale) // 2 * 2)
    comp = {**comp, "size": [W, H]}
    fmt = data.get("format") if data.get("format") in ("mp4", "png") else "mp4"
    stamp = int(time.time())
    tmp = tempfile.mkdtemp(prefix="fc-render-")
    proc = None
    out_rel = f"vp/renders/{comp['id']}-{stamp}" + (".mp4" if fmt == "mp4" else "")
    out_full = V._inside(d, out_rel)
    os.makedirs(os.path.dirname(out_full), exist_ok=True)
    try:
        bg, base = _background(d, r, comp, W, H, fps, tmp)
        layers = _layer_frames(d, r, comp)
        if fmt == "mp4":
            proc = subprocess.Popen([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                     "-crf", "18", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart", out_full], stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=NO_WINDOW)
        else:
            os.makedirs(out_full, exist_ok=True)
        for i in range(n):
            if _cancelled(d):
                raise SystemExit(f"Stopped at frame {i} of {n}. The half-made render was removed.")
            frame = (compose_at(d, r, comp, i / fps, bg, base, layers, fps) * 255 + 0.5).astype(np.uint8)
            if proc:
                proc.stdin.write(frame.tobytes())
            else:
                Image.fromarray(frame, "RGB").save(os.path.join(out_full, f"frame_{i + 1:05d}.png"), "PNG")
            if i % 3 == 0:
                emit(event="progress", stage="drawing frames", progress=round(0.95 * i / n, 3))
        if proc:
            proc.stdin.close()
            err = proc.stderr.read().decode("utf-8", "replace")
            if proc.wait() != 0 or not os.path.isfile(out_full):
                raise SystemExit("The video could not be written: " + (err.strip().splitlines()[-1] if err.strip() else "the video tool stopped."))
            proc = None
    except BaseException:
        if proc:
            try:
                proc.stdin.close()
            except OSError:
                pass
            proc.kill()
            proc.wait()                                                                              # the file is held until the tool has really stopped (Windows)
        if os.path.isdir(out_full):
            shutil.rmtree(out_full, ignore_errors=True)
        elif os.path.isfile(out_full):
            try:
                os.remove(out_full)
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _clear_cancel(d)
    if fmt == "mp4":
        info = probe(out_full)
        if (info["width"], info["height"]) != (W, H) or abs(info["seconds"] - n / fps) > 0.5:
            raise SystemExit("The video was written, but its size or length is not what was asked for.")

    def change(r2):
        c2 = next((c for c in r2["compositions"] if c.get("id") == comp["id"]), None)
        if c2 is not None:
            c2["last_video"] = out_rel
    V._update(d, change)
    emit(event="progress", stage="done", progress=1.0)
    return {**V.get(d), "id": comp["id"], "file": out_rel, "format": fmt, "frames": n, "fps": fps, "seconds": round(n / fps, 3), "width": W, "height": H}


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["capabilities", "import_clip", "key_clip", "export_clip", "render_video", "cancel"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        if a.action == "capabilities":
            V._film(d)
            res = capabilities()
        elif a.action == "import_clip":
            res = import_clip(d, x)
        elif a.action == "key_clip":
            res = key_clip(d, x)
        elif a.action == "export_clip":
            res = export_clip(d, x)
        elif a.action == "render_video":
            res = render_video(d, x)
        else:
            res = cancel(d)
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
