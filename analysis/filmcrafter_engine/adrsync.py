"""Putting a line exactly where the picture needs it: placement in frames, dub-fit, lining up with the picture's own sound, and ADR retakes.

A recording is attached to a shot (`voiceover`). This module changes *when* it is heard and offers *other takes* of it; it never changes a recording.

* **Placement in frames.** A line can be moved earlier or later by whole frames at the film's frame rate (exact rational time from `edit_time`: 24, 23.976, 25, 29.97 and the rest), shown as a timecode inside
  the shot. The offset is a record (`voice/sync.json`); the mixer applies it when the film is made.
* **Dub-fit.** When a line is a little too long or short for the space it has, a *fitted take* is made with a pitch-preserving tempo change (ffmpeg `atempo`), kept beside the others. A change of up to 8%
  is called natural, up to 15% audible, and more than that is refused unless you insist: shorten the line, lengthen the shot or record it again instead.
* **Lining up.** `align` compares the loudness shape of the picture's own sound (or a guide file) with the recording and suggests how many frames to move it. It is a measurement of timing, with a stated
  confidence, not word-level alignment (there is no alignment model here), and a video model's own sound is only a guide if it speaks the same words at the same pace.
* **ADR.** Mark a line as needing replacement (with a reason; `adr_list` also lists recordings the audio inspector found noise, clipping, dropouts or a cut-off end in), and add a retake from a file or the
  microphone. A retake is a new take beside the others, never a replacement: choose it in Line Studio (`cast_voice.use_take`) when it is better. Your original is kept untouched.

Free and local: nothing here is sent anywhere or paid for.

  <film>/voice/sync.json            { lines: { <shot>: { <person>: {offset_frames} } }, adr: { <shot>: { <person>: {needs, reason} } } }
  <film>/voice/_adr/<hash>.<ext>    an ADR recording as it came (never changed)
  <film>/voice/_generated/<shot>-ad<hash>.wav, <shot>-df<hash>.wav   an ADR take and a fitted take, each with a .json beside it

  python -m filmcrafter_engine.adrsync <get|nudge|fit_plan|fit_make|align|adr_mark|adr_list|adr_take> <film> --data '{...}'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from fractions import Fraction

from . import edit_time as T
from . import safeio, shotsound
from . import voiceover as V
from .safe import check_id

RATE = shotsound.RATE
OFFSET_MAX_S = 5.0
FIT_NATURAL = 1.08          # a tempo change up to this much (either way) is called natural
FIT_MAX = 1.15              # and up to this much audible; beyond it is refused unless asked for
TAIL = 0.1                  # seconds of air kept after a line that is fitted into a shot
ALIGN_MAX_S = 2.0
ALIGN_SECONDS = 30.0
ENV_HOP = 0.01
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
NOTE = 300


def emit(**kw) -> None:
    try:
        print(json.dumps(kw, ensure_ascii=False), flush=True)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- frames and the film's clock

def film_fps(d: str) -> T.FrameRate:
    """The film's frame rate as two whole numbers (24 when the film does not say; exports are made at 24 today)."""
    m = safeio.read_json(os.path.join(d, "film.json"), {}) or {}
    return T.FrameRate.of(m.get("fps")) if isinstance(m, dict) else T.FPS_24


def frames_to_seconds(frames: int, fps: T.FrameRate) -> float:
    return float(Fraction(int(frames) * fps.den, fps.num))


def seconds_to_frames(seconds: float, fps: T.FrameRate) -> int:
    f = Fraction(seconds).limit_denominator(1_000_000) * fps.num / fps.den
    n = int(f)
    return n + 1 if f - n >= Fraction(1, 2) else n if f >= 0 else -int(-f + Fraction(1, 2))


def tc(seconds: float, fps: T.FrameRate) -> str:
    """A time inside the shot as hh:mm:ss:ff (non-drop; a minus sign for a time before the shot starts)."""
    sign = "-" if seconds < 0 else ""
    return sign + T.timecode(T.seconds_to_ticks(abs(seconds), fps), fps)


# ---------------------------------------------------------------- the film's record

def _path(d: str) -> str:
    return os.path.join(d, "voice", "sync.json")


def _ok(r: object) -> bool:
    return isinstance(r, dict) and isinstance(r.get("lines", {}), dict) and isinstance(r.get("adr", {}), dict)


def _norm(r: dict) -> dict:
    r.setdefault("schema", 1)
    for k in ("lines", "adr"):
        if not isinstance(r.get(k), dict):
            r[k] = {}
    return r


def _load(d: str) -> dict:
    return _norm(safeio.read_json(_path(d), None, check=_ok) or {"schema": 1, "lines": {}, "adr": {}})


def _update(d: str, change) -> None:
    def wrap(r):
        change(_norm(r))
        return r
    safeio.update_json(_path(d), wrap, {"schema": 1, "lines": {}, "adr": {}}, check=_ok)


def offset_frames(d: str, sid: str, key: str) -> int:
    e = ((_load(d)["lines"].get(sid) or {}).get(key)) or {}
    return int(e.get("offset_frames") or 0) if isinstance(e, dict) else 0


def offset_seconds(d: str, sid: str, key: str) -> float:
    """How far a person's line in a shot is moved from where it would start, in seconds (0 when it is not moved). Read by the renderer."""
    n = offset_frames(d, sid, key)
    return frames_to_seconds(n, film_fps(d)) if n else 0.0


def _line(d: str, shot: str, speaker: str) -> tuple[str, str, str, dict, float]:
    """(shot id, person key, person name, the attached recording, the shot's length) or a plain refusal."""
    V._film(d)
    sid = check_id(shot, "shot")
    k = V.key_of(speaker)
    if not k:
        raise SystemExit("Choose who is speaking.")
    cons = V._contracts(d)
    if sid not in cons:
        raise SystemExit(f"There is no shot {sid} in this film.")
    rec = next((e for e in V._meta(d)["shots"].get(sid, []) if e.get("key") == k), None)
    if not rec:
        raise SystemExit("That person has no recording in that shot. Attach one first.")
    return sid, k, V.pretty(speaker), rec, float((cons[sid].get("generation") or {}).get("duration") or 3.0)


# ---------------------------------------------------------------- where a line sits

def get(d: str, shot: str, speaker: str) -> dict:
    """A line's timing: how long it is, where it starts and ends in the shot (in frames and as a timecode), whether it runs past the shot, and how well it fits. Free."""
    sid, k, name, rec, shot_s = _line(d, shot, speaker)
    fps = film_fps(d)
    n = offset_frames(d, sid, k)
    off = frames_to_seconds(n, fps)
    secs = float(rec.get("seconds") or 0)
    start, end = max(off, 0.0) if off >= 0 else off, off + secs
    plan = fit_plan(d, sid, speaker)
    adr = ((_load(d)["adr"].get(sid) or {}).get(k)) or {}
    return {"shot": sid, "person": name, "key": k, "fps": fps.as_list(), "fps_label": f"{fps.num / fps.den:g}", "shot_seconds": shot_s, "recording": {"file": rec.get("file"), "seconds": secs, "source": rec.get("source") or "recording"},
            "offset_frames": n, "offset_seconds": round(off, 4), "starts": tc(start, fps), "ends": tc(end, fps), "shot_ends": tc(shot_s, fps), "runs_past_shot": end > shot_s + 0.02, "starts_before_shot": off < 0,
            "fit": plan, "adr": {"needs": bool(adr.get("needs")), "reason": str(adr.get("reason") or "")}}


def nudge(d: str, shot: str, speaker: str, frames=None, to_frame=None) -> dict:
    """Move a line earlier or later by whole frames (`frames`, a step) or to an exact offset (`to_frame`). The recording is not changed; the offset is applied when the film is made."""
    sid, k, name, rec, shot_s = _line(d, shot, speaker)
    fps = film_fps(d)
    for v, what in ((frames, "frames"), (to_frame, "to_frame")):
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            raise SystemExit("Move a line by a whole number of frames.")
    if frames is None and to_frame is None:
        raise SystemExit("Say how many frames to move it.")
    cur = offset_frames(d, sid, k)
    new = int(to_frame) if to_frame is not None else cur + int(frames)
    limit = seconds_to_frames(OFFSET_MAX_S, fps)
    if abs(new) > limit:
        raise SystemExit(f"A line can be moved at most {OFFSET_MAX_S:g} seconds ({limit} frames) from where it starts.")

    def change(r):
        line = r["lines"].setdefault(sid, {}).setdefault(k, {})
        if new == 0:
            r["lines"][sid].pop(k, None)
            if not r["lines"][sid]:
                r["lines"].pop(sid)
        else:
            line.update({"offset_frames": new, "fps": fps.as_list(), "updated": int(time.time())})
    _update(d, change)
    return get(d, sid, speaker)


# ---------------------------------------------------------------- dub-fit

def fit_plan(d: str, shot: str, speaker: str, target_seconds=None) -> dict:
    """Whether the line fits the space it has in its shot, and what tempo change would make it fit. A change of up to 8% is natural, up to 15% audible, more is not offered. Free; nothing is made."""
    sid, k, name, rec, shot_s = _line(d, shot, speaker)
    secs = float(rec.get("seconds") or 0)
    off = frames_to_seconds(offset_frames(d, sid, k), film_fps(d))
    if target_seconds is None:
        target = round(shot_s - max(off, 0.0) - TAIL, 3)
    else:
        if isinstance(target_seconds, bool) or not isinstance(target_seconds, (int, float)) or not (0.3 <= float(target_seconds) <= 120):
            raise SystemExit("The length to fit into must be between 0.3 and 120 seconds.")
        target = float(target_seconds)
    if target <= 0.2:
        return {"fits": False, "tempo": None, "target": target, "recording": secs, "class": "no_room", "words": "The line starts too late in the shot to leave any room. Move it earlier or lengthen the shot."}
    if secs <= target + 0.01:
        return {"fits": True, "tempo": 1.0, "target": target, "recording": secs, "class": "fits", "words": f"It fits: {secs:.2f} s in {target:.2f} s."}
    tempo = round(secs / target, 4)
    cls = "natural" if tempo <= FIT_NATURAL else "audible" if tempo <= FIT_MAX else "too_much"
    words = {"natural": f"Speeding it up {100 * (tempo - 1):.1f}% would fit it, which should sound natural.",
             "audible": f"Speeding it up {100 * (tempo - 1):.1f}% would fit it, but listeners may notice. Listen before you keep it.",
             "too_much": f"It would need {100 * (tempo - 1):.0f}% faster, too much to sound right. Shorten the line, lengthen the shot or record it again."}[cls]
    return {"fits": False, "tempo": tempo, "target": target, "recording": secs, "class": cls, "words": words}


def _ffmpeg() -> str:
    from .export import ffmpeg
    return ffmpeg()


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _generated(d: str, sid: str, tag: str, digest: str) -> str:
    return os.path.join(d, "voice", "_generated", f"{sid}-{tag}{digest[:16]}.wav")


def _rel(d: str, p: str) -> str:
    return os.path.relpath(p, d).replace(os.sep, "/")


def _check_audio(path: str, expected: float | None, tol: float) -> float:
    import numpy as np
    x = shotsound.decode(path, 1)
    if not len(x):
        raise SystemExit("The result has no sound, so nothing was kept.")
    if float(np.sqrt(np.mean(np.square(x)))) < V.SILENT_RMS:
        raise SystemExit("The result is silent, so nothing was kept.")
    secs = len(x) / RATE
    if expected is not None and abs(secs - expected) > tol:
        raise SystemExit("The result is not the length it should be, so nothing was kept.")
    return round(secs, 3)


def fit_make(d: str, shot: str, speaker: str, target_seconds=None, tempo=None, allow_extreme=False) -> dict:
    """Make a fitted take of a line: the same words, sped up or slowed down without changing the pitch, kept beside the other takes. The recording is untouched and nothing is attached: choose the take in
    Line Studio. A change beyond 15% is refused unless `allow_extreme`."""
    sid, k, name, rec, shot_s = _line(d, shot, speaker)
    src = V.inside(d, rec.get("file"))
    if not src or not os.path.isfile(src):
        raise SystemExit("That recording is missing from the film.")
    secs = float(rec.get("seconds") or 0)
    if tempo is None:
        plan = fit_plan(d, sid, speaker, target_seconds)
        if plan["tempo"] is None or plan["class"] == "fits":
            raise SystemExit("It already fits, so there is nothing to fit." if plan["class"] == "fits" else plan["words"])
        tempo = plan["tempo"]
    if isinstance(tempo, bool) or not isinstance(tempo, (int, float)) or not (0.5 <= float(tempo) <= 2.0):
        raise SystemExit("A tempo change must be between 0.5 and 2.")
    tempo = round(float(tempo), 4)
    if abs(tempo - 1.0) < 0.002:
        raise SystemExit("That is not a change.")
    worst = max(tempo, 1 / tempo)
    if worst > FIT_MAX and allow_extreme is not True:
        raise SystemExit(f"A change of {100 * (worst - 1):.0f}% is too much to sound right. Shorten the line, lengthen the shot or record it again (or insist, and listen carefully).")
    digest = _sha(src)
    key16 = hashlib.sha256(json.dumps([digest, tempo, sid, k]).encode()).hexdigest()
    out = _generated(d, sid, "df", key16)
    cached = os.path.isfile(out) and os.path.isfile(out[:-4] + ".json")
    seconds = None
    if not cached:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        part = out + ".part.wav"
        r = subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vn", "-filter:a", f"atempo={tempo}", "-ar", str(RATE), "-ac", "2", part],
                           capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode or not os.path.isfile(part):
            if os.path.isfile(part):
                os.remove(part)
            raise SystemExit("The line could not be fitted: " + " ".join((r.stderr or "").strip().splitlines()[-1:])[:200])
        try:
            seconds = _check_audio(part, secs / tempo, max(0.15, 0.05 * secs))
        except SystemExit:
            os.remove(part)
            raise
        os.replace(part, out)
        V._write(out[:-4] + ".json", {"kind": "dubfit", "shot": sid, "key": k, "speaker": name, "text": "", "voice_name": "fitted line", "tempo": tempo, "target_seconds": target_seconds,
                                      "source": rec.get("file"), "source_sha256": digest, "original_seconds": secs, "seconds": seconds, "at": int(time.time()),
                                      "note": f"{'faster' if tempo > 1 else 'slower'} by {100 * abs(tempo - 1):.1f}%, pitch kept"})
    return {"shot": sid, "person": name, "take": _rel(d, out), "tempo": tempo, "seconds": seconds, "cached": cached, "attached": False, "natural": worst <= FIT_NATURAL,
            "next": "Listen to it next to the original, then choose it as the take for the shot."}


# ---------------------------------------------------------------- lining up with the picture's own sound

def _envelope(x, hop: float = ENV_HOP):
    import numpy as np
    w = max(1, int(hop * RATE))
    k = len(x) // w
    if k < 8:
        return np.zeros(0, dtype=np.float32)
    e = np.sqrt(np.mean(np.square(x[: k * w].reshape(k, w)), axis=1)).astype(np.float32)
    e = np.log1p(40.0 * e)
    return e - float(np.mean(e))


def estimate_shift(guide, recording, max_shift: float = ALIGN_MAX_S) -> dict:
    """How far to move `recording` (positive: later) to line its loudness shape up with `guide`. Both are mono sounds at RATE. Pure: no files. Reports the best match and how much better it is than the rest."""
    import numpy as np
    g, r = _envelope(guide[: int(ALIGN_SECONDS * RATE)]), _envelope(recording[: int(ALIGN_SECONDS * RATE)])
    if len(g) < 8 or len(r) < 8 or float(np.std(g)) < 1e-6 or float(np.std(r)) < 1e-6:
        return {"ok": False, "why": "One of the two sounds is too short or too even to line up."}
    m = int(max_shift / ENV_HOP)
    scores = []
    for s in range(-m, m + 1):
        # the recording moved by s steps against the guide: compare where they overlap
        a0, b0 = max(0, s), max(0, -s)
        n = min(len(g) - a0, len(r) - b0)
        if n < 8:
            scores.append(-1.0)
            continue
        ga, rb = g[a0:a0 + n], r[b0:b0 + n]
        denom = float(np.std(ga)) * float(np.std(rb))
        scores.append(float(np.mean(ga * rb) / denom) if denom > 1e-9 else -1.0)
    sc = np.array(scores)
    best = int(np.argmax(sc))
    z = (float(sc[best]) - float(np.median(sc))) / (float(np.std(sc)) + 1e-9)
    return {"ok": True, "shift_seconds": round((best - m) * ENV_HOP, 3), "strength": round(float(sc[best]), 3), "z": round(z, 1), "reliable": bool(sc[best] >= 0.5 and z >= 3.0)}


def align(d: str, shot: str, speaker: str, guide: str | None = None) -> dict:
    """Suggest how many frames to move a line so it matches the picture's own sound (or a guide recording you name). It only suggests: apply it with `nudge`. It compares loudness shapes, not words, so it
    is only as good as the guide: the sound a video model made is a guide only if it says the same thing at the same pace."""
    sid, k, name, rec, shot_s = _line(d, shot, speaker)
    src = V.inside(d, rec.get("file"))
    if not src or not os.path.isfile(src):
        raise SystemExit("That recording is missing from the film.")
    if guide:
        s = str(guide).strip()
        gp = os.path.abspath(s) if os.path.isabs(s) else V.inside(d, s)
        if not gp:
            raise SystemExit("That guide file is not inside this film.")
        what = os.path.basename(gp)
    else:
        take = shotsound.take_for(d, sid)
        gp = os.path.join(d, take["output"]) if take and take.get("output") else None
        what = "the picture's own sound"
        if not gp or not os.path.isfile(gp):
            raise SystemExit("This shot has no picture sound to line up with. Choose a guide recording instead.")
    gx = shotsound.decode(gp, 1)
    if not len(gx):
        raise SystemExit(f"There is no sound in {what} to line up with.")
    est = estimate_shift(gx, shotsound.decode(src, 1))
    if not est["ok"]:
        raise SystemExit(est["why"])
    fps = film_fps(d)
    target = seconds_to_frames(est["shift_seconds"], fps)          # where the recording should start, against the guide (the recording is measured as it is, not as it is placed now)
    cur = offset_frames(d, sid, k)
    delta = target - cur
    return {**est, "shot": sid, "person": name, "guide": what, "frames": target, "move_to_frame": target, "move_by_frames": delta, "fps_label": f"{fps.num / fps.den:g}",
            "words": (f"Move it {abs(delta)} frame{'s' if abs(delta) != 1 else ''} {'later' if delta > 0 else 'earlier'} to line up with {what}." if delta else f"It already lines up with {what}.")
                     + ("" if est["reliable"] else " This is not a confident match: listen, and do not trust it blindly.")}


# ---------------------------------------------------------------- ADR

def adr_mark(d: str, shot: str, speaker: str, needs=True, reason: str = "") -> dict:
    """Mark a line as needing ADR (to be replaced with a better recording), or take the mark off. Nothing else changes."""
    sid, k, name, rec, shot_s = _line(d, shot, speaker)
    why = " ".join(str(reason or "").split())[:NOTE]

    def change(r):
        if needs is True:
            r["adr"].setdefault(sid, {})[k] = {"needs": True, "reason": why, "at": int(time.time())}
        else:
            (r["adr"].get(sid) or {}).pop(k, None)
            if sid in r["adr"] and not r["adr"][sid]:
                r["adr"].pop(sid)
    _update(d, change)
    return get(d, sid, speaker)


def adr_list(d: str) -> dict:
    """Lines marked as needing ADR, and recordings the audio inspector found a problem in that ADR could fix. Free; reads recordings, changes nothing."""
    from . import audioqa as Q
    V._film(d)
    marks = _load(d)["adr"]
    contracts = V._contracts(d)
    fixable = {"clipping", "noise", "dropout", "click", "long_silence", "silent", "longer_than_shot"}
    rows, count = [], 0
    for sid, entries in sorted(V._meta(d)["shots"].items()):
        for e in entries:
            m = (marks.get(sid) or {}).get(e.get("key")) or {}
            reasons = [f"you marked it: {m['reason']}" if m.get("reason") else "you marked it"] if m.get("needs") else []
            path = V.inside(d, e.get("file"))
            if path and count < Q.MAX_FILES:
                count += 1
                it = Q.inspect_file(path, "voice", f"{e.get('speaker')} in {sid}", with_loudness=False)
                dur = float(((contracts.get(sid) or {}).get("generation") or {}).get("duration") or 0)
                if it["ok"] and dur and it["metrics"]["seconds"] > dur + 0.05:
                    it["findings"].append({"code": "longer_than_shot", "what": f"It is {it['metrics']['seconds']} s and the shot is {dur} s."})
                reasons += [f["what"] for f in it["findings"] if f["code"] in fixable]
            if reasons:
                takes = sorted(f for f in (os.listdir(os.path.join(d, "voice", "_generated")) if os.path.isdir(os.path.join(d, "voice", "_generated")) else [])
                               if f.startswith(f"{sid}-ad") and f.endswith(".wav") and ((V._read(os.path.join(d, "voice", "_generated", f[:-4] + ".json"), {}) or {}).get("key") == e.get("key")))
                rows.append({"shot": sid, "person": e.get("speaker"), "key": e.get("key"), "marked": bool(m.get("needs")), "reasons": reasons, "adr_takes": len(takes)})
    return {"lines": rows, "marked": sum(1 for r in rows if r["marked"]),
            "note": "The reasons come from the audio inspector's measurements and from your own marks. A reason is a place to listen, not a verdict."}


def adr_take(d: str, shot: str, speaker: str, recording: str, performed_by: str = "", note: str = "") -> dict:
    """Add an ADR retake of a line as a new take beside the others: your recording is kept as it came, and a copy is made at the film's sound format. Nothing is replaced and nothing is attached; choose the
    take in Line Studio when it is better. The same recording is not added twice."""
    from . import revoice as R
    sid, k, name, rec, shot_s = _line(d, shot, speaker)
    full, _ = R._resolve(d, recording)
    info = V.probe(full)
    if not info["ok"]:
        raise SystemExit(info["why"])
    digest = R._sha(full)
    keep = R._copy_in(d, full, "voice/_adr", digest)
    out = _generated(d, sid, "ad", hashlib.sha256(json.dumps([digest, sid, k]).encode()).hexdigest())
    cached = os.path.isfile(out) and os.path.isfile(out[:-4] + ".json")
    if not cached:
        import soundfile as sf
        x = shotsound.decode(os.path.join(d, *keep.split("/")), 2)
        if not len(x):
            raise SystemExit("FilmCrafter cannot read any sound in that recording.")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        sf.write(out + ".part.wav", x, RATE, subtype="PCM_16")
        os.replace(out + ".part.wav", out)
        V._write(out[:-4] + ".json", {"kind": "adr", "shot": sid, "key": k, "speaker": name, "text": "", "voice_name": "ADR retake", "performed_by": " ".join(str(performed_by or "").split())[:80] or "a person",
                                      "note": " ".join(str(note or "").split())[:NOTE], "original": keep, "original_sha256": digest, "original_name": os.path.basename(full)[:120], "seconds": round(len(x) / RATE, 3),
                                      "at": int(time.time())})
    return {"shot": sid, "person": name, "take": _rel(d, out), "original": keep, "seconds": info["seconds"], "cached": cached, "attached": False, "next": "Listen to it next to the others, then choose it as the take for the shot."}


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["get", "nudge", "fit_plan", "fit_make", "align", "adr_mark", "adr_list", "adr_take"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        s, w = x.get("shot", ""), x.get("speaker", "")
        if a.action == "get":
            res = get(d, s, w)
        elif a.action == "nudge":
            res = nudge(d, s, w, x.get("frames"), x.get("to_frame"))
        elif a.action == "fit_plan":
            res = fit_plan(d, s, w, x.get("target_seconds"))
        elif a.action == "fit_make":
            res = fit_make(d, s, w, x.get("target_seconds"), x.get("tempo"), x.get("allow_extreme") is True)
        elif a.action == "align":
            res = align(d, s, w, x.get("guide"))
        elif a.action == "adr_mark":
            res = adr_mark(d, s, w, x.get("needs") is not False, x.get("reason", ""))
        elif a.action == "adr_list":
            res = adr_list(d)
        else:
            res = adr_take(d, s, w, x.get("recording", ""), x.get("performed_by", ""), x.get("note", ""))
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
