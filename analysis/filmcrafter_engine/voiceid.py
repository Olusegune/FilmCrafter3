"""Who a character sounds like, and keeping it that way: the voice identity of each person in a film.

A character's voice identity is three things that already existed, now kept together and protected:
  * the profile in the Production Bible (`bible.voice_profile`: age range, accent, timbre, pace... and the identity fields added here: language, pitch range, vocal weight, texture, breathiness,
    rhythm, articulation, mannerisms, pronunciation notes);
  * the voice they were given (`cast_voice`, in `voice/cast.json`);
  * what this module adds: a **lock** (a record of exactly which voice and model were approved, so a change is noticed), **listening ratings** (what you heard and thought of a voice and its accent),
    a **casting comparison** (candidate voices side by side with why they fit, what auditioning costs and what to check about their licence) and a **cast library** (a character's voice and profile kept on
    this computer to use again in another film).

Nothing here chooses, changes or pays for a voice. The lock only records and reports. An accent is never "verified" by FilmCrafter: the status is what you rated after listening.

  <film>/voice/identity.json              locks and listening ratings per person
  ~/.filmcrafter/cast_library.json        reusable characters (outside any film)

  python -m filmcrafter_engine.voiceid <overview|lock|unlock|rate|compare|cast_library|library_save|library_use> <film> --data '{...}'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

from . import bible as B
from . import cast_voice as C
from . import safeio
from . import voicedirect as VD
from . import voiceover as V

LIB_PATH = os.path.join(os.path.expanduser("~"), ".filmcrafter", "cast_library.json")
AUDITION = "Hello. I'm not sure we have met, but I have heard a great deal about you."
RATINGS_KEEP = 200
HISTORY_KEEP = 50
LIBRARY_KEEP = 300
PREMADE = ("premade", "default")
CLONED = ("cloned", "professional", "generated")


def emit(**kw) -> None:
    try:
        print(json.dumps(kw, ensure_ascii=False), flush=True)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- the film's record

def _path(d: str) -> str:
    return os.path.join(d, "voice", "identity.json")


def _ok(r: object) -> bool:
    return isinstance(r, dict) and (not r or isinstance(r.get("people", {}), dict))


def _records(d: str) -> dict:
    r = safeio.read_json(_path(d), None, check=_ok)
    return r if isinstance(r, dict) and isinstance(r.get("people"), dict) else {"schema": 1, "people": {}}


def _update(d: str, change) -> None:
    def wrap(r):
        if not isinstance(r.get("people"), dict):
            r["people"] = {}
        r.setdefault("schema", 1)
        change(r)
    safeio.update_json(_path(d), wrap, {"schema": 1, "people": {}}, check=_ok)


def _person_rec(r: dict, k: str) -> dict:
    p = r["people"].setdefault(k, {})
    if not isinstance(p.get("ratings"), list):
        p["ratings"] = []
    if not isinstance(p.get("history"), list):
        p["history"] = []
    return p


def _character(d: str, who: str) -> dict:
    k = V.key_of(who)
    if not k:
        raise SystemExit("Choose a character.")
    for c in B.load(d)["characters"]:
        if V.key_of(c["name"]) == k:
            return c
    raise SystemExit("That character is not in the Production Bible.")


def _voice_of(d: str, key: str) -> dict | None:
    v = C._cast(d)["people"].get(key)
    return v if isinstance(v, dict) and v.get("voice_id") else None


def _reference_sha(d: str, key: str) -> str | None:
    try:
        from . import revoice as R
        ref = (R._records(d)["people"].get(key) or {}).get("reference") or {}
        return None if ref.get("revoked_at") else ref.get("sha256")
    except Exception:
        return None


def _snapshot(d: str, key: str) -> dict:
    v = _voice_of(d, key)
    if not v:
        raise SystemExit("This character has no voice to lock yet.")
    return {"voice_id": v["voice_id"], "voice_name": str(v.get("voice_name") or "")[:80], "model": v.get("model"), "made": v.get("made"),
            "reference_sha256": _reference_sha(d, key), "at": int(time.time())}


# ---------------------------------------------------------------- listening ratings

def accent_status(ratings: list[dict]) -> dict:
    """What the listener's own ratings add up to for one voice. FilmCrafter does not judge an accent; it reports what you rated."""
    rs = [r for r in ratings if isinstance(r.get("accent_score"), int)]
    if not rs:
        return {"status": "untested", "words": "Not listened to and rated yet."}
    avg = sum(r["accent_score"] for r in rs) / len(rs)
    n = len(rs)
    if avg >= 4:
        s, w = "accepted", f"You rated the accent {avg:.1f} of 5 after listening ({n} rating{'s' if n != 1 else ''})."
    elif avg <= 2:
        s, w = "not_convincing", f"You rated the accent {avg:.1f} of 5 after listening ({n} rating{'s' if n != 1 else ''}): not convincing to you."
    else:
        s, w = "mixed", f"You rated the accent {avg:.1f} of 5 ({n} rating{'s' if n != 1 else ''}): mixed."
    return {"status": s, "words": w + " This is your judgement as a listener, not a measurement."}


def _score(x, name: str):
    if x in (None, ""):
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)) or int(x) != x or not (1 <= int(x) <= 5):
        raise SystemExit(f"{name} must be a whole number from 1 to 5.")
    return int(x)


def rate(d: str, who: str, voice_id: str, accent_score=None, natural_score=None, accent: str = "", note: str = "") -> dict:
    """Write down what you thought of a voice after listening: how convincing its accent was and how natural it sounded (1 to 5). Free; kept in the film."""
    V._film(d)
    ch = _character(d, who)
    vid = str(voice_id or "")
    if not C.VOICE_ID.fullmatch(vid):
        raise SystemExit("Choose one of the voices you listened to.")
    a, n = _score(accent_score, "The accent rating"), _score(natural_score, "The natural rating")
    if a is None and n is None:
        raise SystemExit("Give the accent or the natural rating (1 to 5).")
    entry = {"voice_id": vid, "accent": " ".join(str(accent or "").split())[:40].lower(), "accent_score": a, "natural_score": n, "note": " ".join(str(note or "").split())[:300], "at": int(time.time())}
    k = V.key_of(ch["name"])

    def change(r):
        p = _person_rec(r, k)
        p["ratings"].append(entry)
        del p["ratings"][:-RATINGS_KEEP]
    _update(d, change)
    return {"person": ch["name"], "rating": entry, "accent": accent_status([x for x in _person_rec(_records(d), k)["ratings"] if x.get("voice_id") == vid])}


# ---------------------------------------------------------------- the lock and the consistency report

def lock(d: str, who: str) -> dict:
    """Record exactly which voice and model are the character's approved voice, so any later change is noticed. Free. (Approving in the Bible is still your separate act.)"""
    V._film(d)
    ch = _character(d, who)
    k = V.key_of(ch["name"])
    snap = _snapshot(d, k)

    def change(r):
        p = _person_rec(r, k)
        if p.get("lock"):
            p["history"].append({**p["lock"], "ended": int(time.time()), "why": "replaced by a new lock"})
            del p["history"][:-HISTORY_KEEP]
        p["lock"] = snap
    _update(d, change)
    return {"person": ch["name"], "lock": snap}


def unlock(d: str, who: str) -> dict:
    """Stop watching a character's voice. The record is kept in the history."""
    V._film(d)
    ch = _character(d, who)
    k = V.key_of(ch["name"])

    def change(r):
        p = _person_rec(r, k)
        if p.get("lock"):
            p["history"].append({**p["lock"], "ended": int(time.time()), "why": "unlocked"})
            del p["history"][:-HISTORY_KEEP]
            p["lock"] = None
    _update(d, change)
    return {"person": ch["name"], "lock": None}


def _consistency(d: str, key: str, lock_rec: dict | None, approved: bool) -> dict:
    """ok | unlocked | changed | missing: and the plain reasons. Nothing here changes anything."""
    cur = _voice_of(d, key)
    if not lock_rec:
        return {"state": "unlocked", "problems": [], "words": "Approved, but not locked: a change of voice would not be noticed." if approved else "Not locked."}
    if not cur:
        return {"state": "missing", "problems": ["The locked voice was taken off this character."], "words": "The voice that was locked is no longer on this character."}
    problems = []
    if cur["voice_id"] != lock_rec.get("voice_id"):
        problems.append(f"The voice changed from {lock_rec.get('voice_name') or 'the locked voice'} to {cur.get('voice_name') or 'another voice'}.")
    if cur.get("model") != lock_rec.get("model"):
        problems.append(f"The speech model changed from {lock_rec.get('model')} to {cur.get('model')}.")
    if lock_rec.get("reference_sha256") != _reference_sha(d, key):
        problems.append("The reference voice used for speech to speech changed.")
    return {"state": "changed" if problems else "ok", "problems": problems, "words": " ".join(problems) if problems else "Same voice, model and reference as when it was locked."}


def overview(d: str) -> dict:
    """Every character's voice identity at a glance: profile, voice, lock and consistency, and what you thought of the voice they have. Free."""
    V._film(d)
    rec = _records(d)
    people = []
    for c in B.load(d)["characters"]:
        k = V.key_of(c["name"])
        prof = c.get("voice_profile") or {}
        p = rec["people"].get(k) or {}
        voice = _voice_of(d, k)
        mine = [x for x in (p.get("ratings") or []) if voice and x.get("voice_id") == voice["voice_id"]]
        naturals = [x["natural_score"] for x in mine if isinstance(x.get("natural_score"), int)]
        people.append({"id": c["id"], "name": c["name"], "key": k, "role": c.get("role", ""), "approved": prof.get("approved") is True,
                       "voice": ({"voice_id": voice["voice_id"], "voice_name": voice.get("voice_name"), "model": voice.get("model"), "made": voice.get("made")} if voice else None),
                       "lock": p.get("lock"), "consistency": _consistency(d, k, p.get("lock"), prof.get("approved") is True),
                       "accent": accent_status(mine), "natural": round(sum(naturals) / len(naturals), 1) if naturals else None, "ratings": len(mine),
                       "history": (p.get("history") or [])[-5:]})
    flagged = sum(1 for x in people if x["consistency"]["state"] in ("changed", "missing"))
    return {"people": people, "flagged": flagged}


# ---------------------------------------------------------------- casting comparison

def _licence_note(category: str) -> str:
    c = str(category or "").lower()
    if c in PREMADE:
        return "One of ElevenLabs' own voices; use is covered by your plan's terms."
    if c in CLONED:
        return "A cloned or community voice: check its owner's terms and your plan's licence before you use it in a film you share."
    return "Check this voice's licence in ElevenLabs before you use it in a film you share."


def compare(d: str, who: str, candidates: list, model: str | None = None) -> dict:
    """Candidate voices side by side for one character: how well each fits their profile and why, what hearing it say a line would use of your plan, a licence reminder, what you rated it before and
    where it is available. Free: the candidates are voices the screen already looked up; nothing is sent or made. Emotional range and accent authenticity are not in a voice's labels, so they are not
    claimed: listen, then rate."""
    V._film(d)
    ch = _character(d, who)
    k = V.key_of(ch["name"])
    prof = ch.get("voice_profile") or {}
    w = VD.wanted_from_text(prof.get("description", ""), prof.get("age_range", ""), ch.get("age", ""), ch.get("role", ""), ch.get("voice", ""), ch.get("notes", ""))
    w["accent"] = " ".join(str(prof.get("accent") or "").split())[:40].lower()
    w["descriptors"] = [x for x in VD._words_of(" ".join([prof.get("description", ""), prof.get("timbre", ""), prof.get("texture", ""), ch.get("voice", "")])) if len(x) > 3][:4]
    cur = _voice_of(d, k)
    mdl = C._model(model or (cur or {}).get("model"))
    audition = C._credits(AUDITION, mdl)
    mine = (_records(d)["people"].get(k) or {}).get("ratings") or []
    rows = []
    for v in (candidates or [])[:60]:
        if not isinstance(v, dict) or not C.VOICE_ID.fullmatch(str(v.get("voice_id") or "")):
            continue
        clean = {"voice_id": v["voice_id"], "name": str(v.get("name") or "")[:80], "category": str(v.get("category") or "")[:30], "description": str(v.get("description") or "")[:200],
                 "labels": {str(a)[:30]: str(b)[:40] for a, b in list((v.get("labels") or {}).items())[:8]} if isinstance(v.get("labels"), dict) else {}, "preview_url": str(v.get("preview_url") or "")[:300]}
        s, why = VD.score_voice(clean, w)
        r = [x for x in mine if x.get("voice_id") == clean["voice_id"]]
        nat = [x["natural_score"] for x in r if isinstance(x.get("natural_score"), int)]
        rows.append({"voice": clean, "score": round(s, 1), "why": why, "current": bool(cur and cur["voice_id"] == clean["voice_id"]),
                     "available": {"where": "ElevenLabs (online; needs your key)", "local": False},
                     "audition_credits": audition["amount"], "audition_basis": audition["basis"] + " (an estimate)", "licence": _licence_note(clean["category"]),
                     "rated": {"count": len(r), "natural": round(sum(nat) / len(nat), 1) if nat else None, "accent": accent_status(r)}})
    rows.sort(key=lambda x: (-x["score"], x["voice"]["name"].lower()))
    return {"person": ch["name"], "wanted": w, "rows": rows[:12], "searched": len(rows), "model": mdl,
            "note": "Fit comes from the labels ElevenLabs gives each voice. It says nothing about how a voice performs emotion or how real an accent is: listen and rate."}


# ---------------------------------------------------------------- the cast library (reusable across films)

def _lib_ok(r: object) -> bool:
    return isinstance(r, dict) and (not r or isinstance(r.get("entries", []), list))


def _lib() -> dict:
    r = safeio.read_json(LIB_PATH, None, check=_lib_ok)
    return r if isinstance(r, dict) and isinstance(r.get("entries"), list) else {"schema": 1, "entries": []}


def cast_library() -> dict:
    """Characters kept on this computer to use again in another film. Free."""
    return {"entries": [{k: e.get(k) for k in ("id", "name", "voice", "profile", "film", "saved", "note", "rights")} for e in _lib()["entries"]][-LIBRARY_KEEP:]}


def library_save(d: str, who: str, note: str = "") -> dict:
    """Keep a character's profile and chosen voice on this computer so another film can use them. Saves a reference to the voice in your ElevenLabs account, not the audio. Free."""
    V._film(d)
    ch = _character(d, who)
    k = V.key_of(ch["name"])
    voice = _voice_of(d, k)
    if not voice:
        raise SystemExit(f"{ch['name']} has no voice to keep yet.")
    prof = {a: b for a, b in (ch.get("voice_profile") or {}).items() if a != "approved" and isinstance(b, str) and b}
    rights = ("This voice was cloned from a recording. Be sure its owner agrees to its use in another film." if voice.get("made") == "clone"
              else "Check your ElevenLabs plan's terms for this voice." if voice.get("made") != "design" else "Designed in FilmCrafter.")
    entry = {"id": hashlib.sha256(f"{ch['name']}|{voice['voice_id']}".encode()).hexdigest()[:12], "name": ch["name"],
             "voice": {a: voice.get(a) for a in ("voice_id", "voice_name", "model", "made", "stability", "similarity", "style", "speed")},
             "profile": prof, "film": os.path.basename(os.path.normpath(d))[:80], "saved": int(time.time()), "note": " ".join(str(note or "").split())[:200], "rights": rights}

    def change(r):
        if not isinstance(r.get("entries"), list):
            r["entries"] = []
        r.setdefault("schema", 1)
        r["entries"] = [e for e in r["entries"] if e.get("id") != entry["id"]] + [entry]
        del r["entries"][:-LIBRARY_KEEP]
    safeio.update_json(LIB_PATH, change, {"schema": 1, "entries": []}, check=_lib_ok)
    return {"saved": entry}


def library_use(d: str, who: str, entry_id: str, replace_approved=False, rights_confirmed=False) -> dict:
    """Give a character a voice and profile from the cast library. An approved voice is never replaced without `replace_approved`; a cloned voice needs `rights_confirmed`. The new voice is not
    approved or locked: that stays your decision."""
    V._film(d)
    ch = _character(d, who)
    e = next((x for x in _lib()["entries"] if x.get("id") == str(entry_id or "")), None)
    if not e:
        raise SystemExit("That saved character is not in the cast library.")
    v = e.get("voice") or {}
    if v.get("made") == "clone" and rights_confirmed is not True:
        raise SystemExit("This voice was cloned from a recording. Confirm that its owner agrees to its use in this film first.")
    res = C.set_voice(d, ch["name"], {k: v.get(k) for k in ("voice_id", "voice_name", "model", "stability", "similarity", "style", "speed")}, made=v.get("made") or "library",
                      replace_approved=replace_approved is True)
    prof = {a: b for a, b in (e.get("profile") or {}).items() if a in B.VOICE_PROFILE_FIELDS + B.IDENTITY_FIELDS}
    if prof:
        B.set_voice_profile(d, ch["id"], prof)
    return {"person": ch["name"], "voice": res["voice"], "profile": sorted(prof)}


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["overview", "lock", "unlock", "rate", "compare", "cast_library", "library_save", "library_use"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        if a.action == "overview":
            res = overview(d)
        elif a.action == "lock":
            res = lock(d, x.get("person", ""))
        elif a.action == "unlock":
            res = unlock(d, x.get("person", ""))
        elif a.action == "rate":
            res = rate(d, x.get("person", ""), x.get("voice_id", ""), x.get("accent_score"), x.get("natural_score"), x.get("accent", ""), x.get("note", ""))
        elif a.action == "compare":
            res = compare(d, x.get("person", ""), x.get("candidates") or [], x.get("model"))
        elif a.action == "cast_library":
            res = cast_library()
        elif a.action == "library_save":
            res = library_save(d, x.get("person", ""), x.get("note", ""))
        else:
            res = library_use(d, x.get("person", ""), x.get("id", ""), x.get("replace_approved") is True, x.get("rights_confirmed") is True)
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
