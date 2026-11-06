"""Virtual production, part 1: the cutout studio. Take a subject filmed or generated against a green or blue screen, cut it out, and put it on a different background.

This is the film's side of `keying` (which only does the picture work): the pictures a film keeps, the cutouts made from them, and the compositions that place cutouts on a background.

  <film>/vp/vp.json                      { sources, cutouts, compositions, removed }       (safeio; nothing is deleted: removed items move to `removed`)
  <film>/vp/sources/<name>               a picture brought in (a plate with a screen, a background, a foreground), copied in, never changed
  <film>/vp/cutouts/<id>/cutout.png      the subject as a straight-alpha RGBA PNG        (and mask.png: the transparency alone, grey)
  <film>/vp/renders/<name>.png           a finished composition
  <film>/exports/virtual-production/     what `export` copies out: an RGBA PNG and its mask

Everything free and local: no provider, no key, no network. A cutout is made again with other settings by giving the same source again: each one is kept and named.
`plate_prompt` only writes the words to ask an image or video maker for a clean screen plate; it sends nothing, and nothing in this module checks that a generated plate is good until `plate_check`
and `key` look at it. Stills only here: video, sequences and keyframes come next.

  python -m filmcrafter_engine.vpstudio <get|import|plate_check|key|cutout_remove|export|compose_set|compose_remove|render|plate_prompt> <film> --data '{...}'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import uuid

import numpy as np
from PIL import Image

from . import keying as K
from . import safeio

KINDS = ("plate", "background", "foreground")
EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
MAX_FILE = 120 * 1024 * 1024
MAX_SOURCES, MAX_CUTOUTS, MAX_COMPS, MAX_LAYERS = 300, 300, 100, 24
MAX_SIDE = 8192
KEEP_REMOVED = 200


def emit(**kw) -> None:
    try:
        print(json.dumps(kw, ensure_ascii=False), flush=True)
    except (OSError, ValueError):
        pass


def _t(v, limit: int) -> str:
    return " ".join(str(v if v is not None else "").replace("\x00", "").split())[:limit]


def _n(v, lo: float, hi: float, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return min(hi, max(lo, x))


# ---------------------------------------------------------------- the film's record

def _film(d: str) -> None:
    m = safeio.read_json(os.path.join(d, "film.json"), None)
    if not isinstance(m, dict) or "story" not in m:
        raise SystemExit("That isn't a FilmCrafter film.")


def _path(d: str) -> str:
    return os.path.join(d, "vp", "vp.json")


def _empty() -> dict:
    return {"schema": 1, "sources": [], "cutouts": [], "compositions": [], "removed": []}


def _ok(r: object) -> bool:
    return isinstance(r, dict) and all(isinstance(r.get(k, []), list) for k in ("sources", "cutouts", "compositions", "removed"))


def _norm(r: dict) -> dict:
    r.setdefault("schema", 1)
    for k in ("sources", "cutouts", "compositions", "removed"):
        if not isinstance(r.get(k), list):
            r[k] = []
        r[k] = [x for x in r[k] if isinstance(x, dict)]
    return r


def _load(d: str) -> dict:
    return _norm(safeio.read_json(_path(d), None, check=_ok) or _empty())


def _update(d: str, change) -> None:
    def wrap(r):
        change(_norm(r))
        return r
    safeio.update_json(_path(d), wrap, _empty(), check=_ok)


def _inside(d: str, rel: str) -> str:
    """The full path of a film file written relative to the film, refusing anything that leads outside it."""
    base = os.path.realpath(d)
    full = os.path.realpath(os.path.join(d, rel))
    if not (full == base or full.startswith(base + os.sep)):
        raise SystemExit("That file is not inside the film.")
    return full


def _source(r: dict, sid: str) -> dict:
    s = next((s for s in r["sources"] if s.get("id") == sid), None)
    if not s:
        raise SystemExit("That picture isn't in the film's virtual production folder.")
    return s


def _open_source(d: str, s: dict) -> np.ndarray:
    return K.load(_inside(d, s["file"]))


def _cutout(r: dict, cid: str) -> dict:
    c = next((c for c in r["cutouts"] if c.get("id") == cid), None)
    if not c:
        raise SystemExit("That cutout isn't in the film.")
    return c


# ---------------------------------------------------------------- bringing a picture in

def import_source(d: str, data: dict) -> dict:
    """Copy a picture into the film as a plate (a subject on a screen), a background or a foreground. The original is never touched; the same picture twice is kept once."""
    _film(d)
    src = str(data.get("path") or "")
    kind = data.get("kind") if data.get("kind") in KINDS else "plate"
    if not src or not os.path.isfile(src):
        raise SystemExit("Choose a picture file.")
    ext = os.path.splitext(src)[1].lower()
    if ext not in EXTS:
        raise SystemExit("Choose a PNG, JPG, WebP, BMP or TIFF picture.")
    if os.path.getsize(src) > MAX_FILE:
        raise SystemExit("That file is larger than 120 MB.")
    try:
        with Image.open(src) as im:
            im.verify()
        with Image.open(src) as im:
            w, h = im.size
    except Exception:
        raise SystemExit("That file could not be read as a picture.")
    if w * h > K.MAX_PIXELS or max(w, h) > MAX_SIDE:
        raise SystemExit(f"That picture is {w} by {h}: the limit is {MAX_SIDE} pixels on a side.")
    raw = open(src, "rb").read()
    sha = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
    name = _t(data.get("name") or os.path.splitext(os.path.basename(src))[0], 60) or "picture"
    holder: dict = {}

    def change(r):
        old = next((s for s in r["sources"] if s.get("sha1") == sha and s.get("kind") == kind), None)
        if old:
            holder["id"], holder["same"] = old["id"], True
            return
        if len(r["sources"]) >= MAX_SOURCES:
            raise SystemExit(f"At most {MAX_SOURCES} pictures.")
        sid = f"vs-{uuid.uuid4().hex[:8]}"
        rel = f"vp/sources/{sid}{ext}"
        full = _inside(d, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(raw)
        r["sources"].append({"id": sid, "kind": kind, "name": name, "file": rel, "sha1": sha, "width": w, "height": h, "bytes": len(raw), "added": time.time()})
        holder["id"], holder["same"] = sid, False
    _update(d, change)
    return {**get(d), "id": holder["id"], "already_there": holder["same"]}


# ---------------------------------------------------------------- the plate and the key

def plate_check(d: str, sid: str, screen: str | None = None) -> dict:
    """Is this plate a screen a key can work on? The numbers and the plain verdict. Free; nothing is saved."""
    _film(d)
    r = _load(d)
    s = _source(r, sid)
    return {"source": sid, **K.analyze_plate(_open_source(d, s), screen if screen in K.SCREENS else None)}


def key(d: str, data: dict) -> dict:
    """Cut the subject out of a plate and keep it as a cutout (an RGBA PNG and its mask). Settings not given get their defaults; each cutout keeps the settings that made it and what the key found."""
    _film(d)
    r0 = _load(d)
    s0 = _source(r0, str(data.get("source") or ""))
    rgb = _open_source(d, s0)
    rgba, rep = K.key(rgb, data.get("params") if isinstance(data.get("params"), dict) else {})
    cid = f"cu-{uuid.uuid4().hex[:8]}"
    rel_dir = f"vp/cutouts/{cid}"
    base = _inside(d, rel_dir)
    os.makedirs(base, exist_ok=True)
    K.save_rgba(rgba, os.path.join(base, "cutout.png"))
    Image.fromarray((rgba[..., 3] * 255 + 0.5).astype(np.uint8), "L").save(os.path.join(base, "mask.png"), "PNG")
    back = Image.open(os.path.join(base, "cutout.png"))
    if back.mode != "RGBA" or back.size != (rgb.shape[1], rgb.shape[0]):
        raise SystemExit("The cutout could not be written correctly.")
    name = _t(data.get("name") or f"{s0['name']} cutout", 60) or "cutout"

    def change(r):
        _source(r, s0["id"])
        if len(r["cutouts"]) >= MAX_CUTOUTS:
            raise SystemExit(f"At most {MAX_CUTOUTS} cutouts.")
        r["cutouts"].append({"id": cid, "name": name, "source": s0["id"], "params": rep["params"], "report": {k: v for k, v in rep.items() if k != "params"}, "rgba": f"{rel_dir}/cutout.png",
                             "mask": f"{rel_dir}/mask.png", "width": int(rgb.shape[1]), "height": int(rgb.shape[0]), "created": time.time()})
    _update(d, change)
    return {**get(d), "id": cid, "report": rep}


def cutout_remove(d: str, cid: str) -> dict:
    """Take a cutout out of use. It moves aside (the files stay) and is taken out of every composition that used it."""
    _film(d)

    def change(r):
        c = _cutout(r, cid)
        r["cutouts"].remove(c)
        r["removed"].append({"kind": "cutout", "at": time.time(), "item": c})
        del r["removed"][:-KEEP_REMOVED]
        for comp in r["compositions"]:
            comp["layers"] = [l for l in comp.get("layers") or [] if l.get("cutout") != cid]
    _update(d, change)
    return get(d)


def export(d: str, cid: str) -> dict:
    """Copy a cutout out as an RGBA PNG and its mask into exports/virtual-production, and read the PNG back to check it really has transparency."""
    _film(d)
    c = _cutout(_load(d), cid)
    out = _inside(d, "exports/virtual-production")
    os.makedirs(out, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9 _.-]+", "", c["name"]).strip() or c["id"]
    stem = f"{stem} {c['id']}"
    files = {}
    for k, suffix in (("rgba", "rgba"), ("mask", "mask")):
        dst = os.path.join(out, f"{stem} {suffix}.png")
        shutil.copyfile(_inside(d, c[k]), dst)
        files[k] = f"exports/virtual-production/{os.path.basename(dst)}"
    back = Image.open(_inside(d, files["rgba"]))
    a = np.asarray(back.convert("RGBA"))[..., 3]
    ok = back.mode == "RGBA" and int(a.min()) < 255
    return {"id": cid, "files": files, "folder": out, "has_alpha": bool(ok), "transparent_share": round(float((a < 5).mean()), 4),
            "note": "An RGBA PNG keeps straight (unassociated) alpha: open it in an editor that reads PNG transparency. Transparent H.264 MP4 does not exist, so nothing here offers it."}


# ---------------------------------------------------------------- compositions

def _clean_layer(x: dict, cutouts: set) -> dict:
    cid = x.get("cutout")
    if cid not in cutouts:
        raise SystemExit("A layer uses a cutout that isn't in the film.")
    sh = x.get("shadow") if isinstance(x.get("shadow"), dict) else None
    return {"cutout": cid, "x": round(_n(x.get("x"), -2, 3, 0.5), 4), "y": round(_n(x.get("y"), -2, 3, 1.0), 4), "scale": round(_n(x.get("scale"), 0.02, 8, 1.0), 3), "rotation": round(_n(x.get("rotation"), -360, 360, 0), 1),
            "flip": bool(x.get("flip", False)), "anchor": x.get("anchor") if x.get("anchor") in ("feet", "bottom", "centre") else "feet",
            "start": round(_n(x.get("start"), 0, 3600, 0.0), 3), "loop": bool(x.get("loop", False)), "keys": K.clean_keys(x.get("keys")), "opacity": round(_n(x.get("opacity"), 0, 1, 1.0), 2), "match": round(_n(x.get("match"), 0, 1, 0.0), 2),
            "shadow": ({"strength": round(_n(sh.get("strength"), 0, 1, 0.4), 2), "blur": round(_n(sh.get("blur"), 0, 60, 8), 1), "squash": round(_n(sh.get("squash"), 0.05, 1, 0.25), 2),
                        "spread": round(_n(sh.get("spread"), 0.2, 3, 1.0), 2)} if sh else None)}


def compose_set(d: str, data: dict) -> dict:
    """Make a composition (a background and the cutouts on it, bottom to top) or change one (give its `id`). Saving a composition draws nothing: `render` does."""
    _film(d)
    holder: dict = {}

    def change(r):
        cid = data.get("id")
        old = next((c for c in r["compositions"] if c.get("id") == cid), None) if cid else None
        if cid and not old:
            raise SystemExit("That composition isn't in the film.")
        comp = dict(old or {})
        comp["name"] = _t(data.get("name", comp.get("name", "Composition")), 60) or "Composition"
        if "background" in data or "background" not in comp:
            b = data.get("background", comp.get("background"))
            if b:
                _source(r, str(b))
            comp["background"] = b or None
        if "size" in data or "size" not in comp:
            sz = data.get("size", comp.get("size")) or [1280, 720]
            if not (isinstance(sz, (list, tuple)) and len(sz) == 2):
                raise SystemExit("The size is a width and a height.")
            comp["size"] = [int(_n(sz[0], 16, MAX_SIDE, 1280)), int(_n(sz[1], 16, MAX_SIDE, 720))]
        if "colour" in data or "colour" not in comp:
            col = data.get("colour", comp.get("colour")) or [0.1, 0.1, 0.1]
            comp["colour"] = [round(_n(c, 0, 1, 0.1), 3) for c in (col if isinstance(col, (list, tuple)) and len(col) == 3 else [0.1, 0.1, 0.1])]
        if "layers" in data or "layers" not in comp:
            have = {c["id"] for c in r["cutouts"]}
            layers = data.get("layers", comp.get("layers")) or []
            if not isinstance(layers, list) or len(layers) > MAX_LAYERS:
                raise SystemExit(f"At most {MAX_LAYERS} layers.")
            comp["layers"] = [_clean_layer(x, have) for x in layers if isinstance(x, dict)]
        if old:
            old.update(comp)
            comp = old
        else:
            if len(r["compositions"]) >= MAX_COMPS:
                raise SystemExit(f"At most {MAX_COMPS} compositions.")
            comp["id"] = f"cp-{uuid.uuid4().hex[:8]}"
            comp["created"] = time.time()
            r["compositions"].append(comp)
        comp["updated"] = time.time()
        holder["id"] = comp["id"]
    _update(d, change)
    return {**get(d), "id": holder["id"]}


def compose_remove(d: str, cid: str) -> dict:
    _film(d)

    def change(r):
        c = next((c for c in r["compositions"] if c.get("id") == cid), None)
        if not c:
            raise SystemExit("That composition isn't in the film.")
        r["compositions"].remove(c)
        r["removed"].append({"kind": "composition", "at": time.time(), "item": c})
        del r["removed"][:-KEEP_REMOVED]
    _update(d, change)
    return get(d)


def render(d: str, cid: str, at: float = 0.0) -> dict:
    """Draw one frame of a composition to a PNG, at `at` seconds (0 is the first frame: keyframes and clips are read at that time). The background (or its colour), then each cutout bottom to top
    with its place, size, turn, shadow and colour match. Every render is kept under its own name. `render_video` in `vpvideo` draws it over time."""
    _film(d)
    from . import vpvideo
    r = _load(d)
    comp = next((c for c in r["compositions"] if c.get("id") == cid), None)
    if not comp:
        raise SystemExit("That composition isn't in the film.")
    W, H = comp["size"]
    tmp = __import__("tempfile").mkdtemp(prefix="fc-vp-")
    try:
        bg, base = vpvideo._background(d, r, comp, W, H, 24.0, tmp)
        layers = vpvideo._layer_frames(d, r, comp)
        out = vpvideo.compose_at(d, r, comp, float(at), bg, base, layers, 24.0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    missing = [l["cutout"] for l in comp["layers"] if not any(c["id"] == l["cutout"] for c in r["cutouts"])]
    name = f"vp/renders/{cid}-{int(time.time())}.png"
    full = _inside(d, name)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGB").save(full, "PNG")
    back = Image.open(full)
    if back.size != (W, H):
        raise SystemExit("The picture could not be written correctly.")

    def change(r2):
        c2 = next((c for c in r2["compositions"] if c.get("id") == cid), None)
        if c2 is not None:
            c2["last_render"] = name
    _update(d, change)
    return {**get(d), "id": cid, "file": name, "width": W, "height": H, "layers": len(comp["layers"]) - len(missing), "missing": missing}


# ---------------------------------------------------------------- asking for a clean plate (words only)

FRAMING = {"full": "full body, head to feet in frame with room around", "half": "waist up", "close": "head and shoulders", "prop": "the object alone, centred, with room around"}
LIGHT = {"front": "soft even light from the front", "left": "key light from camera left, soft fill", "right": "key light from camera right, soft fill", "back": "gentle rim light from behind, front softly filled",
         "top": "soft light from above"}
ANGLE = {"eye": "eye-level camera", "low": "low camera angle", "high": "high camera angle"}
MOVE = {"still": "the subject stands still", "walk": "the subject walks toward the camera on the spot", "turn": "the subject turns slowly", "gesture": "the subject gestures naturally while standing"}


MODES = ("full", "green_screen", "transparent")


def clean_production(x) -> dict:
    """A shot's production mode and plate settings, each from its list. Anything else (a number, a list, a word not in the list) is the default: a full scene."""
    x = x if isinstance(x, dict) else {}

    def pick(key, allowed, default):
        v = x.get(key)
        return v if isinstance(v, str) and v in allowed else default
    return {"mode": pick("mode", MODES, "full"), "screen": pick("screen", K.SCREENS, "green"), "framing": pick("framing", FRAMING, "full"), "light": pick("light", LIGHT, "front"),
            "angle": pick("angle", ANGLE, "eye"), "movement": pick("movement", MOVE, "still")}


def plate_clause(p: dict) -> str:
    """The sentence added to a shot's picture prompt when it is made as a plate (a green screen or transparent shot): the subject on a flat, even screen, lit and framed as chosen. Words only."""
    p = clean_production(p)
    colour = "pure chroma-key green (#00B140)" if p["screen"] == "green" else "pure chroma-key blue (#0047BB)"
    return (f"Made as a plate to be keyed: {FRAMING[p['framing']]}, against a perfectly flat, evenly lit {colour} background with no shadows, gradient, floor line or props behind. "
            f"{LIGHT[p['light']].capitalize()}; {ANGLE[p['angle']]}; {MOVE[p['movement']]}. Sharp subject edges, no {p['screen']} on the subject, no reflections of the background.")


def plate_prompt(data: dict) -> dict:
    """The words to ask an image or video maker for a plate that keys well. Words only: nothing is sent. A generated screen is never guaranteed to be even, so the plate is checked (`plate_check`) before it is trusted."""
    screen = data.get("screen") if data.get("screen") in K.SCREENS else "green"
    framing = data.get("framing") if data.get("framing") in FRAMING else "full"
    light = data.get("light") if data.get("light") in LIGHT else "front"
    angle = data.get("angle") if data.get("angle") in ANGLE else "eye"
    move = data.get("movement") if data.get("movement") in MOVE else "still"
    subject = _t(data.get("subject"), 200)
    if not subject:
        raise SystemExit("Say who or what is on the screen.")
    colour = "pure chroma-key green (#00B140)" if screen == "green" else "pure chroma-key blue (#0047BB)"
    parts = [f"{subject}, {FRAMING[framing]}, against a perfectly flat, evenly lit {colour} background with no shadows, no gradient, no floor line and no props behind.",
             f"{LIGHT[light].capitalize()}; {ANGLE[angle]}; {MOVE[move]}.",
             f"Sharp subject edges, hair and clothing clearly separated from the background. No {screen} in the subject's clothes or objects, no reflections of the background, no motion blur on the edges."]
    notes = ["A generated plate is rarely perfectly even: check it with Check the screen before keying.",
             "Keep the subject well inside the frame so the border is all screen.",
             "If your subject must wear green, use a blue screen instead." if screen == "green" else "If your subject must wear blue, use a green screen instead."]
    return {"prompt": " ".join(parts), "screen": screen, "notes": notes, "sent": False}


# ---------------------------------------------------------------- the whole record

def get(d: str) -> dict:
    """Everything the film keeps for virtual production: pictures, cutouts (with what the key found), compositions. Free; changes nothing."""
    _film(d)
    r = _load(d)
    return {"sources": r["sources"], "cutouts": r["cutouts"], "compositions": r["compositions"], "limits": {"sources": MAX_SOURCES, "cutouts": MAX_CUTOUTS, "compositions": MAX_COMPS, "layers": MAX_LAYERS, "side": MAX_SIDE},
            "defaults": K.clean_params({})}


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["get", "import", "plate_check", "key", "cutout_remove", "export", "compose_set", "compose_remove", "render", "plate_prompt"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        if a.action == "get":
            res = get(d)
        elif a.action == "import":
            res = import_source(d, x)
        elif a.action == "plate_check":
            res = plate_check(d, x.get("source", ""), x.get("screen"))
        elif a.action == "key":
            res = key(d, x)
        elif a.action == "cutout_remove":
            res = cutout_remove(d, x.get("id", ""))
        elif a.action == "export":
            res = export(d, x.get("id", ""))
        elif a.action == "compose_set":
            res = compose_set(d, x)
        elif a.action == "compose_remove":
            res = compose_remove(d, x.get("id", ""))
        elif a.action == "render":
            res = render(d, x.get("id", ""), x.get("time") or 0.0)
        else:
            res = plate_prompt(x)
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
