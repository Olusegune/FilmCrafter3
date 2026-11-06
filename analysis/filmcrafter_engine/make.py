"""Making the film from its shots: the storyboard, the hero keyframes and the video, through the proven render engine.

A film keeps its work in its own folders (script, Bible, Shot Contracts). To make pictures and video it hands the render engine a plain render project it
builds from them, in <Film>/render/. That folder is a normal render project (jobs, takes, keyframes, references), so everything the engine already does works on it:
prices, budgets, providers, retries, queues that survive a crash. Nothing here spends money: a price is shown and confirmed by a person first, in the app.

  <Film>/render/                 the render project built from the Shot Contracts and the Bible (rebuilt by `sync`, never touching its jobs or takes)
  <Film>/storyboard.json         the storyboard panel chosen for each shot
  <Film>/shots/<id>/contract.json   `locks.storyboard` and `locks.keyframe` for each shot

Order of work: storyboard panels, choose one (and lock it), hero keyframe made from it, choose one (and lock it), video from the locked keyframe, choose a take.

  python -m filmcrafter_engine.make <action> <film_dir> --data '{...}'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time

from . import safeio
from . import sheetmatch as SM
from .safe import check_id, file_name, file_part

LOOK_FOR_LANE = {"photoreal cinematic": "live-action", "photoreal CGI": "photoreal-cgi", "feature 3D": "feature-3d", "low-poly 3D": "low-poly", "hand-drawn 2D": "hand-drawn-2d",
                 "stylized 3D": "stylized-3d", "graphic 3D": "cel-shaded-3d", "2D animation": "digital-2d", "painterly animation": "painterly",
                 "anime-inspired": "anime", "graphic comic-inspired animation": "motion-comic", "stop motion": "stop-motion", "clay": "claymation", "miniature": "diorama",
                 "mixed media": "mixed-media", "experimental animation": "mixed-media"}
STAGES = ("storyboard", "keyframe", "video")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
MAX_IMAGE_BYTES = 25 * 1024 * 1024


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


def render_dir(d: str) -> str:
    return os.path.join(d, "render")


def _film(d: str) -> dict:
    m = _read(os.path.join(d, "film.json"))
    if not isinstance(m, dict) or "story" not in m:
        raise SystemExit("That isn't a FilmCrafter film.")
    return m


def _contracts(d: str) -> list[dict]:
    from . import shots
    idx = shots._index(d)
    out = []
    for sid in idx["order"]:
        c = _read(shots._cpath(d, sid))
        if isinstance(c, dict):
            out.append(c)
    return out


def _save_contract(d: str, c: dict) -> None:
    from . import shots
    _write(shots._cpath(d, c["id"]), c)


# ---------------------------------------------------------------- building the render project

def _beats_text(c: dict) -> str:
    parts = []
    if c["performance"].get("emotional_intention"):
        parts.append(f"The feeling: {c['performance']['emotional_intention']}.")
    for b in c["performance"].get("beats", []):
        bits = [f"{b.get('character') or 'Someone'}: {b.get('what', '').rstrip('.')}"]
        for k, n in (("hiding", "hiding"), ("subtext", "subtext")):
            if b.get(k):
                bits.append(f"{n}: {b[k].rstrip('.')}")
        arc = " then ".join(x for x in (b.get("start"), b.get("turn"), b.get("end")) if x)
        if arc:
            bits.append(f"feeling goes {arc}")
        parts.append("; ".join(x for x in bits if x.strip(": ")) + ".")
    if c["performance"].get("micro_animation"):
        parts.append(f"Small motion: {c['performance']['micro_animation'].rstrip('.')}.")
    return " ".join(parts)


def _visual(c: dict) -> str:
    what = c["action"] or c["story_purpose"] or c["title"]
    who = ", ".join(x["name"].title() for x in c["characters"])
    say = ""
    if c["dialogue"]:
        # who is speaking, never the words: a picture or video model draws quoted speech as a caption (found in a real run). The lines themselves reach video through the dialogue lane.
        speakers = list(dict.fromkeys(x["speaker"].title() for x in c["dialogue"][:6] if x.get("speaker")))
        say = (" " + " and ".join(speakers) + (" are talking, taking turns." if len(speakers) > 1 else " is speaking.")) if speakers else " Someone is speaking."
    prod = c.get("production") if isinstance(c.get("production"), dict) else {}
    plate = prod.get("mode") in ("green_screen", "transparent")                          # made as a plate: the place is not drawn, a flat screen is asked for, and the background is put in later
    place = f" In {c['environment']['name']}." if c["environment"].get("name") and not plate else ""
    things = ", ".join(x["name"] for x in c.get("props") or [] if x.get("name"))
    clause = ""
    if plate:
        from . import vpstudio
        clause = " " + vpstudio.plate_clause(prod)
    return (f"{what}{' ' if what and not what.endswith(('.', '!', '?')) else ''}{('People: ' + who + '.') if who else ''}{place}{(' Props: ' + things + '.') if things else ''}{say}{clause}").strip()


def _plan(d: str, bible: dict, cons: list[dict]) -> dict:
    style = bible["style"]
    meta = {"VISUAL STYLE": ". ".join(x for x in (style.get("lane"), style.get("traits"), "; ".join(style.get("references", []))) if x),
            "WORLD": bible["rules"].get("world", ""), "TONE": bible["rules"].get("tone", "")}
    chars = []
    for ch in bible["characters"]:
        wardrobe = ch["wardrobe"][0] if ch["wardrobe"] else None
        appearance = ". ".join(x for x in (ch.get("physical"), (f"Wearing: {wardrobe['name']} {wardrobe['notes']}".strip() if wardrobe else "")) if x)
        chars.append({"name": ch["name"], "appearance": appearance, "role": ch.get("role", "")})
    scenes: dict[int, dict] = {}
    t = 0.0
    for c in cons:
        sc = scenes.setdefault(c["scene"], {"number": c["scene"], "heading": c["environment"].get("name") or f"Scene {c['scene']}", "start": t, "end": t, "notes": {}, "shots": []})
        dur = float(c["generation"].get("duration") or 3.0)
        cam = c["camera"]
        env = c["environment"].get("name", "")
        bible_env = next((e for e in bible["environments"] if e["id"] == c["environment"].get("id")), None)
        shot = {"id": c["id"], "scene": c["scene"], "number": c["index"], "start": round(t, 2), "end": round(t + dur, 2),
                "beats": [_visual(c)], "visual_prompt": _visual(c), "performers": [x["name"].title() if x["name"].isupper() else x["name"] for x in c["characters"]],
                "framing": ", ".join(x for x in (cam["framing"].capitalize() if cam["framing"] else "", (cam["angle"] + " angle") if cam["angle"] and cam["angle"] != "eye level" else "", cam["position"]) if x),
                "dof": cam.get("dof", ""), "dialogue_lead": float((c.get("sound_cut") or {}).get("lead", 0.0)), "dialogue_tail": float((c.get("sound_cut") or {}).get("tail", 0.0)),
                "lens": cam["lens"], "camera_movement": cam["movement"] if cam["movement"] != "locked off" else "locked off, no camera movement", "focus": (cam["focus"] + " focus") if cam["focus"] else "",
                "environment": ". ".join(x for x in (env, (bible_env or {}).get("description", "")) if x),
                "lighting": c["lighting"]["description"], "acting_beats": _beats_text(c), "source_shots": [c["id"]],
                "continuity_notes": [x for x in (c["continuity"], ("Starts: " + c["opening_state"]) if c["opening_state"] else "", ("Ends: " + c["closing_state"]) if c["closing_state"] else "", c["blocking"], _plan_words(c)) if x]}
        sc["shots"].append(shot)
        t += dur
        sc["end"] = round(t, 2)
    return {"meta": meta, "characters": chars, "scenes": [scenes[k] for k in sorted(scenes)]}


def _plan_words(c: dict) -> str:
    """What the shot's top-down blocking plan says, as the camera sees it ('' when there is none)."""
    from . import blocking
    return blocking.describe(c.get("plan"))


def sync(d: str) -> dict:
    """Build (or refresh) the render project from the Shot Contracts and the Bible. Jobs, takes and chosen keyframes there are never touched."""
    from . import bible as B
    from . import library
    m = _film(d)
    cons = _contracts(d)
    if not cons:
        raise SystemExit("There are no shots yet. Break the story down first.")
    rd = render_dir(d)
    os.makedirs(rd, exist_ok=True)
    bible = B.load(d)
    plan = _plan(d, bible, cons)
    total = plan["scenes"][-1]["end"] if plan["scenes"] else 0
    pj = _read(os.path.join(rd, "project.json"), {}) or {}
    old_look = pj.get("look") if isinstance(pj.get("look"), dict) else {}
    own_looks = {k: old_look[k] for k in ("scenes", "shots") if isinstance(old_look.get(k), dict) and old_look[k]}      # a scene or shot played in a look of its own (stylebible.py) is the filmmaker's, not the Bible's: it stays
    pj.update({"schema_version": 2, "title": m["title"], "song": "", "state": "directed", "aspect_ratio": m.get("aspect_ratio", "16:9"),
               "look": {"style": B.effective_look(bible), **({"genre": bible["style"]["genre"]} if bible["style"].get("genre") else {}), **({"notes": bible["style"]["notes"]} if bible["style"].get("notes") else {}), **own_looks}, "film": True})
    pj.setdefault("performance", {"default": "natural", "scenes": {}, "characters": {}, "shots": {}})      # a film starts with natural acting, so small real motion is in the prompt from the first render
    pj.setdefault("lip_sync_mode", "auto")
    if "principles" in bible["style"]:               # the twelve principles of animation the film switched on (none saved: the style's own defaults)
        pj["animation"] = {"principles": bible["style"]["principles"]}
    else:
        pj.pop("animation", None)
    _write(os.path.join(rd, "project.json"), pj)
    _write(os.path.join(rd, "production.json"), plan)
    from . import continuity
    continuity.derive(rd)                  # who stands where in each scene follows the shots as they are now
    # the pictures people brought become the render project's references: characters in the shots they are in, places in their scenes, props everywhere
    refs = os.path.join(rd, "assets", "refs")
    os.makedirs(refs, exist_ok=True)
    made = 0
    for kind, key, lkind in (("character", "characters", "character"), ("environment", "environments", "set"), ("prop", "props", "prop")):
        for it in bible[key]:
            files = []
            for mm in (SM.identity(it["media"]) if kind == "character" else it["media"][:6]):    # a person's own pictures: who they are first; their expressions, poses and outfits go only to the shots they fit
                src = os.path.join(d, mm["path"])
                if os.path.isfile(src):
                    dst = os.path.join(refs, f"{file_part(it['id'], 40)}-{file_name(os.path.basename(mm['path']), 48)}")
                    if not os.path.exists(dst):
                        shutil.copyfile(src, dst)
                    files.append("assets/refs/" + os.path.basename(dst))
            if not files:
                continue
            name = it["name"].title() if it["name"].isupper() else it["name"]
            library.upsert(rd, {"id": "fc-" + it["id"], "kind": lkind, "name": name, "files": files, "notes": (it.get("physical") or it.get("description") or it.get("notes") or "")[:300]})
            made += 1
            if kind == "prop":                                       # a prop goes to the shots that name it; a prop no shot names stays everywhere, as before
                users = [c["id"] for c in cons if any((x.get("prop_id") == it["id"]) or (x.get("name") or "").lower() == it["name"].lower() for x in c.get("props") or [])]
                if users:
                    library.assign(rd, "project", None, "fc-" + it["id"], False)
                    for sid in users:
                        library.assign(rd, "shot", sid, "fc-" + it["id"], True)
                else:
                    library.assign(rd, "project", None, "fc-" + it["id"], True)
            if kind == "environment":
                library.assign(rd, "project", None, "fc-" + it["id"], False)
                for n in it.get("scenes") or []:
                    library.assign(rd, "scene", str(n), "fc-" + it["id"], True)
    moments = _moment_references(d, rd, bible, cons, refs)
    sound = _soundtrack(d, total)
    _write(os.path.join(rd, "songmap.json"), _timeline_map(d, cons, plan, total))
    from . import voiceover                          # the person's own recorded voices, for the render project to follow
    voices = voiceover.to_render(d, rd)
    return {"render_dir": rd, "shots": len(cons), "seconds": total, "references": made, "moment_references": moments, "look": pj["look"]["style"], "soundtrack": sound, "voiceovers": voices}


def _moment_references(d: str, rd: str, bible: dict, cons: list[dict], refs: str) -> int:
    """A person's expression, pose and outfit pictures go only to the shots they fit (sheetmatch.py). Rebuilt each time, so changing a picture's name or a shot's words changes where it goes."""
    from . import library
    p, lib = library.load(rd)
    for it in [i for i in lib.get("items", []) if str(i.get("id", "")).startswith("fc-sm-")]:
        library.delete(rd, it["id"])
    made = 0
    for ch in bible["characters"]:
        cands = SM.moment_candidates(ch["media"])
        if not cands:
            continue
        users = [c for c in cons if any((x.get("character_id") == ch["id"]) or (x.get("name") or "").lower() == ch["name"].lower() for x in c.get("characters") or [])]
        made_ids: dict[str, str] = {}
        for c in users:
            for cand in SM.pick_for_shot(cands, SM.shot_text(c)):
                m = cand["media"]
                src = os.path.join(d, m["path"])
                if not os.path.isfile(src):
                    continue
                iid = "fc-sm-" + file_part(ch["id"], 30) + "-" + hashlib.sha1(m["path"].encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
                if iid not in made_ids:
                    dst = os.path.join(refs, f"{file_part(ch['id'], 40)}-{file_name(os.path.basename(m['path']), 48)}")
                    if not os.path.exists(dst):
                        shutil.copyfile(src, dst)
                    what = {"expression": "expression", "pose": "pose", "wardrobe": "outfit"}[cand["kind"]]
                    name = f"{ch['name']} ({what}: {os.path.splitext(os.path.basename(m['path']))[0][:30]})"
                    library.upsert(rd, {"id": iid, "kind": "character", "name": name, "files": ["assets/refs/" + os.path.basename(dst)],
                                        "notes": f"The {what} picture for {ch['name']} that fits this shot: keep the same person, with this {what}."})
                    made_ids[iid] = iid
                    made += 1
                library.assign(rd, "shot", c["id"], iid, True)
    return made


# ---------------------------------------------------------------- the soundtrack

def _silence(path: str, seconds: float) -> None:
    import wave
    n = int(max(1.0, seconds) * 44100)
    tmp = path + ".part"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        chunk = bytes(2) * 44100
        for _ in range(n // 44100):
            w.writeframes(chunk)
        w.writeframes(bytes(2) * (n % 44100))
    os.replace(tmp, path)


def _soundtrack(d: str, seconds: float) -> dict:
    """The film's sound bed. Until a soundtrack is brought it is silence the length of the film, so the export always has something to lay the picture over."""
    rd = render_dir(d)
    meta_path = os.path.join(rd, "soundtrack.json")
    meta = _read(meta_path, {}) or {}
    pj = _read(os.path.join(rd, "project.json"), {}) or {}
    if meta.get("kind") == "file" and meta.get("file") and os.path.isfile(os.path.join(rd, meta["file"])):
        pj["song"] = meta["file"]
    else:
        _silence(os.path.join(rd, "soundtrack.wav"), seconds)
        meta = {"kind": "silence", "file": "soundtrack.wav", "seconds": round(seconds, 1)}
        _write(meta_path, meta)
        pj["song"] = "soundtrack.wav"
    _write(os.path.join(rd, "project.json"), pj)
    return {"kind": meta["kind"], "file": meta.get("name") or meta["file"]}


AUDIO_EXT = (".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg")


def set_soundtrack(d: str, file: str | None) -> dict:
    """Use an audio file you brought (music, a dialogue mix, an ADR track) as the film's soundtrack, or go back to silence. The file is copied in untouched."""
    _film(d)
    cons = _contracts(d)
    if not cons:
        raise SystemExit("There are no shots yet. Break the story down first.")
    rd = render_dir(d)
    if not os.path.isfile(os.path.join(rd, "production.json")):
        sync(d)
    total = sum(float(c["generation"].get("duration") or 3.0) for c in cons)
    meta_path = os.path.join(rd, "soundtrack.json")
    if file:
        src = os.path.abspath(str(file))
        if not src.lower().endswith(AUDIO_EXT) or not os.path.isfile(src):
            raise SystemExit("Choose a WAV, MP3, M4A, FLAC, AAC or OGG file.")
        if os.path.getsize(src) > 500 * 1024 * 1024:
            raise SystemExit("That audio file is larger than 500 MB.")
        name = f"soundtrack-{int(time.time())}{os.path.splitext(src)[1].lower()}"
        shutil.copyfile(src, os.path.join(rd, name))
        _write(meta_path, {"kind": "file", "file": name, "name": os.path.basename(src)})
    else:
        _write(meta_path, {"kind": "silence"})
    _soundtrack(d, total)
    sync(d)
    return {**status(d), "soundtrack": _read(meta_path, {})}


def _peaks(path: str, points: int = 2000) -> list[float]:
    """A waveform envelope of the soundtrack for the timeline (all zeros for silence)."""
    try:
        import numpy as np
        from . import shotsound
        y = shotsound.decode(path, 1)[:, 0] if os.path.isfile(path) else np.zeros(0, dtype="float32")
        if len(y) < points * 2:
            return [0.0] * points
        n = len(y) // points * points
        return [round(float(v), 3) for v in np.abs(y[:n]).reshape(points, -1).max(axis=1)]
    except Exception:
        return [0.0] * points


def _timeline_map(d: str, cons: list[dict], plan: dict, total: float) -> dict:
    """What the studio timeline reads as its 'song map': the scenes are its sections, the cuts are its beat grid, the dialogue is its lyric lane, the soundtrack is its waveform."""
    rd = render_dir(d)
    sections = [{"start": sc["start"], "end": sc["end"], "label": f"Scene {sc['number']}", "group": sc.get("heading") or f"Scene {sc['number']}", "energy": 0.5, "mood": ""} for sc in plan["scenes"]]
    starts = {c["id"]: s["start"] for sc in plan["scenes"] for c, s in zip([x for x in cons if x["scene"] == sc["number"]], sc["shots"])}
    ends = {c["id"]: s["end"] for sc in plan["scenes"] for c, s in zip([x for x in cons if x["scene"] == sc["number"]], sc["shots"])}
    lines = []
    for c in cons:
        dl = [x for x in c["dialogue"] if x.get("line")]
        words = sum(max(1, len(x["line"].split())) for x in dl)
        t = starts.get(c["id"], 0.0)
        span = max(0.1, ends.get(c["id"], t) - t)
        for x in dl:
            share = span * max(1, len(x["line"].split())) / max(1, words)
            lines.append({"section": f"Scene {c['scene']}", "text": f"{x['speaker'].title()}: {x['line']}", "start": round(t, 2), "end": round(t + share, 2)})
            t += share
    meta = _read(os.path.join(rd, "soundtrack.json"), {}) or {}
    wav = os.path.join(rd, meta.get("file") or "soundtrack.wav")
    cuts = sorted({round(x, 2) for x in starts.values()})
    return {"duration": total, "bpm": 0, "beats": [], "downbeats": cuts, "energy_curve": [], "accents": [], "sections": sections, "lyrics": lines, "lyric_match": None,
            "peaks": _peaks(wav), "analyzer": "film"}


# ---------------------------------------------------------------- what has been made

def _jobs(d: str) -> list[dict]:
    return (_read(os.path.join(render_dir(d), "jobs.json"), {"jobs": []}) or {"jobs": []}).get("jobs", [])


def _exists(d: str, rel: str | None) -> bool:
    return bool(rel) and os.path.isfile(os.path.join(render_dir(d), rel))


def status(d: str) -> dict:
    """Per shot: the storyboard panels and which is chosen, the keyframes and which is chosen, the video takes and which is approved; and what is still being made."""
    _film(d)
    cons = _contracts(d)
    rd = render_dir(d)
    jobs = _jobs(d)
    board = _read(os.path.join(d, "storyboard.json"), {}) or {}
    kfs = ((_read(os.path.join(rd, "keyframes.json"), {}) or {}).get("production", {})) or {}
    state = _read(os.path.join(rd, "shots.json"), {}) or {}
    out = []
    active = 0
    for c in cons:
        mine = [j for j in jobs if j["shot_id"] == c["id"] and j.get("state") != "dismissed"]
        imgs = [j for j in mine if j.get("kind") == "image" and j.get("frame", "start") != "end"]
        vids = [j for j in mine if j.get("kind", "video") not in ("image", "lipsync")]
        def opt(j):
            return {"job": j["id"], "image": j.get("output"), "state": j["state"], "model": j["model"], "provider": j["provider"], "created": j["created"], "error": j.get("error"),
                    "cost": j.get("cost"), "ok": j["state"] == "ready" and _exists(d, j.get("output"))}
        sb = sorted([opt(j) for j in imgs if j.get("purpose") == "storyboard"], key=lambda o: -o["created"])
        kf = sorted([opt(j) for j in imgs if j.get("purpose") != "storyboard"], key=lambda o: -o["created"])
        chosen_kf = (kfs.get(c["id"]) or "").removeprefix("project:") or None
        takes = sorted([{"job": j["id"], "video": j.get("output"), "state": j["state"], "model": j["model"], "provider": j["provider"], "created": j["created"], "error": j.get("error"),
                         "cost": j.get("cost"), "approved": (state.get(c["id"]) or {}).get("approved") == j["id"], "ok": j["state"] == "ready" and _exists(d, j.get("output"))} for j in vids],
                       key=lambda t: -t["created"])
        active += sum(1 for o in sb + kf if o["state"] in ("queued", "submitting", "submitted")) + sum(1 for t in takes if t["state"] in ("queued", "submitting", "submitted"))
        out.append({"id": c["id"], "scene": c["scene"], "title": c["title"] or c["story_purpose"], "duration": c["generation"]["duration"], "framing": c["camera"]["framing"],
                    "storyboard": {"options": sb, "chosen": board.get(c["id"]), "locked": bool(c["locks"]["storyboard"])},
                    "keyframe": {"options": kf, "chosen": chosen_kf if _exists(d, chosen_kf) else None, "locked": bool(c["locks"]["keyframe"])},
                    "video": {"takes": takes, "approved": (state.get(c["id"]) or {}).get("approved")}})
    return {"shots": out, "active": active, "render_dir": rd, "aspect_ratio": _film(d).get("aspect_ratio", "16:9"), "soundtrack": (_read(os.path.join(rd, "soundtrack.json"), {}) or {"kind": "none"}), "synced": os.path.isfile(os.path.join(rd, "production.json")),
            "counts": {"shots": len(out), "storyboard": sum(1 for s in out if s["storyboard"]["chosen"]), "keyframe": sum(1 for s in out if s["keyframe"]["chosen"]),
                       "video": sum(1 for s in out if any(t["ok"] for t in s["video"]["takes"]))}}


def progress(d: str) -> dict:
    """How far along each step of the film is, for the badges along the top. Cheap: it only reads files."""
    from . import bible as B
    from . import shots as S
    m = _film(d)
    st = m["story"]
    b = B.load(d)
    cons = _contracts(d)
    done = {"storyboard": 0, "keyframe": 0, "video": 0}
    if cons and os.path.isfile(os.path.join(render_dir(d), "production.json")):
        s = status(d)
        done = s["counts"]
    return {"story": {"kind": st["kind"], "locked": st.get("locked") is not None, "as_is": st.get("as_is") is not None},
            "cast": {"characters": len(b["characters"]), "places": len(b["environments"]), "pictures": sum(1 for c in b["characters"] if c["media"]), "style": bool(b["style"]["lane"] or b["style"].get("look"))},
            "shots": {"count": len(cons), "edited": sum(1 for c in cons if c.get("edited"))},
            "make": {"shots": len(cons), "storyboard": done["storyboard"], "keyframe": done["keyframe"], "video": done["video"]}}


def tag(d: str, jobs: list[str], purpose: str) -> dict:
    """Mark newly queued picture jobs as storyboard panels or keyframes (the render engine only knows 'image')."""
    if purpose not in ("storyboard", "keyframe"):
        raise SystemExit("Choose storyboard or keyframe.")
    from .render import Store
    store = Store(render_dir(d))
    ids = {str(j) for j in jobs}
    for j in list(store.jobs):
        if j["id"] in ids and j.get("kind") == "image":
            store.update(j, purpose=purpose)
    return status(d)


# ---------------------------------------------------------------- choosing and locking

def _contract(d: str, sid: str) -> dict:
    from . import shots
    return shots._contract(d, check_id(sid, "shot"))


def choose(d: str, shot: str, stage: str, job: str) -> dict:
    """Choose which storyboard panel, keyframe or video take is the one. A locked stage keeps its choice."""
    if stage not in STAGES:
        raise SystemExit("Choose storyboard, keyframe or video.")
    c = _contract(d, shot)
    j = next((x for x in _jobs(d) if x["id"] == job and x["shot_id"] == c["id"]), None)
    if not j or j["state"] != "ready" or not _exists(d, j.get("output")):
        raise SystemExit("Choose a finished one.")
    rd = render_dir(d)
    if stage == "storyboard":
        if c["locks"]["storyboard"]:
            raise SystemExit("The storyboard for this shot is locked. Unlock it to choose another.")
        if j.get("kind") != "image" or j.get("purpose") != "storyboard":
            raise SystemExit("That isn't a storyboard panel.")
        board = _read(os.path.join(d, "storyboard.json"), {}) or {}
        board[c["id"]] = j["output"]
        _write(os.path.join(d, "storyboard.json"), board)
    elif stage == "keyframe":
        if c["locks"]["keyframe"]:
            raise SystemExit("The keyframe for this shot is locked. Unlock it to choose another.")
        if j.get("kind") != "image" or j.get("purpose") == "storyboard":
            raise SystemExit("That isn't a keyframe.")
        from . import library
        library.choose_keyframe(rd, c["id"], job)
    else:
        if j.get("kind", "video") in ("image", "lipsync"):
            raise SystemExit("That isn't a video take.")
        from . import library
        library.approve(rd, c["id"], job)
    return status(d)


def lock(d: str, shot: str, stage: str, on: bool = True) -> dict:
    """Lock a stage: the choice is kept and can't be changed (or regenerated over) until it is unlocked. A storyboard lock also fixes the shot's framing."""
    if stage not in ("storyboard", "keyframe"):
        raise SystemExit("Choose storyboard or keyframe.")
    c = _contract(d, shot)
    if on:
        have = status(d)["shots"]
        s = next(x for x in have if x["id"] == c["id"])
        if not s[stage]["chosen"]:
            raise SystemExit("Choose one first, then lock it.")
    c["locks"][stage] = bool(on)
    if stage == "storyboard" and on:
        c["status"] = "storyboard locked"
    if stage == "keyframe" and on:
        c["status"] = "keyframe locked"
    _save_contract(d, c)
    return status(d)


def use_storyboard_as_reference(d: str, shot: str) -> dict:
    """Give the keyframe the storyboard panel as a composition reference, so the hero frame keeps the approved framing."""
    from . import library
    c = _contract(d, shot)
    board = _read(os.path.join(d, "storyboard.json"), {}) or {}
    rel = board.get(c["id"])
    if not _exists(d, rel):
        raise SystemExit("Choose a storyboard panel first.")
    rd = render_dir(d)
    iid = "fc-board-" + c["id"].lower()
    library.upsert(rd, {"id": iid, "kind": "style", "name": f"Storyboard {c['id']}", "files": [rel], "notes": "Composition reference: keep this framing and blocking."})
    library.assign(rd, "project", None, iid, False)
    library.assign(rd, "shot", c["id"], iid, True)
    return {"reference": iid}


def import_media(d: str, shot: str, stage: str, file: str) -> dict:
    """Bring your own storyboard panel, keyframe or video for a shot. It is copied into the film untouched; the original stays where it is."""
    from . import media
    c = _contract(d, shot)
    src = os.path.abspath(str(file or ""))
    if not os.path.isfile(src):
        raise SystemExit("That file can't be found.")
    rd = render_dir(d)
    if not os.path.isfile(os.path.join(rd, "production.json")):
        sync(d)
    if stage == "storyboard":
        if c["locks"]["storyboard"]:
            raise SystemExit("The storyboard for this shot is locked.")
        if not src.lower().endswith(IMAGE_EXT) or os.path.getsize(src) > MAX_IMAGE_BYTES:
            raise SystemExit("Choose a PNG, JPG or WebP picture under 25 MB.")
        os.makedirs(os.path.join(d, "storyboard"), exist_ok=True)
        dst = os.path.join(d, "storyboard", f"{file_part(c['id'])}-{int(time.time())}{os.path.splitext(src)[1].lower()}")
        k = 2
        while os.path.exists(dst) or os.path.exists(os.path.join(rd, "media", os.path.basename(dst))):       # two panels in the same second must never overwrite each other
            dst = os.path.join(d, "storyboard", f"{file_part(c['id'])}-{int(time.time())}-{k}{os.path.splitext(src)[1].lower()}")
            k += 1
        shutil.copyfile(src, dst)
        # the render engine reads project-relative files: keep a copy where it can
        rel = "media/" + os.path.basename(dst)
        os.makedirs(os.path.join(rd, "media"), exist_ok=True)
        shutil.copyfile(dst, os.path.join(rd, rel))
        board = _read(os.path.join(d, "storyboard.json"), {}) or {}
        board[c["id"]] = rel
        _write(os.path.join(d, "storyboard.json"), board)
    elif stage == "keyframe":
        if c["locks"]["keyframe"]:
            raise SystemExit("The keyframe for this shot is locked.")
        media.import_media(rd, c["id"], src, role="keyframe")
    elif stage == "video":
        media.import_media(rd, c["id"], src, role="take")
    else:
        raise SystemExit("Choose storyboard, keyframe or video.")
    return status(d)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="filmcrafter-make")
    ap.add_argument("action", choices=["sync", "status", "tag", "choose", "lock", "reference", "import", "soundtrack", "progress"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    x = json.loads(a.data)
    d = a.target
    try:
        if a.action == "sync":
            res = sync(d)
        elif a.action == "status":
            res = status(d)
        elif a.action == "tag":
            res = tag(d, x.get("jobs") or [], x.get("purpose", ""))
        elif a.action == "choose":
            res = choose(d, x["shot"], x["stage"], x["job"])
        elif a.action == "lock":
            res = lock(d, x["shot"], x["stage"], x.get("on", True) is not False)
        elif a.action == "reference":
            res = use_storyboard_as_reference(d, x["shot"])
        elif a.action == "progress":
            res = progress(d)
        elif a.action == "soundtrack":
            res = set_soundtrack(d, x.get("file"))
        else:
            res = import_media(d, x["shot"], x["stage"], x["file"])
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
