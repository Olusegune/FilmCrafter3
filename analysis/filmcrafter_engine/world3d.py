"""True 3D for a WorldLock set: reading glTF models, placing them with a transform hierarchy, and drawing them with a small software renderer. Pure numpy and Pillow: no film, no network, no GPU, no
3D library; deterministic (the same scene and camera always give the same picture), and reusable by any application.

What it reads. **glTF 2.0** as `.glb` (binary) or as `.gltf` with its buffers inside the file as base64: meshes made of triangles with positions, normals, texture coordinates and indices, the node
hierarchy (matrices or translation, rotation and scale), and materials (`baseColorFactor`, `baseColorTexture`, `doubleSided`). What it ignores, and says so in `warnings`: animations, skins, morph
targets, cameras and lights inside the file, extensions, buffers kept in separate files, and everything that is not a triangle list. A glTF model is Y-up, in metres, with its front toward +Z in glTF's right-handed space. The set is left-handed (+Z into the set), so Z is mirrored on reading
and a model's front then faces -Z, toward a camera at rest: a model faces the camera when it is not turned.

Transforms. An instance has a position (metres), a rotation (yaw about Y, pitch about X, roll about Z, degrees) and a scale; a group has the same and instances name a group as their parent. The
world matrix is parent after parent, then the instance: `M = T(position) . Ry(yaw) . Rx(pitch) . Rz(roll) . S(scale)`. Yaw turns the model's front from +Z toward +X; pitch tips its front up.

Drawing. Triangles are moved into camera space (the same camera as `worldmath`), clipped to the near plane, rasterised with a depth buffer and perspective-correct interpolation, and shaded with a
base colour (material factor times texture) under the set's lights (directional, from an azimuth and elevation) and a soft ambient term, in linear light. A ground plane is drawn exactly, by
intersecting each pixel's ray with the plane, with a metre-wide checker so scale can be read. There is no shadow casting, no reflections, no transparency, no anti-aliasing beyond what the output size gives
and no physically based shading: it is a reference renderer, honest about being one. A scene is refused when it has more than `MAX_TRIANGLES` triangles rather than taking minutes.
"""
from __future__ import annotations

import base64
import io
import json
import math
import struct

import numpy as np
from PIL import Image

from . import keying as K
from . import worldmath as WM

MAX_FILE = 60 * 1024 * 1024
MAX_TRIANGLES = 150_000
MAX_TEXTURE = 4096
NEAR = WM.NEAR
GLTF_FLOAT, GLTF_UBYTE, GLTF_USHORT, GLTF_UINT = 5126, 5121, 5123, 5125
_COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


# ---------------------------------------------------------------- transforms

def rotation(yaw: float, pitch: float, roll: float) -> np.ndarray:
    """The 3x3 rotation `Ry(yaw) . Rx(pitch) . Rz(roll)`, degrees. Yaw turns +Z toward +X, pitch tips +Z up."""
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, cp, sp], [0, -sp, cp]])
    rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    return ry @ rx @ rz


def matrix(t: dict) -> np.ndarray:
    """The 4x4 matrix of {x, y, z, yaw, pitch, roll, scale (a number or three)}: T . R . S."""
    s = t.get("scale", 1.0)
    sx, sy, sz = (s, s, s) if not isinstance(s, (list, tuple)) else (s[0], s[1], s[2])
    m = np.eye(4)
    m[:3, :3] = rotation(t.get("yaw", 0.0), t.get("pitch", 0.0), t.get("roll", 0.0)) @ np.diag([sx, sy, sz])
    m[:3, 3] = [t.get("x", 0.0), t.get("y", 0.0), t.get("z", 0.0)]
    return m


def world_matrix(inst: dict, groups: dict[str, dict], seen: tuple = ()) -> np.ndarray:
    """An instance's world matrix: its own transform inside its parent group's, and so on up. A cycle in the groups is refused."""
    m = matrix(inst)
    pid = inst.get("parent")
    if pid:
        if pid in seen or pid not in groups:
            if pid in seen:
                raise SystemExit("The groups contain themselves.")
            return m
        return world_matrix(groups[pid], groups, seen + (pid,)) @ m
    return m


# ---------------------------------------------------------------- reading glTF

def _trs(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T                           # glTF stores matrices column-major
    t = node.get("translation", [0, 0, 0])
    q = node.get("rotation", [0, 0, 0, 1])
    s = node.get("scale", [1, 1, 1])
    x, y, z, w = q
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r @ np.diag(s)
    m[:3, 3] = t
    return m


def _parse_container(raw: bytes) -> tuple[dict, bytes | None]:
    if raw[:4] == b"glTF":
        if len(raw) < 20:
            raise SystemExit("That file is too short to be a glTF binary.")
        version, length = struct.unpack_from("<II", raw, 4)
        if version != 2:
            raise SystemExit("Only glTF 2.0 is read.")
        pos, js, binchunk = 12, None, None
        while pos + 8 <= min(len(raw), length):
            clen, ctype = struct.unpack_from("<II", raw, pos)
            body = raw[pos + 8: pos + 8 + clen]
            if ctype == 0x4E4F534A:
                js = body
            elif ctype == 0x004E4942 and binchunk is None:
                binchunk = body
            pos += 8 + clen + (-clen % 4)
        if js is None:
            raise SystemExit("That glTF binary has no scene description.")
        try:
            return json.loads(js.decode("utf-8")), binchunk
        except (ValueError, UnicodeDecodeError):
            raise SystemExit("That glTF binary's description is damaged.")
    try:
        return json.loads(raw.decode("utf-8")), None
    except (ValueError, UnicodeDecodeError):
        raise SystemExit("That file is not a glTF model (.glb or .gltf).")


def _buffers(doc: dict, binchunk: bytes | None) -> list[bytes]:
    out = []
    for i, b in enumerate(doc.get("buffers", [])):
        uri = b.get("uri")
        if uri is None:
            if i == 0 and binchunk is not None:
                out.append(binchunk)
                continue
            raise SystemExit("A buffer of the model has no data.")
        if uri.startswith("data:"):
            try:
                out.append(base64.b64decode(uri.split(",", 1)[1]))
            except Exception:
                raise SystemExit("A buffer inside the model could not be decoded.")
        else:
            raise SystemExit("This model keeps its data in separate files. Export it as a single .glb (or a .gltf with embedded buffers).")
    return out


def _accessor(doc: dict, bufs: list[bytes], idx: int) -> np.ndarray:
    acc = doc["accessors"][idx]
    if "sparse" in acc:
        raise SystemExit("Sparse accessors are not read.")
    fmt, size = _COMPONENT[acc["componentType"]]
    n = _NCOMP[acc["type"]]
    count = acc["count"]
    if "bufferView" not in acc:
        return np.zeros((count, n), dtype=np.float32 if fmt == "f" else np.int64)
    bv = doc["bufferViews"][acc["bufferView"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or size * n
    data = bufs[bv["buffer"]]
    need = base + (count - 1) * stride + size * n if count else base
    if need > len(data):
        raise SystemExit("The model's data ends too soon.")
    dt = np.dtype({"f": "<f4", "B": "u1", "b": "i1", "H": "<u2", "h": "<i2", "I": "<u4"}[fmt])
    if stride == size * n:
        arr = np.frombuffer(data, dtype=dt, count=count * n, offset=base).reshape(count, n)
    else:
        arr = np.stack([np.frombuffer(data, dtype=dt, count=n, offset=base + i * stride) for i in range(count)]) if count else np.zeros((0, n), dtype=dt)
    return arr.astype(np.float32) if fmt == "f" else arr.astype(np.int64)


def _image(doc: dict, bufs: list[bytes], tex_index: int) -> np.ndarray | None:
    try:
        src = doc["textures"][tex_index]["source"]
        img = doc["images"][src]
        if "bufferView" in img:
            bv = doc["bufferViews"][img["bufferView"]]
            raw = bufs[bv["buffer"]][bv.get("byteOffset", 0): bv.get("byteOffset", 0) + bv["byteLength"]]
        elif str(img.get("uri", "")).startswith("data:"):
            raw = base64.b64decode(img["uri"].split(",", 1)[1])
        else:
            return None
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
        if max(im.size) > MAX_TEXTURE:
            im.thumbnail((MAX_TEXTURE, MAX_TEXTURE))
        return np.asarray(im, dtype=np.float32) / 255.0
    except Exception:                                                                                      # noqa: BLE001  a damaged texture is ignored and reported, never fatal
        return None


def load_model(path: str) -> dict:
    try:
        return _load_model(path)
    except (KeyError, IndexError, TypeError, ValueError, struct.error):
        raise SystemExit("That model's description is damaged or incomplete, so it cannot be read.")


def _load_model(path: str) -> dict:
    """A glTF model read into flat triangle meshes in the model's own space (its node transforms applied): `meshes` (each: positions, normals, uvs or None, triangles, material), the `bbox` (min and max),
    the triangle count, and `warnings` about what was ignored. Refuses what it cannot read, in plain words."""
    import os
    if os.path.getsize(path) > MAX_FILE:
        raise SystemExit("That model is larger than 60 MB.")
    raw = open(path, "rb").read()
    doc, binchunk = _parse_container(raw)
    if str(doc.get("asset", {}).get("version", "")).split(".")[0] != "2":
        raise SystemExit("Only glTF 2.0 is read.")
    bufs = _buffers(doc, binchunk)
    warnings: list[str] = []
    for k, msg in (("animations", "Animations are ignored."), ("skins", "Skins (rigged bones) are ignored: the model is drawn in its rest pose."), ("cameras", "Cameras inside the model are ignored.")):
        if doc.get(k):
            warnings.append(msg)
    if doc.get("extensionsRequired"):
        warnings.append("Required extensions (" + ", ".join(map(str, doc["extensionsRequired"]))[:80] + ") are not supported: the model may look wrong.")
    meshes, tris = [], 0
    scene = doc["scenes"][doc.get("scene", 0)] if doc.get("scenes") else {"nodes": list(range(len(doc.get("nodes", []))))}

    def walk(ni: int, parent: np.ndarray, depth: int = 0):
        nonlocal tris
        if depth > 64:
            raise SystemExit("The model's node tree is too deep.")
        node = doc["nodes"][ni]
        m = parent @ _trs(node)
        if "mesh" in node:
            for prim in doc["meshes"][node["mesh"]]["primitives"]:
                if prim.get("mode", 4) != 4:
                    warnings.append("Only triangle meshes are drawn; lines and points were skipped.")
                    continue
                attrs = prim.get("attributes", {})
                if "POSITION" not in attrs:
                    continue
                pos = _accessor(doc, bufs, attrs["POSITION"]).astype(np.float64)
                idx = _accessor(doc, bufs, prim["indices"]).reshape(-1) if "indices" in prim else np.arange(len(pos))
                if len(idx) % 3:
                    idx = idx[: len(idx) - len(idx) % 3]
                tri = idx.reshape(-1, 3)
                if len(tri) and (tri.max() >= len(pos) or tri.min() < 0):
                    raise SystemExit("A triangle of the model points at a point that does not exist.")
                tris += len(tri)
                if tris > MAX_TRIANGLES:
                    raise SystemExit(f"That model has more than {MAX_TRIANGLES:,} triangles: too many to draw. Simplify it (decimate) in a modelling tool first.")
                pw = (np.c_[pos, np.ones(len(pos))] @ m.T)[:, :3]
                if "NORMAL" in attrs:
                    nm = _accessor(doc, bufs, attrs["NORMAL"]).astype(np.float64)
                    nw = nm @ np.linalg.inv(m[:3, :3]).T
                    nw /= np.maximum(np.linalg.norm(nw, axis=1, keepdims=True), 1e-12)
                else:
                    nw = None
                pw[:, 2] *= -1.0                                                                          # glTF is right-handed, the set is left-handed (Z into the set): mirror Z so a model is not mirrored in the picture
                if nw is not None:
                    nw[:, 2] *= -1.0
                tri = tri[:, [0, 2, 1]]                                                                  # and keep the outside of every triangle the outside
                uv = _accessor(doc, bufs, attrs["TEXCOORD_0"]).astype(np.float64) if "TEXCOORD_0" in attrs else None
                mat = doc.get("materials", [])[prim["material"]] if "material" in prim and prim["material"] < len(doc.get("materials", [])) else {}
                pbr = mat.get("pbrMetallicRoughness", {})
                tex = None
                if "baseColorTexture" in pbr:
                    tex = _image(doc, bufs, pbr["baseColorTexture"]["index"])
                    if tex is None:
                        warnings.append("A texture could not be read: its surface is drawn in the material's plain colour.")
                meshes.append({"pos": pw, "nrm": nw, "uv": uv, "tri": tri, "color": np.array(pbr.get("baseColorFactor", [1, 1, 1, 1]), dtype=np.float64), "tex": tex, "double": bool(mat.get("doubleSided", False))})
        for c in node.get("children", []):
            walk(c, m, depth + 1)
    for n in scene.get("nodes", []):
        walk(n, np.eye(4))
    if not meshes:
        raise SystemExit("That model has no triangle meshes to draw.")
    allp = np.concatenate([m_["pos"] for m_ in meshes])
    return {"meshes": meshes, "bbox": [allp.min(axis=0).round(4).tolist(), allp.max(axis=0).round(4).tolist()], "triangles": int(tris), "warnings": list(dict.fromkeys(warnings)),
            "materials": len(doc.get("materials", [])), "textures": len(doc.get("textures", []))}


def summary(model: dict) -> dict:
    lo, hi = model["bbox"]
    return {"triangles": model["triangles"], "bbox": model["bbox"], "size": [round(hi[i] - lo[i], 3) for i in range(3)], "warnings": model["warnings"], "materials": model["materials"], "textures": model["textures"]}


def world_bbox(local_bbox: list, m: np.ndarray) -> list:
    """The axis-aligned box that holds a model's box after a transform (the corners moved, then boxed). Conservative for a turned model."""
    lo, hi = local_bbox
    corners = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    w = (corners @ m.T)[:, :3]
    return [w.min(axis=0).round(4).tolist(), w.max(axis=0).round(4).tolist()]


# ---------------------------------------------------------------- drawing

def _to_cam(points: np.ndarray, cam: dict) -> np.ndarray:
    """World points (N, 3) in the camera's space (x right, y up, z forward): the same maths as `worldmath.to_camera`, for many points."""
    p = points - np.array([cam["x"], cam["y"], cam["z"]])
    yaw, pitch = math.radians(cam.get("yaw", 0.0)), math.radians(cam.get("pitch", 0.0))
    cy, sy = math.cos(yaw), math.sin(yaw)
    x, z = p[:, 0] * cy - p[:, 2] * sy, p[:, 0] * sy + p[:, 2] * cy
    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = p[:, 1] * cp - z * sp, p[:, 1] * sp + z * cp
    return np.stack([x, y, z], axis=1)


def _cam_to_world_dirs(cam: dict) -> np.ndarray:
    """The rows are the camera's right, up and forward as world directions."""
    yaw, pitch = math.radians(cam.get("yaw", 0.0)), math.radians(cam.get("pitch", 0.0))
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    fwd = np.array([sy * cp, sp, cy * cp])
    right = np.array([cy, 0.0, -sy])
    up = np.cross(fwd, right)
    return np.stack([right, up, fwd])


def light_vectors(lights: list[dict] | None) -> list[tuple[np.ndarray, np.ndarray]]:
    """The directions toward each light and its colour times strength (linear). With no lights set, a soft key from above and to the left stands in so a model is not drawn flat."""
    if not lights:
        lights = [{"azimuth": -35.0, "elevation": 50.0, "colour": "#ffffff", "intensity": 0.8}]
    out = []
    for l in lights:
        az, el = math.radians(l.get("azimuth", 0.0)), math.radians(l.get("elevation", 45.0))
        d = np.array([math.sin(az) * math.cos(el), math.sin(el), math.cos(az) * math.cos(el)])
        c = l.get("colour", "#ffffff")
        rgb = np.array([int(c[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]) if isinstance(c, str) and len(c) == 7 else np.ones(3)
        out.append((d, K.to_linear(rgb) * float(l.get("intensity", 0.8))))
    return out


def _clip_near(tri_c: np.ndarray, attrs: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """A triangle (camera space) cut at the near plane: nothing, the triangle, or one or two triangles, with its attributes interpolated along the cut."""
    z = tri_c[:, 2]
    inside = z > NEAR
    if inside.all():
        return [(tri_c, attrs)]
    if not inside.any():
        return []
    poly = []
    for i in range(3):
        j = (i + 1) % 3
        if inside[i]:
            poly.append((tri_c[i], attrs[i]))
        if inside[i] != inside[j]:
            t = (NEAR - z[i]) / (z[j] - z[i])
            poly.append((tri_c[i] + (tri_c[j] - tri_c[i]) * t, attrs[i] + (attrs[j] - attrs[i]) * t))
    if len(poly) < 3:
        return []
    out = []
    for k in range(1, len(poly) - 1):
        out.append((np.array([poly[0][0], poly[k][0], poly[k + 1][0]]), np.array([poly[0][1], poly[k][1], poly[k + 1][1]])))
    return out


def _sample(tex: np.ndarray, uv: np.ndarray) -> np.ndarray:
    h, w = tex.shape[:2]
    u = np.minimum(np.floor(np.mod(uv[:, 0], 1.0) * w).astype(int), w - 1)
    v = np.minimum(np.floor(np.mod(uv[:, 1], 1.0) * h).astype(int), h - 1)
    return tex[v, u]


def render_meshes(instances: list[dict], cam: dict, size: tuple[int, int], lights: list[dict] | None, ambient: float, depth: np.ndarray, color: np.ndarray, hit: np.ndarray) -> int:
    """Draw model instances (each {meshes, matrix}) into `color` (linear light), `depth` (camera-space z, inf where nothing) and `hit`. Returns how many triangles were drawn."""
    W, H = size
    f = WM.focal_px(W, cam.get("fov", 50.0))
    ls = light_vectors(lights)
    drawn = 0
    for inst in instances:
        M = inst["matrix"]
        nmat = np.linalg.inv(M[:3, :3]).T
        for mesh in inst["model"]["meshes"]:
            pw = (np.c_[mesh["pos"], np.ones(len(mesh["pos"]))] @ M.T)[:, :3]
            pc = _to_cam(pw, cam)
            if mesh["nrm"] is not None:
                nw = mesh["nrm"] @ nmat.T
                nw /= np.maximum(np.linalg.norm(nw, axis=1, keepdims=True), 1e-12)
            else:
                nw = None
            uv = mesh["uv"]
            tri = mesh["tri"]
            base = mesh["color"]
            zmax = pc[tri][:, :, 2].max(axis=1)
            keep = zmax > NEAR
            sx = W / 2 + f * pc[:, 0] / np.maximum(pc[:, 2], NEAR)
            sy = H / 2 - f * pc[:, 1] / np.maximum(pc[:, 2], NEAR)
            tx, ty = sx[tri], sy[tri]
            keep &= (tx.max(axis=1) >= 0) & (tx.min(axis=1) <= W) & (ty.max(axis=1) >= 0) & (ty.min(axis=1) <= H)
            for ti in np.nonzero(keep)[0]:
                a, b, c = tri[ti]
                attrs = np.zeros((3, 8))
                p3 = pw[[a, b, c]]
                if nw is not None:
                    attrs[:, 0:3] = nw[[a, b, c]]
                else:
                    fn = np.cross(p3[1] - p3[0], p3[2] - p3[0])
                    attrs[:, 0:3] = fn / (np.linalg.norm(fn) or 1.0)
                if uv is not None:
                    attrs[:, 3:5] = uv[[a, b, c]]
                for tc, at in _clip_near(pc[[a, b, c]], attrs):
                    z = tc[:, 2]
                    x = W / 2 + f * tc[:, 0] / z
                    y = H / 2 - f * tc[:, 1] / z
                    x0, x1 = int(max(0, math.floor(x.min()))), int(min(W, math.ceil(x.max())))
                    y0, y1 = int(max(0, math.floor(y.min()))), int(min(H, math.ceil(y.max())))
                    if x1 <= x0 or y1 <= y0:
                        continue
                    area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
                    if abs(area) < 1e-9:
                        continue
                    if not mesh["double"] and area < 0:                                                    # back face: after the mirror and the index swap an outward face has positive area on the y-down screen
                        continue
                    gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
                    w0 = ((x[1] - gx) * (y[2] - gy) - (x[2] - gx) * (y[1] - gy)) / area
                    w1 = ((x[2] - gx) * (y[0] - gy) - (x[0] - gx) * (y[2] - gy)) / area
                    w2 = 1.0 - w0 - w1
                    m = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
                    if not m.any():
                        continue
                    iz = w0 / z[0] + w1 / z[1] + w2 / z[2]
                    zz = 1.0 / np.maximum(iz, 1e-12)
                    sub = depth[y0:y1, x0:x1]
                    m &= zz < sub
                    if not m.any():
                        continue
                    pw0, pw1, pw2 = w0[m] / z[0], w1[m] / z[1], w2[m] / z[2]
                    zi = zz[m]
                    at_p = (pw0[:, None] * at[0] + pw1[:, None] * at[1] + pw2[:, None] * at[2]) * zi[:, None]
                    n = at_p[:, 0:3]
                    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
                    if mesh["double"]:
                        facing = (n * _cam_view_dir(cam)).sum(axis=1) > 0
                        n = np.where(facing[:, None], -n, n)
                    rgba = np.tile(base, (len(zi), 1))
                    if mesh["tex"] is not None and uv is not None:
                        t = _sample(mesh["tex"], at_p[:, 3:5])
                        rgba = rgba * np.c_[K.to_linear(t[:, :3]), t[:, 3]]
                    lit = np.full((len(zi), 3), ambient)
                    for d, lc in ls:
                        lit += np.maximum(0.0, (n * d).sum(axis=1))[:, None] * lc
                    col = K.to_linear(np.clip(rgba[:, :3], 0, 1)) if mesh["tex"] is None else np.clip(rgba[:, :3], 0, 1)
                    color[y0:y1, x0:x1][m] = col * lit
                    sub[m] = zi
                    hit[y0:y1, x0:x1][m] = True
                    drawn += 1
    return drawn


def _cam_view_dir(cam: dict) -> np.ndarray:
    return _cam_to_world_dirs(cam)[2]


def render_ground(cam: dict, size: tuple[int, int], y: float, colours: tuple[tuple[float, float, float], tuple[float, float, float]], extent: float, lights: list[dict] | None,
                  ambient: float, depth: np.ndarray, color: np.ndarray, hit: np.ndarray) -> None:
    """A ground plane at height `y`, drawn exactly: each pixel's ray is cut with the plane. A metre-wide two-colour checker shows scale; it stops at `extent` metres from the origin."""
    W, H = size
    f = WM.focal_px(W, cam.get("fov", 50.0))
    gx, gy = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    ray_cam = np.stack([(gx - W / 2) / f, -(gy - H / 2) / f, np.ones_like(gx)], axis=-1)              # a ray through each pixel in camera space
    R = _cam_to_world_dirs(cam)
    ray = ray_cam @ R                                                                                      # rows are right, up, forward in world space
    cy = cam["y"]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (y - cy) / ray[..., 1]
    ok = (t > 0) & np.isfinite(t)
    px = cam["x"] + ray[..., 0] * t
    pz = cam["z"] + ray[..., 2] * t
    zc = t * ray_cam[..., 2]                                                                              # camera-space depth of the hit
    ok &= (np.abs(px) <= extent) & (np.abs(pz) <= extent) & (zc > NEAR)
    ok &= zc < depth
    if not ok.any():
        return
    chk = ((np.floor(px) + np.floor(pz)) % 2 == 0)
    base = np.where(chk[..., None], np.array(colours[0]), np.array(colours[1]))
    lit = np.full(3, ambient)
    for d, lc in light_vectors(lights):
        lit = lit + max(0.0, d[1]) * lc
    color[ok] = (K.to_linear(base) * lit)[ok]
    depth[ok] = zc[ok]
    hit[ok] = True


def new_buffers(size: tuple[int, int]):
    W, H = size
    return np.zeros((H, W, 3), np.float64), np.full((H, W), np.inf), np.zeros((H, W), bool)
