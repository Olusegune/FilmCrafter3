"""Optional filmmaker craft traits for directing prompts.

Names are for selection and attribution in the UI. Only the bounded traits are
read by render.py, so a provider never receives a living filmmaker's name.
"""
from __future__ import annotations
import argparse, json, os, sys, time
from .filmmakers import LIBRARY

FIELDS = ("summary", "camera", "light", "editing", "movement", "design", "acting", "avoid")


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return default


def _write(path, value):
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(value, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _traits(x):
    # Library traits contain no filmmaker name; keep fields and lengths bounded anyway.
    return {k: str(x.get(k) or "").replace("`", "")[:700] for k in FIELDS if x.get(k)}


def list_styles(d):
    p = _read(os.path.join(d, "project.json"), {}) or {}
    current = (p.get("director_style") or {}).get("id")
    styles = [{"id": x["id"], "name": x["name"], "region": x["region"], "origin": x["origin"],
               "known_for": x.get("known_for", ""), "palette": x.get("palette", []), "traits": _traits(x)} for x in LIBRARY]
    return {"styles": styles, "current": current}


def set_style(d, sid):
    x = next((x for x in LIBRARY if x["id"] == sid), None)
    if not x: raise SystemExit("That director style is not in the library.")
    path = os.path.join(d, "project.json"); p = _read(path, {}) or {}
    p["director_style"] = {"id": x["id"], "name": x["name"], "region": x["region"], "traits": _traits(x), "selected": int(time.time())}
    _write(path, p)
    return {"id": x["id"], "name": x["name"], "traits": _traits(x)}


def clear(d):
    path = os.path.join(d, "project.json"); p = _read(path, {}) or {}
    p.pop("director_style", None); _write(path, p)
    return {"cleared": True}


def main(argv):
    try:
        ap = argparse.ArgumentParser(); ap.add_argument("action", choices=["list", "set", "clear"]); ap.add_argument("project"); ap.add_argument("--data", default="{}")
        a = ap.parse_args(argv); action, d, data = a.action, a.project, json.loads(a.data)
        out = list_styles(d) if action == "list" else set_style(d, str(data.get("id") or "")) if action == "set" else clear(d)
        print(json.dumps({"event": "result", "data": out}), flush=True); return 0
    except SystemExit as e:
        print(json.dumps({"event": "error", "message": str(e)}), flush=True); return 1


if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
