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
RUN_FILE = "agent-production-run.json"
STAGES = [
    ("story", "Story & shot plan"),
    ("design", "Characters, sets & world"),
    ("direction", "Cast & visual direction"),
    ("storyboard", "Storyboard & keyframes"),
    ("first_scene", "First scene preview"),
    ("scenes", "Remaining scenes"),
    ("audio", "Voices, score & sound"),
    ("motion", "Titles & motion graphics"),
    ("preview", "Preview cut"),
    ("review", "Continuity & quality review"),
    ("export", "Final review & export"),
]
MODES = {"guided", "balanced", "autopilot", "custom"}
ASPECTS = {"2.39:1", "21:9", "16:9", "4:3", "1:1", "4:5", "3:4", "9:16", "9:21"}
CHECKPOINTS = {
    "guided": [x[0] for x in STAGES],
    "balanced": ["story", "direction", "first_scene", "preview"],
    # Autopilot still asks before money is spent and when an instruction is
    # ambiguous; it does not add routine creative check-ins of its own.
    "autopilot": [],
}
ANALYSIS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["logline", "genre", "tone", "characters", "locations", "props", "scenes", "sound_direction", "score_prompt", "sfx_plan", "motion_graphics", "visual_style", "visual_style_reason", "director_style_id", "director_style_reason", "questions"], "properties": {
    "logline": {"type": "string"}, "genre": {"type": "string"}, "tone": {"type": "string"},
    "characters": {"type": "array", "maxItems": 40, "items": {"type": "object", "additionalProperties": False, "required": ["name", "role", "appearance", "wardrobe", "voice"], "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "appearance": {"type": "string"}, "wardrobe": {"type": "string"}, "voice": {"type": "string"}}}},
    "locations": {"type": "array", "maxItems": 40, "items": {"type": "object", "additionalProperties": False, "required": ["name", "design", "lighting"], "properties": {"name": {"type": "string"}, "design": {"type": "string"}, "lighting": {"type": "string"}}}},
    "props": {"type": "array", "maxItems": 40, "items": {"type": "object", "additionalProperties": False, "required": ["name", "design", "continuity"], "properties": {"name": {"type": "string"}, "design": {"type": "string"}, "continuity": {"type": "string"}}}},
    "scenes": {"type": "array", "maxItems": 100, "items": {"type": "object", "additionalProperties": False, "required": ["heading", "summary"], "properties": {"heading": {"type": "string"}, "summary": {"type": "string"}}}},
    "sound_direction": {"type": "string"}, "score_prompt": {"type": "string"},
    "sfx_plan": {"type": "array", "maxItems": 40, "items": {"type": "object", "additionalProperties": False, "required": ["scene", "sound", "purpose"], "properties": {"scene": {"type": "string"}, "sound": {"type": "string"}, "purpose": {"type": "string"}}}},
    "motion_graphics": {"type": "array", "maxItems": 20, "items": {"type": "object", "additionalProperties": False, "required": ["type", "text", "when"], "properties": {"type": {"type": "string"}, "text": {"type": "string"}, "when": {"type": "string"}}}},
    "visual_style": {"type": "string", "enum": ["cinematic", "photoreal", "stylized-3d", "2d-animation", "storybook", "documentary", "commercial", "experimental"]},
    "visual_style_reason": {"type": "string"}, "director_style_id": {"type": "string"}, "director_style_reason": {"type": "string"},
    "questions": {"type": "array", "maxItems": 6, "items": {"type": "string"}}
}}


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
            "image_provider": "auto", "image_model": "auto", "video_provider": "auto", "video_model": "auto",
            "voice_provider": "elevenlabs", "voice_model": "auto", "music_provider": "auto", "sfx_provider": "auto",
        },
        "current": "story",
        "stages": [{"id": sid, "label": label, "state": "not_started"} for sid, label in STAGES],
        "approvals": [],
        "revisions": [],
        "analysis": None,
        "activity": [{"id": uuid.uuid4().hex, "at": int(time.time()), "kind": "created", "text": "Agent Studio opened for this project."}],
        "existing": {"scenes": len(plan.get("scenes", [])), "shots": len(shots)},
    }


def _path(d):
    return os.path.join(d, FILE)


def _load(d):
    value = _read(_path(d))
    if not isinstance(value, dict):
        return _base(d)
    # Keep older projects usable as the production pipeline grows.
    old = {s.get("id"): s for s in value.get("stages", []) if isinstance(s, dict)}
    value["stages"] = [{"id": sid, "label": label,
                        "state": old.get(sid, {}).get("state", "not_started")}
                       for sid, label in STAGES]
    value.setdefault("revisions", [])
    value.setdefault("approvals", [])
    value.setdefault("activity", [])
    if not _stage(value, value.get("current")):
        value["current"] = next((s["id"] for s in value["stages"] if s["state"] != "complete"), "export")
    return value


def _activity(w, kind, text):
    w.setdefault("activity", []).append({"id": uuid.uuid4().hex, "at": int(time.time()), "kind": kind, "text": _clean(text, 500)})
    w["activity"] = w["activity"][-100:]


def _save(d, w):
    w["updated"] = int(time.time())
    _write(_path(d), w)
    return state(d, w)


def _stage(w, sid):
    return next((s for s in w["stages"] if s["id"] == sid), None)


def _stage_index(sid):
    return next((i for i, (stage, _) in enumerate(STAGES) if stage == sid), 0)


def _inbox(d, w, jobs=None):
    jobs = jobs if jobs is not None else _jobs(d)
    items = []
    for s in w.get("stages", []):
        if s.get("state") == "needs_approval":
            items.append({"id": f"approval:{s['id']}", "kind": "approval", "stage": s["id"],
                          "title": s["label"], "detail": "Creative approval required before production continues.",
                          "priority": 1, "action": "review"})
    for job in jobs:
        if job.get("state") == "failed":
            jid = _clean(job.get("id") or job.get("job_id") or "job", 80)
            items.append({"id": f"job:{jid}", "kind": "failure", "stage": "", "title": "Generation needs attention",
                          "detail": _clean(job.get("error") or job.get("message") or jid, 240),
                          "priority": 0, "action": "manual"})
        elif job.get("state") == "uncertain":
            jid = _clean(job.get("id") or job.get("job_id") or "job", 80)
            items.append({"id": f"job:{jid}", "kind": "uncertain", "stage": "", "title": "Provider result is uncertain",
                          "detail": "Check the provider before retrying so the same work is not purchased twice.",
                          "priority": 0, "action": "manual"})
    for rev in w.get("revisions", []):
        if rev.get("state") == "proposed":
            items.append({"id": f"revision:{rev.get('id')}", "kind": "revision", "stage": rev.get("stage", ""),
                          "title": "Revision ready to review", "detail": _clean(rev.get("note"), 240),
                          "priority": 2, "action": "review"})
    return sorted(items, key=lambda x: (x["priority"], _stage_index(x.get("stage"))))[:100]


def _impact(d, w, data):
    sid = _clean(data.get("stage") or w.get("current"), 40)
    note = _clean(data.get("note"), 2000)
    if not _stage(w, sid) or not note:
        raise SystemExit("Say what should change.")
    manifest = _read(os.path.join(d, "agent-production.json"), {}) or {}
    creative = manifest.get("creative", {}) if isinstance(manifest, dict) else {}
    names = [str(x.get("name", "")) for x in creative.get("characters", []) if isinstance(x, dict)]
    places = [str(x.get("name", "")) for x in creative.get("locations", []) if isinstance(x, dict)]
    low = note.casefold()
    matched_names = [x for x in names if x and x.casefold() in low]
    matched_places = [x for x in places if x and x.casefold() in low]
    matched = matched_names + matched_places
    global_words = ("all shots", "every shot", "whole film", "entire film", "throughout")
    global_change = any(x in low for x in global_words)
    shots, scenes = [], []
    plan = _plan(d)
    explicit_ids = set()
    for scene in plan.get("scenes", []):
        heading_blob = json.dumps({"heading": scene.get("heading"), "notes": scene.get("notes")}, ensure_ascii=False).casefold()
        scene_hit = global_change or any(x.casefold() in heading_blob for x in matched_places)
        for shot in scene.get("shots", []):
            shot_id = _clean(shot.get("id"), 80)
            if shot_id and shot_id.casefold() in low:
                explicit_ids.add(shot_id)
            blob = json.dumps(shot, ensure_ascii=False).casefold()
            if shot_id and (scene_hit or shot_id in explicit_ids or any(x.casefold() in blob for x in matched_names)):
                shots.append(shot_id)
                number = scene.get("number")
                if number not in scenes: scenes.append(number)
    shots = list(dict.fromkeys(shots))[:200]
    downstream = [x[0] for x in STAGES[_stage_index(sid) + 1:]]
    approved = {asset for a in w.get("approvals", []) for asset in a.get("asset_versions", [])}
    ambiguous = not global_change and not matched and not explicit_ids
    return {"stage": sid, "note": note, "affected_shots": shots, "affected_scenes": scenes[:100],
            "matched_entities": matched[:40], "downstream_stages": downstream,
            "preserved_approved_assets": len(approved - set(shots)),
            "regeneration_count": len(shots), "scope": "project" if global_change else ("targeted" if shots else "stage"),
            "needs_clarification": ambiguous,
            "warning": ("No exact shot, character or location was identified. The request will be recorded, but no generation should run until its scope is chosen."
                        if ambiguous else "Only matched work is marked for revision; unrelated approved assets stay locked.")}


def _orchestration(d, w, jobs=None):
    jobs = jobs if jobs is not None else _jobs(d)
    evidence = {
        "story": bool(_plan(d) or len(w.get("brief", {}).get("story", "")) >= 20),
        "design": os.path.exists(os.path.join(d, "agent-production.json")),
        "storyboard": bool(_read(os.path.join(d, "keyframes.json"), {})),
        "motion": bool((_read(os.path.join(d, "overlays.json"), {}) or {}).get("overlays")),
        "export": bool([x for x in os.listdir(d) if x.lower().endswith(".mp4")]) if os.path.isdir(d) else False,
    }
    active = sum(1 for j in jobs if j.get("state") in {"queued", "submitting", "submitted", "uncertain"})
    failed = sum(1 for j in jobs if j.get("state") == "failed")
    current = _stage(w, w.get("current")) or w["stages"][0]
    blockers = []
    if w.get("paused"): blockers.append("Production is paused")
    if failed: blockers.append(f"{failed} failed generation job{'s' if failed != 1 else ''}")
    if current.get("state") == "needs_approval": blockers.append(f"Approve {current['label']}")
    status = "paused" if w.get("paused") else "waiting" if blockers else "running" if active else "ready"
    if blockers: next_action = blockers[0]
    elif active: next_action = "Wait for running generation jobs"
    else: next_action = f"Continue {current['label']}"
    return {"status": status, "next_action": next_action, "blockers": blockers, "active_jobs": active,
            "evidence": evidence, "safe_to_continue": not blockers and not active,
            "message": "Project state reconciled from durable files. No provider work was submitted."}


def _first_scene_proof(d):
    """Describe the smallest useful production batch. Free: estimates and reads only."""
    plan = _plan(d)
    scene = next((x for x in plan.get("scenes", []) if x.get("shots")), None)
    if not scene:
        return {"state": "blocked", "scene": None, "shots": [], "blockers": ["Create a shot plan first"],
                "can_start_local": False, "requires_cost_review": False}
    ids = [_clean(x.get("id"), 80) for x in scene.get("shots", []) if x.get("id")][:40]
    from .golden import status as golden_status
    from .routing import batch_usd, pick
    project = _project(d)
    image, video = pick(project, "image"), pick(project, "video")
    try:
        golden = golden_status(d).get("shots", [])
    except (KeyError, TypeError, ValueError):
        golden = [{"id": x, "keyframe": False, "take": "none", "described": True} for x in ids]
    by_id = {x["id"]: x for x in golden}
    missing_keyframes = [x for x in ids if not by_id.get(x, {}).get("keyframe") and by_id.get(x, {}).get("described")]
    missing_video = [x for x in ids if by_id.get(x, {}).get("take") == "none"]
    active = [j for j in _jobs(d) if j.get("shot_id") in ids and j.get("state") in {"queued", "submitting", "submitted", "uncertain"}]
    failed = [j for j in _jobs(d) if j.get("shot_id") in ids and j.get("state") == "failed"]
    complete = bool(ids) and not missing_video
    blockers = []
    if not image.get("provider") and missing_keyframes: blockers.append(image.get("reason") or "Choose an image model")
    if not video.get("provider") and missing_video: blockers.append(video.get("reason") or "Choose a video model")
    image_cost = batch_usd(d, missing_keyframes, image.get("provider"), image.get("model"), "image") if image.get("provider") and missing_keyframes else 0.0
    video_cost = batch_usd(d, missing_video, video.get("provider"), video.get("model"), "video") if video.get("provider") and missing_video else 0.0
    cloud = (bool(missing_keyframes) and image.get("provider") != "comfyui") or (bool(missing_video) and video.get("provider") != "comfyui")
    run = _read(os.path.join(d, RUN_FILE), {}) or {}
    state_name = "complete" if complete else "failed" if failed and not active else "working" if active else "blocked" if blockers else "ready"
    return {"state": state_name, "scene": scene.get("number"), "heading": scene.get("heading", "First scene"), "shots": ids,
            "missing_keyframes": missing_keyframes, "missing_video": missing_video, "active_jobs": len(active), "failed_jobs": len(failed),
            "image_route": image, "video_route": video, "estimated_usd": round(image_cost + video_cost, 2),
            "requires_cost_review": cloud, "can_start_local": not cloud and not blockers and not complete and not active,
            "blockers": blockers, "run": run, "message": ("The first scene is ready for approval." if complete else
            "Review the live cost in Manual Studio before cloud work starts." if cloud else
            "This proof scene can run locally without provider charges." if not blockers else blockers[0])}


def start_first_scene(d):
    """Queue only a free/local proof scene. Cloud batches always use the shell's spend-token path."""
    proof = _first_scene_proof(d)
    if proof.get("requires_cost_review"):
        raise SystemExit("This proof scene uses cloud models. Open Manual Studio to review the live price and confirm the batch.")
    if not proof.get("can_start_local"):
        raise SystemExit(proof.get("message") or "The first scene is not ready to start.")
    from .render import enqueue
    if proof["missing_keyframes"]:
        route = proof["image_route"]
        made = enqueue(d, proof["missing_keyframes"], route["provider"], route["model"], {}, [], kind="image")
        step = "keyframes"
    else:
        route = proof["video_route"]
        made = enqueue(d, proof["missing_video"], route["provider"], route["model"], {}, [], kind="video")
        step = "video"
    run = {"schema": 1, "scene": proof["scene"], "shots": proof["shots"], "step": step,
           "state": "working", "queued": len(made), "started": int(time.time()), "updated": int(time.time())}
    _write(os.path.join(d, RUN_FILE), run)
    return proof


def _advance_first_scene(d, w):
    """Continue a local proof after its current queue drains; safe to call repeatedly."""
    run = _read(os.path.join(d, RUN_FILE), {}) or {}
    if run.get("state") != "working" or not run.get("shots"):
        return False
    proof = _first_scene_proof(d)
    if proof.get("active_jobs"):
        return False
    if proof.get("failed_jobs"):
        run.update(state="failed", updated=int(time.time())); _write(os.path.join(d, RUN_FILE), run); return True
    if proof.get("missing_keyframes"):
        from .library import approve_keyframes, pending_keyframes
        if pending_keyframes(d, proof["shots"]):
            approve_keyframes(d, proof["shots"])
            proof = _first_scene_proof(d)
        if proof.get("missing_keyframes"):
            return False
    if proof.get("missing_video"):
        from .render import enqueue
        route = proof["video_route"]
        if route.get("provider") != "comfyui": return False
        made = enqueue(d, proof["missing_video"], "comfyui", route["model"], {}, [], kind="video")
        run.update(step="video", queued=len(made), updated=int(time.time())); _write(os.path.join(d, RUN_FILE), run); return True
    run.update(state="complete", updated=int(time.time())); _write(os.path.join(d, RUN_FILE), run)
    stage = _stage(w, "first_scene")
    if stage and stage["state"] != "complete": stage["state"] = "needs_approval"; w["current"] = "first_scene"
    _activity(w, "first_scene_ready", "The first scene proof is ready for review. No remaining scenes were generated.")
    return True


def state(d, w=None):
    w = w or _load(d)
    jobs = _jobs(d)
    actual = sum(float(j.get("cost") or 0) for j in jobs if j.get("state") == "ready")
    committed = sum(float(j.get("estimate_usd") or j.get("cost") or 0) for j in jobs if j.get("state") in {"queued", "submitting", "submitted", "uncertain"})
    failed = sum(1 for j in jobs if j.get("state") == "failed")
    ready = sum(1 for j in jobs if j.get("state") == "ready")
    return {**w, "spending": {"actual": round(actual, 4), "committed": round(committed, 4),
                               "limit": float(w["brief"].get("budget_limit", 0)), "pricing_known": True},
            "jobs": {"ready": ready, "working": sum(1 for j in jobs if j.get("state") in {"queued", "submitting", "submitted"}), "failed": failed},
            "inbox": _inbox(d, w, jobs), "orchestration": _orchestration(d, w, jobs),
            "first_scene_proof": _first_scene_proof(d)}


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
    for key in ("image_provider", "image_model", "video_provider", "video_model", "voice_provider", "voice_model", "music_provider", "sfx_provider"):
        if key in data: b[key] = _clean(data[key], 160) or "auto"
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


def analyze(d):
    w = _load(d); story = w.get("brief", {}).get("story", "")
    if len(story.strip()) < 20: raise SystemExit("Add a story or script before asking the agent to analyse it.")
    from . import llm
    from .director import resolve_model
    from .filmmakers import LIBRARY
    c = llm.client(); model = llm.local_model(c) or resolve_model(c, "gpt-5")
    choices = [{"id": x["id"], "name": x["name"], "known_for": x.get("known_for", "")} for x in LIBRARY]
    prompt = "Analyse this script as a full film production team. Suggestions are optional and must preserve the writer's story. Design production-ready characters (appearance, wardrobe and voice direction), locations/sets, continuity props, a sound direction, one provider-neutral score prompt, an SFX/ambience plan, and useful title/motion-graphics moments. Pick a visual_style enum and optionally one director_style_id from the supplied library; use an empty id if none genuinely fits. Do not rewrite the script or invent plot events.\n\nDIRECTOR LIBRARY:\n" + json.dumps(choices, ensure_ascii=False) + "\n\nSCRIPT:\n" + story[:60000]
    r = c.responses.create(model=model, input=[{"role": "system", "content": "You are FilmCrafter's careful development producer. Separate facts from suggestions."}, {"role": "user", "content": prompt}], text={"format": {"type": "json_schema", "name": "script_analysis", "schema": ANALYSIS_SCHEMA, "strict": True}})
    out = json.loads(r.output_text)
    valid = {x["id"] for x in LIBRARY}
    if out.get("director_style_id") not in valid: out["director_style_id"] = ""
    w["analysis"] = {**out, "status": "proposed", "model": model, "at": int(time.time())}
    _activity(w, "analysis", "The AI analysed the script and prepared optional suggestions. Nothing was changed.")
    return _save(d, w)


def accept_analysis(d, data):
    w = _load(d); a = w.get("analysis")
    if not isinstance(a, dict): raise SystemExit("Analyse the script first.")
    style = _clean(data.get("style") or a.get("visual_style"), 120)
    if style: w["brief"]["style"] = style
    a["status"] = "accepted"; a["accepted"] = int(time.time()); a["director_style_id"] = _clean(data.get("director_style_id", a.get("director_style_id", "")), 100)
    manifest = {"schema": 1, "created": int(time.time()), "source": "approved-script-analysis", "story_unchanged": True,
                "models": {k: w["brief"].get(k, "auto") for k in ("image_provider", "image_model", "video_provider", "video_model", "voice_provider", "voice_model", "music_provider", "sfx_provider")},
                "creative": {k: a.get(k) for k in ("logline", "genre", "tone", "characters", "locations", "props", "scenes", "sound_direction", "score_prompt", "sfx_plan", "motion_graphics", "visual_style", "director_style_id")}}
    _write(os.path.join(d, "agent-production.json"), manifest)
    _activity(w, "analysis_accepted", "Script analysis accepted. The original story remains the source of truth.")
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
    preview = _impact(d, w, data)
    supplied = data.get("affected")
    affected = (list(dict.fromkeys(_clean(x, 80) for x in supplied))[:200]
                if isinstance(supplied, list) and supplied else preview["affected_shots"])
    w["revisions"].append({"id": uuid.uuid4().hex, "stage": sid, "note": note, "affected": affected,
                           "impact": {**preview, "affected_shots": affected}, "at": int(time.time()), "state": "proposed"})
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
    if action == "analyze": return analyze(d)
    if action == "accept_analysis": return accept_analysis(d, data)
    if action == "approve": return approve(d, data)
    if action == "request_changes": return request_changes(d, data)
    if action == "impact": return _impact(d, _load(d), data)
    if action == "inbox": return _inbox(d, _load(d))
    if action == "orchestrate":
        w = _load(d); _advance_first_scene(d, w); result = _orchestration(d, w)
        _activity(w, "orchestrated", result["message"])
        saved = _save(d, w); saved["orchestration"] = result
        return saved
    if action == "plan_first_scene": return _first_scene_proof(d)
    if action == "start_first_scene":
        start_first_scene(d)
        w = _load(d); _activity(w, "first_scene_started", "Local first-scene proof started. Remaining scenes were left untouched.")
        return _save(d, w)
    if action == "pause": return pause(d, True)
    if action == "resume": return pause(d, False)
    raise SystemExit("Unknown Agent Studio action.")


def main(argv):
    try:
        ap = argparse.ArgumentParser()
        ap.add_argument("action", choices=["state", "update_brief", "analyze", "accept_analysis", "create_plan", "approve", "request_changes", "impact", "inbox", "orchestrate", "plan_first_scene", "start_first_scene", "pause", "resume"])
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
