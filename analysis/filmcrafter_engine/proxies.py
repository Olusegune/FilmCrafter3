"""Preview copies of big clips: a small, quick-to-scrub copy of a take, used ONLY to show the film in the Studio's player, never to make the film.

  <project>/cache/proxies/<name>.mp4     540 lines high, h264, a keyframe every half second, no sound; named from the take's own path, size and time, so a changed take gets a new copy

Which clips: a clip that is taller than 720 lines, or larger than 60 MB, is "big"; the rest play fine as they are and get no copy. The export reads the take itself, always (a test builds the film
with and without copies and compares the frames, and checks that the export module never names this folder). Copies are made on request and only inside the project's cache folder; clearing them
removes that folder's files and nothing else. Free, local, nothing is sent anywhere.

  python -m filmcrafter_engine.proxies <status|build|clear> <project> --data '{...}'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

from . import safeio

FOLDER = os.path.join("cache", "proxies")
BIG_LINES = 720
BIG_BYTES = 60 * 1024 * 1024
PROXY_LINES = 540
ACTIONS = ("status", "build", "clear")


def emit(**kw) -> None:
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def _ffmpeg() -> str:
    from . import export
    return export.ffmpeg()


def _flags() -> int:
    from . import export
    return getattr(export, "NO_WINDOW", 0)


def folder(d: str) -> str:
    return os.path.join(d, FOLDER)


def proxy_name(d: str, rel: str) -> str | None:
    """The copy's file name for a take (a project-relative path), or None when the take is not there."""
    p = os.path.join(d, rel)
    try:
        st = os.stat(p)
    except OSError:
        return None
    return hashlib.sha256(f"{rel}|{st.st_size}|{int(st.st_mtime)}|{PROXY_LINES}".encode("utf-8")).hexdigest()[:20] + ".mp4"


def lines_of(path: str) -> int | None:
    """How many lines tall the picture is, read from ffmpeg's own description of the file (None when it cannot be told)."""
    try:
        r = subprocess.run([_ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True, timeout=60, creationflags=_flags())
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", r.stderr or "")
    return int(m.group(2)) if m else None


def is_big(d: str, rel: str) -> bool:
    p = os.path.join(d, rel)
    try:
        if os.path.getsize(p) > BIG_BYTES:
            return True
    except OSError:
        return False
    h = lines_of(p)
    return h is not None and h > BIG_LINES


def existing(d: str, rel: str) -> str | None:
    """The project-relative path of this take's copy, if one has been made (and the take has not changed since)."""
    name = proxy_name(d, rel)
    if not name:
        return None
    p = os.path.join(folder(d), name)
    return os.path.join(FOLDER, name).replace(os.sep, "/") if os.path.isfile(p) and os.path.getsize(p) > 0 else None


def make(d: str, rel: str) -> str:
    """Make (or find) the copy of one take. Raises SystemExit with a plain reason when it cannot be made."""
    name = proxy_name(d, rel)
    if not name:
        raise SystemExit("That take is not there.")
    out = os.path.join(folder(d), name)
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return os.path.join(FOLDER, name).replace(os.sep, "/")
    os.makedirs(folder(d), exist_ok=True)
    tmp = f"{out}.{os.getpid()}.part.mp4"
    cmd = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", os.path.join(d, rel), "-vf", f"scale=-2:{PROXY_LINES}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
           "-g", "12", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", tmp]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, creationflags=_flags())
    if r.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise SystemExit("A preview copy could not be made: " + (r.stderr.strip().splitlines() or ["ffmpeg stopped"])[-1][:160])
    os.replace(tmp, out)
    return os.path.join(FOLDER, name).replace(os.sep, "/")


def takes(d: str) -> list[dict]:
    """The take each shot uses (the approved one, else the newest), as {shot, take, output}: the clips a copy would be for."""
    from .library import chosen_take, shot_state
    name = "directed" if os.path.exists(os.path.join(d, "directed.json")) else "production"
    plan = safeio.read_json(os.path.join(d, f"{name}.json"), None)
    if not isinstance(plan, dict):
        return []
    jobs = (safeio.read_json(os.path.join(d, "jobs.json"), {"jobs": []}) or {}).get("jobs", [])
    state = shot_state(d)
    out = []
    for sc in plan.get("scenes", []):
        for sh in sc.get("shots", []):
            t = chosen_take(d, sh["id"], name, jobs, state)
            if t and t.get("media_kind") != "image":
                out.append({"shot": sh["id"], "take": t["id"], "output": t["output"]})
    return out


def status(d: str) -> dict:
    rows = []
    for t in takes(d):
        big = is_big(d, t["output"])
        have = existing(d, t["output"]) if big else None
        rows.append({**t, "big": big, "proxy": have})
    f = folder(d)
    size = sum(os.path.getsize(os.path.join(f, n)) for n in os.listdir(f)) if os.path.isdir(f) else 0
    return {"rows": rows, "big": sum(1 for r in rows if r["big"]), "ready": sum(1 for r in rows if r["proxy"]), "bytes": size}


def build(d: str, shot: str | None = None) -> dict:
    rows = [r for r in status(d)["rows"] if r["big"] and (shot is None or r["shot"] == shot)]
    made = 0
    for i, r in enumerate(rows):
        if r["proxy"]:
            continue
        emit(event="progress", stage="making a preview copy", progress=round(i / max(1, len(rows)), 3), detail=r["shot"])
        make(d, r["output"])
        made += 1
    emit(event="progress", stage="done", progress=1.0)
    return {**status(d), "made": made}


def clear(d: str) -> dict:
    """Remove the preview copies (only the files in this project's proxies folder). The takes are not touched."""
    f = folder(d)
    n = 0
    if os.path.isdir(f):
        for name in os.listdir(f):
            p = os.path.join(f, name)
            if os.path.isfile(p) and (name.endswith(".mp4") or name.endswith(".part.mp4") or ".part.mp4" in name):
                os.remove(p)
                n += 1
    return {**status(d), "removed": n}


def run(d: str, action: str, x: dict) -> dict:
    if action == "status":
        return status(d)
    if action == "build":
        shot = x.get("shot")
        return build(d, shot if isinstance(shot, str) and len(shot) <= 40 else None)
    if action == "clear":
        return clear(d)
    raise SystemExit("Unknown action.")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="filmcrafter-proxies")
    ap.add_argument("action", choices=["status", "build", "clear"])
    ap.add_argument("project")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data)
        emit(event="result", data=run(a.project, a.action, x if isinstance(x, dict) else {}))
        return 0
    except SystemExit as e:
        emit(event="error", message=str(e))
    except Exception as e:                       # noqa: BLE001
        emit(event="error", message=__import__("filmcrafter_engine.errtext", fromlist=["plain"]).plain(e))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
