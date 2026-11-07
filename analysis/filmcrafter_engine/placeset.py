"""A set for a place: the guided way into WorldLock. A film's Bible lists its places; this gives each place one set, made in whichever way suits the person:

  * from the place's own **pictures** (2D, nothing to learn): the pictures stand in a new set as a backdrop and layers, with a camera in front;
  * from a **3D model** (.glb or .gltf), or from a **Blender** file (.blend, for people who use Blender): the model is stood in a new set with a ground and a camera looking at it;
  * or **made in Blender**: a blank Blender file is made for the place and opened; when the person saves it, `bring_back` reads it again and the set's model is replaced by the new one (its place in the set is kept).

The link from place to set is a small file (`worldlock/place_sets.json`), so a set itself is the same set as ever and can still be edited in the full set builder. Everything here is free and local; nothing is sent
anywhere. Blender is run in the background with fixed arguments (the paths are list items, never a shell line) and a time limit, and is never installed or changed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

from . import bible
from . import blenderbridge as BB
from . import safeio
from . import vpstudio as V
from . import worldlock as WL

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
PICS = (".png", ".jpg", ".jpeg", ".webp")
MODEL_TIMEOUT = 600

EXPORT_SCRIPT = '''import bpy, sys
out = sys.argv[sys.argv.index("--") + 1]
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_yup=True, use_selection=False, export_apply=True)
'''
BLANK_SCRIPT = '''import bpy, sys
out = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, 0))
bpy.context.object.name = "Floor"
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 3, 0.5))
bpy.context.object.name = "Marker (delete me)"
bpy.ops.wm.save_as_mainfile(filepath=out)
'''


def emit(**kw) -> None:
    V.emit(**kw)


def _index_path(d: str) -> str:
    return V._inside(d, "worldlock/place_sets.json")


def _index(d: str) -> dict:
    x = safeio.read_json(_index_path(d), {}) if os.path.isfile(_index_path(d)) else {}
    return x if isinstance(x, dict) else {}


def _save_index(d: str, x: dict) -> None:
    os.makedirs(os.path.dirname(_index_path(d)), exist_ok=True)
    safeio.write_json(_index_path(d), x, backup=False)


def _place(d: str, pid: str) -> dict:
    for e in bible.load(d)["environments"]:
        if e["id"] == str(pid):
            return e
    raise SystemExit("Choose a place from the film's Bible.")


def _set_exists(d: str, sid: str) -> bool:
    try:
        WL._load(d, sid)
        return True
    except SystemExit:
        return False


def _link(d: str, pid: str) -> dict | None:
    row = _index(d).get(pid)
    if isinstance(row, dict) and row.get("set") and _set_exists(d, row["set"]):
        return row
    return None


def _pictures(d: str, place: dict) -> list[str]:
    out = []
    for m in place.get("media", []):
        p = V._inside(d, m["path"]) if m.get("path") else ""
        if p and os.path.isfile(p) and os.path.splitext(p)[1].lower() in PICS:
            out.append(p)
    return out


def status(d: str, pid: str) -> dict:
    """What this place has: its pictures, its set (if any) and how it was made, whether Blender is here, and the one next thing to do, in plain words."""
    V._film(d)
    pl = _place(d, pid)
    pics = _pictures(d, pl)
    row = _link(d, pid)
    bl = BB.status()
    res = {"place": pl["id"], "name": pl["name"], "pictures": len(pics), "blender": {"found": bl["found"], "version": bl["version"]}, "set": None}
    if row:
        s = WL._load(d, row["set"])
        mode = row.get("mode", "pictures")
        res["set"] = {"id": s["id"], "name": s["name"], "version": s.get("version", 1), "locked": bool(s.get("locked")), "mode": mode, "pictures": len(s["assets"]), "models": len(s["models"]), "cameras": len(s["cameras"]),
                      "blend": row.get("blend"), "blend_saved": os.path.isfile(V._inside(d, row["blend"])) if row.get("blend") else False}
        if mode == "blender" and not s["models"]:
            res["next"] = "Open the file in Blender, build the place, save it, then press Bring it back."
        elif mode == "blender":
            res["next"] = "Changed it in Blender? Save there and press Bring it back. Otherwise the set is ready: plan the shots, or look from the camera."
        else:
            res["next"] = "The set is ready: look from the camera, or plan the shots."
    elif pics:
        res["next"] = "Make a set from this place's pictures: one press, and you can change it later."
    else:
        res["next"] = "Add a picture to this place, or use a 3D model, or make it in Blender."
    return res


def _new_set(d: str, pl: dict, mode: str, **extra) -> str:
    sid = WL.create(d, {"name": pl["name"]})["id"]
    idx = _index(d)
    idx[pl["id"]] = {"set": sid, "mode": mode, "made": time.time(), **extra}
    _save_index(d, idx)
    return sid


def _no_double(d: str, pid: str) -> None:
    if _link(d, pid):
        raise SystemExit("This place already has a set. Open it to change it, or take the link off first (the set is kept).")


def from_pictures(d: str, pid: str) -> dict:
    """The place's pictures become a set: the first one a backdrop 14 m away, the rest narrower layers in front of it at different depths, and a camera at head height. Nothing is invented between them: what the
    pictures do not cover shows as a gap, as in every set."""
    V._film(d)
    pl = _place(d, pid)
    _no_double(d, pid)
    pics = _pictures(d, pl)
    if not pics:
        raise SystemExit("Add a picture to this place first (Cast, Places, Pictures).")
    sid = _new_set(d, pl, "pictures")
    WL.ground_set(d, sid, {"visible": True})
    for i, p in enumerate(pics[:12]):
        if i == 0:
            WL.asset_add(d, sid, {"path": p, "name": "Backdrop", "kind": "layer", "x": 0, "y": 0, "z": 14, "height": 7.2})
        else:
            WL.asset_add(d, sid, {"path": p, "name": f"Picture {i + 1}", "kind": "layer", "x": (-1) ** i * (1.5 + i), "y": 0, "z": 14 - 2.5 * min(i, 4), "height": 3.0})
    return status(d, pid)


def _fit(d: str, sid: str, mid: str, ground: bool = True) -> None:
    """Stand a new model so its nearest face is 4 m ahead of the camera, centred, on the ground; turn the ground on (not for a Blender place, which brings its own floor)."""
    s = WL._load(d, sid)
    m = next(x for x in s["models"] if x["id"] == mid)
    (x0, y0, z0), (x1, y1, z1) = m["summary"]["bbox"]
    sc = m.get("scale", 1.0) or 1.0
    WL.model_set(d, sid, {"id": mid, "x": round(-(x0 + x1) / 2 * sc, 3), "y": round(-y0 * sc, 3), "z": round(4.0 - z0 * sc, 3)})
    if ground:
        WL.ground_set(d, sid, {"visible": True})
    size = max(x1 - x0, y1 - y0, z1 - z0) * sc
    if size > 8:                                                        # a big model (a building, a street): put the camera further back and a bit higher
        s = WL._load(d, sid)
        cam = dict(s["cameras"][0])
        WL.camera_set(d, sid, {"id": cam["id"], "z": round(-size * 0.6, 2), "y": round(min(1.6 + size * 0.05, 8), 2)})
        WL.model_set(d, sid, {"id": mid, "z": round(4.0 - z0 * sc, 3)})


def from_model(d: str, pid: str, path: str) -> dict:
    """A 3D model file (.glb, .gltf) becomes the place's set."""
    V._film(d)
    pl = _place(d, pid)
    _no_double(d, pid)
    src = str(path or "")
    if os.path.splitext(src)[1].lower() not in (".glb", ".gltf") or not os.path.isfile(src):
        raise SystemExit("Choose a .glb or .gltf model file.")
    sid = _new_set(d, pl, "model")
    try:
        r = WL.model_add(d, sid, {"path": src, "name": pl["name"]})
    except SystemExit:
        idx = _index(d)
        idx.pop(pid, None)
        _save_index(d, idx)
        raise
    _fit(d, sid, r["id"])
    return status(d, pid)


def _blender() -> str:
    st = BB.status()
    if not st["found"]:
        raise SystemExit("Blender was not found. It is optional: use a .glb or .gltf file, or the pictures, instead. If it is installed, set its path in ~/.filmcrafter/blender.json.")
    return st["path"]


def _export_glb(d: str, blend: str, out_dir: str) -> str:
    """Ask Blender, in the background, to save a .blend's scene as a .glb. Fixed script, fixed arguments, a time limit."""
    exe = _blender()
    os.makedirs(out_dir, exist_ok=True)
    script = os.path.join(out_dir, "export_glb.py")
    open(script, "w", encoding="utf-8").write(EXPORT_SCRIPT)
    out = os.path.join(out_dir, f"export-{int(time.time())}.glb")
    try:
        r = subprocess.run([exe, "-b", blend, "-P", script, "--", out], capture_output=True, text=True, timeout=MODEL_TIMEOUT, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise SystemExit("Blender took too long to read that file.")
    if r.returncode != 0 or not os.path.isfile(out):
        tail = ((r.stderr or "") + (r.stdout or "")).strip().splitlines()
        raise SystemExit("Blender could not turn that file into a model: " + (tail[-1][:160] if tail else "no message"))
    return out


def from_blend(d: str, pid: str, path: str) -> dict:
    """A Blender file (.blend) becomes the place's set: Blender saves it as a .glb in the background and the model is stood in a new set. The .blend is copied into the film (the original is never touched) so
    it can be brought back again after changes."""
    V._film(d)
    pl = _place(d, pid)
    _no_double(d, pid)
    src = str(path or "")
    if os.path.splitext(src)[1].lower() != ".blend" or not os.path.isfile(src):
        raise SystemExit("Choose a Blender (.blend) file.")
    _blender()
    sid = _new_set(d, pl, "blender")
    base = V._inside(d, f"worldlock/{sid}/blender")
    os.makedirs(base, exist_ok=True)
    import shutil
    blend = os.path.join(base, "place.blend")
    shutil.copyfile(src, blend)
    idx = _index(d)
    idx[pid]["blend"] = f"worldlock/{sid}/blender/place.blend"
    idx[pid]["from_file"] = os.path.basename(src)
    _save_index(d, idx)
    return _bring(d, pid, first=True)


def blender_new(d: str, pid: str) -> dict:
    """Make a blank Blender file for the place (a floor and a marker cube) and open Blender on it, so a place can be built in Blender from nothing. Save in Blender, then press Bring it back."""
    V._film(d)
    pl = _place(d, pid)
    _no_double(d, pid)
    exe = _blender()
    sid = _new_set(d, pl, "blender")
    base = V._inside(d, f"worldlock/{sid}/blender")
    os.makedirs(base, exist_ok=True)
    script = os.path.join(base, "make_blank.py")
    open(script, "w", encoding="utf-8").write(BLANK_SCRIPT)
    blend = os.path.join(base, "place.blend")
    r = subprocess.run([exe, "-b", "--factory-startup", "-P", script, "--", blend], capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
    if r.returncode != 0 or not os.path.isfile(blend):
        idx = _index(d)
        idx.pop(pid, None)
        _save_index(d, idx)
        raise SystemExit("Blender could not make a blank file.")
    idx = _index(d)
    idx[pid]["blend"] = f"worldlock/{sid}/blender/place.blend"
    _save_index(d, idx)
    open_blender(d, pid)
    return status(d, pid)


def open_blender(d: str, pid: str) -> dict:
    """Open the place's Blender file in Blender (a normal window; FilmCrafter does not wait for it)."""
    V._film(d)
    row = _link(d, pid)
    if not row or not row.get("blend"):
        raise SystemExit("This place has no Blender file.")
    blend = V._inside(d, row["blend"])
    if not os.path.isfile(blend):
        raise SystemExit("The place's Blender file is missing.")
    subprocess.Popen([_blender(), blend], creationflags=(0x00000008 | 0x00000200) if os.name == "nt" else 0, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"opened": row["blend"]}


def _bring(d: str, pid: str, first: bool = False) -> dict:
    row = _link(d, pid)
    if not row or not row.get("blend"):
        raise SystemExit("This place has no Blender file.")
    blend = V._inside(d, row["blend"])
    if not os.path.isfile(blend):
        raise SystemExit("The place's Blender file is missing.")
    sid = row["set"]
    glb = _export_glb(d, blend, V._inside(d, f"worldlock/{sid}/blender/exports"))
    s = WL._load(d, sid)
    old = s["models"][0] if s["models"] else None
    r = WL.model_add(d, sid, {"path": glb, "name": _place_name(d, pid), **({k: old[k] for k in ("x", "y", "z", "yaw", "pitch", "roll", "scale")} if old else {})})
    if old:
        WL.model_remove(d, sid, old["id"])
    else:
        _fit(d, sid, r["id"], ground=False)
    idx = _index(d)
    idx[pid]["brought"] = time.time()
    _save_index(d, idx)
    return status(d, pid)


def _place_name(d: str, pid: str) -> str:
    return _place(d, pid)["name"]


def bring_back(d: str, pid: str) -> dict:
    """Read the place's Blender file again and swap the set's model for the new one, keeping where it stood. The old model is removed from the set (the set's undo brings it back)."""
    V._film(d)
    return _bring(d, pid)


def preview(d: str, pid: str, size=(640, 360)) -> dict:
    """The set seen from its first camera, as a picture in the film folder."""
    V._film(d)
    row = _link(d, pid)
    if not row:
        raise SystemExit("This place has no set yet.")
    r = WL.render(d, row["set"], {"camera": WL._load(d, row["set"])["cameras"][0]["id"], "size": list(size)})
    return {"set": row["set"], "file": r["file"], "uncovered": r.get("uncovered", 0), "warnings": r.get("warnings", [])}


def unlink(d: str, pid: str) -> dict:
    """Take the link off. The set stays in the film (nothing is deleted); the place can then be given a set again."""
    V._film(d)
    idx = _index(d)
    idx.pop(str(pid), None)
    _save_index(d, idx)
    return status(d, pid)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["status", "from_pictures", "from_model", "from_blend", "blender_new", "open_blender", "bring_back", "preview", "unlink"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        d, pid = os.path.abspath(a.target), str(x.get("place", ""))
        table = {"status": lambda: status(d, pid), "from_pictures": lambda: from_pictures(d, pid), "from_model": lambda: from_model(d, pid, x.get("path", "")),
                 "from_blend": lambda: from_blend(d, pid, x.get("path", "")), "blender_new": lambda: blender_new(d, pid), "open_blender": lambda: open_blender(d, pid),
                 "bring_back": lambda: bring_back(d, pid), "preview": lambda: preview(d, pid), "unlink": lambda: unlink(d, pid)}
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
