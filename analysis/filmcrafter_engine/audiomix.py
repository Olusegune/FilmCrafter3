"""Mixing the planned sound (audio cues) into the film's soundtrack, and previewing a scene's mix.

The film's soundtrack so far (the song, each shot's own sound layers, the recorded and spoken voices) is the BASE. The approved cues of the plan (sound effects, ambience, music: see audiocues.py)
are laid on top of it at their places, with their level and fades; music and ambience dip under the voices (ducking); then a peak limiter keeps the sum from clipping and, if the person asked for
one, the whole film is brought to a target loudness. Nothing is changed in any source file: every sound is read, never written, and a film with no approved cue is not touched at all.

Memory: the film is mixed in blocks of BLOCK seconds, so a long film uses about the same memory as a short one (a long sound is read a block at a time, a short one is kept once).

  <Film>/audio/mix.json   {schema, ducking_db, duck_attack, duck_release, target_lufs, peak_db, mute_lanes[], solo}
                          ducking_db: how far music and ambience dip while someone speaks (0 = no dip); target_lufs: null leaves the level alone; peak_db: the ceiling (never above -0.1)
                          mute_lanes are left out of the film (and the preview); solo only narrows the PREVIEW and never changes the film.

  python -m filmcrafter_engine.audiomix <settings|set_settings|preview> <film_dir> --data '{...}'
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

from . import audiocues as Q
from . import audiolib as AL
from . import safeio

RATE = 44100
BLOCK = 30.0                       # seconds mixed at a time
CACHE_MAX = 120.0                  # a sound up to this long is read once and kept; a longer one is read a block at a time
DEFAULTS = {"schema": 1, "ducking_db": -12.0, "duck_attack": 0.15, "duck_release": 0.6, "target_lufs": None, "peak_db": -1.0, "mute_lanes": [], "solo": None}
LANES = ("dialogue", "foley", "sfx", "ambience", "music")        # foley: the sounds made for what a shot shows (sounddesign.py); a cue with no `foley` mark is an ordinary effect
VOICE_MARGIN = (0.1, 0.2)          # seconds the ducking starts before a voice and stays after it
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def emit(**kw) -> None:
    try:
        print(json.dumps(kw), flush=True)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- the settings

def _path(d: str) -> str:
    return os.path.join(d, "audio", "mix.json")


def _ok(x) -> bool:
    return isinstance(x, dict)


def _num(v, lo, hi, default, what):
    if v is None:
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise SystemExit(f"{what} must be a number.")
    if not (lo <= x <= hi):
        raise SystemExit(f"{what} must be between {lo:g} and {hi:g}.")
    return x


def settings(d: str) -> dict:
    s = {**DEFAULTS, **{k: v for k, v in (safeio.read_json(_path(d), {}, check=_ok) or {}).items() if k in DEFAULTS}}
    s["mute_lanes"] = [x for x in s["mute_lanes"] if x in LANES]
    s["solo"] = s["solo"] if s["solo"] in LANES else None
    return s


def set_settings(d: str, data: dict) -> dict:
    """Change the mix settings. Only the known ones are taken, each checked; the cues and the sound files are not touched."""
    Q._film(d)
    cur = settings(d)
    if "ducking_db" in data:
        cur["ducking_db"] = round(_num(data["ducking_db"], -30, 0, -12.0, "The dip under voices"), 1)
    if "duck_attack" in data:
        cur["duck_attack"] = round(_num(data["duck_attack"], 0.02, 2, 0.15, "The dip's speed"), 2)
    if "duck_release" in data:
        cur["duck_release"] = round(_num(data["duck_release"], 0.05, 5, 0.6, "The return's speed"), 2)
    if "target_lufs" in data:
        cur["target_lufs"] = None if data["target_lufs"] in (None, "") else round(_num(data["target_lufs"], -30, -9, -16.0, "The loudness target"), 1)
    if "peak_db" in data:
        cur["peak_db"] = round(_num(data["peak_db"], -12, -0.1, -1.0, "The peak ceiling"), 1)
    if "mute_lanes" in data:
        lanes = data["mute_lanes"] if isinstance(data["mute_lanes"], list) else []
        cur["mute_lanes"] = [x for x in LANES if x in lanes]
    if "solo" in data:
        if data["solo"] not in (None, "", *LANES):
            raise SystemExit("Choose a lane to solo, or none.")
        cur["solo"] = data["solo"] or None
    safeio.write_json(_path(d), cur)
    return settings(d)


# ---------------------------------------------------------------- where each cue sits on the film

def placements(d: str, shot_times: dict, duration: float, st: dict | None = None, only_scene: int | None = None, preview: bool = False) -> tuple[list[dict], list[dict]]:
    """The cues that will be heard: [{cue, path, start, end, gain, fade_in, fade_out, loop, duck, asset_seconds}] and the ones left out with a reason. `shot_times` maps a shot id to (start, end)
    seconds on the film. A cue is heard only when it is approved, not muted, in a lane that is not muted, its sound file is there and its shot or scene is in the film."""
    st = st or settings(d)
    lib = AL.load(d)
    assets = {a["id"]: a for a in lib["assets"]}
    shots = Q._shots(d)
    scene_of = {sid: int(s["scene"]) for sid, s in shots.items()}
    spans: dict[int, list[float]] = {}
    for sid, (a, b) in shot_times.items():
        n = scene_of.get(sid)
        if n is not None:
            lo, hi = spans.get(n, [a, b])
            spans[n] = [min(lo, a), max(hi, b)]
    data = safeio.read_json(Q._path(d), {"cues": []}, check=Q._ok)
    out, skipped = [], []
    solo = st["solo"] if (only_scene is not None or preview) else None     # solo narrows a preview only; the finished film ignores it
    for c in data.get("cues", []):
        cid = c.get("id")
        if only_scene is not None and int(c.get("scene", 0)) != int(only_scene):
            continue
        if c.get("approval") != "approved" or not c.get("asset_id"):
            if c.get("approval") == "approved":
                skipped.append({"cue": cid, "why": "It has no sound yet."})
            continue
        lane = "foley" if c.get("foley") and c.get("kind", "sfx") == "sfx" else c.get("kind", "sfx")
        if c.get("muted") or lane in st["mute_lanes"] or (solo and lane != solo):
            continue
        a = assets.get(c["asset_id"])
        path = os.path.join(d, *a["file"].split("/")) if a else None
        if not a or not os.path.isfile(path):
            skipped.append({"cue": cid, "why": "Its sound is missing from the library."})
            continue
        anchor = shot_times.get(c["shot"]) if c.get("shot") else (tuple(spans[int(c["scene"])]) if int(c.get("scene", 0)) in spans else None)
        if not anchor:
            skipped.append({"cue": cid, "why": "Its shot or scene is not in this film."})
            continue
        start = anchor[0] + float(c.get("start") or 0)
        if c.get("duration"):
            length = float(c["duration"])
        elif c.get("loop"):
            length = max(0.0, anchor[1] - start)
        else:
            length = float(a["seconds"])
        if not c.get("loop"):
            length = min(length, float(a["seconds"]))
        end = min(start + length, duration)
        if end - start < 0.02 or start >= duration:
            skipped.append({"cue": cid, "why": "It falls outside the film."})
            continue
        duck = c.get("ducking") == "on" or (c.get("ducking", "auto") == "auto" and lane in ("music", "ambience"))
        out.append({"cue": cid, "path": path, "start": start, "end": end, "gain": 10 ** (float(c.get("gain_db") or 0) / 20), "fade_in": float(c.get("fade_in") or 0), "fade_out": float(c.get("fade_out") or 0),
                    "loop": bool(c.get("loop")), "duck": duck, "asset_seconds": float(a["seconds"]), "lane": lane, "pan": max(-1.0, min(1.0, float(c.get("pan") or 0)))})
    return out, skipped


def pan_gains(pan: float):
    """Left and right gains for a balance from -1 (all left) to 1 (all right): the centre is untouched, and the far side fades out smoothly (a cosine law), so a sound never gets louder by moving.
    This is a stereo balance, not a 3D position and not a spatial-audio format."""
    import numpy as np
    p = max(-1.0, min(1.0, float(pan)))
    return np.array([1.0 if p <= 0 else np.cos(p * np.pi / 2), 1.0 if p >= 0 else np.cos(-p * np.pi / 2)], dtype=np.float32)


def film_of(d: str) -> str | None:
    """The film folder for a folder the exporter hands over: the film itself, or its render project (film/render). None for a project that is not a film (no cues exist there)."""
    d = os.path.abspath(d)
    if os.path.isfile(os.path.join(d, "film.json")):
        return d
    parent = os.path.dirname(d)
    return parent if os.path.basename(d) == "render" and os.path.isfile(os.path.join(parent, "film.json")) else None


def film_windows(film: str):
    """For a film folder (not its render project): when each person speaks inside a shot, from the film's own voice records. Same layout as the render project's: one after another with a short gap."""
    from . import voiceover as V
    by_shot = {s["id"]: [p for p in s["people"] if p.get("recording")] for s in V.status(film)["shots"]}

    def windows(sid: str) -> list[dict]:
        out, at = [], 0.0
        for p in by_shot.get(sid, []):
            sec = float(p["recording"]["seconds"])
            out.append({"speaker": p["name"], "start": at, "end": at + sec, "file": p["recording"]["file"]})
            at += sec + V.GAP
        return out
    return windows


def dialogue_spans(d: str, shot_times: dict, windows=None) -> list[tuple[float, float]]:
    """When someone is speaking on the film: each person's recording within each shot, where the film's sound puts it."""
    from . import voiceover as V
    windows = windows or (lambda sid: V.windows(d, sid))
    spans = []
    for sid, (a, b) in shot_times.items():
        for w in windows(sid):
            s0, s1 = a + w["start"], min(b, a + w["end"])
            if s1 > s0:
                spans.append((max(0.0, s0 - VOICE_MARGIN[0]), s1 + VOICE_MARGIN[1]))
    return sorted(spans)


def duck_envelope(spans: list[tuple[float, float]], t0: float, n: int, st: dict):
    """The level music and ambience are held to over n samples starting at second t0: 1 away from voices, down to the dip while someone speaks, gliding in and out."""
    import numpy as np
    g = np.ones(n, dtype=np.float32)
    if not spans or st["ducking_db"] >= -0.01:
        return g
    low = 10 ** (st["ducking_db"] / 20)
    t = t0 + np.arange(n, dtype=np.float64) / RATE
    att, rel = st["duck_attack"], st["duck_release"]
    for a, b in spans:
        if b + rel < t0 or a - att > t0 + n / RATE:
            continue
        g = np.minimum(g, np.interp(t, [a - att, a, b, b + rel], [1.0, low, low, 1.0], left=1.0, right=1.0).astype(np.float32))
    return g


# ---------------------------------------------------------------- reading a sound

class _Source:
    """A cue's sound as samples, by the asset's own time. Short sounds are read once; long ones a block at a time."""

    def __init__(self, path: str, seconds: float):
        self.path, self.seconds, self.cache, self.block = path, seconds, None, (None, None)
        if seconds <= CACHE_MAX:
            from .shotsound import decode
            self.cache = decode(path, 2)

    def get(self, a: float, n: int, loop: bool):
        """n samples from asset time `a` (seconds), looping when asked; zeros past the end otherwise."""
        import numpy as np
        out = np.zeros((n, 2), dtype=np.float32)
        total = None
        if self.cache is not None:
            total = len(self.cache)
        else:
            total = int(self.seconds * RATE)
        if total <= 0:
            return out
        i = int(round(a * RATE))
        got = 0
        while got < n:
            pos = i + got
            if loop:
                pos %= total
            elif pos >= total:
                break
            take = min(n - got, total - pos)
            out[got:got + take] = self._read(pos, take)
            got += take
            if not loop:
                break
        return out

    def _read(self, pos: int, n: int):
        import numpy as np
        if self.cache is not None:
            x = self.cache[pos:pos + n]
        else:
            from .shotsound import decode
            x = decode(self.path, 2, start=pos / RATE, seconds=n / RATE)
        if len(x) < n:
            x = np.concatenate([x, np.zeros((n - len(x), 2), dtype=np.float32)])
        return x[:n]


def _fade_gain(i0: int, n: int, s0: int, s1: int, fi: int, fo: int):
    """Per-sample level of a cue between its first sample s0 and last s1 over block samples [i0, i0+n): linear fades at both edges, never less than a few ms (so nothing clicks)."""
    import numpy as np
    idx = np.arange(i0, i0 + n)
    g = np.ones(n, dtype=np.float32)
    fi, fo = max(fi, int(0.005 * RATE)), max(fo, int(0.01 * RATE))
    g = np.minimum(g, np.clip((idx - s0) / float(fi), 0, 1).astype(np.float32))
    g = np.minimum(g, np.clip((s1 - idx) / float(fo), 0, 1).astype(np.float32))
    return g


# ---------------------------------------------------------------- the mix

def mix_cues(d: str, base_path: str | None, shot_times: dict, duration: float, out: str, st: dict | None = None, only_scene: int | None = None, progress=None, windows=None, preview: bool = False) -> dict | None:
    """The base soundtrack with the approved cues laid on it, ducked, limited and (if asked) levelled. `d` is the film or its render project. Returns None when no cue is heard (then nothing
    is changed). Writes a WAV to `out`."""
    import numpy as np
    import soundfile as sf
    film = film_of(d)
    if film is None or not os.path.isfile(Q._path(film)):
        return None                                              # not a film, or a film with no plan: the soundtrack is left exactly as it is
    st = st or settings(film)
    plan, skipped = placements(film, shot_times, duration, st, only_scene, preview)
    if not plan:
        return {"none": True, "skipped": skipped} if skipped else None
    total = int(round(duration * RATE))
    spans = dialogue_spans(d, shot_times, windows)
    sources = {p["path"]: _Source(p["path"], p["asset_seconds"]) for p in plan}
    base = sf.SoundFile(base_path) if base_path and os.path.isfile(base_path) else None
    raw = out + ".raw.wav"
    block = int(BLOCK * RATE)
    peak_in = 0.0
    try:
        with sf.SoundFile(raw, "w", RATE, 2, subtype="FLOAT") as w:
            for i0 in range(0, total, block):
                n = min(block, total - i0)
                mix = np.zeros((n, 2), dtype=np.float32)
                if base is not None:
                    base.seek(min(i0, base.frames))
                    x = base.read(n, dtype="float32", always_2d=True)
                    if x.shape[1] == 1:
                        x = np.repeat(x, 2, axis=1)
                    mix[: len(x)] = x[:, :2]
                plain = np.zeros((n, 2), dtype=np.float32)
                ducked = np.zeros((n, 2), dtype=np.float32)
                for p in plan:
                    s0, s1 = int(round(p["start"] * RATE)), int(round(p["end"] * RATE))
                    a, b = max(s0, i0), min(s1, i0 + n)
                    if b <= a:
                        continue
                    seg = sources[p["path"]].get((a - s0) / RATE, b - a, p["loop"])
                    seg = seg * _fade_gain(a, b - a, s0, s1, int(p["fade_in"] * RATE), int(p["fade_out"] * RATE))[:, None] * np.float32(p["gain"])
                    if p.get("pan"):
                        seg = seg * pan_gains(p["pan"])[None, :]
                    (ducked if p["duck"] else plain)[a - i0:b - i0] += seg
                env = duck_envelope(spans, i0 / RATE, n, st)
                mix += plain + ducked * env[:, None]
                peak_in = max(peak_in, float(np.max(np.abs(mix))) if n else 0.0)
                w.write(mix)
                if progress:
                    progress(min(1.0, (i0 + n) / total))
        if st.get("raw_float"):                                  # a stem for the pro export: the mix as it is before the master stage, 32-bit float, no limiter and no loudness change
            os.replace(raw, out)
            info = {"limiter": False, "target_lufs": None, "loudness_before": None}
        else:
            info = _finish(raw, out, st)
    finally:
        if base is not None:
            base.close()
        if os.path.exists(raw):
            os.remove(raw)
    return {"path": out, "cues": len(plan), "skipped": skipped, "ducked": bool(spans) and st["ducking_db"] < -0.01 and any(p["duck"] for p in plan), "peak_before_db": _db(peak_in), **info}


def _db(x: float) -> float:
    import math
    return round(20 * math.log10(max(x, 1e-6)), 1)


def _ffmpeg() -> str:
    from .export import ffmpeg
    return ffmpeg()


def _finish(raw: str, out: str, st: dict) -> dict:
    """The last stage: a peak limiter under the ceiling, and, when a target was set, the whole film brought to that loudness (measured first, then applied as one steady gain). Falls back to plain
    peak scaling if ffmpeg cannot do it, so the result never clips either way."""
    ceiling = 10 ** (st["peak_db"] / 20)
    limiter = f"alimiter=limit={ceiling:.4f}:attack=5:release=60:level=disabled"
    chain = limiter
    measured = None
    try:
        if st["target_lufs"] is not None:
            tp = min(st["peak_db"], -0.5)
            r = subprocess.run([_ffmpeg(), "-hide_banner", "-nostats", "-i", raw, "-af", f"loudnorm=I={st['target_lufs']}:TP={tp}:LRA=11:print_format=json", "-f", "null", "-"],
                               capture_output=True, text=True, creationflags=NO_WINDOW, timeout=1800)
            m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
            if m:
                j = json.loads(m.group(0))
                if all(j.get(k) not in (None, "-inf", "inf") for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")):
                    measured = j
                    chain = (f"loudnorm=I={st['target_lufs']}:TP={tp}:LRA=11:measured_I={j['input_i']}:measured_TP={j['input_tp']}:measured_LRA={j['input_lra']}:"
                             f"measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true,{limiter}")
        r = subprocess.run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", raw, "-af", chain, "-ar", str(RATE), "-c:a", "pcm_s16le", out], capture_output=True, creationflags=NO_WINDOW, timeout=1800)
        if r.returncode == 0 and os.path.isfile(out):
            return {"limiter": True, "target_lufs": st["target_lufs"] if measured else None, "loudness_before": float(measured["input_i"]) if measured else None}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        pass
    return _fallback(raw, out, ceiling)


def _fallback(raw: str, out: str, ceiling: float) -> dict:
    """Without ffmpeg's help: one steady gain so the loudest sample sits at the ceiling (if it was above it), written in blocks."""
    import numpy as np
    import soundfile as sf
    peak = 0.0
    with sf.SoundFile(raw) as r:
        for x in r.blocks(blocksize=RATE * 10, dtype="float32"):
            peak = max(peak, float(np.max(np.abs(x))))
    g = ceiling / peak if peak > ceiling else 1.0
    with sf.SoundFile(raw) as r, sf.SoundFile(out, "w", RATE, 2, subtype="PCM_16") as w:
        for x in r.blocks(blocksize=RATE * 10, dtype="float32"):
            w.write(np.clip(x * g, -1, 1))
    return {"limiter": "peak scaling", "target_lufs": None, "loudness_before": None}


# ---------------------------------------------------------------- previewing one scene

def _voices_base(film: str, times: dict, duration: float, out: str) -> str | None:
    """The scene's recorded and spoken voices laid at their places on a silent bed (written in blocks). None when the scene has no voice."""
    import numpy as np
    import soundfile as sf
    from . import voiceover as V
    from .shotsound import decode
    rows = []
    for s in V.status(film)["shots"]:
        if s["id"] in times:
            at = times[s["id"]][0]
            for p in s["people"]:
                if p.get("recording"):
                    rows.append((at, V.inside(film, p["recording"]["file"]), times[s["id"]][1]))
                    at += float(p["recording"]["seconds"]) + V.GAP
    rows = [(a, f, e) for a, f, e in rows if f]
    if not rows:
        return None
    track = np.zeros((int(duration * RATE), 2), dtype=np.float32)
    for a, f, e in rows:
        x = decode(f, 2)[: max(0, int(round((e - a) * RATE)))]
        i = int(round(a * RATE))
        track[i:i + len(x)] += x[: len(track) - i]
    peak = float(np.max(np.abs(track))) if len(track) else 0.0
    if peak > 0.98:
        track *= 0.98 / peak
    sf.write(out, track, RATE, subtype="PCM_16")
    return out


WHOLE_MAX = 20 * 60.0              # a whole-film preview is built in memory: longer films are previewed a scene at a time


def preview(d: str, scene, solo: str | None = None) -> dict:
    """A short audio mix of one scene: the voices that are there, with the scene's approved cues on top, as the finished film would sound. Written to cache/audio-preview; nothing in the film changes."""
    import numpy as np
    import soundfile as sf
    Q._film(d)
    whole = scene in ("all", "film", "whole")
    every = sorted(Q._shots(d).values(), key=lambda s: (int(s["scene"]), s["index"]))
    shots = every if whole else [s for s in every if int(s["scene"]) == int(scene)]
    if not shots:
        raise SystemExit("There are no shots in the film yet." if whole else "That scene isn't in the film.")
    times, at = {}, 0.0
    for s in shots:
        times[s["id"]] = (at, at + float(s["duration"]))
        at += float(s["duration"])
    duration = at
    if whole and duration > WHOLE_MAX:
        raise SystemExit(f"The film is {duration / 60:.0f} minutes long: preview it a scene at a time.")
    st = settings(d)
    if solo not in (None, "", *LANES):
        raise SystemExit("Choose a lane to solo.")
    st = {**st, "solo": solo or None, "target_lufs": None}
    work = os.path.join(d, "cache", "audio-preview")
    os.makedirs(work, exist_ok=True)
    n = "film" if whole else int(scene)
    silent = os.path.join(work, f"scene{n}-silence.wav")
    sf.write(silent, np.zeros((int(duration * RATE), 2), dtype=np.float32), RATE, subtype="PCM_16")
    voices = _voices_base(d, times, duration, os.path.join(work, f"scene{n}-voices.wav"))
    base = voices if (voices and st["solo"] in (None, "dialogue")) else silent
    if st["solo"] == "dialogue":
        st["mute_lanes"] = [x for x in LANES if x != "dialogue"]
    out = os.path.join(work, f"scene{n}{'-' + st['solo'] if st['solo'] else ''}.wav")
    r = mix_cues(d, base, times, duration, out, st, only_scene=None if whole else n, windows=film_windows(d), preview=True)
    if not r or r.get("none"):
        return {"file": os.path.relpath(base, d).replace(os.sep, "/"), "seconds": round(duration, 1), "cues": 0, "skipped": (r or {}).get("skipped", []), "solo": st["solo"], "voices": bool(voices), "whole": whole}
    return {"file": os.path.relpath(out, d).replace(os.sep, "/"), "seconds": round(duration, 1), "cues": r["cues"], "skipped": r["skipped"], "ducked": r["ducked"], "solo": st["solo"], "voices": bool(voices), "whole": whole}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="audiomix")
    ap.add_argument("action", choices=["settings", "set_settings", "preview"])
    ap.add_argument("film")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        d = os.path.abspath(a.film)
        if a.action == "settings":
            Q._film(d)
            res = settings(d)
        elif a.action == "set_settings":
            res = set_settings(d, x)
        else:
            res = preview(d, x.get("scene", 0), x.get("solo"))
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
