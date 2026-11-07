"""An optional bridge to Blender, for people who have it. FilmCrafter does not need Blender: its own 3D renderer (`world3d`) draws sets without it. The bridge only does what a person would otherwise do by
hand: turn a WorldLock set into a Blender scene (the models placed, the ground, the lights, the cameras) and, if asked, render reference frames with Blender's own renderer.

  * `status` finds Blender (a path saved in `~/.filmcrafter/blender.json`, the `BLENDER_PATH` variable, the PATH, or the usual Windows install folders) and asks it for its version. Nothing is downloaded or installed.
  * `export` writes `worldlock/<set>/blender/build_scene.py` (a script made only from the set's numbers and file names) and `scene.json`. Run on its own, it needs nothing but Blender: `blender -b -P build_scene.py`.
  * `run` runs that script in Blender in the background (fixed arguments, a time limit, no user text in the command), which saves `scene.blend` and renders one reference frame per saved camera.

Status of this bridge, stated plainly: the script and the detection are tested without Blender (the script is parsed and its numbers checked; detection is tested against a stand-in program). **It has not been
run in a real Blender**, because none is installed on the machine it was built on. Treat `run` as experimental. Blender's licence (GPL) means nothing of it is bundled or redistributed here.

Coordinates: WorldLock is left-handed (X right, Y up, Z into the set); Blender is right-handed with Z up. The script converts: a set point (x, y, z) becomes Blender (x, z, y), and a set yaw turns about Blender's
Z axis the opposite way. glTF models are imported by Blender's own importer; the set mirrors glTF's Z on reading, so the script applies the same mirror (scale Z by -1 on the object) to keep the model the right way round.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys

from . import safeio
from . import vpstudio as V
from . import worldlock as WL

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CONFIG = os.path.join(os.path.expanduser("~"), ".filmcrafter", "blender.json")


def emit(**kw) -> None:
    V.emit(**kw)


def _candidates() -> list[str]:
    out = []
    cfg = safeio.read_json(CONFIG, None) if os.path.isfile(CONFIG) else None
    if isinstance(cfg, dict) and isinstance(cfg.get("path"), str):
        out.append(cfg["path"])
    if os.environ.get("BLENDER_PATH"):
        out.append(os.environ["BLENDER_PATH"])
    w = shutil.which("blender")
    if w:
        out.append(w)
    if os.name == "nt":
        for pat in ("C:/Program Files/Blender Foundation/Blender */blender.exe", "C:/Program Files (x86)/Blender Foundation/Blender */blender.exe"):
            out += sorted(glob.glob(pat), reverse=True)
    return [p for p in dict.fromkeys(out) if p and os.path.isfile(p)]


def status() -> dict:
    """Is Blender here, and which version? Looks only; runs `blender --version` with a short time limit."""
    for p in _candidates():
        try:
            r = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.search(r"Blender\s+(\d+(?:\.\d+)+)", r.stdout or "")
        if m:
            return {"found": True, "path": p, "version": m.group(1), "note": "Found. The bridge has not been run in a real Blender by its authors: treat it as experimental."}
    return {"found": False, "path": "", "version": "", "note": "Blender was not found. It is optional: FilmCrafter draws 3D sets without it. If you have it, set its location in ~/.filmcrafter/blender.json as {\"path\": \"...\\\\blender.exe\"}."}


def _bl(x: float, y: float, z: float) -> tuple[float, float, float]:
    return (round(x, 4), round(z, 4), round(y, 4))


def build_script(s: dict, files: dict[str, str]) -> str:
    """A Blender Python script made from the set's numbers and the models' file names. Every value goes through `repr` of a number or `json.dumps` of a string, so nothing a person typed can become code."""
    g = {x["id"]: x for x in s["groups"]}
    from . import world3d as W3
    objs = []
    for m in s["models"]:
        if not m.get("visible", True) or m["id"] not in files:
            continue
        w = W3.world_matrix(m, g)
        x, y, z = _bl(float(w[0, 3]), float(w[1, 3]), float(w[2, 3]))
        sx = float(math.sqrt(sum(w[i, 0] ** 2 for i in range(3))))
        yaw = math.degrees(math.atan2(w[0, 2], w[2, 2]))
        objs.append({"id": m["id"], "name": m["name"], "file": files[m["id"]], "loc": [x, y, z], "yaw_z": round(-yaw, 3), "scale": round(sx, 5)})
    cams = [{"name": c["name"], "loc": list(_bl(c["x"], c["y"], c["z"])), "yaw": c["yaw"], "pitch": c["pitch"], "fov": c["fov"], "aspect": c.get("aspect", "16:9")} for c in s["cameras"]]
    lights = [{"name": l["name"], "azimuth": l["azimuth"], "elevation": l["elevation"], "colour": l["colour"], "intensity": l["intensity"]} for l in s["lights"]]
    data = {"set": s["name"], "objects": objs, "cameras": cams, "lights": lights, "ground": s["ground"]}
    return '''# Made by FilmCrafter from a WorldLock set. Run with:  blender -b -P build_scene.py
# It builds the scene from the numbers below and saves scene.blend next to this file, then renders one frame per camera into renders/.
import json, math, os, sys
import bpy

DATA = json.loads(%s)
HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = "--no-render" not in sys.argv

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
_engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
scene.render.engine = next((e for e in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE") if e in _engines), "BLENDER_WORKBENCH")   # the name changed between Blender versions

if DATA["ground"].get("visible"):
    bpy.ops.mesh.primitive_plane_add(size=float(DATA["ground"].get("extent", 60)) * 2, location=(0, 0, float(DATA["ground"].get("y", 0))))
    bpy.context.object.name = "Ground"

for o in DATA["objects"]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(HERE, o["file"]))
    new = [x for x in bpy.data.objects if x not in before]
    root = bpy.data.objects.new(o["name"], None)
    bpy.context.collection.objects.link(root)
    for x in new:
        if x.parent is None:
            x.parent = root
    root.location = o["loc"]
    root.rotation_euler[2] = math.radians(o["yaw_z"])
    root.scale = (o["scale"], -o["scale"], o["scale"])   # WorldLock mirrors glTF's Z (Blender's Y here) so a model faces the camera at rest

for l in DATA["lights"]:
    sun = bpy.data.lights.new(l["name"], type="SUN")
    sun.energy = 3.0 * float(l["intensity"])
    h = l["colour"].lstrip("#")
    sun.color = tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    ob = bpy.data.objects.new(l["name"], sun)
    bpy.context.collection.objects.link(ob)
    ob.rotation_euler = (math.radians(90 - float(l["elevation"])), 0, math.radians(-float(l["azimuth"]) + 180))

cams = []
for c in DATA["cameras"]:
    cam = bpy.data.cameras.new(c["name"])
    cam.angle_x = math.radians(float(c["fov"]))
    ob = bpy.data.objects.new(c["name"], cam)
    bpy.context.collection.objects.link(ob)
    ob.location = c["loc"]
    ob.rotation_euler = (math.radians(90 + float(c["pitch"])), 0, math.radians(-float(c["yaw"])))
    cams.append(ob)

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "scene.blend"))
if RENDER and cams:
    os.makedirs(os.path.join(HERE, "renders"), exist_ok=True)
    scene.render.resolution_x, scene.render.resolution_y = 960, 540
    for ob in cams:
        scene.camera = ob
        scene.render.filepath = os.path.join(HERE, "renders", ob.name.replace(" ", "_") + ".png")
        bpy.ops.render.render(write_still=True)
''' % repr(json.dumps(data))


def export(d: str, sid: str, data: dict) -> dict:
    """Write the Blender script and scene data for a set, and copy nothing: the script reads the models from the set's own folder. With `run` true and Blender present, run it."""
    V._film(d)
    s = WL._load(d, sid)
    base = V._inside(d, f"worldlock/{sid}/blender")
    os.makedirs(base, exist_ok=True)
    files = {m["id"]: os.path.relpath(V._inside(d, m["file"]), base).replace("\\", "/") for m in s["models"]}
    script = build_script(s, files)
    open(os.path.join(base, "build_scene.py"), "w", encoding="utf-8").write(script)
    safeio.write_json(os.path.join(base, "scene.json"), {"set": s["name"], "version": s.get("version", 1), "models": len(s["models"]), "cameras": len(s["cameras"])}, backup=False)
    res = {"folder": base, "relative": f"worldlock/{sid}/blender", "script": "build_scene.py", "models": len(s["models"]), "cameras": len(s["cameras"]), "ran": False, "rendered": []}
    if data.get("run"):
        st = status()
        if not st["found"]:
            raise SystemExit("Blender was not found. The script was written; run it with Blender yourself: blender -b -P build_scene.py")
        r = subprocess.run([st["path"], "-b", "-P", os.path.join(base, "build_scene.py")] + ([] if data.get("render", True) else ["--", "--no-render"]), capture_output=True, text=True, timeout=1200, cwd=base, creationflags=NO_WINDOW)
        res["ran"] = True
        res["returncode"] = r.returncode
        res["tail"] = (r.stdout or "")[-400:] + (r.stderr or "")[-400:]
        rd = os.path.join(base, "renders")
        res["rendered"] = sorted(os.listdir(rd)) if os.path.isdir(rd) else []
        if r.returncode != 0 or not os.path.isfile(os.path.join(base, "scene.blend")):
            raise SystemExit("Blender ran but did not make the scene: " + (res["tail"].strip().splitlines() or ["no output"])[-1][:200])
    return res


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["status", "export"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        res = status() if a.action == "status" else export(os.path.abspath(a.target), x.get("set", ""), x)
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
