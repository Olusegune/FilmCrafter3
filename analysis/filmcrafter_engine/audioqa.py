"""The audio quality inspector: objective measurements of the film's sound, reported as findings you can act on.

It measures what can be measured and says what it cannot. For each sound file (your recordings, the sounds in the cues, and optionally a finished film) it reports peak and true peak, loudness, clipping,
digital silence and long silences, the noise floor, short dropouts, clicks (sudden jumps), DC offset and whether the two channels cancel when folded to mono. Across a film it also reports a line recorded
much louder or quieter than the same person's others, more than one voice or model behind one person's lines, a recording longer than its shot, and a cue that starts or stops abruptly with no fade.

  fix    the sound is wrong (silent, heavily clipped, many dropouts)
  look   worth a listen (a few clips, a click, a noisy room, a long silence in a recording, a mono fold-down that loses level)
  note   for information (a peak at the ceiling, a small DC offset)

**Not measured, and never claimed:** how clear the speech is, how good anything sounds, accent or voice authenticity, whether the mouth matches the words, how loud the stems are against each other. There is
no "quality score". The limits below are plain numbers chosen for this tool, not an industry standard: they say where to listen, not what is right.

Free, local and read-only: it only reads sound files and writes nothing.

  python -m filmcrafter_engine.audioqa <inspect|film> <film> --data '{...}'
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import shotsound, voiceover as V

RATE = shotsound.RATE
LIMITS = {
    "clip_level": 0.999, "clip_min_run": 3, "clip_look_runs": 1, "clip_fix_runs": 20,
    "peak_note_db": -0.1, "true_peak_look_db": -1.0,
    "silent_peak_db": -80.0,
    "long_silence_s": 2.0, "silence_db": -70.0,
    "noise_voice_db": -50.0,
    "dropout_ms": (5, 300), "dropout_neighbour_db": -45.0, "dropout_fix_count": 3,
    "click_jump": 0.15, "click_times_median": 8.0,
    "dc": 0.02, "mono_loss_db": -6.0,
    "loudness_target_tolerance_lu": 1.5,
    "voice_level_outlier_db": 6.0, "voice_level_min_takes": 3,
    "edge_level": 0.05, "edge_ms": 5,
}
MAX_FILES = 60
MAX_SECONDS = 60 * 60
NOT_MEASURED = ["How clear the speech is.", "How good anything sounds.", "Whether an accent or a voice is authentic.", "Whether the mouth matches the words.", "How loud the stems are against each other."]


def emit(**kw) -> None:
    try:
        print(json.dumps(kw, ensure_ascii=False), flush=True)
    except (OSError, ValueError):
        pass


def _db(x: float) -> float:
    import math
    return round(20 * math.log10(max(float(x), 1e-6)), 1)


def _runs(mask, min_len: int):
    """Start and end (exclusive) index of each run of True at least `min_len` long."""
    import numpy as np
    if not len(mask):
        return []
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return [(int(a), int(b)) for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)) if b - a >= min_len]


# ---------------------------------------------------------------- measuring (pure: a sound in, numbers out)

def measure(x, rate: int = RATE) -> dict:
    """Measurements of a sound `x` shaped (samples, channels), floats from -1 to 1. No files, no ffmpeg."""
    import numpy as np
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    n = len(x)
    if n == 0:
        return {"seconds": 0.0, "empty": True}
    mono = x.mean(axis=1)
    out: dict = {"seconds": round(n / rate, 2), "channels": int(x.shape[1])}
    peak = float(np.max(np.abs(x)))
    out["peak_db"] = _db(peak)
    mask = np.max(np.abs(x), axis=1) >= LIMITS["clip_level"]
    runs = _runs(mask, LIMITS["clip_min_run"])
    out["clip_runs"] = len(runs)
    out["clip_at"] = [round(a / rate, 2) for a, _ in runs[:5]]
    w = max(1, int(0.05 * rate))
    k = n // w
    if k:
        blocks = mono[: k * w].reshape(k, w)
        rms_db = 20 * np.log10(np.maximum(np.sqrt(np.mean(np.square(blocks), axis=1)), 1e-6))
    else:
        rms_db = np.array([_db(float(np.sqrt(np.mean(np.square(mono)))))])
    out["rms_db"] = round(float(20 * np.log10(max(float(np.sqrt(np.mean(np.square(mono)))), 1e-6))), 1)
    active = rms_db > -50.0
    out["active_ratio"] = round(float(np.mean(active)), 3)
    loud = rms_db > float(np.max(rms_db)) - 12.0                                  # the loud parts: within 12 dB of the loudest stretch
    out["speech_level_db"] = round(float(np.mean(rms_db[loud])), 1) if float(np.max(rms_db)) > -70.0 else None      # their average level, for comparing one recording with another
    min_len = max(1, int(LIMITS["long_silence_s"] / 0.05))
    sil = []
    for a, b in _runs(rms_db < LIMITS["silence_db"], min_len):
        where = "start" if a == 0 else "end" if b >= len(rms_db) else "inside"
        sil.append({"at": round(a * 0.05, 2), "length": round((b - a) * 0.05, 2), "where": where})
    out["silences"] = sil[:8]
    live = rms_db[rms_db > -90.0]
    floor = float(np.percentile(live, 10)) if len(live) >= 5 else None
    # a noise floor can only be read where there are quiet moments between the loud ones; a sound that never pauses has none to measure
    out["noise_floor_db"] = round(floor, 1) if floor is not None and loud.any() and float(np.median(rms_db[loud])) - floor >= 6.0 else None
    w5 = max(1, int(0.005 * rate))
    k5 = n // w5
    drops = []
    if k5:
        quiet = np.max(np.abs(mono[: k5 * w5].reshape(k5, w5)), axis=1) < 1e-4
        lo, hi = LIMITS["dropout_ms"]
        for a, b in _runs(quiet, max(1, lo // 5)):
            if (b - a) * 5 > hi:
                continue
            before = mono[max(0, a * w5 - w): a * w5]
            after = mono[b * w5: b * w5 + w]
            if len(before) and len(after) and _db(float(np.sqrt(np.mean(np.square(before))))) > LIMITS["dropout_neighbour_db"] and _db(float(np.sqrt(np.mean(np.square(after))))) > LIMITS["dropout_neighbour_db"]:
                drops.append({"at": round(a * w5 / rate, 3), "ms": (b - a) * 5})
    out["dropouts"] = drops[:10]
    out["dropout_count"] = len(drops)
    clicks = []
    if n > 2 * w:
        d = np.abs(np.diff(mono))
        kk = len(d) // w
        if kk:
            med = np.median(d[: kk * w].reshape(kk, w), axis=1)
            thr = np.maximum(LIMITS["click_jump"], LIMITS["click_times_median"] * np.repeat(med, w))
            hit = np.flatnonzero(d[: kk * w] > thr)
            last = -10 ** 9
            for h in hit:
                if h - last > int(0.01 * rate):
                    clicks.append(round(float(h) / rate, 3))
                last = h
    out["click_count"] = len(clicks)
    out["clicks_at"] = clicks[:8]
    out["dc"] = round(float(abs(np.mean(mono))), 4)
    if x.shape[1] >= 2 and float(np.std(x[:, 0])) > 1e-6 and float(np.std(x[:, 1])) > 1e-6:
        l, r = x[:, 0], x[:, 1]
        side = float(np.sqrt(np.mean(np.square((l + r) / 2))))
        each = (float(np.sqrt(np.mean(np.square(l)))) + float(np.sqrt(np.mean(np.square(r))))) / 2
        out["mono_loss_db"] = _db(side / max(each, 1e-9)) if each > 1e-6 else 0.0
    else:
        out["mono_loss_db"] = 0.0
    return out


# ---------------------------------------------------------------- findings from measurements

def _f(sev: str, code: str, where: str, what: str, measured, limit=None) -> dict:
    return {"severity": sev, "code": code, "where": where, "what": what, "measured": measured, "limit": limit}


def findings(m: dict, role: str, where: str, loudness: dict | None = None, target_lufs: float | None = None) -> list[dict]:
    """The findings for one sound's measurements. `role` is voice, effect, music or mix: a quiet stretch means something different in each."""
    if m.get("empty"):
        return [_f("fix", "empty", where, "There is no sound in this file.", 0)]
    out: list[dict] = []
    L = LIMITS
    if m["peak_db"] < L["silent_peak_db"]:
        return [_f("fix", "silent", where, "This file is silent.", m["peak_db"], L["silent_peak_db"])]
    if m["clip_runs"] >= L["clip_look_runs"]:
        sev = "fix" if m["clip_runs"] >= L["clip_fix_runs"] else "look"
        out.append(_f(sev, "clipping", where, f"The sound is flattened at the top {m['clip_runs']} time{'s' if m['clip_runs'] != 1 else ''} (first at {', '.join(str(t) + ' s' for t in m['clip_at'][:3])}). Listen for harshness.", m["clip_runs"], L["clip_look_runs"]))
    elif m["peak_db"] > L["peak_note_db"]:
        out.append(_f("note", "peak", where, f"The loudest point is at the ceiling ({m['peak_db']} dBFS) with no flattening found.", m["peak_db"], L["peak_note_db"]))
    if loudness and loudness.get("true_peak_db") is not None and loudness["true_peak_db"] > L["true_peak_look_db"]:
        out.append(_f("look", "true_peak", where, f"The true peak is {loudness['true_peak_db']} dBFS, above {L['true_peak_look_db']}: some players and encoders can clip it.", loudness["true_peak_db"], L["true_peak_look_db"]))
    if role == "mix" and loudness and loudness.get("lufs") is not None and target_lufs is not None and abs(loudness["lufs"] - target_lufs) > L["loudness_target_tolerance_lu"]:
        out.append(_f("look", "loudness", where, f"The film measures {loudness['lufs']} LUFS and the target is {target_lufs}.", loudness["lufs"], target_lufs))
    inside = [s for s in m["silences"] if s["where"] == "inside"]
    if role == "voice" and inside:
        s = inside[0]
        out.append(_f("look", "long_silence", where, f"There is {s['length']} s of silence {s['at']} s into this recording{' (and more)' if len(inside) > 1 else ''}. Fine for a pause, wrong for a gap.", s["length"], L["long_silence_s"]))
    if role == "mix" and m["active_ratio"] < 0.1:
        out.append(_f("look", "almost_silent", where, "Almost all of this is silent.", m["active_ratio"], 0.1))
    if role == "voice" and m["noise_floor_db"] is not None and m["noise_floor_db"] > L["noise_voice_db"]:
        out.append(_f("look", "noise", where, f"The quietest parts sit at {m['noise_floor_db']} dBFS, so there is steady background noise under the voice.", m["noise_floor_db"], L["noise_voice_db"]))
    if m["dropout_count"]:
        out.append(_f("fix" if m["dropout_count"] >= L["dropout_fix_count"] else "look", "dropout", where, f"{m['dropout_count']} very short gap{'s' if m['dropout_count'] != 1 else ''} of digital silence inside loud sound (first at {m['dropouts'][0]['at']} s, {m['dropouts'][0]['ms']} ms).", m["dropout_count"], 0))
    if m["click_count"]:
        out.append(_f("look", "click", where, f"{m['click_count']} sudden jump{'s' if m['click_count'] != 1 else ''} in the waveform (first at {m['clicks_at'][0]} s), which usually sounds like a click.", m["click_count"], 0))
    if m["dc"] > L["dc"]:
        out.append(_f("note", "dc", where, f"The whole file is shifted off centre by {m['dc']}.", m["dc"], L["dc"]))
    if m["mono_loss_db"] < L["mono_loss_db"]:
        out.append(_f("look", "mono", where, f"Folded to mono this loses {abs(m['mono_loss_db'])} dB: the two sides partly cancel.", m["mono_loss_db"], L["mono_loss_db"]))
    return out


# ---------------------------------------------------------------- files

def _loudness(path: str) -> dict | None:
    try:
        from .export import measure_loudness
        return measure_loudness(path)
    except Exception:
        return None


def inspect_file(path: str, role: str = "mix", where: str | None = None, target_lufs: float | None = None, with_loudness: bool = True) -> dict:
    """Measure one sound file and say what is worth a listen. Reads the file; changes nothing."""
    where = where or os.path.basename(path)
    if not os.path.isfile(path):
        return {"where": where, "role": role, "ok": False, "why": "That file is not there.", "findings": [_f("fix", "missing", where, "That file is not there.", None)]}
    from .render import take_duration
    if take_duration(path) > MAX_SECONDS:
        return {"where": where, "role": role, "ok": False, "why": "That file is longer than an hour.", "findings": []}
    x = shotsound.decode(path, 2)
    if not len(x):
        return {"where": where, "role": role, "ok": False, "why": "FilmCrafter cannot read any sound in that file.", "findings": [_f("fix", "unreadable", where, "No sound could be read from this file.", None)]}
    m = measure(x, RATE)
    ld = _loudness(path) if with_loudness else None
    return {"where": where, "role": role, "ok": True, "metrics": m, "loudness": ld, "findings": findings(m, role, where, ld, target_lufs)}


def _edge_levels(path: str) -> tuple[float, float] | None:
    """The size of the first and the last few milliseconds of a sound: a sound that starts or stops at full level with no fade clicks."""
    import numpy as np
    x = shotsound.decode(path, 1)
    if not len(x):
        return None
    k = max(1, int(LIMITS["edge_ms"] / 1000 * RATE))
    return float(np.max(np.abs(x[:k]))), float(np.max(np.abs(x[-k:])))


def _film_dir(d: str) -> str:
    V._film(d)
    return d


def _within(d: str, rel: str) -> str | None:
    return V.inside(d, rel)


def film(d: str, file: str | None = None) -> dict:
    """Inspect the film's sound: its recordings and spoken lines, the sounds in its approved cues, and (if given) a finished film file; then the checks that need the whole film. Free, read-only."""
    from . import audiocues as Q, audiolib as AL, audiomix as M
    _film_dir(d)
    items: list[dict] = []
    notes: list[str] = []
    st = M.settings(d)
    target = st.get("target_lufs")
    if file:
        s = str(file).strip()
        full = os.path.abspath(s) if os.path.isabs(s) else _within(d, s)
        if not full:
            raise SystemExit("That file is not inside this film.")
        items.append(inspect_file(full, "mix", "The finished film: " + os.path.basename(full), target))
    meta = V._meta(d)
    contracts = V._contracts(d)
    by_person: dict[str, list[dict]] = {}
    count = 0
    for sid, entries in sorted(meta["shots"].items()):
        for e in entries:
            if count >= MAX_FILES:
                notes.append(f"Only the first {MAX_FILES} recordings were checked.")
                break
            path = _within(d, e.get("file"))
            if not path:
                continue
            count += 1
            it = inspect_file(path, "voice", f"{e.get('speaker') or e.get('key')} in {sid}", with_loudness=False)
            it["shot"], it["person"], it["file"] = sid, e.get("key"), e.get("file")
            items.append(it)
            if it["ok"]:
                by_person.setdefault(e.get("key"), []).append({"shot": sid, "speaker": e.get("speaker"), "level": it["metrics"]["speech_level_db"], "gen": e.get("gen"), "source": e.get("source")})
                dur = float(((contracts.get(sid) or {}).get("generation") or {}).get("duration") or 0)
                if dur and it["metrics"]["seconds"] > dur + 0.05:
                    it["findings"].append(_f("look", "longer_than_shot", it["where"], f"The recording is {it['metrics']['seconds']} s and the shot is {dur} s, so the end is cut off unless the shot is lengthened.", it["metrics"]["seconds"], dur))
    lib = {a["id"]: a for a in AL.load(d)["assets"]}
    seen: set[str] = set()
    cue_rows = [c for c in Q.listing(d)["cues"] if c.get("approval") == "approved" and c.get("asset_id") and not c.get("muted")]
    for c in cue_rows:
        a = lib.get(c["asset_id"])
        if not a or a["id"] in seen:
            continue
        if len(seen) >= MAX_FILES:
            notes.append(f"Only the first {MAX_FILES} cue sounds were checked.")
            break
        seen.add(a["id"])
        path = _within(d, a.get("file"))
        if path:
            it = inspect_file(path, c.get("kind") if c.get("kind") in ("music", "ambience", "sfx") else "effect", f"{a['name']} ({c.get('kind')})", with_loudness=False)
            it["asset"] = a["id"]
            items.append(it)
    for c in cue_rows:
        a = lib.get(c["asset_id"])
        path = _within(d, a["file"]) if a else None
        if not path or c.get("loop") or float(c.get("fade_in") or 0) > 0 or float(c.get("fade_out") or 0) > 0:
            continue
        e = _edge_levels(path)
        if e and max(e) > LIMITS["edge_level"]:
            which = "starts" if e[0] > LIMITS["edge_level"] else "stops"
            both = e[0] > LIMITS["edge_level"] and e[1] > LIMITS["edge_level"]
            items.append({"where": f"{a['name']} in scene {c.get('scene')}", "role": "edit", "ok": True, "asset": a["id"], "cue": c["id"], "metrics": {}, "findings": [
                _f("look", "abrupt_edit", f"{a['name']} in scene {c.get('scene')}", f"This sound {'starts and stops' if both else which} at full level with no fade, which can click. A short fade on the cue usually fixes it.", [round(e[0], 3), round(e[1], 3)], LIMITS["edge_level"])]})
    consistency = []
    for key, rows in sorted(by_person.items()):
        lv = [r["level"] for r in rows if r["level"] is not None]
        if len(lv) >= LIMITS["voice_level_min_takes"]:
            import numpy as np
            med = float(np.median(lv))
            for r in rows:
                if r["level"] is not None and abs(r["level"] - med) > LIMITS["voice_level_outlier_db"]:
                    consistency.append({"severity": "note", "code": "level_outlier", "where": f"{r['speaker']} in {r['shot']}", "person": key,
                                        "what": f"This line averages {r['level']} dBFS where {r['speaker']}'s lines usually sit around {round(med, 1)}. Listen: it may be a different room, microphone or take.", "measured": r["level"], "limit": round(med, 1), "confidence": "low"})
        makers = set()
        for r in rows:
            side = os.path.join(d, "voice", "_generated", (r["gen"] or "x")[:-4] + ".json") if r.get("gen") else None
            sc = V._read(side, None) if side else None
            makers.add((r.get("source") or "recording", (sc or {}).get("model"), (sc or {}).get("voice_id")))
        if len(makers) > 1:
            names = ", ".join(sorted(f"{s}{' / ' + m if m else ''}" for s, m, _ in makers))
            consistency.append({"severity": "look", "code": "voice_changed", "where": rows[0]["speaker"], "person": key, "what": f"{rows[0]['speaker']}'s lines come from more than one source or model: {names}. A listener may hear the difference.", "measured": len(makers), "limit": 1, "confidence": "high"})
    allf = [f for it in items for f in it["findings"]] + consistency
    summary = {sev: sum(1 for f in allf if f["severity"] == sev) for sev in ("fix", "look", "note")}
    summary["files"] = sum(1 for it in items if it.get("ok"))
    return {"summary": summary, "items": items, "consistency": consistency, "target_lufs": target, "not_measured": NOT_MEASURED, "limits": {k: v for k, v in LIMITS.items()}, "notes": notes,
            "says": ("Nothing here needs a second listen." if not summary["fix"] and not summary["look"] else f"{summary['fix']} to fix and {summary['look']} worth a listen.") + " These are measurements, not a quality score."}


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["film", "inspect"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        if a.action == "film":
            res = film(d, x.get("file"))
        else:
            _film_dir(d)
            s = str(x.get("file") or "").strip()
            full = os.path.abspath(s) if os.path.isabs(s) else _within(d, s)
            if not s or not full:
                raise SystemExit("Choose a sound file inside this film.")
            res = inspect_file(full, x.get("role") if x.get("role") in ("voice", "mix", "effect", "music", "ambience", "sfx") else "mix")
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
