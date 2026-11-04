"""Colour Studio: a creative grade for a shot, a scene or the whole film, and .cube LUTs, applied when the film is put together and never to the takes themselves.

  <film>/edit/edit.json    {"schema": 1, "revision": n, "grades": {"film": G, "scenes": {"3": G}, "shots": {"S01-01": G}}, "luts": {id: {...}}, "presets": {name: G}, "history": [...]}
  <film>/edit/luts/<id>.cube   an imported LUT, copied in by the hash of its content and never edited

(For a project that is not a film the folder sits in the project itself.) It lives in the film, not in the render project, so making the render project again can never lose a grade.

A grade G is one short list of numbers, each with a limit:
  exposure (stops), brightness, contrast, highlights, shadows, whites, blacks, saturation, vibrance, hue (degrees), temperature, tint, gamma, lift, gain  (master),
  lift_rgb, gamma_rgb, gain_rgb (three numbers each)  and  lut {id, intensity}.
A grade has one place per scope: setting it again REPLACES that scope's grade; it never stacks on itself. The picture gets the film's grade, then the scene's, then the shot's, each on top of the one before.

How it is applied (the same text builds the film and the preview frame, which is how the two stay equal): the colour match (the cast fix, in colormatch.py) comes first, so the AI's own tint
is corrected before a creative grade is put on; then the picture goes to RGB with the HD matrix written out, the grade is done there, and it goes back with the same matrix. Only numbers made
here go into a filter: nothing you type is ever put in one. A grade with nothing set adds nothing at all.

LUTs: strict `.cube` files only (1D or 3D, size limits, domain 0 to 1, finite numbers, no other keywords). Each is labelled creative or technical and says what colour space it expects and makes.
Pictures here are Rec.709: a LUT that expects anything else (log, HDR, DCI-P3...) is refused with a plain message, not guessed. Intensity is a mix between the picture with and without the LUT,
made by blending the LUT itself with the identity, so the filter chain stays one simple chain.

  python -m filmcrafter_engine.grading <action> <project> --data '{...}'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time

from . import safeio

SCHEMA = 2                   # 2: the sequence (the film's cut) and a redo list join the grades; a file of schema 1 reads as it is and is written as 2 by the next change
SPACES = ("rec709", "srgb", "log", "hdr_pq", "hdr_hlg", "dci_p3", "other")
PICTURE_SPACE = "rec709"
MAX_LUT_BYTES = 24 * 1024 * 1024
MAX_3D, MAX_1D = 65, 4096
HISTORY = 40
# name -> (low, high, default)
RANGES = {"exposure": (-3.0, 3.0, 0.0), "brightness": (-1.0, 1.0, 0.0), "contrast": (-1.0, 1.0, 0.0), "highlights": (-1.0, 1.0, 0.0), "shadows": (-1.0, 1.0, 0.0),
          "whites": (-1.0, 1.0, 0.0), "blacks": (-1.0, 1.0, 0.0), "saturation": (-1.0, 1.0, 0.0), "vibrance": (-1.0, 1.0, 0.0), "hue": (-180.0, 180.0, 0.0),
          "temperature": (-1.0, 1.0, 0.0), "tint": (-1.0, 1.0, 0.0), "gamma": (-1.0, 1.0, 0.0), "lift": (-1.0, 1.0, 0.0), "gain": (-1.0, 1.0, 0.0)}
RGB3 = ("lift_rgb", "gamma_rgb", "gain_rgb")
SCOPES = ("film", "scene", "shot")


# ---------------------------------------------------------------- where it lives

def film_root(d: str) -> str:
    from . import character_performance as CP
    return CP.film_dir(d) or os.path.abspath(d)


def edit_dir(d: str) -> str:
    return os.path.join(film_root(d), "edit")


def _path(d: str) -> str:
    return os.path.join(edit_dir(d), "edit.json")


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if not math.isfinite(x) else max(lo, min(hi, x))


def clean_grade(raw) -> dict:
    """A grade made safe: only the known numbers, each inside its limits, anything else dropped. Values equal to the default are not kept."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for k, (lo, hi, dflt) in RANGES.items():
        if k in raw:
            v = round(_num(raw[k], lo, hi, dflt), 4)
            if v != dflt:
                out[k] = v
    for k in RGB3:
        v = raw.get(k)
        if isinstance(v, (list, tuple)) and len(v) == 3:
            t = [round(_num(x, -1.0, 1.0, 0.0), 4) for x in v]
            if any(t):
                out[k] = t
    lut = raw.get("lut")
    if isinstance(lut, dict) and isinstance(lut.get("id"), str) and len(lut["id"]) == 16 and all(c in "0123456789abcdef" for c in lut["id"]):
        out["lut"] = {"id": lut["id"], "intensity": round(_num(lut.get("intensity"), 0.0, 1.0, 1.0), 3)}
    if raw.get("off") is True:
        out["off"] = True
    return out


def _refuse_newer(s) -> None:
    """A record made by a newer FilmCrafter is never read halfway or written over."""
    if isinstance(s, dict) and isinstance(s.get("schema"), int) and not isinstance(s.get("schema"), bool) and s["schema"] > SCHEMA:
        raise SystemExit("This film's edit record was made by a newer FilmCrafter. Update FilmCrafter to open it; nothing has been changed.")


def load(d: str, notes: list | None = None) -> dict:
    """The edit record. A damaged one is put back from its backup when there is one (and `notes` says so); with no good backup it STOPS with a plain message rather than read as 'never edited',
    which would quietly turn the film back into the plan."""
    s = safeio.read_json(_path(d), {}, notes=notes)
    s = s if isinstance(s, dict) else {}
    _refuse_newer(s)
    g = s.get("grades") if isinstance(s.get("grades"), dict) else {}
    grades = {"film": clean_grade(g.get("film")),
              "scenes": {str(k): clean_grade(v) for k, v in (g.get("scenes") if isinstance(g.get("scenes"), dict) else {}).items() if clean_grade(v)},
              "shots": {str(k): clean_grade(v) for k, v in (g.get("shots") if isinstance(g.get("shots"), dict) else {}).items() if clean_grade(v)}}
    luts = {str(k): v for k, v in (s.get("luts") if isinstance(s.get("luts"), dict) else {}).items() if isinstance(v, dict)}
    presets = {str(k)[:60]: clean_grade(v) for k, v in (s.get("presets") if isinstance(s.get("presets"), dict) else {}).items() if clean_grade(v)}
    hist = [h for h in (s.get("history") if isinstance(s.get("history"), list) else []) if isinstance(h, dict)][-HISTORY:]
    extra = {k: v for k, v in s.items() if k not in ("schema", "revision", "grades", "luts", "presets", "history")}      # a newer version's keys are kept as they are
    return {"schema": SCHEMA, "revision": int(s.get("revision") or 0) if isinstance(s.get("revision"), (int, float)) else 0, "grades": grades, "luts": luts, "presets": presets,
            "history": hist, "_extra": extra}


def snapshot(cur: dict) -> dict:
    """What one undo puts back: the grades, the saved looks and the sequence (the film's cut). The LUT library is not part of it: a LUT file stays until you remove it."""
    return {"grades": json.loads(json.dumps(cur["grades"])), "presets": json.loads(json.dumps(cur["presets"])), "sequence": json.loads(json.dumps(cur["_extra"].get("sequence")))}


def restore(cur: dict, snap: dict) -> None:
    cur["grades"] = _normalise({"grades": snap.get("grades") or {}})["grades"]
    cur["presets"] = {k: clean_grade(v) for k, v in (snap.get("presets") or {}).items()}
    if snap.get("sequence") is None:
        cur["_extra"].pop("sequence", None)
    else:
        cur["_extra"]["sequence"] = snap["sequence"]


def _out(cur: dict) -> dict:
    return {**cur["_extra"], "schema": SCHEMA, "revision": cur["revision"], "grades": cur["grades"], "luts": cur["luts"], "presets": cur["presets"], "history": cur["history"]}


def _save(d: str, change, what: str, keep_redo: bool = False) -> dict:
    """Read, change, write as one step; what the change replaced is kept in the history so the last change can be undone (and, until a new change is made, done again)."""
    os.makedirs(edit_dir(d), exist_ok=True)
    seen: dict = {}

    def run(data):
        _refuse_newer(data)
        cur = load(d) if not isinstance(data, dict) or not data else None
        cur = cur or _normalise(data)
        before = snapshot(cur)
        change(cur)
        if not keep_redo:
            cur["_extra"].pop("redo", None)
        cur["revision"] += 1
        cur["history"] = (cur["history"] + [{"rev": cur["revision"], "at": int(time.time()), "what": what, "before": before}])[-HISTORY:]
        seen.update(cur)
        return _out(cur)
    safeio.update_json(_path(d), run, {})
    return state(d)


def _normalise(data: dict) -> dict:
    tmp = {"schema": SCHEMA, **data}
    g = tmp.get("grades") if isinstance(tmp.get("grades"), dict) else {}
    return {"schema": SCHEMA, "revision": int(tmp.get("revision") or 0), "luts": dict(tmp.get("luts") or {}), "presets": {k: clean_grade(v) for k, v in (tmp.get("presets") or {}).items()},
            "grades": {"film": clean_grade(g.get("film")), "scenes": {str(k): clean_grade(v) for k, v in (g.get("scenes") or {}).items()},
                       "shots": {str(k): clean_grade(v) for k, v in (g.get("shots") or {}).items()}},
            "history": list(tmp.get("history") or []), "_extra": {k: v for k, v in tmp.items() if k not in ("schema", "revision", "grades", "luts", "presets", "history")}}


# ---------------------------------------------------------------- the maths (pure: numbers in, filter text out)

def _w_shadows(x: str) -> str:
    return f"(6.75*{x}*pow(1-{x},2))"


def _w_highlights(x: str) -> str:
    return f"(6.75*pow({x},2)*(1-{x}))"


def channel_expr(g: dict, c: int) -> str:
    """lutrgb expression for channel c (0 red, 1 green, 2 blue), from a clean grade. Every step is a plain function of the channel's own value."""
    x = "(val/maxval)"
    e = 2.0 ** g.get("exposure", 0.0)
    temp, tint = g.get("temperature", 0.0), g.get("tint", 0.0)
    mult = [1 + 0.25 * temp, 1 - 0.12 * tint, 1 - 0.25 * temp][c]
    e *= mult
    lift = g.get("lift", 0.0) + (g.get("lift_rgb") or [0, 0, 0])[c]
    gain = g.get("gain", 0.0) + (g.get("gain_rgb") or [0, 0, 0])[c]
    gam = g.get("gamma", 0.0) + (g.get("gamma_rgb") or [0, 0, 0])[c]
    slope, offset, power = 1 + 0.5 * gain, 0.2 * lift, 2.0 ** (-max(-2.0, min(2.0, gam)))
    y = f"clip({x}*{e:.5f}*{slope:.5f}+{offset:.5f},0,1)"
    if power != 1.0:
        y = f"pow({y},{power:.5f})"
    tone = []
    for key, w in (("shadows", _w_shadows), ("highlights", _w_highlights)):
        if g.get(key):
            tone.append(f"{g[key] * 0.12:+.5f}*{w('Y')}")
    if g.get("blacks"):
        tone.append(f"{g['blacks'] * 0.12:+.5f}*pow(1-Y,4)")
    if g.get("whites"):
        tone.append(f"{g['whites'] * 0.12:+.5f}*pow(Y,4)")
    if tone:
        y = "clip(Y" + "".join(tone) + ",0,1)"
        y = y.replace("Y", f"clip({x}*{e:.5f}*{slope:.5f}+{offset:.5f},0,1)" if power == 1.0 else f"pow(clip({x}*{e:.5f}*{slope:.5f}+{offset:.5f},0,1),{power:.5f})")
    k, b = 1 + g.get("contrast", 0.0), 0.25 * g.get("brightness", 0.0)
    if k != 1.0 or b:
        y = f"clip(({y}-0.5)*{k:.5f}+0.5+{b:.5f},0,1)"
    return f"clip({y},0,1)*maxval"


def swing(g: dict) -> dict:
    """What the pointwise part does at black and at white, before the final clip: used to say plainly when a grade pushes values out of range. Mirrors channel_expr."""
    out = {"clipped_whites": False, "crushed_blacks": False}
    for c in range(3):
        for x, key in ((0.0, "crushed_blacks"), (1.0, "clipped_whites")):
            v = _apply_point(g, c, x)
            if (key == "clipped_whites" and v >= 0.999 and x < 1.0) or (key == "crushed_blacks" and v <= 0.001 and x > 0.0):
                out[key] = True
    # a few more points show a squeezed range even when the end points are fine
    for c in range(3):
        if _apply_point(g, c, 0.95) >= 0.999 and g.get("exposure", 0) + g.get("gain", 0) + g.get("contrast", 0) > 0:
            out["clipped_whites"] = True
        if _apply_point(g, c, 0.05) <= 0.001 and (g.get("contrast", 0) > 0 or g.get("exposure", 0) < 0 or g.get("lift", 0) < 0):
            out["crushed_blacks"] = True
    return out


def _apply_point(g: dict, c: int, x: float) -> float:
    e = 2.0 ** g.get("exposure", 0.0) * [1 + 0.25 * g.get("temperature", 0.0), 1 - 0.12 * g.get("tint", 0.0), 1 - 0.25 * g.get("temperature", 0.0)][c]
    lift = g.get("lift", 0.0) + (g.get("lift_rgb") or [0, 0, 0])[c]
    gain = g.get("gain", 0.0) + (g.get("gain_rgb") or [0, 0, 0])[c]
    gam = g.get("gamma", 0.0) + (g.get("gamma_rgb") or [0, 0, 0])[c]
    y = min(1.0, max(0.0, x * e * (1 + 0.5 * gain) + 0.2 * lift)) ** (2.0 ** (-max(-2.0, min(2.0, gam))))
    y += 0.12 * (g.get("shadows", 0.0) * 6.75 * y * (1 - y) ** 2 + g.get("highlights", 0.0) * 6.75 * y * y * (1 - y) + g.get("blacks", 0.0) * (1 - y) ** 4 + g.get("whites", 0.0) * y ** 4)
    y = min(1.0, max(0.0, y))
    return min(1.0, max(0.0, (y - 0.5) * (1 + g.get("contrast", 0.0)) + 0.5 + 0.25 * g.get("brightness", 0.0)))


def _mix_matrix(sat: float, hue: float) -> list[float] | None:
    """3x3 for saturation (1 = unchanged) then hue turn, with the luma weights of the W3C filter definitions; None when it would do nothing."""
    if abs(sat - 1.0) < 1e-6 and abs(hue) < 1e-6:
        return None
    lr, lg, lb = 0.213, 0.715, 0.072
    s = [[lr + (1 - lr) * sat, lg - lg * sat, lb - lb * sat], [lr - lr * sat, lg + (1 - lg) * sat, lb - lb * sat], [lr - lr * sat, lg - lg * sat, lb + (1 - lb) * sat]]
    a = math.radians(hue)
    c, n = math.cos(a), math.sin(a)
    h = [[lr + c * (1 - lr) - n * lr, lg - c * lg - n * lg, lb - c * lb + n * (1 - lb)],
         [lr - c * lr + n * 0.143, lg + c * (1 - lg) + n * 0.140, lb - c * lb - n * 0.283],
         [lr - c * lr - n * (1 - lr), lg - c * lg + n * lg, lb + c * (1 - lb) + n * lb]]
    m = [[sum(h[i][k] * s[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return [m[0][0], m[0][1], m[0][2], m[1][0], m[1][1], m[1][2], m[2][0], m[2][1], m[2][2]]


TO_RGB = "scale=in_range=tv:in_color_matrix=bt709:out_range=pc:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int,format=gbrp16le"
TO_YUV = "scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=accurate_rnd+full_chroma_int,format=yuv420p"


def _fesc(path: str) -> str:
    """A file name as an ffmpeg filter option: slashes forward, the drive colon and any apostrophe escaped, the whole thing quoted. The file name is a hash we made; the folder is the person's own
    ("Sarah's film"), so an apostrophe needs the three-level escape below (found by trying it against ffmpeg, see the test)."""
    p = path.replace("\\", "/").replace(":", "\\:").replace("'", "'" + "\\" * 3 + "''")
    return f"'{p}'"


def grade_chain(g: dict, lut_file: str | None = None, lut_dims: int = 3) -> str:
    """The filter text for one clean grade ('' when it does nothing)."""
    if not g or g.get("off"):
        return ""
    parts: list[str] = []
    pointwise = any(g.get(k) for k in ("exposure", "brightness", "contrast", "highlights", "shadows", "whites", "blacks", "temperature", "tint", "gamma", "lift", "gain") + RGB3)
    if pointwise:
        r, gg, b = (channel_expr(g, c) for c in range(3))
        parts.append(f"lutrgb=r='{r}':g='{gg}':b='{b}'")
    m = _mix_matrix(1.0 + g.get("saturation", 0.0), g.get("hue", 0.0))
    if m:
        names = ("rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb")
        parts.append("colorchannelmixer=" + ":".join(f"{n}={v:.5f}" for n, v in zip(names, m)))
    if g.get("vibrance"):
        parts.append(f"vibrance=intensity={g['vibrance'] * 1.5:.4f}")
    if lut_file:
        parts.append((f"lut3d=file={_fesc(lut_file)}:interp=tetrahedral" if lut_dims == 3 else f"lut1d=file={_fesc(lut_file)}:interp=cubic"))
    return ",".join([TO_RGB, *parts, TO_YUV]) if parts else ""


# ---------------------------------------------------------------- LUTs

def parse_cube(text: str) -> dict:
    """A strict .cube file. Returns {title, dims, size, rows}. Raises SystemExit with a plain reason for anything it will not take."""
    title, dims, size, rows = "", 0, 0, []
    dmin, dmax = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    for n, line in enumerate(text.splitlines(), 1):
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        w = s.split()
        key = w[0].upper()
        if key == "TITLE":
            title = s[5:].strip().strip('"')[:80]
        elif key in ("LUT_3D_SIZE", "LUT_1D_SIZE"):
            if dims:
                raise SystemExit("This LUT file says its size twice.")
            try:
                size = int(w[1])
            except (IndexError, ValueError):
                raise SystemExit(f"Line {n}: the LUT size is not a whole number.")
            dims = 3 if key == "LUT_3D_SIZE" else 1
            if not (2 <= size <= (MAX_3D if dims == 3 else MAX_1D)):
                raise SystemExit(f"This LUT's size ({size}) is outside what FilmCrafter takes ({'2 to %d' % (MAX_3D if dims == 3 else MAX_1D)}).")
        elif key in ("DOMAIN_MIN", "DOMAIN_MAX"):
            try:
                v = tuple(float(x) for x in w[1:4])
            except ValueError:
                raise SystemExit(f"Line {n}: the LUT domain is not made of numbers.")
            if len(v) != 3:
                raise SystemExit(f"Line {n}: the LUT domain needs three numbers.")
            if key == "DOMAIN_MIN":
                dmin = v
            else:
                dmax = v
        elif key in ("LUT_3D_INPUT_RANGE", "LUT_1D_INPUT_RANGE"):
            raise SystemExit("This LUT uses an input range other than 0 to 1, which FilmCrafter does not take.")
        else:
            try:
                v3 = tuple(float(x) for x in w)
            except ValueError:
                raise SystemExit(f"Line {n}: this is not a .cube LUT line ({w[0][:20]}).")
            if len(v3) != 3 or not all(math.isfinite(x) and -0.5 <= x <= 1.5 for x in v3):
                raise SystemExit(f"Line {n}: a LUT row needs three numbers between -0.5 and 1.5.")
            rows.append(v3)
    if not dims:
        raise SystemExit("This is not a .cube LUT: it has no LUT_3D_SIZE or LUT_1D_SIZE.")
    if dmin != (0.0, 0.0, 0.0) or dmax != (1.0, 1.0, 1.0):
        raise SystemExit("This LUT has a domain other than 0 to 1, which FilmCrafter does not take.")
    want = size ** 3 if dims == 3 else size
    if len(rows) != want:
        raise SystemExit(f"This LUT should have {want} rows for its size and has {len(rows)}.")
    return {"title": title, "dims": dims, "size": size, "rows": rows}


def _cube_text(title: str, dims: int, size: int, rows) -> str:
    head = [f'TITLE "{title}"'] if title else []
    head.append(f"LUT_{'3D' if dims == 3 else '1D'}_SIZE {size}")
    return "\n".join(head + [f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in rows]) + "\n"


def lut_import(d: str, path: str, name: str = "", kind: str = "creative", space_in: str = "rec709", space_out: str = "rec709") -> dict:
    """Take a LUT file you picked: checked, then copied in by the hash of its content. Reading it changes nothing of yours."""
    if kind not in ("creative", "technical"):
        raise SystemExit("A LUT is either creative or technical.")
    if space_in not in SPACES or space_out not in SPACES:
        raise SystemExit("That colour space is not one of the choices.")
    p = os.path.realpath(str(path or ""))
    if not p.lower().endswith(".cube") or not os.path.isfile(p):
        raise SystemExit("Choose a .cube LUT file.")
    if os.path.getsize(p) > MAX_LUT_BYTES:
        raise SystemExit("This LUT file is too large.")
    with open(p, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SystemExit("This LUT file is not plain text.")
    cube = parse_cube(text)
    norm = _cube_text(cube["title"], cube["dims"], cube["size"], cube["rows"])
    lid = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
    os.makedirs(os.path.join(edit_dir(d), "luts"), exist_ok=True)
    dest = os.path.join(edit_dir(d), "luts", f"{lid}.cube")
    if not os.path.isfile(dest):
        tmp = f"{dest}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(norm)
        os.replace(tmp, dest)
    label = " ".join(str(name or cube["title"] or os.path.splitext(os.path.basename(p))[0]).split())[:60] or "LUT"

    def change(cur):
        old = cur["luts"].get(lid) or {}
        cur["luts"][lid] = {"name": label, "kind": kind, "space_in": space_in, "space_out": space_out, "dims": cube["dims"], "size": cube["size"], "favorite": bool(old.get("favorite")),
                            "added": int(old.get("added") or time.time())}
    return _save(d, change, f"added the LUT {label}")


def lut_remove(d: str, lid: str) -> dict:
    def change(cur):
        if lid not in cur["luts"]:
            raise SystemExit("That LUT is not in the library.")
        users = [f"{s} {k}" for s, table in (("film", {"": cur["grades"]["film"]}), ("scene", cur["grades"]["scenes"]), ("shot", cur["grades"]["shots"])) for k, g in table.items() if (g.get("lut") or {}).get("id") == lid]
        if users:
            raise SystemExit("This LUT is used by a grade (" + ", ".join(users[:3]).strip() + "). Take it off there first.")
        cur["luts"].pop(lid)
    out = _save(d, change, "removed a LUT")
    f = os.path.join(edit_dir(d), "luts", f"{lid}.cube")
    if lid.isalnum() and os.path.isfile(f):
        os.remove(f)
    return out


def lut_favorite(d: str, lid: str, on: bool) -> dict:
    def change(cur):
        if lid not in cur["luts"]:
            raise SystemExit("That LUT is not in the library.")
        cur["luts"][lid]["favorite"] = bool(on)
    return _save(d, change, "marked a LUT")


def _lut_file(d: str, lid: str, k: float) -> tuple[str, int]:
    """The file the filter reads: the LUT itself at full strength, or the LUT blended with the identity (made once, kept by hash and strength)."""
    src = os.path.join(edit_dir(d), "luts", f"{lid}.cube")
    if not os.path.isfile(src):
        raise SystemExit("A LUT used by this film is missing from its edit folder. Import it again, or take it off the grade.")
    with open(src, encoding="utf-8") as f:
        cube = parse_cube(f.read())
    if k >= 0.999:
        return src, cube["dims"]
    cache = os.path.join(edit_dir(d), "cache")
    os.makedirs(cache, exist_ok=True)
    out = os.path.join(cache, f"{lid}_{int(round(k * 100)):03d}.cube")
    if not os.path.isfile(out):
        n, rows = cube["size"], cube["rows"]
        mixed = []
        if cube["dims"] == 3:
            for i, (r, g, b) in enumerate(rows):
                ri, gi, bi = i % n, (i // n) % n, i // (n * n)       # .cube lists red fastest
                idr, idg, idb = ri / (n - 1), gi / (n - 1), bi / (n - 1)
                mixed.append((idr + (r - idr) * k, idg + (g - idg) * k, idb + (b - idb) * k))
        else:
            for i, (r, g, b) in enumerate(rows):
                t = i / (n - 1)
                mixed.append((t + (r - t) * k, t + (g - t) * k, t + (b - t) * k))
        tmp = f"{out}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(_cube_text("", cube["dims"], n, mixed))
        os.replace(tmp, out)
    return out, cube["dims"]


def _check_lut_use(meta: dict) -> None:
    if (meta.get("space_in") or "other") != PICTURE_SPACE:
        raise SystemExit(f"This LUT expects {meta.get('space_in', 'other')} footage, and FilmCrafter's pictures are Rec.709. It is not applied: using it would change the colours in a way it was not made for.")
    if (meta.get("space_out") or "other") != PICTURE_SPACE:
        raise SystemExit(f"This LUT makes {meta.get('space_out', 'other')} pictures, and the film is Rec.709. It is not applied.")


# ---------------------------------------------------------------- one shot's filter

def effective(d: str, shot_id: str, scene) -> list[tuple[str, dict]]:
    """The grades that apply to this shot, in the order they are put on: the film's, the scene's, the shot's."""
    g = load(d)["grades"]
    out = []
    for scope, grade in (("film", g["film"]), ("scene", g["scenes"].get(str(scene))), ("shot", g["shots"].get(shot_id))):
        if grade and not grade.get("off"):
            out.append((scope, grade))
    return out


def filter_for(d: str, shot_id: str, scene=None) -> str:
    """The ffmpeg text for this shot's grades ('' when there are none). Raises with a plain message when a LUT is missing or not for Rec.709 pictures."""
    st = load(d)
    chains = []
    for scope, grade in effective(d, shot_id, scene):
        lf, dims = None, 3
        lut = grade.get("lut")
        if lut:
            meta = st["luts"].get(lut["id"])
            if not meta:
                raise SystemExit("A grade uses a LUT that is no longer in the library.")
            _check_lut_use(meta)
            lf, dims = _lut_file(d, lut["id"], lut["intensity"])
        c = grade_chain(grade, lf, dims)
        if c:
            chains.append(c)
    return ",".join(chains)


# ---------------------------------------------------------------- state and edits

def state(d: str) -> dict:
    s = load(d)
    notes = {}
    for scope, table in (("film", {"": s["grades"]["film"]}), ("scene", s["grades"]["scenes"]), ("shot", s["grades"]["shots"])):
        for k, g in table.items():
            if g:
                notes[f"{scope}:{k}" if k else scope] = swing(g)
    return {"revision": s["revision"], "grades": s["grades"], "luts": [{"id": k, **v} for k, v in sorted(s["luts"].items(), key=lambda kv: (not kv[1].get("favorite"), kv[1].get("name", "").lower()))],
            "presets": [{"name": k, "grade": v} for k, v in sorted(s["presets"].items())], "ranges": {k: list(v) for k, v in RANGES.items()}, "swing": notes,
            "history": [{"rev": h.get("rev"), "at": h.get("at"), "what": h.get("what")} for h in s["history"]][-10:], "can_undo": bool(s["history"]), "can_redo": bool(s["_extra"].get("redo")), "spaces": list(SPACES), "picture_space": PICTURE_SPACE,
            "shots": _shots(d)}


def _shots(d: str) -> list[dict]:
    """The scenes and shots of the film, so a grade can be put on one of them."""
    for name in ("directed.json", "production.json"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            try:
                plan = safeio.read_json(p, {})
            except SystemExit:
                return []
            return [{"id": sh["id"], "scene": sc.get("number"), "heading": sc.get("heading", "")} for sc in plan.get("scenes", []) for sh in sc.get("shots", []) if isinstance(sh, dict) and sh.get("id")]
    return []


def _scope_ok(scope: str, key) -> str:
    if scope not in SCOPES:
        raise SystemExit("A grade goes on the film, a scene or a shot.")
    if scope == "film":
        return ""
    k = str(key if key is not None else "").strip()
    if not k or len(k) > 40 or any(c in k for c in "/\\"):
        raise SystemExit("Say which scene or shot.")
    return k


def set_grade(d: str, scope: str, key, grade: dict) -> dict:
    k = _scope_ok(scope, key)
    g = clean_grade(grade)
    if g.get("lut"):
        meta = load(d)["luts"].get(g["lut"]["id"])
        if not meta:
            raise SystemExit("That LUT is not in the library.")
        _check_lut_use(meta)

    def change(cur):
        if scope == "film":
            cur["grades"]["film"] = g
        else:
            table = cur["grades"]["scenes" if scope == "scene" else "shots"]
            if g:
                table[k] = g
            else:
                table.pop(k, None)
    return _save(d, change, f"set the {scope} grade" + (f" {k}" if k else ""))


def clear_grade(d: str, scope: str, key) -> dict:
    return set_grade(d, scope, key, {})


def preset_save(d: str, name: str, scope: str, key) -> dict:
    nm = " ".join(str(name or "").split())[:60]
    if not nm:
        raise SystemExit("Give the look a name.")
    k = _scope_ok(scope, key)
    cur = load(d)["grades"]
    g = cur["film"] if scope == "film" else cur["scenes" if scope == "scene" else "shots"].get(k) or {}
    if not g:
        raise SystemExit("There is nothing set there to save.")
    return _save(d, lambda c: c["presets"].__setitem__(nm, dict(g)), f"saved the look {nm}")


def preset_apply(d: str, name: str, scope: str, key) -> dict:
    p = load(d)["presets"].get(str(name))
    if not p:
        raise SystemExit("That look is not saved.")
    return set_grade(d, scope, key, p)


def preset_delete(d: str, name: str) -> dict:
    def change(cur):
        if str(name) not in cur["presets"]:
            raise SystemExit("That look is not saved.")
        cur["presets"].pop(str(name))
    return _save(d, change, "deleted a saved look")


def undo(d: str) -> dict:
    """Put back what the last change replaced: a grade, a saved look, or a cut."""
    s = load(d)
    if not s["history"]:
        raise SystemExit("There is nothing to undo.")
    last = s["history"][-1]

    def run(data):
        _refuse_newer(data)
        cur = _normalise(data if isinstance(data, dict) else {})
        redo = [x for x in (cur["_extra"].get("redo") if isinstance(cur["_extra"].get("redo"), list) else []) if isinstance(x, dict)]
        redo.append({"what": last.get("what", ""), "after": snapshot(cur)})
        cur["_extra"]["redo"] = redo[-HISTORY:]
        restore(cur, last.get("before") or {})
        cur["history"] = cur["history"][:-1]
        cur["revision"] = max(0, cur["revision"] - 1)
        return _out(cur)
    os.makedirs(edit_dir(d), exist_ok=True)
    safeio.update_json(_path(d), run, {})
    return state(d)


def redo(d: str) -> dict:
    """Do again what was just undone (until a new change is made)."""
    s = load(d)
    stack = [x for x in (s["_extra"].get("redo") if isinstance(s["_extra"].get("redo"), list) else []) if isinstance(x, dict)]
    if not stack:
        raise SystemExit("There is nothing to do again.")
    last = stack[-1]

    def run(data):
        _refuse_newer(data)
        cur = _normalise(data if isinstance(data, dict) else {})
        cur["_extra"]["redo"] = [x for x in cur["_extra"].get("redo", [])][:-1]
        cur["history"] = (cur["history"] + [{"rev": cur["revision"] + 1, "at": int(time.time()), "what": last.get("what", ""), "before": snapshot(cur)}])[-HISTORY:]
        restore(cur, last.get("after") or {})
        cur["revision"] += 1
        return _out(cur)
    os.makedirs(edit_dir(d), exist_ok=True)
    safeio.update_json(_path(d), run, {})
    return state(d)


# ---------------------------------------------------------------- a frame, before and after, through the same text the export uses

def preview(d: str, shot_id: str, grade: dict | None = None) -> dict:
    """One frame of the shot's take, as it is and as it will be graded (the grade you are editing, or the saved one). The files are small pictures in the project's cache."""
    from . import export as E, colormatch
    from .library import chosen_take, shot_state
    from .safe import check_id
    shot_id = check_id(shot_id, "shot")
    plan_name = "directed" if os.path.exists(os.path.join(d, "directed.json")) else "production"
    plan = safeio.read_json(os.path.join(d, f"{plan_name}.json"), {})
    scene = next((sc for sc in plan.get("scenes", []) for sh in sc.get("shots", []) if sh.get("id") == shot_id), None)
    if scene is None:
        raise SystemExit("That shot is not in the film.")
    jobs = (safeio.read_json(os.path.join(d, "jobs.json"), {"jobs": []}) or {}).get("jobs", [])
    take = chosen_take(d, shot_id, plan_name, jobs, shot_state(d))
    src = os.path.join(d, take["output"]) if take else None
    if not src or not os.path.isfile(src):
        raise SystemExit("This shot has no picture yet to look at.")
    base = colormatch.filter_for(d, shot_id)
    st = load(d)
    if grade is not None:                    # the grade being edited, not yet saved: it stands in for the shot's own, over the film's and scene's
        g = clean_grade(grade)
        if g.get("lut"):
            meta = st["luts"].get(g["lut"]["id"])
            if not meta:
                raise SystemExit("That LUT is not in the library.")
            _check_lut_use(meta)
        grades = [x for scope, x in effective(d, shot_id, scene.get("number")) if scope != "shot"] + ([g] if g else [])
    else:
        grades = [x for _, x in effective(d, shot_id, scene.get("number"))]
    extra = ",".join(c for c in (grade_chain(x, *_lutargs(d, st, x)) for x in grades) if c)
    out_dir = os.path.join(d, "cache", "grade_preview")
    os.makedirs(out_dir, exist_ok=True)
    key = hashlib.sha256(json.dumps([src, os.path.getmtime(src), base, extra], default=str).encode()).hexdigest()[:12]
    w = 640
    fill = f"scale={w}:-2,setsar=1,format=yuv420p"
    res = {}
    for label, chain in (("before", ",".join(x for x in (base,) if x)), ("after", ",".join(x for x in (base, extra) if x))):
        out = os.path.join(out_dir, f"{shot_id}_{key}_{label}.png")
        if not os.path.isfile(out):
            vf = fill + ("," + chain if chain else "") + ",format=rgb24"
            is_img = take.get("media_kind") == "image"
            cmd = [E.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", *([] if is_img else ["-ss", "0.6"]), "-i", src, "-vf", vf, "-frames:v", "1", f"{out}.{os.getpid()}.tmp.png"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode != 0 or not os.path.isfile(f"{out}.{os.getpid()}.tmp.png"):
                raise SystemExit("The preview frame could not be made: " + (r.stderr.strip().splitlines() or ["ffmpeg stopped"])[-1][:160])
            os.replace(f"{out}.{os.getpid()}.tmp.png", out)
        res[label] = os.path.relpath(out, d).replace(os.sep, "/")
    return res


def _lutargs(d: str, st: dict, g: dict):
    lut = g.get("lut")
    if not lut:
        return (None, 3)
    return _lut_file(d, lut["id"], lut["intensity"])


# ---------------------------------------------------------------- the door

ACTIONS = ("state", "set_grade", "clear_grade", "lut_import", "lut_remove", "lut_favorite", "preset_save", "preset_apply", "preset_delete", "undo", "redo", "preview")


def run(d: str, action: str, x: dict) -> dict:
    if action == "state":
        return state(d)
    if action == "set_grade":
        return set_grade(d, str(x.get("scope", "")), x.get("key"), x.get("grade") if isinstance(x.get("grade"), dict) else {})
    if action == "clear_grade":
        return clear_grade(d, str(x.get("scope", "")), x.get("key"))
    if action == "lut_import":
        return lut_import(d, str(x.get("path", "")), str(x.get("name", "")), str(x.get("kind", "creative")), str(x.get("space_in", "rec709")), str(x.get("space_out", "rec709")))
    if action == "lut_remove":
        return lut_remove(d, str(x.get("id", "")))
    if action == "lut_favorite":
        return lut_favorite(d, str(x.get("id", "")), bool(x.get("on")))
    if action == "preset_save":
        return preset_save(d, str(x.get("name", "")), str(x.get("scope", "")), x.get("key"))
    if action == "preset_apply":
        return preset_apply(d, str(x.get("name", "")), str(x.get("scope", "")), x.get("key"))
    if action == "preset_delete":
        return preset_delete(d, str(x.get("name", "")))
    if action == "undo":
        return undo(d)
    if action == "redo":
        return redo(d)
    if action == "preview":
        return preview(d, str(x.get("shot", "")), x.get("grade") if isinstance(x.get("grade"), dict) else None)
    raise SystemExit("Unknown action.")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="filmcrafter-grading")
    ap.add_argument("action", choices=["state", "set_grade", "clear_grade", "lut_import", "lut_remove", "lut_favorite", "preset_save", "preset_apply", "preset_delete", "undo", "redo", "preview"])
    ap.add_argument("project")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data)
        print(json.dumps({"event": "result", "data": run(a.project, a.action, x if isinstance(x, dict) else {})}, ensure_ascii=False), flush=True)
        return 0
    except SystemExit as e:
        print(json.dumps({"event": "error", "message": str(e)}), flush=True)
    except Exception as e:                       # noqa: BLE001
        print(json.dumps({"event": "error", "message": __import__("filmcrafter_engine.errtext", fromlist=["plain"]).plain(e)}), flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
