"""The music director: where music goes in a film, what it is built from, and who said it may be used.

Three things the sound plan did not know about:

* **Motifs.** A motif is a short musical idea the film comes back to, tied to a person, a place or a theme: how it feels, how fast, which instruments, and a line saying what it is. It is a *plan*:
  nothing here composes anything. A motif is written into the words used to ask for music and into the notes beside each cue, so the same idea can come back.
* **Spotting.** For each scene the person (or `suggest`, free, from the written action) decides: **score** (music plays), **source** (music in the world: a radio) or **silence** (a deliberate choice).
  A spot says from which shot to which shot, how the energy moves (0 to 5), the mood, the tempo, the motifs, where music enters and where it leaves, and which library music covers it.
  `suggest` reads only the words of the scene (free, no AI, nothing saved), says which words it acted on, and proposes silence when nothing in the scene calls for music.
* **Records.** For each piece of library music: who approved it, for which scenes, a note about the licence, and when. The record is kept with its history. Music whose licence says commercial use is *not*
  allowed is never put into the film by `to_cues`; music with an unknown licence is put in but listed by `report` until someone has recorded a decision.

`to_cues` turns the approved spots that have music into ordinary audio cues (`audiocues`), so the mixer, the ducking and the loudness all apply. Doing it again updates the same cues.

  <film>/audio/music.json   { motifs: [...], spots: [...], records: { <asset id>: {...} }, removed: [...] }   (written with safeio; nothing is deleted: removed items move to `removed`)

  python -m filmcrafter_engine.musicdirector <get|suggest|motif_set|motif_remove|spot_set|spot_remove|prompt|candidates|record_set|to_cues|report> <film> --data '{...}'
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
from .sounddesign import _list, _n, _t

MOTIF_KINDS = ("character", "place", "theme")
DECISIONS = ("score", "source", "silence")
ROLES = ("", "theme", "underscore", "stinger")
APPROVALS = ("suggested", "approved", "rejected")
RECORD_STATUS = ("approved", "revoked")
MAX_MOTIFS = 40
MAX_SPOTS_PER_SCENE = 6
MAX_HISTORY = 30
KEEP_REMOVED = 200
PROMPT_CHARS = 900
MIN_S, MAX_S = 3.0, 600.0
LEVELS = (-40.0, 6.0)

# the words of a scene that call for music, with what they suggest: (pattern, mood, energy)
FEELINGS: list[tuple[str, str, int]] = [
    (r"\b(?:chas(?:e|es|ed|ing)|runs?|ran|scream(?:s|ed)?|gun|shoots?|fights?|punch(?:es|ed)?|blood|panic|explod\w*|slams?|slammed|crash\w*)\b", "tension", 4),
    (r"\b(?:cr(?:y|ies|ied|ying)|weeps?|wept|tears?|funeral|grave|dies|died|dead|death|alone|lonely|loss|grie\w+|sobs?)\b", "sorrow", 2),
    (r"\b(?:laugh\w*|smil\w+|hugs?|hugged|kiss\w*|danc\w+|celebrat\w+|embrac\w+|cheer\w*|giggl\w+)\b", "warmth", 3),
    (r"\b(?:dawn|sunrise|sunset|horizon|vast|mountain|stars?|ocean|sea|clouds?|glow\w*|light spills?)\b", "wonder", 2),
    (r"\b(?:shadow\w*|creep\w*|whisper\w*|silence|dark(?:ness)?|stalk\w*|watch(?:es|ing)? from|empty)\b", "unease", 3),
]


def emit(**kw) -> None:
    try:
        print(json.dumps(kw, ensure_ascii=False), flush=True)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- the film's record

def _path(d: str) -> str:
    return os.path.join(d, "audio", "music.json")


def _empty() -> dict:
    return {"schema": 1, "motifs": [], "spots": [], "records": {}, "removed": []}


def _ok(r: object) -> bool:
    return isinstance(r, dict) and isinstance(r.get("motifs", []), list) and isinstance(r.get("spots", []), list) and isinstance(r.get("records", {}), dict) and isinstance(r.get("removed", []), list)


def _norm(r: dict) -> dict:
    r.setdefault("schema", 1)
    for k in ("motifs", "spots", "removed"):
        if not isinstance(r.get(k), list):
            r[k] = []
        r[k] = [x for x in r[k] if isinstance(x, dict)]
    if not isinstance(r.get("records"), dict):
        r["records"] = {}
    r["records"] = {k: v for k, v in r["records"].items() if isinstance(v, dict)}
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


def _shot_list(d: str) -> dict[int, list[dict]]:
    out = Q._scenes(Q._shots(d))
    return {k: sorted(v, key=lambda s: (int(s.get("index") or 0), s["id"])) for k, v in out.items()}


def _scene_or_fail(d: str, scene) -> tuple[int, list[dict]]:
    try:
        n = int(scene)
    except (TypeError, ValueError):
        raise SystemExit("Choose a scene in this film.")
    shots = _shot_list(d).get(n)
    if not shots:
        raise SystemExit("That scene isn't in the film.")
    return n, shots


# ---------------------------------------------------------------- motifs

def _clean_motif(x: dict, old: dict | None) -> dict:
    m = dict(old or {})
    for k, lim in (("name", 60), ("subject", 80), ("mood", 60), ("tempo", 40), ("key", 30), ("description", 300), ("note", 400)):
        if k in x or k not in m:
            m[k] = _t(x.get(k, m.get(k, "")), lim)
    if not m.get("name"):
        raise SystemExit("Give the motif a name.")
    if "kind" in x or "kind" not in m:
        k = x.get("kind", m.get("kind"))
        if k not in MOTIF_KINDS:
            raise SystemExit("A motif belongs to a character, a place or a theme.")
        m["kind"] = k
    if "instruments" in x or "instruments" not in m:
        m["instruments"] = _list(x.get("instruments", m.get("instruments")), 8, 40)
    return m


def motif_set(d: str, data: dict) -> dict:
    """Add a motif, or change one (give its `id`). Nothing is composed: this is the idea the music is asked for in words."""
    _film(d)
    holder: dict = {}

    def change(r):
        mid = data.get("id")
        old = next((m for m in r["motifs"] if m.get("id") == mid), None) if mid else None
        if mid and not old:
            raise SystemExit("That motif isn't in the film.")
        m = _clean_motif(data, old)
        if any(o.get("id") != m.get("id") and o.get("name", "").lower() == m["name"].lower() for o in r["motifs"]):
            raise SystemExit("There is already a motif with that name.")
        if old:
            old.update(m)
            m = old
        else:
            if len(r["motifs"]) >= MAX_MOTIFS:
                raise SystemExit(f"At most {MAX_MOTIFS} motifs.")
            m["id"] = f"mo-{uuid.uuid4().hex[:8]}"
            m["created"] = time.time()
            r["motifs"].append(m)
        m["updated"] = time.time()
        holder["id"] = m["id"]
    _update(d, change)
    return {**get(d), "id": holder["id"]}


def motif_remove(d: str, mid: str) -> dict:
    """Take a motif out of use. It moves aside (nothing is deleted) and is taken off the spots that named it."""
    _film(d)

    def change(r):
        m = next((m for m in r["motifs"] if m.get("id") == mid), None)
        if not m:
            raise SystemExit("That motif isn't in the film.")
        r["motifs"].remove(m)
        r["removed"].append({"kind": "motif", "at": time.time(), "item": m})
        del r["removed"][:-KEEP_REMOVED]
        for s in r["spots"]:
            s["motif_ids"] = [x for x in s.get("motif_ids") or [] if x != mid]
    _update(d, change)
    return get(d)


# ---------------------------------------------------------------- spotting

def _span(shots: list[dict], a: str | None, b: str | None) -> list[dict]:
    ids = [s["id"] for s in shots]
    i = ids.index(a) if a in ids else 0
    j = ids.index(b) if b in ids else len(ids) - 1
    if j < i:
        i, j = j, i
    return shots[i: j + 1]


def _clean_spot(d: str, x: dict, old: dict | None, r: dict, lib: dict) -> dict:
    s = dict(old or {})
    if not old or "scene" in x:
        n, shots = _scene_or_fail(d, x.get("scene", s.get("scene")))
        s["scene"] = n
    else:
        n, shots = _scene_or_fail(d, s["scene"])
    ids = {sh["id"] for sh in shots}
    for k in ("start_shot", "end_shot"):
        if k in x or k not in s:
            v = x.get(k, s.get(k)) or None
            if v is not None and v not in ids:
                raise SystemExit("That shot isn't in this scene.")
            s[k] = v
    if "decision" in x or "decision" not in s:
        v = x.get("decision", s.get("decision", "score"))
        if v not in DECISIONS:
            raise SystemExit("Choose score, source or silence.")
        s["decision"] = v
    if "role" in x or "role" not in s:
        v = x.get("role", s.get("role", ""))
        s["role"] = v if v in ROLES else ""
    for k in ("energy_in", "energy_out"):
        if k in x or k not in s:
            s[k] = int(round(_n(x.get(k, s.get(k)), 0, 5, 2)))
    for k, lim in (("mood", 60), ("tempo", 40), ("intent", 400), ("enters", 200), ("exits", 200), ("note", 400)):
        if k in x or k not in s:
            s[k] = _t(x.get(k, s.get(k, "")), lim)
    if "instruments" in x or "instruments" not in s:
        s["instruments"] = _list(x.get("instruments", s.get("instruments")), 8, 40)
    if "motif_ids" in x or "motif_ids" not in s:
        have = {m["id"] for m in r["motifs"]}
        ids_ = []
        for v in (x.get("motif_ids", s.get("motif_ids")) or [])[:6]:
            if v not in have:
                raise SystemExit("A motif named here isn't in the film.")
            if v not in ids_:
                ids_.append(v)
        s["motif_ids"] = ids_
    if "level_db" in x or "level_db" not in s:
        s["level_db"] = round(_n(x.get("level_db", s.get("level_db")), LEVELS[0], LEVELS[1], -6.0), 1)
    for k, default in (("fade_in", 1.5), ("fade_out", 2.0)):
        if k in x or k not in s:
            s[k] = round(_n(x.get(k, s.get(k)), 0, 10, default), 2)
    if "asset_id" in x:
        aid = x.get("asset_id") or None
        a = next((a for a in lib["assets"] if a["id"] == aid), None) if aid else None
        if aid and (not a or a.get("kind") != "music"):
            raise SystemExit("That music is not in this film's library.")
        s["asset_id"] = aid
    s.setdefault("asset_id", None)
    if "approval" in x:
        if x["approval"] not in APPROVALS:
            raise SystemExit("Choose approved, rejected or suggested.")
        s["approval"] = x["approval"]
    s.setdefault("approval", "suggested")
    s.setdefault("source", "derived" if x.get("source") == "derived" else "manual")
    s.setdefault("cue_id", None)
    return s


def spot_set(d: str, data: dict) -> dict:
    """Add a spot (a decision for a stretch of a scene) or change one (give its `id`). Nothing is heard until it has music, is approved, and `to_cues` is pressed."""
    _film(d)
    lib = AL.load(d)
    holder: dict = {}

    def change(r):
        sid = data.get("id")
        old = next((s for s in r["spots"] if s.get("id") == sid), None) if sid else None
        if sid and not old:
            raise SystemExit("That spot isn't in the film.")
        s = _clean_spot(d, data, old, r, lib)
        if old:
            old.update(s)
            s = old
        else:
            if sum(1 for o in r["spots"] if o["scene"] == s["scene"]) >= MAX_SPOTS_PER_SCENE:
                raise SystemExit(f"At most {MAX_SPOTS_PER_SCENE} spots in one scene.")
            s["id"] = f"sp-{uuid.uuid4().hex[:8]}"
            s["created"] = time.time()
            r["spots"].append(s)
        s["updated"] = time.time()
        holder["id"] = s["id"]
    _update(d, change)
    return {**get(d), "id": holder["id"]}


def spot_remove(d: str, sid: str) -> dict:
    """Take a spot out. It moves aside; the cue it made (if any) is left in the sound plan, where it can be removed or restored like any other."""
    _film(d)

    def change(r):
        s = next((s for s in r["spots"] if s.get("id") == sid), None)
        if not s:
            raise SystemExit("That spot isn't in the film.")
        r["spots"].remove(s)
        r["removed"].append({"kind": "spot", "at": time.time(), "item": s})
        del r["removed"][:-KEEP_REMOVED]
    _update(d, change)
    return get(d)


# ---------------------------------------------------------------- suggesting a spot from the words of a scene (free; saves nothing)

def _scene_text(d: str, shots: list[dict]) -> list[tuple[str, str]]:
    from . import make
    texts = {c["id"]: " ".join(str(c.get("action") or "").split()) for c in make._contracts(d)}
    return [(s["id"], texts.get(s["id"], "")) for s in shots]


def suggest(d: str, scene: int) -> dict:
    """What the words of a scene call for: music (with the mood and how hard the words push), or silence. Free: no model is asked and nothing is saved. It says which words it acted on, names the motifs
    of the people and the place in the scene, and proposes silence when nothing in the written action calls for music. It judges words, not pictures or sound: the director decides."""
    _film(d)
    n, shots = _scene_or_fail(d, scene)
    r = _load(d)
    rows = _scene_text(d, shots)
    found: list[dict] = []
    for sid, text in rows:
        for rx, mood, energy in FEELINGS:
            for m in re.finditer(rx, text, re.I):
                found.append({"shot": sid, "word": m.group(0).lower(), "mood": mood, "energy": energy})
    spoken = sum(1 for s in shots if s.get("has_dialogue"))
    people = {str(c).lower() for s in shots for c in (s.get("characters") or [])}
    places = {str(s.get("environment") or "").lower() for s in shots}
    motifs = [m["id"] for m in r["motifs"] if (m["kind"] == "character" and m.get("subject", "").lower() in people) or (m["kind"] == "place" and m.get("subject", "").lower() in places)]
    if not found:
        return {"scene": n, "proposal": {"scene": n, "decision": "silence", "start_shot": None, "end_shot": None, "energy_in": 0, "energy_out": 0, "mood": "", "motif_ids": [], "source": "derived",
                                          "intent": "Nothing in the written action calls for music."}, "because": [], "motifs": motifs, "spoken_shots": spoken, "shots": len(shots),
                "note": "Proposed silence is a choice, not a gap: keep it, or write the spot you want. Only the words of the scene were read."}
    moods = sorted({f["mood"] for f in found}, key=lambda m: -sum(1 for f in found if f["mood"] == m))
    top = max((f for f in found if f["mood"] == moods[0]), key=lambda f: f["energy"])                   # the energy of the mood the words point to most
    first = min(found, key=lambda f: [s["id"] for s in shots].index(f["shot"]))
    proposal = {"scene": n, "decision": "score", "start_shot": first["shot"], "end_shot": shots[-1]["id"], "energy_in": max(0, top["energy"] - 1), "energy_out": top["energy"], "mood": moods[0],
                "motif_ids": motifs, "source": "derived", "role": "underscore", "intent": f"Words in the scene point to {moods[0]}" + (f", then {moods[1]}" if len(moods) > 1 else "") + "."}
    return {"scene": n, "proposal": proposal, "because": [{"shot": f["shot"], "word": f["word"], "mood": f["mood"]} for f in found[:12]], "motifs": motifs, "spoken_shots": spoken, "shots": len(shots),
            "note": "A proposal from the written words only. Where music enters and leaves is estimated from the first word that pushed: move it to the moment you see it."}


# ---------------------------------------------------------------- asking for the music (the words only: nothing is sent)

def prompt(d: str, sid: str) -> dict:
    """The words to ask a music maker for this spot, and the length, built from the spot and its motifs. Nothing is sent: paste it into Sound & Music's music generator, where the price is shown first."""
    _film(d)
    r = _load(d)
    s = next((s for s in r["spots"] if s.get("id") == sid), None)
    if not s:
        raise SystemExit("That spot isn't in the film.")
    if s["decision"] != "score":
        raise SystemExit("Only a spot that is scored needs music.")
    _, shots = _scene_or_fail(d, s["scene"])
    span = _span(shots, s.get("start_shot"), s.get("end_shot"))
    secs = round(max(MIN_S, min(MAX_S, sum(float(x.get("duration") or 4.0) for x in span))), 1)
    ms = [m for m in r["motifs"] if m["id"] in (s.get("motif_ids") or [])]
    parts = ["Instrumental film score cue, no vocals."]
    if s.get("mood"):
        parts.append(f"Mood: {s['mood']}.")
    if s.get("tempo"):
        parts.append(f"Tempo: {s['tempo']}.")
    ins = list(s.get("instruments") or []) or [i for m in ms for i in m.get("instruments") or []]
    if ins:
        parts.append("Instruments: " + ", ".join(dict.fromkeys(ins)) + ".")
    parts.append(f"Intensity moves from {s['energy_in']} to {s['energy_out']} on a scale of 0 to 5.")
    for m in ms:
        parts.append(f"Motif ({m['name']}): " + (m.get("description") or m.get("mood") or "a recurring idea") + (f", {m['tempo']}" if m.get("tempo") else "") + (f", key {m['key']}" if m.get("key") else "") + ".")
    if s.get("intent"):
        parts.append(s["intent"])
    if s.get("enters"):
        parts.append(f"Enters: {s['enters']}.")
    if s.get("exits"):
        parts.append(f"Ends: {s['exits']}.")
    text = " ".join(parts)[:PROMPT_CHARS]
    return {"spot": sid, "prompt": text, "duration": secs, "instrumental": True, "shots": [x["id"] for x in span],
            "how": "Paste this into the music generator in Sound & Music. Nothing has been sent or charged; the price is shown there first. Then choose the result for this spot."}


def candidates(d: str, sid: str) -> dict:
    """Music already in the film's library that could cover a spot, best first (free). Reuse before generating; rejected music is never offered."""
    _film(d)
    r = _load(d)
    s = next((s for s in r["spots"] if s.get("id") == sid), None)
    if not s:
        raise SystemExit("That spot isn't in the film.")
    terms = " ".join(x for x in (s.get("mood"), s.get("tempo"), " ".join(s.get("instruments") or []), s.get("intent")) if x)
    rows = Q.match_assets(AL.load(d), "music", terms, scene=int(s["scene"]), limit=5)
    return {"spot": sid, "terms": terms, "candidates": [{"id": x["asset_id"], "name": x["name"], "seconds": x["seconds"], "approved": x["approved"], "why": x["why"]} for x in rows]}


# ---------------------------------------------------------------- records: who approved this music, for what, and the licence note

def record_set(d: str, asset_id: str, data: dict) -> dict:
    """Record a decision about a piece of library music: approved or revoked, by whom, for which scenes, with a note about the licence. Every decision is kept in the record's history. This records what
    the person says; it does not check a licence, and it does not change what the library says about commercial use."""
    _film(d)
    a = next((a for a in AL.load(d)["assets"] if a["id"] == asset_id and a.get("kind") == "music"), None)
    if not a:
        raise SystemExit("That music is not in this film's library.")
    status = data.get("status", "approved")
    if status not in RECORD_STATUS:
        raise SystemExit("Choose approved or revoked.")
    by = _t(data.get("by"), 60)
    if not by:
        raise SystemExit("Say who is making this decision.")
    scenes = sorted({int(x) for x in (data.get("scenes") or []) if str(x).lstrip("-").isdigit() and int(x) > 0})[:50]
    note = _t(data.get("licence_ref"), 300)

    def change(r):
        cur = r["records"].setdefault(asset_id, {"history": []})
        entry = {"status": status, "by": by, "scenes": scenes, "licence_ref": note, "at": time.time()}
        cur.update(entry)
        cur["history"] = (list(cur.get("history") or []) + [entry])[-MAX_HISTORY:]
    _update(d, change)
    return get(d)


# ---------------------------------------------------------------- into the mix, as ordinary cues

def _commercial(lib: dict, aid: str) -> str:
    a = next((a for a in lib["assets"] if a["id"] == aid), None)
    return ((a or {}).get("licence") or {}).get("commercial", "unknown")


def to_cues(d: str, scene: int) -> dict:
    """Make or update this scene's music cues from its approved, scored spots that have music: anchored at the spot's first shot, as long as the spot, with its level and fades. Doing it again updates
    the same cues. Music whose licence says commercial use is not allowed is never put in (`blocked`); spots without music are listed (`waiting`); silence and source spots make no cue."""
    _film(d)
    n, shots = _scene_or_fail(d, scene)
    r = _load(d)
    lib = AL.load(d)
    made, updated, waiting, blocked, silent = [], [], [], [], []
    existing = {c["id"] for c in Q.listing(d)["cues"]}
    stamp: dict[str, str] = {}
    for s in r["spots"]:
        if int(s["scene"]) != n or s["approval"] != "approved":
            continue
        if s["decision"] != "score":
            silent.append({"id": s["id"], "decision": s["decision"]})
            continue
        if not s.get("asset_id"):
            waiting.append({"id": s["id"], "mood": s.get("mood", "")})
            continue
        if _commercial(lib, s["asset_id"]) == "no":
            blocked.append({"id": s["id"], "why": "This music's licence says commercial use is not allowed."})
            continue
        span = _span(shots, s.get("start_shot"), s.get("end_shot"))
        secs = round(sum(float(x.get("duration") or 4.0) for x in span), 2)
        base = {"kind": "music", "asset_id": s["asset_id"], "scene": n, "shot": span[0]["id"], "start": 0.0, "duration": secs, "gain_db": s["level_db"], "fade_in": s["fade_in"], "fade_out": s["fade_out"],
                "loop": False, "ducking": "auto", "note": ("Music: " + (s.get("mood") or "score") + (f" ({s['intent']})" if s.get("intent") else ""))[:600]}
        if s.get("cue_id") in existing:
            Q.update(d, s["cue_id"], {**base, "keep_plan": False})
            updated.append(s["id"])
            stamp[s["id"]] = s["cue_id"]
        else:
            cid = Q.add(d, {**base, "source": "manual", "approval": "approved"})["id"]
            existing.add(cid)
            made.append(s["id"])
            stamp[s["id"]] = cid

    def change(r2):
        for s in r2["spots"]:
            if s["id"] in stamp:
                s["cue_id"] = stamp[s["id"]]
    if stamp:
        _update(d, change)
    return {**get(d), "made": made, "updated": updated, "waiting": waiting, "blocked": blocked, "silent": silent}


# ---------------------------------------------------------------- the whole film as one view

def report(d: str) -> dict:
    """What the music plan still needs, in plain facts: scenes with no decision, motifs never used or used once, big jumps of energy from one scored scene to the next, how much of the film has music,
    and music in the plan with no recorded decision or with a licence that does not allow commercial use. Free; changes nothing."""
    _film(d)
    r = _load(d)
    lib = AL.load(d)
    scenes = _shot_list(d)
    rows, undecided, dur_total, dur_music = [], [], 0.0, 0.0
    by_scene: dict[int, list[dict]] = {}
    for s in r["spots"]:
        if s["approval"] != "rejected":
            by_scene.setdefault(int(s["scene"]), []).append(s)
    for n in sorted(scenes):
        sh = scenes[n]
        total = sum(float(x.get("duration") or 4.0) for x in sh)
        dur_total += total
        spots = by_scene.get(n, [])
        music = sum(sum(float(x.get("duration") or 4.0) for x in _span(sh, s.get("start_shot"), s.get("end_shot"))) for s in spots if s["decision"] == "score")
        dur_music += min(total, music)
        if not spots:
            undecided.append(n)
        rows.append({"scene": n, "seconds": round(total, 1), "spots": len(spots), "decisions": sorted({s["decision"] for s in spots}), "scored_seconds": round(min(total, music), 1)})
    use: dict[str, set] = {m["id"]: set() for m in r["motifs"]}
    for s in r["spots"]:
        if s["approval"] == "rejected":
            continue
        for mid in s.get("motif_ids") or []:
            use.setdefault(mid, set()).add(int(s["scene"]))
    motifs = [{"id": m["id"], "name": m["name"], "kind": m["kind"], "scenes": sorted(use.get(m["id"], ())),
               "note": "Never used." if not use.get(m["id"]) else ("Used in one scene only: a motif is an idea the film comes back to." if len(use[m["id"]]) == 1 else "")} for m in r["motifs"]]
    jumps = []
    scored = sorted((s for s in r["spots"] if s["decision"] == "score" and s["approval"] != "rejected"), key=lambda s: (int(s["scene"]), s["id"]))
    for a, b in zip(scored, scored[1:]):
        if int(b["scene"]) != int(a["scene"]) and abs(int(b["energy_in"]) - int(a["energy_out"])) >= 3:
            jumps.append({"from_scene": int(a["scene"]), "to_scene": int(b["scene"]), "from_energy": a["energy_out"], "to_energy": b["energy_in"],
                          "note": "A big change of energy between scored scenes: right if it is meant."})
    plan_assets = {c["asset_id"] for c in Q.listing(d)["cues"] if c.get("kind") == "music" and c.get("asset_id") and c.get("approval") != "rejected"} | {s["asset_id"] for s in r["spots"] if s.get("asset_id")}
    records = []
    for aid in sorted(plan_assets):
        a = next((a for a in lib["assets"] if a["id"] == aid), None)
        if not a:
            continue
        rec = r["records"].get(aid) or {}
        com = (a.get("licence") or {}).get("commercial", "unknown")
        problems = []
        if com == "no":
            problems.append("Commercial use is not allowed.")
        elif com == "unknown":
            problems.append("Commercial use is not known.")
        if rec.get("status") != "approved":
            problems.append("Revoked." if rec.get("status") == "revoked" else "No recorded decision.")
        records.append({"id": aid, "name": a["name"], "commercial": com, "status": rec.get("status") or "none", "by": rec.get("by", ""), "scenes": rec.get("scenes", []), "problems": problems})
    return {"scenes": rows, "undecided": undecided, "motifs": motifs, "jumps": jumps, "records": records, "music_share": round(dur_music / dur_total, 2) if dur_total else 0.0,
            "seconds": round(dur_total, 1), "needs_attention": bool(undecided or any(x["problems"] for x in records) or any(m["note"] == "Never used." for m in motifs))}


def get(d: str) -> dict:
    """The film's music plan: motifs, spots (with the cue each one made and whether it is out of date), records and the report. Free."""
    _film(d)
    r = _load(d)
    cues = {c["id"]: c for c in Q.listing(d)["cues"]}
    spots = sorted(r["spots"], key=lambda s: (int(s["scene"]), s.get("created", 0)))
    return {"motifs": r["motifs"], "spots": [{**s, "cue": ({"approval": cues[s["cue_id"]]["approval"]} if s.get("cue_id") in cues else None)} for s in spots], "records": r["records"], "report": report(d)}


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["get", "suggest", "motif_set", "motif_remove", "spot_set", "spot_remove", "prompt", "candidates", "record_set", "to_cues", "report"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        if a.action == "get":
            res = get(d)
        elif a.action == "suggest":
            res = suggest(d, x.get("scene"))
        elif a.action == "motif_set":
            res = motif_set(d, x)
        elif a.action == "motif_remove":
            res = motif_remove(d, x.get("id", ""))
        elif a.action == "spot_set":
            res = spot_set(d, x)
        elif a.action == "spot_remove":
            res = spot_remove(d, x.get("id", ""))
        elif a.action == "prompt":
            res = prompt(d, x.get("id", ""))
        elif a.action == "candidates":
            res = candidates(d, x.get("id", ""))
        elif a.action == "record_set":
            res = record_set(d, x.get("asset_id", ""), x)
        elif a.action == "to_cues":
            res = to_cues(d, x.get("scene"))
        else:
            res = report(d)
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
