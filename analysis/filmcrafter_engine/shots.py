"""Scenes and shots: the story broken down by a director, each shot a renderer-independent Shot Contract.

  <Film>/shots/index.json          the order of the shots, and which story version they were drafted from
  <Film>/shots/<id>/contract.json  one Shot Contract: purpose, characters and their states, place, action, dialogue, performance, camera, lighting, continuity
  <Film>/shots/_removed/           shots taken out (never deleted)

The first pass is a draft made with plain rules (a wide to open each scene, coverage for each exchange, an insert for a held detail). It is a starting
point to change, not an answer: nothing is rewritten once you have edited a shot, and re-running a breakdown never touches an edited shot.
Camera and light are suggested with a reason, from what the shot is meant to make the audience feel, and only applied when you ask.

  python -m filmcrafter_engine.shots <action> <film_dir> --data '{...}'
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
import time

from . import safeio
from .safe import check_id

SCHEMA = 1
FRAMING = ("establishing", "wide", "medium", "close-up", "extreme close-up", "over the shoulder", "point of view", "insert")
ANGLE = ("eye level", "low", "high", "dutch", "overhead")
LENS = ("wide (24mm)", "normal (35mm)", "portrait (50mm)", "telephoto (85mm+)", "macro")
MOVEMENT = ("locked off", "push in", "pull out", "pan", "tilt", "dolly", "tracking", "orbit", "crane", "handheld", "rack focus", "subject tracking")
FOCUS = ("deep", "shallow", "rack", "follow")
DOF = ("very shallow", "shallow", "medium", "deep")      # how much is in focus, chosen like an aperture (dof.py); empty is automatic
CUT_MAX = 2.0                                           # a J or L cut: how many seconds a line may lead or trail its picture
LIMIT = 4000
MAX_PER_SCENE = 8
BEAT_FIELDS = ("character", "what", "want", "need", "fear", "hiding", "subtext", "start", "turn", "end")


def emit(**kw) -> None:
    try:
        print(json.dumps(kw), flush=True)
    except (OSError, ValueError):
        pass


def _read(path, default=None):
    """Absent -> default. A damaged file is never mistaken for an absent one (see safeio): its bytes are kept and the last good copy is used, or the person is told."""
    return safeio.read_json(path, default)


def _write(path, data) -> None:
    safeio.write_json(path, data)


def _text(v, limit: int = LIMIT) -> str:
    return str(v if v is not None else "").replace("\x00", "").strip()[:limit]


def _film(d: str) -> dict:
    m = _read(os.path.join(d, "film.json"))
    if not isinstance(m, dict) or "story" not in m:
        raise SystemExit("That isn't a FilmCrafter film.")
    return m


def _index(d: str) -> dict:
    i = _read(os.path.join(d, "shots", "index.json"))
    return i if isinstance(i, dict) and "order" in i else {"schema": SCHEMA, "order": [], "story_version": None, "scenes": {}}


def _save_index(d: str, i: dict) -> None:
    _write(os.path.join(d, "shots", "index.json"), i)


def _cpath(d: str, sid: str) -> str:
    return os.path.join(d, "shots", check_id(sid, "shot"), "contract.json")


def _contract(d: str, sid: str) -> dict:
    c = _read(_cpath(d, sid))
    if not isinstance(c, dict):
        raise SystemExit("That shot doesn't exist.")
    return c


# ---------------------------------------------------------------- reading the scenes into blocks

def scene_blocks(text: str) -> list[dict]:
    """The script as scenes, each a list of action and dialogue blocks."""
    from . import story
    lines = story._norm(text).split("\n")
    scenes: list[dict] = []
    cur: dict | None = None
    has_headings = any(story.SLUG.match(x.strip()) for x in lines)
    prev_blank, in_dlg, blk = True, False, None
    for i, raw in enumerate(lines):
        s = raw.strip()
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if not s:
            prev_blank, in_dlg, blk = True, False, None
            continue
        if story.SLUG.match(s) and prev_blank:
            cur = {"number": len(scenes) + 1, "heading": story.clean_heading(s), **story._heading_parts(s), "blocks": []}
            scenes.append(cur)
            prev_blank, in_dlg, blk = False, False, None
            continue
        if cur is None:
            cur = {"number": 1, "heading": "Opening", "int_ext": "", "location": "", "time": "", "blocks": [], "implied": True}
            scenes.append(cur)
        if not in_dlg and not (cur.get("implied") and has_headings) and story._is_cue(raw, prev_blank, nxt):          # lines before the first scene heading are a title page (an all-capitals title is not a speaker)
            blk = {"type": "dialogue", "speaker": story.CUE_NOTE.sub("", s).strip().lstrip("@").strip(), "paren": "", "lines": []}
            ext = story.CUE_NOTE.search(s)                                 # (V.O.) and (O.S.) say that nobody on screen speaks this line: kept, not thrown away with the note
            if ext and re.search(r"V\.?O|O\.?S", ext.group(0), re.I):
                blk["ext"] = "V.O." if re.search(r"V\.?O", ext.group(0), re.I) else "O.S."
            cur["blocks"].append(blk)
            in_dlg = True
        elif in_dlg and blk is not None:
            if s.startswith("(") and s.endswith(")"):
                blk["paren"] = s.strip("() ")
            else:
                blk["lines"].append(s)
        elif story.TRANSITION.match(s):
            pass
        else:
            if blk is None or blk["type"] != "action":
                blk = {"type": "action", "lines": []}
                cur["blocks"].append(blk)
            blk["lines"].append(s)
        prev_blank = False
    if len(scenes) > 1 and scenes[0].get("implied") and not any(x["type"] == "dialogue" for x in scenes[0]["blocks"]):          # a title page is not a scene
        scenes = scenes[1:]
        for i, sc in enumerate(scenes, 1):
            sc["number"] = i
    return scenes


# ---------------------------------------------------------------- the first draft

def _blank(sid: str, scene: dict, n: int, version: int | None) -> dict:
    return {"schema": SCHEMA, "id": sid, "scene": scene["number"], "index": n, "story_version": version, "title": "", "status": "draft", "edited": False,
            "story_purpose": "", "action": "", "dialogue": [], "characters": [], "environment": {"id": None, "name": scene.get("location", "").title(), "state_id": None},
            "props": [], "blocking": "",
            "performance": {"emotional_intention": "", "beats": [], "micro_animation": ""},
            "camera": {"framing": "", "angle": "eye level", "position": "", "lens": "", "movement": "locked off", "focus": "", "why": ""},
            "lighting": {"description": "", "time": scene.get("time", "").title(), "why": ""},
            "opening_state": "", "closing_state": "", "continuity": "", "reference_assets": [], "sound": "",
            "generation": {"duration": 3.0, "aspect": "", "notes": ""}, "locks": {"storyboard": False, "keyframe": False}}


def _seconds(words: int, dialogue: bool) -> float:
    return round(min(12.0, max(2.0, words / 2.5 + 1.0 if dialogue else words / 3.0 + 1.5)), 1)


_GENERIC = {"woman", "man", "girl", "boy", "friend", "mother", "father", "kid", "child", "teacher", "voice", "crowd"}


def _named_in(text: str, names: list[str], group: list[str] | None = None) -> list[str]:
    """Which of the film's people are named in some action text, in the order they appear: a full name, a last name only the one person has, a numbered person
    written as in the script or as "Friend 1", and, with `group` (the numbered people who speak in this scene), a plural: "two friends" means Friend #1 and Friend #2."""
    last: dict[str, list[str]] = {}
    for n in names:
        w = n.split()[-1].lower() if len(n.split()) > 1 else ""
        if w and "#" not in n and len(w) >= 3 and w not in _GENERIC:
            last.setdefault(w, []).append(n)
    low = text.lower()
    found: list[tuple[int, str]] = []
    for n in names:
        if "#" in n:
            base, _, num = n.partition("#")
            base, num = base.strip().lower(), num.strip()
            m = re.search(r"(?<![a-z0-9])" + re.escape(base) + r"\s*#?\s*" + re.escape(num) + r"(?![0-9])", low) if base and num else None
            if m:
                found.append((m.start(), n))
            continue
        forms = [n.lower()] + [w for w, who in last.items() if who == [n]]
        hits = [m.start() for f in forms for m in re.finditer(r"(?<![a-z0-9])" + re.escape(f) + r"(?![a-z0-9])", low)]
        if hits:
            found.append((min(hits), n))
    for n in group or []:                                          # "with two friends in tow": the scene's numbered friends
        base = n.partition("#")[0].strip().lower()
        if "#" in n and len(base) >= 3 and n not in [x for _, x in found]:
            m = re.search(r"(?<![a-z0-9])" + re.escape(base) + r"(?:s|es)(?![a-z0-9])", low)
            if m:
                found.append((m.start(), n))
    return [n for _, n in sorted(found)]


def _props_in(text: str, props: list[str]) -> list[str]:
    """Which of the film's props the text names (the whole name, or its plural), in the order they appear."""
    low = text.lower()
    found: list[tuple[int, str]] = []
    for p in props:
        n = p.strip().lower()
        if len(n) < 3:
            continue
        m = re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?:s|es)?(?![a-z0-9])", low)
        if m:
            found.append((m.start(), p))
    return [p for _, p in sorted(found)]


def _draft_scene(scene: dict, version: int | None, names: list[str] | None = None, props: list[str] | None = None) -> list[dict]:
    blocks = scene["blocks"]
    in_scene = list(dict.fromkeys(b["speaker"] for b in blocks if b["type"] == "dialogue"))       # who speaks in this scene (the numbered group members among them)
    shots: list[dict] = []
    place = scene.get("location", "").title()
    first_action = next((b for b in blocks if b["type"] == "action"), None)

    def add(framing: str, purpose: str, action: str = "", dialogue: list | None = None, speakers: list | None = None, words: int = 8, is_dlg: bool = False) -> None:
        if len(shots) >= MAX_PER_SCENE:
            return
        sh = _blank("", scene, len(shots) + 1, version)
        sh["story_purpose"], sh["action"] = purpose, action[:700]
        sh["dialogue"] = dialogue or []
        who = list(speakers or []) if speakers else _named_in(action, names or [], in_scene)          # the people speaking; or, in an action shot, the people the action names
        sh["characters"] = [{"name": n, "character_id": None, "state_id": None, "wardrobe_id": None} for n in who]
        sh["props"] = [{"name": p, "prop_id": None, "state": ""} for p in _props_in(action, props or [])]          # the props the shot's action names
        sh["camera"]["framing"] = framing
        sh["generation"]["duration"] = _seconds(words, is_dlg)
        shots.append(sh)

    where = f"{place} ({scene.get('int_ext', '')}{', ' + scene['time'].title() if scene.get('time') else ''})".replace(" ()", "").replace("(, ", "(")
    if place or first_action:
        text = " ".join(first_action["lines"]) if first_action else ""
        add("establishing" if scene.get("int_ext") == "EXT" else "wide", f"Show where we are: {where}." if place else "Open the scene.", text, words=len(text.split()))
    used_first = first_action
    run: list[dict] = []

    def flush() -> None:
        nonlocal run
        if not run:
            return
        speakers = list(dict.fromkeys(b["speaker"] for b in run))
        dlg = [{"speaker": b["speaker"], "line": " ".join(b["lines"]), "paren": b.get("paren", ""), **({"ext": b["ext"]} if b.get("ext") else {})} for b in run]
        words = sum(len(x["line"].split()) for x in dlg)
        if len(speakers) >= 2:
            turns: list[list[dict]] = []
            for x in dlg:
                if turns and turns[-1][0]["speaker"] == x["speaker"]:
                    turns[-1].append(x)
                else:
                    turns.append([x])
            for t in turns[:4]:
                w = sum(len(x["line"].split()) for x in t)
                add("over the shoulder", f"{t[0]['speaker'].title()} speaks to {', '.join(s.title() for s in speakers if s != t[0]['speaker'])}.", "", t, [t[0]["speaker"]] + [s for s in speakers if s != t[0]["speaker"]], w, True)
        else:
            short = words <= 8
            add("close-up" if short else "medium", f"{speakers[0].title()} speaks.", "", dlg, speakers, words, True)
        run = []

    last_speaker = ""
    for b in blocks:
        if b is used_first:
            continue
        if b["type"] == "dialogue":
            run.append(b)
            last_speaker = b["speaker"]
            continue
        flush()
        text = " ".join(b["lines"])
        held = re.search(r"\b(hand|hands|letter|phone|ring|key|photo|photograph|glass|cup|door|window|clock|note|knife|gun)\b", text, re.I)
        who, named = None, _named_in(text, names or [])
        if len(named) == 1:
            last_speaker = named[0]                                    # "Chloe keeps drawing." then "She does not look up." is Chloe
        if last_speaker and not named and re.match(r"(?i)\s*(she|he|her|his|him|they)\b", text):
            who = [last_speaker]                                       # "She wrinkles her nose" straight after someone's line is about that person
        add("insert" if held and len(text.split()) <= 14 else "medium", "Show what happens." if not held else f"A detail that matters: {held.group(1)}.", text, speakers=who, words=len(text.split()))
    flush()
    if not shots:
        add("wide", "Open the scene.", "", words=6)
    return shots


def _link(c: dict, bible: dict) -> None:
    """Link people and the place to the Bible by name, so the shot refers to the one canonical entry."""
    chars = {x["name"].lower(): x for x in bible.get("characters", [])}
    envs = {x["name"].lower(): x for x in bible.get("environments", [])}
    for pr in c.get("props", []):
        hit = next((x for x in bible.get("props", []) if x["name"].lower() == pr["name"].lower()), None)
        if hit:
            pr["prop_id"] = hit["id"]
    for ch in c["characters"]:
        hit = chars.get(ch["name"].lower())
        if hit:
            ch["character_id"], ch["state_id"] = hit["id"], hit["states"][0]["id"]
    e = envs.get(c["environment"]["name"].lower())
    if e:
        c["environment"].update({"id": e["id"], "state_id": e["states"][0]["id"]})


def breakdown(d: str, scene: int | None = None) -> dict:
    """Draft shots for the scenes that have none (or, with `scene`, for one scene whose shots are all untouched drafts). Edited shots are never changed."""
    from . import bible as B
    from . import story
    m = _film(d)
    ver = m["story"].get("locked") or m["story"]["current"]
    rec = _read(story._vpath(d, int(ver)))
    if not rec:
        raise SystemExit("The story isn't there to break down.")
    if rec["kind"] != "screenplay":
        raise SystemExit("Break down a screenplay. This is still a " + rec["kind"] + ": write the screenplay as a new version first.")
    idx = _index(d)
    cons = {sid: _contract(d, sid) for sid in idx["order"]}
    bible = B.load(d)
    made = []
    all_scenes = scene_blocks(rec["text"])
    names = list(dict.fromkeys([b["speaker"] for s in all_scenes for b in s["blocks"] if b["type"] == "dialogue"] + [x["name"].upper() for x in bible.get("characters", [])]))
    for sc in all_scenes:
        if scene is not None and sc["number"] != int(scene):
            continue
        mine = [sid for sid in idx["order"] if cons[sid]["scene"] == sc["number"]]
        if mine:
            if scene is None:
                continue                                           # a scene that already has shots is left alone
            if any(cons[s]["edited"] for s in mine):
                raise SystemExit("Some shots in that scene have been edited, so they were left as they are. Delete the ones you don't want, then try again.")
            for s in mine:
                _archive(d, s)
                idx["order"].remove(s)
        drafts = _draft_scene(sc, ver, names, [x["name"] for x in bible.get("props", [])])
        for n, c in enumerate(drafts, 1):
            c["id"] = f"S{sc['number']:02d}-{n:02d}"
            while os.path.exists(os.path.dirname(_cpath(d, c["id"]))):
                n += 1
                c["id"] = f"S{sc['number']:02d}-{n:02d}"
            c["index"] = n
            c["title"] = c["story_purpose"][:60]
            _link(c, bible)
            _write(_cpath(d, c["id"]), c)
            made.append(c["id"])
            idx["order"].append(c["id"])
            cons[c["id"]] = c
    idx["order"].sort(key=lambda s: (cons[s]["scene"], cons[s]["index"]) if s in cons else (999, 0))
    idx["story_version"] = ver
    _save_index(d, idx)
    return {**view(d), "made": made}


def _archive(d: str, sid: str, into: str | None = None) -> None:
    from . import voiceover
    voiceover.shot_gone(d, sid, into)                        # its recordings move with it (joined into another shot) or are put aside, never left under an id that may be used again
    src = os.path.join(d, "shots", sid)
    if os.path.isdir(src):
        dst = os.path.join(d, "shots", "_removed", f"{sid}-{int(time.time())}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)


# ---------------------------------------------------------------- editing a contract

def _clean_list(v, limit_each: int = 200, cap: int = 30) -> list[str]:
    return [_text(x, limit_each) for x in (v or []) if _text(x, limit_each)][:cap]


def set_fields(d: str, sid: str, patch: dict) -> dict:
    """Change a shot's contract. Only known fields are taken, each trimmed and limited; the camera words must be from the lists."""
    c = _contract(d, sid)
    for k in ("title", "story_purpose", "action", "blocking", "opening_state", "closing_state", "continuity", "sound"):
        if k in patch:
            c[k] = _text(patch[k], 120 if k == "title" else LIMIT)
    if "production" in patch:                            # how the shot is made: a full scene, or a plate to key (vpstudio)
        from . import vpstudio
        c["production"] = vpstudio.clean_production(patch["production"])
    if "plan" in patch:                                  # the top-down blocking plan (blocking.py); None clears it
        from . import blocking
        c["plan"] = blocking.clean(patch["plan"])
    if "dialogue" in patch:
        c["dialogue"] = [{"speaker": _text(x.get("speaker"), 60), "line": _text(x.get("line")), "paren": _text(x.get("paren"), 100), **({"ext": x["ext"]} if x.get("ext") in ("V.O.", "O.S.") else {})} for x in (patch["dialogue"] or []) if isinstance(x, dict)][:60]
    if "characters" in patch:
        c["characters"] = [{"name": _text(x.get("name"), 80), "character_id": _text(x.get("character_id"), 64) or None, "state_id": _text(x.get("state_id"), 16) or None,
                            "wardrobe_id": _text(x.get("wardrobe_id"), 16) or None} for x in (patch["characters"] or []) if isinstance(x, dict) and _text(x.get("name"), 80)][:20]
    if isinstance(patch.get("environment"), dict):
        e = patch["environment"]
        for k, n in (("id", 64), ("name", 80), ("state_id", 16)):
            if k in e:
                c["environment"][k] = _text(e[k], n) or (None if k != "name" else "")
    if "props" in patch:
        c["props"] = [{"name": _text(x.get("name"), 80), "prop_id": _text(x.get("prop_id"), 64) or None, "state": _text(x.get("state"), 80)} for x in (patch["props"] or []) if isinstance(x, dict) and _text(x.get("name"), 80)][:30]
    if "reference_assets" in patch:
        c["reference_assets"] = _clean_list(patch["reference_assets"], 300, 20)
    perf = patch.get("performance")
    if isinstance(perf, dict):
        for k in ("emotional_intention", "micro_animation"):
            if k in perf:
                c["performance"][k] = _text(perf[k])
        if "beats" in perf:
            c["performance"]["beats"] = [{k: _text(b.get(k), 600) for k in BEAT_FIELDS} for b in (perf["beats"] or []) if isinstance(b, dict)][:20]
    cam = patch.get("camera")
    if isinstance(cam, dict):
        for k, allowed in (("framing", FRAMING), ("angle", ANGLE), ("lens", LENS), ("movement", MOVEMENT), ("focus", FOCUS)):
            if k in cam:
                v = _text(cam[k], 40)
                if v and v not in allowed:
                    raise SystemExit(f"Choose a {k} from the list.")
                c["camera"][k] = v
        if "dof" in cam:
            v = _text(cam["dof"], 20)
            if v and v not in DOF:
                raise SystemExit("Choose a depth of field from the list.")
            c["camera"]["dof"] = v
        for k in ("position", "why"):
            if k in cam:
                c["camera"][k] = _text(cam[k])
    cut = patch.get("sound_cut")
    if isinstance(cut, dict):                                                  # J and L cuts: the line starts before its picture (lead) or carries on over the next picture (tail)
        cur = dict(c.get("sound_cut") or {})
        for k in ("lead", "tail"):
            if k in cut:
                try:
                    cur[k] = round(max(0.0, min(CUT_MAX, float(cut[k] or 0))), 1)
                except (TypeError, ValueError):
                    raise SystemExit("A lead or a tail is a number of seconds.")
        c["sound_cut"] = {"lead": cur.get("lead", 0.0), "tail": cur.get("tail", 0.0)}
    lit = patch.get("lighting")
    if isinstance(lit, dict):
        for k in ("description", "time", "why"):
            if k in lit:
                c["lighting"][k] = _text(lit[k])
    gen = patch.get("generation")
    if isinstance(gen, dict):
        if "duration" in gen:
            try:
                c["generation"]["duration"] = round(max(1.0, min(30.0, float(gen["duration"]))), 1)
            except (TypeError, ValueError):
                raise SystemExit("The length must be a number of seconds.")
        for k in ("aspect", "notes"):
            if k in gen:
                c["generation"][k] = _text(gen[k], 200 if k == "aspect" else LIMIT)
    if c.get("locks", {}).get("storyboard") and any(k in patch for k in ("camera", "blocking", "characters", "environment", "plan")) and not patch.get("_unlock"):
        raise SystemExit("This shot's storyboard is locked, so its framing can't change. Unlock the storyboard first.")
    c["edited"] = True
    _write(_cpath(d, sid), c)
    return {**view(d), "shot": c}


def get_shot(d: str, sid: str) -> dict:
    _film(d)
    return {"shot": _contract(d, sid)}


# ---------------------------------------------------------------- the list

def view(d: str) -> dict:
    m = _film(d)
    idx = _index(d)
    shots = []
    for sid in idx["order"]:
        c = _read(_cpath(d, sid))
        if isinstance(c, dict):
            shots.append({k: c[k] for k in ("id", "scene", "index", "title", "status", "edited", "story_purpose", "camera", "locks")} |
                         {"duration": c["generation"]["duration"], "characters": [x["name"] for x in c["characters"]], "has_dialogue": bool(c["dialogue"]), "environment": c["environment"]["name"]})
    scenes: dict[int, dict] = {}
    for sh in shots:
        s = scenes.setdefault(sh["scene"], {"number": sh["scene"], "shots": 0, "seconds": 0.0})
        s["shots"] += 1
        s["seconds"] = round(s["seconds"] + sh["duration"], 1)
    return {"title": m["title"], "story_version": idx.get("story_version"), "shots": shots, "scenes": list(scenes.values()),
            "seconds": round(sum(s["duration"] for s in shots), 1), "enums": {"framing": list(FRAMING), "angle": list(ANGLE), "lens": list(LENS), "movement": list(MOVEMENT), "focus": list(FOCUS), "dof": list(DOF)}, "cut_max": CUT_MAX}


def add(d: str, scene: int, after: str | None = None) -> dict:
    idx = _index(d)
    cons = {s: _contract(d, s) for s in idx["order"]}
    n = max([c["index"] for c in cons.values() if c["scene"] == int(scene)] + [0]) + 1
    sid = f"S{int(scene):02d}-{n:02d}"
    sc = {"number": int(scene), "location": "", "time": ""}
    c = _blank(sid, sc, n, idx.get("story_version"))
    c.update({"edited": True, "title": "New shot"})
    c["camera"]["framing"] = "medium"
    _write(_cpath(d, sid), c)
    pos = idx["order"].index(after) + 1 if after in idx["order"] else len([s for s in idx["order"] if cons[s]["scene"] <= int(scene)])
    idx["order"].insert(pos, sid)
    _save_index(d, idx)
    return {**view(d), "id": sid}


def duplicate(d: str, sid: str) -> dict:
    idx = _index(d)
    src = _contract(d, sid)
    cons = [_contract(d, s) for s in idx["order"]]
    n = max([c["index"] for c in cons if c["scene"] == src["scene"]] + [0]) + 1
    new = copy.deepcopy(src)
    new.update({"id": f"S{src['scene']:02d}-{n:02d}", "index": n, "title": (src["title"] + " (copy)")[:120], "edited": True, "locks": {"storyboard": False, "keyframe": False}})
    _write(_cpath(d, new["id"]), new)
    idx["order"].insert(idx["order"].index(sid) + 1, new["id"])
    _save_index(d, idx)
    return {**view(d), "id": new["id"]}


def delete(d: str, sid: str) -> dict:
    """Take a shot out. It moves to shots/_removed, never deleted."""
    idx = _index(d)
    check_id(sid, "shot")
    if sid not in idx["order"]:
        raise SystemExit("That shot doesn't exist.")
    _archive(d, sid)
    idx["order"].remove(sid)
    _save_index(d, idx)
    return view(d)


def move(d: str, sid: str, delta: int) -> dict:
    idx = _index(d)
    if sid not in idx["order"]:
        raise SystemExit("That shot doesn't exist.")
    i = idx["order"].index(sid)
    j = max(0, min(len(idx["order"]) - 1, i + int(delta)))
    idx["order"].insert(j, idx["order"].pop(i))
    _save_index(d, idx)
    return view(d)


def merge(d: str, sid: str) -> dict:
    """Join a shot with the one after it (in the same scene): their action and dialogue are combined and the second is taken out."""
    idx = _index(d)
    if sid not in idx["order"]:
        raise SystemExit("That shot doesn't exist.")
    i = idx["order"].index(sid)
    a = _contract(d, sid)
    nxt = idx["order"][i + 1] if i + 1 < len(idx["order"]) else None
    b = _contract(d, nxt) if nxt else None
    if not b or b["scene"] != a["scene"]:
        raise SystemExit("There is no shot after this one in the same scene.")
    a["action"] = (a["action"] + " " + b["action"]).strip()[:LIMIT]
    a["dialogue"] += b["dialogue"]
    names = {x["name"].lower() for x in a["characters"]}
    a["characters"] += [x for x in b["characters"] if x["name"].lower() not in names]
    a["generation"]["duration"] = round(min(30.0, a["generation"]["duration"] + b["generation"]["duration"]), 1)
    a["edited"] = True
    _write(_cpath(d, sid), a)
    _archive(d, nxt, into=sid)
    idx["order"].remove(nxt)
    _save_index(d, idx)
    return view(d)


def split(d: str, sid: str) -> dict:
    """Cut a shot in two: the dialogue (or, with none, the action sentences) divided at the middle."""
    idx = _index(d)
    a = _contract(d, sid)
    if sid not in idx["order"]:
        raise SystemExit("That shot doesn't exist.")
    b = copy.deepcopy(a)
    if len(a["dialogue"]) >= 2:
        h = len(a["dialogue"]) // 2
        a["dialogue"], b["dialogue"] = a["dialogue"][:h], a["dialogue"][h:]
    else:
        sents = re.split(r"(?<=[.!?])\s+", a["action"].strip())
        if len(sents) < 2:
            raise SystemExit("There is nothing to split: the shot needs two lines of dialogue or two sentences of action.")
        h = len(sents) // 2
        a["action"], b["action"] = " ".join(sents[:h]), " ".join(sents[h:])
    half = round(max(1.0, a["generation"]["duration"] / 2), 1)
    a["generation"]["duration"] = b["generation"]["duration"] = half
    cons = [_contract(d, s) for s in idx["order"]]
    n = max([c["index"] for c in cons if c["scene"] == a["scene"]] + [0]) + 1
    b.update({"id": f"S{a['scene']:02d}-{n:02d}", "index": n, "edited": True, "locks": {"storyboard": False, "keyframe": False}})
    a["edited"] = True
    _write(_cpath(d, sid), a)
    _write(_cpath(d, b["id"]), b)
    idx["order"].insert(idx["order"].index(sid) + 1, b["id"])
    _save_index(d, idx)
    return {**view(d), "id": b["id"]}


# ---------------------------------------------------------------- suggestions, with a reason

FEEL = [
    (r"tense|fear|afraid|dread|anxious|claustro|threat|panic", {"camera": {"framing": "close-up", "angle": "low", "movement": "handheld", "focus": "shallow", "lens": "portrait (50mm)"},
     "camera_why": "Tension is felt up close: a tight frame, a slightly low angle and a small unsteadiness keep the audience uneasy.",
     "light": "Hard, low-key light from one side; deep shadow on the rest of the face.", "light_why": "Contrast and shadow say something is being held back."}),
    (r"sad|lonely|loss|grief|empty|alone|longing|regret", {"camera": {"framing": "wide", "angle": "eye level", "movement": "locked off", "focus": "deep", "lens": "normal (35mm)"},
     "camera_why": "Loneliness reads when the person is small in a still, wide frame.",
     "light": "Soft, cool, low light with little contrast.", "light_why": "Muted light keeps the feeling quiet."}),
    (r"calm|peace|content|gentle|warm|tender|safe", {"camera": {"framing": "medium", "angle": "eye level", "movement": "locked off", "focus": "deep", "lens": "normal (35mm)"},
     "camera_why": "A steady medium frame at eye level feels settled.",
     "light": "Soft, warm daylight from a window, gentle fill.", "light_why": "Soft warm light tells the audience they are safe here."}),
    (r"joy|happy|excite|celebrat|laugh|playful|delight", {"camera": {"framing": "medium", "angle": "eye level", "movement": "tracking", "focus": "deep", "lens": "wide (24mm)"},
     "camera_why": "Movement and a wider lens carry energy.", "light": "Bright, open light with warm highlights.", "light_why": "Open light lifts the mood."}),
    (r"anger|rage|furious|confront|argument|defiant", {"camera": {"framing": "close-up", "angle": "low", "movement": "push in", "focus": "shallow", "lens": "portrait (50mm)"},
     "camera_why": "A slow push in on a low angle closes in on the pressure.", "light": "Hard key with a warm edge, strong shadow.", "light_why": "Harsh light matches harsh feeling."}),
    (r"intimate|love|desire|close|whisper", {"camera": {"framing": "close-up", "angle": "eye level", "movement": "locked off", "focus": "shallow", "lens": "portrait (50mm)"},
     "camera_why": "Closeness is shown by a close frame and soft focus around the face.", "light": "Soft, low, warm light from a nearby source.", "light_why": "A small warm source makes the space feel private."}),
]
BY_FRAMING = {"establishing": ("wide", "locked off"), "wide": ("normal (35mm)", "locked off"), "medium": ("normal (35mm)", "locked off"), "close-up": ("portrait (50mm)", "locked off"),
              "extreme close-up": ("macro", "locked off"), "over the shoulder": ("portrait (50mm)", "locked off"), "insert": ("macro", "locked off"), "point of view": ("normal (35mm)", "handheld")}
BY_TIME = [(r"night|midnight", "Moonlight or street light through windows, with practical lamps as the warm accents.", "Night light has to come from somewhere you can see."),
           (r"dawn|sunrise|morning", "Low, soft daylight through a window; long gentle shadows.", "Morning light is low and soft."),
           (r"dusk|sunset|evening", "Low warm sun with a cooling sky.", "Dusk is warm against a cooling sky."),
           (r"day|noon|afternoon", "Even daylight from the windows, soft fill.", "Daylight is the motivation here.")]


def suggest_for(c: dict) -> dict:
    """The suggestion for a contract (pure): camera and light for what the shot is meant to feel like, each with its reason."""
    feel = " ".join([c["performance"]["emotional_intention"], c["story_purpose"], c["action"]]).lower()
    cam: dict = {}
    light = {"description": "", "why": ""}
    for pat, rec in FEEL:
        if re.search(pat, c["performance"]["emotional_intention"].lower() or feel):
            cam, light = dict(rec["camera"]), {"description": rec["light"], "why": rec["light_why"]}
            cam["why"] = rec["camera_why"]
            break
    framing = c["camera"]["framing"] or cam.get("framing", "medium")
    lens, move = BY_FRAMING.get(framing, ("normal (35mm)", "locked off"))
    base = {"framing": framing, "lens": lens, "movement": move, "angle": "eye level", "focus": "deep" if framing in ("wide", "establishing") else "shallow"}
    cam = {**base, **cam, "framing": c["camera"]["framing"] or cam.get("framing", framing)}
    cam.setdefault("why", f"A {framing} frame suits what this shot has to show.")
    if not light["description"]:
        t = (c["lighting"]["time"] or "").lower()
        hit = next(((a, b) for p, a, b in BY_TIME if re.search(p, t)), None)
        light = {"description": hit[0] if hit else "Natural, motivated light that matches the place.", "why": hit[1] if hit else "Light should come from a source the audience can believe."}
    return {"camera": cam, "lighting": light, "from": "the feeling of the shot" if c["performance"]["emotional_intention"] else "what the shot shows"}


def suggest(d: str, sid: str) -> dict:
    """What the camera and light could do for what this shot is meant to feel like, each with its reason. Nothing is applied."""
    return suggest_for(_contract(d, sid))


def blocking_view(d: str, sid: str, mode: str = "get") -> dict:
    """The blocking plan of a shot (or a suggested one), the words it adds to the prompts, every shot of the scene on the same floor, and where the camera crosses the line. Nothing is sent."""
    from . import blocking
    idx = _index(d)
    cons = [c for c in (_read(_cpath(d, s)) for s in idx["order"]) if isinstance(c, dict)]
    c = next((x for x in cons if x["id"] == sid), None)
    if c is None:
        raise SystemExit("That shot doesn't exist.")
    scene = [x for x in cons if x["scene"] == c["scene"]]
    pos = next(i for i, x in enumerate(scene) if x["id"] == sid)
    prev = next((x["plan"] for x in reversed(scene[:pos]) if x.get("plan")), None)
    plan = c.get("plan")
    suggested = None
    if mode in ("suggest", "carry"):
        suggested = blocking.suggest(c, prev, blocking.scene_side(cons, c["scene"], before=sid))
        if mode == "carry" and prev:                               # the same floor as the shot before, the camera left where it is in this shot (or suggested)
            suggested = blocking.clean({**prev, "people": suggested["people"], "camera": (plan or {}).get("camera") or suggested["camera"]})
    shown = suggested if suggested is not None else plan
    return {"id": sid, "scene": c["scene"], "framing": c["camera"]["framing"], "plan": plan, "suggested": suggested, "has_previous": bool(prev),
            "text": blocking.describe(shown), "people": [x["name"] for x in c["characters"]],
            "scene_shots": [{"id": x["id"], "framing": x["camera"]["framing"], "plan": x.get("plan")} for x in scene], "crossings": [x for x in blocking.crossings(cons) if x["shot"] in {y["id"] for y in scene}],
            "room": {"w": blocking.W, "h": blocking.H}}


def principles(d: str, sid: str) -> dict:
    """The animation principles (or, for a photorealistic film, the screen craft) that will be added to this shot's prompts, from its words and the film's look. Free; nothing is sent."""
    from . import animation_principles as AP
    from . import bible as B
    c = _contract(d, sid)
    b = B.load(d)
    look = B.effective_look(b)
    perf = c.get("performance") or {}
    cam = c.get("camera") or {}
    beats = [str(x.get("what", "")) for x in (perf.get("beats") or []) if isinstance(x, dict)]
    shot = {"description": " ".join(str(x) for x in (c.get("action"), c.get("story_purpose")) if x), "performance": " ".join(beats), "emotion": perf.get("emotional_intention", ""),
            "movement": " ".join(str(x) for x in (cam.get("movement"), perf.get("micro_animation")) if x), "beats": beats}
    project = {"animation": {"principles": b["style"]["principles"]}} if "principles" in b["style"] else {}
    names = lambda ids: [{"id": i, "name": AP.BY_ID[i]["name"], "plain": AP.BY_ID[i]["plain"]} for i in ids]   # noqa: E731
    return {"look": look, "family": AP.family(look), "screen_craft": AP.family(look) == "photoreal", "video": names(AP.pick(project, shot, look, True)), "picture": names(AP.pick(project, shot, look, False))}


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="filmcrafter-shots")
    ap.add_argument("action", choices=["get", "breakdown", "shot", "set", "add", "duplicate", "delete", "move", "merge", "split", "suggest", "command", "principles", "blocking"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    x = json.loads(a.data)
    d = a.target
    try:
        _film(d)
        if a.action == "get":
            res = view(d)
        elif a.action == "breakdown":
            res = breakdown(d, x.get("scene"))
        elif a.action == "shot":
            res = get_shot(d, x["id"])
        elif a.action == "set":
            res = set_fields(d, x["id"], x.get("patch") or {})
        elif a.action == "add":
            res = add(d, int(x["scene"]), x.get("after"))
        elif a.action == "duplicate":
            res = duplicate(d, x["id"])
        elif a.action == "delete":
            res = delete(d, x["id"])
        elif a.action == "move":
            res = move(d, x["id"], int(x["delta"]))
        elif a.action == "merge":
            res = merge(d, x["id"])
        elif a.action == "split":
            res = split(d, x["id"])
        elif a.action == "command":
            from . import directcmd
            res = directcmd.command(d, x["id"], x.get("text", ""))
        elif a.action == "principles":
            res = principles(d, x["id"])
        elif a.action == "blocking":
            res = blocking_view(d, x["id"], x.get("mode", "get") if x.get("mode") in ("get", "suggest", "carry") else "get")
        else:
            res = suggest(d, x["id"])
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
