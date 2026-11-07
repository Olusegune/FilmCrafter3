"""WorldLock: a set that exists on its own, and cameras that look at it.

A film keeps its sets in `worldlock/<set id>/`. A **set** is a versioned package: a world (metres, an origin, bounds), flat **layers** and props standing in it at fixed world coordinates, characters
placed on the floor, saved **cameras**, lights and an environment state (stored, for the planner and for prompts; they are not painted into the pictures), and **events** that change the set over the
shots of the film (a basket falls in shot 12 and is on the floor from shot 13). The set as built is never altered by an event: events are replayed on top of it (`worldmath.state_at`).

What a view shows is computed, not generated: the pictures standing in the set are placed by the pinhole projection in `worldmath`, so the same camera always gives the same picture, moving a camera
never moves an object, and a camera move that goes past what the pictures cover shows a gap that is *reported* (`uncovered`), never filled with invented picture.

Everything goes through one mutation path: a locked set refuses changes; every change keeps the state before it (undo and redo, 50 deep); every change counts a version number; a **version** can also be
saved by name (kept forever) and restored; nothing is deleted (a removed layer moves to `removed`; its picture file stays; a removed set moves to `worldlock/_removed/`).

  <film>/worldlock/<id>/set.json            the set
  <film>/worldlock/<id>/history.json        { undo: [...], redo: [...] }  the states before and after
  <film>/worldlock/<id>/versions/<n>.json   named versions
  <film>/worldlock/<id>/assets/<id>.png     the pictures (copied in; the originals are never touched)
  <film>/worldlock/<id>/views/              rendered views

Free and local: no provider, no key, no network, nothing generated. 2.5D only: layers are flat. There is no depth estimation and no inpainting: separating a picture into layers is done by the person
(`cut_layer`), and what is hidden behind a layer is not known.

  python -m filmcrafter_engine.worldlock <list|create|get|meta_set|asset_add|asset_set|asset_remove|cut_layer|character_set|character_remove|camera_set|camera_remove|light_set|light_remove|
      event_set|event_remove|shot_camera|render|check|check_move|lock|unlock|undo|redo|version_save|versions|version_restore|set_remove> <film> --data '{...}'
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import shutil
import sys
import time
import uuid

import numpy as np
from PIL import Image

from . import keying as K
from . import safeio
from . import vpstudio as V
from . import world3d as W3
from . import worldmath as WM

KINDS = ("layer", "prop", "landmark")
ASPECTS = {"16:9": 16 / 9, "2.39:1": 2.39, "1.85:1": 1.85, "4:3": 4 / 3, "1:1": 1.0, "9:16": 9 / 16, "3:4": 3 / 4}
EVENT_KINDS = ("move", "state", "remove", "appear")
MAX_SETS, MAX_ASSETS, MAX_CAMERAS, MAX_CHARS, MAX_EVENTS, MAX_LIGHTS, MAX_HISTORY = 40, 200, 30, 30, 200, 8, 50
SPAN = 1000.0
MAX_VIEW = (2560, 1440)
GAP_WARN = 0.02
SKY = (0.10, 0.11, 0.14)


def emit(**kw) -> None:
    V.emit(**kw)


_t, _n = V._t, V._n


# ---------------------------------------------------------------- where things live

def _root(d: str) -> str:
    return os.path.join(d, "worldlock")


def _dir(d: str, sid: str) -> str:
    if not isinstance(sid, str) or not sid.startswith("ws-") or not sid[3:].isalnum():
        raise SystemExit("That set isn't in the film.")
    return V._inside(d, f"worldlock/{sid}")


def _ok(r: object) -> bool:
    return isinstance(r, dict) and r.get("schema") == 1 and isinstance(r.get("assets"), list) and isinstance(r.get("cameras"), list) and isinstance(r.get("world"), dict)


def _hok(r: object) -> bool:
    return isinstance(r, dict) and isinstance(r.get("undo", []), list) and isinstance(r.get("redo", []), list)


def _load(d: str, sid: str) -> dict:
    p = os.path.join(_dir(d, sid), "set.json")
    s = safeio.read_json(p, None, check=_ok)
    if s is None:
        raise SystemExit("That set isn't in the film.")
    for k in ("assets", "cameras", "characters", "events", "lights", "removed", "shots", "models", "groups"):
        if not isinstance(s.get(k), list):
            s[k] = []
        s[k] = [x for x in s[k] if isinstance(x, dict)]
    sk = s.get("sky") if isinstance(s.get("sky"), dict) else {}
    s["sky"] = {"top": sk.get("top"), "horizon": sk.get("horizon"), "fog": sk.get("fog", 0.0)}
    g = s.get("ground") if isinstance(s.get("ground"), dict) else {}
    s["ground"] = {"visible": bool(g.get("visible", False)), "y": g.get("y", 0.0), "colours": g.get("colours", ["#c9c4b8", "#8d887c"]), "extent": g.get("extent", 60.0)}
    return s


def _history(d: str, sid: str) -> dict:
    h = safeio.read_json(os.path.join(_dir(d, sid), "history.json"), None, check=_hok) or {}
    return {"undo": [x for x in h.get("undo", []) if isinstance(x, dict)], "redo": [x for x in h.get("redo", []) if isinstance(x, dict)]}


def _write(d: str, sid: str, s: dict, h: dict | None = None) -> None:
    base = _dir(d, sid)
    os.makedirs(base, exist_ok=True)
    safeio.write_json(os.path.join(base, "set.json"), s)
    if h is not None:
        safeio.write_json(os.path.join(base, "history.json"), {"undo": h["undo"][-MAX_HISTORY:], "redo": h["redo"][-MAX_HISTORY:]}, backup=False)


def _mutate(d: str, sid: str, label: str, fn, allow_locked: bool = False) -> dict:
    """The one way a set changes: refuse when locked; keep the state before it for undo; count a version; write atomically. `fn` raises SystemExit to refuse, and then nothing is written."""
    V._film(d)
    s = _load(d, sid)
    if s.get("locked") and not allow_locked:
        raise SystemExit("This set is locked. Unlock it to change it.")
    before = copy.deepcopy(s)
    fn(s)
    s["version"] = int(before.get("version", 1)) + 1
    s["updated"] = time.time()
    h = _history(d, sid)
    h["undo"].append({"label": label, "at": time.time(), "set": before})
    h["redo"] = []
    _write(d, sid, s, h)
    return s


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------- cleaning (everything comes from the screen)

def _pos(x, key: str, lo: float, hi: float, default: float) -> float:
    return round(_n(x.get(key), lo, hi, default), 3)


def _clean_world(w, old: dict) -> dict:
    w = w if isinstance(w, dict) else {}
    b = w.get("bounds") if isinstance(w.get("bounds"), dict) else {}
    ob = old.get("bounds", {"x": [-10.0, 10.0], "y": [0.0, 10.0], "z": [0.0, 30.0]})

    def pair(k):
        v = b.get(k, ob[k])
        if isinstance(v, (list, tuple)) and len(v) == 2:
            lo, hi = _n(v[0], -SPAN, SPAN, ob[k][0]), _n(v[1], -SPAN, SPAN, ob[k][1])
            return [round(min(lo, hi), 2), round(max(lo, hi), 2)]
        return ob[k]
    return {"units": "m", "up": "y", "origin": [0.0, 0.0, 0.0], "bounds": {"x": pair("x"), "y": pair("y"), "z": pair("z")}}


def _clean_asset(x: dict, old: dict | None) -> dict:
    a = dict(old or {})
    if "name" in x or "name" not in a:
        a["name"] = _t(x.get("name", a.get("name", "")), 60) or "Layer"
    if "kind" in x or "kind" not in a:
        a["kind"] = x.get("kind") if x.get("kind") in KINDS else a.get("kind", "layer")
    for k, lo, hi, dflt in (("x", -SPAN, SPAN, 0.0), ("y", -SPAN, SPAN, 0.0), ("z", -SPAN, SPAN, 5.0), ("width", 0.01, SPAN, 2.0), ("height", 0.01, SPAN, 2.0)):
        if k in x or k not in a:
            a[k] = _pos(x, k, lo, hi, a.get(k, dflt))
    if "tags" in x or "tags" not in a:
        a["tags"] = [t for t in dict.fromkeys(_t(v, 30).lower() for v in (x.get("tags") if isinstance(x.get("tags"), list) else a.get("tags", []))) if t][:8]
    if "note" in x or "note" not in a:
        a["note"] = _t(x.get("note", a.get("note", "")), 300)
    return a


def _clean_camera(x: dict, old: dict | None) -> dict:
    c = dict(old or {})
    if "name" in x or "name" not in c:
        c["name"] = _t(x.get("name", c.get("name", "")), 60) or "Camera"
    for k, lo, hi, dflt in (("x", -SPAN, SPAN, 0.0), ("y", -SPAN, SPAN, 1.6), ("z", -SPAN, SPAN, 0.0), ("yaw", -360, 360, 0.0), ("pitch", -85, 85, 0.0), ("fov", 10, 120, 50.0)):
        if k in x or k not in c:
            c[k] = _pos(x, k, lo, hi, c.get(k, dflt))
    # a real camera has a filmback and a focal length: the field of view follows them (or the other way round when only the field of view is given)
    if "sensor_mm" in x or "sensor_mm" not in c:
        c["sensor_mm"] = round(_n(x.get("sensor_mm"), 5, 80, c.get("sensor_mm", 36.0)), 2)
    if "focal_mm" in x:
        c["focal_mm"] = round(_n(x["focal_mm"], 8, 400, 35.0), 1)
        c["fov"] = round(math.degrees(2 * math.atan(c["sensor_mm"] / (2 * c["focal_mm"]))), 2)
    elif "fov" in x or "focal_mm" not in c:
        c["focal_mm"] = round(c["sensor_mm"] / (2 * math.tan(math.radians(c["fov"]) / 2)), 1)
    if "aperture" in x or "aperture" not in c:
        c["aperture"] = round(_n(x.get("aperture"), 1.0, 22.0, c.get("aperture", 4.0)), 1)
    if "aspect" in x or "aspect" not in c:
        c["aspect"] = x.get("aspect") if x.get("aspect") in ASPECTS else c.get("aspect", "16:9")
    if "focus" in x or "focus" not in c:
        c["focus"] = _t(x.get("focus", c.get("focus")), 64) or None
    if "note" in x or "note" not in c:
        c["note"] = _t(x.get("note", c.get("note", "")), 300)
    return c


def _clean_char(x: dict, old: dict | None, assets: set) -> dict:
    c = dict(old or {})
    if "name" in x or "name" not in c:
        c["name"] = _t(x.get("name", c.get("name", "")), 60)
    if not c["name"]:
        raise SystemExit("Give the character a name.")
    for k, lo, hi, dflt in (("x", -SPAN, SPAN, 0.0), ("z", -SPAN, SPAN, 3.0), ("facing", -360, 360, 0.0)):
        if k in x or k not in c:
            c[k] = _pos(x, k, lo, hi, c.get(k, dflt))
    if "asset" in x or "asset" not in c:
        a = x.get("asset", c.get("asset")) or None
        if a and a not in assets:
            raise SystemExit("That picture isn't in the set.")
        c["asset"] = a
    return c


def _clean_light(x: dict, old: dict | None) -> dict:
    l = dict(old or {})
    if "name" in x or "name" not in l:
        l["name"] = _t(x.get("name", l.get("name", "")), 60) or "Light"
    for k, lo, hi, dflt in (("azimuth", -360, 360, 0.0), ("elevation", -90, 90, 45.0), ("intensity", 0, 1, 0.8)):
        if k in x or k not in l:
            l[k] = _pos(x, k, lo, hi, l.get(k, dflt))
    col = _t(x.get("colour", l.get("colour", "#ffffff")), 7)
    l["colour"] = col if len(col) == 7 and col[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in col[1:]) else l.get("colour", "#ffffff")
    return l


# ---------------------------------------------------------------- sets

def _summary(s: dict) -> dict:
    return {"id": s["id"], "name": s["name"], "version": s.get("version", 1), "locked": bool(s.get("locked")), "assets": len(s["assets"]), "cameras": len(s["cameras"]), "updated": s.get("updated", 0)}


def list_sets(d: str) -> dict:
    """The film's sets. Free; changes nothing."""
    V._film(d)
    out = []
    root = _root(d)
    if os.path.isdir(root):
        for n in sorted(os.listdir(root)):
            if n.startswith("ws-") and os.path.isfile(os.path.join(root, n, "set.json")):
                try:
                    out.append(_summary(_load(d, n)))
                except SystemExit:
                    out.append({"id": n, "name": n, "version": 0, "locked": False, "assets": 0, "cameras": 0, "updated": 0, "damaged": True})
    return {"sets": out, "limits": {"sets": MAX_SETS, "assets": MAX_ASSETS, "cameras": MAX_CAMERAS, "events": MAX_EVENTS}}


def create(d: str, data: dict) -> dict:
    """Make an empty set: a world in metres with bounds, no pictures yet, and a default camera at head height looking forward."""
    V._film(d)
    if len(list_sets(d)["sets"]) >= MAX_SETS:
        raise SystemExit(f"At most {MAX_SETS} sets.")
    sid = f"ws-{uuid.uuid4().hex[:8]}"
    now = time.time()
    s = {"schema": 1, "id": sid, "name": _t(data.get("name"), 60) or "New set", "version": 1, "locked": False, "world": _clean_world(data.get("world"), {}), "assets": [], "characters": [],
         "cameras": [{"id": _id("wk"), "name": "Main camera", "x": 0.0, "y": 1.6, "z": 0.0, "yaw": 0.0, "pitch": 0.0, "fov": 50.0, "note": ""}], "lights": [], "events": [], "removed": [], "shots": [],
         "environment": {"time": "", "weather": "", "atmosphere": ""}, "axis": [], "sky": {"top": None, "horizon": None, "fog": 0.0}, "models": [], "groups": [], "ground": {"visible": False, "y": 0.0, "colours": ["#c9c4b8", "#8d887c"], "extent": 60.0}, "created": now, "updated": now}
    _write(d, sid, s, {"undo": [], "redo": []})
    return get(d, sid)


def get(d: str, sid: str) -> dict:
    """A set whole, with its undo and redo state and the names of its saved versions. Free."""
    V._film(d)
    s = _load(d, sid)
    h = _history(d, sid)
    return {**s, "can_undo": bool(h["undo"]), "can_redo": bool(h["redo"]), "undo_label": h["undo"][-1]["label"] if h["undo"] else "", "redo_label": h["redo"][-1]["label"] if h["redo"] else "",
            "saved_versions": versions(d, sid)["versions"]}


def meta_set(d: str, sid: str, data: dict) -> dict:
    """Rename a set, change its world bounds, its environment words, its lights' context, or which two characters define the line the camera must not cross."""
    def fn(s):
        if "name" in data:
            s["name"] = _t(data["name"], 60) or s["name"]
        if "world" in data:
            s["world"] = _clean_world(data["world"], s["world"])
        if isinstance(data.get("environment"), dict):
            s["environment"] = {k: _t(data["environment"].get(k, s["environment"].get(k, "")), 80) for k in ("time", "weather", "atmosphere")}
        if "axis" in data:
            ids = [c for c in (data["axis"] if isinstance(data["axis"], list) else []) if any(x["id"] == c for x in s["characters"])]
            s["axis"] = ids[:2]
    _mutate(d, sid, "Change the set", fn)
    return get(d, sid)


def lock(d: str, sid: str, on: bool) -> dict:
    """Lock a set so nothing can change it (the approved environment), or unlock it. Locking is itself kept in the undo history."""
    def fn(s):
        s["locked"] = bool(on)
    _mutate(d, sid, "Lock the set" if on else "Unlock the set", fn, allow_locked=True)
    return get(d, sid)


def set_remove(d: str, sid: str) -> dict:
    """Put a set away: its folder moves to worldlock/_removed. Nothing is deleted."""
    V._film(d)
    src = _dir(d, sid)
    _load(d, sid)
    dst = os.path.join(_root(d), "_removed", f"{sid}-{int(time.time())}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return list_sets(d)


# ---------------------------------------------------------------- pictures in the set

def _picture_source(d: str, data: dict) -> tuple[Image.Image, str]:
    """Where a new layer's picture comes from: a file the person chose, a cutout of the film's virtual production, or one of its pictures. Always opened and converted to RGBA; never altered."""
    if data.get("cutout"):
        c = V._cutout(V._load(d), str(data["cutout"]))
        return Image.open(V._inside(d, c["rgba"])).convert("RGBA"), c["name"]
    if data.get("source"):
        s = V._source(V._load(d), str(data["source"]))
        if s.get("clip"):
            raise SystemExit("Choose a picture or a cutout, not a video.")
        return Image.open(V._inside(d, s["file"])).convert("RGBA"), s["name"]
    src = str(data.get("path") or "")
    if not src or not os.path.isfile(src):
        raise SystemExit("Choose a picture file, a cutout or a picture from the film.")
    if os.path.splitext(src)[1].lower() not in V.EXTS:
        raise SystemExit("Choose a PNG, JPG, WebP, BMP or TIFF picture.")
    if os.path.getsize(src) > V.MAX_FILE:
        raise SystemExit("That file is larger than 120 MB.")
    try:
        with Image.open(src) as im:
            im.verify()
        im = Image.open(src).convert("RGBA")
    except Exception:
        raise SystemExit("That file could not be read as a picture.")
    return im, os.path.splitext(os.path.basename(src))[0]


def _save_picture(d: str, sid: str, im: Image.Image) -> tuple[str, str]:
    if im.width * im.height > K.MAX_PIXELS or max(im.size) > V.MAX_SIDE:
        raise SystemExit(f"That picture is {im.width} by {im.height}: the limit is {V.MAX_SIDE} pixels on a side.")
    aid = _id("wa")
    rel = f"worldlock/{sid}/assets/{aid}.png"
    full = V._inside(d, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    im.save(full, "PNG")
    return aid, rel


def asset_add(d: str, sid: str, data: dict) -> dict:
    """Stand a picture in the set as a layer, prop or landmark, at a world position and size (give a height or a width in metres; the other follows the picture's shape). Its id never changes."""
    V._film(d)
    _load(d, sid)
    im, nm = _picture_source(d, data)
    holder: dict = {}

    def fn(s):
        if len(s["assets"]) >= MAX_ASSETS:
            raise SystemExit(f"At most {MAX_ASSETS} pictures in a set.")
        aid, rel = _save_picture(d, sid, im)
        x = dict(data)
        x.setdefault("name", nm)
        ratio = im.width / im.height
        if "width" in x and "height" not in x:
            x["height"] = _n(x["width"], 0.01, SPAN, 2.0) / ratio
        elif "height" in x and "width" not in x:
            x["width"] = _n(x["height"], 0.01, SPAN, 2.0) * ratio
        elif "width" not in x and "height" not in x:
            x["height"] = 2.0
            x["width"] = 2.0 * ratio
        a = _clean_asset(x, None)
        a.update({"id": aid, "file": rel, "pixels": [im.width, im.height], "added": time.time()})
        s["assets"].append(a)
        holder["id"] = aid
    _mutate(d, sid, "Add a picture", fn)
    return {**get(d, sid), "id": holder["id"]}


def asset_set(d: str, sid: str, data: dict) -> dict:
    """Move, resize, rename or retag a picture in the set. Only the fields given change; the picture file and the id never do."""
    def fn(s):
        a = next((a for a in s["assets"] if a["id"] == data.get("id")), None)
        if not a:
            raise SystemExit("That picture isn't in the set.")
        a.update(_clean_asset(data, a))
    _mutate(d, sid, "Change a picture", fn)
    return get(d, sid)


def asset_remove(d: str, sid: str, aid: str) -> dict:
    """Take a picture out of the set. It moves to `removed` (the file stays); events that named it stay too and the checks will point at them."""
    def fn(s):
        a = next((a for a in s["assets"] if a["id"] == aid), None)
        if not a:
            raise SystemExit("That picture isn't in the set.")
        s["assets"].remove(a)
        s["removed"].append({**a, "removed_at": time.time()})
        s["removed"] = s["removed"][-200:]
        for c in s["characters"]:
            if c.get("asset") == aid:
                c["asset"] = None
    _mutate(d, sid, "Remove a picture", fn)
    return get(d, sid)


def cut_layer(d: str, sid: str, data: dict) -> dict:
    """Separate a region of a picture in the set into its own layer at another depth, the way a person would cut a foreground out of a backdrop: `box` is [left, top, right, bottom] as shares of the picture
    (0 to 1), `z` the new depth. The new layer is scaled and placed so that, from the camera `camera` (default: the set's first), it covers exactly the same part of the view as the region did.
    The original is left whole: what was behind the region is not known and nothing invents it, so moving the camera will show the region's old place still holding the original picture."""
    def fn(s):
        a = next((a for a in s["assets"] if a["id"] == data.get("id")), None)
        if not a:
            raise SystemExit("That picture isn't in the set.")
        box = data.get("box")
        if not (isinstance(box, (list, tuple)) and len(box) == 4):
            raise SystemExit("Give the region as left, top, right and bottom (0 to 1).")
        l, t, r, b = (_n(v, 0.0, 1.0, 0.0) for v in box)
        if r - l < 0.01 or b - t < 0.01:
            raise SystemExit("That region is too small.")
        z1 = _n(data.get("z"), -SPAN, SPAN, a["z"] * 0.5)
        cam = next((c for c in s["cameras"] if c["id"] == data.get("camera")), s["cameras"][0] if s["cameras"] else {"x": 0.0, "y": 1.6, "z": 0.0})
        if abs(a["z"] - cam["z"]) < 0.05 or z1 - cam["z"] <= WM.NEAR:
            raise SystemExit("The new depth must be in front of the camera.")
        im = Image.open(V._inside(d, a["file"])).convert("RGBA")
        w, h = im.size
        crop = im.crop((int(l * w), int(t * h), max(int(l * w) + 1, int(r * w)), max(int(t * h) + 1, int(b * h))))
        new_id, rel = _save_picture(d, sid, crop)
        k = (z1 - cam["z"]) / (a["z"] - cam["z"])                                              # the same view from the camera: scale about the camera by the ratio of depths
        wm, hm = a["width"] * (r - l), a["height"] * (b - t)
        cx = a["x"] - a["width"] / 2 + a["width"] * (l + r) / 2
        bottom_y = a["y"] + a["height"] * (1 - b)
        s["assets"].append({**_clean_asset({"name": _t(data.get("name"), 60) or f"{a['name']} (cut)", "kind": "layer", "x": cam["x"] + (cx - cam["x"]) * k, "y": cam["y"] + (bottom_y - cam["y"]) * k,
                                            "z": z1, "width": wm * k, "height": hm * k}, None), "id": new_id, "file": rel, "pixels": [crop.width, crop.height], "added": time.time(), "cut_from": a["id"]})
        data["_id"] = new_id
    _mutate(d, sid, "Cut a layer out", fn)
    return {**get(d, sid), "id": data.get("_id")}


# ---------------------------------------------------------------- cameras, characters, lights, events, shots

def _list_set(d: str, sid: str, key: str, label: str, data: dict, clean, prefix: str, cap: int, what: str) -> dict:
    holder: dict = {}

    def fn(s):
        items = s[key]
        old = next((x for x in items if x["id"] == data.get("id")), None) if data.get("id") else None
        if data.get("id") and not old:
            raise SystemExit(f"That {what} isn't in the set.")
        c = clean(data, old, s)
        if old:
            old.update(c)
            c = old
        else:
            if len(items) >= cap:
                raise SystemExit(f"At most {cap} {what}s in a set.")
            c["id"] = _id(prefix)
            items.append(c)
        holder["id"] = c["id"]
    _mutate(d, sid, label, fn)
    return {**get(d, sid), "id": holder["id"]}


def _remove(d: str, sid: str, key: str, label: str, item_id: str, what: str, also=None) -> dict:
    def fn(s):
        x = next((x for x in s[key] if x["id"] == item_id), None)
        if not x:
            raise SystemExit(f"That {what} isn't in the set.")
        s[key].remove(x)
        if also:
            also(s, item_id)
    _mutate(d, sid, label, fn)
    return get(d, sid)


def camera_set(d: str, sid: str, data: dict) -> dict:
    """Save a camera by name at a world position, yaw, pitch and field of view, or change one (give its `id`). A camera only looks: saving or moving it never changes the set."""
    return _list_set(d, sid, "cameras", "Save a camera", data, lambda x, old, s: _clean_camera(x, old), "wk", MAX_CAMERAS, "camera")


def camera_remove(d: str, sid: str, cid: str) -> dict:
    return _remove(d, sid, "cameras", "Remove a camera", cid, "camera", lambda s, i: s.__setitem__("shots", [x for x in s["shots"] if x.get("camera") != i]))


def character_set(d: str, sid: str, data: dict) -> dict:
    """Place a character on the floor of the set (a position and which way they face), optionally drawn by one of the set's pictures."""
    return _list_set(d, sid, "characters", "Place a character", data, lambda x, old, s: _clean_char(x, old, {a["id"] for a in s["assets"]}), "wc", MAX_CHARS, "character")


def character_remove(d: str, sid: str, cid: str) -> dict:
    return _remove(d, sid, "characters", "Remove a character", cid, "character", lambda s, i: s.__setitem__("axis", [a for a in s.get("axis", []) if a != i]))


def light_set(d: str, sid: str, data: dict) -> dict:
    """A light's direction, colour and strength, kept with the set. Stored for the planner and for prompts; it is not painted into the rendered views."""
    return _list_set(d, sid, "lights", "Set a light", data, lambda x, old, s: _clean_light(x, old), "wl", MAX_LIGHTS, "light")


def light_remove(d: str, sid: str, lid: str) -> dict:
    return _remove(d, sid, "lights", "Remove a light", lid, "light")


def _shot_ids(d: str) -> list[str]:
    from . import shots as S
    return [s["id"] for s in sorted(S.view(d)["shots"], key=lambda x: (int(x["scene"]), x["index"]))]


def _clean_event(d: str):
    shots = set(_shot_ids(d))

    def clean(x: dict, old: dict | None, s: dict) -> dict:
        e = dict(old or {})
        if "shot" in x or "shot" not in e:
            if x.get("shot") not in shots:
                raise SystemExit("Choose a shot in this film.")
            e["shot"] = x["shot"]
        for key, pool, what in (("asset", s["assets"], "picture"), ("character", s["characters"], "character")):
            if key in x:
                v = x.get(key) or None
                if v and not any(p["id"] == v for p in pool):
                    raise SystemExit(f"That {what} isn't in the set.")
                e[key] = v
        if not e.get("asset") and not e.get("character"):
            raise SystemExit("Say which picture or character the event is about.")
        if e.get("asset") and e.get("character"):
            raise SystemExit("An event is about one thing: a picture or a character.")
        if "kind" in x or "kind" not in e:
            e["kind"] = x.get("kind") if x.get("kind") in EVENT_KINDS else e.get("kind", "move")
        if isinstance(x.get("to"), dict):
            e["to"] = {k: round(_n(x["to"][k], -360 if k == "facing" else -SPAN, 360 if k == "facing" else SPAN, 0.0), 3) for k in ("x", "y", "z", "facing") if k in x["to"]}
        e.setdefault("to", {})
        if "state" in x or "state" not in e:
            e["state"] = _t(x.get("state", e.get("state", "")), 80)
        if "note" in x or "note" not in e:
            e["note"] = _t(x.get("note", e.get("note", "")), 300)
        e["order"] = int(_n(x.get("order"), 0, 1000, e.get("order", 0)))
        if e["kind"] == "move" and not e["to"] and not e.get("state"):
            raise SystemExit("A move needs a new place or a new state.")
        return e
    return clean


def event_set(d: str, sid: str, data: dict) -> dict:
    """Record that something in the set changes at a shot (it moves, is left in a state, leaves or appears). The set as built is not changed: from the next shot on, the set is *seen* with the event applied."""
    return _list_set(d, sid, "events", "Record an event", data, _clean_event(d), "we", MAX_EVENTS, "event")


def event_remove(d: str, sid: str, eid: str) -> dict:
    return _remove(d, sid, "events", "Remove an event", eid, "event")


def shot_camera(d: str, sid: str, data: dict) -> dict:
    """Say which of the set's cameras a shot uses (or clear it with no camera). Used by the continuity checks."""
    shot, cam = data.get("shot"), data.get("camera") or None
    if shot not in _shot_ids(d):
        raise SystemExit("Choose a shot in this film.")

    def fn(s):
        if cam and not any(c["id"] == cam for c in s["cameras"]):
            raise SystemExit("That camera isn't in the set.")
        s["shots"] = [x for x in s["shots"] if x.get("shot") != shot] + ([{"shot": shot, "camera": cam}] if cam else [])
    _mutate(d, sid, "Choose a shot's camera", fn)
    return get(d, sid)


# ---------------------------------------------------------------- 3D models, groups, ground

MAX_MODELS, MAX_GROUPS = 60, 40


def _lights_for(s: dict) -> tuple[list[dict], float]:
    """The set's lights for the 3D renderer, and how much ambient light fills the shadows (more in the day, less at night, from the environment's time of day)."""
    if isinstance(s.get("ambient"), (int, float)):                                  # an explicit ambient level (the animation renderer sets this per frame)
        return [{k: l[k] for k in ("azimuth", "elevation", "colour", "intensity")} for l in s["lights"]], float(s["ambient"])
    t = (s.get("environment", {}).get("time") or "").lower()
    amb = 0.12 if any(w in t for w in ("night", "dusk", "dark")) else 0.45 if any(w in t for w in ("day", "noon", "morning")) else 0.3
    return [{k: l[k] for k in ("azimuth", "elevation", "colour", "intensity")} for l in s["lights"]], amb


_MODEL_CACHE: dict = {}


def _model_of(d: str, m: dict) -> dict:
    full = V._inside(d, m["file"])
    key = (full, os.path.getmtime(full))
    if key not in _MODEL_CACHE:
        if len(_MODEL_CACHE) > 8:
            _MODEL_CACHE.pop(next(iter(_MODEL_CACHE)))
        _MODEL_CACHE[key] = W3.load_model(full)
    return _MODEL_CACHE[key]


def _instances(d: str, s: dict) -> tuple[list[dict], list[dict]]:
    groups = {g["id"]: g for g in s["groups"]}
    out, bad = [], []
    for m in s["models"]:
        if not m.get("visible", True):
            continue
        try:
            out.append({"id": m["id"], "model": _model_of(d, m), "matrix": W3.world_matrix(m, groups)})
        except (SystemExit, OSError) as e:
            bad.append({"id": m["id"], "why": "its model could not be read" if isinstance(e, OSError) else str(e)})
    return out, bad


def _clean_transform(x: dict, old: dict | None, default_scale: float = 1.0) -> dict:
    t = dict(old or {})
    for k, lo, hi, dflt in (("x", -SPAN, SPAN, 0.0), ("y", -SPAN, SPAN, 0.0), ("z", -SPAN, SPAN, 5.0), ("yaw", -360, 360, 0.0), ("pitch", -360, 360, 0.0), ("roll", -360, 360, 0.0)):
        if k in x or k not in t:
            t[k] = _pos(x, k, lo, hi, t.get(k, dflt))
    if "scale" in x or "scale" not in t:
        t["scale"] = round(_n(x.get("scale"), 0.001, 1000.0, t.get("scale", default_scale)), 4)
    return t


def _world_boxes(s: dict) -> dict[str, list]:
    groups = {g["id"]: g for g in s["groups"]}
    out = {}
    for m in s["models"]:
        if m.get("visible", True) and m.get("summary"):
            try:
                out[m["id"]] = W3.world_bbox(m["summary"]["bbox"], W3.world_matrix(m, groups))
            except SystemExit:
                pass
    return out


def model_add(d: str, sid: str, data: dict) -> dict:
    """Stand a glTF model (.glb, or .gltf with embedded buffers) in the set. The file is copied in (the original is never touched), read once to check it and to measure it, and placed with a position, a
    turn and a scale. What the reader ignores (animations, rigging, extensions) is listed in the model's warnings. The model's front faces the camera at rest; turn it 180 degrees to face away."""
    V._film(d)
    _load(d, sid)
    src = str(data.get("path") or "")
    if not src or not os.path.isfile(src):
        raise SystemExit("Choose a .glb or .gltf model file.")
    if os.path.splitext(src)[1].lower() not in (".glb", ".gltf"):
        raise SystemExit("Choose a .glb or .gltf model file.")
    model = W3.load_model(src)
    info = W3.summary(model)
    holder: dict = {}

    def fn(s):
        if len(s["models"]) >= MAX_MODELS:
            raise SystemExit(f"At most {MAX_MODELS} models in a set.")
        mid = _id("wm")
        rel = f"worldlock/{sid}/models/{mid}{os.path.splitext(src)[1].lower()}"
        full = V._inside(d, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        shutil.copyfile(src, full)
        g = _clean_transform(data, None)
        if "z" not in data:
            g["z"] = 5.0
        nm = _t(data.get("name") or os.path.splitext(os.path.basename(src))[0], 60) or "Model"
        parent = data.get("parent") if any(x["id"] == data.get("parent") for x in s["groups"]) else None
        s["models"].append({"id": mid, "name": nm, "file": rel, **g, "parent": parent, "visible": True, "solid": bool(data.get("solid", True)), "summary": info, "added": time.time()})
        holder["id"] = mid
    _mutate(d, sid, "Add a model", fn)
    return {**get(d, sid), "id": holder["id"]}


def model_set(d: str, sid: str, data: dict) -> dict:
    """Move, turn, scale, rename, hide or regroup a model. Only the fields given change; the file and the id never do."""
    def fn(s):
        m = next((m for m in s["models"] if m["id"] == data.get("id")), None)
        if not m:
            raise SystemExit("That model isn't in the set.")
        m.update(_clean_transform(data, m))
        if "name" in data:
            m["name"] = _t(data["name"], 60) or m["name"]
        for k in ("visible", "solid"):
            if k in data:
                m[k] = bool(data[k])
        if "parent" in data:
            p = data["parent"] or None
            if p and not any(g["id"] == p for g in s["groups"]):
                raise SystemExit("That group isn't in the set.")
            m["parent"] = p
    _mutate(d, sid, "Change a model", fn)
    return get(d, sid)


def model_remove(d: str, sid: str, mid: str) -> dict:
    """Take a model out of the set. It moves to `removed` (the file stays)."""
    def fn(s):
        m = next((m for m in s["models"] if m["id"] == mid), None)
        if not m:
            raise SystemExit("That model isn't in the set.")
        s["models"].remove(m)
        s["removed"].append({**m, "removed_at": time.time(), "model": True})
        s["removed"] = s["removed"][-200:]
    _mutate(d, sid, "Remove a model", fn)
    return get(d, sid)


def group_set(d: str, sid: str, data: dict) -> dict:
    """A group is a transform that models (and other groups) can sit inside: move a group and everything in it moves. A group cannot sit inside itself."""
    holder: dict = {}

    def fn(s):
        gid = data.get("id")
        old = next((g for g in s["groups"] if g["id"] == gid), None) if gid else None
        if gid and not old:
            raise SystemExit("That group isn't in the set.")
        if not old and len(s["groups"]) >= MAX_GROUPS:
            raise SystemExit(f"At most {MAX_GROUPS} groups in a set.")
        g = _clean_transform(data, old)
        g["z"] = g.get("z", 0.0) if ("z" in data or old) else 0.0
        g["name"] = _t(data.get("name", (old or {}).get("name", "")), 60) or "Group"
        p = data.get("parent", (old or {}).get("parent")) or None
        if p and not any(x["id"] == p for x in s["groups"]):
            raise SystemExit("That group isn't in the set.")
        g["parent"] = p
        if old:
            old.update(g)
            g = old
        else:
            g["id"] = _id("wg")
            s["groups"].append(g)
        holder["id"] = g["id"]
        W3.world_matrix(g, {x["id"]: x for x in s["groups"]})                      # refuses a loop before anything is written
    _mutate(d, sid, "Change a group", fn)
    return {**get(d, sid), "id": holder["id"]}


def group_remove(d: str, sid: str, gid: str) -> dict:
    """Remove a group. What was inside it keeps its place in the world (its position is carried out of the group) and is no longer in a group."""
    def fn(s):
        g = next((g for g in s["groups"] if g["id"] == gid), None)
        if not g:
            raise SystemExit("That group isn't in the set.")
        groups = {x["id"]: x for x in s["groups"]}
        for m in s["models"]:
            if m.get("parent") == gid:
                w = W3.world_matrix(m, groups)
                m.update({"x": round(float(w[0, 3]), 3), "y": round(float(w[1, 3]), 3), "z": round(float(w[2, 3]), 3), "parent": None})        # position is kept; a turned group's turn is not carried (see the docs)
        for x in s["groups"]:
            if x.get("parent") == gid:
                x["parent"] = g.get("parent")
        s["groups"].remove(g)
    _mutate(d, sid, "Remove a group", fn)
    return get(d, sid)


def ground_set(d: str, sid: str, data: dict) -> dict:
    """The ground plane: shown or hidden, its height, its two checker colours and how far it reaches. Drawn exactly by the 3D renderer."""
    def fn(s):
        g = dict(s["ground"])
        if "visible" in data:
            g["visible"] = bool(data["visible"])
        if "y" in data:
            g["y"] = round(_n(data["y"], -SPAN, SPAN, g["y"]), 3)
        if "extent" in data:
            g["extent"] = round(_n(data["extent"], 1, SPAN, g["extent"]), 1)
        if isinstance(data.get("colours"), list) and len(data["colours"]) == 2:
            ok = lambda c: isinstance(c, str) and len(c) == 7 and c[0] == "#" and all(h in "0123456789abcdefABCDEF" for h in c[1:])
            if all(ok(c) for c in data["colours"]):
                g["colours"] = list(data["colours"])
        s["ground"] = g
    _mutate(d, sid, "Change the ground", fn)
    return get(d, sid)


def sky_set(d: str, sid: str, data: dict) -> dict:
    """The sky behind the set: a colour at the horizon, a colour overhead, and how thick the distance fog is (0 for none). With no sky set the background is a plain dark colour."""
    def fn(s):
        k = dict(s["sky"])
        ok = lambda c: isinstance(c, str) and len(c) == 7 and c[0] == "#" and all(h in "0123456789abcdefABCDEF" for h in c[1:])
        for key in ("top", "horizon"):
            if key in data:
                if data[key] in (None, ""):
                    k[key] = None
                elif ok(data[key]):
                    k[key] = data[key]
        if "fog" in data:
            k["fog"] = round(_n(data["fog"], 0.0, 1.0, k.get("fog", 0.0)), 4)
        s["sky"] = k
    _mutate(d, sid, "Change the sky", fn)
    return get(d, sid)


def collisions(d: str, sid: str) -> dict:
    """Which solid models overlap each other (their world boxes, by more than 2 cm), which sink below the ground or stand outside the world, and whether a camera is inside a model. Boxes are the corners of a
    turned model, boxed again, so a turned model can report a touch that is only its box: the report says what it measured. Free; changes nothing."""
    V._film(d)
    s = _load(d, sid)
    boxes = _world_boxes(s)
    names = {m["id"]: m["name"] for m in s["models"]}
    issues = []
    ids = [m["id"] for m in s["models"] if m.get("solid", True) and m["id"] in boxes]
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            lo = [max(boxes[a][0][k], boxes[b][0][k]) for k in range(3)]
            hi = [min(boxes[a][1][k], boxes[b][1][k]) for k in range(3)]
            depth = [hi[k] - lo[k] for k in range(3)]
            if all(x > 0.02 for x in depth):
                issues.append({"kind": "overlap", "ids": [a, b], "depth_m": round(min(depth), 3), "text": f"'{names[a]}' and '{names[b]}' overlap by {min(depth):.2f} m (their boxes)."})
    bx, by, bz = s["world"]["bounds"]["x"], s["world"]["bounds"]["y"], s["world"]["bounds"]["z"]
    for mid, bb in boxes.items():
        if s["ground"]["visible"] and bb[0][1] < s["ground"]["y"] - 0.05:
            issues.append({"kind": "below_ground", "ids": [mid], "depth_m": round(s["ground"]["y"] - bb[0][1], 3), "text": f"'{names[mid]}' sinks {s['ground']['y'] - bb[0][1]:.2f} m below the ground."})
        if bb[1][0] < bx[0] or bb[0][0] > bx[1] or bb[1][2] < bz[0] or bb[0][2] > bz[1]:
            issues.append({"kind": "outside", "ids": [mid], "depth_m": 0.0, "text": f"'{names[mid]}' stands outside the set's bounds."})
    for c in s["cameras"]:
        for mid, bb in boxes.items():
            if all(bb[0][k] <= v <= bb[1][k] for k, v in enumerate((c["x"], c["y"], c["z"]))):
                issues.append({"kind": "camera_inside", "ids": [mid, c["id"]], "depth_m": 0.0, "text": f"Camera '{c['name']}' is inside '{names[mid]}'."})
    return {"issues": issues, "ok": not issues, "measured": "world boxes of the models", "checked": {"models": len(boxes), "cameras": len(s["cameras"])}}


def occupancy(d: str, sid: str, data: dict) -> dict:
    """A floor plan of what is taken: the floor is cut into squares (default 0.5 m) and a square is occupied when a solid model's box over it rises more than 0.1 m above the ground. Returns the grid
    (1 = occupied), so a person or a camera can be placed where there is room."""
    V._film(d)
    s = _load(d, sid)
    cell = _n(data.get("cell"), 0.1, 5.0, 0.5)
    b = s["world"]["bounds"]
    nx, nz = int(min(160, math.ceil((b["x"][1] - b["x"][0]) / cell))), int(min(160, math.ceil((b["z"][1] - b["z"][0]) / cell)))
    grid = [[0] * nx for _ in range(nz)]
    gy = s["ground"]["y"] if s["ground"]["visible"] else 0.0
    for mid, bb in _world_boxes(s).items():
        m = next(m for m in s["models"] if m["id"] == mid)
        if not m.get("solid", True) or bb[1][1] - gy < 0.1:
            continue
        for iz in range(nz):
            z0, z1 = b["z"][0] + iz * cell, b["z"][0] + (iz + 1) * cell
            if z1 <= bb[0][2] or z0 >= bb[1][2]:
                continue
            for ix in range(nx):
                x0, x1 = b["x"][0] + ix * cell, b["x"][0] + (ix + 1) * cell
                if x1 > bb[0][0] and x0 < bb[1][0]:
                    grid[iz][ix] = 1
    return {"cell": cell, "origin": [b["x"][0], b["z"][0]], "grid": grid, "occupied": sum(map(sum, grid)), "free": nx * nz - sum(map(sum, grid))}


def views3d(d: str, sid: str, data: dict) -> dict:
    """The same scene from four sides: front, side, reverse and elevated, round a target point (default: the middle of the models, or of the set) at a distance (default: enough to hold everything). Each view is
    a normal render; nothing about the set changes. This is the acceptance view of a 3D set."""
    V._film(d)
    s = _load(d, sid)
    boxes = list(_world_boxes(s).values())
    if boxes:
        if len(boxes) > 6:                                                          # a few far things (a skyline) must not shrink everything else to a speck: frame the nearest 85%
            mid = [sorted((b[0][k] + b[1][k]) / 2 for b in boxes)[len(boxes) // 2] for k in range(3)]
            boxes = sorted(boxes, key=lambda b: sum(((b[0][k] + b[1][k]) / 2 - mid[k]) ** 2 for k in range(3)))[:max(6, int(len(boxes) * 0.85))]
        lo = [min(b[0][k] for b in boxes) for k in range(3)]
        hi = [max(b[1][k] for b in boxes) for k in range(3)]
        center = [(lo[k] + hi[k]) / 2 for k in range(3)]
        radius = max(hi[k] - lo[k] for k in range(3)) / 2 or 1.0
    else:
        b = s["world"]["bounds"]
        center = [(b["x"][0] + b["x"][1]) / 2, 1.0, (b["z"][0] + b["z"][1]) / 2]
        radius = 4.0
    if isinstance(data.get("target"), (list, tuple)) and len(data["target"]) == 3:
        center = [float(_n(v, -SPAN, SPAN, c)) for v, c in zip(data["target"], center)]
    fov = _n(data.get("fov"), 20, 100, 50.0)
    dist = _n(data.get("distance"), 0.5, SPAN, radius * 1.35 / math.tan(math.radians(fov) / 2) * 1.1 + radius)
    size = data.get("size") if isinstance(data.get("size"), (list, tuple)) and len(data["size"]) == 2 else [480, 270]
    out = []
    for name, yaw, elev in (("Front", 0.0, 8.0), ("Side", -90.0, 8.0), ("Reverse", 180.0, 8.0), ("Elevated", 0.0, 55.0)):
        a, e = math.radians(yaw), math.radians(elev)
        cam = {"x": center[0] - math.sin(a) * math.cos(e) * dist, "y": center[1] + math.sin(e) * dist, "z": center[2] - math.cos(a) * math.cos(e) * dist, "name": name, "fov": fov}
        flat = math.hypot(center[0] - cam["x"], center[2] - cam["z"]) or 1.0
        cam["yaw"] = math.degrees(math.atan2(center[0] - cam["x"], center[2] - cam["z"]))
        cam["pitch"] = math.degrees(math.atan2(center[1] - cam["y"], flat))
        r = render(d, sid, {"view": {k: round(v, 3) if isinstance(v, float) else v for k, v in cam.items()}, "size": list(size), "shot": data.get("shot")})
        out.append({"name": name, **r})
    return {"views": out, "target": [round(c, 3) for c in center], "distance": round(dist, 3)}


# ---------------------------------------------------------------- history and versions

def _swap(d: str, sid: str, direction: str) -> dict:
    V._film(d)
    s = _load(d, sid)
    if s.get("locked"):
        raise SystemExit("This set is locked. Unlock it to change it.")
    h = _history(d, sid)
    src, dst = ("undo", "redo") if direction == "undo" else ("redo", "undo")
    if not h[src]:
        raise SystemExit("There is nothing to undo." if direction == "undo" else "There is nothing to redo.")
    entry = h[src].pop()
    h[dst].append({"label": entry["label"], "at": time.time(), "set": copy.deepcopy(s)})
    restored = entry["set"]
    restored["locked"] = False
    restored["updated"] = time.time()
    _write(d, sid, restored, h)
    return get(d, sid)


def undo(d: str, sid: str) -> dict:
    """Go back one change. The state it came from is kept for redo."""
    return _swap(d, sid, "undo")


def redo(d: str, sid: str) -> dict:
    return _swap(d, sid, "redo")


def versions(d: str, sid: str) -> dict:
    V._film(d)
    folder = os.path.join(_dir(d, sid), "versions")
    out = []
    if os.path.isdir(folder):
        for n in sorted(os.listdir(folder)):
            if n.endswith(".json"):
                v = safeio.read_json(os.path.join(folder, n), None)
                if isinstance(v, dict) and isinstance(v.get("set"), dict):
                    out.append({"number": v.get("number"), "name": v.get("name"), "at": v.get("at"), "set_version": v["set"].get("version"), "assets": len(v["set"].get("assets", []))})
    return {"versions": out}


def version_save(d: str, sid: str, name: str) -> dict:
    """Keep the set as it is now under a name, forever (the undo history is limited; a saved version is not). It can be restored later."""
    V._film(d)
    s = _load(d, sid)
    nm = _t(name, 60)
    if not nm:
        raise SystemExit("Give the version a name.")
    folder = os.path.join(_dir(d, sid), "versions")
    os.makedirs(folder, exist_ok=True)
    n = max([v["number"] for v in versions(d, sid)["versions"] if isinstance(v.get("number"), int)] + [0]) + 1
    safeio.write_json(os.path.join(folder, f"v-{n:04d}.json"), {"number": n, "name": nm, "at": time.time(), "set": s}, backup=False)
    return {**get(d, sid), "saved": n}


def version_restore(d: str, sid: str, number) -> dict:
    """Bring a saved version back as the set's current state. The state before is kept for undo, so nothing is lost."""
    V._film(d)
    try:
        n = int(number)
    except (TypeError, ValueError):
        raise SystemExit("Choose a saved version.")
    v = safeio.read_json(os.path.join(_dir(d, sid), "versions", f"v-{n:04d}.json"), None)
    if not isinstance(v, dict) or not _ok(v.get("set")):
        raise SystemExit("That saved version isn't there.")
    snap = v["set"]

    def fn(s):
        keep = {"id": s["id"], "version": s["version"], "locked": False}
        s.clear()
        s.update(copy.deepcopy(snap))
        s.update(keep)
    _mutate(d, sid, f"Restore '{v.get('name')}'", fn)
    return get(d, sid)


# ---------------------------------------------------------------- seeing the set

def _order_for(d: str) -> list[str]:
    try:
        return _shot_ids(d)
    except Exception:
        return []


def _camera_from(s: dict, data: dict) -> dict:
    if data.get("camera"):
        c = next((c for c in s["cameras"] if c["id"] == data["camera"]), None)
        if not c:
            raise SystemExit("That camera isn't in the set.")
        return c
    if isinstance(data.get("view"), dict):
        return _clean_camera(data["view"], None)
    if s["cameras"]:
        return s["cameras"][0]
    raise SystemExit("The set has no camera: save one first.")


def _layers_for(d: str, s: dict, shot: str | None, overrides: dict | None = None) -> tuple[list[dict], list[dict]]:
    assets, chars = WM.state_at(s["assets"], s["characters"], s["events"], _order_for(d), shot)
    ov = overrides if isinstance(overrides, dict) else {}                                      # a planner may stand people and things somewhere else for one view; the set is not changed
    assets = [{**a, **{k: v for k, v in (ov.get("assets") or {}).get(a["id"], {}).items() if k in ("x", "y", "z")}} for a in assets]
    chars = [{**c, **{k: v for k, v in (ov.get("characters") or {}).get(c["id"], {}).items() if k in ("x", "z", "facing")}} for c in chars]
    by_id = {a["id"]: a for a in s["assets"]}
    layers = list(assets)
    for c in chars:
        a = by_id.get(c.get("asset"))
        if a:
            layers.append({**a, "id": f"{c['id']}", "name": c["name"], "x": c["x"], "y": 0.0, "z": c["z"], "kind": "character"})
    return layers, chars


def _draw(d: str, s: dict, cam: dict, size: tuple[int, int], shot: str | None, overrides: dict | None = None) -> tuple[np.ndarray, list[np.ndarray], list[str], list[dict]]:
    layers, _ = _layers_for(d, s, shot, overrides)
    W, H = size
    out = np.zeros((H, W, 3), np.float32)
    out[...] = SKY
    sky = s["sky"]
    fogc = None
    if sky.get("top") and sky.get("horizon"):                                       # a sky: a gradient from the horizon colour up to the top colour, by the direction each pixel looks
        top, hor = (np.array([int(c[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]) for c in (sky["top"], sky["horizon"]))
        f_ = WM.focal_px(W, cam.get("fov", 50.0))
        gx, gy = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
        ray = np.stack([(gx - W / 2) / f_, -(gy - H / 2) / f_, np.ones_like(gx)], axis=-1) @ W3._cam_to_world_dirs(cam)
        el = ray[..., 1] / np.linalg.norm(ray, axis=-1)
        t = np.clip(el * 2.2, 0.0, 1.0)[..., None]
        out = (K.to_srgb(K.to_linear(hor) * (1 - t) + K.to_linear(top) * t)).astype(np.float32)
        fogc = K.to_linear(hor)
    alphas, drawn, skipped = [], [], []
    depth3 = None
    if s["ground"]["visible"] or any(m.get("visible", True) for m in s["models"]):
        color, depth3, hit3 = W3.new_buffers(size)
        lights, ambient = _lights_for(s)
        if s["ground"]["visible"]:
            cols = tuple(tuple(int(c[i:i + 2], 16) / 255.0 for i in (1, 3, 5)) for c in s["ground"]["colours"][:2])
            W3.render_ground(cam, size, float(s["ground"]["y"]), cols, float(s["ground"]["extent"]), lights, ambient, depth3, color, hit3)
        insts, bad = _instances(d, s)
        skipped += bad
        n = W3.render_meshes(insts, cam, size, lights, ambient, depth3, color, hit3)
        if fogc is not None and float(sky.get("fog", 0.0)) > 0:                        # distance fog toward the horizon colour: far things fade into the sky
            k = (1.0 - np.exp(-float(sky["fog"]) * np.where(np.isfinite(depth3), depth3, 0.0)))[..., None]
            color = color * (1 - k) + fogc * k
        out = np.where(hit3[..., None], K.to_srgb(color).astype(np.float32), out)
        alphas.append(hit3.astype(np.float32))
        drawn += [i["id"] for i in insts] + (["ground"] if s["ground"]["visible"] else [])
    for a in sorted(layers, key=lambda a: -(a["z"] - cam["z"])):                      # far to near
        try:
            rgba = K.load_rgba(V._inside(d, a["file"]))
        except (SystemExit, OSError):
            skipped.append({"id": a["id"], "why": "its picture file is missing"})
            continue
        placed = WM.draw_layer(rgba, a, cam, size)
        if placed is None:
            skipped.append({"id": a["id"], "why": "it is behind the camera or outside the view"})
            continue
        if depth3 is not None:                                                         # a layer stands where it stands in depth: a 3D thing nearer than it hides it
            ld = WM.to_camera((a["x"], a["y"] + a["height"] / 2, a["z"]), cam)[2]
            placed = placed.copy()
            placed[..., 3] *= (depth3 >= ld).astype(np.float32)
        out = K.over(placed, out)
        alphas.append(placed[..., 3])
        drawn.append(a["id"])
    return out, alphas, drawn, skipped


def render(d: str, sid: str, data: dict) -> dict:
    """Draw the set from a camera (a saved one, or a `view` given inline), at the size asked, with the set as it stands at the start of `shot` when one is named. Pictures are placed by the projection
    and nothing else: the same camera gives the same picture. The gap (the share of the view with nothing from the set) is measured and warned about; it is never filled."""
    V._film(d)
    s = _load(d, sid)
    cam = _camera_from(s, data)
    sz = data.get("size") if isinstance(data.get("size"), (list, tuple)) and len(data["size"]) == 2 else [960, 540]
    W, H = int(_n(sz[0], 64, MAX_VIEW[0], 960)), int(_n(sz[1], 64, MAX_VIEW[1], 540))
    shot = data.get("shot") or None
    if shot and shot not in _order_for(d):
        raise SystemExit("Choose a shot in this film.")
    out, alphas, drawn, skipped = _draw(d, s, cam, (W, H), shot, data.get("overrides"))
    gap = WM.uncovered(alphas, (W, H), 0.02)
    warnings = []
    if gap > GAP_WARN:
        warnings.append(f"{gap:.0%} of this view shows nothing the set has. The set is made of flat pictures: from here the camera sees past their edges. Move the camera back, or add a picture that covers it.")
    bx, bz = s["world"]["bounds"]["x"], s["world"]["bounds"]["z"]
    if not (bx[0] <= cam["x"] <= bx[1] and bz[0] <= cam["z"] <= bz[1]):
        warnings.append("This camera is outside the set's bounds.")
    rel = f"worldlock/{sid}/views/{_t(cam.get('name', 'view'), 30).replace(' ', '-')}-{int(time.time() * 1000)}.png"
    full = V._inside(d, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB").save(full, "PNG")
    return {"id": sid, "file": rel, "width": W, "height": H, "camera": {k: cam[k] for k in ("x", "y", "z", "yaw", "pitch", "fov")}, "drawn": drawn, "skipped": skipped, "uncovered": round(gap, 4),
            "coverage": round(WM.coverage(alphas, (W, H)), 4), "warnings": warnings, "shot": shot, "set_version": s.get("version", 1)}


def check_move(d: str, sid: str, data: dict) -> dict:
    """Walk a camera from one saved camera (or view) to another in steps and measure the gap at each: does the move go past what the set covers? Reports the worst step."""
    V._film(d)
    s = _load(d, sid)
    a = _camera_from(s, {"camera": data.get("from")} if data.get("from") else {"view": data.get("from_view")})
    b = _camera_from(s, {"camera": data.get("to")} if data.get("to") else {"view": data.get("to_view")})
    steps = int(_n(data.get("steps"), 2, 40, 10))
    shot = data.get("shot") or None
    size = (320, 180)
    rows = []
    for i in range(steps + 1):
        t = i / steps
        cam = {k: a[k] + (b[k] - a[k]) * t for k in ("x", "y", "z", "yaw", "pitch", "fov")}
        _, alphas, _, _ = _draw(d, s, cam, size, shot)
        rows.append({"t": round(t, 3), "uncovered": round(WM.uncovered(alphas, size, 0.02), 4)})
    worst = max(rows, key=lambda r: r["uncovered"])
    ok = worst["uncovered"] <= GAP_WARN
    return {"steps": rows, "worst": worst, "ok": ok, "warning": "" if ok else f"This move shows a gap of {worst['uncovered']:.0%} of the view at {worst['t']:.0%} of the way. The set does not cover where the camera goes: shorten the move or add a picture."}


# ---------------------------------------------------------------- continuity checks

def check(d: str, sid: str) -> dict:
    """Plain facts about a set that may be wrong: pictures whose file is missing or that stand outside the world; cameras outside it; events about things that are not in the set or in shots that no longer exist;
    a pair of characters whose line the camera crosses between two consecutive shots (the 180-degree rule). Free; changes nothing."""
    V._film(d)
    s = _load(d, sid)
    issues = []
    b = s["world"]["bounds"]

    def inside(x, y, z):
        return b["x"][0] <= x <= b["x"][1] and b["y"][0] <= y <= b["y"][1] and b["z"][0] <= z <= b["z"][1]
    for a in s["assets"]:
        if not os.path.isfile(V._inside(d, a["file"])):
            issues.append({"kind": "missing_picture", "id": a["id"], "text": f"The picture for '{a['name']}' is missing from the set's folder."})
        if not inside(a["x"], a["y"], a["z"]):
            issues.append({"kind": "outside", "id": a["id"], "text": f"'{a['name']}' stands outside the set's bounds."})
    for c in s["cameras"]:
        if not (b["x"][0] <= c["x"] <= b["x"][1] and b["z"][0] <= c["z"] <= b["z"][1]):
            issues.append({"kind": "camera_outside", "id": c["id"], "text": f"Camera '{c['name']}' is outside the set's bounds."})
        for a in s["assets"]:
            if abs(a["z"] - c["z"]) < 0.05 and a["x"] - a["width"] / 2 <= c["x"] <= a["x"] + a["width"] / 2 and a["y"] <= c["y"] <= a["y"] + a["height"]:
                issues.append({"kind": "camera_inside", "id": c["id"], "text": f"Camera '{c['name']}' is inside the picture '{a['name']}'."})
    shots = set(_order_for(d))
    ids = {x["id"] for x in s["assets"]} | {x["id"] for x in s["characters"]}
    for e in s["events"]:
        who = e.get("asset") or e.get("character")
        if who not in ids:
            issues.append({"kind": "event_orphan", "id": e["id"], "text": "An event is about something that is no longer in the set."})
        if e.get("shot") not in shots:
            issues.append({"kind": "event_shot", "id": e["id"], "text": f"An event is set at shot {e.get('shot')}, which is not in the film."})
    axis = s.get("axis") or []
    if len(axis) == 2:
        order = _order_for(d)
        cams = {x["shot"]: x["camera"] for x in s["shots"]}
        byc = {c["id"]: c for c in s["cameras"]}
        prev = None
        for sh in order:
            if sh not in cams or cams[sh] not in byc:
                continue
            _, chars = WM.state_at(s["assets"], s["characters"], s["events"], order, sh)
            pair = [next((c for c in chars if c["id"] == i), None) for i in axis]
            if None in pair:
                prev = None
                continue
            side = WM.side_of_axis((pair[0]["x"], pair[0]["z"]), (pair[1]["x"], pair[1]["z"]), (byc[cams[sh]]["x"], byc[cams[sh]]["z"]))
            if prev and side and prev[1] and side != prev[1]:
                issues.append({"kind": "crossed_line", "id": sh, "text": f"Between {prev[0]} and {sh} the camera crosses the line between {pair[0]['name']} and {pair[1]['name']}: left and right will swap on screen."})
            prev = (sh, side)
    return {"issues": issues, "ok": not issues, "checked": {"pictures": len(s["assets"]), "cameras": len(s["cameras"]), "events": len(s["events"])}}


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["list", "create", "get", "meta_set", "asset_add", "asset_set", "asset_remove", "cut_layer", "character_set", "character_remove", "camera_set", "camera_remove", "light_set", "light_remove", "event_set", "event_remove", "shot_camera", "render", "check", "check_move", "lock", "unlock", "undo", "redo", "version_save", "versions", "version_restore", "set_remove",
                                        "model_add", "model_set", "model_remove", "group_set", "group_remove", "ground_set", "collisions", "occupancy", "views3d", "sky_set"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        sid, act = x.get("set", ""), a.action
        table = {
            "list": lambda: list_sets(d), "create": lambda: create(d, x), "get": lambda: get(d, sid), "meta_set": lambda: meta_set(d, sid, x), "asset_add": lambda: asset_add(d, sid, x),
            "asset_set": lambda: asset_set(d, sid, x), "asset_remove": lambda: asset_remove(d, sid, x.get("id", "")), "cut_layer": lambda: cut_layer(d, sid, x),
            "character_set": lambda: character_set(d, sid, x), "character_remove": lambda: character_remove(d, sid, x.get("id", "")), "camera_set": lambda: camera_set(d, sid, x),
            "camera_remove": lambda: camera_remove(d, sid, x.get("id", "")), "light_set": lambda: light_set(d, sid, x), "light_remove": lambda: light_remove(d, sid, x.get("id", "")),
            "event_set": lambda: event_set(d, sid, x), "event_remove": lambda: event_remove(d, sid, x.get("id", "")), "shot_camera": lambda: shot_camera(d, sid, x), "render": lambda: render(d, sid, x),
            "check": lambda: check(d, sid), "check_move": lambda: check_move(d, sid, x), "lock": lambda: lock(d, sid, True), "unlock": lambda: lock(d, sid, False), "undo": lambda: undo(d, sid),
            "redo": lambda: redo(d, sid), "version_save": lambda: version_save(d, sid, x.get("name", "")), "versions": lambda: versions(d, sid), "version_restore": lambda: version_restore(d, sid, x.get("number")),
            "set_remove": lambda: set_remove(d, sid), "model_add": lambda: model_add(d, sid, x), "model_set": lambda: model_set(d, sid, x), "model_remove": lambda: model_remove(d, sid, x.get("id", "")),
            "group_set": lambda: group_set(d, sid, x), "group_remove": lambda: group_remove(d, sid, x.get("id", "")), "ground_set": lambda: ground_set(d, sid, x), "collisions": lambda: collisions(d, sid),
            "occupancy": lambda: occupancy(d, sid, x), "views3d": lambda: views3d(d, sid, x), "sky_set": lambda: sky_set(d, sid, x),
        }
        emit(event="result", data=table[act]())
        return 0
    except SystemExit as e:
        emit(event="error", message=str(e))
        return 1
    except Exception as e:
        emit(event="error", message=__import__("filmcrafter_engine.errtext", fromlist=["plain"]).plain(e))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
