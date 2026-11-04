"""The Smart Editor: suggestions for the cut that explain themselves, can be previewed, and change nothing until you accept them.

What it does, plainly: it reads the cut, the dialogue, the beats and directions YOU wrote in the Performance Director, and each take's own length, and proposes a few edits by explainable rules. Every
proposal says what it would change, why that may help, which clips it touches, and shows a real before and after preview (the film's own export of the part). Accepting applies it as ONE change
(one undo takes it back); rejecting keeps it away. It is free, local and deterministic: nothing is sent anywhere, nothing is rendered by a provider, and the same cut gives the same suggestions.

The rules (a deliberately small, testable set; a suggestion is a reading to accept or refuse, never a verdict):
  tighten    a clip with spoken lines that runs well past the time the words need (about 155 words a minute plus a breath between lines): suggest ending it a little after the last word.
             NEVER suggested where the pause is yours: a beat you wrote that falls in the tail, or "Hold the reaction longer" or "More hesitant" switched on for the shot. Those are listed as kept, with
             the reason, so you can see the editor left them alone on purpose.
  react      a clip of someone listening straight after another person spoke: suggest giving it a little more time (only if the take has more picture, or it is a still).

Recipes set how tight or generous those two are. Three are built; the others in the list are named so you can see what is not there yet and are not offered. "Ask" understands a few plain requests
("tighten this scene", "give the audience more time on her reaction") by keywords, says when it does not understand, and never guesses.

  <film>/edit/proposals.json   which suggestions you rejected or accepted (so a rejected one stays away), nothing else

  python -m filmcrafter_engine.smart_editor <action> <project> --data '{...}'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

from . import edit_ops as O
from . import edit_time as T
from . import editing as ED
from . import grading as G
from . import safeio
from . import sequence as Q
from . import sequence_derive as D

WORDS_PER_SECOND = 155 / 60
BREATH = 0.4                                    # seconds between spoken lines
HEAD = 0.3                                      # a little air before the first word
ACTIONS = ("recipes", "suggest", "ask", "accept", "reject", "reset_rejected", "preview")

# id -> (label, what it is for, tail after the last word, smallest trim worth suggesting, extra time for a reaction, built)
RECIPES: dict[str, dict] = {
    "restrained_drama": {"label": "Restrained character drama", "for": "Quiet scenes where silence and reactions carry the feeling.", "tail": 1.4, "min_trim": 0.75, "reaction": 0.6, "built": True},
    "intimate_conversation": {"label": "Intimate conversation", "for": "Two people talking close: unhurried, room to listen.", "tail": 1.6, "min_trim": 1.0, "reaction": 0.7, "built": True},
    "rhythmic_montage": {"label": "Rhythmic montage", "for": "Quick, cut-on-the-beat sequences.", "tail": 0.5, "min_trim": 0.4, "reaction": 0.0, "built": True},
    "suspense": {"label": "Suspense and anticipation", "built": False}, "documentary": {"label": "Documentary observation", "built": False},
    "expressive_animation": {"label": "Expressive animation", "built": False}, "visual_comedy": {"label": "Visual comedy", "built": False},
    "action_continuity": {"label": "Action continuity", "built": False}, "poetic": {"label": "Reflective or poetic storytelling", "built": False},
    "educational": {"label": "Educational and historical narrative", "built": False},
}
DEFAULT_RECIPE = "restrained_drama"


# ---------------------------------------------------------------- what the editor reads

def _film_shot_dialogue(d: str) -> dict[str, tuple[int, int]]:
    """For each shot id: (words spoken, lines spoken), from the dialogue lane of the film's own timeline map."""
    sm = safeio.read_json(os.path.join(d, "songmap.json"), {}) or {}
    _, plan, _ = D.plan_of(d)
    spans = [(sh["id"], sh["start"], sh["end"]) for sh, _ in D.shots_of(plan)]
    out: dict[str, tuple[int, int]] = {}
    for ln in sm.get("lyrics") or []:
        if not isinstance(ln, dict) or ln.get("start") is None:
            continue
        t = float(ln["start"])
        sid = next((s for s, a, b in spans if a <= t < b), None)
        if not sid:
            continue
        words = len(re.sub(r"^[^:]{1,40}:\s*", "", str(ln.get("text", ""))).split())
        w, n = out.get(sid, (0, 0))
        out[sid] = (w + max(1, words), n + 1)
    return out


def _directions(d: str) -> tuple[dict, dict]:
    """(the beats you wrote, the directions you switched on), by shot. A draft that was not kept is not read."""
    from . import acting
    try:
        s = acting.load(d)
    except Exception:                                           # noqa: BLE001
        return {}, {}
    beats = {k: v for k, v in (s.get("beats") or {}).items() if isinstance(v, dict) and v.get("source") == "you"}
    return beats, (s.get("nudges") or {})


def _take_seconds(d: str) -> dict[str, float | None]:
    """How long each shot's chosen take is (None for a still, which can be held as long as you like)."""
    from . import library, proxies
    out: dict[str, float | None] = {}
    for t in proxies.takes(d):
        out[t["shot"]] = library._duration(os.path.join(d, t["output"]))
    plan_name, plan, _ = D.plan_of(d)
    jobs = (safeio.read_json(os.path.join(d, "jobs.json"), {"jobs": []}) or {}).get("jobs", [])
    state = library.shot_state(d)
    for sc in plan.get("scenes", []):
        for sh in sc.get("shots", []):
            t = library.chosen_take(d, sh["id"], plan_name, jobs, state)
            if t and t.get("media_kind") == "image":
                out[sh["id"]] = None
    return out


def _state(d: str) -> dict:
    p = os.path.join(G.edit_dir(d), "proposals.json")
    s = safeio.read_json(p, {}) or {}
    return {"rejected": [x for x in (s.get("rejected") or []) if isinstance(x, str)][-500:], "accepted": [x for x in (s.get("accepted") or []) if isinstance(x, str)][-500:]}


def _save_state(d: str, st: dict) -> None:
    os.makedirs(G.edit_dir(d), exist_ok=True)
    safeio.write_json(os.path.join(G.edit_dir(d), "proposals.json"), {"schema": 1, **st})


def _pid(kind: str, *parts) -> str:
    return hashlib.sha256("|".join([kind, *map(str, parts)]).encode()).hexdigest()[:10]


# ---------------------------------------------------------------- the rules

def _clips(cut: dict) -> list[dict]:
    return sorted((c for t in cut["tracks"] if not t["hidden"] and not t["locked"] for c in t["clips"]), key=lambda c: c["start"])


def propose(d: str, recipe_id: str = DEFAULT_RECIPE, scene: int | None = None, only: str | None = None) -> dict:
    """The suggestions for the cut as it stands: {proposals, kept, recipe}. Nothing is written."""
    r = RECIPES.get(recipe_id)
    if not r or not r.get("built"):
        raise SystemExit("That editing style is not built yet.")
    cut, _ = ED.current(d)
    fps = Q.fps_of(cut)
    ft = fps.frame_ticks
    dialogue = _film_shot_dialogue(d)
    beats, nudges = _directions(d)
    takes = _take_seconds(d)
    _, plan, _ = D.plan_of(d)
    scene_of = {sh["id"]: sc.get("number") for sh, sc in D.shots_of(plan)}
    people = {sh["id"]: [p for p in sh.get("performers") or [] if isinstance(p, str)] for sh, _ in D.shots_of(plan)}
    rejected = set(_state(d)["rejected"])
    clips = _clips(cut)
    out: list[dict] = []
    kept: list[dict] = []

    def secs(ticks: int) -> float:
        return T.ticks_to_seconds(ticks)

    for i, c in enumerate(clips):
        sid = c["shot"]
        if scene is not None and scene_of.get(sid) != scene:
            continue
        words, lines = dialogue.get(sid, (0, 0))
        dur_s = secs(c["duration"])
        # ---- tighten: end a spoken clip a little after its last word
        if (only in (None, "tighten")) and words:
            need = HEAD + words / WORDS_PER_SECOND + BREATH * max(0, lines - 1)
            allowed = need + r["tail"]
            excess = dur_s - allowed
            if excess >= r["min_trim"]:
                mine = beats.get(sid)
                last_beat_end = max((float(b.get("t1") or 0.0) for b in (mine or {}).get("beats", []) if isinstance(b, dict)), default=0.0)
                reason = None
                if "hold" in (nudges.get(sid) or {}):
                    reason = "you asked to hold the reaction longer there"
                elif "hesitant" in (nudges.get(sid) or {}):
                    reason = "you made the acting there hesitant, and a hesitation needs its time"
                elif mine and last_beat_end > allowed:
                    reason = "a beat you wrote there is still playing after the words end"
                if reason:
                    kept.append({"kind": "tighten", "shot": sid, "clip": c["id"], "why": f"Kept the pause at the end of {sid}: {reason}."})
                else:
                    to = c["start"] + T.snap_nearest(T.seconds_to_ticks(allowed, fps), fps)
                    pid = _pid("tighten", c["id"], c["start"], c["duration"], to, recipe_id)
                    if pid not in rejected and to > c["start"] and to < c["start"] + c["duration"]:
                        out.append({"id": pid, "kind": "tighten", "title": f"Tighten the end of {sid}", "clips": [c["id"]], "shots": [sid],
                                    "what": f"End {sid} {secs(c['start'] + c['duration'] - to):.1f} s sooner ({dur_s:.1f} s to {secs(to - c['start']):.1f} s) and close the gap.",
                                    "why": f"{sid} has {words} spoken word{'s' if words != 1 else ''} in {lines} line{'s' if lines != 1 else ''}, which take about {need:.1f} s to say. With a {r['tail']:.1f} s breath after the last word it needs about {allowed:.1f} s, and it runs {dur_s:.1f} s: {excess:.1f} s more. "
                                           "Cutting the dead time keeps the scene moving. It is only a reading: refuse it if the quiet is the point.",
                                    "ops": [{"op": "trim", "clip": c["id"], "edge": "out", "to": secs(to), "ripple": True}], "window": [max(0.0, secs(c["start"]) - 1.0), secs(c["start"] + c["duration"]) + 1.0],
                                    "saves": round(secs(c["start"] + c["duration"] - to), 2)})
        # ---- react: give a listening shot a little more time
        if (only in (None, "react")) and r["reaction"] > 0 and i > 0 and not words:
            prev = clips[i - 1]
            pw = dialogue.get(prev["shot"], (0, 0))[0]
            listener = [p for p in people.get(sid, []) if p not in people.get(prev["shot"], [])] or people.get(sid, [])
            if pw and prev["shot"] != sid and prev["start"] + prev["duration"] == c["start"] and listener:
                have = takes.get(sid, 0.0)
                extra = T.snap(T.seconds_to_ticks(r["reaction"], fps), fps)
                room = None if have is None else T.seconds_to_ticks(have, fps) - (c["source_in"] + c["duration"])
                if extra > 0 and (room is None or room >= extra):
                    pid = _pid("react", c["id"], c["start"], c["duration"], extra, recipe_id)
                    if pid not in rejected:
                        out.append({"id": pid, "kind": "react", "title": f"Give {sid} a little more time", "clips": [c["id"]], "shots": [sid],
                                    "what": f"Hold {sid} for {secs(extra):.1f} s longer, and move what follows later by the same amount.",
                                    "why": f"{sid} shows {listener[0]} after {prev['shot']}, where words were spoken. A moment on the listener lets the audience take in what was said. "
                                           f"The take has {'more picture' if room is not None else 'a still, which can be held'} for it. Refuse it if the pace is right.",
                                    "ops": [{"op": "trim", "clip": c["id"], "edge": "out", "to": secs(c["start"] + c["duration"] + extra), "ripple": True}],
                                    "window": [max(0.0, secs(c["start"]) - 1.0), secs(c["start"] + c["duration"] + extra) + 1.0], "saves": -round(secs(extra), 2)})
    return {"recipe": {"id": recipe_id, "label": r["label"], "for": r["for"]}, "proposals": out, "kept": kept}


# ---------------------------------------------------------------- accepting, rejecting, previewing

def _find(d: str, pid: str, recipe_id: str = DEFAULT_RECIPE) -> dict:
    for rid in [recipe_id] + [k for k, v in RECIPES.items() if v.get("built") and k != recipe_id]:
        p = next((x for x in propose(d, rid)["proposals"] if x["id"] == pid), None)
        if p:
            return p
    raise SystemExit("That suggestion no longer applies: the cut has changed since it was made. Ask again.")


def _after(d: str, p: dict) -> dict:
    cut, _ = ED.current(d)
    for op in p["ops"]:
        cut = O.run(cut, op["op"], ED._params(cut, op["op"], {k: v for k, v in op.items() if k != "op"}))
    return cut


def accept(d: str, pid: str, recipe_id: str = DEFAULT_RECIPE) -> dict:
    p = _find(d, pid, recipe_id)
    new = _after(d, p)

    def change(cur):
        cur["_extra"]["sequence"] = new
    G._save(d, change, f"accepted: {p['title']}")                       # one history entry: one undo takes the whole suggestion back
    st = _state(d)
    st["accepted"] = (st["accepted"] + [pid])[-500:]
    _save_state(d, st)
    return {"accepted": p["title"], "cut": ED.get(d)}


def reject(d: str, pid: str, recipe_id: str = DEFAULT_RECIPE) -> dict:
    p = _find(d, pid, recipe_id)
    st = _state(d)
    st["rejected"] = (st["rejected"] + [p["id"]])[-500:]
    _save_state(d, st)
    return {"rejected": p["title"]}


def reset_rejected(d: str) -> dict:
    st = _state(d)
    n = len(st["rejected"])
    st["rejected"] = []
    _save_state(d, st)
    return {"cleared": n}


def preview(d: str, pid: str, recipe_id: str = DEFAULT_RECIPE) -> dict:
    """The part of the film around the suggestion, as it is and as it would be: two real previews made the way the film is made. Nothing is saved."""
    from . import export as E
    p = _find(d, pid, recipe_id)
    after = _after(d, p)
    a0, a1 = p["window"]
    before = E.build(d, "preview", (a0, min(a1, T.ticks_to_seconds(ED.current(d)[0]["length"]))))
    shift = p["saves"]
    new = E.build(d, "preview", (a0, max(a0 + 0.6, min(a1 - max(shift, 0.0), T.ticks_to_seconds(after["length"])))), cut_override=after)
    rel = lambda x: os.path.relpath(x["path"], d).replace(os.sep, "/")
    return {"before": rel(before), "after": rel(new), "id": pid, "title": p["title"]}


# ---------------------------------------------------------------- plain requests

INTENTS = (
    (re.compile(r"\b(tighten|trim|shorter|cut down|too long|drag|dead (air|time)|speed up|snappier|tighter)\b", re.I), "tighten", "Tightening: ending spoken clips a little after the last word."),
    (re.compile(r"\b(more time|process|reaction|react|linger|breathe|breath|let it land|hold on)\b", re.I), "react", "Reaction time: a little longer on a listener after someone speaks."),
)


def ask(d: str, text: str) -> dict:
    """A plain request, read by keywords. It says what it understood, or says it did not and what it can do; it never guesses."""
    t = " ".join(str(text or "").split())[:300]
    if not t:
        raise SystemExit("Say what you would like, for example: tighten this scene.")
    scene = None
    m = re.search(r"\bscene\s+(\d{1,3})\b", t, re.I)
    if m:
        scene = int(m.group(1))
    recipe = DEFAULT_RECIPE
    if re.search(r"\b(montage|fast|rhythm|rhythmic|quick|pacey|punchy)\b", t, re.I):
        recipe = "rhythmic_montage"
    elif re.search(r"\b(intimate|conversation)\b", t, re.I):
        recipe = "intimate_conversation"
    hits = [(k, why) for rx, k, why in INTENTS if rx.search(t)]
    if not hits:
        can = ["tighten (end spoken clips a little after the last word)", "give a listener more time after someone speaks"]
        return {"understood": False, "said": t, "message": "I did not understand that as something I can do yet. I can: " + "; ".join(can) + ". Other requests (continuity, transitions, camera movement) are not built.", "can": can,
                "proposals": [], "kept": [], "recipe": {"id": recipe, "label": RECIPES[recipe]["label"]}}
    out = {"proposals": [], "kept": []}
    for k, _ in hits:
        got = propose(d, recipe, scene, k)
        out["proposals"] += got["proposals"]
        out["kept"] += got["kept"]
    return {"understood": True, "said": t, "message": " ".join(w for _, w in hits) + (f" In scene {scene}." if scene else " Across the film.") + f" Style: {RECIPES[recipe]['label']}.",
            "recipe": {"id": recipe, "label": RECIPES[recipe]["label"]}, **out}


def recipes() -> dict:
    return {"recipes": [{"id": k, "label": v["label"], "for": v.get("for", ""), "built": bool(v.get("built"))} for k, v in RECIPES.items()], "default": DEFAULT_RECIPE}


def run(d: str, action: str, x: dict) -> dict:
    rid = x.get("recipe") if isinstance(x.get("recipe"), str) else DEFAULT_RECIPE
    pid = str(x.get("id", ""))[:20]
    if action == "recipes":
        return recipes()
    if action == "suggest":
        scene = x.get("scene")
        return propose(d, rid, scene if isinstance(scene, int) and not isinstance(scene, bool) else None)
    if action == "ask":
        return ask(d, str(x.get("text", "")))
    if action == "accept":
        return accept(d, pid, rid)
    if action == "reject":
        return reject(d, pid, rid)
    if action == "reset_rejected":
        return reset_rejected(d)
    if action == "preview":
        return preview(d, pid, rid)
    raise SystemExit("Unknown action.")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="filmcrafter-smart-editor")
    ap.add_argument("action", choices=["recipes", "suggest", "ask", "accept", "reject", "reset_rejected", "preview"])
    ap.add_argument("project")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    try:
        x = json.loads(a.data)
        print(json.dumps({"event": "result", "data": run(a.project, a.action, x if isinstance(x, dict) else {})}, ensure_ascii=False), flush=True)
        return 0
    except SystemExit as e:
        print(json.dumps({"event": "error", "message": str(e)}), flush=True)
    except Exception as e:                       # noqa: BLE001
        print(json.dumps({"event": "error", "message": __import__("filmcrafter_engine.errtext", fromlist=["plain"]).plain(e)}), flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
