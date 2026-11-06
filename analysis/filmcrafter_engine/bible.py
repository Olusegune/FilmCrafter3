"""The Production Bible, Cast and World of a film: the one source of truth the rest of the film is made from.

  <Film>/bible/bible.json      rules, philosophy, style profile, characters (with states, wardrobe, pictures), environments (with spatial notes), props
  <Film>/bible/history/        a copy of the Bible before each change (the newest 30)
  <Film>/cast/<id>/            a character's pictures
  <Film>/world/<id>/           an environment's pictures
  <Film>/props/<id>/           a prop's pictures

The Bible is seeded from the story (speaking characters and places) and then belongs to the person: seeding only adds, nothing is ever deleted
(removing an entry moves it to the history), and the pictures you bring are copied in untouched.

  python -m filmcrafter_engine.bible <action> <film_dir> --data '{...}'
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time

from . import animation_principles as AP
from . import safeio
from .safe import check_id, file_part

SCHEMA = 1
KINDS = ("character", "environment", "prop")
FOLDER = {"character": "cast", "environment": "world", "prop": "props"}
LISTKEY = {"character": "characters", "environment": "environments", "prop": "props"}
# the film's visual style is chosen in two steps: a family (photorealistic, 3D animation, 2D animation, hands-on crafts), then a style within it
LANE_GROUPS = (("photoreal", ("photoreal cinematic", "photoreal CGI")),
               ("3d", ("feature 3D", "stylized 3D", "graphic 3D", "low-poly 3D")),
               ("2d", ("hand-drawn 2D", "2D animation", "painterly animation", "anime-inspired", "graphic comic-inspired animation")),
               ("craft", ("stop motion", "clay", "miniature", "mixed media", "experimental animation")))
STYLE_LANES = tuple(l for _, ls in LANE_GROUPS for l in ls)
MEDIA_KINDS = ("master", "front", "three-quarter", "side", "back", "expression", "pose", "wardrobe", "reference", "other")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
MAX_IMAGE_BYTES = 25 * 1024 * 1024
KEEP_HISTORY = 30

RULE_FIELDS = ("world", "tone", "rules", "avoid")
PHILOSOPHY_FIELDS = ("visual", "cinematography", "lighting", "acting", "colour", "continuity")
# Sound & Music (additive: older films simply lack these keys). The film's sound and music style is film-wide; a voice profile belongs to one character. The assigned ElevenLabs voice
# stays in voice/cast.json (cast_voice.py): the profile describes the voice the character should have, it never replaces that record.
SOUND_STYLE_FIELDS = {"sound": ("philosophy", "realism", "ambience", "dialogue", "silence"),
                      "music": ("genre", "instrumentation", "mood", "tempo", "influences", "palette", "motifs", "intensity", "silence")}
VOICE_PROFILE_FIELDS = ("description", "age_range", "accent", "timbre", "pace", "emotional_range", "delivery", "notes")
# the rest of a character's voice identity (voiceid.py): kept in the same profile, read by nothing that asks a model for a profile (the AI proposes only VOICE_PROFILE_FIELDS)
IDENTITY_FIELDS = ("language", "pitch_range", "vocal_weight", "texture", "breathiness", "rhythm", "articulation", "mannerisms", "pronunciation")
CHARACTER_FIELDS = ("name", "role", "age", "physical", "relationships", "arc", "voice", "notes")
SPATIAL_FIELDS = ("entrances", "exits", "doors", "windows", "landmarks", "furniture", "blocking", "camera_zones", "lighting", "day_night")
ENV_FIELDS = ("name", "description", "notes")
PROP_FIELDS = ("name", "notes")
LIMIT = 4000


def emit(**kw) -> None:
    try:
        print(json.dumps(kw), flush=True)
    except (OSError, ValueError):
        pass


def _read(path, default=None):
    """Absent -> default. A damaged file is never mistaken for an empty Bible (see safeio): its bytes are kept and the last good copy is used, or the person is told."""
    return safeio.read_json(path, default)


def _write(path, data) -> None:
    safeio.write_json(path, data)


def _text(v, limit: int = LIMIT) -> str:
    return str(v if v is not None else "").replace("\x00", "").strip()[:limit]


def _empty() -> dict:
    return {"schema": SCHEMA, "rev": 0, "updated": 0,
            "rules": {k: "" for k in RULE_FIELDS}, "philosophy": {k: "" for k in PHILOSOPHY_FIELDS},
            "style": {"lane": "", "notes": "", "traits": "", "references": []},
            "characters": [], "environments": [], "props": [],
            "sound_style": {sec: {k: "" for k in fs} for sec, fs in SOUND_STYLE_FIELDS.items()}}


def _path(d: str) -> str:
    return os.path.join(d, "bible", "bible.json")


def _film(d: str) -> None:
    m = _read(os.path.join(d, "film.json"))
    if not isinstance(m, dict) or "story" not in m:
        raise SystemExit("That isn't a FilmCrafter film.")


def load(d: str) -> dict:
    _film(d)
    b = _read(_path(d))
    base = _empty()
    if not isinstance(b, dict):
        return base
    for k, v in base.items():
        b.setdefault(k, v)
    ss = b["sound_style"] if isinstance(b.get("sound_style"), dict) else {}
    b["sound_style"] = {sec: {k: str((ss.get(sec) or {}).get(k, "")) for k in fs} for sec, fs in SOUND_STYLE_FIELDS.items()}
    return b


def _save(d: str, b: dict, before: dict | None) -> dict:
    """Write the Bible, keeping a copy of what it was."""
    if before is not None and before.get("rev", 0) > 0:
        hist = os.path.join(d, "bible", "history")
        os.makedirs(hist, exist_ok=True)
        _write(os.path.join(hist, f"rev{before['rev']:04d}.json"), before)
        for old in sorted(os.listdir(hist))[:-KEEP_HISTORY]:
            try:
                os.remove(os.path.join(hist, old))
            except OSError:
                pass
    b["rev"] = int(b.get("rev", 0)) + 1
    b["updated"] = int(time.time())
    _write(_path(d), b)
    return b


def _id(kind: str, name: str, taken: set[str]) -> str:
    stem = {"character": "c", "environment": "e", "prop": "p"}[kind] + "_" + file_part(re.sub(r"\s+", "-", name.lower()), 40).strip("-_.") or "x"
    out, n = stem, 2
    while out in taken:
        out, n = f"{stem}-{n}", n + 1
    return out


def _find(b: dict, kind: str, id_: str) -> dict:
    for it in b[LISTKEY[kind]]:
        if it["id"] == id_:
            return it
    raise SystemExit(f"That {kind} isn't in the Bible.")


# ---------------------------------------------------------------- seeding from the story

def seed(d: str) -> dict:
    """Add the story's speaking characters and places that the Bible does not have yet. Existing entries are never changed or removed."""
    from . import story
    m = story._manifest(d)
    st = story.status(d, m["story"]["current"])
    found = st["found"]
    b = load(d)
    before = json.loads(json.dumps(b))
    names = {c["name"].lower(): c for c in b["characters"]}
    envs = {e["name"].lower(): e for e in b["environments"]}
    added = {"characters": 0, "environments": 0}
    taken_c = {c["id"] for c in b["characters"]}
    taken_e = {e["id"] for e in b["environments"]}
    for c in found.get("characters", []):
        title = c["name"].title()
        if title.lower() in names or c["name"].lower() in names:
            names.get(title.lower(), names.get(c["name"].lower()))["scenes"] = c.get("scenes", [])
            continue
        cid = _id("character", title, taken_c)
        taken_c.add(cid)
        entry = {"id": cid, "name": title, "role": "", "age": "", "physical": "", "relationships": "", "arc": "", "voice": "", "notes": "",
                 "wardrobe": [], "states": [{"id": "s1", "label": "Default", "notes": ""}], "media": [], "scenes": c.get("scenes", []), "source": "story"}
        b["characters"].append(entry)
        names[title.lower()] = entry
        added["characters"] += 1
    for p in found.get("locations", []):
        title = p["name"].title()
        if title.lower() in envs:
            envs[title.lower()]["scenes"] = p.get("scenes", [])
            continue
        eid = _id("environment", title, taken_e)
        taken_e.add(eid)
        times = sorted({s.get("time", "") for s in found.get("scenes", []) if s.get("location") == p["name"] and s.get("time")})
        entry = {"id": eid, "name": title, "description": "", "notes": "", "spatial": {k: "" for k in SPATIAL_FIELDS},
                 "states": [{"id": "s1", "label": (times[0].title() if times else "Default"), "notes": ""}], "media": [], "scenes": p.get("scenes", []), "source": "story"}
        b["environments"].append(entry)
        envs[title.lower()] = entry
        added["environments"] += 1
    if added["characters"] or added["environments"] or b != before:
        b = _save(d, b, before)
    return {**view(d), "added": added}


# ---------------------------------------------------------------- editing

def update_rules(d: str, data: dict) -> dict:
    b = load(d)
    before = json.loads(json.dumps(b))
    for sec, fields in (("rules", RULE_FIELDS), ("philosophy", PHILOSOPHY_FIELDS)):
        for k, v in (data.get(sec) or {}).items():
            if k in fields:
                b[sec][k] = _text(v)
    st = data.get("style") or {}
    if "lane" in st:
        lane = _text(st["lane"], 80)
        if lane and lane not in STYLE_LANES:
            raise SystemExit("Choose one of the listed visual styles.")
        if lane != b["style"].get("lane"):
            b["style"].pop("look", None)               # a newer choice of the broad lane replaces an exact look chosen before
        b["style"]["lane"] = lane
    if "look" in st:                                    # the exact look, one of styles.json (not a genre layer)
        lid = _text(st["look"], 60)
        known = AP.styles().get(lid)
        if lid and (not known or known.get("family") in ("genre", "auto")):
            raise SystemExit("Choose one of the listed visual styles.")
        if lid:
            b["style"]["look"] = lid
            b["style"]["lane"] = known["name"]
        else:
            b["style"].pop("look", None)
    if "genre" in st:                                   # an optional genre feel layered on top of the look
        gid = _text(st["genre"], 60)
        known = AP.styles().get(gid)
        if gid and (not known or known.get("family") != "genre"):
            raise SystemExit("Choose one of the listed genre feels.")
        if gid:
            b["style"]["genre"] = gid
        else:
            b["style"].pop("genre", None)
    for k in ("notes", "traits"):
        if k in st:
            b["style"][k] = _text(st[k])
    if "principles" in st:                          # the twelve principles of animation: a list of ids, or null for "the style's own defaults"
        keep = AP.clean(st["principles"])
        if keep is None:
            b["style"].pop("principles", None)
        else:
            b["style"]["principles"] = keep
    if "references" in st:
        b["style"]["references"] = [_text(r, 300) for r in (st["references"] or [])][:20]
    if b != before:
        _save(d, b, before)
    return view(d)


def update_sound_style(d: str, data: dict) -> dict:
    """The film's sound and music style. Only the known fields are taken, each trimmed; nothing else in the Bible changes."""
    b = load(d)
    before = json.loads(json.dumps(b))
    src = data.get("sound_style") if isinstance(data.get("sound_style"), dict) else data
    for sec, fields in SOUND_STYLE_FIELDS.items():
        part = src.get(sec) if isinstance(src.get(sec), dict) else {}
        for k, v in part.items():
            if k in fields:
                b["sound_style"][sec][k] = _text(v)
    if b != before:
        _save(d, b, before)
    return view(d)


def set_voice_profile(d: str, id_: str, data: dict) -> dict:
    """What a character's voice should be like (description, age range, accent, timbre, pace, emotional range, delivery, notes) and whether the voice chosen for them is approved.
    Approving is only ever the person's own act; nothing here chooses, changes or generates a voice."""
    b = load(d)
    before = json.loads(json.dumps(b))
    cur = _find(b, "character", check_id(id_, "character"))
    prof = dict(cur.get("voice_profile") or {})
    for k in VOICE_PROFILE_FIELDS + IDENTITY_FIELDS:
        if k in data:
            prof[k] = _text(data[k])
    if "approved" in data:
        prof["approved"] = bool(data["approved"])
    cur["voice_profile"] = {**{k: "" for k in VOICE_PROFILE_FIELDS}, "approved": False, **prof}
    if b != before:
        _save(d, b, before)
    return {**view(d), "id": cur["id"]}


def upsert(d: str, kind: str, item: dict) -> dict:
    """Make or change a character, environment or prop. Only the known fields are taken, each trimmed and limited."""
    if kind not in KINDS:
        raise SystemExit("Choose character, environment or prop.")
    b = load(d)
    before = json.loads(json.dumps(b))
    lst = b[LISTKEY[kind]]
    fields = {"character": CHARACTER_FIELDS, "environment": ENV_FIELDS, "prop": PROP_FIELDS}[kind]
    iid = item.get("id")
    if iid:
        cur = _find(b, kind, check_id(iid, kind))
    else:
        name = _text(item.get("name"), 80)
        if not name:
            raise SystemExit("Give it a name.")
        cur = {"id": _id(kind, name, {x["id"] for x in lst}), "media": [], "scenes": [], "source": "manual"}
        if kind == "character":
            cur.update({k: "" for k in CHARACTER_FIELDS} | {"wardrobe": [], "states": [{"id": "s1", "label": "Default", "notes": ""}]})
        elif kind == "environment":
            cur.update({k: "" for k in ENV_FIELDS} | {"spatial": {k: "" for k in SPATIAL_FIELDS}, "states": [{"id": "s1", "label": "Default", "notes": ""}]})
        else:
            cur.update({k: "" for k in PROP_FIELDS} | {"states": [{"id": "s1", "label": "Default", "notes": ""}]})
        lst.append(cur)
    for k in fields:
        if k in item:
            cur[k] = _text(item[k], 80 if k == "name" else LIMIT)
    if kind == "environment" and isinstance(item.get("spatial"), dict):
        for k in SPATIAL_FIELDS:
            if k in item["spatial"]:
                cur["spatial"][k] = _text(item["spatial"][k])
    if not cur.get("name"):
        raise SystemExit("Give it a name.")
    _save(d, b, before)
    return {**view(d), "id": cur["id"]}


def remove(d: str, kind: str, id_: str) -> dict:
    """Take an entry out of the Bible. The Bible as it was is kept in the history, and the entry's pictures stay on disk."""
    if kind not in KINDS:
        raise SystemExit("Choose character, environment or prop.")
    b = load(d)
    before = json.loads(json.dumps(b))
    it = _find(b, kind, check_id(id_, kind))
    b[LISTKEY[kind]] = [x for x in b[LISTKEY[kind]] if x is not it]
    _save(d, b, before)
    return view(d)


def _state_id(states: list[dict]) -> str:
    n = 1
    ids = {s["id"] for s in states}
    while f"s{n}" in ids:
        n += 1
    return f"s{n}"


def add_state(d: str, kind: str, id_: str, label: str, notes: str = "", wardrobe: str = "", age: str = "") -> dict:
    """A related state of the same thing: the character at another age or in another outfit, the place by night, the prop broken. It stays the same canonical entry."""
    if kind not in KINDS:
        raise SystemExit("Choose character, environment or prop.")
    b = load(d)
    before = json.loads(json.dumps(b))
    it = _find(b, kind, check_id(id_, kind))
    label = _text(label, 80)
    if not label:
        raise SystemExit("Name the state, for example Age 28 or Night.")
    if any(s["label"].lower() == label.lower() for s in it["states"]):
        raise SystemExit("There is already a state with that name.")
    st = {"id": _state_id(it["states"]), "label": label, "notes": _text(notes)}
    if kind == "character":
        st["wardrobe"] = _text(wardrobe, 200)
        st["age"] = _text(age, 40)
    it["states"].append(st)
    _save(d, b, before)
    return {**view(d), "state": st["id"]}


def remove_state(d: str, kind: str, id_: str, state: str) -> dict:
    b = load(d)
    before = json.loads(json.dumps(b))
    it = _find(b, kind, check_id(id_, kind))
    if len(it["states"]) <= 1:
        raise SystemExit("Keep at least one state.")
    it["states"] = [s for s in it["states"] if s["id"] != state]
    _save(d, b, before)
    return view(d)


def add_wardrobe(d: str, id_: str, name: str, notes: str = "") -> dict:
    b = load(d)
    before = json.loads(json.dumps(b))
    ch = _find(b, "character", check_id(id_, "character"))
    name = _text(name, 80)
    if not name:
        raise SystemExit("Name the outfit.")
    n = 1
    ids = {w["id"] for w in ch["wardrobe"]}
    while f"w{n}" in ids:
        n += 1
    ch["wardrobe"].append({"id": f"w{n}", "name": name, "notes": _text(notes)})
    _save(d, b, before)
    return view(d)


def add_media(d: str, kind: str, id_: str, file: str, label: str = "reference", media_kind: str = "reference") -> dict:
    """Bring a picture for a character, place or prop. It is copied into the film untouched; the original stays where it is."""
    if kind not in KINDS:
        raise SystemExit("Choose character, environment or prop.")
    b = load(d)
    before = json.loads(json.dumps(b))
    it = _find(b, kind, check_id(id_, kind))
    src = os.path.abspath(str(file or ""))
    if not src.lower().endswith(IMAGE_EXT) or not os.path.isfile(src):
        raise SystemExit("Choose a PNG, JPG or WebP picture.")
    if os.path.getsize(src) > MAX_IMAGE_BYTES:
        raise SystemExit("That picture is larger than 25 MB.")
    media_kind = media_kind if media_kind in MEDIA_KINDS else "reference"
    folder = os.path.join(d, FOLDER[kind], it["id"])
    os.makedirs(folder, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(src))
    name = f"{file_part(base, 50)}{ext.lower()}"
    out, n = os.path.join(folder, name), 2
    while os.path.exists(out):
        out = os.path.join(folder, f"{file_part(base, 50)}-{n}{ext.lower()}")
        n += 1
    shutil.copyfile(src, out)
    rel = os.path.relpath(out, d).replace(os.sep, "/")
    it["media"].append({"path": rel, "kind": media_kind, "label": _text(label, 80) or media_kind})
    _save(d, b, before)
    return view(d)


def _copy_in(d: str, kind: str, it: dict, file: str) -> str:
    """Copy a picture the person chose into the entry's folder (never over another file) and return its path inside the film."""
    src = os.path.abspath(str(file or ""))
    if not src.lower().endswith(IMAGE_EXT) or not os.path.isfile(src):
        raise SystemExit("Choose a PNG, JPG or WebP picture.")
    if os.path.getsize(src) > MAX_IMAGE_BYTES:
        raise SystemExit("That picture is larger than 25 MB.")
    folder = os.path.join(d, FOLDER[kind], it["id"])
    os.makedirs(folder, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(src))
    name = f"{file_part(base, 50)}{ext.lower()}"
    out, n = os.path.join(folder, name), 2
    while os.path.exists(out):
        out = os.path.join(folder, f"{file_part(base, 50)}-{n}{ext.lower()}")
        n += 1
    shutil.copyfile(src, out)
    return os.path.relpath(out, d).replace(os.sep, "/")


def replace_media(d: str, kind: str, id_: str, path: str, file: str, label: str | None = None, media_kind: str | None = None) -> dict:
    """Swap one picture for another, in the same place in the list and with the same label and kind unless told otherwise. The old picture's file stays in the film folder (nothing is deleted)."""
    if kind not in KINDS:
        raise SystemExit("Choose character, environment or prop.")
    b = load(d)
    before = json.loads(json.dumps(b))
    it = _find(b, kind, check_id(id_, kind))
    i = next((k for k, m in enumerate(it["media"]) if m["path"] == path), None)
    if i is None:
        raise SystemExit("That picture isn't on this entry.")
    new = _copy_in(d, kind, it, file)
    m = it["media"][i]
    it["media"][i] = {"path": new, "kind": media_kind if media_kind in MEDIA_KINDS else m.get("kind", "reference"), "label": _text(label, 80) or m.get("label") or "reference"}
    _save(d, b, before)
    return view(d)


def update_media(d: str, kind: str, id_: str, path: str, label: str | None = None, media_kind: str | None = None) -> dict:
    """Change what a picture is called, or what it shows (master, front, side, expression...). Only the note is changed: the file is not touched."""
    if kind not in KINDS:
        raise SystemExit("Choose character, environment or prop.")
    if media_kind is not None and media_kind not in MEDIA_KINDS:
        raise SystemExit("Choose one of the listed kinds of picture.")
    b = load(d)
    before = json.loads(json.dumps(b))
    it = _find(b, kind, check_id(id_, kind))
    m = next((m for m in it["media"] if m["path"] == path), None)
    if m is None:
        raise SystemExit("That picture isn't on this entry.")
    if media_kind:
        m["kind"] = media_kind
    if label is not None:
        m["label"] = _text(label, 80) or m.get("label") or "reference"
    _save(d, b, before)
    return view(d)


def remove_media(d: str, kind: str, id_: str, path: str) -> dict:
    """Take a picture off the entry. The file stays in the film folder."""
    b = load(d)
    before = json.loads(json.dumps(b))
    it = _find(b, kind, check_id(id_, kind))
    it["media"] = [m for m in it["media"] if m["path"] != path]
    _save(d, b, before)
    return view(d)


# ---------------------------------------------------------------- reading

def effective_look(b: dict) -> str:
    """The exact look (a styles.json id): the one chosen, or the one the broad lane stands for, or 'auto'."""
    from .make import LOOK_FOR_LANE
    st = b["style"]
    return st.get("look") or LOOK_FOR_LANE.get(st.get("lane", ""), "auto")


def view(d: str) -> dict:
    b = load(d)
    need = []
    if not b["style"]["lane"] and not b["style"].get("look"):
        need.append("Choose a visual style.")
    if not b["characters"]:
        need.append("Add the characters.")
    if not b["environments"]:
        need.append("Add the places.")
    pics = sum(1 for c in b["characters"] if c["media"])
    look = effective_look(b)
    chosen = b["style"].get("principles")
    sty = AP.styles()
    families = [{"id": f, "name": AP.FAMILY_NAMES[f], "blurb": AP.FAMILY_BLURB[f], "lanes": list(dict(LANE_GROUPS).get(f, ())),
                 "looks": [{"id": k, "name": v["name"], "description": v["description"]} for k, v in sty.items() if v.get("family") == f]} for f in AP.FAMILIES]
    genres = [{"id": k, "name": v["name"], "description": v["description"]} for k, v in sty.items() if v.get("family") == "genre"]
    have = bool(b["style"]["lane"] or b["style"].get("look"))
    return {**b, "lanes": list(STYLE_LANES), "families": families, "genres": genres, "look": look if have else "", "genre": b["style"].get("genre", ""),
            "family": AP.style_family(look) if have else "",
            "principles": AP.catalog(look), "principles_on": AP.defaults(look) if chosen is None else chosen, "principles_custom": chosen is not None, "media_kinds": list(MEDIA_KINDS), "need": need,
            "counts": {"characters": len(b["characters"]), "environments": len(b["environments"]), "props": len(b["props"]), "characters_with_pictures": pics}}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="filmcrafter-bible")
    ap.add_argument("action", choices=["get", "seed", "update_rules", "update_sound_style", "set_voice_profile", "upsert", "remove", "add_state", "remove_state", "add_wardrobe", "add_media", "replace_media", "update_media", "remove_media"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    x = json.loads(a.data)
    d = a.target
    try:
        if a.action == "get":
            res = view(d)
        elif a.action == "seed":
            res = seed(d)
        elif a.action == "update_rules":
            res = update_rules(d, x)
        elif a.action == "update_sound_style":
            res = update_sound_style(d, x)
        elif a.action == "set_voice_profile":
            res = set_voice_profile(d, x.get("id", ""), x)
        elif a.action == "upsert":
            res = upsert(d, x.get("kind", ""), x.get("item") or {})
        elif a.action == "remove":
            res = remove(d, x.get("kind", ""), x.get("id", ""))
        elif a.action == "add_state":
            res = add_state(d, x.get("kind", ""), x.get("id", ""), x.get("label", ""), x.get("notes", ""), x.get("wardrobe", ""), x.get("age", ""))
        elif a.action == "remove_state":
            res = remove_state(d, x.get("kind", ""), x.get("id", ""), x.get("state", ""))
        elif a.action == "add_wardrobe":
            res = add_wardrobe(d, x.get("id", ""), x.get("name", ""), x.get("notes", ""))
        elif a.action == "add_media":
            res = add_media(d, x.get("kind", ""), x.get("id", ""), x.get("file", ""), x.get("label", "reference"), x.get("media_kind", "reference"))
        elif a.action == "replace_media":
            res = replace_media(d, x.get("kind", ""), x.get("id", ""), x.get("path", ""), x.get("file", ""), x.get("label"), x.get("media_kind"))
        elif a.action == "update_media":
            res = update_media(d, x.get("kind", ""), x.get("id", ""), x.get("path", ""), x.get("label"), x.get("media_kind"))
        else:
            res = remove_media(d, x.get("kind", ""), x.get("id", ""), x.get("path", ""))
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
