"""Video finishing: measure flicker, restore a flickery video, add a finishing look, and deliver in a chosen profile. Free and local (ffmpeg only); nothing is sent anywhere.

  flicker    Measures temporal flicker in a video: how much the brightness pulses from frame to frame, over the whole picture and in each part of it, once slow fades, cuts and real motion
             are discounted. Gives numbers, a plain word and a confidence. It does not judge taste: a strobe light or a flashing screen in the story is flicker on purpose.
  restore    Makes a calmer COPY (ffmpeg deflicker + gentle temporal denoise) and measures again, so the gain is a number and not a claim. The original file is never written.
  presets    The finishing looks and delivery profiles available.
  finish     Makes a delivery COPY of a finished video: an optional finishing look (clean / film grain) and an encoding profile (web, master, ProRes, H.265, small). The original is untouched.

Every file written goes in <film>/restore or <film>/finish under a unique name, with a ledger (restore.json / finish.json). Inputs must be inside the film folder.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid

import numpy as np

from . import render as R
from .safe import file_name

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
W, H = 256, 144                # measured at this size: flicker is about brightness, not detail
MAX_FRAMES = 720               # about 30 s at 24 fps; longer videos are measured on their first 30 s (the report says so)
CUT = 14.0                     # a jump in brightness above this many levels (of 255) is a cut or a flash on purpose, not flicker
CALM, SOME = 0.8, 3.5          # RMS flicker in levels (of 255): below CALM is calm, below SOME is noticeable, above is strong

LOOKS = {
    "none": {"label": "No look", "note": "Leaves the picture as it is.", "vf": []},
    "clean": {"label": "Clean", "note": "A light temporal denoise and a gentle sharpen.", "vf": ["hqdn3d=1.2:1.0:3:2.5", "unsharp=5:5:0.4:5:5:0.0"]},
    "film": {"label": "Film grain", "note": "A fine, moving grain and a gentle sharpen. A look, not a repair.", "vf": ["unsharp=5:5:0.3:5:5:0.0", "noise=alls=7:allf=t"]},
}
TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
PROFILES = {
    "web": {"label": "Web (H.264)", "ext": "mp4", "note": "Plays everywhere. Good quality, moderate size.",
            "v": ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", *TAGS], "a": ["-c:a", "aac", "-b:a", "192k"]},
    "master": {"label": "Master (H.264, high quality)", "ext": "mp4", "note": "Large, near-lossless; for keeping or re-editing.",
               "v": ["-c:v", "libx264", "-preset", "slow", "-crf", "12", "-pix_fmt", "yuv420p", "-movflags", "+faststart", *TAGS], "a": ["-c:a", "aac", "-b:a", "320k"]},
    "prores": {"label": "ProRes 422 HQ", "ext": "mov", "note": "For editors. Very large.",
               "v": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", *TAGS], "a": ["-c:a", "pcm_s16le"]},
    "h265": {"label": "H.265 (smaller)", "ext": "mp4", "note": "About half the size; some older players cannot open it.",
             "v": ["-c:v", "libx265", "-preset", "medium", "-crf", "24", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-movflags", "+faststart", *TAGS], "a": ["-c:a", "aac", "-b:a", "192k"]},
    "small": {"label": "Small (720p)", "ext": "mp4", "note": "For sharing quickly. Reduced to at most 720 pixels tall.",
              "v": ["-c:v", "libx264", "-preset", "medium", "-crf", "27", "-pix_fmt", "yuv420p", "-movflags", "+faststart", *TAGS], "a": ["-c:a", "aac", "-b:a", "128k"], "vf": ["scale=-2:'min(720,ih)'"]},
}
STRENGTHS = {"gentle": 0.5, "balanced": 1.0, "strong": 1.6}


def emit(**kw) -> None:
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str], timeout: int = 3600) -> None:
    try:
        p = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SystemExit("ffmpeg took too long and was stopped. Nothing was changed.")
    if p.returncode != 0:
        last = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "ffmpeg failed"
        raise SystemExit(f"The video could not be processed: {last}")


def _inside(d: str, rel: str) -> str:
    """A path in the film folder, from a `project:` reference or a relative path. Anything that leaves the folder is refused."""
    rel = rel[len(R.PROJECT_MEDIA):] if rel.startswith(R.PROJECT_MEDIA) else rel
    full = os.path.realpath(os.path.join(d, rel))
    root = os.path.realpath(d)
    if os.path.isabs(rel) or os.path.commonpath([root, full]) != root:
        raise SystemExit("That file is not inside this film.")
    if not os.path.isfile(full):
        raise SystemExit("That video could not be found.")
    return full


def _frames(path: str) -> np.ndarray:
    p = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", path, "-an", "-frames:v", str(MAX_FRAMES), "-vf", f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True, creationflags=NO_WINDOW, timeout=900)
    n = len(p.stdout) // (W * H)
    if p.returncode != 0 or n < 1:
        raise SystemExit("That video could not be read.")
    return np.frombuffer(p.stdout[: n * W * H], np.uint8).reshape(n, H, W).astype(np.float32)


def _rms_second_diff(series: np.ndarray) -> np.ndarray:
    """Per frame: how far each value sits from the average of its two neighbours. Slow changes (fades, drifts) are ~0; a pulse is large."""
    return series[1:-1] - 0.5 * (series[:-2] + series[2:])


def measure_frames(fr: np.ndarray) -> dict:
    n = len(fr)
    if n < 6:
        return {"frames": n, "level": "Unknown", "confidence": "low", "global": None, "local": None, "note": "Too few frames to measure flicker."}
    m = fr.mean(axis=(1, 2))
    r = _rms_second_diff(m)
    keep = np.abs(r) < CUT                                                            # cuts and flashes on purpose
    g = float(np.sqrt(np.mean(r[keep] ** 2))) if keep.any() else 0.0
    tiles = fr[:, : (H // 16) * 16, : (W // 16) * 16].reshape(n, H // 16, 16, W // 16, 16).mean(axis=(2, 4)).reshape(n, -1)
    rt = tiles[1:-1] - 0.5 * (tiles[:-2] + tiles[2:])
    med = np.median(rt, axis=1)                                                       # the typical part of the picture: robust to a moving subject that fills a few tiles
    # the typical tile pulsing in step with the whole picture is flicker; the spread between tiles (the part that is not shared) is local shimmer
    shimmer = float(np.sqrt(np.mean(np.median(np.abs(rt - med[:, None]), axis=1)[keep] ** 2))) if keep.any() else 0.0
    score = max(g, shimmer * 1.5)
    level = "Calm" if score < CALM else "Noticeable" if score < SOME else "Strong"
    conf = "high" if n >= 24 and keep.sum() >= 0.8 * len(r) else "medium" if n >= 12 else "low"
    cuts = int((~keep).sum())
    note = {"Calm": "Brightness is steady from frame to frame.", "Noticeable": "Brightness pulses a little from frame to frame.", "Strong": "Brightness pulses clearly from frame to frame."}[level]
    if cuts:
        note += f" {cuts} sudden jump(s) were treated as cuts or flashes on purpose."
    return {"frames": n, "level": level, "confidence": conf, "global": round(g, 3), "local": round(shimmer, 3), "score": round(score, 3), "note": note}


def flicker(d: str, ref: str) -> dict:
    path = _inside(d, ref)
    rep = measure_frames(_frames(path))
    rep["limited"] = rep["frames"] >= MAX_FRAMES
    return {"ref": ref, "report": rep, "limits": "Measured on brightness at a reduced size. It cannot tell a strobe light in the story from flicker, and it does not measure fine texture boiling."}


def _ledger(d: str, name: str) -> list[dict]:
    v = R._read(os.path.join(d, name), [])
    return v if isinstance(v, list) else []


def _out(d: str, folder: str, base: str, tag: str, ext: str) -> tuple[str, str]:
    os.makedirs(os.path.join(d, folder), exist_ok=True)
    uid = uuid.uuid4().hex[:10]
    return uid, os.path.join(d, folder, f"{file_name(base)}_{uid}_{tag}.{ext}")


def _rel(d: str, p: str) -> str:
    return R.PROJECT_MEDIA + os.path.relpath(p, d).replace(os.sep, "/")


def restore(d: str, ref: str, strength: str = "balanced") -> dict:
    if strength not in STRENGTHS:
        raise SystemExit("Choose gentle, balanced or strong.")
    src = _inside(d, ref)
    k = STRENGTHS[strength]
    before = measure_frames(_frames(src))
    uid, out = _out(d, "restore", os.path.splitext(os.path.basename(src))[0], "restored", "mp4")
    tmp = f"{out}.{os.getpid()}.tmp.mp4"
    size = int(round(5 + 4 * k))                                                      # deflicker averages over this many frames
    vf = f"deflicker=size={size}:mode=pm,hqdn3d=0:0:{3 * k:.1f}:{3 * k:.1f}"
    _run(["-i", src, "-vf", vf, "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p", *TAGS, "-c:a", "copy", "-movflags", "+faststart", tmp])
    os.replace(tmp, out)
    after = measure_frames(_frames(out))
    gain = None if before.get("score") is None or after.get("score") is None else round(before["score"] - after["score"], 3)
    item = {"id": uid, "source": ref, "output": _rel(d, out), "strength": strength, "created": int(time.time()), "before": before, "after": after, "gain": gain}
    items = _ledger(d, "restore.json"); items.append(item)
    R._write(os.path.join(d, "restore.json"), items[-100:])
    better = gain is not None and gain > 0.05
    return {**item, "output_path": out, "better": better,
            "note": "Calmer than the original." if better else "The copy is not measurably calmer than the original; keep the original."}


def presets() -> dict:
    return {"looks": [{"id": k, "label": v["label"], "note": v["note"]} for k, v in LOOKS.items()],
            "profiles": [{"id": k, "label": v["label"], "note": v["note"], "ext": v["ext"]} for k, v in PROFILES.items()],
            "strengths": list(STRENGTHS)}


def finish(d: str, ref: str, look: str = "none", profile: str = "web") -> dict:
    if look not in LOOKS or profile not in PROFILES:
        raise SystemExit("That look or profile is not available.")
    src = _inside(d, ref)
    pr = PROFILES[profile]
    vf = [*LOOKS[look]["vf"], *pr.get("vf", [])]
    uid, out = _out(d, "finish", os.path.splitext(os.path.basename(src))[0], f"{look}_{profile}", pr["ext"])
    tmp = f"{out}.{os.getpid()}.tmp.{pr['ext']}"
    args = ["-i", src, *(["-vf", ",".join(vf)] if vf else []), "-map", "0:v:0", "-map", "0:a?", *pr["v"], *pr["a"], tmp]
    _run(args)
    os.replace(tmp, out)
    item = {"id": uid, "source": ref, "output": _rel(d, out), "look": look, "profile": profile, "bytes": os.path.getsize(out), "created": int(time.time())}
    items = _ledger(d, "finish.json"); items.append(item)
    R._write(os.path.join(d, "finish.json"), items[-100:])
    return {**item, "output_path": out, "source_bytes": os.path.getsize(src)}


def videos(d: str) -> dict:
    """Finished videos in the film's exports folder (newest first), to choose from."""
    out = []
    root = os.path.join(d, "exports")
    if os.path.isdir(root):
        for dp, _dn, fns in os.walk(root):
            for f in fns:
                if f.lower().endswith((".mp4", ".mov")):
                    p = os.path.join(dp, f)
                    out.append({"ref": _rel(d, p), "name": f, "bytes": os.path.getsize(p), "at": int(os.path.getmtime(p))})
    return {"videos": sorted(out, key=lambda x: -x["at"])[:40]}


def status(d: str) -> dict:
    return {"restored": _ledger(d, "restore.json"), "finished": _ledger(d, "finish.json")}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="filmcrafter-videofinish")
    ap.add_argument("action", choices=["flicker", "restore", "presets", "finish", "videos", "status"])
    ap.add_argument("project")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data)
        if a.action == "flicker": res = flicker(a.project, str(x["ref"]))
        elif a.action == "restore": res = restore(a.project, str(x["ref"]), str(x.get("strength", "balanced")))
        elif a.action == "finish": res = finish(a.project, str(x["ref"]), str(x.get("look", "none")), str(x.get("profile", "web")))
        elif a.action == "presets": res = presets()
        elif a.action == "videos": res = videos(a.project)
        else: res = status(a.project)
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
