"""DirectorCam: planning shots on a WorldLock set, with cameras that move along real paths and advice that a director can overrule.

What it does, and how:

* **Camera placement** (`place_camera`). A shot size ("close-up", "medium", "wide"...) is a *height of the world that fits in the frame* (a close-up fits about half a metre, a wide shot nearly three).
  Given who is in the shot, the camera's distance follows from the lens and that height by trigonometry, and it is turned to look at them. An over-the-shoulder shot stands behind one person's
  shoulder looking at the other.
* **Camera movements** (`camera_path`). Static, pan, tilt, dolly, truck, pedestal, crane, orbit, tracking, push-in, pull-out, each a plain transform of the camera (move along the way it points, to
  the side, up, round a point, turn in place), sampled into poses. The path is deterministic: the same move always gives the same poses. Every pose is checked against the set for gaps.
* **Planning from a story beat** (`plan_beat`). Plain word rules over a sentence ("The girl enters, sees the spilled oranges, and rushes to help the vendor"): the people and things of the set that
  the sentence names, what each verb asks for (an entrance, a look, a rush, a line of dialogue, a fall), and a short list of shots with a reason for each. It reads words, it does not understand
  stories; what it cannot find in the set it says it could not find. No AI model is asked, nothing is sent, and nothing is saved until the plan is.
* **Advice** (`checks`). The 180-degree line, the 30-degree guideline, eyelines, screen direction, objects in the way, people out of frame, cameras outside the set. Each is *advice with a reason*
  and a person can mark a shot as deliberate: a deliberate break is noted, not nagged.
* **Shot packages** (`package`). For a shot: the first and last frame rendered from the set, a strip of frames along the camera path, a depth map and an object map computed from the set, the camera,
  the people's start and end positions, the lights, the continuity constraints and the motion in words, with a plain list of what a chosen model can and cannot take.

What it does not do: it does not generate a picture or a video, ask a model, or send anything. The depth map is the depth of flat pictures (each object has one depth). A generated shot made from a
package is *not* guaranteed to match the set: the package is the reference it should be checked against. Providers do not all accept all of these inputs: `capabilities` says which are known.

  <film>/worldlock/<set>/plans/<plan>.json                the plan (shots, cameras, moves, blocking, approvals)
  <film>/worldlock/<set>/packages/<plan>-<n>/             a shot's package

  python -m filmcrafter_engine.directorcam <presets|place_camera|path|plan_beat|plan_save|plans|plan_get|shot_set|shot_remove|checks|preview|package|capabilities|apply|plan_remove> <film> --data '{...}'
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import sys
import time
import uuid

import numpy as np
from PIL import Image

from . import keying as K
from . import safeio
from . import vpstudio as V
from . import worldlock as WL
from . import worldmath as WM

# how much of the world is in the frame, top to bottom (metres): the height that decides how far away the camera stands
SIZES = {"extreme close-up": 0.25, "close-up": 0.5, "medium close-up": 0.8, "medium": 1.2, "medium wide": 1.8, "wide": 2.8, "establishing": 9.0}
FILM_FRAMING = {"extreme close-up": "extreme close-up", "close-up": "close-up", "medium close-up": "close-up", "medium": "medium", "medium wide": "medium", "wide": "wide", "establishing": "establishing",
                "over the shoulder": "over the shoulder", "insert": "insert", "point of view": "point of view"}
MOVES = ("static", "pan", "tilt", "dolly", "truck", "pedestal", "crane", "orbit", "tracking", "push_in", "pull_out")
FILM_MOVEMENT = {"static": "locked off", "pan": "pan", "tilt": "tilt", "dolly": "dolly", "truck": "tracking", "pedestal": "crane", "crane": "crane", "orbit": "orbit", "tracking": "tracking",
                 "push_in": "push in", "pull_out": "pull out"}
EYE = 1.6
RULES = ("line", "thirty", "eyeline", "screen_direction", "blocked", "out_of_frame", "bounds", "gap", "continuity")
MAX_SHOTS, MAX_PLANS = 16, 40
PATH_STEPS = 8


def emit(**kw) -> None:
    V.emit(**kw)


_t, _n = V._t, V._n


# ---------------------------------------------------------------- the camera and what it can do

def forward(c: dict) -> tuple[float, float, float]:
    y, p = math.radians(c.get("yaw", 0.0)), math.radians(c.get("pitch", 0.0))
    return (math.sin(y) * math.cos(p), math.sin(p), math.cos(y) * math.cos(p))


def right(c: dict) -> tuple[float, float, float]:
    y = math.radians(c.get("yaw", 0.0))
    return (math.cos(y), 0.0, -math.sin(y))


def look_at(c: dict, p: tuple[float, float, float]) -> dict:
    """The camera turned to look at a world point (yaw and pitch only; no roll)."""
    dx, dy, dz = p[0] - c["x"], p[1] - c["y"], p[2] - c["z"]
    flat = math.hypot(dx, dz)
    return {**c, "yaw": round(math.degrees(math.atan2(dx, dz)), 3), "pitch": round(max(-85.0, min(85.0, math.degrees(math.atan2(dy, flat) if flat > 1e-9 else 0.0))), 3)}


def vfov(c: dict, aspect: float) -> float:
    """The vertical field of view (degrees) from the horizontal one and the picture's shape."""
    return math.degrees(2 * math.atan(math.tan(math.radians(c["fov"]) / 2) / aspect))


def aspect_of(c: dict) -> float:
    return float(WL.ASPECTS.get(c.get("aspect", "16:9"), 16 / 9))


def _ease(t: float, how: str) -> float:
    return t * t * (3 - 2 * t) if how == "smooth" else t


def camera_path(cam: dict, move: dict, steps: int = PATH_STEPS, target: tuple[float, float, float] | None = None, follow: tuple[tuple[float, float], tuple[float, float]] | None = None) -> list[dict]:
    """The poses of a camera move, `steps + 1` of them from the start to the end. A move is {kind, amount, ease}: `amount` is metres for dolly, truck, pedestal, push-in, pull-out and crane, and degrees
    for pan, tilt and orbit (positive is right, up or counter-clockwise seen from above as stated for each). `target` is the point an orbit goes round, a crane keeps in view and a push-in or pull-out
    heads for or away from; `follow` is the start and end floor positions (x, z) of the person a tracking shot goes with. Deterministic."""
    kind = move.get("kind", "static") if move.get("kind") in MOVES else "static"
    amount = float(move.get("amount", 0.0))
    ease = move.get("ease", "smooth")
    steps = max(1, int(steps))
    out = []
    f0, r0 = forward(cam), right(cam)
    flat = math.hypot(f0[0], f0[2]) or 1.0
    fh = (f0[0] / flat, 0.0, f0[2] / flat)                                                           # the way the camera points along the floor
    for i in range(steps + 1):
        t = _ease(i / steps, ease)
        c = dict(cam)
        if kind == "pan":
            c["yaw"] = cam["yaw"] + amount * t                                                         # degrees, right is positive
        elif kind == "tilt":
            c["pitch"] = max(-85.0, min(85.0, cam["pitch"] + amount * t))                              # degrees, up is positive
        elif kind in ("dolly", "push_in", "pull_out"):
            a = abs(amount) * (-1 if kind == "pull_out" else 1) if kind != "dolly" else amount        # push in goes forward, pull out goes back, dolly goes where the sign says
            if target is not None and kind in ("push_in", "pull_out"):
                dx, dz = target[0] - cam["x"], target[2] - cam["z"]
                d = math.hypot(dx, dz) or 1.0
                c["x"], c["z"] = cam["x"] + dx / d * a * t, cam["z"] + dz / d * a * t
            else:
                c["x"], c["z"] = cam["x"] + fh[0] * a * t, cam["z"] + fh[2] * a * t
        elif kind == "truck":
            c["x"], c["z"] = cam["x"] + r0[0] * amount * t, cam["z"] + r0[2] * amount * t             # sideways: right is positive
        elif kind == "pedestal":
            c["y"] = cam["y"] + amount * t
        elif kind == "crane":
            c["y"] = cam["y"] + amount * t                                                             # up (or down) and back (or in) by half as much, keeping the subject in view
            c["x"], c["z"] = cam["x"] - fh[0] * amount * 0.5 * t, cam["z"] - fh[2] * amount * 0.5 * t
            if target is not None:
                c = look_at(c, target)
        elif kind == "orbit":
            if target is None:
                raise SystemExit("An orbit needs a point or a person to go round.")
            rx, rz = cam["x"] - target[0], cam["z"] - target[2]
            a = math.radians(amount * t)                                                               # degrees, counter-clockwise seen from above is positive
            c["x"] = target[0] + rx * math.cos(a) - rz * math.sin(a)
            c["z"] = target[2] + rx * math.sin(a) + rz * math.cos(a)
            c = look_at(c, (target[0], target[1], target[2]))
        elif kind == "tracking":
            if follow is None:
                raise SystemExit("A tracking shot needs the person it goes with.")
            (sx, sz), (ex, ez) = follow
            c["x"], c["z"] = cam["x"] + (ex - sx) * t, cam["z"] + (ez - sz) * t                       # the camera keeps its offset to the person: it goes where they go
        c["yaw"] = round(c["yaw"], 3)
        out.append({k: (round(v, 4) if isinstance(v, float) else v) for k, v in c.items()})
    return out


def place_camera(s: dict, data: dict) -> dict:
    """A camera for a shot size and a subject. `subjects` are one or two of the set's person or picture ids; `size` is one of the shot sizes (or "over the shoulder": behind the first person's shoulder,
    looking at the second); `side` (left or right, as seen from the first person toward the second) chooses which side of the line the camera is on. Returns the camera and what it is looking at."""
    pts = []
    for sid in data.get("subjects") or []:
        c = next((c for c in s["characters"] if c["id"] == sid), None)
        a = next((a for a in s["assets"] if a["id"] == sid), None)
        if c:
            pts.append({"id": sid, "name": c["name"], "x": c["x"], "z": c["z"], "h": 1.7})
        elif a:
            pts.append({"id": sid, "name": a["name"], "x": a["x"], "z": a["z"], "h": max(0.2, a["height"])})
        else:
            raise SystemExit("A subject isn't in the set.")
    if not pts:
        raise SystemExit("Choose who or what the shot is of.")
    size = data.get("size") if data.get("size") in SIZES or data.get("size") == "over the shoulder" else "medium"
    base = {"sensor_mm": 36.0, "focal_mm": 35.0, "fov": 54.43, "aspect": "16:9"}
    cam = WL._clean_camera({**base, "focal_mm": _n(data.get("focal_mm"), 8, 400, 35.0), "aspect": data.get("aspect") if data.get("aspect") in WL.ASPECTS else "16:9", "name": data.get("name") or size.title()}, None)
    side = -1 if data.get("side") == "left" else 1
    if size == "over the shoulder":
        if len(pts) < 2:
            raise SystemExit("An over-the-shoulder shot needs two people.")
        a, b = pts[0], pts[1]
        dx, dz = b["x"] - a["x"], b["z"] - a["z"]
        d = math.hypot(dx, dz) or 1.0
        ux, uz = dx / d, dz / d                                                                         # from the first person toward the second
        nx, nz = uz * side, -ux * side                                                                  # to the camera's side of that line
        cam.update(x=round(a["x"] - ux * 0.9 + nx * 0.35, 3), z=round(a["z"] - uz * 0.9 + nz * 0.35, 3), y=EYE + 0.05)
        cam = look_at(cam, (b["x"], 1.45, b["z"]))
        return {"camera": cam, "looking_at": b["name"], "framing": "over the shoulder", "because": f"Behind {a['name']}'s shoulder, looking at {b['name']}."}
    height = SIZES[size]
    cx = sum(p["x"] for p in pts) / len(pts)
    cz = sum(p["z"] for p in pts) / len(pts)
    spread = max([math.hypot(p["x"] - cx, p["z"] - cz) for p in pts] + [0.0]) * 2
    aim_y = {"extreme close-up": 1.6, "close-up": 1.5, "medium close-up": 1.4, "medium": 1.25, "medium wide": 1.0, "wide": 0.95, "establishing": 1.4}[size]
    if size == "establishing":
        aim_y = 1.5
    frame_h = max(height, spread / aspect_of(cam) * 1.15)
    dist = (frame_h / 2) / math.tan(math.radians(vfov(cam, aspect_of(cam))) / 2)
    ang = math.radians(_n(data.get("angle_deg"), -180, 180, 0.0))                                        # degrees round the subject from "in front" (0), towards the right
    cam.update(x=round(cx + math.sin(ang) * dist, 3), z=round(cz - math.cos(ang) * dist, 3), y=round(_n(data.get("height"), 0.2, 30.0, EYE), 3))
    cam = look_at(cam, (cx, aim_y if size != "establishing" else 1.5, cz))
    return {"camera": cam, "looking_at": ", ".join(p["name"] for p in pts), "framing": size, "frame_height_m": round(frame_h, 2), "distance_m": round(dist, 2),
            "because": f"{size.capitalize()}: about {frame_h:.1f} m of the set fits top to bottom, so the camera stands {dist:.1f} m away with a {cam['focal_mm']:.0f} mm lens."}


# ---------------------------------------------------------------- reading a story beat (words only)

ENTER = r"\b(enters?|entered|walks? in|arrives?|arrived|comes? in|steps? in)\b"
SEE = r"\b(sees?|saw|notices?|noticed|spots?|spotted|discovers?|looks? at|stares? at|watches|watched)\b"
RUSH = r"\b(rush(?:es|ed)?|runs?|ran|hurr(?:y|ies|ied)|dash(?:es|ed)?|race[sd]?|sprints?)\b"
WALK = r"\b(walks?|walked|goes|went|crosses|crossed|approach(?:es|ed)?|moves?|moved)\b"
TALK = r"\b(says?|said|tells?|told|asks?|asked|talks?|speaks?|replies|replied|whispers?|shouts?)\b"
FALL = r"\b(falls?|fell|spills?|spilled|drops?|dropped|knocks? over|topples?)\b"
FEEL = r"\b(cries|cried|smiles?|smiled|laughs?|laughed|gasps?|gasped|frowns?|sighs?|sighed|screams?)\b"
HELP = r"\b(helps?|helped|picks? up|grabs?|grabbed|lifts?|lifted|reaches? for|takes?)\b"


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def _find(text: str, items: list[dict]) -> list[dict]:
    """The set's items whose names (or tags) appear in the text, in the order the text names them. A name matches as whole words, so 'Cart' does not match 'carton'."""
    low = " " + " ".join(_words(text)) + " "
    hits = []
    for it in items:
        names = [it["name"].lower()] + [t.lower() for t in it.get("tags", [])]
        for nm in names:
            w = " ".join(_words(nm))
            if w and f" {w} " in low or (w.endswith("s") and f" {w[:-1]} " in low) or f" {w}s " in low:
                hits.append((low.find(" " + w.rstrip("s")), it))
                break
    return [it for _, it in sorted(hits, key=lambda x: x[0])]


def _clauses(text: str) -> list[str]:
    parts = re.split(r",|;|\band then\b|\bthen\b|\band\b(?=\s+(?:she|he|they|it|the|[A-Z]))", text, flags=re.I)
    return [p.strip() for p in parts if p and p.strip()]


def _shot(n: int, size: str, subjects: list[str], s: dict, why: list[str], title: str, *, move: dict | None = None, duration: float = 3.0, side: str | None = None, angle: float = 0.0,
          chars: list[dict] | None = None) -> dict:
    p = place_camera(s, {"subjects": subjects, "size": size, "side": side, "angle_deg": angle})
    return {"id": f"ds-{uuid.uuid4().hex[:8]}", "n": n, "title": title, "size": size, "camera": p["camera"], "move": move or {"kind": "static", "amount": 0.0, "ease": "smooth"}, "duration": duration,
            "subjects": subjects, "characters": chars or [], "because": why, "looking_at": p["looking_at"], "notes": p["because"], "allow": [], "approval": "suggested", "film_shot": None}


def plan_beat(s: dict, beat: str) -> dict:
    """A draft shot list for a story beat on this set. Free: plain word rules, no model, nothing saved. It names the people and things of the set that the sentence mentions, turns each action word into
    the shot that usually tells it (an entrance, a look, a rush, a line, a fall, a feeling), and says why. What the sentence names that the set does not have is listed as not found."""
    text = _t(beat, 600)
    if not text:
        raise SystemExit("Write the story beat first.")
    people = _find(text, s["characters"])
    things = _find(text, s["assets"])
    if not s["cameras"] and not s["characters"] and not s["assets"]:
        raise SystemExit("The set is empty: stand some pictures in it first.")
    shots: list[dict] = []
    heard: list[str] = []
    main = people[0] if people else None

    def pos(c): return {"x": c["x"], "z": c["z"], "facing": c.get("facing", 0.0)}
    est_subj = [main["id"]] if main else ([things[0]["id"]] if things else [])
    mid_b = s["world"]["bounds"]
    c0x, c0z = (mid_b["x"][0] + mid_b["x"][1]) / 2, (mid_b["z"][0] + mid_b["z"][1]) / 2
    est = place_camera(s, {"subjects": est_subj or [(s["assets"] or s["characters"])[0]["id"]], "size": "establishing"}) if (est_subj or s["assets"] or s["characters"]) else None
    if est:
        shots.append({"id": f"ds-{uuid.uuid4().hex[:8]}", "n": 1, "title": "Establish the place", "size": "establishing", "camera": est["camera"], "move": {"kind": "static", "amount": 0.0, "ease": "smooth"},
                      "duration": 3.0, "subjects": est_subj, "characters": [], "because": ["Every plan opens by showing where we are."], "looking_at": est["looking_at"], "notes": est["because"], "allow": [], "approval": "suggested", "film_shot": None})
    carried = main
    for cl in _clauses(text):
        low = cl.lower()
        pos_v = min([m.start() for m in (re.search(rx, low) for rx in (ENTER, SEE, RUSH, WALK, TALK, FALL, FEEL, HELP)) if m] or [0])
        subj, after = _find(cl[:pos_v], s["characters"]), cl[pos_v:]
        who = subj[0] if subj else carried                                                              # "she"/"the girl" named earlier carries over to a clause with no name before its verb
        carried = who or carried
        cp = [who] + [c for c in _find(after, s["characters"]) if who and c["id"] != who["id"]] if who else _find(after, s["characters"])
        ct = _find(after, s["assets"])
        if re.search(ENTER, low) and who:
            heard.append("enters")
            far = (who["x"], who["z"])
            shots.append(_shot(len(shots) + 1, "wide", [who["id"]], s, ["enters"], f"{who['name']} enters", move={"kind": "tracking", "amount": 0.0, "ease": "smooth"}, duration=4.0,
                               chars=[{"id": who["id"], "name": who["name"], "from": {"x": round(far[0] - 1.2, 2), "z": round(far[1] + 0.8, 2), "facing": who.get("facing", 0.0)}, "to": pos(who)}]))
        if re.search(SEE, low) and who:
            heard.append("sees")
            shots.append(_shot(len(shots) + 1, "close-up", [who["id"]], s, ["sees"], f"{who['name']} notices", move={"kind": "push_in", "amount": 0.4, "ease": "smooth"}, duration=2.5, chars=[{"id": who["id"], "name": who["name"], "from": pos(who), "to": pos(who)}]))
            if ct:
                shots.append(_shot(len(shots) + 1, "insert", [ct[0]["id"]], s, ["sees", f"names {ct[0]['name']}"], f"What {who['name']} sees: {ct[0]['name']}", duration=2.0))
        if re.search(FALL, low) and ct:
            heard.append("falls")
            shots.append(_shot(len(shots) + 1, "medium", [ct[0]["id"]], s, ["falls", f"names {ct[0]['name']}"], f"{ct[0]['name']} falls", duration=2.0))
        if re.search(RUSH, low) or (re.search(WALK, low) and not re.search(ENTER, low) and not re.search(SEE, low)):
            heard.append("rushes" if re.search(RUSH, low) else "walks")
            goal = (cp[1] if len(cp) > 1 else None) or (ct[0] if ct else None)
            if who:
                dest = pos(who)
                if goal:
                    dx, dz = goal["x"] - who["x"], goal["z"] - who["z"]
                    d = math.hypot(dx, dz) or 1.0
                    dest = {"x": round(goal["x"] - dx / d * 0.9, 2), "z": round(goal["z"] - dz / d * 0.9, 2), "facing": round(math.degrees(math.atan2(dx, dz)), 1)}
                shots.append(_shot(len(shots) + 1, "medium", [who["id"]], s, ["rushes" if re.search(RUSH, low) else "walks"] + ([f"to {goal['name']}"] if goal else []), f"{who['name']} {'rushes' if re.search(RUSH, low) else 'walks'}" + (f" to {goal['name']}" if goal else ""),
                                   move={"kind": "tracking", "amount": 0.0, "ease": "smooth"}, duration=3.5, chars=[{"id": who["id"], "name": who["name"], "from": pos(who), "to": dest}]))
        if re.search(HELP, low) and who and len(cp) + len(ct) >= 1:
            other = (cp[1] if len(cp) > 1 else None)
            heard.append("helps")
            if other:
                shots.append(_shot(len(shots) + 1, "over the shoulder", [who["id"], other["id"]], s, ["helps", f"with {other['name']}"], f"{who['name']} reaches {other['name']}", duration=3.0, side="right"))
        if re.search(TALK, low) and len(cp) >= 2:
            heard.append("talks")
            a, b = cp[0], cp[1]
            shots.append(_shot(len(shots) + 1, "over the shoulder", [a["id"], b["id"]], s, ["talks"], f"{a['name']} to {b['name']}", duration=3.0, side="right"))
            shots.append(_shot(len(shots) + 1, "over the shoulder", [b["id"], a["id"]], s, ["talks", "reverse"], f"{b['name']} to {a['name']}", duration=3.0, side="right"))
        if re.search(FEEL, low) and who:
            heard.append("feels")
            shots.append(_shot(len(shots) + 1, "close-up", [who["id"]], s, ["a feeling"], f"{who['name']}'s face", duration=2.5))
    if len(shots) <= 1:
        raise SystemExit("No action the planner knows (enters, sees, rushes, talks, falls, helps, a feeling) was found in that beat, or its people are not in the set. Name the people and things the way the set does.")
    for i, sh in enumerate(shots[:MAX_SHOTS], 1):
        sh["n"] = i
    sent = {w for sh in shots for w in sh["because"]}
    unresolved = [w for w in re.findall(r"\b(?:the|a|an)\s+([a-z]+)", text.lower()) if not any(w in (p["name"].lower() + " " + " ".join(p.get("tags", []))) for p in s["characters"] + s["assets"])]
    return {"beat": text, "shots": shots[:MAX_SHOTS], "people": [p["name"] for p in people], "things": [t["name"] for t in things], "actions": sorted(set(heard)),
            "not_found": sorted(set(unresolved))[:8], "note": "A draft from the words of the beat only: no model was asked and nothing is saved. Move any camera, change any shot, or delete it before you save."}


# ---------------------------------------------------------------- advice (a director may overrule every one)

def _shot_ends(s: dict, sh: dict) -> tuple[dict, dict]:
    start = dict(sh["camera"])
    path = camera_path(start, sh["move"], PATH_STEPS, target=_target(s, sh), follow=_follow(sh))
    return path[0], path[-1]


def _target(s: dict, sh: dict) -> tuple[float, float, float] | None:
    for sid in sh.get("subjects") or []:
        c = next((c for c in s["characters"] if c["id"] == sid), None)
        a = next((a for a in s["assets"] if a["id"] == sid), None)
        if c:
            return (c["x"], 1.4, c["z"])
        if a:
            return (a["x"], a["y"] + a["height"] / 2, a["z"])
    return None


def _follow(sh: dict):
    c = (sh.get("characters") or [None])[0]
    if c:
        return ((c["from"]["x"], c["from"]["z"]), (c["to"]["x"], c["to"]["z"]))
    return None


def _in_frame(p: tuple[float, float, float], cam: dict, size=(960, 540)) -> bool:
    r = WM.project(p, cam, size)
    return bool(r and -20 <= r[0] <= size[0] + 20 and -20 <= r[1] <= size[1] + 20)


def checks(d: str, s: dict, plan: dict) -> dict:
    """Advice on a plan, each item with the rule it comes from and why. A shot marked deliberate for a rule gets a note instead of a warning. Free; changes nothing."""
    items = []
    shots = plan["shots"]
    axis = s.get("axis") or []
    byc = {c["id"]: c for c in s["characters"]}

    def add(rule, sh, text, severity="warning"):
        deliberate = rule in (sh.get("allow") or [])
        items.append({"rule": rule, "shot": sh["id"], "n": sh["n"], "severity": "note" if deliberate else severity, "deliberate": deliberate, "text": text + (" (marked deliberate)" if deliberate else "")})
    prev = None
    for sh in shots:
        a, b = _shot_ends(s, sh)
        b_in = s["world"]["bounds"]
        for lab, c in (("start", a), ("end", b)):
            if not (b_in["x"][0] <= c["x"] <= b_in["x"][1] and b_in["z"][0] <= c["z"] <= b_in["z"][1]):
                add("bounds", sh, f"The camera is outside the set at the {lab} of this shot.")
                break
        for sid in sh.get("subjects") or []:
            who = byc.get(sid)
            pos = (who["x"], 1.4, who["z"]) if who else None
            if who is None:
                al = next((x for x in s["assets"] if x["id"] == sid), None)
                pos = (al["x"], al["y"] + al["height"] / 2, al["z"]) if al else None
            if pos and not (_in_frame(pos, a) or _in_frame(pos, b)):
                add("out_of_frame", sh, f"The subject of this shot is out of the frame.")
            if pos:                                                                                    # an object standing between the camera and the subject, hiding it
                for al in s["assets"]:
                    if al["id"] == sid:
                        continue
                    if al["z"] < pos[2] - 0.3 and al["z"] > a["z"] + 0.3 and al["x"] - al["width"] / 2 <= (a["x"] + (pos[0] - a["x"]) * (al["z"] - a["z"]) / max(pos[2] - a["z"], 1e-6)) <= al["x"] + al["width"] / 2 \
                            and al["y"] <= EYE + 0.1 <= al["y"] + al["height"] + 0.1 and al["height"] > 1.0 and al["width"] > 0.5:
                        add("blocked", sh, f"'{al['name']}' stands between the camera and the subject and may block the view.", "warning")
                        break
        if sh.get("characters"):
            ch = sh["characters"][0]
            if sh["size"] == "over the shoulder" and len(sh.get("subjects") or []) == 2:
                p1, p2 = byc.get(sh["subjects"][0]), byc.get(sh["subjects"][1])
                if p1 and p2:
                    want = math.degrees(math.atan2(p2["x"] - p1["x"], p2["z"] - p1["z"]))
                    off = abs((p1.get("facing", 0.0) - want + 180) % 360 - 180)
                    if off > 70:
                        add("eyeline", sh, f"{p1['name']} faces {off:.0f}° away from {p2['name']}: the eyeline will not match.", "advice")
        if prev is not None:
            pa, pb = prev
            if len(axis) == 2 and all(i in byc for i in axis):
                A, B = (byc[axis[0]]["x"], byc[axis[0]]["z"]), (byc[axis[1]]["x"], byc[axis[1]]["z"])
                s1, s2 = WM.side_of_axis(A, B, (pb["x"], pb["z"])), WM.side_of_axis(A, B, (a["x"], a["z"]))
                if s1 and s2 and s1 != s2:
                    add("line", sh, f"The camera crosses the line between {byc[axis[0]]['name']} and {byc[axis[1]]['name']} here: left and right swap on screen.")
            ang = abs((math.degrees(math.atan2(a["x"] - pb["x"], a["z"] - pb["z"])) + 180) % 360 - 180)
            same = prev_shot["size"] == sh["size"] and prev_shot.get("subjects") == sh.get("subjects") and sh["size"] not in ("establishing",)
            if same and math.hypot(a["x"] - pb["x"], a["z"] - pb["z"]) < 0.01 and abs(a["yaw"] - pb["yaw"]) < 30:
                add("thirty", sh, "This shot is nearly the same view as the one before it (same size, same subject, under 30° of change): it will feel like a jump cut. Change the angle or the size.", "advice")
            if sh.get("characters") and prev_shot.get("characters"):
                c1, c2 = prev_shot["characters"][0], sh["characters"][0]
                if c1["id"] == c2["id"]:
                    d1 = _screen_dir(pb, c1)
                    d2 = _screen_dir(a, c2)
                    if d1 and d2 and d1 != d2:
                        add("screen_direction", sh, f"{c2['name']} moves {d2} across the frame here but moved {d1} in the shot before: the direction of travel flips.")
            if prev_shot["to_state"] and sh.get("characters"):
                for c2 in sh["characters"]:
                    c1 = next((x for x in prev_shot["to_state"] if x["id"] == c2["id"]), None)
                    if c1 and math.hypot(c1["to"]["x"] - c2["from"]["x"], c1["to"]["z"] - c2["from"]["z"]) > 0.5:
                        add("continuity", sh, f"{c2['name']} ends the shot before at ({c1['to']['x']}, {c1['to']['z']}) but starts this one at ({c2['from']['x']}, {c2['from']['z']}): they jump.", "warning")
        gap_poses = camera_path(sh["camera"], sh["move"], 4, target=_target(s, sh), follow=_follow(sh))
        w = _worst_gap(d, s, gap_poses)
        if w > WL.GAP_WARN:
            add("gap", sh, f"The set does not cover everything this shot sees ({w:.0%} of the view at its worst): the camera sees past the edge of the pictures.")
        prev = (a, b)
        prev_shot = {**sh, "to_state": sh.get("characters") or []}
    return {"items": items, "ok": not any(i["severity"] == "warning" for i in items), "counts": {"warning": sum(1 for i in items if i["severity"] == "warning"), "advice": sum(1 for i in items if i["severity"] == "advice"),
                                                                                                 "note": sum(1 for i in items if i["severity"] == "note")}}


def _screen_dir(cam: dict, ch: dict) -> str | None:
    """Which way a person's move goes across the frame from this camera: left or right, or None when they hardly move across."""
    a = WM.project((ch["from"]["x"], 1.4, ch["from"]["z"]), cam, (960, 540))
    b = WM.project((ch["to"]["x"], 1.4, ch["to"]["z"]), cam, (960, 540))
    if not a or not b or abs(b[0] - a[0]) < 25:
        return None
    return "right" if b[0] > a[0] else "left"


def _worst_gap(d: str, s: dict, poses: list[dict]) -> float:
    """The largest share of the view the set does not cover, over the poses of a move (measured small, for speed)."""
    size = (240, 135)
    worst = 0.0
    for p in poses:
        _, alphas, _, _ = WL._draw(d, s, p, size, None)
        worst = max(worst, WM.uncovered(alphas, size, 0.02))
    return worst


# ---------------------------------------------------------------- plans on disk

def _pdir(d: str, sid: str) -> str:
    return V._inside(d, f"worldlock/{sid}/plans")


def _plan_path(d: str, sid: str, pid: str) -> str:
    if not isinstance(pid, str) or not pid.startswith("dp-") or not pid[3:].isalnum():
        raise SystemExit("That plan isn't in the set.")
    return os.path.join(_pdir(d, sid), pid + ".json")


def _pok(x) -> bool:
    return isinstance(x, dict) and isinstance(x.get("shots"), list)


def _load_plan(d: str, sid: str, pid: str) -> dict:
    p = safeio.read_json(_plan_path(d, sid, pid), None, check=_pok)
    if p is None:
        raise SystemExit("That plan isn't in the set.")
    p["shots"] = [x for x in p["shots"] if isinstance(x, dict)]
    return p


def _save_plan(d: str, sid: str, p: dict) -> None:
    os.makedirs(_pdir(d, sid), exist_ok=True)
    p["updated"] = time.time()
    safeio.write_json(_plan_path(d, sid, p["id"]), p)


def _clean_shot(x: dict, old: dict, s: dict) -> dict:
    sh = dict(old)
    if "title" in x:
        sh["title"] = _t(x["title"], 80) or sh["title"]
    if "size" in x:
        sh["size"] = x["size"] if x["size"] in list(SIZES) + ["over the shoulder", "insert", "point of view"] else sh["size"]
    if isinstance(x.get("camera"), dict):
        sh["camera"] = WL._clean_camera({k: v for k, v in x["camera"].items() if k != "id"}, sh["camera"])
    if isinstance(x.get("move"), dict):
        m = x["move"]
        sh["move"] = {"kind": m.get("kind") if m.get("kind") in MOVES else "static", "amount": round(_n(m.get("amount"), -360, 360, 0.0), 3), "ease": m.get("ease") if m.get("ease") in ("linear", "smooth") else "smooth"}
    if "duration" in x:
        sh["duration"] = round(_n(x["duration"], 0.5, 60, sh["duration"]), 2)
    if "subjects" in x:
        ok = {c["id"] for c in s["characters"]} | {a["id"] for a in s["assets"]}
        sh["subjects"] = [i for i in (x["subjects"] if isinstance(x["subjects"], list) else []) if i in ok][:3]
    if "characters" in x and isinstance(x["characters"], list):
        chars = []
        for c in x["characters"][:8]:
            ref = next((p for p in s["characters"] if p["id"] == c.get("id")), None)
            if not ref or not isinstance(c.get("from"), dict) or not isinstance(c.get("to"), dict):
                continue
            chars.append({"id": ref["id"], "name": ref["name"], **{k: {"x": round(_n(c[k].get("x"), -1000, 1000, ref["x"]), 3), "z": round(_n(c[k].get("z"), -1000, 1000, ref["z"]), 3),
                                                                       "facing": round(_n(c[k].get("facing"), -360, 360, 0.0), 1)} for k in ("from", "to")}})
        sh["characters"] = chars
    if "allow" in x:
        sh["allow"] = [r for r in (x["allow"] if isinstance(x["allow"], list) else []) if r in RULES]
    if "approval" in x:
        if x["approval"] not in ("suggested", "approved", "rejected"):
            raise SystemExit("Choose approved, rejected or suggested.")
        sh["approval"] = x["approval"]
    if "notes" in x:
        sh["notes"] = _t(x["notes"], 300)
    return sh


def plan_save(d: str, sid: str, data: dict) -> dict:
    """Keep a draft (from `plan_beat`) as a plan of the set. Every shot starts as a suggestion until it is approved."""
    V._film(d)
    s = WL._load(d, sid)
    draft = data.get("shots")
    if not isinstance(draft, list) or not draft:
        raise SystemExit("There are no shots to keep.")
    if len(plans(d, sid)["plans"]) >= MAX_PLANS:
        raise SystemExit(f"At most {MAX_PLANS} plans in a set.")
    shots = []
    for i, x in enumerate(draft[:MAX_SHOTS], 1):
        if not isinstance(x, dict) or not isinstance(x.get("camera"), dict):
            raise SystemExit("A shot in the draft is not complete.")
        base = {"id": f"ds-{uuid.uuid4().hex[:8]}", "n": i, "title": "Shot", "size": "medium", "camera": WL._clean_camera(x["camera"], None), "move": {"kind": "static", "amount": 0.0, "ease": "smooth"}, "duration": 3.0,
                "subjects": [], "characters": [], "because": [_t(b, 120) for b in (x.get("because") or [])][:6], "looking_at": _t(x.get("looking_at"), 120), "notes": "", "allow": [], "approval": "suggested", "film_shot": None}
        shots.append(_clean_shot({k: v for k, v in x.items() if k in ("title", "size", "move", "duration", "subjects", "characters", "notes")} | {"camera": x["camera"]}, base, s))
    pid = f"dp-{uuid.uuid4().hex[:8]}"
    p = {"schema": 1, "id": pid, "set": sid, "set_version": s.get("version", 1), "name": _t(data.get("name"), 60) or "Shot plan", "beat": _t(data.get("beat"), 600), "shots": shots, "created": time.time()}
    _save_plan(d, sid, p)
    return get_plan(d, sid, pid)


def plans(d: str, sid: str) -> dict:
    V._film(d)
    WL._load(d, sid)
    out = []
    folder = _pdir(d, sid)
    if os.path.isdir(folder):
        for n in sorted(os.listdir(folder)):
            if n.startswith("dp-") and n.endswith(".json"):
                p = safeio.read_json(os.path.join(folder, n), None, check=_pok)
                if p:
                    out.append({"id": p["id"], "name": p.get("name", ""), "beat": p.get("beat", ""), "shots": len(p["shots"]), "approved": sum(1 for x in p["shots"] if x.get("approval") == "approved"),
                                "set_version": p.get("set_version"), "updated": p.get("updated", 0)})
    return {"plans": out}


def get_plan(d: str, sid: str, pid: str) -> dict:
    """A plan with the advice on it and whether the set has changed since it was made. Free."""
    V._film(d)
    s = WL._load(d, sid)
    p = _load_plan(d, sid, pid)
    adv = checks(d, s, p)
    return {**p, "advice": adv, "set_changed": s.get("version", 1) != p.get("set_version"), "set_version_now": s.get("version", 1)}


def shot_set(d: str, sid: str, pid: str, data: dict) -> dict:
    """Change one shot of a plan: its camera, move, length, who goes where, approval, or which advice is deliberate. Only the fields given change."""
    V._film(d)
    s = WL._load(d, sid)
    p = _load_plan(d, sid, pid)
    sh = next((x for x in p["shots"] if x["id"] == data.get("shot")), None)
    if not sh:
        raise SystemExit("That shot isn't in the plan.")
    new = _clean_shot(data, sh, s)
    sh.clear()
    sh.update(new)
    if data.get("add"):
        raise SystemExit("Use plan_save to add shots.")
    _save_plan(d, sid, p)
    return get_plan(d, sid, pid)


def shot_remove(d: str, sid: str, pid: str, shot: str) -> dict:
    """Take a shot out of a plan (the rest are renumbered)."""
    V._film(d)
    p = _load_plan(d, sid, pid)
    sh = next((x for x in p["shots"] if x["id"] == shot), None)
    if not sh:
        raise SystemExit("That shot isn't in the plan.")
    p["shots"].remove(sh)
    for i, x in enumerate(p["shots"], 1):
        x["n"] = i
    p.setdefault("removed", []).append({**sh, "removed_at": time.time()})
    _save_plan(d, sid, p)
    return get_plan(d, sid, pid)


def plan_remove(d: str, sid: str, pid: str) -> dict:
    """Put a plan away: its file moves to worldlock/<set>/plans/_removed. Nothing is deleted."""
    V._film(d)
    src = _plan_path(d, sid, pid)
    if not os.path.isfile(src):
        raise SystemExit("That plan isn't in the set.")
    dst = os.path.join(_pdir(d, sid), "_removed", f"{pid}-{int(time.time())}.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.replace(src, dst)
    return plans(d, sid)


# ---------------------------------------------------------------- previews, packages and provider support

def _overrides(sh: dict, end: bool) -> dict:
    return {"characters": {c["id"]: c["to" if end else "from"] for c in sh.get("characters") or []}}


def _render_pose(d: str, sid: str, cam: dict, sh: dict, end: bool, size: tuple[int, int]) -> dict:
    return WL.render(d, sid, {"view": cam, "size": list(size), "overrides": _overrides(sh, end)})


def _size_for(cam: dict, width: int = 960) -> tuple[int, int]:
    a = aspect_of(cam)
    return width, max(64, int(round(width / a)) // 2 * 2)


def preview(d: str, sid: str, pid: str, shot: str) -> dict:
    """Render the first and last frame of a shot from the set (people at their start and end positions) and say how much of each the set does not cover. Free; makes pictures only."""
    V._film(d)
    p = _load_plan(d, sid, pid)
    sh = next((x for x in p["shots"] if x["id"] == shot), None)
    if not sh:
        raise SystemExit("That shot isn't in the plan.")
    s = WL._load(d, sid)
    path = camera_path(sh["camera"], sh["move"], PATH_STEPS, target=_target(s, sh), follow=_follow(sh))
    size = _size_for(sh["camera"])
    first = _render_pose(d, sid, path[0], sh, False, size)
    last = _render_pose(d, sid, path[-1], sh, True, size)
    return {"shot": shot, "first": first, "last": last, "path": [{k: p_[k] for k in ("x", "y", "z", "yaw", "pitch", "fov")} for p_ in path]}


def _passes(d: str, s: dict, cam: dict, sh: dict, end: bool, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Depth (metres, 0 where the set has nothing) and an object id map for one pose. Flat pictures: each object has one depth."""
    layers, _ = WL._layers_for(d, s, None, _overrides(sh, end))
    W, H = size
    depth = np.zeros((H, W), np.float32)
    seg = np.zeros((H, W), np.uint16)
    legend = []
    for a in sorted(layers, key=lambda a: -(a["z"] - cam["z"])):
        try:
            rgba = K.load_rgba(V._inside(d, a["file"]))
        except (SystemExit, OSError):
            continue
        placed = WM.draw_layer(rgba, a, cam, size)
        if placed is None:
            continue
        m = placed[..., 3] > 0.5
        depth[m] = round(WM.to_camera((a["x"], a["y"], a["z"]), cam)[2], 3)
        idx = len(legend) + 1
        seg[m] = idx
        legend.append({"index": idx, "id": a["id"], "name": a["name"]})
    return depth, seg, legend


def _palette(n: int) -> np.ndarray:
    rng = np.random.default_rng(7)
    p = rng.integers(60, 255, size=(n + 1, 3)).astype(np.uint8)
    p[0] = 0
    return p


def package(d: str, sid: str, pid: str, shot: str, data: dict) -> dict:
    """Build a shot's package in `worldlock/<set>/packages/<plan>-<n>/`: first and last frame, a strip along the camera path, depth and object maps, and `package.json` with the camera, the people's start and
    end positions, lights, continuity constraints and the motion in words. Which of them a chosen model can use is listed in `conditioning`; nothing is sent and nothing is generated."""
    V._film(d)
    s = WL._load(d, sid)
    p = _load_plan(d, sid, pid)
    sh = next((x for x in p["shots"] if x["id"] == shot), None)
    if not sh:
        raise SystemExit("That shot isn't in the plan.")
    base = V._inside(d, f"worldlock/{sid}/packages/{pid}-{sh['n']:02d}")
    os.makedirs(base, exist_ok=True)
    rel = lambda n: f"worldlock/{sid}/packages/{pid}-{sh['n']:02d}/{n}"  # noqa: E731
    path = camera_path(sh["camera"], sh["move"], PATH_STEPS, target=_target(s, sh), follow=_follow(sh))
    size = _size_for(sh["camera"])
    first, last = _render_pose(d, sid, path[0], sh, False, size), _render_pose(d, sid, path[-1], sh, True, size)
    for src, name in ((first, "first_frame.png"), (last, "last_frame.png")):
        Image.open(V._inside(d, src["file"])).save(os.path.join(base, name))
    strip_frames = [path[round(i * (len(path) - 1) / 4)] for i in range(5)]
    thumbs = []
    for i, c in enumerate(strip_frames):
        r = WL.render(d, sid, {"view": c, "size": [320, int(320 / aspect_of(sh["camera"]))], "overrides": _overrides(sh, i >= 3)})
        thumbs.append(Image.open(V._inside(d, r["file"])).convert("RGB"))
    strip = Image.new("RGB", (sum(t.width for t in thumbs), thumbs[0].height))
    x = 0
    for t in thumbs:
        strip.paste(t, (x, 0))
        x += t.width
    strip.save(os.path.join(base, "path_preview.png"))
    depth, seg, legend = _passes(d, s, path[0], sh, False, size)
    far = float(depth.max()) or 1.0
    inv = np.where(depth > 0, 1.0 - depth / (far * 1.05), 0.0)
    Image.fromarray((inv * 65535).astype(np.uint16)).save(os.path.join(base, "depth.png"))                  # 16-bit: nearer is brighter, empty is black
    Image.fromarray(_palette(len(legend))[seg]).save(os.path.join(base, "objects.png"))
    caps = capabilities(d, data.get("provider", ""), data.get("model", ""))
    refs = [a["file"] for a in s["assets"] if any(c.get("asset") == a["id"] for c in s["characters"] if c["id"] in [x["id"] for x in sh.get("characters") or []])]
    char_state = [{"id": c["id"], "name": c["name"], "start": c["from"], "end": c["to"]} for c in sh.get("characters") or []]
    constraints = [f"The camera starts at ({path[0]['x']}, {path[0]['y']}, {path[0]['z']}) and ends at ({path[-1]['x']}, {path[-1]['y']}, {path[-1]['z']}), looking at {sh.get('looking_at') or 'the subject'}."]
    constraints += [f"{c['name']} starts at ({c['start']['x']}, {c['start']['z']}) and ends at ({c['end']['x']}, {c['end']['z']})." for c in char_state]
    constraints += [f"'{a['name']}' stays at ({a['x']}, {a['z']}) in the set." for a in s["assets"] if a["kind"] != "layer"][:6]
    motion = {"static": "The camera does not move.", "pan": f"The camera pans {abs(sh['move']['amount']):.0f}° {'right' if sh['move']['amount'] >= 0 else 'left'}.", "tilt": f"The camera tilts {abs(sh['move']['amount']):.0f}° {'up' if sh['move']['amount'] >= 0 else 'down'}.",
              "dolly": f"The camera dollies {'forward' if sh['move']['amount'] >= 0 else 'back'} {abs(sh['move']['amount']):.1f} m.", "truck": f"The camera trucks {'right' if sh['move']['amount'] >= 0 else 'left'} {abs(sh['move']['amount']):.1f} m.",
              "pedestal": f"The camera rises {sh['move']['amount']:.1f} m.", "crane": f"The camera cranes up {sh['move']['amount']:.1f} m and back.", "orbit": f"The camera orbits {abs(sh['move']['amount']):.0f}° around the subject.",
              "tracking": "The camera tracks alongside the person as they move.", "push_in": f"The camera pushes in {abs(sh['move']['amount']):.1f} m.", "pull_out": f"The camera pulls out {abs(sh['move']['amount']):.1f} m."}[sh["move"]["kind"]]
    meta = {"plan": pid, "shot": sh["id"], "n": sh["n"], "title": sh["title"], "set": {"id": sid, "name": s["name"], "version": s.get("version", 1)}, "camera": {k: sh["camera"].get(k) for k in ("x", "y", "z", "yaw", "pitch", "fov", "focal_mm", "sensor_mm", "aperture", "aspect", "focus")},
            "camera_end": {k: path[-1][k] for k in ("x", "y", "z", "yaw", "pitch")}, "move": sh["move"], "motion_words": motion, "duration": sh["duration"], "size": sh["size"], "characters": char_state,
            "props": [{"id": a["id"], "name": a["name"], "x": a["x"], "y": a["y"], "z": a["z"]} for a in s["assets"] if a["kind"] != "layer"], "lights": s["lights"], "environment": s["environment"],
            "constraints": constraints, "files": {k: rel(v) for k, v in {"first_frame": "first_frame.png", "last_frame": "last_frame.png", "path_preview": "path_preview.png", "depth": "depth.png", "objects": "objects.png"}.items()},
            "objects": legend, "character_references": refs, "conditioning": caps["conditioning"], "frame_gap": {"first": first["uncovered"], "last": last["uncovered"]},
            "note": "Made from the set by projection. A video or picture made from this is NOT guaranteed to match it: use the package as the reference to check the result against.", "made": time.time()}
    safeio.write_json(os.path.join(base, "package.json"), meta, backup=False)
    return {"shot": sh["id"], "folder": base, "relative": f"worldlock/{sid}/packages/{pid}-{sh['n']:02d}", "files": meta["files"], "conditioning": caps["conditioning"], "frame_gap": meta["frame_gap"], "motion_words": motion}


def capabilities(d: str, provider: str, model: str) -> dict:
    """Which of a shot package's inputs a model can take, as far as this app knows. Each answer says how it is known: documented (the model's own cached schema or the app's own list) or unknown. Nothing is
    assumed: a model that is not known to take a last frame is not offered one, and the plain alternative is given."""
    from . import compose
    prov, mod = _t(provider, 40), _t(model, 120)
    if prov and mod:
        try:
            last = bool(compose._takes_end(prov, mod))
        except Exception:                                                                                    # noqa: BLE001  a damaged cache must not stop a package
            last = False
        refs = bool(compose.REFS_RX.search(mod))
    else:
        last, refs = None, None

    def row(key, label, known, why, alt):
        status = "unknown" if known is None else ("supported" if known else "not supported")
        return {"input": key, "label": label, "status": status, "why": why, "alternative": "" if known else alt}
    named = f"{prov}/{mod}" if prov and mod else "no model chosen"
    return {"model": named, "conditioning": [
        row("first_frame", "First-frame render", None if not (prov and mod) else True, "Image-to-video models start from a picture; this one was not checked for this model.", "Use the first-frame render as the shot's keyframe."),
        row("last_frame", "Last-frame render", last, "From the model's cached schema or the app's list of models documented to take an end frame.", "Make the shot in two parts, or use the last frame as the next shot's first frame."),
        row("references", "Reference pictures (the set's people)", refs, "From the model's name, as the app's pickers do.", "Describe the person in words; use the picture as the keyframe."),
        row("camera_path", "Camera path", False, "No model here accepts a camera path as data. The motion is given in words and is approximate: check the result against the path strip.", "Use the motion words and the path strip; or make the move in the set (a rendered path preview) and use it as a reference."),
        row("depth", "Depth map", False, "No model in this app takes a depth map. It is kept for ComfyUI workflows that do, and for checking.", "Kept as a file in the package."),
        row("objects", "Object map", False, "No model in this app takes a segmentation map. It is kept for checking.", "Kept as a file in the package.")]}


# ---------------------------------------------------------------- into the film's own shots

def apply(d: str, sid: str, pid: str, data: dict) -> dict:
    """Give a film shot the camera of a planned shot: its framing, angle, lens, movement and a line saying where the camera stands in the set, and attach the first-frame render to it as a reference. This is
    the person's decision (a locked storyboard refuses, as it always does). The plan keeps the link."""
    V._film(d)
    from . import shots as S
    s = WL._load(d, sid)
    p = _load_plan(d, sid, pid)
    sh = next((x for x in p["shots"] if x["id"] == data.get("shot")), None)
    if not sh:
        raise SystemExit("That shot isn't in the plan.")
    film_shot = str(data.get("film_shot") or "")
    if film_shot not in WL._shot_ids(d):
        raise SystemExit("Choose a shot in this film.")
    pk = package(d, sid, pid, sh["id"], data)
    cam = sh["camera"]
    angle = "low" if cam["pitch"] > 12 and cam["y"] < 1.2 else "high" if cam["y"] > 3 or cam["pitch"] < -15 else "eye level"
    f = cam.get("focal_mm", 35.0)
    lens = "wide (24mm)" if f <= 28 else "normal (35mm)" if f <= 40 else "portrait (50mm)" if f <= 70 else "telephoto (85mm+)"
    cur = next((c for c in S.view(d)["shots"] if c["id"] == film_shot), None)
    contract = S._contract(d, film_shot)
    refs = list(dict.fromkeys(list(contract.get("reference_assets") or []) + [pk["files"]["first_frame"]]))[:20]
    S.set_fields(d, film_shot, {"camera": {"framing": FILM_FRAMING.get(sh["size"], "medium"), "angle": angle, "lens": lens, "movement": FILM_MOVEMENT[sh["move"]["kind"]],
                                           "position": f"In the set '{s['name']}' at ({cam['x']}, {cam['y']}, {cam['z']}) m, looking at {sh.get('looking_at') or 'the subject'}.",
                                           "why": "; ".join(sh.get("because") or [])[:200]}, "reference_assets": refs})
    sh["film_shot"] = film_shot
    _save_plan(d, sid, p)
    return {"plan": get_plan(d, sid, pid), "package": pk, "film_shot": film_shot, "applied": {"framing": FILM_FRAMING.get(sh["size"], "medium"), "angle": angle, "lens": lens, "movement": FILM_MOVEMENT[sh["move"]["kind"]]}, "was": bool(cur)}


# ---------------------------------------------------------------- the rest of the actions

def presets() -> dict:
    return {"sizes": [{"id": k, "frame_height_m": v} for k, v in SIZES.items()] + [{"id": "over the shoulder", "frame_height_m": None}], "moves": list(MOVES), "rules": list(RULES), "aspects": list(WL.ASPECTS),
            "lenses": [{"focal_mm": f, "name": n} for f, n in ((18, "ultra wide"), (24, "wide"), (35, "normal"), (50, "portrait"), (85, "telephoto"), (135, "long"))]}


def path_action(d: str, sid: str, data: dict) -> dict:
    """The poses of a camera move on a set, and the gap measured at each. `camera` is a saved camera id or an inline camera; `target` a person or picture id (for an orbit, crane, push-in)."""
    V._film(d)
    s = WL._load(d, sid)
    cam = WL._camera_from(s, data)
    tgt = None
    if data.get("target"):
        tgt = _target(s, {"subjects": [data["target"]]})
        if tgt is None:
            raise SystemExit("That target isn't in the set.")
    follow = None
    if isinstance(data.get("follow"), dict):
        f = data["follow"]
        follow = ((_n(f.get("from_x"), -1000, 1000, 0), _n(f.get("from_z"), -1000, 1000, 0)), (_n(f.get("to_x"), -1000, 1000, 0), _n(f.get("to_z"), -1000, 1000, 0)))
    poses = camera_path(cam, data.get("move") or {}, int(_n(data.get("steps"), 1, 40, PATH_STEPS)), target=tgt, follow=follow)
    size = (240, 135)
    rows = []
    for i, c in enumerate(poses):
        _, alphas, _, _ = WL._draw(d, s, c, size, None)
        rows.append({"i": i, **{k: c[k] for k in ("x", "y", "z", "yaw", "pitch", "fov")}, "uncovered": round(WM.uncovered(alphas, size, 0.02), 4)})
    worst = max(rows, key=lambda r: r["uncovered"])
    return {"poses": rows, "worst": worst, "ok": worst["uncovered"] <= WL.GAP_WARN, "warning": "" if worst["uncovered"] <= WL.GAP_WARN else f"This move shows a gap of {worst['uncovered']:.0%} of the view at step {worst['i']}: the set does not cover where the camera goes."}


def place_action(d: str, sid: str, data: dict) -> dict:
    V._film(d)
    return place_camera(WL._load(d, sid), data)


def plan_beat_action(d: str, sid: str, data: dict) -> dict:
    V._film(d)
    return plan_beat(WL._load(d, sid), data.get("beat", ""))


def checks_action(d: str, sid: str, pid: str) -> dict:
    V._film(d)
    s = WL._load(d, sid)
    return checks(d, s, _load_plan(d, sid, pid))


# ---------------------------------------------------------------- command line

def clip(d: str, sid: str, pid: str, shot: str, data: dict) -> dict:
    """Make a short video of a planned shot: the camera travels along the shot's move for the shot's duration, drawn from the set. `renderer` is "builtin" (FilmCrafter's own, fast) or "blender" (Blender's, with
    real shadows; needs Blender). The set is not changed. People (2.5D characters) stand where the shot starts; only the camera and the set's 3D models, lights and sky are as the set has them. Free and local."""
    V._film(d)
    p = _load_plan(d, sid, pid)
    sh = next((x for x in p["shots"] if x["id"] == shot), None)
    if not sh:
        raise SystemExit("That shot isn't in the plan.")
    s = WL._load(d, sid)
    path = camera_path(sh["camera"], sh["move"], 24, target=_target(s, sh), follow=_follow(sh))
    secs = max(0.5, min(30.0, float(sh.get("duration", 3.0))))
    w = int(max(160, min(1920, float(data.get("width", 960))))) // 2 * 2
    size = _size_for(sh["camera"], w)
    keys = [{"t": round(secs * i / (len(path) - 1), 4), "x": q["x"], "y": q["y"], "z": q["z"], "yaw": q["yaw"], "pitch": q["pitch"], "fov": q["fov"], "ease": "linear"} for i, q in enumerate(path)]
    spec = {"fps": 24, "seconds": secs, "size": list(size), "camera": keys, "name": f"{pid}-{shot}"}
    renderer = "blender" if data.get("renderer") == "blender" else "builtin"
    if renderer == "blender":
        from . import blenderbridge as BB
        r = BB.render_animation(d, sid, spec, workers=int(data.get("workers", 4)), samples=int(data.get("samples", 16)))
    else:
        from . import worldanim as WA
        r = WA.render_sequence(d, sid, spec, workers=int(data.get("workers", 4)))
        r["renderer"] = "FilmCrafter"
    return {"shot": shot, "renderer": r["renderer"], "file": r["file"], "seconds": secs, "frames": r["frames"], "size": list(size), "took": r["took"], "people_note": "People stand where the shot starts." if sh.get("characters") else ""}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["presets", "place_camera", "path", "plan_beat", "plan_save", "plans", "plan_get", "shot_set", "shot_remove", "checks", "preview", "package", "capabilities", "apply", "plan_remove", "clip"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        sid, pid = x.get("set", ""), x.get("plan", "")
        table = {"presets": lambda: presets(), "place_camera": lambda: place_action(d, sid, x), "path": lambda: path_action(d, sid, x), "plan_beat": lambda: plan_beat_action(d, sid, x),
                 "plan_save": lambda: plan_save(d, sid, x), "plans": lambda: plans(d, sid), "plan_get": lambda: get_plan(d, sid, pid), "shot_set": lambda: shot_set(d, sid, pid, x),
                 "shot_remove": lambda: shot_remove(d, sid, pid, x.get("shot", "")), "checks": lambda: checks_action(d, sid, pid), "preview": lambda: preview(d, sid, pid, x.get("shot", "")),
                 "package": lambda: package(d, sid, pid, x.get("shot", ""), x), "capabilities": lambda: capabilities(d, x.get("provider", ""), x.get("model", "")), "apply": lambda: apply(d, sid, pid, x),
                 "plan_remove": lambda: plan_remove(d, sid, pid), "clip": lambda: clip(d, sid, pid, x.get("shot", ""), x)}
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
