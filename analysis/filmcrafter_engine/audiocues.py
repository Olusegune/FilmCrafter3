"""Audio cues: the planned soundscape of a scene. A cue says "this sound (or this music) belongs here": which asset, in which scene or shot, from when, for how long, how loud, how it fades.

  <Film>/audio/cues.json     {schema, cues: [...], removed: [...]}   (written with safeio; nothing is ever deleted: a removed cue moves to `removed` and can be brought back)

Cues are plans, not renders: nothing here makes sound, costs anything, or changes a recording, a take or a picture. Dialogue is not copied: the film's voice files stay where they are and are
listed beside the cues (read-only here); a stored dialogue cue only ever holds a person's adjustments to one of them (later stages).

A cue: {id, kind: dialogue|sfx|ambience|music, asset_id | null (a planned cue that still needs a sound), plan{description, search} for those, scene, shot|null, start (seconds from the start of
the shot, or of the scene when there is no shot), duration|null (null: the whole sound, or the whole shot), gain_db, fade_in, fade_out, loop, ducking (auto|on|off), approval: suggested|approved|rejected,
note, source: manual|director|quick, made_from{asset_sha1, shot_seconds, at}, created, updated}

`made_from` records what the cue was set up against; the listing says when the sound file was replaced, the shot got longer or shorter, or the shot is gone ("may need adjusting"), and never
changes the cue by itself. A person confirms with `refresh`.

  python -m filmcrafter_engine.audiocues <list|add|update|approve|remove|restore|refresh|quick|director_estimate|director_suggest> <film_dir> --data '{...}'
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid

from . import audiolib as AL
from . import safeio

KINDS = ("dialogue", "sfx", "ambience", "music")
APPROVALS = ("suggested", "approved", "rejected")
DUCKING = ("auto", "on", "off")
SOURCES = ("manual", "director", "quick")
ID = re.compile(r"^q-[0-9a-f]{8}$")
GAIN = (-60.0, 12.0)
FADE_MAX = 30.0
TIME_SLACK = 0.25                      # a shot that moved by less than this is not "a different length"
KEEP_REMOVED = 500
MAX_SUGGESTIONS = 8


def emit(**kw) -> None:
    try:
        print(json.dumps(kw), flush=True)
    except (OSError, ValueError):
        pass


def _text(v, limit: int = 600) -> str:
    return " ".join(str(v if v is not None else "").replace("\x00", "").split())[:limit]


def _path(d: str) -> str:
    return os.path.join(d, "audio", "cues.json")


def _empty() -> dict:
    return {"schema": 1, "cues": [], "removed": []}


def _ok(data) -> bool:
    return isinstance(data, dict) and isinstance(data.get("cues", []), list) and isinstance(data.get("removed", []), list)


def _normal(data: dict) -> dict:
    data.setdefault("schema", 1)
    data.setdefault("cues", [])
    data.setdefault("removed", [])
    return data


def _film(d: str) -> None:
    m = safeio.read_json(os.path.join(d, "film.json"), None)
    if not isinstance(m, dict) or "story" not in m:
        raise SystemExit("That isn't a FilmCrafter film.")


def _shots(d: str) -> dict:
    from . import shots as S
    v = S.view(d)
    return {s["id"]: s for s in v["shots"]}


def _scenes(shots: dict) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for s in shots.values():
        out.setdefault(int(s["scene"]), []).append(s)
    return out


def _asset(lib: dict, asset_id: str | None) -> dict | None:
    return next((a for a in lib["assets"] if a["id"] == asset_id), None) if asset_id else None


def _num(v, lo: float, hi: float, default: float, what: str) -> float:
    if v is None or v == "":
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise SystemExit(f"{what} must be a number.")
    if not (lo <= x <= hi):
        raise SystemExit(f"{what} must be between {lo:g} and {hi:g}.")
    return x


def _kind_for(asset: dict | None, kind: str | None) -> str:
    if kind in KINDS:
        return kind
    if asset and asset["kind"] == "music":
        return "music"
    return "ambience" if asset and asset.get("category") == "ambience" else "sfx"


# ---------------------------------------------------------------- reading

def _freshness(c: dict, lib: dict, shots: dict, d: str) -> list[dict]:
    """Why a cue may need another look (never changes it): the sound was replaced or taken out, the shot is gone or is a different length."""
    out = []
    mf = c.get("made_from") or {}
    if c.get("asset_id"):
        a = _asset(lib, c["asset_id"])
        if a is None:
            out.append({"code": "asset_removed", "why": "The sound was taken out of the library."})
        else:
            if mf.get("asset_sha1") and a.get("sha1") != mf["asset_sha1"]:
                out.append({"code": "asset_changed", "why": "The sound file is not the one this cue was set up with."})
            if not os.path.isfile(os.path.join(d, *a["file"].split("/"))):
                out.append({"code": "asset_missing", "why": "The sound file is missing from the film's audio folder."})
    if c.get("shot"):
        s = shots.get(c["shot"])
        if s is None:
            out.append({"code": "shot_gone", "why": "The shot this cue belongs to no longer exists."})
        else:
            was = mf.get("shot_seconds")
            if was is not None and abs(float(s["duration"]) - float(was)) > TIME_SLACK:
                out.append({"code": "timing_changed", "why": f"The shot is now {s['duration']:.1f} s (it was {float(was):.1f} s): the timing may need adjusting."})
            elif c.get("start", 0) > float(s["duration"]) + TIME_SLACK:
                out.append({"code": "after_shot", "why": "The cue starts after the end of the shot."})
    return out


def _derived_dialogue(d: str) -> list[dict]:
    """The film's voice files as read-only dialogue entries, so one list shows everything heard in a scene. Nothing is copied."""
    from . import voiceover as V
    out = []
    for s in V.status(d)["shots"]:
        for p in s["people"]:
            rec = p.get("recording")
            if p["lines"] and rec:
                out.append({"id": f"voice:{s['id']}:{p['key']}", "kind": "dialogue", "derived": True, "scene": int(s["scene"]), "shot": s["id"], "speaker": p["name"], "file": rec["file"], "duration": rec.get("seconds"),
                            "start": 0.0, "source": rec.get("source") or "recording", "text": " ".join(p["lines"])})
    return out


def listing(d: str, scene: int | None = None) -> dict:
    _film(d)
    cues = _normal(safeio.read_json(_path(d), _empty(), check=_ok))
    lib = AL.load(d)
    shots = _shots(d)
    rows = []
    for c in cues["cues"]:
        if scene is not None and int(c.get("scene", 0)) != int(scene):
            continue
        a = _asset(lib, c.get("asset_id"))
        rows.append({**c, "asset_name": a["name"] if a else None, "asset_file": a["file"] if a else None, "asset_seconds": a["seconds"] if a else None,
                     "fresh": _freshness(c, lib, shots, d), "needs_sound": not c.get("asset_id") and c.get("kind") != "dialogue"})
    dialogue = [x for x in _derived_dialogue(d) if scene is None or x["scene"] == int(scene)]
    by_scene = {n: {"shots": [{"id": s["id"], "seconds": s["duration"], "sound": shot_sound_text(d, s["id"])} for s in sorted(v, key=lambda s: s["index"])], "seconds": round(sum(s["duration"] for s in v), 1)}
                for n, v in _scenes(shots).items() if scene is None or n == int(scene)}
    return {"cues": rows, "dialogue": dialogue, "removed": [{"id": r["id"], "kind": r["kind"], "scene": r.get("scene")} for r in cues["removed"]], "scenes": by_scene,
            "counts": {"cues": len(cues["cues"]), "needs_sound": sum(1 for r in rows if r["needs_sound"]), "suggested": sum(1 for r in rows if r["approval"] == "suggested")}}


def shot_sound_text(d: str, sid: str) -> str:
    from . import shots as S
    return S._contract(d, sid).get("sound", "")


# ---------------------------------------------------------------- changing cues

def _clean_fields(c: dict, data: dict, shots: dict) -> None:
    """Apply the fields of `data` to cue `c`, validating each. Raises before anything is saved."""
    if "scene" in data or "shot" in data:
        scene = int(data.get("scene", c.get("scene", 0)) or 0)
        shot = data.get("shot", c.get("shot")) or None
        if shot:
            s = shots.get(str(shot))
            if not s:
                raise SystemExit("That shot isn't in the film.")
            scene = int(s["scene"])
        elif scene not in _scenes(shots):
            raise SystemExit("That scene isn't in the film.")
        c["scene"], c["shot"] = scene, (str(shot) if shot else None)
    if "start" in data:
        c["start"] = round(_num(data["start"], 0, 36000, 0.0, "The start"), 2)
    if "duration" in data:
        c["duration"] = None if data["duration"] in (None, "", 0) else round(_num(data["duration"], 0.1, 36000, 1.0, "The length"), 2)
    if "gain_db" in data:
        c["gain_db"] = round(_num(data["gain_db"], GAIN[0], GAIN[1], 0.0, "The level"), 1)
    if "foley" in data:
        c["foley"] = bool(data["foley"])                   # a sound made for what a shot shows (sounddesign.py): its own lane in the mix and in the pro export
    if "pan" in data:
        c["pan"] = round(_num(data["pan"], -1.0, 1.0, 0.0, "The pan"), 2)          # -1 all left, 0 centre, 1 all right (a balance, not a 3D position)
    for k in ("fade_in", "fade_out"):
        if k in data:
            c[k] = round(_num(data[k], 0, FADE_MAX, 0.0, "The fade"), 2)
    if "loop" in data:
        c["loop"] = bool(data["loop"])
    if "muted" in data:
        c["muted"] = bool(data["muted"])                   # left out of the film and the preview until switched back on; the cue and its sound are untouched
    if "ducking" in data:
        if data["ducking"] not in DUCKING:
            raise SystemExit("Ducking is auto, on or off.")
        c["ducking"] = data["ducking"]
    if "note" in data:
        c["note"] = _text(data["note"], 600)
    if "kind" in data:
        if data["kind"] not in KINDS:
            raise SystemExit("Choose dialogue, a sound effect, ambience or music.")
        c["kind"] = data["kind"]
    if isinstance(data.get("plan"), dict):
        c["plan"] = {"description": _text(data["plan"].get("description"), 400), "search": _text(data["plan"].get("search"), 200)}


def _anchor_seconds(c: dict, shots: dict) -> float | None:
    return float(shots[c["shot"]]["duration"]) if c.get("shot") in shots else None


def _stamp(c: dict, lib: dict, shots: dict) -> None:
    a = _asset(lib, c.get("asset_id"))
    c["made_from"] = {"asset_sha1": a["sha1"] if a else None, "shot_seconds": _anchor_seconds(c, shots), "at": int(time.time())}


def add(d: str, data: dict) -> dict:
    """Place a sound or music in a scene or shot (a person's own act, so it is approved), or plan one that still needs a sound (give `plan`)."""
    _film(d)
    shots = _shots(d)
    lib = AL.load(d)
    asset = _asset(lib, data.get("asset_id")) if data.get("asset_id") else None
    if data.get("asset_id") and not asset:
        raise SystemExit("That sound or music is not in this film's library.")
    if not asset and not isinstance(data.get("plan"), dict):
        raise SystemExit("Choose a sound from the library, or describe the sound to plan for.")
    kind = _kind_for(asset, data.get("kind"))
    src = data.get("source") if data.get("source") in SOURCES else "manual"
    approval = data.get("approval") if data.get("approval") in APPROVALS else ("approved" if src == "manual" else "suggested")
    holder: dict = {}

    def change(cues):
        cues = _normal(cues)
        taken = {c["id"] for c in cues["cues"]} | {c["id"] for c in cues["removed"]}
        cid = f"q-{uuid.uuid4().hex[:8]}"
        while cid in taken:
            cid = f"q-{uuid.uuid4().hex[:8]}"
        now = int(time.time())
        c = {"id": cid, "kind": kind, "asset_id": asset["id"] if asset else None, "scene": 0, "shot": None, "start": 0.0, "duration": None, "gain_db": 0.0, "pan": 0.0, "foley": False, "fade_in": 0.0, "fade_out": 0.0,
             "loop": bool(asset and asset.get("category") == "ambience"), "ducking": "auto", "muted": False, "approval": approval, "note": "", "source": src, "created": now, "updated": now}
        if "scene" not in data and "shot" not in data:
            raise SystemExit("Choose the scene or the shot this belongs to.")
        _clean_fields(c, data, shots)
        _stamp(c, lib, shots)
        cues["cues"].append(c)
        holder["id"] = cid
        return cues

    safeio.update_json(_path(d), change, _empty(), check=_ok)
    return {**listing(d), "id": holder["id"]}


def _find(cues: dict, cue_id: str) -> dict:
    if not ID.match(str(cue_id or "")):
        raise SystemExit("That cue id is not valid.")
    for c in cues["cues"]:
        if c["id"] == cue_id:
            return c
    raise SystemExit("That cue isn't in the film.")


def update(d: str, cue_id: str, data: dict) -> dict:
    """Change a cue's place, timing, level, fades, loop, ducking or note, or give a planned cue its sound (`asset_id`). The sound file itself is never touched."""
    _film(d)
    shots = _shots(d)
    lib = AL.load(d)

    def change(cues):
        cues = _normal(cues)
        c = _find(cues, cue_id)
        if "asset_id" in data:
            a = _asset(lib, data["asset_id"])
            if not a:
                raise SystemExit("That sound or music is not in this film's library.")
            c["asset_id"] = a["id"]
            c["kind"] = _kind_for(a, data.get("kind"))
            if data.get("keep_plan") is not True:
                c.pop("plan", None)
        _clean_fields(c, data, shots)
        if any(k in data for k in ("asset_id", "shot", "scene")):
            _stamp(c, lib, shots)
        c["updated"] = int(time.time())
        return cues

    safeio.update_json(_path(d), change, _empty(), check=_ok)
    return listing(d)


def approve(d: str, cue_id: str, state: str) -> dict:
    _film(d)
    if state not in APPROVALS:
        raise SystemExit("Choose approved, rejected or suggested.")

    def change(cues):
        cues = _normal(cues)
        c = _find(cues, cue_id)
        if state == "approved" and not c.get("asset_id") and c.get("kind") != "dialogue":
            c["approval"] = "approved"                                  # a planned cue can be approved as a plan; it still shows "needs a sound"
        else:
            c["approval"] = state
        c["updated"] = int(time.time())
        return cues

    safeio.update_json(_path(d), change, _empty(), check=_ok)
    return listing(d)


def refresh(d: str, cue_id: str) -> dict:
    """The person has looked at a cue flagged as possibly out of date and says it is fine: it is set up against the sound and the shot as they are now."""
    _film(d)
    shots, lib = _shots(d), AL.load(d)

    def change(cues):
        cues = _normal(cues)
        c = _find(cues, cue_id)
        _stamp(c, lib, shots)
        c["updated"] = int(time.time())
        return cues

    safeio.update_json(_path(d), change, _empty(), check=_ok)
    return listing(d)


def remove(d: str, cue_id: str) -> dict:
    _film(d)

    def change(cues):
        cues = _normal(cues)
        c = _find(cues, cue_id)
        cues["cues"] = [x for x in cues["cues"] if x["id"] != cue_id]
        cues["removed"].append({**c, "removed_at": int(time.time())})
        cues["removed"] = cues["removed"][-KEEP_REMOVED:]
        return cues

    safeio.update_json(_path(d), change, _empty(), check=_ok)
    return listing(d)


def restore(d: str, cue_id: str) -> dict:
    _film(d)

    def change(cues):
        cues = _normal(cues)
        r = next((x for x in cues["removed"] if x["id"] == cue_id), None)
        if not r:
            raise SystemExit("That cue was not removed.")
        cues["removed"] = [x for x in cues["removed"] if x["id"] != cue_id]
        cues["cues"].append({k: v for k, v in r.items() if k != "removed_at"})
        return cues

    safeio.update_json(_path(d), change, _empty(), check=_ok)
    return listing(d)


# ---------------------------------------------------------------- finding sounds that are already in the film

def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(w) > 2}


def match_assets(lib: dict, kind: str, terms: str, places: list[str] | None = None, scene: int | None = None, limit: int = 3) -> list[dict]:
    """Sounds already in the library that fit a description, best first. Looks at the name, tags, description, category and what the asset is linked to. Free and local; rejected sounds are never offered."""
    want = _tokens(terms)
    want_kind = "music" if kind == "music" else "sfx"
    rows = []
    for a in lib["assets"]:
        if a["kind"] != want_kind or a.get("approval") == "rejected":
            continue
        hay = _tokens(" ".join([a["name"], a.get("description", ""), a.get("category", ""), a.get("genre", ""), a.get("mood", ""), " ".join(a.get("tags", [])), " ".join(a.get("places", [])), " ".join(a.get("props", []))]))
        hits = want & hay
        score = len(hits) * 2 + (2 if kind == "ambience" and a.get("category") == "ambience" else 0)
        if places and {p.lower() for p in a.get("places", [])} & {p.lower() for p in places}:
            score += 2
        if scene is not None and str(scene) in [str(s) for s in a.get("scenes", [])]:
            score += 2
        if a.get("approval") == "approved":
            score += 1
        if hits or score >= 4:
            rows.append({"asset_id": a["id"], "name": a["name"], "score": score, "why": sorted(hits)[:4], "approved": a.get("approval") == "approved", "seconds": a["seconds"]})
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit]


# Free "quick ideas": plain keyword rules on the place and the action text, no AI. They only suggest.
QUICK = (
    (("rain", "storm", "downpour", "drizzle"), "ambience", "Rain falling", "rain falling steady"),
    (("wind", "windy", "breeze", "gust"), "ambience", "Wind", "wind breeze"),
    (("forest", "woods", "trees", "tree"), "ambience", "Forest ambience with birds", "forest birds leaves"),
    (("beach", "sea", "ocean", "waves", "shore"), "ambience", "Waves on the shore", "waves sea shore"),
    (("street", "city", "traffic", "road"), "ambience", "Distant city traffic", "city traffic street"),
    (("kitchen",), "ambience", "A quiet kitchen: a fridge hum, small clinks", "kitchen hum"),
    (("night",), "ambience", "Night air: crickets, distant quiet", "night crickets quiet"),
    (("school", "schoolyard", "playground", "yard"), "ambience", "Children playing in the distance", "children playground distant"),
    (("train", "platform", "station"), "ambience", "A station: distant announcements, a train", "train station platform"),
    (("crowd", "market", "party", "bar", "cafe", "café"), "ambience", "A murmuring crowd", "crowd murmur"),
    (("footsteps", "walks", "walking", "steps"), "sfx", "Footsteps", "footsteps walking"),
    (("door",), "sfx", "A door", "door"),
    (("kettle", "tea", "teapot", "cup"), "sfx", "Kettle and cups", "kettle tea cup"),
    (("pencil", "draws", "drawing", "sketchbook", "writes"), "sfx", "Pencil on paper", "pencil paper drawing"),
    (("phone", "rings", "ring"), "sfx", "A phone ringing", "phone ring"),
    (("car", "drives", "engine"), "sfx", "A car", "car engine"),
    (("laughs", "laugh", "giggles"), "sfx", "Light laughter", "laughter"),
    (("fire", "fireplace", "campfire"), "ambience", "A crackling fire", "fire crackle"),
)


def quick_ideas(d: str, scene: int) -> dict:
    """Free, on this computer: sound ideas read from the scene's place, time of day and what happens in it, plus the shots' own sound notes. Plain keyword rules, no AI; they only suggest."""
    from . import shots as S
    _film(d)
    shots = _shots(d)
    mine = [s for s in shots.values() if int(s["scene"]) == int(scene)]
    if not mine:
        raise SystemExit("That scene isn't in the film.")
    lib = AL.load(d)
    notes, text, places = [], [], []
    for s in sorted(mine, key=lambda s: s["index"]):
        c = S._contract(d, s["id"])
        text += [c.get("action", ""), c.get("story_purpose", ""), c["environment"]["name"], c.get("sound", "")] + [p if isinstance(p, str) else p.get("name", "") for p in c.get("props", [])]
        places.append(c["environment"]["name"])
        if c.get("sound"):
            notes.append({"shot": s["id"], "text": c["sound"]})
    words = _tokens(" ".join(text))
    ideas, seen = [], set()
    for keys, kind, what, search in QUICK:
        hit = [k for k in keys if k in words]
        if hit and what not in seen:
            seen.add(what)
            ideas.append({"kind": kind, "what": what, "why": f"The scene mentions {hit[0]}.", "search": search, "shot": None, "loop": kind == "ambience", "matches": match_assets(lib, kind, search + " " + what, places, scene)})
    for n in notes:                                                   # what the shot's own sound note says is the strongest hint
        ideas.insert(0, {"kind": "sfx", "what": n["text"][:120], "why": f"Written in {n['shot']}'s sound note.", "search": n["text"][:80], "shot": n["shot"], "loop": False, "matches": match_assets(lib, "sfx", n["text"], places, scene)})
    return {"scene": int(scene), "ideas": ideas[:MAX_SUGGESTIONS], "source": "quick"}


# ---------------------------------------------------------------- the sound director (the writing AI proposes; the person decides)

def _schema(props: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


DIRECTOR_SYSTEM = ("You are a sound designer helping a film director plan the soundscape of ONE scene. Use only what the scene, the shot notes and the film's sound style show, plus modest, fitting inference. "
                   "Suggest between three and eight cues: the ambience of the place and time of day, weather, small sounds tied to what people and props do, and, only if it serves the emotion, one musical "
                   "idea (or silence). Quiet is a choice: do not fill every moment. For each cue give: kind (ambience, sfx or music), a short description of the sound as you would search for it, the "
                   "single shot id it belongs to (or an empty string for the whole scene), whether it should loop, a one-sentence reason, and a few search words. Never invent plot, people or props.")
DIRECTOR_SCHEMA = _schema({"cues": {"type": "array", "items": _schema({"kind": {"type": "string"}, "what": {"type": "string"}, "shot": {"type": "string"}, "loop": {"type": "boolean"}, "why": {"type": "string"},
                                                                       "search": {"type": "string"}})}})


def director_brief(d: str, scene: int) -> dict:
    from . import bible as B
    from . import shots as S
    _film(d)
    shots = _shots(d)
    mine = sorted([s for s in shots.values() if int(s["scene"]) == int(scene)], key=lambda s: s["index"])
    if not mine:
        raise SystemExit("That scene isn't in the film.")
    b = B.load(d)
    lib = AL.load(d)
    envs = {e["name"].lower(): e for e in b["environments"]}
    out_shots, place = [], ""
    for s in mine:
        c = S._contract(d, s["id"])
        place = c["environment"]["name"]
        out_shots.append({"id": s["id"], "seconds": s["duration"], "action": c.get("action", "")[:300], "purpose": c.get("story_purpose", "")[:200], "sound_note": c.get("sound", ""),
                          "people": [x["name"] for x in c["characters"]], "props": [p if isinstance(p, str) else p.get("name", "") for p in c.get("props", [])], "feeling": c["performance"].get("emotional_intention", "")})
    env = envs.get(place.lower(), {})
    return {"task": "plan the soundscape of one scene", "scene": int(scene), "place": place, "place_notes": {k: v for k, v in {**(env.get("spatial") or {}), "description": env.get("description", "")}.items() if v},
            "shots": out_shots, "tone": b["rules"].get("tone", ""), "sound_style": {k: v for k, v in {**b["sound_style"]["sound"], **{f"music_{k}": x for k, x in b["sound_style"]["music"].items()}}.items() if v},
            "already_in_the_library": [{"id": a["id"], "name": a["name"], "kind": a["kind"], "category": a["category"]} for a in lib["assets"] if a.get("approval") != "rejected"][:60]}


def director_estimate(d: str, scene: int) -> dict:
    from .acting import _estimate
    br = director_brief(d, scene)
    return {**_estimate(len(json.dumps(br, ensure_ascii=False)) + len(DIRECTOR_SYSTEM), 1, 800), "sends": "this scene's shots, the place, your sound style and the names of sounds already in your library"}


def clean_director(out: dict, valid_shots: set[str], lib: dict, scene: int, places: list[str]) -> list[dict]:
    """Keep what is usable: a known kind, a shot that is in this scene (else the whole scene), trimmed words; look in the library first for each."""
    res = []
    for c in (out.get("cues") or []):
        if not isinstance(c, dict):
            continue
        kind = c.get("kind") if c.get("kind") in ("ambience", "sfx", "music") else ""
        what = _text(c.get("what"), 160)
        if not kind or not what:
            continue
        shot = _text(c.get("shot"), 20)
        shot = shot if shot in valid_shots else None
        search = _text(c.get("search"), 120) or what
        res.append({"kind": kind, "what": what, "why": _text(c.get("why"), 240), "shot": shot, "loop": bool(c.get("loop")) and kind == "ambience", "search": search,
                    "matches": match_assets(lib, kind, search + " " + what, places, scene)})
        if len(res) >= MAX_SUGGESTIONS:
            break
    return res


def director_suggest(d: str, scene: int) -> dict:
    """Ask the configured writing AI for a soundscape for the scene. Returns suggestions with what the library already has for each; saves nothing and generates nothing."""
    from . import assist as A
    from .director import DEFAULT_MODEL, openai_error, resolve_model
    from .llm import client as make_client
    br = director_brief(d, scene)
    cl = make_client()
    model = resolve_model(cl, DEFAULT_MODEL)
    emit(event="progress", stage="listening to the scene", progress=0.3)
    try:
        out = A._call(cl, model, DIRECTOR_SYSTEM, json.dumps(br, ensure_ascii=False), "soundscape", DIRECTOR_SCHEMA)
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(openai_error(e))
    lib = AL.load(d)
    return {"scene": int(scene), "ideas": clean_director(out, {s["id"] for s in br["shots"]}, lib, int(scene), [br["place"]]), "source": "director", "model": str(model), "estimate": director_estimate(d, scene)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="audiocues")
    ap.add_argument("action", choices=["list", "add", "update", "approve", "remove", "restore", "refresh", "quick", "director_estimate", "director_suggest"])
    ap.add_argument("film")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        d = os.path.abspath(a.film)
        act = a.action
        if act == "list":
            res = listing(d, x.get("scene"))
        elif act == "add":
            res = add(d, x)
        elif act == "update":
            res = update(d, x.get("id", ""), x)
        elif act == "approve":
            res = approve(d, x.get("id", ""), x.get("state", ""))
        elif act == "remove":
            res = remove(d, x.get("id", ""))
        elif act == "restore":
            res = restore(d, x.get("id", ""))
        elif act == "refresh":
            res = refresh(d, x.get("id", ""))
        elif act == "quick":
            res = quick_ideas(d, x.get("scene", 0))
        elif act == "director_estimate":
            res = director_estimate(d, x.get("scene", 0))
        else:
            res = director_suggest(d, x.get("scene", 0))
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
