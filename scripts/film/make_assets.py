"""Source assets for the short film "He Is Risen": the 3D models, made in code as low-poly, flat-shaded glTF binaries (.glb) so they can be rebuilt, edited and read by any tool.

Style: a low-poly diorama lit like stained glass: faceted shapes, flat colour, dramatic sky and light. Figures are faceless stylised forms (a robe, a head, arms), never realistic portraits.
Units are metres; models stand on y = 0 with their front toward +Z in glTF (the set mirrors Z on reading so a model faces the camera at rest).

  python scripts/film/make_assets.py <output folder>
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from glbtools import glb  # noqa: E402


def rgb(h: str):
    return [int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]


def _lin(c):
    return [(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4) for x in c]


def col(h: str, a: float = 1.0):
    return [*_lin(rgb(h)), a]                                                                              # glTF base colours are linear


class Mesh:
    """Triangles with flat (per-face) normals, one colour. Built up from primitives, then written as one glTF mesh."""

    def __init__(self, color: str, double: bool = False):
        self.tris = []
        self.color, self.double = col(color), double

    def add(self, tri):
        self.tris.append(np.asarray(tri, dtype=np.float64))

    def mat(self, m):
        out = Mesh("#ffffff", self.double)
        out.color = self.color
        for t in self.tris:
            out.tris.append((np.c_[t, np.ones(3)] @ m.T)[:, :3])
        return out

    def glb_mesh(self):
        pos, nrm, idx = [], [], []
        for t in self.tris:
            n = np.cross(t[1] - t[0], t[2] - t[0])
            n = n / (np.linalg.norm(n) or 1.0)
            base = len(pos)
            pos += [list(p) for p in t]
            nrm += [list(n)] * 3
            idx += [base, base + 1, base + 2]
        return {"pos": pos, "nrm": nrm, "idx": idx, "color": self.color, "double": self.double}


def T(x=0, y=0, z=0, sx=1, sy=1, sz=1, ry=0, rx=0, rz=0):
    cy, sy_ = math.cos(math.radians(ry)), math.sin(math.radians(ry))
    cx, sx_ = math.cos(math.radians(rx)), math.sin(math.radians(rx))
    cz, sz_ = math.cos(math.radians(rz)), math.sin(math.radians(rz))
    Ry = np.array([[cy, 0, sy_], [0, 1, 0], [-sy_, 0, cy]])
    Rx = np.array([[1, 0, 0], [0, cx, sx_], [0, -sx_, cx]])
    Rz = np.array([[cz, -sz_, 0], [sz_, cz, 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = Ry @ Rx @ Rz @ np.diag([sx, sy, sz])
    m[:3, 3] = [x, y, z]
    return m


def box(color, w=1, h=1, d=1, at=(0, 0, 0), ry=0, double=False):
    m = Mesh(color, double)
    x0, x1, y0, y1, z0, z1 = -w / 2, w / 2, 0, h, -d / 2, d / 2
    q = lambda a, b, c, e: (m.add([a, b, c]), m.add([a, c, e]))                                           # a quad, counter-clockwise seen from outside
    q((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))
    q((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0))
    q((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1))
    q((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0))
    q((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0))
    q((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))
    return m.mat(T(*at, ry=ry))


def cone(color, r0=0.5, r1=0.0, h=1.0, n=10, at=(0, 0, 0), double=False, rx=0, rz=0, ry=0, cap=True):
    """A frustum (or cone when r1 = 0) standing on y = 0 with n flat sides."""
    m = Mesh(color, double)
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        p0, p1 = (r0 * math.sin(a0), 0, r0 * math.cos(a0)), (r0 * math.sin(a1), 0, r0 * math.cos(a1))
        q0, q1 = (r1 * math.sin(a0), h, r1 * math.cos(a0)), (r1 * math.sin(a1), h, r1 * math.cos(a1))
        m.add([p0, q1, p1]) if r1 == 0 else (m.add([p0, q0, q1]), m.add([p0, q1, p1]))
        if cap and r1 > 0:
            m.add([(0, h, 0), q1, q0])
        if cap:
            m.add([(0, 0, 0), p0, p1])
    return m.mat(T(*at, rx=rx, rz=rz, ry=ry))


def sphere(color, r=0.5, at=(0, 0, 0), seg=8, ring=6, sy=1.0, jitter=0.0, seed=1):
    m = Mesh(color)
    rng = np.random.default_rng(seed)
    pts = {}

    def P(i, j):
        if (i, j) not in pts:
            th, ph = math.pi * j / ring, 2 * math.pi * (i % seg) / seg
            k = 1.0 + (rng.uniform(-jitter, jitter) if jitter and 0 < j < ring else 0.0)
            pts[(i % seg, j)] = (r * k * math.sin(th) * math.sin(ph), r * k * sy * math.cos(th), r * k * math.sin(th) * math.cos(ph))
        return pts[(i % seg, j)]
    for j in range(ring):
        for i in range(seg):
            a, b, c, d = P(i, j), P(i + 1, j), P(i + 1, j + 1), P(i, j + 1)
            if j > 0:
                m.add([a, c, b]) if False else m.add([a, b, c])
            if j < ring - 1:
                m.add([a, c, d])
    return m.mat(T(*at))


def disc(color, r=1.0, h=0.4, n=14, at=(0, 0, 0), rx=90):
    return cone(color, r, r, h, n, at, rx=rx)


def ring(color, r=0.3, w=0.04, h=0.04, n=16, at=(0, 0, 0), rx=0):
    """A flat ring (a halo) made of small boxes."""
    m = Mesh(color, True)
    for i in range(n):
        a = 2 * math.pi * i / n
        b = box(color, w=2 * math.pi * r / n * 1.05, h=h, d=w, at=(0, 0, 0))
        m.tris += b.mat(T(x=r * math.sin(a), z=r * math.cos(a), ry=math.degrees(a))).tris
    return m.mat(T(*at, rx=rx))


def wing(color, span=1.1, h=1.5, at=(0, 0, 0), side=1):
    m = Mesh(color, True)
    pts = [(0, 0, 0), (side * span * 0.55, h * 0.55, -0.12), (side * span, h * 0.9, -0.2), (side * span * 0.5, h * 0.2, -0.1), (side * span * 0.85, h * 0.45, -0.16)]
    m.add([pts[0], pts[1], pts[3]])
    m.add([pts[1], pts[2], pts[4]])
    m.add([pts[1], pts[4], pts[3]])
    return m.mat(T(*at))


def write(folder, name, meshes):
    data = glb([x.glb_mesh() for x in meshes])
    open(os.path.join(folder, name + ".glb"), "wb").write(data)
    return name, sum(len(x.tris) for x in meshes)


def make(folder):
    os.makedirs(folder, exist_ok=True)
    out = {}
    # ---- the land
    hill = [cone(c, 9.0, 5.0, 1.6, n=12, at=(0, 0, 0), cap=False).mat(T()) for c in ("#6b5a3e",)]
    wedges = []
    n = 14
    shades = ["#74623f", "#6a5a3c", "#7b6845", "#665636", "#6f5e3f", "#78653f", "#5f5033"]
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        m = Mesh(shades[i % len(shades)])
        p = lambda r, a, y: (r * math.sin(a), y, r * math.cos(a))
        m.add([p(10, a0, 0), p(4.5, a0, 2.4), p(4.5, a1, 2.4)])
        m.add([p(10, a0, 0), p(4.5, a1, 2.4), p(10, a1, 0)])
        m.add([p(4.5, a0, 2.4), p(0.1, a0, 2.6), p(4.5, a1, 2.4)])
        wedges.append(m)
    top = cone("#7a6944", 4.5, 4.4, 0.02, n=14, at=(0, 2.4, 0))
    out["hill"] = write(folder, "hill", wedges + [top])
    out["cross"] = write(folder, "cross", [box("#3b2a1c", 0.28, 4.6, 0.28, at=(0, 0, 0)), box("#43301f", 2.3, 0.28, 0.28, at=(0, 3.0, 0)), box("#2f2216", 0.5, 0.18, 0.5, at=(0, 0, 0))])
    out["cross_small"] = write(folder, "cross_small", [box("#3b2a1c", 0.22, 3.6, 0.22), box("#43301f", 1.8, 0.22, 0.22, at=(0, 2.4, 0))])
    rocks = [sphere("#8b8478", 1.0, at=(0, 0.5, 0), seg=7, ring=4, sy=0.75, jitter=0.18, seed=3)]
    out["rock"] = write(folder, "rock", rocks)
    out["boulder"] = write(folder, "boulder", [sphere("#7d776c", 1.0, at=(0, 0.8, 0), seg=7, ring=5, sy=0.8, jitter=0.22, seed=9)])
    # ---- the garden tomb: a cut in the rock, a dark opening, a groove, the rolling stone is a separate model
    mass = [box("#a8987a", 6.4, 4.2, 4.0, at=(0, 0, 0)), box("#b5a584", 5.6, 0.5, 3.4, at=(0, 4.2, 0)), box("#9a8a6d", 1.2, 3.0, 4.2, at=(-3.5, 0, 0)), box("#9a8a6d", 1.2, 3.0, 4.2, at=(3.5, 0, 0))]
    opening = [box("#0a0705", 2.1, 2.3, 0.4, at=(0, 0, 1.9)), cone("#0a0705", 1.05, 1.05, 0.4, n=10, at=(0, 2.3, 1.9), rx=90).mat(T(0, 0, 0))]
    arch = [box("#c4b592", 2.5, 0.3, 0.5, at=(0, 2.6, 2.0))]
    out["tomb"] = write(folder, "tomb", mass + opening[:1] + arch)
    out["stone"] = write(folder, "stone", [cone("#b9b1a2", 1.15, 1.15, 0.5, n=14, at=(0, 1.15, 0), rx=90).mat(T(0, 0, 0)), cone("#a69e90", 1.0, 1.0, 0.52, n=14, at=(0, 1.15, 0), rx=90)])
    out["tree"] = write(folder, "tree", [cone("#4c3a28", 0.22, 0.14, 1.8, n=7), sphere("#5f7048", 1.0, at=(0, 2.3, 0), seg=7, ring=5, sy=0.8, jitter=0.1, seed=5), sphere("#6a7b4f", 0.7, at=(0.7, 1.9, 0.2), seg=6, ring=4, jitter=0.1, seed=6)])
    out["cypress"] = write(folder, "cypress", [cone("#4c3a28", 0.2, 0.15, 0.6, n=6), cone("#364a33", 0.7, 0.0, 3.8, n=7, at=(0, 0.5, 0))])
    # ---- the far city: a row of boxes, the skyline of Jerusalem
    city, x = [], -32.0
    rng = np.random.default_rng(4)
    while x < 32:
        w, h = rng.uniform(2.0, 4.5), rng.uniform(3.0, 9.0)
        city.append(box("#9c8a6a" if rng.random() < 0.6 else "#b19c78", w, h, 2.5, at=(x + w / 2, 0, 0)))
        if rng.random() < 0.35:
            city.append(cone("#8a7656", 0.9, 0.0, 1.4, n=6, at=(x + w / 2, h, 0)))
        x += w + rng.uniform(0.1, 0.6)
    out["city"] = write(folder, "city", city)
    # ---- figures: faceless, stylised, kind
    skin = "#c79a76"
    mary = [cone("#1f3b7a", 0.52, 0.16, 1.45, n=9, at=(0, 0, 0)), cone("#2c4f9c", 0.2, 0.19, 0.12, n=9, at=(0, 1.38, 0)), sphere(skin, 0.15, at=(0, 1.62, 0.03), seg=8, ring=6),
            sphere("#e8e0d0", 0.2, at=(0, 1.66, -0.03), seg=8, ring=5, sy=1.0), cone("#1f3b7a", 0.1, 0.07, 0.62, n=6, at=(-0.2, 0.95, 0.1), rx=-18, rz=18), cone("#1f3b7a", 0.1, 0.07, 0.62, n=6, at=(0.2, 0.95, 0.1), rx=-18, rz=-18),
            sphere(skin, 0.06, at=(-0.27, 0.9, 0.27)), sphere(skin, 0.06, at=(0.27, 0.9, 0.27))]
    out["mary"] = write(folder, "mary", mary)
    angel = [cone("#f4f1e8", 0.6, 0.17, 1.75, n=9), cone("#ffd75e", 0.62, 0.58, 0.07, n=9, at=(0, 0.95, 0)), sphere("#f1d9bb", 0.17, at=(0, 1.9, 0.02), seg=8, ring=6), ring("#ffd24a", 0.3, at=(0, 2.22, 0), rx=0),
             cone("#f4f1e8", 0.1, 0.07, 0.8, n=6, at=(-0.3, 1.25, 0.1), rz=35), cone("#f4f1e8", 0.1, 0.07, 0.8, n=6, at=(0.3, 1.25, 0.1), rz=-35),
             wing("#fffaf0", 1.15, 1.6, at=(-0.12, 1.25, -0.12), side=-1), wing("#fffaf0", 1.15, 1.6, at=(0.12, 1.25, -0.12), side=1)]
    out["angel"] = write(folder, "angel", angel)
    jesus = [cone("#fbf7ec", 0.62, 0.17, 1.85, n=10), cone("#c8362d", 0.2, 0.18, 0.1, n=10, at=(0, 1.15, 0)), sphere("#d9b08c", 0.17, at=(0, 1.98, 0.02), seg=8, ring=6), ring("#ffd24a", 0.34, at=(0, 2.3, 0), rx=0),
             cone("#fbf7ec", 0.1, 0.07, 0.95, n=6, at=(-0.28, 1.45, 0.06), rz=62), cone("#fbf7ec", 0.1, 0.07, 0.95, n=6, at=(0.28, 1.45, 0.06), rz=-62), sphere("#d9b08c", 0.06, at=(-1.15, 1.5, 0.06)), sphere("#d9b08c", 0.06, at=(1.15, 1.5, 0.06))]
    out["jesus"] = write(folder, "jesus", jesus)
    return out


if __name__ == "__main__":
    dst = sys.argv[1] if len(sys.argv) > 1 else "assets"
    for k, v in make(dst).items():
        print(f"{k:12s} {v[1]:5d} triangles")
