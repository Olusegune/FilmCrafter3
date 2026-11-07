"""The continuity inspector for a WorldLock set: what is where, in every shot, and what a viewer might see go wrong from one shot to the next.

Everything it says about the set is worked out from the set's own data (deterministic): the set as built, the events that change it from shot to shot, and the camera each shot uses. Nothing is guessed from pictures.
The checks, each with a stable key so a finding can be marked deliberate and stay marked:

  * `unseen_change`   something changes during a shot whose camera does not show it, while a shot beside it does (the change happens off screen)
  * `appears` / `vanishes`   something arrives or leaves where the camera was not looking, between two shots that show the set
  * `reversed` a person faces one way on screen in one shot and the other way in the next
  * `out_of_frame`   a person the film's shot names is in the set but not in the shot's camera view
  * `not_in_set`     a person the film's shot names is not in the set at all
  * `empty_view`     the shot's camera sees nothing of the set (it may be turned away)
  * `conflict`       two events say different things about the same thing at the same moment, or remove something already gone
  * the checks WorldLock already makes (missing pictures, things outside the set, events about nothing, the camera crossing the line between two people)

A finding can be marked **deliberate** with a note (a manual override); that is kept beside the set (`continuity_overrides.json`) and never changes the set. `compare` is the only place pictures are looked at: it sets a picture
(a generated shot, say) beside the set's own view of the same shot and shows where they differ. That is advice, never proof: a generated picture is not expected to match a set pixel for pixel, and the numbers are
reported with that uncertainty in words. Free and local; nothing is sent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np
from PIL import Image

from . import safeio
from . import shots as S
from . import vpstudio as V
from . import worldlock as WL
from . import worldmath as WM

SAME_SPOT = 0.05          # metres: a thing that moved less than this has not moved
SIZE = (960, 540)


def emit(**kw) -> None:
    V.emit(**kw)


def _key(*parts) -> str:
    return "ck-" + hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8"), usedforsecurity=False).hexdigest()[:10]


def _ofile(d: str, sid: str) -> str:
    return V._inside(d, f"worldlock/{sid}/continuity_overrides.json")


def _overrides(d: str, sid: str) -> dict:
    p = _ofile(d, sid)
    x = safeio.read_json(p, {}) if os.path.isfile(p) else {}
    return x if isinstance(x, dict) else {}


def _in_frame(p: tuple[float, float, float], cam: dict) -> bool:
    q = WM.project(p, cam, SIZE)
    return bool(q and 0 <= q[0] <= SIZE[0] and 0 <= q[1] <= SIZE[1])


def _centre(item: dict, kind: str) -> tuple[float, float, float]:
    if kind == "asset":
        return (item["x"], item["y"] + item.get("height", 1.0) / 2, item["z"])
    return (item["x"], 1.2, item["z"])


def names_of(s: dict, who: str) -> str:
    return next((x["name"] for x in s["assets"] + s["characters"] if x["id"] == who), "Something")


def _moved(a: dict, b: dict) -> bool:
    return abs(a["x"] - b["x"]) > SAME_SPOT or abs(a["z"] - b["z"]) > SAME_SPOT or abs(a.get("y", 0) - b.get("y", 0)) > SAME_SPOT


def _screen_side(item: dict, cam: dict) -> int:
    """Which way a person faces on screen: +1 to the right, -1 to the left, 0 toward or away from the camera (no clear direction). Facing 0 is toward +z, 90 toward +x, as in the set."""
    f = np.radians(float(item.get("facing", 0.0)))
    wx, wz = np.sin(f), np.cos(f)
    yaw = np.radians(float(cam.get("yaw", 0.0)))
    cx = wx * np.cos(yaw) - wz * np.sin(yaw)                 # the facing direction in the camera's own right/forward frame
    cz = wx * np.sin(yaw) + wz * np.cos(yaw)
    if abs(cx) < 0.35:
        return 0
    return 1 if cx > 0 else -1


def inspect(d: str, sid: str) -> dict:
    """The set shot by shot, and the findings. Changes nothing."""
    V._film(d)
    s = WL._load(d, sid)
    order = WL._order_for(d)
    film_shots = {x["id"]: x for x in S.view(d)["shots"]}
    cams = {c["id"]: c for c in s["cameras"]}
    by_shot = {x["shot"]: x["camera"] for x in s["shots"] if x.get("camera") in cams}
    ov = _overrides(d, sid)
    timeline, findings = [], []
    prev = None

    def add(kind: str, sev: str, shots: list[str], thing: str, text: str):
        k = _key(kind, thing, *shots)
        o = ov.get(k)
        findings.append({"key": k, "kind": kind, "severity": sev, "shots": shots, "thing": thing, "text": text, "overridden": bool(o), "note": (o or {}).get("note", "")})

    for sh in order:
        assets, chars = WM.state_at(s["assets"], s["characters"], s["events"], order, sh)
        # state at the END of the shot: events of this shot applied (state_at applies earlier shots only)
        nxt = order[order.index(sh) + 1] if order.index(sh) + 1 < len(order) else None
        cam = cams.get(by_shot.get(sh, ""))
        things = []
        for kind, pool in (("asset", assets), ("character", chars)):
            for it in pool:
                inframe = _in_frame(_centre(it, kind), cam) if cam else None
                things.append({"id": it["id"], "kind": kind, "name": it["name"], "x": it["x"], "y": it.get("y", 0.0), "z": it["z"], "facing": it.get("facing"), "state": it.get("state", ""), "in_frame": inframe})
        evs = [e for e in s["events"] if e.get("shot") == sh]
        names = {x["id"]: x["name"] for x in s["assets"] + s["characters"]}
        changes = [f"{names.get(e.get('asset') or e.get('character'), '?')}: " + (e.get("state") or {"remove": "leaves", "appear": "appears", "move": "moves"}.get(e.get("kind"), e.get("kind", ""))) for e in evs]
        row = {"shot": sh, "camera": ({"id": cam["id"], "name": cam["name"]} if cam else None), "things": things, "events": changes}
        timeline.append(row)

        # ---- the film shot's own people against the set
        fs = film_shots.get(sh) or {}
        for nm in fs.get("characters") or []:
            c = next((c for c in chars if c["name"].lower() == str(nm).lower()), None)
            if c is None:
                if any(x["name"].lower() == str(nm).lower() for x in s["characters"]):
                    add("not_in_set", "advice", [sh], nm, f"{nm} is in shot {sh} but has left the set by then (an event removes them).")
                else:
                    add("not_in_set", "note", [sh], nm, f"{nm} is in shot {sh} but is not a character of this set.")
            elif cam and not _in_frame(_centre(c, "character"), cam):
                add("out_of_frame", "advice", [sh], c["id"], f"{nm} is in shot {sh}, but camera '{cam['name']}' does not have them in view.")
        if cam and not any(t["in_frame"] for t in things) and not s["models"]:
            add("empty_view", "warning", [sh], cam["id"], f"Camera '{cam['name']}' sees nothing of the set in shot {sh}: it may be turned away or too close.")

        # ---- from the previous shot to this one
        if prev:
            psh, pcam, pthings = prev
            pm = {t["id"]: t for t in pthings}
            cm = {t["id"]: t for t in things}
            if pcam is not None and cam is not None:
                for tid, t in cm.items():
                    p = pm.get(tid)
                    if t["kind"] != "character" or p is None or not p["in_frame"] or not t["in_frame"]:
                        continue
                    a, b = _screen_side({**p}, pcam), _screen_side({**t}, cam)
                    if a and b and a != b and abs(float(p.get("facing", 0)) - float(t.get("facing", 0))) < 1.0:
                        add("reversed", "warning", [psh, sh], tid, f"{t['name']} faces {'right' if a > 0 else 'left'} on screen in shot {psh} and {'right' if b > 0 else 'left'} in shot {sh}, though they have not turned: screen direction is reversed.")
        prev = (sh, cam, things)

    # ---- changes that happen where the camera does not look
    rows = {t["shot"]: i for i, t in enumerate(timeline)}
    for e in s["events"]:
        i = rows.get(e.get("shot"))
        who = e.get("asset") or e.get("character")
        if i is None or not who:
            continue
        here = next((t for t in timeline[i]["things"] if t["id"] == who), None)
        before = next((t for t in timeline[i - 1]["things"] if t["id"] == who), None) if i > 0 else None
        after = next((t for t in timeline[i + 1]["things"] if t["id"] == who), None) if i + 1 < len(timeline) else None
        seen = bool(here and here["in_frame"])
        name = names_of(s, who)
        shots2 = [timeline[i]["shot"]]
        if seen:
            continue
        was_seen = bool(before and before["in_frame"])
        will_be = bool(after and after["in_frame"])
        if e.get("kind") == "remove" and was_seen:
            add("vanishes", "warning", [timeline[i - 1]["shot"], timeline[i]["shot"]], who, f"{name} is in view in shot {timeline[i - 1]['shot']} and is gone from shot {timeline[i]['shot']} on, without being seen to leave.")
        elif e.get("kind") == "appear" and will_be:
            add("appears", "warning", [timeline[i]["shot"], timeline[i + 1]["shot"]], who, f"{name} is in view in shot {timeline[i + 1]['shot']} but was not in the set before, and its arrival is not in view in shot {timeline[i]['shot']}.")
        elif e.get("kind") in ("move", "appear", "remove") and (was_seen or will_be):
            add("unseen_change", "advice", shots2, who, f"{name} changes during shot {timeline[i]['shot']} ({e.get('state') or e.get('kind')}), but that shot's camera does not show it, while a shot beside it does: the change happens off screen.")

    # ---- conflicting events
    seen: dict = {}
    gone: dict = {}
    for e in sorted(s["events"], key=lambda e: (order.index(e["shot"]) if e.get("shot") in order else 1 << 20, e.get("order", 0))):
        who = e.get("asset") or e.get("character")
        slot = (who, e.get("shot"), e.get("order", 0))
        sig = (e.get("kind"), json.dumps(e.get("to", {}), sort_keys=True), e.get("state", ""))
        if slot in seen and seen[slot] != sig:
            add("conflict", "warning", [e.get("shot")], who, f"Two events at shot {e.get('shot')} say different things about the same thing at the same moment.")
        seen[slot] = sig
        if e.get("kind") == "remove":
            if gone.get(who):
                add("conflict", "advice", [e.get("shot")], who, f"An event at shot {e.get('shot')} removes something that is already gone.")
            gone[who] = True
        elif e.get("kind") == "appear":
            gone[who] = False

    parked = {c.get("asset") for c in s["characters"] if c.get("asset")}                 # a picture that draws a person is parked off to the side on purpose
    for i in WL.check(d, sid)["issues"]:
        if i["kind"] == "outside" and i["id"] in parked:
            continue
        add("set_" + i["kind"], "warning" if i["kind"] in ("crossed_line", "missing_picture") else "advice", [i["id"]] if i["kind"] == "crossed_line" else [], i["id"], i["text"])

    rank = {"warning": 0, "advice": 1, "note": 2}
    findings.sort(key=lambda f: (f["overridden"], rank[f["severity"]], f["shots"]))
    live = [f for f in findings if not f["overridden"]]
    return {"timeline": timeline, "findings": findings, "counts": {"warning": sum(f["severity"] == "warning" for f in live), "advice": sum(f["severity"] == "advice" for f in live), "note": sum(f["severity"] == "note" for f in live),
                                                                    "deliberate": len(findings) - len(live)}, "shots_without_camera": [t["shot"] for t in timeline if not t["camera"]],
            "basis": "Worked out from the set's own data (positions, events and cameras). No picture is read."}


def override(d: str, sid: str, key: str, note: str = "", on: bool = True) -> dict:
    """Mark a finding deliberate (with a note), or take the mark off. Kept beside the set; the set is not changed."""
    V._film(d)
    WL._load(d, sid)
    if not isinstance(key, str) or not key.startswith("ck-") or len(key) != 13 or not all(c in "0123456789abcdef" for c in key[3:]):
        raise SystemExit("That is not a finding of this set.")
    o = _overrides(d, sid)
    if on:
        o[key] = {"note": V._t(note, 300), "at": time.time()}
    else:
        o.pop(key, None)
    os.makedirs(os.path.dirname(_ofile(d, sid)), exist_ok=True)
    safeio.write_json(_ofile(d, sid), o, backup=False)
    return inspect(d, sid)


def compare(d: str, sid: str, shot: str, picture: str) -> dict:
    """The set's own view of a shot beside a picture of that shot (a generated keyframe, say) and a map of where they differ, as a picture in the film folder. Advisory: the numbers say how alike the two are, in words
    that keep the uncertainty. The picture is opened read-only and never altered."""
    V._film(d)
    s = WL._load(d, sid)
    cam_id = next((x["camera"] for x in s["shots"] if x["shot"] == shot), None)
    if not cam_id:
        raise SystemExit("That shot has no camera in the set: give it one first.")
    src = str(picture or "")
    full = src if os.path.isabs(src) else V._inside(d, src)
    if os.path.splitext(full)[1].lower() not in V.EXTS or not os.path.isfile(full):
        raise SystemExit("Choose a picture file (PNG, JPG, WebP).")
    if os.path.getsize(full) > V.MAX_FILE:
        raise SystemExit("That file is larger than 120 MB.")
    try:
        with Image.open(full) as im0:
            im0.verify()
        theirs = Image.open(full).convert("RGB")
    except Exception:
        raise SystemExit("That file could not be read as a picture.")
    r = WL.render(d, sid, {"camera": cam_id, "shot": shot, "size": [480, 270]})
    mine = Image.open(V._inside(d, r["file"])).convert("RGB")
    theirs = theirs.resize(mine.size, Image.LANCZOS)
    a = np.asarray(mine, dtype=np.float32) / 255.0
    b = np.asarray(theirs, dtype=np.float32) / 255.0
    diff = np.abs(a - b).mean(axis=2)
    ga, gb = a.mean(axis=2), b.mean(axis=2)
    ga_s = np.asarray(Image.fromarray((ga * 255).astype(np.uint8)).resize((48, 27), Image.BILINEAR), dtype=np.float32)
    gb_s = np.asarray(Image.fromarray((gb * 255).astype(np.uint8)).resize((48, 27), Image.BILINEAR), dtype=np.float32)
    corr = float(np.corrcoef(ga_s.ravel(), gb_s.ravel())[0, 1]) if ga_s.std() > 1e-6 and gb_s.std() > 1e-6 else 0.0
    mean_diff = float(diff.mean())
    cells = []
    H, W = diff.shape
    for gy in range(3):
        for gx in range(3):
            cells.append(round(float(diff[gy * H // 3:(gy + 1) * H // 3, gx * W // 3:(gx + 1) * W // 3].mean()), 3))
    heat = np.zeros((H, W, 3), dtype=np.uint8)
    t = np.clip(diff * 3.0, 0, 1)
    heat[..., 0] = (t * 255).astype(np.uint8)
    heat[..., 1] = ((1 - np.abs(t - 0.5) * 2) * 160).astype(np.uint8)
    out = Image.new("RGB", (W * 3, H))
    out.paste(mine, (0, 0)); out.paste(theirs, (W, 0)); out.paste(Image.fromarray(heat), (2 * W, 0))
    rel = f"worldlock/{sid}/continuity/{shot}-{int(time.time() * 1000)}.png"
    fp = V._inside(d, rel)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    out.save(fp)
    layout = ("The broad layout of the two pictures is alike." if corr >= 0.6 else "The broad layout is only partly alike." if corr >= 0.3 else "The broad layout is quite different.")
    worst = max(range(9), key=lambda i: cells[i])
    where = ["top left", "top", "top right", "left", "middle", "right", "bottom left", "bottom", "bottom right"][worst]
    return {"file": rel, "shot": shot, "layout_match": round(corr, 3), "mean_difference": round(mean_diff, 3), "cells": cells, "most_different": where, "uncovered": r.get("uncovered", 0.0),
            "words": f"{layout} The picture differs most in the {where}.",
            "note": "Advisory only. A generated picture is not expected to match the set pixel for pixel; colour, style and detail will differ. Look at the layout: where things stand and which way they face."}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["inspect", "override", "compare"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        d, sid = os.path.abspath(a.target), str(x.get("set", ""))
        table = {"inspect": lambda: inspect(d, sid), "override": lambda: override(d, sid, x.get("key", ""), x.get("note", ""), bool(x.get("on", True))), "compare": lambda: compare(d, sid, str(x.get("shot", "")), x.get("picture", ""))}
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
