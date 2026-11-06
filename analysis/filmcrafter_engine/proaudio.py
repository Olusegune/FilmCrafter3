"""Professional audio export: the film's sound as stems and mixes a sound editor or a mixing stage can open, with a cue sheet and an editable timeline.

One folder, `exports/audio/<title> <time>/`:

  stems/01 DIALOGUE.wav ...   one full-length file per lane (dialogue, foley, effects, ambience, music), 48 kHz and 24-bit by default, every one starting at the same point so they line up in any
                              editor; with the ducking, levels, fades and balance the film's mix uses, and no limiter and no loudness change (they are the mix *before* the master stage)
  mixes/<title> FINAL.wav     everything together, brought to a loudness target and kept under a peak ceiling by ONE steady gain (so the stems times that gain are the mix, exactly)
  mixes/<title> M&E.wav       the same without dialogue: music and effects, for dubbing into other languages
  <title> cue sheet.csv/json  every voice line and every sound: lane, name, shot, timecode in and out, level, balance, where the sound came from and its licence, and whether it is approved
  <title> audio.otio          OpenTimelineIO: each sound as a clip on a lane, pointing at copies of the original files in media/ (your originals are never touched)
  README.txt, report.json     what is here, how it was measured, and what was and was not checked

Files are Broadcast WAV (the `bext` chunk, with the start timecode as a time reference, the originator, a date and, for the mixes, the loudness), or plain WAV.

**Positions follow the film's shot list**: shots in scene order at their lengths, each person's recordings in order with the usual gap and moved by any frames set in Timing and ADR (the same
model as the Sound & Music preview). If you trimmed or re-timed shots in the Studio's cut, the finished film's picture may place them differently: use the hand-off's tracks for that cut. Nothing here
is claimed to import cleanly into any particular editor until it has been tried in that editor; the files are checked by reading them back (see `report.json`).

Free and local: nothing is sent anywhere and no model is used.

  python -m filmcrafter_engine.proaudio <plan|export> <film> --data '{...}'
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from fractions import Fraction

from . import audiocues as Q
from . import audiolib as AL
from . import audiomix as M
from . import edit_time as T
from . import safeio, shotsound
from . import voiceover as V
from .safe import file_name

RATE = shotsound.RATE
RATES = (44100, 48000, 96000)
BITS = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_f32le"}
STEMS = ("dialogue", "foley", "sfx", "ambience", "music")
LABEL = {"dialogue": "DIALOGUE", "foley": "FOLEY", "sfx": "EFFECTS", "ambience": "AMBIENCE", "music": "MUSIC"}
MIXES = ("final", "me")
FILM_MAX = 20 * 60.0
RIFF_MAX = 3_900_000_000
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
MEDIA_MAX = 400
LOOP_MAX = 100
TIMEOUT = 1800
NOT_CHECKED = ["Whether any particular editor imports these files without a prompt (the files are read back and measured here; no editor was opened).",
               "How the mix sounds.", "Loudness in the finished film's picture export (this is the film's sound laid out on the shot list)."]


def emit(**kw) -> None:
    try:
        print(json.dumps(kw, ensure_ascii=False), flush=True)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- the settings of one export

def parse_tc(text: str, fps: T.FrameRate) -> float:
    """hh:mm:ss:ff at the film's frame rate, in seconds. Whole frames only, and a frame number that exists."""
    parts = str(text or "").strip().split(":")
    if len(parts) != 4 or not all(p.isdigit() and len(p) <= 2 for p in parts):
        raise SystemExit("A start timecode is written hh:mm:ss:ff, for example 00:00:00:00 or 01:00:00:00.")
    h, m, s, f = (int(p) for p in parts)
    nominal = (fps.num + fps.den - 1) // fps.den
    if m > 59 or s > 59 or f >= nominal:
        raise SystemExit(f"That timecode does not exist at {nominal} frames a second.")
    return float((h * 3600 + m * 60 + s) + Fraction(f * fps.den, fps.num))


def clean_spec(x: dict | None) -> dict:
    x = x if isinstance(x, dict) else {}
    rate = x.get("rate", 48000)
    if isinstance(rate, bool) or rate not in RATES:
        raise SystemExit("Choose 44.1, 48 or 96 kHz.")
    bits = x.get("bits", 24)
    if isinstance(bits, bool) or bits not in BITS:
        raise SystemExit("Choose 16-bit, 24-bit or 32-bit float.")
    stems = x.get("stems")
    stems = list(STEMS) if stems is None else [s for s in STEMS if s in (stems if isinstance(stems, list) else [])]
    mixes = x.get("mixes")
    mixes = list(MIXES) if mixes is None else [m for m in MIXES if m in (mixes if isinstance(mixes, list) else [])]
    if not stems and not mixes:
        raise SystemExit("Choose at least one stem or one mix.")
    t = x.get("target_lufs")
    if t in (None, ""):
        target = None
    else:
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not (-30 <= float(t) <= -9):
            raise SystemExit("The loudness target must be between -30 and -9 LUFS.")
        target = float(t)
    pk = x.get("peak_db", -1.0)
    if isinstance(pk, bool) or not isinstance(pk, (int, float)) or not (-6 <= float(pk) <= -0.1):
        raise SystemExit("The peak ceiling must be between -6 and -0.1 dBFS.")
    return {"rate": rate, "bits": bits, "bwf": x.get("bwf", True) is not False, "stems": stems, "mixes": mixes, "target_lufs": target, "peak_db": float(pk),
            "start_tc": str(x.get("start_tc") or "00:00:00:00"), "media": x.get("media", True) is not False, "title": " ".join(str(x.get("title") or "").split())[:80]}


# ---------------------------------------------------------------- the film's timeline

def film_times(d: str) -> tuple[dict, float, list[dict]]:
    """Shots in scene order at their lengths, laid end to end: {shot: (start, end)}, the film's length and the shots."""
    every = sorted(Q._shots(d).values(), key=lambda s: (int(s["scene"]), s["index"]))
    if not every:
        raise SystemExit("There are no shots in the film yet.")
    times, at = {}, 0.0
    for s in every:
        times[s["id"]] = (at, at + float(s["duration"]))
        at += float(s["duration"])
    if at > FILM_MAX:
        raise SystemExit(f"The film is {at / 60:.0f} minutes long: export it a scene at a time (not built yet) or shorten it.")
    return times, at, every


def _title(d: str, spec: dict) -> str:
    m = safeio.read_json(os.path.join(d, "film.json"), {}) or {}
    t = spec["title"] or str((m.get("title") if isinstance(m, dict) else "") or os.path.basename(os.path.normpath(d)) or "Film")
    clean = " ".join("".join(c for c in t if (c.isascii() and c.isalnum()) or c in " -_()&").split()).strip(" ._") or "Film"      # letters, digits and a few marks only: safe in a file name, and still readable
    return clean[:60].rstrip(" ._") or "Film"


def dialogue_items(d: str, times: dict) -> list[dict]:
    """Every recording laid where the film puts it: in order within its shot with the usual gap, moved by any whole frames set in Timing and ADR, and cut at the end of its shot."""
    from . import adrsync
    items = []
    meta = V._meta(d)["shots"]
    people = {s["id"]: s["people"] for s in V.status(d)["shots"]}
    for sid, (a, b) in times.items():
        at = a
        for p in people.get(sid, []):
            rec = p.get("recording")
            path = V.inside(d, rec["file"]) if rec else None
            if not path or not os.path.isfile(path):
                continue
            secs = float(rec["seconds"])
            start = at + adrsync.offset_seconds(d, sid, p["key"])
            entry = next((e for e in meta.get(sid, []) if e.get("key") == p["key"]), {}) or {}
            side = None
            if entry.get("gen"):
                side = V._read(os.path.join(d, "voice", "_generated", str(entry["gen"])[:-4] + ".json"), None)
            items.append({"sid": sid, "person": p["name"], "key": p["key"], "path": path, "file": rec["file"], "start": max(0.0, start), "end": min(b, max(0.0, start) + secs), "seconds": secs,
                          "source": entry.get("source") or "recording", "model": (side or {}).get("model"), "voice": (side or {}).get("voice_name")})
            at += secs + V.GAP
    return items


def _dialogue_float(d: str, items: list[dict], duration: float, out: str) -> bool:
    import numpy as np
    import soundfile as sf
    if not items:
        return False
    track = np.zeros((int(round(duration * RATE)), 2), dtype=np.float32)
    for it in items:
        x = shotsound.decode(it["path"], 2)
        i = int(round(it["start"] * RATE))
        n = min(len(x), int(round((it["end"] - it["start"]) * RATE)), len(track) - i)
        if n > 0 and i >= 0:
            track[i:i + n] += x[:n]
    sf.write(out, track, RATE, subtype="FLOAT")
    return True


def render_stems(d: str, work: str, lanes: list[str], times: dict, duration: float) -> tuple[dict, dict]:
    """The lanes as 32-bit float files at the engine's rate: {lane: path} for the lanes that have any sound, and {lane: why not} for those that do not."""
    st0 = M.settings(d)
    got, why = {}, {}
    items = dialogue_items(d, times)
    for lane in lanes:
        out = os.path.join(work, f"{lane}.wav")
        if lane in st0["mute_lanes"]:
            why[lane] = "Left out of the film in your mix settings."
        elif lane == "dialogue":
            if _dialogue_float(d, items, duration, out):
                got[lane] = out
            else:
                why[lane] = "No recording or spoken line is attached to a shot."
        else:
            st = {**st0, "mute_lanes": [x for x in M.LANES if x != lane], "solo": None, "target_lufs": None, "raw_float": True}
            r = M.mix_cues(d, None, times, duration, out, st, windows=M.film_windows(d))
            if r and r.get("path") and os.path.isfile(out):
                got[lane] = out
            else:
                skipped = (r or {}).get("skipped") or []
                why[lane] = skipped[0]["why"] if skipped else "No approved cue in this lane."
    return got, why


# ---------------------------------------------------------------- summing, measuring, the master gain

def _sum_files(files: list[str], out: str) -> None:
    import numpy as np
    import soundfile as sf
    readers = [sf.SoundFile(f) for f in files]
    try:
        with sf.SoundFile(out, "w", RATE, 2, subtype="FLOAT") as w:
            while True:
                acc, n = None, 0
                for r in readers:
                    x = r.read(RATE * 10, dtype="float32", always_2d=True)
                    n = max(n, len(x))
                    if len(x):
                        if acc is None or len(acc) < len(x):
                            acc = np.pad(acc, ((0, len(x) - len(acc)), (0, 0))) if acc is not None else np.zeros((len(x), 2), dtype=np.float32)
                        acc[: len(x)] += x[:, :2]
                if not n:
                    break
                w.write(acc)
    finally:
        for r in readers:
            r.close()


def _measure(path: str) -> dict | None:
    from .export import measure_loudness
    return measure_loudness(path)


def _peak(path: str) -> float:
    import numpy as np
    import soundfile as sf
    p = 0.0
    with sf.SoundFile(path) as r:
        for x in r.blocks(blocksize=RATE * 10, dtype="float32"):
            p = max(p, float(np.max(np.abs(x))) if len(x) else 0.0)
    return p


def master_gain(meas: dict | None, peak_linear: float, target: float | None, ceiling_db: float) -> dict:
    """One steady gain (dB) that brings a mix to the loudness target without any peak going over the ceiling. Where both cannot be had, the ceiling wins and it says so. No limiter: the same gain
    applied to each stem gives the mix exactly."""
    import math
    peak_db = 20 * math.log10(max(peak_linear, 1e-9))
    tp = (meas or {}).get("true_peak_db")
    over = tp if tp is not None else peak_db
    cap = ceiling_db - over
    if meas is None:
        return {"gain_db": 0.0, "capped": False, "reached": None, "why": "The mix is silent, so nothing was changed."}
    want = (target - meas["lufs"]) if target is not None else 0.0
    gain = min(want, cap) if target is not None else min(0.0, cap)
    capped = (target is not None and want > cap + 1e-6) or (target is None and cap < 0)
    why = ""
    if target is not None and capped:
        why = f"The loudness target could not be reached without peaks going over {ceiling_db} dBFS, so the ceiling won ({meas['lufs'] + gain:.1f} LUFS)."
    elif target is None and capped:
        why = f"The mix was turned down {abs(gain):.1f} dB so no peak goes over {ceiling_db} dBFS."
    return {"gain_db": round(gain, 2), "capped": bool(capped), "reached": round(meas["lufs"] + gain, 1), "why": why}


# ---------------------------------------------------------------- writing the files (and Broadcast WAV)

def _ffmpeg() -> str:
    from .export import ffmpeg
    return ffmpeg()


def _convert(src: str, dst: str, rate: int, bits: int, gain_db: float = 0.0) -> None:
    af = []
    if abs(gain_db) > 1e-6:
        af.append(f"volume={gain_db}dB")
    af.append(f"aresample={rate}" + (":dither_method=triangular" if bits == 16 else ""))
    part = dst + ".part.wav"
    r = subprocess.run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-af", ",".join(af), "-ar", str(rate), "-ac", "2", "-c:a", BITS[bits], "-fflags", "+bitexact", part],
                       capture_output=True, text=True, creationflags=NO_WINDOW, timeout=TIMEOUT)
    if r.returncode or not os.path.isfile(part):
        if os.path.isfile(part):
            os.remove(part)
        raise SystemExit("A file could not be written: " + " ".join((r.stderr or "").strip().splitlines()[-1:])[:200])
    os.replace(part, dst)


def _fixed(text: str, n: int) -> bytes:
    return str(text).encode("ascii", "replace")[:n].ljust(n, b"\0")


def bext_chunk(description: str, originator: str, reference: str, date: str, clock: str, time_reference: int, coding_history: str, loudness: dict | None = None) -> bytes:
    """A Broadcast WAV `bext` chunk (EBU Tech 3285, version 2): description, originator, a reference, the date and time, the time reference in samples since midnight (the start timecode), a
    blank UMID, the loudness of the file when it is known, and the coding history."""
    def i16(v) -> int:
        return 0x7FFF if v is None else max(-32768, min(32767, int(round(float(v) * 100))))
    ld = loudness or {}
    body = (_fixed(description, 256) + _fixed(originator, 32) + _fixed(reference, 32) + _fixed(date, 10) + _fixed(clock, 8)
            + struct.pack("<II", time_reference & 0xFFFFFFFF, (time_reference >> 32) & 0xFFFFFFFF) + struct.pack("<H", 2) + b"\0" * 64
            + struct.pack("<hhhhh", i16(ld.get("lufs")), i16(ld.get("range_lu")), i16(ld.get("true_peak_db")), 0x7FFF, 0x7FFF) + b"\0" * 180
            + str(coding_history).encode("ascii", "replace"))
    return b"bext" + struct.pack("<I", len(body)) + body + (b"\0" if len(body) % 2 else b"")


def add_bext(path: str, chunk: bytes) -> None:
    """Insert a `bext` chunk straight after `fmt ` in a WAV file (rewriting the file whole, atomically). Refuses a file that is not a plain RIFF WAVE or is over 4 GB."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE" or len(raw) > RIFF_MAX:
        raise SystemExit("That is not a WAV file this tool can add a Broadcast chunk to.")
    out, pos, placed = [raw[:12]], 12, False
    while pos + 8 <= len(raw):
        cid, size = raw[pos:pos + 4], struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        end = pos + 8 + size + (size % 2)
        if cid == b"bext":
            pos = end
            continue
        out.append(raw[pos:end])
        if cid == b"fmt " and not placed:
            out.append(chunk)
            placed = True
        pos = end
    if not placed:
        raise SystemExit("That WAV file has no format chunk.")
    body = b"".join(out)
    body = body[:4] + struct.pack("<I", len(body) - 8) + body[8:]
    tmp = path + ".bwf"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, path)


def read_bext(path: str) -> dict | None:
    """The fields of a file's `bext` chunk, or None when it has none. Used to check what was written."""
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return None
        while True:
            h = f.read(8)
            if len(h) < 8:
                return None
            cid, size = h[:4], struct.unpack("<I", h[4:])[0]
            if cid == b"bext":
                b = f.read(size)
                z = lambda x: x.split(b"\0")[0].decode("ascii", "replace")
                lo, hi = struct.unpack("<II", b[338:346])                         # the fixed part is 602 bytes: description 256, originator 32, reference 32, date 10, time 8, time reference 8, version 2, UMID 64, loudness 10, reserved 180
                li = struct.unpack("<hhhhh", b[412:422])
                return {"description": z(b[0:256]), "originator": z(b[256:288]), "reference": z(b[288:320]), "date": z(b[320:330]), "time": z(b[330:338]), "time_reference": lo | (hi << 32),
                        "version": struct.unpack("<H", b[346:348])[0], "loudness": None if li[0] == 0x7FFF else li[0] / 100, "true_peak": None if li[2] == 0x7FFF else li[2] / 100,
                        "coding_history": z(b[602:])}
            f.seek(size + (size % 2), 1)


# ---------------------------------------------------------------- the cue sheet

def _safe_cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s       # a spreadsheet must never run a cell as a formula


def cue_rows(d: str, times: dict, duration: float, items: list[dict], start_s: float, fps: T.FrameRate) -> list[dict]:
    from . import adrsync
    st = M.settings(d)
    lib = {a["id"]: a for a in AL.load(d)["assets"]}
    cues = {c["id"]: c for c in Q.listing(d)["cues"]}
    tc = lambda t: adrsync.tc(t + start_s, fps)
    rows = []
    for it in items:
        rows.append({"lane": "DIALOGUE", "name": f"{it['person']}", "scene": next((int(s["scene"]) for s in Q._shots(d).values() if s["id"] == it["sid"]), ""), "shot": it["sid"], "tc_in": tc(it["start"]), "tc_out": tc(it["end"]),
                     "seconds": round(it["end"] - it["start"], 2), "level_db": 0.0, "pan": 0.0, "asset": "", "origin": it["source"], "provider": "elevenlabs" if it["source"] == "elevenlabs" else "", "model": it.get("model") or "",
                     "licence": "", "commercial": "", "licence_note": (it.get("voice") or ""), "approval": "recording", "file": it["file"]})
    placed, _skipped = M.placements(d, times, duration, st)
    for p in placed:
        c, a = cues.get(p["cue"]) or {}, lib.get((cues.get(p["cue"]) or {}).get("asset_id")) or {}
        gen, lic = a.get("generation") or {}, a.get("licence") or {}
        rows.append({"lane": LABEL.get(p["lane"], p["lane"].upper()), "name": a.get("name") or c.get("asset_name") or "", "scene": c.get("scene", ""), "shot": c.get("shot") or "", "tc_in": tc(p["start"]),
                     "tc_out": tc(p["end"]), "seconds": round(p["end"] - p["start"], 2), "level_db": round(20 * __import__("math").log10(max(p["gain"], 1e-6)), 1), "pan": round(float(p.get("pan") or 0), 2),
                     "asset": a.get("id") or "", "origin": a.get("source") or "", "provider": gen.get("provider") or "", "model": gen.get("model") or "", "licence": lic.get("source") or "",
                     "commercial": lic.get("commercial") or "", "licence_note": lic.get("note") or "", "approval": c.get("approval") or "", "file": a.get("file") or ""})
    rows.sort(key=lambda r: (r["tc_in"], r["lane"]))
    return rows


CSV_COLUMNS = [("lane", "Lane"), ("name", "Name"), ("scene", "Scene"), ("shot", "Shot"), ("tc_in", "TC in"), ("tc_out", "TC out"), ("seconds", "Seconds"), ("level_db", "Level dB"), ("pan", "Pan"), ("asset", "Asset"),
               ("origin", "Origin"), ("provider", "Provider"), ("model", "Model"), ("licence", "Licence source"), ("commercial", "Commercial use"), ("licence_note", "Licence note / voice"), ("approval", "Approval"), ("file", "File")]


def write_cue_sheet(rows: list[dict], base: str) -> list[str]:
    with open(base + ".csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([h for _, h in CSV_COLUMNS])
        for r in rows:
            w.writerow([_safe_cell(r.get(k)) for k, _ in CSV_COLUMNS])
    safeio.write_json(base + ".json", {"schema": 1, "columns": [k for k, _ in CSV_COLUMNS], "rows": rows})
    return [os.path.basename(base) + ".csv", os.path.basename(base) + ".json"]


# ---------------------------------------------------------------- OpenTimelineIO

def _rt(seconds: float, fps: T.FrameRate) -> dict:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": fps.num / fps.den, "value": float(round(float(Fraction(seconds).limit_denominator(1_000_000) * fps.num / fps.den)))}


def _range(start: float, dur: float, fps: T.FrameRate) -> dict:
    return {"OTIO_SCHEMA": "TimeRange.1", "start_time": _rt(start, fps), "duration": _rt(dur, fps)}


def _pack(clips: list[dict]) -> list[list[dict]]:
    """Clips on one lane into as few tracks as it takes so that no track plays two sounds at once (an OpenTimelineIO track is a sequence)."""
    tracks: list[list[dict]] = []
    for c in sorted(clips, key=lambda c: (c["start"], c["end"])):
        for t in tracks:
            if c["start"] >= t[-1]["end"] - 1e-6:
                t.append(c)
                break
        else:
            tracks.append([c])
    return tracks


def otio_timeline(title: str, fps: T.FrameRate, lanes: dict[str, list[dict]], duration: float, start_s: float) -> dict:
    stack = {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": [], "metadata": {}, "source_range": None, "effects": [], "markers": [], "enabled": True, "color": None}
    for lane in STEMS:
        for n, track in enumerate(_pack(lanes.get(lane, [])), 1):
            kids, at = [], 0.0
            for c in track:
                if c["start"] > at + 1e-6:
                    kids.append({"OTIO_SCHEMA": "Gap.1", "name": "", "source_range": _range(0, c["start"] - at, fps), "effects": [], "markers": [], "enabled": True, "metadata": {}, "color": None})
                kids.append({"OTIO_SCHEMA": "Clip.2", "name": c["name"][:120], "source_range": _range(c.get("source_in", 0.0), c["end"] - c["start"], fps), "effects": [], "markers": [], "enabled": True, "metadata": {"filmcrafter": c.get("meta", {})},
                             "color": None, "media_references": {"DEFAULT_MEDIA": {"OTIO_SCHEMA": "ExternalReference.1", "name": os.path.basename(c["media"]), "available_range": _range(0, c["media_seconds"], fps), "available_image_bounds": None,
                                                                                  "target_url": c["media"], "metadata": {}}}, "active_media_reference_key": "DEFAULT_MEDIA"})
                at = c["end"]
            stack["children"].append({"OTIO_SCHEMA": "Track.1", "name": f"{LABEL[lane]} {n}" if len(_pack(lanes[lane])) > 1 else LABEL[lane], "source_range": None, "effects": [], "markers": [], "enabled": True, "metadata": {},
                                      "children": kids, "kind": "Audio", "color": None})
    return {"OTIO_SCHEMA": "Timeline.1", "name": title, "global_start_time": _rt(start_s, fps), "tracks": stack, "metadata": {"filmcrafter": {"note": "Positions follow the film's shot list; see README.txt", "duration_seconds": round(duration, 3)}}}


# ---------------------------------------------------------------- the export

def plan(d: str, spec: dict | None = None) -> dict:
    """What an export would make, without writing anything: the lanes that have sound, why the others do not, the film's length and a size estimate. Free."""
    Q._film(d)
    sp = clean_spec(spec)
    fps = T.FPS_24
    parse_tc(sp["start_tc"], fps)
    times, duration, shots = film_times(d)
    st = M.settings(d)
    items = dialogue_items(d, times)
    placed, skipped = M.placements(d, times, duration, st)
    have = {"dialogue": bool(items)}
    for p in placed:
        have[p["lane"]] = True
    lanes = {l: ("yes" if have.get(l) else "no sound") for l in STEMS}
    for l in STEMS:
        if l in st["mute_lanes"]:
            lanes[l] = "left out in your mix settings"
    files = [l for l in sp["stems"] if lanes[l] == "yes"] + [m for m in sp["mixes"]]
    size = int(duration * sp["rate"] * 2 * (sp["bits"] // 8) * len(files))
    return {"seconds": round(duration, 2), "shots": len(shots), "spec": sp, "lanes": lanes, "files": len(files), "estimated_bytes": size, "skipped": skipped[:10],
            "positions": "Shots in scene order at their lengths; recordings in order with the usual gap, moved by Timing and ADR frames. A trimmed cut may differ."}


def export(d: str, spec: dict | None = None) -> dict:
    """Write the folder described at the top of this file. Reads the film; writes only into `exports/audio/<title> <time>/` and the cache. Returns what was made and what was checked."""
    import soundfile as sf
    Q._film(d)
    sp = clean_spec(spec)
    fps = T.FPS_24
    start_s = parse_tc(sp["start_tc"], fps)
    times, duration, shots = film_times(d)
    title = _title(d, sp)
    stamp = time.strftime("%Y-%m-%d %H%M%S")
    out = os.path.join(d, "exports", "audio", f"{title} {stamp}")
    work = os.path.join(d, "cache", "pro-audio", stamp)
    os.makedirs(work, exist_ok=True)
    os.makedirs(os.path.join(out, "stems"), exist_ok=True)
    os.makedirs(os.path.join(out, "mixes"), exist_ok=True)
    try:
        emit(event="progress", stage="building the stems", progress=0.1)
        lanes_wanted = list(STEMS)                                       # all lanes are rendered: the mixes need them even if a stem file is not wanted
        got, why = render_stems(d, work, lanes_wanted, times, duration)
        if not got:
            raise SystemExit("There is no sound to export: no recording is attached and no cue is approved. " + " ".join(sorted(set(why.values()))))
        description = f"{title}"
        ref_base = hashlib.sha1((title + stamp).encode(), usedforsecurity=False).hexdigest()[:16]
        date, clock = time.strftime("%Y-%m-%d"), time.strftime("%H:%M:%S")
        tref = int(round(start_s * sp["rate"]))
        history = f"A=PCM,F={sp['rate']},W={sp['bits']},M=stereo,T=FilmCrafter\r\n"
        written, problems, n = [], [], 0

        def finish(src: str, rel: str, gain: float, label: str, loudness: dict | None) -> dict:
            dst = os.path.join(out, *rel.split("/"))
            _convert(src, dst, sp["rate"], sp["bits"], gain)
            if sp["bwf"]:
                add_bext(dst, bext_chunk(f"{description} - {label}", "FilmCrafter", f"FC{ref_base}{len(written):04d}", date, clock, tref, history, loudness))
            info = sf.info(dst)
            return {"file": rel, "label": label, "seconds": round(info.duration, 3), "rate": info.samplerate, "channels": info.channels, "subtype": info.subtype, "bytes": os.path.getsize(dst)}

        stems_made = {}
        for lane in sp["stems"]:
            if lane not in got:
                continue
            n += 1
            emit(event="progress", stage=f"writing {LABEL[lane].lower()}", progress=0.3 + 0.1 * n)
            r = finish(got[lane], f"stems/{n:02d} {LABEL[lane]}.wav", 0.0, LABEL[lane], None)
            r["lane"], r["peak_db"] = lane, round(20 * __import__("math").log10(max(_peak(got[lane]), 1e-9)), 1)
            written.append(r)
            stems_made[lane] = r
        mixes = []
        for kind in sp["mixes"]:
            use = [got[l] for l in STEMS if l in got and (kind == "final" or l != "dialogue")]
            if not use:
                continue
            emit(event="progress", stage=f"mixing {kind}", progress=0.8)
            summed = os.path.join(work, f"sum-{kind}.wav")
            _sum_files(use, summed)
            meas = _measure(summed)
            g = master_gain(meas, _peak(summed), sp["target_lufs"], sp["peak_db"])
            label = "FINAL" if kind == "final" else "M&E"
            loud = {"lufs": g["reached"], "range_lu": (meas or {}).get("range_lu"), "true_peak_db": ((meas or {}).get("true_peak_db") + g["gain_db"]) if meas and meas.get("true_peak_db") is not None else None}
            r = finish(summed, f"mixes/{title} {label}.wav", g["gain_db"], label, loud if meas else None)
            r.update({"kind": kind, "master_gain_db": g["gain_db"], "capped": g["capped"], "note": g["why"], "lufs": g["reached"], "true_peak_db": round(loud["true_peak_db"], 1) if loud["true_peak_db"] is not None else None,
                      "stems_in": [l for l in STEMS if l in got and (kind == "final" or l != "dialogue")]})
            written.append(r)
            mixes.append(r)
        emit(event="progress", stage="writing the cue sheet", progress=0.9)
        items = dialogue_items(d, times)
        rows = cue_rows(d, times, duration, items, start_s, fps)
        sheet = write_cue_sheet(rows, os.path.join(out, f"{title} cue sheet"))
        otio_name, media_made = None, 0
        lanes_clips: dict[str, list[dict]] = {l: [] for l in STEMS}
        mdir = os.path.join(out, "media")
        copied: dict[str, str] = {}

        def media(path: str) -> str | None:
            nonlocal media_made
            if path in copied:
                return copied[path]
            if media_made >= MEDIA_MAX or not os.path.isfile(path):
                return None
            os.makedirs(mdir, exist_ok=True)
            digest = hashlib.sha1(path.encode(), usedforsecurity=False).hexdigest()[:8]
            rel = "media/" + file_name(f"{digest}-{os.path.basename(path)}", 80)
            shutil.copyfile(path, os.path.join(out, *rel.split("/")))
            copied[path] = rel
            media_made += 1
            return rel
        if sp["media"]:
            for it in items:
                rel = media(it["path"])
                if rel:
                    lanes_clips["dialogue"].append({"name": f"{it['person']} {it['sid']}", "start": it["start"], "end": it["end"], "media": rel, "media_seconds": it["seconds"], "meta": {"shot": it["sid"], "source": it["source"]}})
            st = M.settings(d)
            placed, _ = M.placements(d, times, duration, st)
            for p in placed:
                rel = media(p["path"])
                if not rel:
                    continue
                a = p["asset_seconds"]
                lane = p["lane"] if p["lane"] in STEMS else "sfx"
                if p["loop"] and a > 0:
                    at, k = p["start"], 0
                    while at < p["end"] - 1e-6 and k < LOOP_MAX:
                        e = min(p["end"], at + a)
                        lanes_clips[lane].append({"name": os.path.basename(rel)[9:], "start": at, "end": e, "media": rel, "media_seconds": a, "meta": {"cue": p["cue"], "loop": True}})
                        at, k = e, k + 1
                else:
                    lanes_clips[lane].append({"name": os.path.basename(rel)[9:], "start": p["start"], "end": min(p["end"], p["start"] + a), "media": rel, "media_seconds": a, "meta": {"cue": p["cue"]}})
            otio_name = f"{title} audio.otio"
            safeio.write_json(os.path.join(out, otio_name), otio_timeline(title, fps, lanes_clips, duration, start_s), backup=False)
        report = {"schema": 1, "title": title, "made": stamp, "spec": sp, "seconds": round(duration, 3), "start_tc": sp["start_tc"], "fps": [fps.num, fps.den], "stems": [r for r in written if "lane" in r], "mixes": mixes,
                  "lanes_without_sound": why, "cue_sheet": sheet, "otio": otio_name, "media_files": media_made, "not_checked": NOT_CHECKED, "skipped_cues": M.placements(d, times, duration, M.settings(d))[1][:20]}
        problems = verify(out, report, sp, duration, start_s)
        report["problems"], report["ok"] = problems, not problems
        safeio.write_json(os.path.join(out, "report.json"), report, backup=False)
        _readme(out, report, title)
        return {"folder": out, "relative": os.path.relpath(out, d).replace(os.sep, "/"), "files": len(written), "problems": problems, "ok": not problems, "stems": [r["file"] for r in written if "lane" in r],
                "mixes": [{k: r[k] for k in ("file", "lufs", "true_peak_db", "master_gain_db", "capped", "note")} for r in mixes], "lanes_without_sound": why, "cue_sheet": sheet, "otio": otio_name,
                "seconds": round(duration, 1), "not_checked": NOT_CHECKED}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def verify(out: str, report: dict, sp: dict, duration: float, start_s: float) -> list[str]:
    """Read every written file back as a person's tools would, not as it was written: its format, length, sound and, for Broadcast WAV, the chunk. A list of plain problems (empty is good)."""
    import numpy as np
    import soundfile as sf
    problems = []
    sub = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[sp["bits"]]
    for r in [*report["stems"], *report["mixes"]]:
        path = os.path.join(out, *r["file"].split("/"))
        try:
            info = sf.info(path)
        except Exception as e:
            problems.append(f"{r['file']} cannot be read back ({type(e).__name__}).")
            continue
        if info.samplerate != sp["rate"] or info.subtype != sub or info.channels != 2:
            problems.append(f"{r['file']} is {info.samplerate} Hz, {info.subtype}, {info.channels} channels, not what was asked for.")
        if abs(info.duration - duration) > 0.05:
            problems.append(f"{r['file']} is {info.duration:.2f} s, not the film's {duration:.2f} s.")
        x, _ = sf.read(path, dtype="float32", always_2d=True, frames=int(info.samplerate * 600))
        if not len(x) or float(np.max(np.abs(x))) < 1e-5:
            problems.append(f"{r['file']} is silent.")
        if sp["bwf"]:
            b = read_bext(path)
            want = int(round(start_s * sp["rate"]))
            if not b or b["time_reference"] != want or b["originator"] != "FilmCrafter":
                problems.append(f"{r['file']} has a wrong or missing Broadcast chunk.")
    for k in ("cue_sheet",):
        for name in report[k]:
            if not os.path.isfile(os.path.join(out, name)):
                problems.append(f"{name} is missing.")
    return problems


def _readme(out: str, report: dict, title: str) -> None:
    sp = report["spec"]
    lines = [f"{title}: audio export, {report['made']}", "",
             f"{sp['rate'] // 1000 if sp['rate'] % 1000 == 0 else sp['rate'] / 1000} kHz, {sp['bits']}-bit{' float' if sp['bits'] == 32 else ''}, {'Broadcast WAV' if sp['bwf'] else 'WAV'}, stereo. "
             f"Every file is {report['seconds']} s long and starts at {sp['start_tc']} ({report['fps'][0]}/{report['fps'][1]} frames a second).", "",
             "stems/   the mix before the master stage, one lane per file (no limiter, no loudness change).", "mixes/   FINAL and M&E (without dialogue): each is the sum of its stems times ONE steady gain, reported in report.json.",
             "cue sheet (csv, json): every voice line and sound with timecodes, levels, origin and licence.", "audio.otio + media/: each sound as a clip on a lane; the files in media/ are copies of your originals.", "",
             "Positions follow the film's shot list (scene order, shot lengths, recordings in order with the usual gap, Timing and ADR frames). A film trimmed in the Studio's cut may place shots differently.",
             "Not checked: " + " ".join(report["not_checked"]), "", "Problems found when the files were read back: " + ("none." if not report.get("problems") else " ".join(report["problems"]))]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["plan", "export"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        res = plan(d, x) if a.action == "plan" else export(d, x)
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
