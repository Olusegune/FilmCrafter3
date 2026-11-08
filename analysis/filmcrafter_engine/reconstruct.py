"""AI-assisted set reconstruction: from a place's reference pictures to a draft set a person corrects and approves. Mode C of the virtual-production brief, kept honest about what a picture can tell.

The steps, each one a separate action so nothing happens that the person did not ask for:

  1. `add_reference`   copy one to six pictures of the place in (the originals are never touched)
  2. `estimate`        what asking the AI will cost and exactly what is sent (the pictures, shrunk to 512 px, and the instructions)
  3. `propose`         ask the AI, through the brain chosen in Settings, to list what it can see: each object with where it is in the picture, a rough distance and size, how sure it is and why. This is the only
                       step that sends anything, and it needs `confirmed` (unless the brain is a local model). The answer is a *proposal*: nothing is placed yet.
  4. `item_set`        correct the proposal: rename, move, resize, accept or reject each object; change the assumed lens
  5. `build`           make a **new** set from the accepted objects: as flat pictures cropped from the reference (`layers`) or as grey boxes (`boxes`, volumes with the object's measured size). The draft is labelled
                       as inferred everywhere (each object's note says so) and is never locked.
  6. `approve`         lock the draft: the approved environment. Until then it is a draft.

What this can and cannot know: a picture shows the surfaces facing the camera and nothing behind or beside them, so every depth and size is an estimate from one viewpoint (the reference camera is *assumed* to be at
head height, 1.6 m, with a stated field of view), every object carries the AI's own confidence and reason, hidden sides are never invented (a box is a volume of the visible size, not a model of the object), and extra
reference pictures from other angles are listed as what would improve it. Image-to-3D generators are not offered: none is installed. Existing 3D models in the film's other sets are suggested by name for reuse, never
substituted silently.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import shutil
import struct
import sys
import time
import uuid

import numpy as np
from PIL import Image

from . import bible
from . import placeset as PS
from . import safeio
from . import vpstudio as V
from . import worldlock as WL

MAX_REFS = 6
MAX_ITEMS = 40
ASSUMED_FOV = 55.0
ASSUMED_HEIGHT = 1.6
KINDS = ("structure", "furniture", "prop", "vegetation", "vehicle", "person", "other")
LIMITS = ("From one viewpoint a picture shows only the surfaces facing the camera. Distances and sizes below are estimates, "
          "hidden sides are not known, and nothing here has been measured. Add pictures from other angles to improve it.")

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["scene", "objects", "uncertainty", "missing_views"], "properties": {
    "scene": {"type": "object", "additionalProperties": False, "required": ["kind", "summary", "indoor", "room_width_m", "room_depth_m", "lighting"], "properties": {
        "kind": {"type": "string"}, "summary": {"type": "string"}, "indoor": {"type": "boolean"}, "room_width_m": {"type": "number"}, "room_depth_m": {"type": "number"}, "lighting": {"type": "string"}}},
    "objects": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["name", "kind", "picture", "bbox", "distance_m", "width_m", "height_m", "depth_m", "facing", "on_floor", "confidence", "reason", "hidden"], "properties": {
            "name": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)}, "picture": {"type": "integer"},
            "bbox": {"type": "array", "items": {"type": "number"}}, "distance_m": {"type": "number"}, "width_m": {"type": "number"}, "height_m": {"type": "number"}, "depth_m": {"type": "number"},
            "facing": {"type": "string", "enum": ["toward the camera", "away from the camera", "left", "right", "unknown"]}, "on_floor": {"type": "boolean"},
            "confidence": {"type": "number"}, "reason": {"type": "string"}, "hidden": {"type": "string"}}}},
    "uncertainty": {"type": "array", "items": {"type": "string"}}, "missing_views": {"type": "array", "items": {"type": "string"}}}}

SYSTEM = """You help a film crew turn reference pictures of a place into a rough, editable layout. You are careful and honest.
For each picture you are given, list the main things you can actually SEE (structures such as walls, doors and windows; furniture; props; plants; vehicles; people), up to 30.
For each: a short name; its kind; which picture (0 for the first) and a bounding box in that picture as [x0, y0, x1, y1], each between 0 and 1 from the top left;
an estimate of how far it is from the camera in metres, and its width, height and depth in metres (depth is a guess for what you cannot see: say so in "hidden"); which way it faces;
whether it stands on the floor; your confidence from 0 to 1; and one plain sentence on why you think so.
Assume the camera is at head height (1.6 m) with an ordinary lens. Never invent things you cannot see, never claim to know what is behind or beside an object, and lower your confidence for anything small, partly hidden or far away.
In "uncertainty" list what you could not tell. In "missing_views" list what extra pictures (which angles) would most improve the layout. No people's identities, no guessing at text you cannot read."""


def emit(**kw) -> None:
    V.emit(**kw)


# ---------------------------------------------------------------- storage

def _dir(d: str, pid: str) -> str:
    return V._inside(d, f"worldlock/reconstructions/{pid}")


def _state_path(d: str, pid: str) -> str:
    return os.path.join(_dir(d, pid), "state.json")


def _blank(pid: str) -> dict:
    return {"schema": 1, "place": pid, "references": [], "proposal": None, "assumed": {"fov": ASSUMED_FOV, "camera_height": ASSUMED_HEIGHT}, "built": None, "approved": None, "spend": []}


def _load(d: str, pid: str) -> dict:
    x = safeio.read_json(_state_path(d, pid), None) if os.path.isfile(_state_path(d, pid)) else None
    return x if isinstance(x, dict) and x.get("place") == pid else _blank(pid)


def _save(d: str, pid: str, st: dict) -> None:
    os.makedirs(_dir(d, pid), exist_ok=True)
    safeio.write_json(_state_path(d, pid), st, backup=False)


def _place(d: str, pid: str) -> dict:
    return PS._place(d, pid)


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else max(lo, min(hi, x))


# ---------------------------------------------------------------- geometry (a pinhole camera, assumed)

def draft_geometry(it: dict, fov: float, aspect: float) -> dict:
    """World numbers for one inventory item, from its bounding box and distance with the assumed camera at (0, 1.6, 0) looking along +z. x is across, y the base height, z the distance in front of the camera."""
    d = _num(it.get("distance_m"), 0.5, 80.0, 5.0)
    hh = d * math.tan(math.radians(fov) / 2)                  # half the width of the view at that distance
    vh = hh / aspect                                          # half the height
    x0, y0, x1, y1 = it["bbox"]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w = max(0.05, (x1 - x0) * 2 * hh)
    h = max(0.05, (y1 - y0) * 2 * vh)
    x = (cx - 0.5) * 2 * hh
    top = ASSUMED_HEIGHT + (0.5 - y0) * 2 * vh
    base = ASSUMED_HEIGHT + (0.5 - y1) * 2 * vh
    depth = _num(it.get("depth_m"), 0.02, 40.0, min(w, h))
    seen = {"x": round(x, 3), "y": round(max(-5.0, base), 3), "z": round(d, 3), "width": round(w, 3), "height": round(h, 3), "depth": round(depth, 3)}      # exactly the region of the picture: for a flat picture
    if it.get("on_floor"):
        seen["box_y"], seen["box_height"] = 0.0, round(max(h, top), 3)                    # a volume standing on the floor reaches from the floor up to the top of what is seen
    else:
        seen["box_y"], seen["box_height"] = seen["y"], seen["height"]
    return seen


def _clean_item(x: dict, refs: list[dict], i: int) -> dict | None:
    if not isinstance(x, dict):
        return None
    name = V._t(x.get("name"), 60)
    bb = x.get("bbox")
    if not name or not isinstance(bb, (list, tuple)) or len(bb) != 4:
        return None
    try:
        a, b, c, e = (float(v) for v in bb)
    except (TypeError, ValueError):
        return None
    x0, x1 = sorted((max(0.0, min(1.0, a)), max(0.0, min(1.0, c))))
    y0, y1 = sorted((max(0.0, min(1.0, b)), max(0.0, min(1.0, e))))
    if x1 - x0 < 0.01 or y1 - y0 < 0.01:
        return None
    pic = int(_num(x.get("picture"), 0, max(0, len(refs) - 1), 0))
    return {"id": f"it-{i + 1:02d}", "name": name, "kind": x.get("kind") if x.get("kind") in KINDS else "other", "picture": pic, "bbox": [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)],
            "distance_m": round(_num(x.get("distance_m"), 0.5, 80.0, 5.0), 2), "width_m": round(_num(x.get("width_m"), 0.02, 80.0, 1.0), 2), "height_m": round(_num(x.get("height_m"), 0.02, 80.0, 1.0), 2),
            "depth_m": round(_num(x.get("depth_m"), 0.02, 80.0, 0.5), 2), "facing": V._t(x.get("facing"), 30) or "unknown", "on_floor": bool(x.get("on_floor", True)),
            "confidence": round(_num(x.get("confidence"), 0.0, 1.0, 0.3), 2), "reason": V._t(x.get("reason"), 300), "hidden": V._t(x.get("hidden"), 300), "status": "proposed", "source": "inferred"}


# ---------------------------------------------------------------- steps

def status(d: str, pid: str) -> dict:
    V._film(d)
    pl = _place(d, pid)
    st = _load(d, pid)
    return {"place": pid, "name": pl["name"], "references": st["references"], "proposal": st["proposal"], "assumed": st["assumed"], "built": st["built"], "approved": st["approved"], "spend": st["spend"],
            "place_pictures": len(PS._pictures(d, pl)), "limits": LIMITS, "image_to_3d": "No image-to-3D generator is installed, so none is offered. Boxes are volumes of the visible size, not models of the objects."}


def add_reference(d: str, pid: str, path: str = "", from_place: bool = False) -> dict:
    """Copy a picture in as a reference (or all of the place's own pictures with `from_place`). Pictures are converted to PNG inside the film; the original is never touched."""
    V._film(d)
    pl = _place(d, pid)
    st = _load(d, pid)
    srcs = PS._pictures(d, pl) if from_place else [str(path or "")]
    if not srcs or (not from_place and not os.path.isfile(srcs[0])):
        raise SystemExit("Choose a picture file (PNG, JPG, WebP).")
    added = 0
    for src in srcs:
        if len(st["references"]) >= MAX_REFS:
            raise SystemExit(f"At most {MAX_REFS} reference pictures.")
        if os.path.splitext(src)[1].lower() not in V.EXTS:
            raise SystemExit("Choose a PNG, JPG, WebP, BMP or TIFF picture.")
        if os.path.getsize(src) > V.MAX_FILE:
            raise SystemExit("That file is larger than 120 MB.")
        try:
            with Image.open(src) as im0:
                im0.verify()
            im = Image.open(src).convert("RGB")
        except Exception:
            raise SystemExit("That file could not be read as a picture.")
        if max(im.size) > V.MAX_SIDE:
            raise SystemExit(f"That picture is larger than {V.MAX_SIDE} pixels on a side.")
        rid = "rf-" + uuid.uuid4().hex[:6]
        rel = f"worldlock/reconstructions/{pid}/refs/{rid}.png"
        full = V._inside(d, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        im.save(full, "PNG")
        st["references"].append({"id": rid, "file": rel, "name": V._t(os.path.splitext(os.path.basename(src))[0], 60), "width": im.width, "height": im.height})
        added += 1
    st["proposal"] = None if added else st["proposal"]                    # new pictures: an earlier proposal no longer covers them
    st["built"] = None if added and not st.get("approved") else st["built"]
    _save(d, pid, st)
    return status(d, pid)


def remove_reference(d: str, pid: str, rid: str) -> dict:
    V._film(d)
    st = _load(d, pid)
    keep = [r for r in st["references"] if r["id"] != rid]
    if len(keep) == len(st["references"]):
        raise SystemExit("That reference isn't here.")
    st["references"] = keep
    st["proposal"] = None
    _save(d, pid, st)                                                      # the picture file stays in the folder (nothing is deleted)
    return status(d, pid)


def _jpeg(path: str, max_w: int = 512) -> str:
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(max_w * im.height / im.width)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def estimate(d: str, pid: str) -> dict:
    """What asking the AI costs and what it sends. A rough figure: the provider's own price applies."""
    V._film(d)
    st = _load(d, pid)
    if not st["references"]:
        raise SystemExit("Add at least one reference picture first.")
    from .acting import _estimate
    chars = len(SYSTEM) + 400 * 4 * len(st["references"])                  # each shrunk picture counts as about 400 tokens
    e = _estimate(chars, 1, 2500)
    return {**e, "pictures": len(st["references"]), "sends": f"{len(st['references'])} picture{'s' if len(st['references']) != 1 else ''}, shrunk to 512 pixels wide, and the instructions. Nothing else from your film."}


def propose(d: str, pid: str, confirmed: bool = False) -> dict:
    """Ask the AI to list what it can see. Sends the reference pictures; needs `confirmed` unless the brain is a local model. The result is a proposal only: nothing is placed."""
    V._film(d)
    st = _load(d, pid)
    if not st["references"]:
        raise SystemExit("Add at least one reference picture first.")
    from . import llm
    e = estimate(d, pid)
    if not e["local"] and not confirmed:
        raise SystemExit(f"This sends {e['sends']} to your AI provider and costs about ${e['usd']:.3f}. Confirm to go ahead.")
    from .director import DEFAULT_MODEL, openai_error, resolve_model
    cl = llm.client()
    model = resolve_model(cl, DEFAULT_MODEL, vision=True)
    content = [{"type": "input_text", "text": f"There are {len(st['references'])} picture(s) of one place. Picture 0 is the first."}]
    for i, r in enumerate(st["references"]):
        content += [{"type": "input_text", "text": f"Picture {i}:"}, {"type": "input_image", "image_url": f"data:image/jpeg;base64,{_jpeg(V._inside(d, r['file']))}"}]
    try:
        r = cl.responses.create(model=model, input=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}], text={"format": {"type": "json_schema", "name": "set_inventory", "schema": SCHEMA, "strict": True}})
        out = json.loads(r.output_text)
    except Exception as ex:
        raise SystemExit(openai_error(ex))
    if not isinstance(out, dict):
        raise SystemExit("The AI's answer could not be read. Nothing was changed.")
    items = [c for i, x in enumerate((out.get("objects") or [])[:MAX_ITEMS]) if (c := _clean_item(x, st["references"], i))]
    sc = out.get("scene") if isinstance(out.get("scene"), dict) else {}
    st["proposal"] = {"at": time.time(), "model": str(model), "scene": {"kind": V._t(sc.get("kind"), 60), "summary": V._t(sc.get("summary"), 400), "indoor": bool(sc.get("indoor", True)),
                      "room_width_m": round(_num(sc.get("room_width_m"), 0, 500, 0), 1), "room_depth_m": round(_num(sc.get("room_depth_m"), 0, 500, 0), 1), "lighting": V._t(sc.get("lighting"), 200)},
                      "items": items, "uncertainty": [V._t(u, 200) for u in (out.get("uncertainty") or [])[:10] if isinstance(u, str)], "missing_views": [V._t(u, 200) for u in (out.get("missing_views") or [])[:10] if isinstance(u, str)],
                      "reuse": _reuse(d, items)}
    st["spend"].append({"at": time.time(), "usd_estimated": e["usd"], "model": str(model), "pictures": len(st["references"]), "note": "estimated, not billed here"})
    st["built"] = None if not st.get("approved") else st["built"]
    _save(d, pid, st)
    return status(d, pid)


def _reuse(d: str, items: list[dict]) -> list[dict]:
    """Models already in the film's other sets whose names match an inventory item: offered for reuse, never swapped in."""
    out = []
    names = {}
    for s in WL.list_sets(d)["sets"]:
        try:
            for m in WL._load(d, s["id"])["models"]:
                names.setdefault(m["name"].lower(), (s["id"], m["id"], m["name"]))
        except SystemExit:
            continue
    for it in items:
        for key, (sid, mid, nm) in names.items():
            if key and (key in it["name"].lower() or it["name"].lower() in key):
                out.append({"item": it["id"], "set": sid, "model": mid, "name": nm})
                break
    return out


def item_set(d: str, pid: str, item: str, patch: dict) -> dict:
    """Correct one inventory item: its name, kind, distance, size, position in the picture (bbox), whether it stands on the floor, and `status` (proposed, accepted, rejected). Or `assumed.fov`."""
    V._film(d)
    st = _load(d, pid)
    if isinstance(patch.get("assumed"), dict) and "fov" in patch["assumed"]:
        st["assumed"]["fov"] = round(_num(patch["assumed"]["fov"], 20, 110, ASSUMED_FOV), 1)
    if item:
        p = (st.get("proposal") or {})
        it = next((x for x in p.get("items", []) if x["id"] == item), None)
        if not it:
            raise SystemExit("That item isn't in the proposal.")
        if "name" in patch:
            it["name"] = V._t(patch["name"], 60) or it["name"]
        if patch.get("kind") in KINDS:
            it["kind"] = patch["kind"]
        for k, lo, hi in (("distance_m", 0.5, 80.0), ("width_m", 0.02, 80.0), ("height_m", 0.02, 80.0), ("depth_m", 0.02, 80.0)):
            if k in patch:
                it[k] = round(_num(patch[k], lo, hi, it[k]), 2)
        if "on_floor" in patch:
            it["on_floor"] = bool(patch["on_floor"])
        if isinstance(patch.get("bbox"), list) and len(patch["bbox"]) == 4:
            c = _clean_item({**it, "bbox": patch["bbox"]}, st["references"], 0)
            if c:
                it["bbox"] = c["bbox"]
        if patch.get("status") in ("proposed", "accepted", "rejected"):
            it["status"] = patch["status"]
        it["edited"] = True
        st["built"] = None if not st.get("approved") else st["built"]
    _save(d, pid, st)
    return status(d, pid)


def accept_all(d: str, pid: str, min_confidence: float = 0.0) -> dict:
    V._film(d)
    st = _load(d, pid)
    for it in (st.get("proposal") or {}).get("items", []):
        if it["status"] == "proposed" and it["confidence"] >= min_confidence:
            it["status"] = "accepted"
    _save(d, pid, st)
    return status(d, pid)


# ---------------------------------------------------------------- the draft set

def _box_glb(w: float, h: float, dp: float, rgb: tuple[float, float, float]) -> bytes:
    """A box with its base centred on the origin, as a binary glTF 2.0 with one material."""
    hx, hz = w / 2, dp / 2
    faces = [((0, 0, 1), [(-hx, 0, hz), (hx, 0, hz), (hx, h, hz), (-hx, h, hz)]), ((0, 0, -1), [(hx, 0, -hz), (-hx, 0, -hz), (-hx, h, -hz), (hx, h, -hz)]),
             ((1, 0, 0), [(hx, 0, hz), (hx, 0, -hz), (hx, h, -hz), (hx, h, hz)]), ((-1, 0, 0), [(-hx, 0, -hz), (-hx, 0, hz), (-hx, h, hz), (-hx, h, -hz)]),
             ((0, 1, 0), [(-hx, h, hz), (hx, h, hz), (hx, h, -hz), (-hx, h, -hz)]), ((0, -1, 0), [(-hx, 0, -hz), (hx, 0, -hz), (hx, 0, hz), (-hx, 0, hz)])]
    pos, nrm, idx = [], [], []
    for n, quad in faces:
        b = len(pos)
        pos += quad
        nrm += [n] * 4
        idx += [b, b + 1, b + 2, b, b + 2, b + 3]
    P = np.array(pos, dtype="<f4")
    N = np.array(nrm, dtype="<f4")
    I = np.array(idx, dtype="<u2")
    blob = P.tobytes() + N.tobytes() + I.tobytes()
    blob += b"\x00" * (-len(blob) % 4)
    j = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}], "buffers": [{"byteLength": len(blob)}],
         "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": P.nbytes}, {"buffer": 0, "byteOffset": P.nbytes, "byteLength": N.nbytes}, {"buffer": 0, "byteOffset": P.nbytes + N.nbytes, "byteLength": I.nbytes}],
         "accessors": [{"bufferView": 0, "componentType": 5126, "count": 24, "type": "VEC3", "min": P.min(axis=0).tolist(), "max": P.max(axis=0).tolist()}, {"bufferView": 1, "componentType": 5126, "count": 24, "type": "VEC3"},
                       {"bufferView": 2, "componentType": 5123, "count": 36, "type": "SCALAR"}],
         "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [*rgb, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9}}],
         "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}]}]}
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    return struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(blob)) + struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(blob), b"BIN\x00") + blob


def _crop(d: str, st: dict, it: dict, grow: float = 0.02) -> tuple[Image.Image, tuple[float, float, float]]:
    ref = st["references"][min(it["picture"], len(st["references"]) - 1)]
    im = Image.open(V._inside(d, ref["file"])).convert("RGB")
    x0, y0, x1, y1 = it["bbox"]
    box = (int(max(0, x0 - grow) * im.width), int(max(0, y0 - grow) * im.height), int(min(1, x1 + grow) * im.width), int(min(1, y1 + grow) * im.height))
    c = im.crop(box)
    avg = np.asarray(c.resize((8, 8)), dtype=np.float32).reshape(-1, 3).mean(axis=0) / 255.0
    return c, (float(avg[0]), float(avg[1]), float(avg[2]))


def build(d: str, pid: str, mode: str = "layers") -> dict:
    """Make a new, unlocked draft set from the accepted items: `layers` (flat pictures cropped from the reference, rectangular, with their background) or `boxes` (grey-coloured volumes of the visible size).
    The place is linked to the draft. A first build with nothing accepted is refused."""
    V._film(d)
    pl = _place(d, pid)
    st = _load(d, pid)
    items = [i for i in ((st.get("proposal") or {}).get("items") or []) if i["status"] == "accepted"]
    if not items:
        raise SystemExit("Accept at least one object first.")
    if mode not in ("layers", "boxes"):
        raise SystemExit("Choose layers or boxes.")
    if st.get("approved"):
        raise SystemExit("This reconstruction is approved and its set is locked. Unlock the set to build again.")
    link = PS._link(d, pid)
    if link and link.get("mode") != "reconstructed":
        raise SystemExit("This place already has a set. Take the link off first (the set is kept).")
    first = Image.open(V._inside(d, st["references"][0]["file"]))
    aspect = first.width / first.height
    fov = st["assumed"]["fov"]
    sid = WL.create(d, {"name": f"{pl['name']} (draft from a picture)", "world": {"bounds": {"x": [-60, 60], "y": [-5, 40], "z": [-5, 120]}}})["id"]
    base = V._inside(d, f"worldlock/reconstructions/{pid}/crops")
    os.makedirs(base, exist_ok=True)
    WL.meta_set(d, sid, {"environment": {"time": "", "weather": "", "atmosphere": "draft inferred from a reference picture"}})
    WL.camera_set(d, sid, {"name": "Reference camera", "x": 0, "y": ASSUMED_HEIGHT, "z": 0, "yaw": 0, "pitch": 0, "fov": fov, "note": "Assumed: the reference picture's camera is at head height with this lens."})
    WL.ground_set(d, sid, {"visible": True})
    made = []
    for it in items:
        g = draft_geometry(it, fov, aspect)
        note = f"Inferred from a reference picture; confidence {it['confidence']:.2f}. {it['reason']} Hidden sides are not known."[:300]
        crop, rgb = _crop(d, st, it)
        if mode == "layers" or (it["kind"] == "structure" and it["bbox"][2] - it["bbox"][0] >= 0.6):             # a wide wall or backdrop stays a flat picture in either mode
            cp = os.path.join(base, f"{it['id']}.png")
            crop.save(cp)
            WL.asset_add(d, sid, {"path": cp, "name": it["name"], "kind": "layer", "x": g["x"], "y": g["y"], "z": g["z"], "width": g["width"], "height": g["height"], "note": note, "tags": ["inferred", it["kind"]]})
        else:
            gp = os.path.join(base, f"{it['id']}.glb")
            open(gp, "wb").write(_box_glb(g["width"], g["box_height"], g["depth"], rgb))
            WL.model_add(d, sid, {"path": gp, "name": it["name"], "x": g["x"], "y": g["box_y"], "z": round(g["z"] + g["depth"] / 2, 3)})
        made.append({"item": it["id"], "x": g["x"], "y": g["y"], "z": g["z"], "width": g["width"], "height": g["height"]})
    idx = PS._index(d)
    idx[pid] = {"set": sid, "mode": "reconstructed", "made": time.time(), "build": mode}
    PS._save_index(d, idx)
    st["built"] = {"set": sid, "mode": mode, "at": time.time(), "items": made}
    _save(d, pid, st)
    return status(d, pid)


def approve(d: str, pid: str) -> dict:
    """Approve the draft: lock its set. It is then the approved environment of the place. Unlock the set (in the set builder) to change it."""
    V._film(d)
    st = _load(d, pid)
    if not st.get("built"):
        raise SystemExit("Build the draft first.")
    WL.lock(d, st["built"]["set"], True)
    st["approved"] = time.time()
    _save(d, pid, st)
    return status(d, pid)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["status", "add_reference", "remove_reference", "estimate", "propose", "item_set", "accept_all", "build", "approve"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        d, pid = os.path.abspath(a.target), str(x.get("place", ""))
        table = {"status": lambda: status(d, pid), "add_reference": lambda: add_reference(d, pid, x.get("path", ""), bool(x.get("from_place"))), "remove_reference": lambda: remove_reference(d, pid, str(x.get("id", ""))),
                 "estimate": lambda: estimate(d, pid), "propose": lambda: propose(d, pid, bool(x.get("confirmed"))), "item_set": lambda: item_set(d, pid, str(x.get("item", "")), x.get("patch") if isinstance(x.get("patch"), dict) else {}),
                 "accept_all": lambda: accept_all(d, pid, float(x.get("min_confidence", 0.0))), "build": lambda: build(d, pid, str(x.get("mode", "layers"))), "approve": lambda: approve(d, pid)}
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
