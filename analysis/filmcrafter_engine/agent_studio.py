"""Persistent, local orchestration state for Agent Studio.

This module deliberately does not submit provider work.  It records the creative
brief, checkpoints and approvals, while paid execution stays behind FilmCrafter's
existing spend-token confirmation path.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

FILE = "agent-studio.json"
STAGES = [
    ("story", "Story & shot plan"),
    ("direction", "Cast & visual direction"),
    ("storyboard", "Storyboard & keyframes"),
    ("first_scene", "First scene preview"),
    ("scenes", "Remaining scenes"),
    ("audio", "Voices & sound"),
    ("preview", "Preview cut"),
    ("export", "Final review & export"),
]
MODES = {"guided", "balanced", "custom"}
ASPECTS = {"2.39:1", "21:9", "16:9", "4:3", "1:1", "4:5", "3:4", "9:16", "9:21"}
CHECKPOINTS = {
    "guided": [x[0] for x in STAGES],
    "balanced": ["story", "direction", "first_scene", "preview"],
}


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path: str, value: dict) -> None:
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _clean(value, limit=20000):
    text = "" if value is None else str(value)
    return "".join(c for c in text if c >= " " or c in "\n\t")[:limit].strip()


def _project(d):
    return _read(os.path.join(d, "project.json"), {}) or {}


def _plan(d):
    return (_read(os.path.join(d, "directed.json")) or
            _read(os.path.join(d, "production.json")) or {})


def _jobs(d):
    return (_read(os.path.join(d, "jobs.json"), {"jobs": []}) or {"jobs": []}).get("jobs", [])


def _base(d):
    p, plan = _project(d), _plan(d)
    shots = [s for scene in plan.get("scenes", []) for s in scene.get("shots", [])]
    script = p.get("script_text") or p.get("story") or ""
    return {
        "version": 1,
        "paused": False,
        "created": int(time.time()),
        "updated": int(time.time()),
        "brief": {
            "story": _clean(script),
            "style": (p.get("look") or {}).get("style", "auto") if isinstance(p.get("look"), dict) else str(p.get("look") or "auto"),
            "duration": "3–4 minutes",
            "aspect": p.get("aspect_ratio", "16:9"),
            "budget_limit": 30.0,
            "checkin_mode": "balanced",
            "checkpoints": CHECKPOINTS["balanced"],
        },
        "current": "story",
        "stages": [{"id": sid, "label": label, "state": "not_started"} for sid, label in STAGES],
        "approvals": [],
        "revisions": [],
        "activity": [{"id": uuid.uuid4().hex, "at": int(time.time()), "kind": "created", "text": "Agent Studio opened for this project."}],
        "existing": {"scenes": len(plan.get("scenes", [])), "shots": len(shots)},
    }


def _path(d):
    return os.path.join(d, FILE)


def _load(d):
    value = _read(_path(d))
    return value if isinstance(value, dict) else _base(d)


def _activity(w, kind, text):
    w.setdefault("activity", []).append({"id": uuid.uuid4().hex, "at": int(time.time()), "kind": kind, "text": _clean(text, 500)})
    w["activity"] = w["activity"][-100:]


def _save(d, w):
    w["updated"] = int(time.time())
    _write(_path(d), w)
    return state(d, w)


def _stage(w, sid):
    return next((s for s in w["stages"] if s["id"] == sid), None)


def state(d, w=None):
    w = w or _load(d)
    jobs = _jobs(d)
    actual = sum(float(j.get("cost") or 0) for j in jobs if j.get("state") == "ready")
    committed = sum(float(j.get("estimate_usd") or j.get("cost") or 0) for j in jobs if j.get("state") in {"queued", "submitting", "submitted", "uncertain"})
    failed = sum(1 for j in jobs if j.get("state") == "failed")
    ready = sum(1 for j in jobs if j.get("state") == "ready")
    return {**w, "spending": {"actual": round(actual, 4), "committed": round(committed, 4),
                               "limit": float(w["brief"].get("budget_limit", 0)), "pricing_known": True},
            "jobs": {"ready": ready, "working": sum(1 for j in jobs if j.get("state") in {"queued", "submitting", "submitted"}), "failed": failed}}


def update_brief(d, data):
    w = _load(d)
    b = dict(w["brief"])
    if "story" in data: b["story"] = _clean(data["story"])
    if "style" in data: b["style"] = _clean(data["style"], 120) or "auto"
    if "duration" in data: b["duration"] = _clean(data["duration"], 40)
    if "aspect" in data:
        if data["aspect"] not in ASPECTS: raise SystemExit("That aspect ratio is not supported.")
        b["aspect"] = data["aspect"]
    if "budget_limit" in data:
        n = float(data["budget_limit"])
        if not 0 <= n <= 100000: raise SystemExit("Budget limit must be between $0 and $100,000.")
        b["budget_limit"] = round(n, 2)
    if "checkin_mode" in data:
        if data["checkin_mode"] not in MODES: raise SystemExit("Unknown check-in mode.")
        b["checkin_mode"] = data["checkin_mode"]
        if data["checkin_mode"] in CHECKPOINTS: b["checkpoints"] = CHECKPOINTS[data["checkin_mode"]]
    if "checkpoints" in data:
        known = {x[0] for x in STAGES}
        if not isinstance(data["checkpoints"], list) or any(x not in known for x in data["checkpoints"]): raise SystemExit("Unknown checkpoint.")
        b["checkpoints"] = list(dict.fromkeys(data["checkpoints"]))
    w["brief"] = b
    _activity(w, "brief", "Creative brief updated.")
    return _save(d, w)


def create_plan(d):
    w = _load(d)
    if len(w["brief"].get("story", "")) < 20 and not _plan(d):
        raise SystemExit("Add a story or script before creating the production plan.")
    for i, s in enumerate(w["stages"]): s["state"] = "needs_approval" if i == 0 else "not_started"
    w["current"] = "story"
    _activity(w, "plan", "Production plan prepared. No paid work was submitted.")
    return _save(d, w)


def approve(d, data):
    w = _load(d); sid = _clean(data.get("stage"), 40); s = _stage(w, sid)
    if not s: raise SystemExit("Unknown production stage.")
    if s["state"] not in {"needs_approval", "ready", "failed", "paused"}: raise SystemExit("That stage is not ready for approval.")
    s["state"] = "complete"
    w["approvals"].append({"id": uuid.uuid4().hex, "stage": sid, "at": int(time.time()), "asset_versions": list(data.get("asset_versions") or [])[:200]})
    idx = next(i for i, x in enumerate(w["stages"]) if x["id"] == sid)
    if idx + 1 < len(w["stages"]):
        nxt = w["stages"][idx + 1]; nxt["state"] = "ready"; w["current"] = nxt["id"]
    _activity(w, "approval", f"{s['label']} approved.")
    return _save(d, w)


def request_changes(d, data):
    w = _load(d); sid = _clean(data.get("stage"), 40); note = _clean(data.get("note"), 2000); s = _stage(w, sid)
    if not s or not note: raise SystemExit("Say what should change.")
    affected = list(dict.fromkeys(_clean(x, 80) for x in (data.get("affected") or [])))[:200]
    w["revisions"].append({"id": uuid.uuid4().hex, "stage": sid, "note": note, "affected": affected, "at": int(time.time()), "state": "proposed"})
    s["state"] = "ready"
    _activity(w, "revision", f"Changes requested for {s['label']}. Approved assets were kept.")
    return _save(d, w)


def pause(d, on):
    w = _load(d); w["paused"] = bool(on)
    _activity(w, "paused" if on else "resumed", "Upcoming work paused. Running provider jobs may still finish." if on else "Production resumed.")
    return _save(d, w)


def run(action, d, data):
    if action == "state": return state(d)
    if action == "update_brief": return update_brief(d, data)
    if action == "create_plan": return create_plan(d)
    if action == "approve": return approve(d, data)
    if action == "request_changes": return request_changes(d, data)
    if action == "pause": return pause(d, True)
    if action == "resume": return pause(d, False)
    raise SystemExit("Unknown Agent Studio action.")


def main(argv):
    try:
        ap = argparse.ArgumentParser()
        ap.add_argument("action", choices=["state", "update_brief", "create_plan", "approve", "request_changes", "pause", "resume"])
        ap.add_argument("project")
        ap.add_argument("--data", default="{}")
        a = ap.parse_args(argv)
        print(json.dumps({"event": "result", "data": run(a.action, a.project, json.loads(a.data))}), flush=True)
        return 0
    except SystemExit as e:
        print(json.dumps({"event": "error", "message": str(e)}), flush=True); return 1
    except Exception as e:
        print(json.dumps({"event": "error", "message": str(e)}), flush=True); return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
