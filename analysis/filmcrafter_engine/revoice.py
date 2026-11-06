"""Perform a line yourself, hear it in a character's voice (speech to speech), on this computer.

You record (or choose) a performance of a line. FilmCrafter changes only the voice into the character's voice and keeps your timing, pauses and feeling as far as the model can. The result is a
new **take** of that line: it sits beside the spoken takes (`cast_voice.takes` / `use_take`), it is never written over, and it is attached to the shot only when you choose it.

Nothing is uploaded and nothing costs money: the conversion runs here, in its own process with its own packages (`vc_worker.py`), after you installed it on purpose. The model files are fetched once,
by the Install step, never by a conversion (a conversion runs with the network switched off for the model library).

Where things live
  <film>/voice/revoice.json                          who has a reference voice, the consent behind it, and a log of every conversion
  <film>/voice/_reference/<person>/<hash><ext>       the reference voice sample (copied in; yours is never touched)
  <film>/voice/_performances/<hash><ext>             your performance, copied in (the original is never touched or changed)
  <film>/voice/_generated/<shot>-rv<hash>.wav        the converted take, with <same>.json beside it saying who performed it and what made it
  ~/.filmcrafter/voiceconv/                          the packages and model files (outside any film; removable)

Consent. A reference sample is either a take already spoken in this film's cast voice (synthetic, so no one's real voice is copied), or a recording of a real voice, which needs `consent: true`, the
name of the person the voice belongs to and what it may be used for. Consent can be taken back (`revoke`); a revoked reference is never used again, and the record of it stays.
Every converted take is marked as synthetic (`synthetic: true`) with what a person performed and which model changed the voice.

  python -m filmcrafter_engine.revoice <status|reference|revoke|convert|install> <film> --data '{...}'
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import safeio
from . import voiceover as V
from .safe import check_id, file_name

MODEL = {"id": "chatterbox-vc", "name": "Chatterbox voice conversion", "licence": "MIT", "by": "Resemble AI",
         "packages": ["torch==2.6.0", "torchaudio==2.6.0", "chatterbox-tts==0.1.7"],
         "size_note": "Several gigabytes in total (the packages and the model files). It is not known exactly until it is installed.",
         "needs": "About 8 GB of memory is comfortable; a graphics card makes it quicker, but it also runs on the processor (Greenroom measured 36 s for an 8 s line on a processor).",
         "status": "experimental"}
HOME = os.path.join(os.path.expanduser("~"), ".filmcrafter", "voiceconv")
REF_MIN, REF_MAX = 3.0, 60.0          # seconds of reference voice
PERF_MAX = 5 * 60.0                   # seconds: a line or a speech, not a scene
CONVERT_TIMEOUT = 30 * 60
INSTALL_TIMEOUT = 2 * 60 * 60
LOG_KEEP = 500
SOURCES = ("film_take", "own_voice", "permission")
PIP_CPU = "https://download.pytorch.org/whl/cpu"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def emit(**kw) -> None:
    try:
        print(json.dumps(kw, ensure_ascii=False), flush=True)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- the runtime (outside any film)

def _ready_path() -> str:
    return os.path.join(HOME, "ready.json")


def _site() -> str:
    return os.path.join(HOME, "site")


def _exec(args: list[str], env: dict | None = None, timeout: int = 600) -> tuple[int, str, str]:
    """Run a program and return (exit code, stdout, stderr). The one place a process is started, so the tests can stand in for it."""
    full = dict(os.environ)
    full.update(env or {})
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=full, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return 124, "", "Timed out."
    except OSError as e:
        return 127, "", str(e)
    return r.returncode, r.stdout, r.stderr


def _worker_env(allow_network: bool) -> dict:
    env = {"PYTHONPATH": _site() + os.pathsep + os.environ.get("PYTHONPATH", ""), "HF_HOME": os.path.join(HOME, "hf"), "PYTHONIOENCODING": "utf-8",
           "TORCH_HOME": os.path.join(HOME, "torch")}
    if not allow_network:
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
    return env


def _worker(mode: str, extra: list[str] | None = None, allow_network: bool = False, timeout: int = 600) -> dict:
    code, out, err = _exec([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vc_worker.py"), mode, *(extra or [])], _worker_env(allow_network), timeout)
    last = ""
    for line in (out or "").splitlines():
        if line.strip().startswith("{"):
            last = line.strip()
    try:
        res = json.loads(last)
    except ValueError:
        tail = " ".join((err or out or "").strip().splitlines()[-2:])[:300]
        return {"ok": False, "why": tail or "The voice-conversion program did not answer."}
    return res if isinstance(res, dict) else {"ok": False, "why": "The voice-conversion program gave an answer FilmCrafter did not understand."}


def runtime_status() -> dict:
    ready = safeio.read_json(_ready_path(), None)
    ok = isinstance(ready, dict) and ready.get("ok") is True
    return {"model": MODEL, "installed": ok, "since": int(ready.get("at") or 0) if ok else None, "versions": ready.get("versions") if ok else None,
            "device": ready.get("device") if ok else None, "folder": HOME,
            "how": "Press Install. It downloads the packages and model files once, onto this computer, and nothing is installed until you do."}


def install(confirmed=False) -> dict:
    """Install the packages and fetch the model files, once. Needs `confirmed: true` (the screen shows the size and licence first). Large, so it is never done without being asked.
    Everything goes into ~/.filmcrafter/voiceconv (nothing in the app, nothing in a film), so removing that folder removes it all."""
    if confirmed is not True:
        raise SystemExit("Installing voice conversion downloads several gigabytes. Confirm it first.")
    os.makedirs(_site(), exist_ok=True)
    emit(event="progress", step=1, total=3, label="Installing the packages")
    code, _, err = _exec([sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", "--target", _site(), "--extra-index-url", PIP_CPU, *MODEL["packages"]],
                         None, INSTALL_TIMEOUT)
    if code:
        raise SystemExit("The packages could not be installed: " + " ".join((err or "").strip().splitlines()[-2:])[:300])
    emit(event="progress", step=2, total=3, label="Checking them")
    chk = _worker("check", timeout=600)
    if not chk.get("ok"):
        raise SystemExit("The packages installed but did not start: " + str(chk.get("why") or ""))
    emit(event="progress", step=3, total=3, label="Fetching the model files")
    got = _worker("install", allow_network=True, timeout=INSTALL_TIMEOUT)
    if not got.get("ok"):
        raise SystemExit("The model files could not be fetched: " + str(got.get("why") or ""))
    safeio.write_json(_ready_path(), {"schema": 1, "ok": True, "at": int(time.time()), "versions": got.get("versions"), "device": got.get("device"), "model": MODEL["id"]})
    return runtime_status()


# ---------------------------------------------------------------- the film's records

def _path(d: str) -> str:
    return os.path.join(d, "voice", "revoice.json")


def _ok(r: object) -> bool:
    return isinstance(r, dict) and (not r or (isinstance(r.get("people", {}), dict) and isinstance(r.get("log", []), list)))


def _records(d: str) -> dict:
    r = safeio.read_json(_path(d), None, check=_ok)
    return r if isinstance(r, dict) and isinstance(r.get("people"), dict) else {"schema": 1, "people": {}, "log": []}


def _update(d: str, change) -> None:
    def wrap(r):
        if not isinstance(r.get("people"), dict):
            r["people"] = {}
        if not isinstance(r.get("log"), list):
            r["log"] = []
        r.setdefault("schema", 1)
        change(r)
        del r["log"][:-LOG_KEEP]
    safeio.update_json(_path(d), wrap, {"schema": 1, "people": {}, "log": []}, check=_ok)


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _person(who: str) -> tuple[str, str]:
    name = str(who or "").strip()[:60]
    k = V.key_of(name)
    if not k:
        raise SystemExit("Choose which character this is for.")
    return k, V.pretty(name)


def _rel(d: str, path: str) -> str:
    return os.path.relpath(path, d).replace(os.sep, "/")


def _copy_in(d: str, src: str, folder: str, digest: str) -> str:
    """Copy `src` into the film under its own hash (so the same file is stored once and a stored file is never rewritten). Returns the film-relative path."""
    ext = os.path.splitext(src)[1].lower()
    rel = f"{folder}/{digest[:16]}{ext}"
    dst = os.path.join(d, *rel.split("/"))
    if not os.path.isfile(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".part"
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    return rel


def _approved(d: str, k: str) -> bool:
    from . import bible as B
    return any(V.key_of(c["name"]) == k and (c.get("voice_profile") or {}).get("approved") is True for c in B.load(d)["characters"])


def _resolve(d: str, file: str) -> tuple[str, bool]:
    """(full path, inside the film's synthetic takes). A path written relative to the film must stay inside it; anything else is a file the person chose."""
    s = str(file or "").strip()
    if not s:
        raise SystemExit("Choose a file.")
    if not os.path.isabs(s):
        full = V.inside(d, s)
        if not full:
            raise SystemExit("That file is not inside this film.")
        return full, s.startswith("voice/_generated/")
    return os.path.abspath(s), False


# ---------------------------------------------------------------- the reference voice and its consent

def status(d: str) -> dict:
    """What is installed, and which characters have a reference voice (with the consent behind it). Free."""
    V._film(d)
    r = _records(d)
    people = []
    for k, p in sorted(r["people"].items()):
        ref = p.get("reference") or {}
        people.append({"key": k, "person": p.get("person") or k, "file": ref.get("file"), "seconds": ref.get("seconds"), "source": ref.get("source"), "holder": ref.get("holder"),
                       "scope": ref.get("scope"), "consent": ref.get("consent"), "revoked": bool(ref.get("revoked_at")), "at": ref.get("at")})
    return {"runtime": runtime_status(), "people": people, "conversions": len(r["log"])}


def set_reference(d: str, who: str, file: str, consent=False, holder: str = "", scope: str = "", replace_approved=False) -> dict:
    """Choose the voice sample the converted performance should sound like. A take already spoken in the cast voice needs no consent (nothing real is copied).
    A recording of a real voice needs `consent: true`, the `holder` (whose voice it is) and the `scope` (what it may be used for)."""
    V._film(d)
    k, name = _person(who)
    full, synthetic = _resolve(d, file)
    info = V.probe(full)
    if not info["ok"]:
        raise SystemExit(info["why"])
    if not (REF_MIN <= info["seconds"] <= REF_MAX):
        raise SystemExit(f"A reference voice should be {REF_MIN:.0f} to {REF_MAX:.0f} seconds long; this one is {info['seconds']:.0f}.")
    if synthetic:
        source, cons = "film_take", {"given": False, "basis": "A take spoken in this film's cast voice; no real person's voice is copied."}
        holder, scope = "", ""
    else:
        if consent is not True:
            raise SystemExit("This is a recording of a real voice. Confirm that its owner agrees before it is used.")
        holder, scope = " ".join(str(holder or "").split())[:80], " ".join(str(scope or "").split())[:200]
        if not holder:
            raise SystemExit("Write whose voice this is (you, or the person who gave permission).")
        if not scope:
            raise SystemExit("Write what this voice may be used for (for example: this film only).")
        source, cons = ("own_voice" if holder.lower() in ("me", "myself", "self") else "permission"), {"given": True, "basis": "Confirmed by the person using FilmCrafter.", "at": int(time.time())}
    if _approved(d, k) and replace_approved is not True and (_records(d)["people"].get(k) or {}).get("reference"):
        raise SystemExit(f"{name}'s voice is approved, so its reference voice was not changed. Take the approval back first, or confirm the replacement.")
    digest = _sha(full)
    rel = _copy_in(d, full, f"voice/_reference/{file_name(k, 40)}", digest)
    entry = {"file": rel, "sha256": digest, "seconds": info["seconds"], "source": source, "holder": holder, "scope": scope, "consent": cons, "at": int(time.time())}

    def change(r):
        p = r["people"].setdefault(k, {"person": name})
        old = p.get("reference")
        if old:
            r["log"].append({"at": int(time.time()), "event": "reference_replaced", "person": k, "was": old.get("file")})
        p["reference"] = entry
        r["log"].append({"at": int(time.time()), "event": "reference_set", "person": k, "file": rel, "source": source})
    _update(d, change)
    return {"person": name, "reference": entry}


def revoke(d: str, who: str, reason: str = "") -> dict:
    """Take back the consent behind a reference voice. It is never used again; the record and the files stay."""
    V._film(d)
    k, name = _person(who)
    if not (_records(d)["people"].get(k) or {}).get("reference"):
        raise SystemExit(f"{name} has no reference voice.")

    def change(r):
        ref = r["people"][k]["reference"]
        ref["revoked_at"] = int(time.time())
        ref["revoked_reason"] = " ".join(str(reason or "").split())[:200]
        r["log"].append({"at": int(time.time()), "event": "reference_revoked", "person": k})
    _update(d, change)
    return {"person": name, "revoked": True}


# ---------------------------------------------------------------- converting a performance

def _out_path(d: str, sid: str, key16: str) -> str:
    return os.path.join(d, "voice", "_generated", f"{sid}-rv{key16}.wav")


def _check_output(path: str, source_seconds: float) -> float:
    """The converted file must really be sound of about the length of the performance, or it is refused (a model can write a silent or empty file)."""
    from . import shotsound
    import numpy as np
    x = shotsound.decode(path, 1)
    if not len(x):
        raise SystemExit("The conversion made a file with no sound in it, so nothing was kept.")
    seconds = len(x) / shotsound.RATE
    if float(np.sqrt(np.mean(np.square(x)))) < V.SILENT_RMS:
        raise SystemExit("The conversion made a silent file, so nothing was kept.")
    if source_seconds > 0 and not (0.5 * source_seconds <= seconds <= 2.0 * source_seconds + 1.0):
        raise SystemExit("The converted line is a very different length from your performance, so it was not kept. Try again.")
    return round(seconds, 2)


def convert(d: str, shot: str, speaker: str, recording: str, performed_by: str = "", note: str = "") -> dict:
    """Change the voice of a performance into the character's reference voice and keep the result as a new take of the line. Free (local). Does not attach it: choose it with `use_take`.
    The same performance and reference give the same take (nothing is made twice)."""
    V._film(d)
    sid = check_id(shot, "shot")
    k, name = _person(speaker)
    if sid not in V._contracts(d):
        raise SystemExit(f"There is no shot {sid} in this film.")
    ref = (_records(d)["people"].get(k) or {}).get("reference")
    if not ref:
        raise SystemExit(f"{name} has no reference voice yet. Choose one first (a take in their voice, or a recording with its owner's permission).")
    if ref.get("revoked_at"):
        raise SystemExit(f"The permission for {name}'s reference voice was taken back, so it can't be used. Choose another.")
    ref_full = V.inside(d, ref.get("file"))
    if not ref_full or not os.path.isfile(ref_full):
        raise SystemExit(f"{name}'s reference voice file is missing. Choose it again.")
    if _sha(ref_full) != ref.get("sha256"):
        raise SystemExit(f"{name}'s reference voice file was changed after permission was given, so it was not used. Choose it again.")
    src, _ = _resolve(d, recording)
    info = V.probe(src)
    if not info["ok"]:
        raise SystemExit(info["why"])
    if info["seconds"] > PERF_MAX:
        raise SystemExit("A performance for one line should be under 5 minutes.")
    perf_digest = _sha(src)
    perf_rel = _copy_in(d, src, "voice/_performances", perf_digest)
    key16 = hashlib.sha256(json.dumps([MODEL["id"], perf_digest, ref["sha256"], sid, k]).encode()).hexdigest()[:16]
    out = _out_path(d, sid, key16)
    rel = _rel(d, out)
    cached = os.path.isfile(out) and os.path.isfile(out[:-4] + ".json")
    seconds = None
    if not cached:
        if not runtime_status()["installed"]:
            raise SystemExit("Voice conversion is not installed yet. Install it first (Settings > Voice conversion); nothing is downloaded until you do.")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmpdir = tempfile.mkdtemp(prefix="fc-vc-")
        try:
            part = os.path.join(tmpdir, "out.wav")
            req = os.path.join(tmpdir, "request.json")
            with open(req, "w", encoding="utf-8") as f:
                json.dump({"source": os.path.join(d, *perf_rel.split("/")), "target": ref_full, "out": part}, f)
            res = _worker("convert", [req], allow_network=False, timeout=CONVERT_TIMEOUT)
            if not res.get("ok") or not os.path.isfile(part):
                raise SystemExit("The voice could not be changed: " + str(res.get("why") or "no file came back") + ". Your performance is kept.")
            seconds = _check_output(part, info["seconds"])
            shutil.move(part, out + ".part")               # across drives a move is a copy; the take appears whole or not at all
            os.replace(out + ".part", out)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        V._write(out[:-4] + ".json", {
            "kind": "revoice", "shot": sid, "key": k, "speaker": name, "text": "", "synthetic": True,
            "disclosure": "Synthetic audio: a person's performance with its voice changed by a model.",
            "performed_by": " ".join(str(performed_by or "").split())[:80] or "a person", "note": " ".join(str(note or "").split())[:300],
            "performance": perf_rel, "performance_sha256": perf_digest, "performance_name": os.path.basename(src)[:120],
            "reference": ref.get("file"), "reference_sha256": ref.get("sha256"), "reference_source": ref.get("source"), "reference_holder": ref.get("holder"),
            "model": MODEL["id"], "model_licence": MODEL["licence"], "voice_name": "re-voiced performance", "at": int(time.time())})

        def change(r):
            r["log"].append({"at": int(time.time()), "event": "converted", "person": k, "shot": sid, "take": rel, "performance": perf_rel})
        _update(d, change)
    return {"shot": sid, "person": name, "take": rel, "performance": perf_rel, "seconds": seconds, "cached": cached, "attached": False,
            "next": "Listen to it next to your performance, then choose it as the take for the shot."}


# ---------------------------------------------------------------- command line

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["status", "reference", "revoke", "convert", "install"])
    ap.add_argument("target")
    ap.add_argument("--data", default="{}")
    a = ap.parse_args(argv)
    d = os.path.abspath(a.target)
    try:
        x = json.loads(a.data or "{}")
        x = x if isinstance(x, dict) else {}
        if a.action == "status":
            res = status(d)
        elif a.action == "reference":
            res = set_reference(d, x.get("person", ""), x.get("file", ""), x.get("consent") is True, x.get("holder", ""), x.get("scope", ""), x.get("replace_approved") is True)
        elif a.action == "revoke":
            res = revoke(d, x.get("person", ""), x.get("reason", ""))
        elif a.action == "convert":
            res = convert(d, x.get("shot", ""), x.get("speaker", ""), x.get("recording", ""), x.get("performed_by", ""), x.get("note", ""))
        else:
            res = install(x.get("confirmed") is True)
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
