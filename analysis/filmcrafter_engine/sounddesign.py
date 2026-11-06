"""Sound design for a scene: the soundscape of each place, and the few Foley sounds a shot really needs.

Two things the sound plan (`audiocues`) did not know about:

* **A soundscape profile per place.** Each environment in the Production Bible can say whether it is inside or outside, the weather, the time of day, the room, its materials and surfaces, and the
  layers of ambience it always has (rain on the roof, a generator far away, a cooking pot near), each at a distance. The profile belongs to the *place*, not to a shot, so a scene's ambience is one
  scene-wide cue per layer: the camera moving from shot to shot does not change what the place sounds like.
* **Foley events.** A Foley event is one motivated sound: which thing, what it does, what it is made of, what it lands on, where it is, how hard, how far, and which sound from the library covers it.
  `suggest` reads a shot's written action (free, no AI, nothing saved) and proposes only sounds the action actually names (a drop, a slam, a stir, a step), at most a few per shot, most dramatic
  first, each with the words that motivated it. Quiet movement that is not named gets no sound.

Events and layers are *plans*. `to_cues` turns the approved ones that have a sound into ordinary audio cues (`audiocues`), so the existing mixer, ducking and loudness apply, and changing one event
changes only its own cue. Distance becomes a level (near 0 dB, mid -6 dB, far -14 dB) and left/centre/right becomes a stereo balance. That is a stereo balance and a level, **not** an acoustic
simulation: nothing models rooms, occlusion or reflections, and a profile's reverb is a note for you and for sound generation, which the mixer does not apply yet.

  <film>/audio/sounddesign.json   { profiles: { <environment id>: profile }, events: [...], removed: [...] }   (written with safeio; nothing is deleted: a removed event moves to `removed`)

  python -m filmcrafter_engine.sounddesign <scene|profile_set|suggest|event_add|event_update|event_remove|candidates|to_cues> <film> --data '{...}'
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid

from . import audiocues as Q
from . import audiolib as AL
from . import bible as B
from . import safeio

ID = re.compile(r"^(?:fx|ly)-[0-9a-f]{8}$")
DISTANCES = {"near": 0.0, "mid": -6.0, "far": -14.0}               # dB below the sound's own level
SIDES = {"left": -0.6, "centre": 0.0, "right": 0.6}
ROOMS = ("", "small", "medium", "large", "open")
REVERBS = ("", "dry", "room", "hall", "street", "outdoor")
APPROVALS = ("suggested", "approved", "rejected")
MAX_EVENTS_PER_SHOT = 6
MAX_LAYERS = 12
KEEP_REMOVED = 200
NOTE = 400

# what the written action can name -> (words found, action, priority, default object)
VERBS: list[tuple[str, str, int, str]] = [
    (r"\b(?:slams?|slammed|crash(?:es|ed)?|smash(?:es|ed)?|shatters?|shattered|breaks?|broke|bangs?)\b", "impact (hard)", 5, ""),
    (r"\b(?:drops?|dropped|falls?|fell|spill(?:s|ed)?|topples?|knocks? over)\b", "impact", 4, ""),
    (r"\bdoors?\b", "door", 3, "door"),
    (r"\b(?:scrapes?|drags?|dragged)\b", "scrape", 3, ""),
    (r"\b(?:stirs?|stirred|stirring)\b", "stirring", 2, ""),
    (r"\b(?:pours?|poured|pouring)\b", "pouring", 2, ""),
    (r"\b(?:runs?|ran|rush(?:es|ed)?|dash(?:es|ed)?|sprints?)\b", "running footsteps", 2, "feet"),
    (r"\b(?:walks?|walked|steps?|stepped|strides?|enters?|entered|exits?|crosses|crossed|approach(?:es|ed)?)\b", "footsteps", 1, "feet"),
    (r"\b(?:grabs?|grabbed|grips?|gripped|lifts?|lifted|carries|carried|picks? up)\b", "handling", 1, ""),
]
MATERIALS = [("metal", r"\b(?:pot|pan|tin|metal|iron|steel|spoon|bucket|can)\b"), ("wood", r"\b(?:wood|wooden|table|chair|door|crate|floorboards?)\b"), ("glass", r"\b(?:glass|bottle|window|jar)\b"),
             ("fabric", r"\b(?:cloth|coat|dress|umbrella|sheet|curtain|shirt|fabric)\b"), ("water", r"\b(?:water|rain|puddles?|wet|soup|tea)\b"), ("stone", r"\b(?:stone|pavement|concrete|brick|tiles?|cobbles?)\b"),
             ("fruit", r"\b(?:oranges?|apples?|mango(?:es)?|fruit|yams?|tomato(?:es)?)\b"), ("basket", r"\b(?:basket|wicker)\b")]
SURFACES = r"\b(?:wet pavement|pavement|concrete|gravel|mud|grass|wooden floor|floorboards?|tiles?|carpet|stairs?|sand|puddles?|dirt|stone|metal floor)\b"
STOP = {"a", "an", "the", "his", "her", "their", "its", "some", "of", "on", "in", "at", "to", "and", "with", "from", "onto", "into", "across"}


def emit(**kw) -> None:
    try:
        print(json.dumps(kw, ensure_ascii=False), flush=True)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- cleaning (everything comes from the screen)

def _t(v, limit: int) -> str:
    return " ".join(str(v if v is not None else "").replace("\x00", "").split())[:limit]


def _n(v, lo: float, hi: float, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return min(hi, max(lo, x))


def _list(v, n: int, each: int) -> list[str]:
    out = []
    for x in (v if isinstance(v, list) else [])[: n * 2]:
        s = _t(x, each).lower()
        if s and s not in out:
            out.append(s)
    return out[:n]


def clean_profile(raw: dict | None, old: dict | None = None, assets: set | None = None) -> dict:
    """A soundscape profile made only of what is allowed. A layer keeps its id and its cue from the stored profile; a sound named for a layer must be in the film's library."""
    x = raw if isinstance(raw, dict) else {}
    kept = {l.get("id"): l for l in ((old or {}).get("layers") or []) if isinstance(l, dict)}
    layers, seen = [], set()
    for l in (x.get("layers") or [])[: MAX_LAYERS * 2]:
        if not isinstance(l, dict) or not _t(l.get("name"), 60):
            continue
        lid = l.get("id") if isinstance(l.get("id"), str) and ID.match(l.get("id", "")) and l["id"].startswith("ly-") else f"ly-{uuid.uuid4().hex[:8]}"
        if lid in seen:
            continue
        seen.add(lid)
        aid = l.get("asset_id") or None
        if aid and assets is not None and aid not in assets:
            raise SystemExit("A layer names a sound that is not in this film's library.")
        dist = l.get("distance") if l.get("distance") in DISTANCES else "mid"
        layers.append({"id": lid, "name": _t(l.get("name"), 60), "distance": dist, "level_db": round(_n(l.get("level_db"), -40, 6, -6.0), 1), "asset_id": aid,
                       "loop": l.get("loop") is not False, "description": _t(l.get("description"), 200), "cue_id": (kept.get(lid) or {}).get("cue_id")})
    layers = layers[:MAX_LAYERS]
    interior = x.get("interior") if isinstance(x.get("interior"), bool) else None
    return {"interior": interior, "weather": _t(x.get("weather"), 60), "time_of_day": _t(x.get("time_of_day"), 40), "room_size": x.get("room_size") if x.get("room_size") in ROOMS else "",
            "materials": _list(x.get("materials"), 12, 30), "surfaces": _list(x.get("surfaces"), 12, 30), "reverb": x.get("reverb") if x.get("reverb") in REVERBS else "",
            "layers": layers, "recurring": _t(x.get("recurring"), 300), "notes": _t(x.get("notes"), NOTE)}


# ---------------------------------------------------------------- the film's record

def _path(d: str) -> str:
    return os.path.join(d, "audio", "sounddesign.json")


def _empty() -> dict:
    return {"schema": 1, "profiles": {}, "events": [], "removed": []}


def _ok(r: object) -> bool:
    return isinstance(r, dict) and isinstance(r.get("profiles", {}), dict) and isinstance(r.get("events", []), list) and isinstance(r.get("removed", []), list)


def _norm(r: dict) -> dict:
    r.setdefault("schema", 1)
    if not isinstance(r.get("profiles"), dict):
        r["profiles"] = {}
    for k in ("events", "removed"):
        if not isinstance(r.get(k), list):
            r[k] = []
    return r


def _load(d: str) -> dict:
    return _norm(safeio.read_json(_path(d), None, check=_ok) or _empty())


def _update(d: str, change) -> None:
    def wrap(r):
        change(_norm(r))
        return r
    safeio.update_json(_path(d), wrap, _empty(), check=_ok)


def _film(d: str) -> None:
    Q._film(d)


def _environment(d: str, scene: int) -> dict | None:
    for e in B.load(d)["environments"]:
        if int(scene) in [int(s) for s in (e.get("scenes") or [])]:
            return e
    return None


def _contract(d: str, shot: str) -> dict:
    from . import make
    c = next((c for c in make._contracts(d) if c["id"] == shot), None)
    if not c:
        raise SystemExit("That shot isn't in the film.")
    return c


# ---------------------------------------------------------------- distance and side become a level and a balance

def placement(event: dict) -> dict:
    """The level (dB) and stereo balance an event or layer gets from how far away and on which side it is, and how hard it is. A balance and a level only: no room, no occlusion."""
    dist = DISTANCES.get(event.get("distance"), 0.0)
    gain = dist + (_n(event.get("intensity"), 0, 1, 0.5) - 0.5) * 6.0 + float(event.get("level_db") or 0.0)
    return {"gain_db": round(max(Q.GAIN[0], min(Q.GAIN[1], gain)), 1), "pan": SIDES.get(event.get("side"), 0.0)}


# ---------------------------------------------------------------- suggesting what a shot's action names (free; saves nothing)

def _material(phrase: str, env_materials: list[str]) -> str:
    for name, rx in MATERIALS:
        if re.search(rx, phrase, re.I):
            return name
    return ""


def _object_after(sentence: str, end: int) -> str:
    words = re.findall(r"[A-Za-z']+", sentence[end:])
    out = []
    for w in words:
        if w.lower() in STOP and not out:
            continue
        if w.lower() in ("on", "onto", "in", "into", "across", "at", "to", "while", "as", "and", "with") and out:
            break
        if w.lower() == "of" and out:
            out.append("of")
            continue
        if w.lower() in STOP:
            continue
        out.append(w.lower())
        if len(out) >= 4:
            break
    return " ".join(out)


NOT_NAMES = {"INT", "EXT", "CUT", "FADE", "DAY", "NIGHT", "CONT", "V", "O"}


def _subject(before: str, names: list[str]) -> str:
    """Who does it: the nearest person named before the verb, either a character the film knows or a name written in capitals as a screenplay does. Empty when nobody is named (never a guess)."""
    best, at = "", -1
    for n in names:
        i = before.upper().rfind(n.upper()) if n else -1
        if i > at:
            best, at = n, i
    for m in re.finditer(r"(?<![A-Za-z])[A-Z]{2,}(?![A-Za-z])", before):
        if m.group(0) not in NOT_NAMES and m.start() > at:
            best, at = m.group(0), m.start()
    return best


def suggest(d: str, shot: str) -> dict:
    """Foley a shot's written action really names: a drop, a slam, a stir, a step. Free: no model is asked and nothing is saved. At most a few per shot, the most dramatic first; movement the action does
    not name gets no sound. Timing is estimated from where in the text the action falls, and every proposal says the words that motivated it."""
    _film(d)
    c = _contract(d, str(shot))
    dur = float((c.get("generation") or {}).get("duration") or 4.0)
    text = " ".join(str(c.get("action") or "").split())
    env = _environment(d, int(c["scene"]))
    prof = (_load(d)["profiles"].get((env or {}).get("id")) or {}) if env else {}
    framing = str((c.get("camera") or {}).get("framing") or "").lower()
    distance = "near" if "close" in framing else "mid"
    names = [str(x.get("name") or "") for x in c.get("characters") or []] + [str(x.get("name") or "") for x in B.load(d)["characters"]]
    found: list[dict] = []
    for rx, action, prio, default_obj in VERBS:
        for m in re.finditer(rx, text, re.I):
            before = text[: m.start()]
            subject = _subject(text[text.rfind(".", 0, m.start()) + 1: m.start()], names)       # only a person named in the same sentence
            sentence = text[max(0, text.rfind(".", 0, m.start()) + 1): (text.find(".", m.end()) if text.find(".", m.end()) != -1 else len(text))]
            obj = default_obj or _object_after(text, m.end()) or "object"
            phrase = f"{sentence}"
            surf_m = re.search(SURFACES, text[m.start():], re.I)
            surface = surf_m.group(0).lower() if surf_m else (prof.get("surfaces") or [""])[0]
            material = _material(obj, prof.get("materials") or []) or ("" if action == "footsteps" else _material(surface, []))
            found.append({"action": action, "source_object": obj, "by": subject, "material": material, "surface": surface, "intensity": {5: 0.9, 4: 0.75, 3: 0.6, 2: 0.5, 1: 0.35}[prio],
                          "distance": distance, "side": "centre", "pos": m.start(), "start": round(max(0.0, min(dur - 0.5, dur * m.start() / max(1, len(text)))), 1), "priority": prio, "motivated_by": _t(text[max(0, m.start() - 20): m.end() + 30], 80)})
    # a bare "slams" beside "the door" is the same sound: a vague match is dropped when a named one falls within a few words of it
    found = [e for e in found if not (e["source_object"] == "object" and any(o is not e and o["source_object"] != "object" and abs(o["pos"] - e["pos"]) <= 30 for o in found))]
    found.sort(key=lambda e: (-e["priority"], e["start"]))
    out, keys = [], set()
    for e in found:
        k = (e["action"], e["source_object"])
        if k in keys:
            continue
        keys.add(k)
        out.append(e)
        if len(out) >= MAX_EVENTS_PER_SHOT:
            break
    out.sort(key=lambda e: e["start"])
    return {"shot": c["id"], "scene": int(c["scene"]), "proposals": [{k: v for k, v in e.items() if k not in ("priority", "pos")} for e in out], "considered": len(found),
            "note": "Only sounds the written action names are proposed, at most %d per shot. Timing is estimated from where the action falls in the text: move each to the moment you see it." % MAX_EVENTS_PER_SHOT}


# ---------------------------------------------------------------- events

def _clean_event(d: str, x: dict, old: dict | None, lib: dict, shots: dict) -> dict:
    e = dict(old or {})
    if not old or "shot" in x:
        sid = x.get("shot", e.get("shot"))
        if not sid or sid not in shots:
            raise SystemExit("Choose a shot in this film.")
        e["shot"], e["scene"] = str(sid), int(shots[sid]["scene"])
    for k, lim in (("action", 60), ("source_object", 60), ("material", 30), ("surface", 40), ("by", 60), ("motivated_by", 80), ("note", NOTE)):
        if k in x or k not in e:
            e[k] = _t(x.get(k, e.get(k, "")), lim).lower() if k in ("material", "surface") else _t(x.get(k, e.get(k, "")), lim)
    if not e.get("action"):
        raise SystemExit("Say what the sound is (a drop, a step, a stir...).")
    if "distance" in x or "distance" not in e:
        e["distance"] = x.get("distance", e.get("distance")) if x.get("distance", e.get("distance")) in DISTANCES else "mid"
    if "side" in x or "side" not in e:
        e["side"] = x.get("side", e.get("side")) if x.get("side", e.get("side")) in SIDES else "centre"
    if "perspective" in x or "perspective" not in e:
        e["perspective"] = x.get("perspective", e.get("perspective")) if x.get("perspective", e.get("perspective")) in ("close", "wide", "") else ""
    if "intensity" in x or "intensity" not in e:
        e["intensity"] = round(_n(x.get("intensity", e.get("intensity")), 0, 1, 0.5), 2)
    dur = float(shots[e["shot"]].get("duration") or 4.0)
    if "start" in x or "start" not in e:
        e["start"] = round(_n(x.get("start", e.get("start")), 0, max(0.0, dur - 0.1), 0.0), 2)
    if "duration" in x or "duration" not in e:
        v = x.get("duration", e.get("duration"))
        e["duration"] = None if v in (None, "", 0) else round(_n(v, 0.1, 600, 1.0), 2)
    if "asset_id" in x:
        aid = x.get("asset_id") or None
        if aid and not any(a["id"] == aid for a in lib["assets"]):
            raise SystemExit("That sound is not in this film's library.")
        e["asset_id"] = aid
    e.setdefault("asset_id", None)
    if "variations" in x:
        ids = []
        for v in (x.get("variations") or [])[:8]:
            if any(a["id"] == v for a in lib["assets"]) and v not in ids:
                ids.append(v)
        e["variations"] = ids
    e.setdefault("variations", [])
    if "approval" in x:
        if x["approval"] not in APPROVALS:
            raise SystemExit("Choose approved, rejected or suggested.")
        e["approval"] = x["approval"]
    e.setdefault("approval", "suggested")
    e.setdefault("source", "derived" if x.get("source") == "derived" else "manual")
    e.setdefault("cue_id", None)
    return e


def event_add(d: str, data: dict) -> dict:
    """Add a Foley event. One the person types is a plan they chose (still approved separately); one taken from `suggest` is marked derived. Nothing is heard until it has a sound and is approved."""
    _film(d)
    shots, lib = Q._shots(d), AL.load(d)
    holder: dict = {}

    def change(r):
        e = _clean_event(d, data, None, lib, shots)
        e["id"] = f"fx-{uuid.uuid4().hex[:8]}"
        e["created"] = e["updated"] = int(time.time())
        r["events"].append(e)
        holder["id"] = e["id"]
    _update(d, change)
    return {**scene(d, int(shots[data["shot"]]["scene"])), "id": holder["id"]}


def _find(r: dict, eid: str) -> dict:
    if not ID.match(str(eid or "")) or not str(eid).startswith("fx-"):
        raise SystemExit("That sound id is not valid.")
    for e in r["events"]:
        if e["id"] == eid:
            return e
    raise SystemExit("That sound isn't in the film.")


def event_update(d: str, eid: str, data: dict) -> dict:
    """Change an event. If it already became a cue, `to_cues` brings that one cue up to date: nothing else is touched."""
    _film(d)
    shots, lib = Q._shots(d), AL.load(d)
    holder: dict = {}

    def change(r):
        e = _find(r, eid)
        new = _clean_event(d, data, e, lib, shots)
        new["id"], new["created"], new["updated"] = e["id"], e.get("created"), int(time.time())
        e.clear()
        e.update(new)
        holder["scene"] = e["scene"]
    _update(d, change)
    return scene(d, holder["scene"])


def event_remove(d: str, eid: str) -> dict:
    """Take an event out of the plan (it moves to `removed`). Its cue, if it has one, is removed from the plan the same way (the sound file stays in the library)."""
    _film(d)
    holder: dict = {}

    def change(r):
        e = _find(r, eid)
        r["events"] = [x for x in r["events"] if x["id"] != eid]
        r["removed"].append({**e, "removed_at": int(time.time())})
        del r["removed"][:-KEEP_REMOVED]
        holder["e"] = e
    _update(d, change)
    cue = holder["e"].get("cue_id")
    if cue and any(c["id"] == cue for c in Q.listing(d)["cues"]):
        Q.remove(d, cue)
    return scene(d, holder["e"]["scene"])


def candidates(d: str, eid: str) -> dict:
    """Sounds already in the film's library that could cover an event, best first (free; rejected sounds are never offered). Reuse before generating."""
    _film(d)
    e = _find(_load(d), eid)
    terms = " ".join(x for x in (e.get("action"), e.get("source_object"), e.get("material"), e.get("surface")) if x)
    lib = AL.load(d)
    rows = Q.match_assets(lib, "sfx", terms, scene=int(e["scene"]), limit=5)
    return {"id": eid, "terms": terms, "candidates": [{"id": r["asset_id"], "name": r["name"], "seconds": r["seconds"], "approved": r["approved"], "why": r["why"]} for r in rows]}


# ---------------------------------------------------------------- profiles

def profile_set(d: str, env_id: str, profile: dict) -> dict:
    """Save a place's soundscape profile. Its layers keep their cues; nothing is heard until `to_cues`."""
    _film(d)
    env = next((e for e in B.load(d)["environments"] if e["id"] == str(env_id or "")), None)
    if not env:
        raise SystemExit("That place isn't in the Production Bible.")
    assets = {a["id"] for a in AL.load(d)["assets"]}

    def change(r):
        r["profiles"][env["id"]] = clean_profile(profile, r["profiles"].get(env["id"]), assets)
    _update(d, change)
    return scene(d, int((env.get("scenes") or [1])[0]))


# ---------------------------------------------------------------- the scene as one view

def _coverage(r: dict, scn: int, env: dict | None, prof: dict | None) -> dict:
    ev = [e for e in r["events"] if int(e["scene"]) == int(scn)]
    return {"events": len(ev), "approved": sum(1 for e in ev if e["approval"] == "approved"), "without_sound": [e["id"] for e in ev if not e.get("asset_id") and e["approval"] != "rejected"],
            "layers": len((prof or {}).get("layers") or []), "layers_without_sound": [l["id"] for l in (prof or {}).get("layers") or [] if not l.get("asset_id")],
            "has_profile": bool(prof), "environment": (env or {}).get("name")}


def scene(d: str, scn: int) -> dict:
    """Everything sound design knows about one scene: its place and soundscape profile, its Foley events and what is still missing. Free."""
    _film(d)
    r = _load(d)
    env = _environment(d, int(scn))
    prof = r["profiles"].get(env["id"]) if env else None
    cues = {c["id"]: c for c in Q.listing(d)["cues"]}
    events = []
    for e in sorted((e for e in r["events"] if int(e["scene"]) == int(scn)), key=lambda e: (e["shot"], e["start"])):
        events.append({**e, "placement": placement(e), "cue": ({"approval": cues[e["cue_id"]]["approval"]} if e.get("cue_id") in cues else None)})
    layers = [{**l, "placement": placement({"distance": l["distance"], "level_db": l["level_db"]}), "cue": ({"approval": cues[l["cue_id"]]["approval"]} if l.get("cue_id") in cues else None)}
              for l in (prof or {}).get("layers") or []]
    shots = [s for s in Q._shots(d).values() if int(s["scene"]) == int(scn)]
    return {"scene": int(scn), "environment": ({"id": env["id"], "name": env["name"]} if env else None), "profile": prof, "layers": layers, "events": events,
            "shots": [{"id": s["id"], "duration": s.get("duration")} for s in sorted(shots, key=lambda s: s["id"])], "coverage": _coverage(r, scn, env, prof)}


# ---------------------------------------------------------------- into the mix, as ordinary cues

def to_cues(d: str, scn: int) -> dict:
    """Make or update the cues for this scene: one scene-wide ambience cue per profile layer that has a sound, and one cue per approved Foley event that has a sound. This is the person's act, so the cues
    are approved. Doing it again updates the same cues (a changed event changes only its own cue); events and layers without a sound are listed, never guessed."""
    _film(d)
    r = _load(d)
    env = _environment(d, int(scn))
    prof = r["profiles"].get(env["id"]) if env else None
    made, updated, waiting = [], [], []
    existing = {c["id"] for c in Q.listing(d)["cues"]}
    stamp: dict[str, str] = {}

    def sync(kind_id: str, cue_id: str | None, base: dict) -> str:
        if cue_id and cue_id in existing:
            Q.update(d, cue_id, {**base, "keep_plan": False})
            updated.append(kind_id)
            return cue_id
        res = Q.add(d, {**base, "source": "manual", "approval": "approved"})
        made.append(kind_id)
        cid = res["id"]
        existing.add(cid)
        return cid

    for l in (prof or {}).get("layers") or []:
        if not l.get("asset_id"):
            waiting.append({"kind": "layer", "id": l["id"], "name": l["name"]})
            continue
        pl = placement({"distance": l["distance"], "level_db": l["level_db"]})
        stamp[l["id"]] = sync(l["id"], l.get("cue_id"), {"kind": "ambience", "asset_id": l["asset_id"], "scene": int(scn), "shot": None, "start": 0.0, "duration": None, "gain_db": pl["gain_db"], "pan": 0.0,
                                                          "loop": l.get("loop") is not False, "note": f"Soundscape: {l['name']}"[:600]})
    ev_stamp: dict[str, str] = {}
    for e in r["events"]:
        if int(e["scene"]) != int(scn) or e["approval"] != "approved":
            continue
        if not e.get("asset_id"):
            waiting.append({"kind": "event", "id": e["id"], "name": f"{e['action']}: {e['source_object']}".strip(": ")})
            continue
        pl = placement(e)
        ev_stamp[e["id"]] = sync(e["id"], e.get("cue_id"), {"kind": "sfx", "asset_id": e["asset_id"], "scene": int(scn), "shot": e["shot"], "start": e["start"], "duration": e.get("duration"), "gain_db": pl["gain_db"],
                                                            "pan": pl["pan"], "loop": False, "foley": True, "note": f"Foley: {e['action']} {e['source_object']}".strip()[:600]})

    def change(r2):
        pf = r2["profiles"].get(env["id"]) if env else None
        for l in (pf or {}).get("layers") or []:
            if l["id"] in stamp:
                l["cue_id"] = stamp[l["id"]]
        for e in r2["events"]:
            if e["id"] in ev_stamp:
                e["cue_id"] = ev_stamp[e["id"]]
    if stamp or ev_stamp:
        _update(d, change)
    return {**scene(d, int(scn)), "made": made, "updated": updated, "waiting": waiting}


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["scene", "profile_set", "suggest", "event_add", "event_update", "event_remove", "candidates", "to_cues"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        if a.action == "scene":
            res = scene(d, int(x.get("scene") or 1))
        elif a.action == "profile_set":
            res = profile_set(d, x.get("environment", ""), x.get("profile") or {})
        elif a.action == "suggest":
            res = suggest(d, x.get("shot", ""))
        elif a.action == "event_add":
            res = event_add(d, x)
        elif a.action == "event_update":
            res = event_update(d, x.get("id", ""), x)
        elif a.action == "event_remove":
            res = event_remove(d, x.get("id", ""))
        elif a.action == "candidates":
            res = candidates(d, x.get("id", ""))
        else:
            res = to_cues(d, int(x.get("scene") or 1))
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
