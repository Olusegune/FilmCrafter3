"""The finishing pipeline for a clip made from a set: the last stretch of  Set Render -> Continuity -> Fidelity -> Finishing -> Export,  as one resumable run that joins what FilmCrafter already has instead of copying it.

  1. inspect      read the clip (length, frame rate, size, sound) and measure three frames with the Fidelity analyser (sharpness, noise, compression blocks), in numbers and words
  2. continuity   count what the continuity inspector says about the set the clip came from (findings marked deliberate are not counted); advice only, it never stops a run
  3. calm         measure flicker with the video finisher; if it is noticeable, make a calmer copy and measure again, keeping it only if it is measurably calmer (the original is never written)
  4. enhance      optional and local: the Fidelity enhancer, frame by frame, at a strength you choose (noise smoothing, block removal, halo-free sharpening). Off unless asked for
  5. finish       the video finisher: a finishing look (none, clean, film grain) and a delivery profile (web, master, ProRes, H.265, small)
  6. validate     check the delivered file against what was asked: it plays, its length and frame count match the clip, its size and codec match the profile, its sound is still there

Every stage writes its result into the run's record (`worldlock/<set or _clips>/pipeline/<run>.json`) with the seconds it took, so a run that is interrupted (a crash, the computer shut) is **resumed**: stages
already done, whose files are still there, are skipped. Nothing is sent anywhere, nothing is generated, no key is used. The originals are never changed: every stage makes a new file.

What it does not do: it does not judge whether a picture is good or on-story, it cannot repair a bad generation, and the enhancer is local image processing, not an AI model.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid

import numpy as np
from PIL import Image

from . import fidelity as F
from . import safeio
from . import videofinish as VF
from . import vpstudio as V
from . import worldlock as WL

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
STAGES = ("inspect", "continuity", "calm", "enhance", "finish", "validate")
LABELS = {"inspect": "Read and measure the clip", "continuity": "Check the set's continuity", "calm": "Calm flicker", "enhance": "Enhance (Fidelity)", "finish": "Finish and deliver", "validate": "Check the delivered file"}
MAX_SECONDS = 600


def emit(**kw) -> None:
    V.emit(**kw)


def _ff() -> str:
    from .export import ffmpeg
    return ffmpeg()


# ---------------------------------------------------------------- reading a video

def probe(path: str) -> dict:
    """Length, frame rate, size, codec, frame count and sound of a video, read with ffmpeg (no ffprobe needed)."""
    if not os.path.isfile(path):
        raise SystemExit("That video is not there.")
    r = subprocess.run([_ff(), "-hide_banner", "-i", path, "-map", "0:v:0", "-c", "copy", "-f", "null", "-"], capture_output=True, text=True, creationflags=NO_WINDOW)
    err = r.stderr or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    vline = next((ln for ln in err.splitlines() if re.search(r"Stream #\d+:\d+.*: Video:", ln)), "")
    codec = re.search(r"Video: (\w+)", vline)
    size = re.search(r"[ ,](\d{2,5})x(\d{2,5})(?=[ ,\[])", vline)
    if not m or not codec or not size:
        raise SystemExit("That file could not be read as a video.")
    fps = re.search(r"(\d+(?:\.\d+)?) fps", vline)
    pix = re.search(r", ((?:yuv|rgb|bgr|gbr|gray|nv|p0|ya)\w*)", vline)
    secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    fr = re.findall(r"frame=\s*(\d+)", err)
    info = {"seconds": round(secs, 3), "frames": None, "audio": bool(re.search(r"Stream #\d+:\d+[^:]*: Audio", err)), "bytes": os.path.getsize(path), "codec": codec.group(1), "pix_fmt": pix.group(1) if pix else "",
            "width": int(size.group(1)), "height": int(size.group(2)), "fps": float(fps.group(1)) if fps else 0.0}
    fr = re.findall(r"frame=\s*(\d+)", err)
    info["frames"] = int(fr[-1]) if fr else (int(round(secs * info["fps"])) if info["fps"] else None)
    return info


def _frame_at(path: str, t: float, out: str) -> str:
    subprocess.run([_ff(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", out], check=True, creationflags=NO_WINDOW)
    if not os.path.isfile(out):
        raise SystemExit("A frame could not be read from the clip.")
    return out


# ---------------------------------------------------------------- the record

def _dir(d: str, sid: str | None) -> str:
    return V._inside(d, f"worldlock/{sid}/pipeline" if sid else "worldlock/_clips/pipeline")


def _path(d: str, sid: str | None, run: str) -> str:
    if not re.fullmatch(r"pl-[0-9a-f]{8}", run or ""):
        raise SystemExit("That is not a run of this film.")
    return os.path.join(_dir(d, sid), f"{run}.json")


def _save(d: str, sid, run: dict) -> None:
    os.makedirs(_dir(d, sid), exist_ok=True)
    safeio.write_json(_path(d, sid, run["id"]), run, backup=False)


def _load(d: str, sid, rid: str) -> dict:
    p = _path(d, sid, rid)
    x = safeio.read_json(p, None) if os.path.isfile(p) else None
    if not isinstance(x, dict) or x.get("id") != rid:
        raise SystemExit("That run isn't here.")
    return x


def _clean_options(o: dict, sid: str | None) -> dict:
    look = o.get("look") if o.get("look") in VF.LOOKS else "none"
    profile = o.get("profile") if o.get("profile") in VF.PROFILES else "web"
    calm = o.get("calm") if o.get("calm") in ("auto", "off", "gentle", "balanced", "strong") else "auto"
    return {"set": sid or None, "look": look, "profile": profile, "calm": calm, "enhance": bool(o.get("enhance")), "strength": round(float(max(0.0, min(1.0, float(o.get("strength", 0.5))))), 2)}


def plan(d: str, ref: str, options: dict | None = None, sid: str | None = None) -> dict:
    """What a run would do and a rough time for it, before anything is made."""
    V._film(d)
    src = VF._inside(d, ref)
    info = probe(src)
    if info["seconds"] > MAX_SECONDS:
        raise SystemExit(f"That clip is longer than {MAX_SECONDS // 60} minutes: finish it in parts.")
    o = _clean_options(options or {}, sid)
    px = info["width"] * info["height"] * info["frames"]
    est = {"inspect": 3.0, "continuity": 1.0 if sid else 0.0, "calm": 0.0 if o["calm"] == "off" else 2.0 + px / 4e8 * 6, "enhance": (px / 1280 / 720) * 0.22 if o["enhance"] else 0.0, "finish": 2.0 + px / 1280 / 720 * 0.01, "validate": 3.0}
    return {"source": ref, "info": info, "options": o, "stages": [{"id": s, "label": LABELS[s], "on": est[s] > 0 or s in ("inspect", "finish", "validate"), "seconds_estimate": round(est[s], 1)} for s in STAGES],
            "seconds_estimate": round(sum(est.values()), 1), "note": "A rough guess from the clip's size on a typical computer: the measured times are kept in the run."}


def start(d: str, ref: str, options: dict | None = None, sid: str | None = None) -> dict:
    V._film(d)
    VF._inside(d, ref)
    if sid:
        WL._load(d, sid)
    o = _clean_options(options or {}, sid)
    run = {"id": "pl-" + uuid.uuid4().hex[:8], "source": ref, "options": o, "created": time.time(), "stages": {s: {"status": "pending"} for s in STAGES}, "done": False}
    _save(d, sid, run)
    return run


# ---------------------------------------------------------------- stages

def _inspect(d: str, run: dict) -> dict:
    src = VF._inside(d, run["source"])
    info = probe(src)
    tmp = V._inside(d, "worldlock/_clips/pipeline/frames")
    os.makedirs(tmp, exist_ok=True)
    shots = []
    for k, frac in enumerate((0.1, 0.5, 0.9)):
        t = max(0.0, min(info["seconds"] - 0.05, info["seconds"] * frac))
        p = _frame_at(src, t, os.path.join(tmp, f"{run['id']}-{k}.png"))
        a = F.analyze(p)
        shots.append({"t": round(t, 2), "verdict": a["verdict"], "rows": [{"id": r["id"], "label": r["label"], "level": r["level"], "note": r["note"]} for r in a["rows"]], "action": a["action"]})
    worst = {r["id"]: r["level"] for s in shots for r in s["rows"]}
    needs = {"noise": any(r["id"] == "noise" and r["level"] in ("Moderate", "High") for s in shots for r in s["rows"]),
             "blocking": any(r["id"] == "blocking" and r["level"] in ("Moderate", "High", "Visible") for s in shots for r in s["rows"]),
             "soft": any(r["id"] == "sharpness" and r["level"] in ("Soft", "Low", "Poor") for s in shots for r in s["rows"])}
    return {"info": info, "frames": shots, "needs": needs, "levels": worst}


def _continuity(d: str, run: dict) -> dict:
    sid = run["options"].get("set")
    if not sid:
        return {"skipped": "This clip is not tied to a set."}
    from . import setcontinuity as SC
    r = SC.inspect(d, sid)
    return {"counts": r["counts"], "shots_without_camera": len(r["shots_without_camera"]), "advice": f"{r['counts']['warning']} likely problem(s) and {r['counts']['advice']} worth a look in the set; {r['counts']['deliberate']} marked deliberate."}


def _calm(d: str, run: dict) -> dict:
    mode = run["options"]["calm"]
    cur = run["current"]
    if mode == "off":
        return {"skipped": "Switched off.", "output": cur}
    f = VF.flicker(d, cur)["report"]
    word = f.get("word") or f.get("level") or ""
    score = f.get("score")
    noticeable = score is not None and score >= VF.CALM
    if mode == "auto" and not noticeable:
        return {"flicker": {"score": score, "word": word}, "kept": False, "note": "Calm enough: left as it is.", "output": cur}
    r = VF.restore(d, cur, "balanced" if mode == "auto" else mode)
    if r["better"]:
        return {"flicker": {"score": score, "word": word}, "kept": True, "gain": r["gain"], "note": r["note"], "output": r["output"]}
    return {"flicker": {"score": score, "word": word}, "kept": False, "gain": r["gain"], "note": r["note"], "output": cur}


def _enhance(d: str, run: dict) -> dict:
    if not run["options"]["enhance"]:
        return {"skipped": "Not asked for.", "output": run["current"]}
    src = VF._inside(d, run["current"])
    info = probe(src)
    W, H = info["width"], info["height"]
    strength = run["options"]["strength"]
    base = os.path.splitext(os.path.basename(src))[0]
    rel = f"worldlock/_clips/pipeline/{run['id']}-{base}-enhanced.mp4"
    out = V._inside(d, rel)
    tmp = out + ".tmp.mp4"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    dec = subprocess.Popen([_ff(), "-hide_banner", "-loglevel", "error", "-i", src, "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, creationflags=NO_WINDOW)
    enc = subprocess.Popen([_ff(), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{info['fps']}", "-i", "-", "-i", src, "-map", "0:v:0", "-map", "1:a?",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p", *VF.TAGS, "-c:a", "copy", "-shortest", "-movflags", "+faststart", tmp], stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    n, t0, size = 0, time.time(), W * H * 3
    try:
        while True:
            buf = dec.stdout.read(size)
            if len(buf) < size:
                break
            im = Image.frombytes("RGB", (W, H), buf)
            enc.stdin.write(F.enhance_image(im, strength).tobytes())
            n += 1
            if n % 24 == 0:
                emit(event="progress", stage="enhancing frames", progress=round(n / max(1, info["frames"]), 3))
        enc.stdin.close()
        err = enc.stderr.read().decode("utf-8", "replace")
        if enc.wait() != 0 or not os.path.isfile(tmp):
            raise SystemExit("The enhanced video could not be written: " + (err.strip().splitlines()[-1] if err.strip() else "the video tool stopped."))
    except BaseException:
        for p in (dec, enc):
            try:
                p.kill()
            except OSError:
                pass
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, out)
    dt = time.time() - t0
    return {"output": rel, "frames": n, "frames_per_second": round(n / dt, 2) if dt else None, "strength": strength}


def _finish(d: str, run: dict) -> dict:
    o = run["options"]
    r = VF.finish(d, run["current"], o["look"], o["profile"])
    return {"output": r["output"], "bytes": r["bytes"], "look": o["look"], "profile": o["profile"], "source_bytes": r["source_bytes"]}


def _validate(d: str, run: dict) -> dict:
    """Check the delivered file against the clip it came from and the profile it was asked for. Plain pass or fail per check, with the reason."""
    out = VF._inside(d, run["stages"]["finish"]["result"]["output"])
    src_info = run["stages"]["inspect"]["result"]["info"]
    got = probe(out)
    prof = VF.PROFILES[run["options"]["profile"]]
    checks = []

    def chk(name: str, ok: bool, detail: str):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
    chk("It plays", got["frames"] is not None and got["frames"] > 0, f"{got['frames']} frames read")
    chk("Same length as the clip", abs(got["seconds"] - src_info["seconds"]) <= 0.15, f"{got['seconds']} s against {src_info['seconds']} s")
    chk("Same number of frames", got["frames"] == src_info["frames"] or abs((got["frames"] or 0) - (src_info["frames"] or 0)) <= 1, f"{got['frames']} against {src_info['frames']}")
    chk("Same picture size", (got["width"], got["height"]) == (src_info["width"], src_info["height"]), f"{got['width']}x{got['height']} against {src_info['width']}x{src_info['height']}")
    want_codec = {"libx264": "h264", "libx265": "hevc", "prores_ks": "prores"}
    vc = prof["v"][prof["v"].index("-c:v") + 1] if "-c:v" in prof["v"] else ""
    if vc in want_codec:
        chk("The codec the profile promises", got["codec"] == want_codec[vc], f"{got['codec']} (the profile says {want_codec[vc]})")
    chk("Sound kept" if src_info["audio"] else "No sound to keep", got["audio"] == src_info["audio"], "sound present" if got["audio"] else "no sound")
    if prof["ext"] == "mp4":
        head = open(out, "rb").read(65536)
        chk("Starts playing before it is all downloaded", b"moov" in head, "the index is at the front of the file" if b"moov" in head else "the index is at the end: some players wait for the whole file")
    return {"checks": checks, "ok": all(c["ok"] for c in checks), "output": run["stages"]["finish"]["result"]["output"], "info": got}


RUNNERS = {"inspect": _inspect, "continuity": _continuity, "calm": _calm, "enhance": _enhance, "finish": _finish, "validate": _validate}


def _output_ok(d: str, st: dict) -> bool:
    out = (st.get("result") or {}).get("output")
    if not out:
        return True
    try:
        return os.path.isfile(VF._inside(d, out))
    except SystemExit:                                                          # the file is gone: the stage is done again
        return False


def run(d: str, rid: str, sid: str | None = None, only: str | None = None) -> dict:
    """Run the stages not yet done, in order. A stage that is done and whose file is still there is skipped (this is how an interrupted run resumes). A stage that fails stops the run with its reason and can be tried
    again; the earlier stages are kept."""
    V._film(d)
    rec = _load(d, sid, rid)
    rec["current"] = rec.get("current") or rec["source"]
    for name in STAGES:
        st = rec["stages"][name]
        if st["status"] == "done" and _output_ok(d, st):
            if (st.get("result") or {}).get("output"):
                rec["current"] = st["result"]["output"]
            continue
        st.update({"status": "running", "started": time.time()})
        st.pop("error", None)
        _save(d, sid, rec)
        emit(event="progress", stage=LABELS[name], progress=STAGES.index(name) / len(STAGES))
        t0 = time.time()
        try:
            rec_view = {**rec, "current": rec["current"]}
            res = RUNNERS[name](d, rec_view)
        except SystemExit as e:
            st.update({"status": "failed", "error": str(e), "seconds": round(time.time() - t0, 2)})
            _save(d, sid, rec)
            raise SystemExit(f"{LABELS[name]}: {e}")
        except Exception as e:
            msg = __import__("filmcrafter_engine.errtext", fromlist=["plain"]).plain(e)
            st.update({"status": "failed", "error": msg, "seconds": round(time.time() - t0, 2)})
            _save(d, sid, rec)
            raise SystemExit(f"{LABELS[name]}: {msg}")
        st.update({"status": "done", "result": res, "seconds": round(time.time() - t0, 2)})
        if res.get("output") and name in ("calm", "enhance", "finish"):
            rec["current"] = res["output"]
        _save(d, sid, rec)
        if only == name:
            break
    rec["done"] = all(rec["stages"][s]["status"] == "done" for s in STAGES)
    rec["finished"] = time.time() if rec["done"] else None
    _save(d, sid, rec)
    return summary(rec)


def summary(rec: dict) -> dict:
    fin = (rec["stages"]["finish"].get("result") or {})
    val = (rec["stages"]["validate"].get("result") or {})
    return {**rec, "delivered": fin.get("output"), "valid": val.get("ok"), "total_seconds": round(sum(s.get("seconds", 0) for s in rec["stages"].values()), 1),
            "labels": LABELS}


def get(d: str, rid: str, sid: str | None = None) -> dict:
    V._film(d)
    return summary(_load(d, sid, rid))


def runs(d: str, sid: str | None = None) -> dict:
    V._film(d)
    out = []
    dr = _dir(d, sid)
    if os.path.isdir(dr):
        for f in sorted(os.listdir(dr)):
            if re.fullmatch(r"pl-[0-9a-f]{8}\.json", f):
                x = safeio.read_json(os.path.join(dr, f), None)
                if isinstance(x, dict) and x.get("id"):
                    out.append({"id": x["id"], "source": x.get("source"), "created": x.get("created"), "done": x.get("done"), "stages": {k: v.get("status") for k, v in x.get("stages", {}).items()}})
    return {"runs": sorted(out, key=lambda r: -(r.get("created") or 0))[:30]}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["plan", "start", "run", "get", "runs", "presets"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        d, sid = os.path.abspath(a.target), (str(x["set"]) if x.get("set") else None)
        opts = x.get("options") if isinstance(x.get("options"), dict) else {}
        table = {"plan": lambda: plan(d, str(x.get("ref", "")), opts, sid), "start": lambda: start(d, str(x.get("ref", "")), opts, sid), "run": lambda: run(d, str(x.get("run", "")), sid), "get": lambda: get(d, str(x.get("run", "")), sid),
                 "runs": lambda: runs(d, sid), "presets": lambda: VF.presets()}
        emit(event="result", data=table[a.action]())
        return 0
    except SystemExit as e:
        emit(event="error", message=str(e))
        return 1
    except Exception as e:
        emit(event="error", message=__import__("filmcrafter_engine.errtext", fromlist=["plain"]).plain(e))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
