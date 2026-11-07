"""A tiny glTF 2.0 writer for tests: enough to make real .glb files (meshes, materials, node hierarchy, a texture) following the specification, independently of the reader in `world3d`."""
import base64
import io
import json
import struct

import numpy as np
from PIL import Image


def _pad(b: bytes, fill: bytes = b"\x00") -> bytes:
    return b + fill * (-len(b) % 4)


def glb(meshes: list[dict], nodes: list[dict] | None = None, extra: dict | None = None, embedded: bool = False, texture: Image.Image | None = None) -> bytes:
    """meshes: [{pos, idx, color, nrm?, uv?, double?, tex?}]; nodes: optional [{mesh, children, translation, rotation, scale}] (default: one node per mesh)."""
    blob = bytearray()
    views, accessors, mats, prims = [], [], [], []

    def add(arr: np.ndarray, ctype: int, typ: str, target: int | None = None, minmax=False) -> int:
        data = _pad(arr.tobytes())
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(arr.tobytes()), **({"target": target} if target else {})})
        blob.extend(data)
        acc = {"bufferView": len(views) - 1, "componentType": ctype, "count": int(len(arr)), "type": typ}
        if minmax:
            acc["min"], acc["max"] = arr.min(axis=0).tolist(), arr.max(axis=0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    images, textures = [], []
    if texture is not None:
        b = io.BytesIO()
        texture.save(b, "PNG")
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(b.getvalue())})
        blob.extend(_pad(b.getvalue()))
        images.append({"bufferView": len(views) - 1, "mimeType": "image/png"})
        textures.append({"source": 0})
    gm = []
    for m in meshes:
        attrs = {"POSITION": add(np.asarray(m["pos"], dtype="<f4"), 5126, "VEC3", 34962, True)}
        if m.get("nrm") is not None:
            attrs["NORMAL"] = add(np.asarray(m["nrm"], dtype="<f4"), 5126, "VEC3", 34962)
        if m.get("uv") is not None:
            attrs["TEXCOORD_0"] = add(np.asarray(m["uv"], dtype="<f4"), 5126, "VEC2", 34962)
        idx = np.asarray(m["idx"], dtype="<u2" if np.asarray(m["pos"]).shape[0] < 65535 else "<u4").reshape(-1)
        ii = add(idx.reshape(-1, 1), 5123 if idx.dtype == np.dtype("<u2") else 5125, "SCALAR", 34963)
        pbr = {"baseColorFactor": list(m.get("color", [1, 1, 1, 1]))}
        if m.get("tex") and texture is not None:
            pbr["baseColorTexture"] = {"index": 0}
        mats.append({"pbrMetallicRoughness": pbr, "doubleSided": bool(m.get("double", False))})
        gm.append({"primitives": [{"attributes": attrs, "indices": ii, "material": len(mats) - 1}]})
    doc = {"asset": {"version": "2.0", "generator": "FilmCrafter test writer"}, "scene": 0, "scenes": [{"nodes": [0] if nodes else list(range(len(gm)))}], "meshes": gm, "materials": mats,
           "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}], "nodes": nodes or [{"mesh": i} for i in range(len(gm))]}
    if images:
        doc["images"], doc["textures"] = images, textures
    doc.update(extra or {})
    if embedded:
        doc["buffers"] = [{"byteLength": len(blob), "uri": "data:application/octet-stream;base64," + base64.b64encode(bytes(blob)).decode()}]
        return json.dumps(doc).encode()
    js = _pad(json.dumps(doc).encode(), b" ")
    bn = _pad(bytes(blob))
    total = 12 + 8 + len(js) + 8 + len(bn)
    return b"GLB" b"\x00"[:0] + struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bn), 0x004E4942) + bn


def cube_faces(size=1.0, colors=None, center=(0.0, 0.0, 0.0)):
    """A cube as six meshes (one per face, so each can have its own colour), faces wound counter-clockwise seen from outside. Order: +Z (front), -Z (back), +X, -X, +Y, -Y."""
    h = size / 2.0
    cx, cy, cz = center
    f = {
        "+z": ([[-h, -h, h], [h, -h, h], [h, h, h], [-h, h, h]], [0, 0, 1]),
        "-z": ([[h, -h, -h], [-h, -h, -h], [-h, h, -h], [h, h, -h]], [0, 0, -1]),
        "+x": ([[h, -h, h], [h, -h, -h], [h, h, -h], [h, h, h]], [1, 0, 0]),
        "-x": ([[-h, -h, -h], [-h, -h, h], [-h, h, h], [-h, h, -h]], [-1, 0, 0]),
        "+y": ([[-h, h, h], [h, h, h], [h, h, -h], [-h, h, -h]], [0, 1, 0]),
        "-y": ([[-h, -h, -h], [h, -h, -h], [h, -h, h], [-h, -h, h]], [0, -1, 0]),
    }
    cols = colors or {"+z": (1, 0, 0), "-z": (0, 0, 1), "+x": (0, 1, 0), "-x": (1, 1, 0), "+y": (1, 1, 1), "-y": (0.2, 0.2, 0.2)}
    out = []
    for k in ("+z", "-z", "+x", "-x", "+y", "-y"):
        v, n = f[k]
        v = [[a + cx, b + cy, c + cz] for a, b, c in v]
        out.append({"pos": v, "nrm": [n] * 4, "uv": [[0, 1], [1, 1], [1, 0], [0, 0]], "idx": [0, 1, 2, 0, 2, 3], "color": [*cols[k], 1.0]})
    return out
