"""An optional bridge to Blender, for people who have it. FilmCrafter does not need Blender: its own 3D renderer (`world3d`) draws sets without it. The bridge only does what a person would otherwise do by
hand: turn a WorldLock set into a Blender scene (the models placed, the ground, the lights, the cameras) and, if asked, render reference frames with Blender's own renderer.

  * `status` finds Blender (a path saved in `~/.filmcrafter/blender.json`, the `BLENDER_PATH` variable, the PATH, or the usual Windows install folders) and asks it for its version. Nothing is downloaded or installed.
  * `export` writes `worldlock/<set>/blender/build_scene.py` (a script made only from the set's numbers and file names) and `scene.json`. Run on its own, it needs nothing but Blender: `blender -b -P build_scene.py`.
  * `run` runs that script in Blender in the background (fixed arguments, a time limit, no user text in the command), which saves `scene.blend` and renders one reference frame per saved camera.

Status: tried for real in Blender 5.2.2 (the set is rebuilt and rendered; ground, sky and lights are not yet carried over).
Blender's licence (GPL) means nothing of it is bundled or redistributed here.

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


def scene_data(s: dict, files: dict[str, str], hidden: bool = False, cam: dict | None = None) -> dict:
    """The numbers a Blender scene is made from: models (place, turn, size), cameras, lights, ground, sky and the ambient level. `hidden` keeps invisible models in the list, flagged (an animation shows and hides them);
    `cam` replaces the cameras with one (the animation's camera at this moment)."""
    g = {x["id"]: x for x in s["groups"]}
    from . import world3d as W3
    objs = []
    for m in s["models"]:
        if (not m.get("visible", True) and not hidden) or m["id"] not in files:
            continue
        w = W3.world_matrix(m, g)
        x, y, z = _bl(float(w[0, 3]), float(w[1, 3]), float(w[2, 3]))
        sx = float(math.sqrt(sum(w[i, 0] ** 2 for i in range(3))))
        yaw = math.degrees(math.atan2(w[0, 2], w[2, 2]))
        objs.append({"id": m["id"], "name": m["name"], "file": files[m["id"]], "loc": [x, y, z], "yaw_z": round(-yaw, 3), "scale": round(sx, 5), "visible": bool(m.get("visible", True))})
    cams = [{"name": c["name"], "loc": list(_bl(c["x"], c["y"], c["z"])), "yaw": c["yaw"], "pitch": c["pitch"], "fov": c["fov"], "aspect": c.get("aspect", "16:9")} for c in ([cam] if cam else s["cameras"])]
    lights = [{"name": l["name"], "azimuth": l["azimuth"], "elevation": l["elevation"], "colour": l["colour"], "intensity": l["intensity"]} for l in s["lights"]]
    _, ambient = WL._lights_for(s)
    sky = s.get("sky") or {}
    return {"set": s["name"], "objects": objs, "cameras": cams, "lights": lights, "ground": s["ground"], "ambient": float(ambient), "sky": {"top": sky.get("top") or "#6f8fc4", "horizon": sky.get("horizon") or "#d9c9a8"}}


def build_script(s: dict, files: dict[str, str]) -> str:
    """A Blender Python script made from the set's numbers and the models' file names. Every value goes through `repr` of a number or `json.dumps` of a string, so nothing a person typed can become code."""
    data = scene_data(s, files)
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

def rgb(h):
    h = h.lstrip("#")
    return tuple((int(h[i:i + 2], 16) / 255.0) ** 2.2 for i in (0, 2, 4)) + (1.0,)   # the set's colours are display colours; Blender wants linear ones

scene.view_settings.view_transform = "Standard"        # no film curve: colours stay as the set states them

# the sky: a gradient from the horizon colour to the colour overhead, lighting the scene as the set's ambient level says
world = bpy.data.worlds.new("Sky")
world.use_nodes = True
nt = world.node_tree
nt.nodes.clear()
tc = nt.nodes.new("ShaderNodeTexCoord")
sep = nt.nodes.new("ShaderNodeSeparateXYZ")
ramp = nt.nodes.new("ShaderNodeValToRGB")
bg = nt.nodes.new("ShaderNodeBackground")
out = nt.nodes.new("ShaderNodeOutputWorld")
nt.links.new(tc.outputs["Generated"], sep.inputs[0])
nt.links.new(sep.outputs["Z"], ramp.inputs[0])
nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
ramp.color_ramp.elements[0].position = 0.5
ramp.color_ramp.elements[0].color = rgb(DATA["sky"]["horizon"])
ramp.color_ramp.elements[1].position = 1.0
ramp.color_ramp.elements[1].color = rgb(DATA["sky"]["top"])
bg.inputs["Strength"].default_value = max(0.05, float(DATA["ambient"]) * 3.0)
scene.world = world

if DATA["ground"].get("visible"):
    bpy.ops.mesh.primitive_plane_add(size=float(DATA["ground"].get("extent", 60)) * 2, location=(0, 0, float(DATA["ground"].get("y", 0))))
    bpy.context.object.name = "Ground"
    mat = bpy.data.materials.new("Ground")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = rgb((DATA["ground"].get("colours") or ["#c9c4b8"])[0])
    mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.95
    bpy.context.object.data.materials.append(mat)

ROOTS, SUNS = {}, []
for o in DATA["objects"]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(HERE, o["file"]))
    new = [x for x in bpy.data.objects if x not in before]
    root = bpy.data.objects.new(o["name"], None)
    bpy.context.collection.objects.link(root)
    for x in new:
        if x.parent is None:
            x.parent = root
    ROOTS[o["id"]] = root
    root.location = o["loc"]
    root.rotation_euler[2] = math.radians(o["yaw_z"])
    root.scale = (o["scale"], -o["scale"], o["scale"])   # WorldLock mirrors glTF's Z (Blender's Y here) so a model faces the camera at rest

for l in DATA["lights"]:
    sun = bpy.data.lights.new(l["name"], type="SUN")
    sun.energy = 3.0 * float(l["intensity"])
    h = l["colour"].lstrip("#")
    sun.color = tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    ob = bpy.data.objects.new(l["name"], sun)
    SUNS.append((sun, ob))
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


ANIM_TAIL = '''
# ---- the animation: the scene above is built once; each frame sets the numbers for that moment and renders a PNG
args = sys.argv[sys.argv.index("--") + 1:]
FRAMES = json.load(open(args[0], encoding="utf-8"))
START, END, OUT, W, H, SAMPLES = int(args[1]), int(args[2]), args[3], int(args[4]), int(args[5]), int(args[6])
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.resolution_percentage = 100
try:
    scene.eevee.taa_render_samples = SAMPLES
except Exception:
    pass
cam = bpy.data.cameras.new("Camera")
camob = bpy.data.objects.new("Camera", cam)
bpy.context.collection.objects.link(camob)
scene.camera = camob
os.makedirs(OUT, exist_ok=True)
for i in range(START, min(END, len(FRAMES))):
    fr = FRAMES[i]
    for o in fr["objects"]:
        r = ROOTS.get(o["id"])
        if r is None:
            continue
        r.location = o["loc"]
        r.rotation_euler[2] = math.radians(o["yaw_z"])
        r.scale = (o["scale"], -o["scale"], o["scale"])
        r.hide_render = not o["visible"]
        r.hide_viewport = not o["visible"]
    for (sun, ob), l in zip(SUNS, fr["lights"]):
        sun.energy = 3.0 * float(l["intensity"])
        sun.color = rgb(l["colour"])[:3]
        ob.rotation_euler = (math.radians(90 - float(l["elevation"])), 0, math.radians(-float(l["azimuth"]) + 180))
    ramp.color_ramp.elements[0].color = rgb(fr["sky"]["horizon"])
    ramp.color_ramp.elements[1].color = rgb(fr["sky"]["top"])
    bg.inputs["Strength"].default_value = max(0.05, float(fr["ambient"]) * 3.0)
    c = fr["cam"]
    cam.angle_x = math.radians(float(c["fov"]))
    camob.location = c["loc"]
    camob.rotation_euler = (math.radians(90 + float(c["pitch"])), 0, math.radians(-float(c["yaw"])))
    scene.render.filepath = os.path.join(OUT, "frame_%05d.png" % i)
    bpy.ops.render.render(write_still=True)
'''


def animation_script(s: dict, files: dict[str, str]) -> str:
    """The set's Blender script with its own cameras and save-and-render ending replaced by the frame loop."""
    head = build_script(s, files)
    cut = head.index("cams = []")
    return head[:cut] + ANIM_TAIL


def render_animation(d: str, sid: str, spec: dict, workers: int = 4, samples: int = 16) -> dict:
    """Render a worldanim animation with Blender's own renderer: every frame's numbers (camera, models, lights, sky, ambient, shake) are worked out exactly as the built-in renderer works them out, then Blender draws
    the frames in `workers` background processes and ffmpeg joins them into an MP4. Progress is reported as frames done; a `cancel.flag` file in the set's folder stops it."""
    import time
    from . import worldanim as WA
    from .export import ffmpeg
    V._film(d)
    st = status()
    if not st["found"]:
        raise SystemExit("Blender was not found.")
    s = WL._load(d, sid)
    sp = WA.clean_spec(spec)
    W, H = sp["size"]
    base = V._inside(d, f"worldlock/{sid}/blender")
    os.makedirs(base, exist_ok=True)
    files = {m["id"]: os.path.relpath(V._inside(d, m["file"]), base).replace("\\", "/") for m in s["models"]}
    frames = []
    for i in range(sp["frames"]):
        s2, cam = WA.state_at(s, sp, i / sp["fps"])
        fd = scene_data(s2, files, hidden=True, cam={"name": "Camera", "x": cam["x"], "y": cam["y"], "z": cam["z"], "yaw": cam["yaw"], "pitch": cam["pitch"], "fov": cam["fov"]})
        frames.append({"objects": fd["objects"], "cam": fd["cameras"][0], "lights": fd["lights"], "sky": fd["sky"], "ambient": fd["ambient"]})
    s0, _ = WA.state_at(s, sp, 0.0)
    script = os.path.join(base, "animate_scene.py")
    open(script, "w", encoding="utf-8").write(animation_script(s0, files))
    fjson = os.path.join(base, "frames.json")
    safeio.write_json(fjson, frames, backup=False)
    out = os.path.join(base, "anim_frames")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    cancel = os.path.join(V._inside(d, f"worldlock/{sid}"), "cancel.flag")
    try:
        os.remove(cancel)
    except OSError:
        pass
    n = sp["frames"]
    workers = max(1, min(int(workers), 12, n))
    step = -(-n // workers)
    t0 = time.time()
    procs = [subprocess.Popen([st["path"], "-b", "--factory-startup", "-P", script, "--", fjson, str(a), str(min(a + step, n)), out, str(W), str(H), str(int(samples))], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
             for a in range(0, n, step)]
    last = -1
    try:
        while any(p.poll() is None for p in procs):
            time.sleep(1.0)
            done = len(os.listdir(out))
            if done != last:
                last = done
                emit(event="progress", stage="drawing frames in Blender", progress=round(done / n, 3))
            if os.path.exists(cancel):
                for p in procs:
                    p.kill()
                raise SystemExit("Stopped.")
            if time.time() - t0 > 3600 * 3:
                for p in procs:
                    p.kill()
                raise SystemExit("Blender took too long.")
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
    got = sorted(os.listdir(out))
    if len(got) != n:
        raise SystemExit(f"Blender drew {len(got)} of {n} frames.")
    name = V._t(sp.get("name") or "animation", 40).replace(" ", "-") or "animation"
    rel = f"worldlock/{sid}/animations/{name}-blender-{int(time.time())}.mp4"
    full = V._inside(d, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    r = subprocess.run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(sp["fps"]), "-i", os.path.join(out, "frame_%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart", full], capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0 or not os.path.isfile(full):
        raise SystemExit("The frames were drawn but could not be joined into a video.")
    return {"file": rel, "path": full, "frames": n, "fps": sp["fps"], "size": [W, H], "took": round(time.time() - t0, 1), "renderer": "Blender " + st["version"]}


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
    ap.add_argument("action", choices=["status", "export", "render"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        res = status() if a.action == "status" else render_animation(os.path.abspath(a.target), x.get("set", ""), x.get("spec") or {}, int(x.get("workers", 4)), int(x.get("samples", 16))) if a.action == "render" else export(os.path.abspath(a.target), x.get("set", ""), x)
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
