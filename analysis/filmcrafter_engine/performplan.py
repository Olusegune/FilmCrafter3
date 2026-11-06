"""A vocal performance plan for one line: what the person wants, how the feeling changes inside the line, where the breaths, laughs and efforts fall, and how the body affects the voice.

The plan is model-independent and editable. It is turned into words a speaking model can read (`compile`) only for the model that will speak it, and only the parts that model can really be asked for
are included; the rest is listed as "not carried" with the reason, never silently dropped and never promised. Applying a plan makes the compiled words the line's **spoken version** (`voicedirect`), the
same mechanism the Line Studio already uses, so nothing here speaks, spends or replaces a recording. Speaking it is the existing "Speak this", with its price and its yes.

Positions are **gaps between words**: gap 0 is before the first word, gap 3 is after the third, gap N is after the last. Arcs, sounds and pauses all use them.

  <film>/voice/performplan.json     { lines: { <shot>: { <person>: plan } } }

  python -m filmcrafter_engine.performplan <get|set|apply|clear> <film> --data '{...}'
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

from . import safeio
from . import voicedirect as VD
from . import voiceover as V
from .safe import check_id

TAG = re.compile(r"\[[^\]]*\]")
MAX_ARC, MAX_EVENTS, MAX_PAUSES, MAX_EMPHASIS = 12, 30, 20, 20
NOTE = 400

# emotion -> (tag, verified). "verified" means Greenroom Local's notes record that the tag did what it says on a real run; the rest are common tags that were not checked, and are labelled so.
EMOTIONS: dict[str, tuple[str, bool]] = {
    "neutral": ("", True), "excited": ("excited", False), "happy": ("happy", False), "sad": ("sad", False), "angry": ("angry", False), "annoyed": ("annoyed", False),
    "scared": ("scared", False), "nervous": ("nervous", False), "tender": ("tender", False), "sarcastic": ("sarcastic", False), "tired": ("tired", False),
    "whisper": ("whispers", True), "shouting": ("shouting", False), "warm": ("warm", False), "furious": ("furious", False), "amused": ("amused", False),
}
EVENTS: dict[str, tuple[str, bool, str]] = {      # kind -> (tag, verified, group)
    "breath": ("exhales", False, "breathing"), "heavy_breathing": ("breathing heavily", False, "breathing"), "panting": ("panting", False, "breathing"), "out_of_breath": ("out of breath", True, "breathing"),
    "inhale": ("inhales sharply", False, "breathing"), "breath_catch": ("catches breath", False, "breathing"),
    "chuckle": ("chuckles", False, "laughter"), "laugh": ("laughs", True, "laughter"), "giggle": ("giggles", False, "laughter"), "nervous_laugh": ("nervous laugh", False, "laughter"),
    "grunt": ("grunts", False, "effort"), "groan": ("groans", False, "effort"), "strain": ("straining", False, "effort"), "wince": ("winces", False, "effort"),
    "gasp": ("gasps", True, "emotion"), "sigh": ("sighs", True, "emotion"), "cry": ("crying", True, "emotion"), "sob": ("sobs", False, "emotion"), "whimper": ("whimpers", False, "emotion"),
    "cough": ("coughs", True, "other"), "clear_throat": ("clears throat", False, "other"), "sniffle": ("sniffles", False, "other"),
}
# activity -> (leading tag when the body is clearly working, verified). None: a voice model cannot be asked for this reliably.
ACTIVITIES: dict[str, tuple[str | None, bool]] = {
    "still": (None, True), "walking": (None, True), "running": ("out of breath", True), "lifting": ("straining", False), "pushing": ("straining", False), "fighting": ("panting", False),
    "injured": ("winces", False), "cold": (None, True), "crying": ("crying", True), "hiding": ("whispers", True), "eating": (None, True), "drinking": (None, True), "carrying": ("straining", False),
    "rain": (None, True), "tired": ("tired", False),
}
UNREQUESTABLE = {"eating": "speaking with food in the mouth", "drinking": "speaking while drinking", "cold": "shivering", "rain": "speaking in the rain", "walking": "walking", "still": ""}


def emit(**kw) -> None:
    try:
        print(json.dumps(kw, ensure_ascii=False), flush=True)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- cleaning a plan (everything comes from the screen)

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


def _i(v, lo: int, hi: int, default: int | None = None):
    try:
        x = int(v)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, x))


def _gap(v, lo: int, hi: int):
    """A position that must really exist: a gap that is not in the line is dropped, never moved to the nearest one."""
    try:
        x = int(v)
    except (TypeError, ValueError):
        return None
    return x if lo <= x <= hi else None


def _label(v) -> str:
    """A feeling written in the person's own words, safe to put inside [ ]."""
    return re.sub(r"[^A-Za-z0-9 '\-]", "", _t(v, 40)).strip().lower()


def words_of(text: str) -> list[str]:
    return TAG.sub(" ", str(text or "")).replace("[", " ").replace("]", " ").split()


def clean(raw: dict | None, n_words: int) -> dict:
    """A plan made only of what is allowed: known sounds, gaps that exist, numbers in range, limited lists. Unknown things are dropped, not kept."""
    x = raw if isinstance(raw, dict) else {}
    arc, seen = [], set()
    for a in (x.get("arc") or [])[:MAX_ARC * 2]:
        if not isinstance(a, dict):
            continue
        at, em = _gap(a.get("at"), 0, n_words), _label(a.get("emotion"))
        if at is None or not em or at in seen:
            continue
        seen.add(at)
        arc.append({"at": at, "emotion": em, "intensity": round(_n(a.get("intensity"), 0, 1, 0.5), 2)})
    arc = sorted(arc, key=lambda a: a["at"])[:MAX_ARC]
    events = []
    for e in (x.get("events") or [])[:MAX_EVENTS * 2]:
        if not isinstance(e, dict) or e.get("kind") not in EVENTS:
            continue
        at = _gap(e.get("after_word"), 0, n_words)
        if at is not None:
            events.append({"kind": e["kind"], "after_word": at, "intensity": round(_n(e.get("intensity"), 0, 1, 0.5), 2)})
    events = sorted(events, key=lambda e: e["after_word"])[:MAX_EVENTS]
    pauses = []
    for p in (x.get("pauses") or [])[:MAX_PAUSES * 2]:
        if isinstance(p, dict) and _gap(p.get("after_word"), 1, n_words) is not None:
            pauses.append({"after_word": _gap(p["after_word"], 1, n_words), "ms": _i(p.get("ms"), 100, 3000, 500)})
    pauses = sorted(pauses, key=lambda p: p["after_word"])[:MAX_PAUSES]
    emph = sorted({w for w in (_gap(v, 0, n_words - 1) for v in (x.get("emphasis") or [])[:MAX_EMPHASIS * 2]) if w is not None})[:MAX_EMPHASIS]
    ph = x.get("physical") if isinstance(x.get("physical"), dict) else {}
    act = ph.get("activity") if ph.get("activity") in ACTIVITIES else "still"
    return {"objective": _t(x.get("objective"), NOTE), "subtext": _t(x.get("subtext"), NOTE), "outward": _t(x.get("outward"), 80), "concealed": _t(x.get("concealed"), 80),
            "direction": _t(x.get("direction"), NOTE), "arc": arc, "events": events, "pauses": pauses, "emphasis": emph,
            "physical": {"activity": act, "effort": round(_n(ph.get("effort"), 0, 1, 0), 2), "fatigue": round(_n(ph.get("fatigue"), 0, 1, 0), 2), "pain": round(_n(ph.get("pain"), 0, 1, 0), 2),
                         "breathlessness": round(_n(ph.get("breathlessness"), 0, 1, 0), 2), "note": _t(ph.get("note"), 200)},
            "pace": round(_n(x.get("pace"), 0.7, 1.2, 1.0), 2), "approved": x.get("approved") is True}


# ---------------------------------------------------------------- compiling for a model

def _emotion_tag(name: str) -> tuple[str, bool]:
    if name in EMOTIONS:
        return EMOTIONS[name]
    return name, False                                  # the person's own words: passed as written, and said to be unchecked


def compile(plan: dict, text: str, model: str | None) -> dict:  # noqa: A001 (the engine calls it compile)
    """The words to speak for this plan and model, what could not be carried and why, which tags nobody has checked, and a suggested speed. Pure: no file, no network, no cost."""
    from .cast_voice import MAX_LINE, TAGGED, _model
    mdl = _model(model)
    tagged = mdl in TAGGED
    words = words_of(text)
    n = len(words)
    p = clean(plan, n)
    dropped, unverified, used = [], [], []
    toks = list(words)

    def note_tag(tag: str, ok: bool) -> None:
        if tag and tag not in used:
            used.append(tag)
        if tag and not ok and tag not in unverified:
            unverified.append(tag)

    if tagged:
        for w in p["emphasis"]:
            if 0 <= w < n:
                toks[w] = toks[w].upper()
    else:
        if p["emphasis"]:
            dropped.append({"what": "emphasis on words", "why": "This model would not reliably stress capitalised words."})
    for q in p["pauses"]:
        i = q["after_word"] - 1
        if 0 <= i < n:
            toks[i] = toks[i].rstrip(".…") + (" ... ..." if q["ms"] >= 1500 else "...")

    gaps: dict[int, list[str]] = {g: [] for g in range(n + 1)}
    lead: list[str] = []
    prev = "neutral"
    for a in p["arc"]:
        tag, ok = _emotion_tag(a["emotion"])
        if a["emotion"] == prev:
            continue
        prev = a["emotion"]
        if not tagged:
            dropped.append({"what": f"feeling \"{a['emotion']}\" at word {a['at']}", "why": "This model cannot be directed inside a line. Choose Eleven v4 to change feeling word by word."})
        elif tag:
            gaps[a["at"]].append(f"[{tag}]")
            note_tag(tag, ok)
    for e in p["events"]:
        tag, ok, _g = EVENTS[e["kind"]]
        if not tagged:
            dropped.append({"what": f"{e['kind'].replace('_', ' ')} after word {e['after_word']}", "why": "This model would speak the sound's name aloud. Choose Eleven v4, or record it and use speech to speech."})
        else:
            gaps[e["after_word"]].append(f"[{tag}]")
            note_tag(tag, ok)

    ph = p["physical"]
    act_tag, act_ok = ACTIVITIES[ph["activity"]]
    working = max(ph["effort"], ph["breathlessness"], ph["pain"], ph["fatigue"]) >= 0.5 or ph["activity"] in ("running", "crying", "hiding")
    if ph["activity"] in UNREQUESTABLE and UNREQUESTABLE[ph["activity"]] and ph["activity"] in ("eating", "drinking", "cold", "rain"):
        dropped.append({"what": UNREQUESTABLE[ph["activity"]], "why": "A speaking model cannot be asked for this reliably. Record it yourself and use speech to speech, or add a sound effect."})
    if tagged and working:
        for cond, tag, ok in ((ph["breathlessness"] >= 0.5, "out of breath", True), (ph["effort"] >= 0.5, "straining", False), (ph["pain"] >= 0.4, "winces", False), (ph["fatigue"] >= 0.5, "tired", False),
                              (act_tag is not None and ph["activity"] in ("running", "crying", "hiding"), act_tag, act_ok)):
            if cond and tag and f"[{tag}]" not in lead:
                lead.append(f"[{tag}]")
                note_tag(tag, ok)
    elif not tagged and working:
        dropped.append({"what": "the body's effort, breathlessness, pain or tiredness", "why": "This model cannot be asked for it. Choose Eleven v4, or record the line and use speech to speech."})

    out: list[str] = list(lead)
    for g in range(n + 1):
        out.extend(gaps[g])
        if g < n:
            out.append(toks[g])
    spoken = " ".join(out)
    if len(spoken) > MAX_LINE:
        raise SystemExit(f"With everything in it this line is {len(spoken)} characters, over the {MAX_LINE} limit. Split it across shots or take some of the sounds out.")
    speed = round(max(0.7, min(1.2, p["pace"] - 0.1 * ph["fatigue"] - 0.05 * ph["breathlessness"])), 2)
    return {"model": mdl, "tagged": tagged, "text": spoken, "tags": used, "unverified": unverified, "not_carried": dropped, "speed": speed,
            "words": words, "stripped_tags": len(TAG.findall(str(text or "")))}


# ---------------------------------------------------------------- the film's plans

def _path(d: str) -> str:
    return os.path.join(d, "voice", "performplan.json")


def _ok(r: object) -> bool:
    return isinstance(r, dict) and isinstance(r.get("lines", {}), dict)


def _load(d: str) -> dict:
    r = safeio.read_json(_path(d), None, check=_ok)
    return r if isinstance(r, dict) and isinstance(r.get("lines"), dict) else {"schema": 1, "lines": {}}


def _line(d: str, shot: str, speaker: str) -> tuple[str, str, str, str]:
    """(shot id, person key, person name, the words the plan is for: their spoken version if there is one, else the written line, with any [tags] taken out)."""
    V._film(d)
    sid = check_id(shot, "shot")
    k = V.key_of(speaker)
    if not k:
        raise SystemExit("Choose who is speaking.")
    written, name = VD._written(d, sid, k)
    base = VD.performance_text(d, sid, k) or written
    return sid, k, name, " ".join(words_of(base))


def get(d: str, shot: str, speaker: str, model: str | None = None) -> dict:
    """The plan for this line (a blank one if none), the words it compiles to for the model, and whether those words are the line's spoken version now. Free."""
    from . import cast_voice as C
    sid, k, name, text = _line(d, shot, speaker)
    saved = ((_load(d)["lines"].get(sid) or {}).get(k)) or None
    voice = C._cast(d)["people"].get(k) or {}
    n = len(words_of(text))
    plan = clean((saved or {}).get("plan"), n) if saved else clean({}, n)
    # a plan made for other words is kept but flagged: its gaps may no longer fall where they were meant to
    base = (saved or {}).get("base_text", text)
    stale = bool(saved) and " ".join(words_of(base)) != text
    comp = compile(plan, text, model or voice.get("model"))
    spoken_now = VD.performance_text(d, sid, k)
    return {"shot": sid, "person": name, "text": text, "words": comp["words"], "plan": plan, "saved": bool(saved), "stale": stale, "compiled": comp,
            "applied": bool(saved) and bool(spoken_now) and spoken_now == comp["text"], "voice_model": voice.get("model"),
            "events": {kind: {"tag": t, "verified": v, "group": g} for kind, (t, v, g) in EVENTS.items()},
            "emotions": {e: {"tag": t, "verified": v} for e, (t, v) in EMOTIONS.items()}, "activities": sorted(ACTIVITIES)}


def set_plan(d: str, shot: str, speaker: str, plan: dict, model: str | None = None) -> dict:
    """Save the plan for a line. The words, the written line and the spoken version are not touched."""
    sid, k, name, text = _line(d, shot, speaker)
    n = len(words_of(text))
    cleaned = clean(plan, n)

    def change(data):
        data.setdefault("schema", 1)
        data.setdefault("lines", {})
        data["lines"].setdefault(sid, {})[k] = {"speaker": name, "plan": cleaned, "base_text": text, "updated": int(time.time())}
        return data
    safeio.update_json(_path(d), change, {"schema": 1, "lines": {}}, check=_ok)
    return get(d, sid, speaker, model)


def apply(d: str, shot: str, speaker: str, model: str | None = None) -> dict:
    """Make the compiled words the line's spoken version. This is the person's act; it speaks nothing and costs nothing. The written line is never changed; clearing the spoken version goes back to it."""
    g = get(d, shot, speaker, model)
    if not g["saved"]:
        raise SystemExit("Save the plan first.")
    if g["stale"]:
        raise SystemExit("The words of this line changed after the plan was made, so its positions may be wrong. Check the plan and save it again.")
    if not g["plan"]["approved"]:
        raise SystemExit("Approve the plan first.")
    c = g["compiled"]
    if not c["text"].strip():
        raise SystemExit("There is nothing to speak.")
    note = _t("Performance plan: " + "; ".join(x for x in (g["plan"]["objective"], g["plan"]["subtext"]) if x), 400)
    VD.set_performance(d, g["shot"], speaker, c["text"], note=note, source="person")
    return {**get(d, shot, speaker, model), "spoken_version": c["text"]}


def clear(d: str, shot: str, speaker: str) -> dict:
    """Forget the plan for this line. A spoken version made from it stays until you clear it."""
    sid, k, _name, _text = _line(d, shot, speaker)
    if os.path.isfile(_path(d)):
        def change(data):
            (data.get("lines") or {}).get(sid, {}).pop(k, None)
            if sid in data.get("lines", {}) and not data["lines"][sid]:
                data["lines"].pop(sid)
            return data
        safeio.update_json(_path(d), change, {"schema": 1, "lines": {}}, check=_ok)
    return get(d, sid, speaker)


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["get", "set", "apply", "clear"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        if a.action == "get":
            res = get(d, x.get("shot", ""), x.get("speaker", ""), x.get("model"))
        elif a.action == "set":
            res = set_plan(d, x.get("shot", ""), x.get("speaker", ""), x.get("plan") or {}, x.get("model"))
        elif a.action == "apply":
            res = apply(d, x.get("shot", ""), x.get("speaker", ""), x.get("model"))
        else:
            res = clear(d, x.get("shot", ""), x.get("speaker", ""))
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
