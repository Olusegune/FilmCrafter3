"""Rendering: model capability manifests, Shot Contract -> provider request, persistent jobs.

Providers are adapters behind one internal request (PRD §15). Every model is described by a
manifest built from the provider's own published schema (fal OpenAPI / Kie OpenAPI), so Director
Mode can expose *every* input of any model without hand-written UI.

Jobs live in <project>/jobs.json and are written *before* any billable call (PRD §29):
  queued -> submitting -> submitted -> ready | failed
A job found in `submitting` after a crash is marked `uncertain` and never re-submitted
automatically; the user decides. Keys arrive via env (FAL_KEY, KIE_KEY) from the OS keychain.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
from .safe import sha1 as _sha1
import json
import math
import mimetypes
import os
import re
import sys
import time
import uuid

import requests

UA = {"User-Agent": "FilmCrafter/0.1"}
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".filmcrafter", "manifests")
ACTIVE = ("queued", "submitting", "submitted")

# Auto routing (Simple Mode): reference-to-video models keep characters consistent.
AUTO = {
    "fal": "bytedance/seedance-2.0/reference-to-video",
    "kie": "bytedance/seedance-2",
    "google": "veo-3.1-fast-generate-preview",
}
# Lip-sync pass: re-sync a finished take's mouth to the isolated vocal under the shot.
AUTO_LIPSYNC = {"fal": "fal-ai/sync-lipsync/v3", "kie": "volcengine/video-to-video-lip-sync"}
# Keyframes: a still for each shot, made with reference images, then animated (better consistency, cheaper retries).
AUTO_IMAGE = {
    "fal": "fal-ai/nano-banana/edit",
    "kie": "google/nano-banana-edit",
    "google": "gemini-nano-banana-2.1",
    "openai": "gpt-image-2.5-flare",
    "byteplus": "dola-seedream-5-0-pro-260628",
}


def _fal_headers() -> dict:
    """Authenticated catalog/schema reads get far higher rate limits than anonymous ones."""
    key = os.environ.get("FAL_KEY")
    return {**UA, **({"Authorization": f"Key {key}"} if key else {})}


def http_get(url: str, *, params=None, headers=None, timeout: int = 30, attempts: int = 4) -> requests.Response:
    """GET for metadata and status only (never for billable submits): retries rate limits and
    transient server errors with backoff, honouring Retry-After."""
    last = None
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, headers=headers or UA, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
            time.sleep(min(8, 1.5 * (2 ** i)))
            continue
        if r.status_code in (429, 500, 502, 503, 504) and i < attempts - 1:
            wait = r.headers.get("Retry-After")
            time.sleep(min(20, float(wait)) if wait and wait.replace(".", "", 1).isdigit() else min(8, 1.5 * (2 ** i)))
            continue
        return r
    if last:
        raise last
    return r


def emit(**kw) -> None:
    try:
        print(json.dumps(kw, ensure_ascii=False), flush=True)
    except (OSError, ValueError):
        # The app that started this renderer has gone (closed or updated), so nobody can hear us. Stop quietly:
        # nothing is marked failed, and in-flight renders are picked up again the next time the app starts.
        os._exit(0)


# ---------------------------------------------------------------- manifests

ROLE_NAMES = {
    "prompt": ["prompt"],
    "negative_prompt": ["negative_prompt"],
    "ref_images": ["image_urls", "reference_image_urls", "reference_images", "reference_image", "ref_image_urls",
                   "input_image_urls", "input_urls", "image_input"],
    "ref_videos": ["video_urls", "reference_video_urls", "reference_videos"],
    "ref_audio": ["audio_urls", "reference_audio_urls"],
    "first_frame": ["image_url", "first_frame_url", "start_image_url", "first_image_url", "first_frame_image", "input_image"],
    "last_frame": ["end_image_url", "last_frame_url", "tail_image_url", "last_frame_image"],
    "duration": ["duration", "duration_seconds", "seconds"],
    "aspect_ratio": ["aspect_ratio"],
    "resolution": ["resolution"],
    "audio": ["generate_audio", "with_audio", "enable_audio", "sound"],
    "seed": ["seed"],
    # lip-sync passes: the take to re-sync and the vocal that drives it
    "src_video": ["video_url", "input_video", "video"],
    "src_audio": ["audio_url", "input_audio", "audio"],
}


def _resolve(spec: dict, node: dict) -> dict:
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"].split("/")[-1]
        node = spec["components"]["schemas"][ref]
    if isinstance(node, dict) and "allOf" in node and len(node["allOf"]) == 1:
        return _resolve(spec, node["allOf"][0])
    return node


def _field(spec: dict, name: str, raw: dict, required: set) -> dict:
    raw = _resolve(spec, raw)
    types = [raw.get("type")] if raw.get("type") else [_resolve(spec, x).get("type") for x in raw.get("anyOf", [])]
    types = [t for t in types if t and t != "null"]
    item = _resolve(spec, raw.get("items", {})) if raw.get("items") else {}
    enum = raw.get("enum") or next((x.get("enum") for x in raw.get("anyOf", []) if isinstance(x, dict) and x.get("enum")), None)
    return {"name": name, "type": types[0] if types else "string", "items": item.get("type"),
            "enum": enum, "default": raw.get("default"), "minimum": raw.get("minimum"), "maximum": raw.get("maximum"),
            "max_items": raw.get("maxItems"), "max_length": raw.get("maxLength"),
            "description": (raw.get("description") or "").strip(),
            "required": name in required}


LEARNED_LIMITS = os.path.join(CACHE_DIR, "learned_limits.json")
ONE_IMAGE = re.compile(r"^\s*(?:the\s+)?(?:url|link)s?\s+of\s+(?:the|an?|one)\s+image\b|^\s*(?:upload|provide)\s+an?\s+image\b", re.I)


def learned_limit(provider: str, model: str, field: str) -> int | None:
    return ((_read(LEARNED_LIMITS, {}) or {}).get(f"{provider}:{model}") or {}).get(field)


def learn_limit(provider: str, model: str, field: str, n: int) -> None:
    """A provider said how many items a field takes (\"image_urls supports at most 1 files\"): remember it so the next request is right."""
    data = _read(LEARNED_LIMITS, {}) or {}
    data.setdefault(f"{provider}:{model}", {})[field] = int(n)
    os.makedirs(CACHE_DIR, exist_ok=True)
    _write(LEARNED_LIMITS, data)


def _tidy_field(f: dict) -> dict:
    """A model's own documentation is sometimes sloppy: a field named "image_urls " with a trailing space (the provider then never sees it),
    or a limit written only in the description ("Maximum length: 5000 characters", "Minimum: 6, Maximum: 30"). Read what is meant."""
    f = dict(f)
    f["name"] = str(f["name"]).strip()
    d = f.get("description") or ""
    if not f.get("max_length") and f.get("type") == "string":
        m = re.search(r"(?:maximum length|max(?:imum)?)[:\s]+([\d,]{3,6})\s*(?:non[-\u2011 ]?chinese\s+)?(?:characters|chars)", d, re.I)
        if m:
            f["max_length"] = int(m.group(1).replace(",", ""))
    if f.get("type") == "array" and not f.get("max_items") and f["name"] in ROLE_NAMES["ref_images"]:
        up_to = re.search(r"(?:up to|at most|maximum(?: of)?|max\.?)\s+(\d+)\s+(?:images|files|pictures)", d, re.I)
        if ONE_IMAGE.search(d):
            f["max_items"] = 1            # "URL of the image to be used for the video": one picture, though the field is a list
        elif up_to:
            f["max_items"] = int(up_to.group(1))
    if f.get("minimum") is None and f.get("maximum") is None and f["name"] in ROLE_NAMES["duration"]:
        m = re.search(r"Minimum:\s*(\d+)\D{1,12}Maximum:\s*(\d+)", d)
        if m:
            f["minimum"], f["maximum"] = int(m.group(1)), int(m.group(2))
    return f


def _finish(provider: str, model: str, title: str, category: str, fields: list[dict]) -> dict:
    fields = [_tidy_field(f) for f in fields]
    for f in fields:
        n = learned_limit(provider, model, f["name"])
        if n:
            f["max_items"] = min(n, f["max_items"]) if f.get("max_items") else n
    roles = {}
    names = {f["name"].strip(): f["name"] for f in fields}
    for role, cands in ROLE_NAMES.items():
        hit = next((names[c] for c in cands if c in names), None)
        if hit:
            roles[role] = hit
    types = {f["name"]: f.get("type") for f in fields}
    for r in ("src_video", "src_audio", "ref_audio", "first_frame", "last_frame"):
        if r in roles and types.get(roles[r]) not in ("string", "array"):
            roles.pop(r)
    if "first_frame" in roles and roles["first_frame"] == roles.get("ref_images"):
        roles.pop("first_frame")
    text = " ".join(f["description"] for f in fields)
    syntax = "@Image{n}" if "@Image" in text else "[Image {n}]" if "[Image" in text else None
    man = {"schema_version": 1, "provider": provider, "model": model, "title": title, "category": category,
           "inputs": fields, "roles": roles, "ref_syntax": syntax, "fetched": int(time.time()),
           "caps": capabilities(fields, roles)}
    if frame_list_size(man):          # its picture list is first + last frame: it does take an end frame, through that list
        man["caps"] = {**man["caps"], "first_frame": True, "last_frame": True, "image_refs": 0}
        man["frame_list"] = 2
    return man


def capabilities(fields: list[dict], roles: dict) -> dict:
    """What a model can take, derived from its schema: reference counts, frame control, durations, aspects."""
    f = {x["name"]: x for x in fields}

    def count(role):
        if role not in roles:
            return 0
        x = f[roles[role]]
        return (x.get("max_items") or 4) if x.get("type") == "array" else 1
    dur = f.get(roles.get("duration", ""), {})
    return {"image_refs": count("ref_images"), "video_refs": count("ref_videos"), "audio_refs": count("ref_audio"),
            "first_frame": "first_frame" in roles, "last_frame": "last_frame" in roles,
            "kind": "video" if "duration" in roles else "lipsync" if "src_video" in roles else "image",
            "durations": [str(x) for x in dur.get("enum") or []] or None,
            "duration_range": [dur.get("minimum"), dur.get("maximum")] if dur.get("minimum") is not None else None,
            "aspect_ratios": f.get(roles.get("aspect_ratio", ""), {}).get("enum"),
            "resolutions": f.get(roles.get("resolution", ""), {}).get("enum"),
            "native_audio": "audio" in roles, "seed": "seed" in roles, "negative_prompt": "negative_prompt" in roles}


def ref_limits(man: dict, keyframe: bool) -> dict:
    caps = man.get("caps") or capabilities(man["inputs"], man["roles"])
    if caps["image_refs"]:
        img = caps["image_refs"] - (1 if keyframe and not caps["first_frame"] else 0)
    else:  # no reference field: the first reference becomes the start frame unless a keyframe already is
        img = 1 if caps["first_frame"] and not keyframe else 0
    return {"image": max(0, img), "video": caps["video_refs"], "audio": caps["audio_refs"]}


def fal_manifest(model: str) -> dict:
    r = http_get("https://api.fal.ai/v1/models", params={"endpoint_id": model, "expand": "openapi-3.0"},
                 headers=_fal_headers())
    r.raise_for_status()
    items = r.json().get("models") or []
    m = next((x for x in items if x.get("endpoint_id") == model), None)
    if not m or not m.get("openapi"):
        raise SystemExit(f"fal model not found: {model}")
    spec = m["openapi"]
    post = next(v["post"] for p, v in spec["paths"].items() if "post" in v and "{request_id}" not in p)
    schema = _resolve(spec, post["requestBody"]["content"]["application/json"]["schema"])
    req = set(schema.get("required", []))
    fields = [_field(spec, k, v, req) for k, v in schema.get("properties", {}).items()]
    meta = m.get("metadata", {})
    return _finish("fal", model, meta.get("display_name", model), meta.get("category", ""), fields)


def _kie_index() -> list[dict]:
    t = http_get("https://docs.kie.ai/llms.txt").text
    out = []
    for line in t.splitlines():
        m = re.match(r"- (Video|Image)\s+Models > ([^\[]+)\[([^\]]+)\]\((https://docs\.kie\.ai/market/[^)]+\.md)\)", line)
        if m and "/cn/" not in m.group(4):
            out.append({"kind": m.group(1).lower(), "family": m.group(2).strip(), "title": m.group(3).strip(), "doc": m.group(4)})
    return out


def yaml_blocks(md: str) -> list[str]:
    """The ```yaml blocks of a Kie doc page. A block ends at a fence that starts a line: a model's description can hold its own code fences, indented inside the YAML text (Kling 3.0's
    does), and stopping at the first ``` anywhere cut the spec short so the model looked unreadable."""
    return re.findall(r"^```ya?ml[ \t]*\r?\n(.*?)^```", md, re.S | re.M)


def kie_manifest(model: str, doc: str | None = None) -> dict:
    import yaml
    if not doc:
        direct = f"https://docs.kie.ai/market/{model}.md"
        if requests.head(direct, headers=UA, timeout=20, allow_redirects=True).status_code == 200:
            doc = direct
        else:
            doc = next((e["doc"] for e in _kie_index() if _slug_from_doc(e["doc"]) == model
                        or model.replace("/", "-") in e["doc"]), None)
        if not doc:
            raise SystemExit(f"Kie model not found: {model}")
    md = http_get(doc).text
    blocks = yaml_blocks(md)
    body = None
    for blk in blocks:
        try:
            spec = yaml.safe_load(blk)
        except yaml.YAMLError:
            continue
        for path, ops in (spec.get("paths") or {}).items():
            op = (ops or {}).get("post") or {}
            sch = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema")
            if sch and "input" in (_resolve(spec, sch).get("properties") or {}):
                body = _resolve(spec, sch)
                break
        if body:
            break
    if not body:
        raise SystemExit(f"Kie hasn't published a readable input schema for {model} yet.")
    model_id = (_resolve(spec, body["properties"].get("model") or {}).get("enum") or [model])[0]
    inp = _resolve(spec, body["properties"]["input"])
    req = set(inp.get("required", []))
    fields = [_field(spec, k, v, req) for k, v in inp.get("properties", {}).items()]
    title = md.splitlines()[0].lstrip("# ").strip()
    return _finish("kie", model_id, title, "", fields)


def _g(name, typ, desc, enum=None, default=None, items=None, max_items=None, required=False):
    return {"name": name, "type": typ, "items": items, "enum": enum, "default": default, "minimum": None, "maximum": None,
            "max_items": max_items, "max_length": None, "description": desc, "required": required}


MJ_MODELS = {"midjourney/mj-v7": "Midjourney v7"}
MJ_ASPECTS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9", "2:1", "1:2", "5:4", "4:5", "7:4", "4:7"]


def midjourney_manifest(model: str) -> dict:
    """Midjourney through Kie.ai's Midjourney endpoint (not the Market catalog: it has its own address and task types). Taken from Kie's published request and not yet proven with a real
    render here, so it shows as untested. Midjourney itself has no public API; this is a paid third-party route, and a picture you make in Midjourney and drop on a shot works everywhere."""
    return _finish("kie", model, MJ_MODELS.get(model, "Midjourney") + " (via Kie.ai)", "text-to-image", [
        _g("prompt", "string", "What the picture shows.", required=True),
        _g("image_urls", "array", "Pictures Midjourney should take its look from (image prompts).", items="string", max_items=5),
        _g("aspect_ratio", "string", "Shape of the picture.", enum=MJ_ASPECTS, default="16:9"),
        _g("speed", "string", "relaxed is cheapest and slowest; turbo is fastest and dearest.", enum=["relaxed", "fast", "turbo"], default="fast"),
        _g("version", "string", "Midjourney version.", enum=["7", "6.1", "6", "5.2", "niji6"], default="7"),
        _g("stylization", "integer", "How strongly Midjourney's own look is applied, 0 to 1000.", default=100),
        _g("weirdness", "integer", "How unusual the result is, 0 to 3000.", default=0),
        _g("variety", "integer", "How different the four pictures are from each other, 0 to 100.", default=0),
    ])


def google_manifest(model: str) -> dict:
    """Gemini API models (per ai.google.dev docs, Sept 2026). Media is sent inline, so refs are local files."""
    if model.startswith("veo-"):
        lite = "lite" in model
        fields = [
            _g("prompt", "string", "What happens in the video. Veo also follows sound cues in quotes; FilmCrafter mutes model audio.", required=True),
            _g("negative_prompt", "string", "What to avoid."),
            _g("image_url", "string", "First frame image (image-to-video)."),
            _g("last_frame_url", "string", "Last frame image; Veo interpolates between first and last frame."),
            _g("reference_image_urls", "array", "Up to 3 asset reference images for characters, objects or style.", items="string", max_items=3),
            _g("aspect_ratio", "string", "Frame shape.", enum=["16:9", "9:16"], default="16:9"),
            _g("resolution", "string", "Output resolution.", enum=["720p", "1080p"] + ([] if lite else ["4k"]), default="720p"),
            _g("duration", "string", "Length in seconds.", enum=["4", "6", "8"], default="8"),
            _g("person_generation", "string", "People in the video.", enum=["allow_adult", "allow_all"], default="allow_adult"),
            _g("seed", "integer", "Fix for repeatable results."),
        ]
        title = {"veo-3.1-generate-preview": "Veo 3.1", "veo-3.1-fast-generate-preview": "Veo 3.1 Fast",
                 "veo-3.1-lite-generate-preview": "Veo 3.1 Lite"}.get(model, model)
        return _finish("google", model, title, "video", fields)
    fields = [
        _g("prompt", "string", "What the image shows.", required=True),
        _g("image_urls", "array", "Reference images (characters, style, the previous shot).", items="string", max_items=14),
        _g("aspect_ratio", "string", "Frame shape.", enum=["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"] + (["1:4", "4:1", "1:8", "8:1"] if "2.1" in model else []), default="16:9"),
        _g("image_size", "string", "Output size.", enum=(["1K"] if "lite" in model else ["1K", "2K", "4K"]), default="1K"),
    ]
    title = {"gemini-nano-banana-2.1": "Nano Banana 2.1", "gemini-3.1-flash-image": "Nano Banana 2 (Gemini 3.1 Flash Image, retiring 29 Oct 2026)", "gemini-3-pro-image": "Nano Banana Pro (Gemini 3 Pro Image)",
             "gemini-3.1-flash-lite-image": "Gemini 3.1 Flash Lite Image"}.get(model, model)
    return _finish("google", model, title, "image", fields)


SIZE_PRESETS = {"landscape_16_9": 16 / 9, "landscape_4_3": 4 / 3, "square_hd": 1.0, "square": 1.0,
                "portrait_4_3": 3 / 4, "portrait_16_9": 9 / 16}

OPENAI_IMAGE_MODELS = ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2", "gpt-image-1.5"]


def openai_flex_sizes(model: str) -> bool:
    """GPT Image 2 and 2.5 take any width x height (multiples of 16, up to 3:1); GPT Image 1.5 only three fixed sizes."""
    return model.startswith("gpt-image-2")


def ratio_of(text: str | None, default: float = 16 / 9) -> float:
    """'21:9', '2.39:1' or '16:9' as a number."""
    m = re.match(r"^\s*([\d.]+)\s*:\s*([\d.]+)\s*$", str(text or ""))
    try:
        return float(m.group(1)) / float(m.group(2)) if m else default
    except (ValueError, ZeroDivisionError):
        return default


FLEX_LONG_EDGE = {"draft": 1280, "standard": 1536, "high": 1920, "max": 2560}   # the longer side asked of a GPT Image 2/2.5 model


def flex_size(aspect: str | None, quality: str | None = "standard") -> str:
    """The exact 'WxH' to ask a flexible-size image model for, so a 21:9 project gets a 21:9 picture instead of the nearest fixed shape.
    Both sides are multiples of 16, the shape is never wider than 3:1, and the picture stays inside the model's pixel budget."""
    r = min(3.0, max(1 / 3.0, ratio_of(aspect)))
    long_edge = FLEX_LONG_EDGE.get(quality or "standard", 1536)
    w, h = (long_edge, long_edge / r) if r >= 1 else (long_edge * r, long_edge)
    w, h = max(16, round(w / 16) * 16), max(16, round(h / 16) * 16)
    while w * h > 8_294_400:
        w, h = w - 16, h - 16
    while w * h < 655_360:
        w, h = round(w * 1.1 / 16) * 16, round(h * 1.1 / 16) * 16
    return f"{w}x{h}"


def fit_to_aspect(path: str, aspect: str | None, tolerance: float = 0.012) -> bool:
    """Trim a returned picture to the project's shape (a centred crop) when the model made a different one. The original is kept next to it
    as '<name>.uncropped.<ext>'. Returns True when it cropped. A picture that can't be opened is left exactly as it is."""
    want = ratio_of(aspect, 0.0)
    if want <= 0:
        return False
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
            if abs(w / h - want) / want <= tolerance:
                return False
            if w / h > want:                      # too wide: trim the sides
                nw, nh = round(h * want), h
            else:                                 # too tall: trim top and bottom
                nw, nh = w, round(w / want)
            left, top = (w - nw) // 2, (h - nh) // 2
            fmt = im.format or "PNG"
            cropped = im.crop((left, top, left + nw, top + nh)).copy()
        base, ext = os.path.splitext(path)
        os.replace(path, f"{base}.uncropped{ext}")
        cropped.save(path, format=fmt)
        return True
    except Exception:
        return False


def openai_manifest(model: str) -> dict:
    """OpenAI Images API (direct, with your OpenAI key). References are sent as files (edits endpoint)."""
    flex = openai_flex_sizes(model)
    size = (_g("size", "string", "Output size: any width x height (multiples of 16, up to 3:1). FilmCrafter asks for your project's shape.", default="1536x1024")
            if flex else _g("size", "string", "Output size (this model has three fixed shapes; FilmCrafter trims the picture to your project's shape).",
                            enum=["1536x1024", "1024x1024", "1024x1536", "auto"], default="1536x1024"))
    if flex:
        size["flex"] = True
    fields = [
        _g("prompt", "string", "What the image shows.", required=True),
        _g("image_urls", "array", "Reference images (characters, set, the previous shot). Up to 16.", items="string", max_items=16),
        size,
        _g("quality", "string", "Detail (and price).", enum=["low", "medium", "high", "auto"], default="high"),
    ]
    title = {"gpt-image-2.5-flare": "GPT Image 2.5 Flare", "gpt-image-2.5-sunburst": "GPT Image 2.5 Sunburst",
             "gpt-image-2": "GPT Image 2", "gpt-image-1.5": "GPT Image 1.5"}.get(model, model)
    return _finish("openai", model, title, "image", fields)


# ---------------------------------------------------------------- BytePlus ModelArk: ByteDance's own Seedream API (pictures only)
# Everything below is from BytePlus's published documentation, read 2026-10-30 (docs.byteplus.com/en/docs/modelark: the Seedream tutorial, the image tutorial and the pricing page); none of it
# has been proved by a real render here. Prices are per picture made, in USD. "pixels" is the allowed total pixels (width x height) for an exact size.
BYTEPLUS_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/images/generations"
BYTEPLUS_MODELS = {
    "dola-seedream-5-0-pro-260628": {"title": "Seedream 5.0 Pro", "refs": 10, "png": True, "pixels": (921_600, 4_624_220),
                                     "price": None, "tier": (2_610_000, 0.045, 0.09), "extra_ref": 0.003,        # 1.5K or lower $0.045, higher $0.09; the first reference picture is free
                                     "sizes": {"draft": "1K", "standard": "1.5K", "high": "2K", "max": "2K"}},   # 1.5K costs the same as 1K and looks better (BytePlus says so)
    "dola-seedream-5-0-flash-260915": {"title": "Seedream 5.0 Flash", "refs": 10, "png": True, "pixels": (921_600, 4_624_220), "price": 0.018,         # the size limits of Pro are assumed: BytePlus lists the same levels
                                       "sizes": {"draft": "1K", "standard": "1.5K", "high": "2K", "max": "2K"}},
    "seedream-5-0-260128": {"title": "Seedream 5.0 Lite", "refs": 14, "png": True, "pixels": (3_686_400, 16_777_216), "price": 0.035,
                            "sizes": {"draft": "2K", "standard": "2K", "high": "4K", "max": "4K"}},
    "seedream-4-5-251128": {"title": "Seedream 4.5", "refs": 14, "png": False, "pixels": (3_686_400, 16_777_216), "price": 0.04,
                            "sizes": {"draft": "2K", "standard": "2K", "high": "4K", "max": "4K"}},
    "seedream-4-0-250828": {"title": "Seedream 4.0", "refs": 14, "png": False, "pixels": (921_600, 16_777_216), "price": 0.03,
                            "sizes": {"draft": "1K", "standard": "2K", "high": "4K", "max": "4K"}},
}
_LEVEL_PIXELS = {"1K": 1024 ** 2, "1.5K": 1536 ** 2, "2K": 2048 ** 2, "3K": 3072 ** 2, "4K": 4096 ** 2}


def byteplus_size(model: str, project: dict) -> str:
    """The exact "WIDTHxHEIGHT" to ask for: the film's shape at the size level the quality tier maps to, inside the model's published pixel range (multiples of 16)."""
    info = BYTEPLUS_MODELS[model]
    level = info["sizes"].get(project.get("quality", "standard"), info["sizes"]["standard"])
    lo, hi = info["pixels"]
    ratio = min(16.0, max(1 / 16, _ratio(project)))
    budget = float(_LEVEL_PIXELS[level])
    for _ in range(60):                                          # nudge until the rounded size is inside the allowed range
        w = max(16, int((budget * ratio) ** 0.5) // 16 * 16)
        h = max(16, int((budget / ratio) ** 0.5) // 16 * 16)
        if w * h > hi:
            budget *= 0.98
        elif w * h < lo:
            budget *= 1.02
        else:
            return f"{w}x{h}"
    raise SystemExit(f"No size in {info['title']}'s range fits this film's shape.")


def byteplus_price(model: str, payload: dict) -> dict:
    """What one picture costs on BytePlus (their published price, which is exact for the size and the reference pictures sent)."""
    info = BYTEPLUS_MODELS.get(model)
    if not info:
        return {"usd": None, "basis": "BytePlus has not published a price for this model here."}
    m = re.fullmatch(r"(\d+)x(\d+)", str(payload.get("size") or ""))
    pixels = int(m.group(1)) * int(m.group(2)) if m else None
    if info.get("tier"):
        if pixels is None:
            return {"usd": None, "basis": "The size is not chosen yet, and the price depends on it."}
        limit, low, high = info["tier"]
        usd, basis = (low, f"${low} for a picture up to {limit / 1e6:.2f} million pixels") if pixels <= limit else (high, f"${high} for a picture over {limit / 1e6:.2f} million pixels")
    else:
        usd, basis = info["price"], f"${info['price']} per picture"
    refs = len(payload.get("image_urls") or [])
    extra = max(0, refs - 1) * info.get("extra_ref", 0.0)
    if extra:
        usd += extra
        basis += f" + ${extra:.3f} for {refs - 1} extra reference picture{'s' if refs > 2 else ''}"
    return {"usd": round(usd, 4), "basis": f"{basis} (BytePlus's published price; a picture its moderation refuses is not billed)"}


def byteplus_manifest(model: str) -> dict:
    """BytePlus ModelArk Images API (direct, with your BytePlus key). References are sent inside the request as base64 pictures."""
    info = BYTEPLUS_MODELS.get(model)
    if not info:
        raise SystemExit(f"{model} is not a BytePlus picture model FilmCrafter knows.")
    fields = [
        _g("prompt", "string", "What the image shows.", required=True),
        _g("image_urls", "array", f"Reference images (characters, set, the previous shot). Up to {info['refs']}.", items="string", max_items=info["refs"]),
        _g("size", "string", "Output size as WIDTHxHEIGHT. FilmCrafter asks for your project's shape at the size its quality setting maps to."),
    ]
    return _finish("byteplus", model, info["title"], "image", fields)


GOOGLE_MODELS = [
    ("veo-3.1-generate-preview", "video"), ("veo-3.1-fast-generate-preview", "video"), ("veo-3.1-lite-generate-preview", "video"),
    ("gemini-nano-banana-2.1", "image"), ("gemini-3.1-flash-image", "image"), ("gemini-3-pro-image", "image"), ("gemini-3.1-flash-lite-image", "image"),
]

# The automatic picture models are editing models: they redraw reference pictures, so they need one. A film that has no pictures yet (no character art, nothing chosen before) would be refused,
# so with no reference at all the same family's text-to-picture model is used instead (found in a real run against Kie.ai: "Needs an image for image_urls").
TEXT_ONLY_SIBLING = {"google/nano-banana-edit": "google/nano-banana", "fal-ai/nano-banana/edit": "fal-ai/nano-banana"}


def text_only_model(model: str, has_references: bool) -> str:
    """The model to draw a picture with: the same one when there is a reference to edit, its text-to-picture sibling when there is none."""
    if has_references:
        return model
    if model in TEXT_ONLY_SIBLING:
        return TEXT_ONLY_SIBLING[model]
    if "image-to-image" in model:                                   # GPT Image, Flux 2, Seedream...: the "image-to-image" model has a "text-to-image" twin
        return model.replace("image-to-image", "text-to-image")
    return model


def default_model(provider: str, kind: str = "video") -> str:
    """The Auto model for a provider (ComfyUI: your first workflow of that kind)."""
    if provider == "comfyui":
        from . import comfy
        flows = [w for w in comfy.workflows() if kind == "lipsync" or w["kind"] == ("image" if kind == "image" else "video")] \
            or comfy.workflows()
        if not flows:
            raise SystemExit("Add a ComfyUI workflow in Settings → ComfyUI first.")
        return flows[0]["model"]
    table = {"image": AUTO_IMAGE, "lipsync": AUTO_LIPSYNC}.get(kind, AUTO)
    if provider not in table:
        raise SystemExit(f"{provider} has no automatic {kind} model; choose one in Director Mode.")
    return table[provider]


def manifest(provider: str, model: str, refresh: bool = False) -> dict:
    if provider == "kie" and model in MJ_MODELS:
        return midjourney_manifest(model)
    if provider == "google":
        return google_manifest(model)
    if provider == "openai":
        return openai_manifest(model)
    if provider == "byteplus":
        return byteplus_manifest(model)
    if provider == "comfyui":
        from . import comfy
        return comfy.manifest(model)
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{provider}__{re.sub(r'[^A-Za-z0-9._-]+', '_', model)}.json")
    if not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        # Recompute roles so improvements to role detection apply to cached schemas too.
        m = {**_finish(m["provider"], m["model"], m["title"], m.get("category", ""), m["inputs"]), "fetched": m.get("fetched")}
        _remember_alias(provider, model, m)
        return m
    if provider == "kie":
        alias = (_read(os.path.join(CACHE_DIR, "kie_aliases.json"), {}) or {}).get(model)
        m = kie_manifest(alias or model)
    else:
        m = fal_manifest(model)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1, ensure_ascii=False)
    _remember_alias(provider, model, m)
    return m


def _remember_alias(provider: str, asked: str, m: dict) -> None:
    """Kie docs can name a model differently from their URL (kling/image-to-video -> kling-2.6/image-to-video).
    Remember both so jobs that store the resolved id can find the schema again."""
    if provider != "kie" or m["model"] == asked:
        return
    aliases = _read(os.path.join(CACHE_DIR, "kie_aliases.json"), {}) or {}
    if aliases.get(m["model"]) != asked:
        aliases[m["model"]] = asked
        _write(os.path.join(CACHE_DIR, "kie_aliases.json"), aliases)
    resolved = os.path.join(CACHE_DIR, f"kie__{re.sub(r'[^A-Za-z0-9._-]+', '_', m['model'])}.json")
    if not os.path.exists(resolved):
        with open(resolved, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1, ensure_ascii=False)


FAL_CATEGORIES = {"video": ("image-to-video", "text-to-video", "video-to-video"),
                  "image": ("text-to-image", "image-to-image"),
                  "lipsync": ("video-to-video", "audio-to-video")}


def _with_midjourney(provider: str, kind: str, items: list[dict]) -> list[dict]:
    if (provider, kind) != ("kie", "image"):
        return items
    have = {m["model"] for m in items}
    return items + [{"provider": "kie", "model": m, "category": "text-to-image", "title": midjourney_manifest(m)["title"]} for m in MJ_MODELS if m not in have]


def motion_catalog(provider: str, refresh: bool = False) -> list[dict]:
    """The motion-control models of a provider (Kie.ai lists them among its video tools): recommended first."""
    from . import modelinfo
    if provider != "kie":
        return []
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "catalog__kie__motion.json")
    raw = None
    if not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = None
    if raw is None:
        raw = _catalog("kie", "motion")
        if raw:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(raw, f)
    items = [dict(m) for m in raw if is_motion_model(m.get("model", ""))]
    for m in items:
        m["sees"], m["text"] = True, False
        m["rec"] = MOTION_RECOMMENDED.index(m["model"]) if m["model"] in MOTION_RECOMMENDED else None
        m["fresh"] = False
    return sorted(items, key=lambda m: (m["rec"] is None, m["rec"] if m["rec"] is not None else 0, m.get("title", "")))


def catalog(provider: str, kind: str = "video", refresh: bool = False) -> list[dict]:
    if kind == "motion":
        return motion_catalog(provider, refresh)
    """Models a user can pick in Director Mode (kind: video | image | lipsync | upscale). Cached for a day (`refresh` asks the provider again, to see models added today).
    Each entry also says whether the model can see your pictures, is good at text, is recommended or new (modelinfo.py)."""
    from . import modelinfo
    if provider == "comfyui":
        return _catalog(provider, kind)
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"catalog__{provider}__{kind}.json")
    if not refresh and os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        if (provider, kind) == ("kie", "video"):
            cached = [m for m in cached if kie_makes_video(m["model"])]      # an older saved list may still hold tools
        if (provider, kind) == ("kie", "image"):
            cached = [m for m in cached if not modelinfo.is_image_tool(m["model"])]
        return modelinfo.decorate(_with_midjourney(provider, kind, cached), provider, kind, CACHE_DIR)
    out = _catalog(provider, kind)
    if out:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f)
    return modelinfo.decorate(_with_midjourney(provider, kind, out), provider, kind, CACHE_DIR)


def _catalog(provider: str, kind: str = "video") -> list[dict]:
    if provider == "openai":
        return [{"provider": "openai", "model": m, "category": "image", "title": openai_manifest(m)["title"]}
                for m in OPENAI_IMAGE_MODELS] if kind == "image" else []
    if provider == "byteplus":
        return [{"provider": "byteplus", "model": m, "category": "image", "title": i["title"]} for m, i in BYTEPLUS_MODELS.items()] if kind == "image" else []
    if provider == "comfyui":
        from . import comfy
        return [{"provider": "comfyui", "model": w["model"], "category": f"workflow-{w['kind']}", "title": w["title"]}
                for w in comfy.workflows() if w["kind"] == kind or kind == "lipsync"]
    if provider == "google":
        return [{"provider": "google", "model": m, "category": k, "title": google_manifest(m)["title"]}
                for m, k in GOOGLE_MODELS if k == kind]
    if provider == "fal":
        out, seen = [], set()
        for cat in FAL_CATEGORIES.get(kind, FAL_CATEGORIES["video"]):
            cursor = None
            for _ in range(10):
                params = {"category": cat, "limit": 100, "status": "active"}
                if cursor:
                    params["cursor"] = cursor
                r = http_get("https://api.fal.ai/v1/models", params=params, headers=_fal_headers()).json()
                for m in r.get("models", []):
                    if m["endpoint_id"] not in seen:
                        seen.add(m["endpoint_id"])
                        out.append({"provider": "fal", "model": m["endpoint_id"], "category": cat,
                                    "title": m.get("metadata", {}).get("display_name", m["endpoint_id"])})
                cursor = r.get("next_cursor")
                if not r.get("has_more") or not cursor:
                    break
        if kind == "lipsync":
            out = [m for m in out if re.search(r"lip.?sync|sync-|talking|avatar", m["model"] + m["title"], re.I)]
        return out
    from . import modelinfo
    if kind == "motion":       # motion control: a reference video drives the character (listed by Kie among its video tools)
        return [{"provider": "kie", "model": _slug_from_doc(e["doc"]), "category": "motion", "title": f"{e['family']} · {e['title']}", "doc": e["doc"]}
                for e in _kie_index() if e["kind"] == "video" and is_motion_model(_slug_from_doc(e["doc"]))]
    if kind == "upscale":      # Topaz, Recraft and Grok upscalers: tools that take a picture or a video you have and give it back sharper and larger
        return [{"provider": "kie", "model": _slug_from_doc(e["doc"]), "category": "video-upscale" if e["kind"] == "video" else "image-upscale",
                 "title": f"{e['family']} · {e['title']}", "doc": e["doc"]} for e in _kie_index() if modelinfo.is_upscaler(_slug_from_doc(e["doc"]))]
    return [{"provider": "kie", "model": _slug_from_doc(e["doc"]), "category": e["kind"], "title": f"{e['family']} · {e['title']}",
             "doc": e["doc"]} for e in _kie_index()
            if (e["kind"] == kind and (kind != "video" or kie_makes_video(_slug_from_doc(e["doc"]))) and (kind != "image" or not modelinfo.is_image_tool(_slug_from_doc(e["doc"]))))
            or (kind == "lipsync" and re.search(r"lip.?sync|avatar|infinitalk", e["doc"] + e["title"], re.I))]


# Kie lists tools under "video" that are not video generators: they need a video you already have, or do something else (upscale, extend, edit,
# motion transfer, face detection, talking-avatar and lip-sync tools). They stay out of the video model picker, because choosing one can only fail.
KIE_NOT_A_GENERATOR = re.compile(r"upscale|/extend|motion-control|identification|subject-detection|video-?edit|video-to-video|animate-(?:move|replace)|"
                                 r"transformation|gemini-omni-(?:audio|character)|ai-avatar|infinitalk|transition", re.I)


# Motion control: a reference VIDEO drives how your character moves (dance, acting, a walk), and a picture says who the character is. Kie lists these among the video tools; they are shown in
# their own picker (kind "motion") and never as an ordinary video model, because choosing one without a motion video can only fail.
MOTION_RX = re.compile(r"motion-control|animate-(?:move|replace)", re.I)
MOTION_RECOMMENDED = ["kling-3.0/motion-control", "kling/motion-control-v3", "kling-2.6/motion-control", "kling/motion-control", "wan/2-2-animate-move"]


def is_motion_model(slug: str) -> bool:
    return bool(MOTION_RX.search(slug or ""))


def motion_fields(man: dict) -> dict:
    """Which of a motion model's inputs is the character picture, the motion video, the facing, the quality and the background."""
    names = {f["name"]: f for f in man.get("inputs") or []}
    pick = lambda *c: next((n for n in c if n in names), None)
    return {"image": pick("input_urls", "image_url", "image_urls", "input_image"), "video": pick("video_urls", "video_url", "input_video", "video"),
            "orientation": pick("character_orientation"), "quality": pick("mode", "resolution"), "background": pick("background_source"), "prompt": pick("prompt")}


def compile_motion(d: str, man: dict, shot: dict, motion: dict, overrides: dict | None = None) -> dict:
    """A motion-control request: the character picture and the motion video (project files, uploaded at send time), how to face, how sharp, whose background, and the look as the prompt."""
    f = motion_fields(man)
    fields = {x["name"]: x for x in man["inputs"]}
    if not f["image"] or not f["video"]:
        raise SystemExit(f"{man.get('title') or man['model']} doesn't take a character picture and a motion video, so it can't be used for motion control.")
    wrap = lambda name, rel: [PROJECT_MEDIA + rel] if fields[name]["type"] == "array" else PROJECT_MEDIA + rel
    payload = {f["video"]: wrap(f["video"], motion["video"]), f["image"]: wrap(f["image"], motion["image"])}
    if f["orientation"]:
        want = motion.get("orientation") or "video"
        en = fields[f["orientation"]].get("enum")
        payload[f["orientation"]] = want if not en or want in en else en[0]
    if f["quality"]:
        pro = (motion.get("quality") or "pro") == "pro"
        en = fields[f["quality"]].get("enum") or []
        payload[f["quality"]] = ("1080p" if pro else "720p") if "1080p" in en else ("pro" if pro else "std")
    if f["background"]:
        payload[f["background"]] = "input_image" if motion.get("background") == "image" else "input_video"
    if f["prompt"]:
        look = resolve_look(_read(os.path.join(d, "project.json"), {}), shot.get("scene"), shot.get("id"))
        text = " ".join(x.strip() for x in (motion.get("note") or "", f"The character keeps exactly the face, hair, clothes and body of the picture. {look['prompt']}") if x and x.strip())
        limit = fields[f["prompt"]].get("max_length") or 2500
        payload[f["prompt"]] = text.encode("utf-8")[:limit].decode("utf-8", "ignore")
    for k, v in (overrides or {}).items():
        if k in fields:
            payload[k] = v
    return fill_required(man, payload, [])


def kie_makes_video(slug: str) -> bool:
    return not KIE_NOT_A_GENERATOR.search(slug or "")


def _slug_from_doc(doc: str) -> str:
    # docs.kie.ai/market/bytedance/seedance-2.md -> bytedance/seedance-2 (matches Kie ids for most models;
    # the manifest fetch reads the exact id from the doc's schema).
    return doc.split("/market/")[1].removesuffix(".md")


# ---------------------------------------------------------------- looks

STYLES_PATH = os.path.join(os.path.dirname(__file__), "styles.json")


def styles() -> dict[str, dict]:
    with open(STYLES_PATH, encoding="utf-8") as f:
        return {s["id"]: s for s in json.load(f)["styles"]}


def own_look_id(look: dict, scene=None, shot=None) -> str | None:
    """The look a shot is played in when it is not the film's: the shot's own (look.shots), else its scene's (look.scenes). A look id that is not in the library (or is a genre feel,
    which is only ever layered on a look) is ignored, so a hand-edited or older project falls back to the next level. Pure: it reads, never writes."""
    lib = styles()
    for table, key in (("shots", shot), ("scenes", scene)):
        if key is None or not isinstance(look.get(table), dict):
            continue
        own = look[table].get(str(key))
        if isinstance(own, str) and own in lib and lib[own].get("family") != "genre":
            return own
    return None


def resolve_look(project: dict, scene=None, shot=None) -> dict:
    """Project look -> {'id', 'prompt', 'avoid'}. Custom wording (Director Mode) overrides the library's. A shot played in a look of its own (stylebible.py) gets that look's wording;
    otherwise its scene's own look, otherwise the film's. The film's notes ("keep Sege's beard") still apply; its custom wording and genre feel belong to the film's look and do not."""
    look = project.get("look") or {"style": "auto"}
    if isinstance(look, str):  # early projects stored free text
        return {"id": "custom", "prompt": look, "avoid": ""}
    own = own_look_id(look, scene, shot)
    if own:
        lib = styles()[own]
        notes = str(look.get("notes") or "").strip()
        return {"id": own, "prompt": f"{lib['prompt']} {notes}" if notes else lib["prompt"], "avoid": lib["avoid"]}
    base = styles().get(look.get("style", "auto"), styles()["auto"])
    prompt = look.get("prompt") or base["prompt"]
    avoid = look.get("avoid") if look.get("avoid") is not None else base["avoid"]
    genre = styles().get(look.get("genre") or "")
    if genre and genre.get("family") == "genre":                  # a genre feel (epic fantasy, noir, solarpunk...) is layered on top of the look, never in place of it
        prompt = f"{prompt} {genre['prompt'].strip()}"
        avoid = ", ".join(x for x in (avoid, genre.get("avoid")) if x)
    if look.get("notes"):
        prompt = f"{prompt} {look['notes'].strip()}"
    return {"id": base["id"], "prompt": prompt, "avoid": avoid}


# ---------------------------------------------------------------- compile: Shot Contract -> request

def _nearest_aspect(options: list[str] | None, ratio: float) -> str | None:
    if not options:
        return None
    best, err = None, 9e9
    for o in options:
        m = re.match(r"^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$", str(o))
        if m and abs(float(m.group(1)) / float(m.group(2)) - ratio) < err:
            best, err = o, abs(float(m.group(1)) / float(m.group(2)) - ratio)
    return best


def _duration_value(field: dict, need: float):
    """Smallest allowed duration >= shot length + a short handle for trimming on the beat."""
    want = need + 0.5
    if field.get("exact"):  # local renderers (ComfyUI) make exactly what's needed, within what the workflow allows
        return round(min(float(field.get("maximum") or want), max(float(field.get("minimum") or 0), want)), 2)
    if field.get("enum"):
        nums = sorted(float(str(e).rstrip("s")) for e in field["enum"] if re.match(r"^\d+(\.\d+)?$", str(e).rstrip("s")))
        pick = next((n for n in nums if n >= want), nums[-1] if nums else None)
        if pick is None:
            return field.get("default")
        raw = next(e for e in field["enum"] if re.match(r"^\d", str(e)) and float(str(e).rstrip("s")) == pick)
        return raw
    lo = field.get("minimum") or 4
    hi = field.get("maximum") or 15
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*sec", field.get("description", ""))
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
    val = int(min(hi, max(lo, math.ceil(want))))
    return val if field["type"] == "integer" else str(val) if field["type"] == "string" else val


INTENSITY = [(3, "restrained, almost still, the feeling held just under the surface"),
             (6, "grounded and natural, clearly felt but never pushed"),
             (8, "heightened and visible, the emotion driving the body"),
             (11, "at full intensity, the emotion overwhelming control")]
QUALITY_TIERS = ("draft", "standard", "high", "max")


def _intensity_words(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    return next(w for lim, w in INTENSITY if n < lim)


def _locked_names(locked_design: str | None) -> set[str]:
    """The names in a 'Locked design, keep exactly: Name: rules | Other: rules.' block, lower case. Those are described in full there."""
    return {m.strip().lower() for m in re.findall(r"(?:keep exactly:\s*|\|\s*)([^:|]+?):", locked_design or "")}


def _ref_label(label: str, locked_design: str | None) -> str:
    """A reference's label without its notes when those notes are the same locks the Locked design block already states in full (the notes were cut at 120 characters,
    which is why a lock could end mid-word in the References line)."""
    head, sep, _notes = label.partition(" — ")
    if sep and any(n and n in head.lower() for n in _locked_names(locked_design)):
        return head
    return label


def default_play(n) -> str:
    """The closing note on how to play a shot when no acting style was chosen. It follows the shot's intensity, so it never contradicts it:
    a shot directed at 'heightened' must not be told 'no exaggerated poses'."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 4
    if n >= 8:
        return ("Commit fully: the feeling takes over the face, breath and hands; keep it human and specific, with real eye-lines and weight, never mugging or cartoon poses.")
    if n >= 6:
        return ("Let the feeling read: motivated gestures, a face that shows the change, eyes that think before they move, breathing that matches the emotion; committed but never mugging.")
    return ("Play it truthfully: motivated small gestures, eyes that think before they move, breathing that matches the emotion; no mugging or exaggerated poses.")


def _character(plan: dict, name: str) -> dict:
    return next((c for c in plan.get("characters", []) if c.get("name", "").lower() == name.lower()), {})


def acting_direction(shot: dict, plan: dict, play: str | None = None) -> str:
    """Actor-language direction for the performance, the part video models most often get wrong.

    Combines the shot's directed performance (emotion, intensity, intention, body, face, gaze, movement)
    with each performer's standing acting notes from the character bible.
    """
    lines = []
    emotion, level = shot.get("emotion"), _intensity_words(shot.get("performance_intensity"))
    if emotion or level:
        lines.append(f"Emotion: {emotion or 'as the moment requires'}" + (f", played {level}" if level else "") + ".")
    if shot.get("performance"):
        lines.append(f"Performance: {shot['performance'].rstrip('.')}.")
    if shot.get("expression"):
        lines.append(f"Face: {shot['expression'].rstrip('.')}.")
    if shot.get("movement"):
        lines.append(f"Body and blocking: {shot['movement'].rstrip('.')}.")
    for name in shot.get("performers", []):
        notes = _character(plan, name).get("acting_notes")
        if notes:
            lines.append(f"{name}'s acting style: {notes.strip().rstrip('.')}.")
    if lines or (play and shot.get("performers")):
        # a chosen performance profile replaces the default truthful-and-small note
        lines.append(play or default_play(shot.get("performance_intensity")))
    return " ".join(lines)


K_TOKEN = re.compile(r"^(?:auto_)?(\d+(?:\.\d+)?)\s*k$", re.I)


def _k(value) -> float | None:
    """1.5 for "auto_1.5K", 4 for "4K": the size a picture model names in thousands of pixels (None for anything else)."""
    m = K_TOKEN.match(str(value).strip())
    return float(m.group(1)) if m else None


def _k_only(opts) -> bool:
    return bool(opts) and all(_k(o) is not None for o in opts)


def _pick_quality(field: dict, tier: str):
    """Map a project quality tier onto the model's own resolution options. A picture model that names its sizes 1K, 2K, 4K gets the smallest at Draft and Standard and the largest
    at High and Max (it used to get the largest at every tier: 4K for a draft)."""
    opts = field.get("enum") or []
    if _k_only(opts):
        ordered = sorted(opts, key=_k)
        return ordered[-1] if tier in ("high", "max") else ordered[0]

    def height(o):
        if str(o).lower() in ("4k", "2160p"):
            return 2160
        m = re.search(r"(\d{3,4})", str(o))
        return int(m.group(1)) if m else 0

    ranked = sorted((o for o in opts if height(o)), key=height)
    if not ranked:
        return field.get("default")
    if tier == "draft":
        return ranked[0]
    if tier == "max":
        return ranked[-1]
    want = 1080 if tier == "high" else 720
    return min(ranked, key=lambda o: (abs(height(o) - want), -height(o)))


def _ratio(project: dict) -> float:
    m = re.match(r"^\s*([\d.]+)\s*[:/]\s*([\d.]+)\s*$", str(project.get("aspect_ratio", "16:9")))
    r = float(m.group(1)) / float(m.group(2)) if m and float(m.group(2)) else 16 / 9
    return r if 0.1 < r < 10 else 16 / 9


def _dims(k: float, ratio: float) -> dict:
    """The exact size for "k thousand pixels" on the long edge, in the project's shape (multiples of 8)."""
    long_edge = round(k * 1024)
    w, h = (long_edge, long_edge / ratio) if ratio >= 1 else (long_edge * ratio, long_edge)
    return {"width": max(8, round(w / 8) * 8), "height": max(8, round(h / 8) * 8)}


def picture_size_plan(man: dict, project: dict) -> dict:
    """What the quality tier asks of a PICTURE model's size: {"payload": the fields to set, "key": "" for the model's basic size, else a short name of the larger one}.
    High and Max ask for the largest size the model offers (2K for Seedream 5 Pro, 4K for Seedream 4.5); Draft and Standard keep the basic size. The key is what a price is
    remembered under, because a bigger picture costs more: a price learned at the basic size must never be shown for a 4K one. Video models are left to `_pick_quality`."""
    roles, fields = man.get("roles") or {}, {f["name"]: f for f in man.get("inputs") or []}
    if "duration" in roles:
        return {"payload": {}, "key": ""}
    top = project.get("quality", "standard") in ("high", "max")
    payload, key = {}, ""
    q = fields.get("quality")
    if q and sorted(str(x) for x in (q.get("enum") or [])) == ["basic", "high"]:         # Kie's Seedream: basic is the small size, high the large one
        payload["quality"] = "high" if top else "basic"
        key = "quality=high" if top else ""
    sz = fields.get("image_size")
    autos = [_k(o) for o in (sz.get("enum") or []) if str(o).lower().startswith("auto_") and _k(o)] if sz else []
    if top and autos and "aspect_ratio" not in roles:                                  # fal's Seedream: an exact width and height in the project's shape
        k = max(autos)
        payload["image_size"] = _dims(k, _ratio(project))
        key = f"size={k:g}K"
    res = fields.get(roles.get("resolution", ""))
    if res and _k_only(res.get("enum")):
        chosen = _pick_quality(res, project.get("quality", "standard"))
        if _k(chosen) != min(_k(o) for o in res["enum"]):
            key = f"resolution={chosen}"
    return {"payload": payload, "key": key}


class RequestProblem(Exception):
    """The request can't be sent as-is (caught before any billable call)."""


MEDIA_NAME = re.compile(r"(image|video|audio|frame|mask|reference|url)", re.I)


def fill_required(man: dict, payload: dict, refs: list[dict]) -> dict:
    """Satisfy required inputs the Shot Contract doesn't cover: model defaults / first allowed value for
    settings, and the approved keyframe or a character image for a required still image."""
    images = [r["url"] for r in refs]
    for f in man["inputs"]:
        name = f["name"]
        if not f.get("required") or payload.get(name) not in (None, "", []):
            continue
        n = f"{name} {f.get('description', '')}".lower()
        if f["type"] == "boolean":
            payload[name] = f["default"] if isinstance(f.get("default"), bool) else False
        elif f.get("enum"):
            payload[name] = f["default"] if f.get("default") in f["enum"] else f["enum"][0]
        elif f.get("default") not in (None, ""):
            payload[name] = f["default"]
        elif MEDIA_NAME.search(name) and "image" in n and "video" not in name.lower() and images:
            payload[name] = images if f["type"] == "array" else images[0]
    return payload


def validate_request(man: dict, payload: dict) -> list[str]:
    """Problems that would make the provider reject the request. Empty list = OK to send."""
    problems = []
    fields = {f["name"]: f for f in man["inputs"]}
    for f in man["inputs"]:
        if f.get("required") and payload.get(f["name"]) in (None, "", []):
            kind = "video" if "video" in f["name"].lower() else "audio" if "audio" in f["name"].lower() else \
                "image" if MEDIA_NAME.search(f["name"]) else "value"
            problems.append(f"Needs {'an' if kind in ('audio', 'image') else 'a'} {kind} for “{f['name'].strip()}”"
                            + (f": {f['description'][:90]}" if f.get("description") else ""))
    for k, v in payload.items():
        f = fields.get(k)
        if not f or v in (None, ""):
            continue
        if f.get("enum") and not isinstance(v, (list, dict)) and str(v) not in [str(x) for x in f["enum"]]:
            problems.append(f"“{k}” can't be {v!r}; allowed: {', '.join(map(str, f['enum']))}")
        if f.get("max_items") and isinstance(v, list) and len(v) > f["max_items"]:
            problems.append(f"“{k}” takes at most {f['max_items']} items (got {len(v)})")
        if f["type"] in ("integer", "number") and isinstance(v, (int, float)):
            if f.get("minimum") is not None and v < f["minimum"]:
                problems.append(f"“{k}” must be at least {f['minimum']}")
            if f.get("maximum") is not None and v > f["maximum"]:
                problems.append(f"“{k}” must be at most {f['maximum']}")
    return problems


EDITOR_NOTE = re.compile(r"\b(svg|in editing|for editing|editing (?:insert|resource|note)|human editing|text to add|lower[- ]third|title card|end card)\b", re.I)


_TITLES = {"dr", "mr", "mrs", "ms", "miss", "auntie", "aunt", "uncle", "chief", "sir", "madam", "mama", "papa", "the"}      # words in a name that name nobody in particular


def _cast_tokens(plan: dict) -> dict[str, str]:
    """Each capitalised word that names exactly one character ("Mercy", "Emmanuel", "Queen"), mapped to that character. A word several characters share (a family name,
    "Auntie") names nobody in particular, so it is left out."""
    owners: dict[str, set[str]] = {}
    for c in plan.get("characters", []):
        name = c.get("name") or ""
        for tok in re.findall(r"[A-Z][\w'’-]{2,}", name):
            if tok.lower() not in _TITLES:
                owners.setdefault(tok, set()).add(name)
    return {t: next(iter(n)) for t, n in owners.items() if len(n) == 1}


def for_this_shot(text: str, shot: dict, plan: dict, project: dict | None = None) -> str:
    """The project-wide rules (world, always, palette, never) as they apply to one shot: any sentence or clause that names a character who is NOT in this shot is left out.
    A line like "Emmanuel is clean shaven; Mercy has no glasses" in the prompt of a close-up of someone else invites exactly those people into the picture.
    Rules that name nobody (the set, the light, the style) always stay. `bible_all_shots: true` in project.json switches this off."""
    if not text or (project or {}).get("bible_all_shots"):
        return text
    tokens = _cast_tokens(plan)
    if not tokens:
        return text
    here = {n.lower() for n in shot.get("performers") or []}
    keep = []
    for unit in re.split(r"(?<=[.!?])\s+|;\s+", text):
        unit = unit.strip()
        if not unit:
            continue
        named = {owner for tok, owner in tokens.items() if re.search(r"(?<![\w])" + re.escape(tok) + r"(?![\w])", unit)}
        if all(o.lower() in here for o in named):
            keep.append(unit if unit[-1] in ".!?" else unit + ".")
    return " ".join(keep)


def bible_text(text) -> str:
    """A Production Bible field as plain visual rules for the model: markdown headings and symbols out, and any section or sentence that is only
    a note for the editor (texts to add in editing, SVG resources, insert cards) out, so no written words are suggested for the picture.
    The bible often arrives flattened onto one line ("... satire. ## Text to add in editing ..."), so headings are found inline too."""
    t = str(text or "")
    t = re.sub(r"\s+(#{2,6})\s+", r"\n\1 ", t)                                   # an inline "## Heading" starts a new section
    t = re.sub(r"(?mi)^#\s*[^\n.]*?production bible\s*", "", t)                   # the document title
    sections = []
    for sec in re.split(r"\n(?=#{2,6}\s)", t):                                    # a section whose heading is about editing is only for the editor
        head = sec.split("\n", 1)[0] if sec.lstrip().startswith("#") else ""
        if head and EDITOR_NOTE.search(head[:80]):
            continue
        sections.append(re.sub(r"(?m)^\s*(?:#{1,6}|[-•])\s*", "", sec))
    t = " ".join(sections)
    t = re.sub(r"[*_`]{1,3}", "", t)
    parts = re.split(r"(?<=[.!?])\s+|\n+", t)                                  # whole sentences only: a ";" inside a list stays where it is
    keep = [p.strip().rstrip(".").strip() for p in parts if p.strip(" .") and not EDITOR_NOTE.search(p)]
    return ". ".join(k for k in keep if k).strip()


def compile_request(shot: dict, scene: dict | None, plan: dict, project: dict, man: dict,
                    refs: list[dict], overrides: dict | None = None, fix_notes: list[str] | None = None,
                    sung: dict | None = None, native: dict | None = None, said: dict | None = None, trace: list | None = None) -> dict:
    """Shot Contract -> this model's request. `trace`, if given, is filled with every block of the prompt ({priority, text, kept}) for the prompt budget view.

    refs: reference images already uploaded [{'label', 'url'}]. sung: optional lip-sync audio
    {'url', 'lyrics', 'performer'} for shots where a character sings. native: the lines the model itself speaks in this
    shot (native_for), for a scene whose dialogue is spoken by the video model instead of a recorded voice.
    """
    roles, fields = man["roles"], {f["name"]: f for f in man["inputs"]}
    payload: dict = {}
    look = resolve_look(project, (scene or {}).get("number"), shot.get("id"))  # the film's look wording goes into every shot, unless the shot (or its scene) is played in a look of its own
    # A shot (or scene) played in a look of its own is RESTYLED: the reference pictures show the people in the film's look, and a model follows a picture before words, so without this
    # only the set changes and the characters keep their old rendering. `keep_cast` (look.keep_cast[shot id]) is the person's choice to change only the world.
    _lk = project.get("look") if isinstance(project.get("look"), dict) else {}
    restyle = own_look_id(_lk, (scene or {}).get("number"), shot.get("id")) is not None
    keep_cast = restyle and bool((_lk.get("keep_cast") or {}).get(str(shot.get("id"))))
    full = restyle and not keep_cast
    look_name = look["prompt"].split(":")[0].rstrip(".")
    fig = fig_avoid = ""
    if full:     # how the people themselves are built in this look (faceted, clay, pixels...): the reference pictures show them smooth, and a model follows a picture before words
        _s = styles().get(look["id"], {})
        fig = _s.get("figures") or "their skin, hair, clothes and faces carry exactly the same surface and shading treatment as the set around them, with nothing smoother, glossier or more detailed than the rest"
        fig_avoid = _s.get("figures_avoid") or ""
        look = {**look, "avoid": ", ".join(x for x in (look.get("avoid"), fig_avoid, "the characters drawn in a different style from the rest of the picture") if x)}
    from . import styleguard as SG   # a stylised look is kept: words that ask for a photograph, from elsewhere in the prompt, are reworded (see styleguard.py)
    style = SG.sanitize(plan.get("meta", {}).get("VISUAL STYLE", ""), project, look["id"])
    blocks: list[tuple[int, str]] = []  # (priority, text); lowest priority is dropped first if too long

    body = SG.sanitize(shot.get("visual_prompt") or " ".join(shot.get("beats", [])) or shot.get("description", ""), project, look["id"])
    custom = str(shot.get("custom_prompt") or "").strip() if "duration" in roles else ""   # the filmmaker's own words for what happens (video only)
    only = bool(custom and shot.get("prompt_only"))
    if custom:
        body = SG.sanitize(custom, project, look["id"])
    if "duration" not in roles:  # an image model: this is the shot's first frame
        # Image models weight the opening words most, so the look leads.
        lead = look["prompt"].split(":")[0].rstrip(".")
        # ...then the framing: image models otherwise default to a medium portrait whatever the Camera block says.
        frame = "; ".join(x for x in (shot.get("framing"), shot.get("lens")) if x)
        frame = f"Framing (follow exactly): {frame.rstrip('.')}. " if frame else ""
        ident = ""
        if shot.get("performers") and full:    # who they are, not how they are drawn: the reference pictures are in another look
            ident = ("Same people as the reference images (" + ", ".join(shot["performers"]) + "): keep who they are (face shape, features, hair design, build, skin tone, outfit design) "
                     "and draw them entirely in this look: " + fig.rstrip(".") + ". "
                     "Do not copy how the reference pictures are drawn, lit or rendered. ")
        elif shot.get("performers"):  # identity up front too: close framings (hands, fragments) otherwise drift
            ident = "Same people as the reference images (" + ", ".join(shot["performers"]) + "): identical skin tone, face, hair and clothes. "
        body = f"{lead}. {frame}{ident}A single still, the first frame of this shot, in exactly that style: " + body
    elif not only and look["id"] not in ("auto", "custom"):          # a video model weighs its opening words most too: name the look first
        body = f"{look['prompt'].split(':')[0].rstrip('.')}. " + body
    blocks.append((10, body.strip()))
    if full:
        blocks.append((10, f"Whole-picture style, no exceptions: {look_name}. Everything in the frame is drawn this way, the characters' bodies, faces, hair and clothes included, not only the set and the background. "
                           "THIS IS THE MOST IMPORTANT RULE OF THE SHOT: IF THE CHARACTERS LOOK LIKE THEY BELONG TO A DIFFERENT STYLE FROM THE BACKGROUND, THE SHOT IS WRONG. "
                           "From the reference pictures take only who the people are and what the place contains: not their lighting, colour grade, depth of field, framing or rendering."))
    elif keep_cast:
        blocks.append((9, f"Only the setting is in this look ({look_name}); the characters keep their own rendering from the reference pictures."))
    if shot.get("performers") and not only:
        # Name AND describe them: with partial faces (hands, profiles, fragments) the name alone lets models drift.
        who = []
        locked_names = _locked_names(shot.get("locked_design"))
        for n in shot["performers"]:
            look_ = (_character(plan, n).get("appearance") or "").split(". ")
            who.append(f"{n} ({'. '.join(look_[:2]).rstrip('.')})" if look_[0] and n.lower() not in locked_names else n)
        blocks.append((9, "Characters: " + "; ".join(who) + "."))
    from .performance import direction as perf_direction
    perf = perf_direction(project, shot, video="duration" in roles)
    acting = acting_direction(shot, plan, perf and perf["play"])
    if acting and not custom:
        blocks.append((8, acting))
    if perf and perf.get("extra") and not custom:   # micro-animation for video; the matching expression for a still
        blocks.append((7, perf["extra"]))
    # A selected director style is optional and wins over the older all-in-one direction brief.
    # Its saved name is for the UI only; providers receive the bounded craft traits below.
    brief = ((project.get("director_style") or {}).get("traits") or project.get("direction_brief") or {}) if not custom else {}
    if brief and not only:                          # the filmmaker's approach the person applied (camera, light, rhythm, movement): traits only, in whatever look the film has
        bits = [f"{k}: {str(brief[k]).rstrip('.')}" for k in ("camera", "light", "movement", "editing") if brief.get(k) and brief.get(k) != "—"]
        if bits:
            blocks.append((7, "Directing approach (" + "; ".join(bits) + ")."))
    if not custom:                                  # the twelve principles of animation that fit this shot (animation_principles.py): a few, not all
        from . import animation_principles as AP
        craft = AP.direction(project, shot, look["id"], video="duration" in roles)
        if craft:
            blocks.append((6, craft))
    if custom:
        pass                                                    # your words say what happens: the shot's own timed acting, arc and business would compete with them
    elif "duration" in roles and shot.get("acting_beats"):        # the performance as timed moments: the most specific acting direction there is
        blocks.append((9, shot["acting_beats"]))
    elif "duration" not in roles and shot.get("acting_beats_pose"):
        blocks.append((8, shot["acting_beats_pose"]))
    if shot.get("arc_text") and not custom:
        blocks.append((7, shot["arc_text"]))
    if "duration" in roles and shot.get("business_text") and not custom:
        blocks.append((6, shot["business_text"]))
    if not custom:                                  # the Performance Director's lines: each is the first to go when the prompt is too long
        if shot.get("acting_nudges"):
            blocks.append((8, shot["acting_nudges"]))
        if "duration" in roles and shot.get("acting_carry"):
            blocks.append((8, shot["acting_carry"]))
        if shot.get("inner_text"):
            blocks.append((7, shot["inner_text"]))
        if shot.get("psychology_text"):
            blocks.append((5, shot["psychology_text"]))
        if shot.get("performance_text"):
            blocks.append((6, shot["performance_text"]))
    if shot.get("continuity") and not only:   # Continuity Director: blocking, 180-degree line, eyelines, wardrobe, light
        blocks.append((7, shot["continuity"]))
    if shot.get("locked_design"):   # canonical assets (e.g. from a Producer package)
        blocks.append((9, shot["locked_design"]))
    if shot.get("continuity_notes") and not only:   # the shot's own continuity requirements
        blocks.append((8, "Continuity for this shot: " + "; ".join(n.rstrip(".") for n in shot["continuity_notes"]) + "."))
    cam = [shot.get("framing"), shot.get("lens"), shot.get("camera_movement") or ", ".join(shot.get("camera_moves", []))]
    cam = [c for c in cam if c]
    if cam and not only:
        energy = f"; {shot['camera_energy']} energy" if shot.get("camera_energy") else ""
        blocks.append((7, "Camera: " + "; ".join(cam) + energy + "."))
    focus = "; ".join(x for x in (shot.get("focus"), shot.get("focus_motion") if "duration" in roles else None) if x)   # a rack focus needs time: video only
    if focus and not only:
        blocks.append((7, f"Focus: {focus.rstrip('.')}."))
    if shot.get("environment") and not only:
        blocks.append((5, f"Setting: {shot['environment'].rstrip('.')}."))
    if shot.get("lighting") and not only:
        blocks.append((6, f"Lighting: {shot['lighting'].rstrip('.')}."))
    if shot.get("wardrobe") and not only:
        blocks.append((6, f"Wardrobe: {shot['wardrobe'].rstrip('.')}."))
    blocks.append((9, f"Look: {look['prompt']}"))
    style_lock = SG.lock(project, look)
    if style_lock:
        blocks.append((SG.LOCK_PRIORITY, style_lock))         # dropped last of all, however long the prompt gets
    bib = project.get("bible") or {}   # Production Bible: the same world rules in every shot
    for key, weight, label in (("world", 6, "World"), ("rules", 8, "Always"), ("palette", 5, "Palette"), ("avoid", 8, "Never show")):
        v = SG.sanitize(for_this_shot(bible_text(bib.get(key)), shot, plan, project), project, look["id"])
        if v:
            blocks.append((weight, f"{label}: {v.rstrip('.')}."))
    if style:
        blocks.append((3, f"Mood and colour: {style}"))

    motion_refs = [r for r in refs if r.get("media") == "video"]
    audio_refs = [r for r in refs if r.get("media") == "audio"]
    refs = [r for r in refs if r.get("media", "image") == "image"]
    image_refs = refs[: fields[roles["ref_images"]].get("max_items") or len(refs)] if "ref_images" in roles else []
    if motion_refs and "ref_videos" in roles:
        blocks.append((7, "Motion references: " + "; ".join(r["label"] for r in motion_refs) + "."))
    if image_refs:
        ordinal = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]
        def _what(r: dict) -> str:
            label = _ref_label(r["label"], shot.get("locked_design"))
            if not full or r.get("endframe"):
                return label
            if r.get("kind") == "continuity":     # the shot before is in this look already when it was played in it: then it is the best reference there is
                return label if r.get("look") == look["id"] else label + " (use only its set layout and light; redraw everything in the new look)"
            return label + " (take what it shows, not how it is drawn)"
        tags = [f"{man['ref_syntax'].format(n=i + 1)} is the {_what(r)}" if man.get("ref_syntax")
                else f"the {ordinal[i] if i < len(ordinal) else str(i + 1) + 'th'} reference image is the {_what(r)}" for i, r in enumerate(image_refs)]
        close = (f"Take only each character's identity from them (face, hair, outfit design, skin tone), not their rendering style: redraw the characters in {look_name}." if full
                 else "Match the characters' faces, hair and wardrobe exactly.")
        blocks.append((9, "References: " + "; ".join(tags) + ". " + close))

    lip = bool(sung and "ref_audio" in roles and project.get("lip_sync", "auto") != "off")
    if lip:
        tag = "@Audio1" if man.get("ref_syntax") == "@Image{n}" else "the reference audio"
        lyric = " / ".join(sung.get("lyrics", []))
        verb = "speaks along to" if sung.get("spoken") or SPEAK_WORDS.search(" ".join(str(shot.get(k, "")) for k in ("beats", "performance", "movement"))) else "sings along to"
        turns = sung.get("turns") or []
        if len(turns) > 1:                                           # two or more people, one after the other, in the one audio clip: who speaks when, and the others listen
            when = "; then ".join(f"{t['speaker']} from {t['start']:.1f} to {t['end']:.1f} s" + (f" (\"{t['line']}\")" if str(t.get("line", "")).strip() else "") for t in turns)
            blocks.append((9, f"{sung['performer']} speak in turn, following {tag}: {when}. Only the person speaking moves their mouth; the others listen with their mouths closed, eyes on the speaker. "
                              f"Mouth shapes, breaths and phrasing follow the voice exactly; the performance is felt, not mimed."))
        else:
            blocks.append((9, f"{sung['performer']} {verb} {tag}" + (f": \"{lyric}\"" if lyric.strip() else "") + ". Mouth shapes, breaths and phrasing "
                              f"follow the voice exactly; the performance is felt, not mimed."))
    model_sound = bool(said and not lip and not native and roles.get("audio") and (overrides or {}).get(roles["audio"]) is True)   # the take's sound is switched on
    if said and not lip and not (native and "audio" in roles):
        what = "speaks" if said.get("spoken") else "voices"
        lines = " / ".join(said.get("lyrics", []))
        if model_sound:   # the model makes sound on this take: ask for the words themselves, not a hum (the recorded song still goes over it at export)
            say = "says" if said.get("spoken") else "sings"
            blocks.append((10, f"{said['performer']} {say}: \"{lines}\". The words are clearly voiced and the lips match each word exactly and in time; nobody else speaks. "
                               "No humming, no background music, and no subtitles, captions or written words appear."))
        else:
            blocks.append((9, f"{said['performer']} {what} these words in this shot: \"{lines}\". The lips and jaw shape each word clearly and in time, moving only while the words "
                          "are voiced, with the face and body acting them. The voice is added afterwards, so this video has no sound and no written words."))
    if native and "audio" in roles:
        # "Name says: "line"" (the colon and the quotes are what the models key on), one speaker at a time, short lines, no printed words
        said = " Then ".join(f"{x['who']} says{' ' + x['how'] if x.get('how') else ''}: \"{x['text']}\"" for x in native["lines"])
        turns = (" Each line is spoken only by the person named, in turn, while the others listen with their mouths closed."
                 if len({x["who"] for x in native["lines"]}) > 1 else "")
        blocks.append((10, f"Spoken dialogue, said aloud with the lips matching the words exactly: {said}.{turns} "
                           "A natural, restrained delivery. Only these words are spoken; nothing is sung, there is no background music, "
                           "and no subtitles, captions or written words appear."))
    if look["avoid"] and "negative_prompt" not in roles and not style_lock:      # a style lock already says it, and is never dropped
        blocks.append((4, f"Avoid: {look['avoid']}."))
    from . import anatomy as ANAT          # people in the shot: ask for correct hands and limbs (a stronger line when hands hold or touch)
    g = ANAT.guard(shot)
    if g and not only:
        blocks.append((g["priority"], g["text"]))
    from . import picturecare as PC        # natural skin, neutral colour, a clean image (and a warm look left alone): the habits of AI pictures, asked against in plain words
    pcare = PC.guard(shot, project, look.get("prompt", ""))
    if pcare and not only:
        blocks.append((pcare["priority"], pcare["text"]))
    from . import composition as COMP      # where people sit in the frame: thirds, headroom, look room (left out when a storyboard panel sets the composition)
    comp = COMP.line_for(shot, project, refs)
    if comp and not only:
        blocks.append((comp["priority"], comp["text"]))
    from . import dof as DOF               # the aperture-style depth of field the person chose for this shot
    dof = DOF.line(shot)
    if dof and not only:
        blocks.append((dof["priority"], dof["text"]))
    if shot.get("note"):
        blocks.append((10, "Direction for this take: " + str(shot["note"]).strip().rstrip(".") + "."))
    if shot.get("continues"):
        blocks.append((10, "This clip continues straight on from its first frame, which is the last frame of the clip before it: the same people, clothes, set, light and lens, no cut and no new framing. "
                           "Do not restart the action; carry it forward to its conclusion."))
    if fix_notes:
        blocks.append((10, "Corrections from review: " + " ".join(n.rstrip(".") + "." for n in fix_notes)))
    if "duration" not in roles:
        blocks.append((10, "One single continuous camera frame filling the whole image: not a collage, no panels, no split screen, "
                           "no inset portraits and no reference-sheet layout. If the shot describes several moments, show only its "
                           "first moment. A clean, uncluttered cinematic frame with nothing written anywhere in the image."))
    else:
        blocks.append((9, "No on-screen text, no subtitles, no watermark." + ("" if lip or model_sound or (native and "audio" in roles) else " Other performers do not lip-sync." if said else " Performers do not lip-sync.")))

    limit = (fields.get(roles.get("prompt", "prompt")) or {}).get("max_length") or known_prompt_limit(man.get("model", ""))
    keep = set(range(len(blocks)))
    drop_order = sorted(range(len(blocks)), key=lambda i: blocks[i][0])

    def text() -> str:
        return " ".join(blocks[i][1] for i in sorted(keep))

    # limits are in bytes for some providers: measure UTF-8 so curly quotes and accents can't push it over
    while limit and len(text().encode("utf-8")) > limit and drop_order:
        keep.discard(drop_order.pop(0))
    final = text()
    if trace is not None:
        trace[:] = [{"priority": blocks[i][0], "text": blocks[i][1], "kept": i in keep} for i in range(len(blocks))]
    while limit and len(final.encode("utf-8")) > limit:
        final = final[:-50]
    payload[roles.get("prompt", "prompt")] = final

    endframe = next((r["url"] for r in refs if r.get("endframe")), None)
    image_refs = [r for r in image_refs if not r.get("endframe")]
    if endframe and "last_frame" in roles:   # where the shot lands (frames.py); models without the input never get it
        payload[roles["last_frame"]] = endframe
    keyframe = next((r["url"] for r in refs if r.get("keyframe")), None)
    if keyframe and "first_frame" in roles:
        payload[roles["first_frame"]] = keyframe
        image_refs = [r for r in image_refs if not r.get("keyframe")]
    if image_refs and "ref_images" in roles and frames_only(man):
        f = fields[roles["ref_images"]]
        frames = ([keyframe] if keyframe else []) + ([endframe] if endframe and (frame_list_size(man) or f.get("max_items") or 1) > 1 else [])
        if frames:
            payload[f["name"]] = frames if f["type"] == "array" else frames[0]
        elif f.get("required"):          # a model that must have a first frame and has none yet: the first picture, as before
            payload[f["name"]] = [image_refs[0]["url"]] if f["type"] == "array" else image_refs[0]["url"]
    elif image_refs:
        f = fields[roles["ref_images"]]
        urls = [r["url"] for r in image_refs]
        payload[f["name"]] = urls if f["type"] == "array" else urls[0]
    elif refs and "first_frame" in roles and "first_frame" not in [k for k in roles if roles[k] in payload]:
        payload[roles["first_frame"]] = refs[0]["url"]
    if lip:
        f = fields[roles["ref_audio"]]
        payload[f["name"]] = [sung["url"]] if f["type"] == "array" else sung["url"]
    elif audio_refs and "ref_audio" in roles:
        f = fields[roles["ref_audio"]]
        payload[f["name"]] = [r["url"] for r in audio_refs] if f["type"] == "array" else audio_refs[0]["url"]
    if motion_refs and "ref_videos" in roles:
        f = fields[roles["ref_videos"]]
        payload[f["name"]] = [r["url"] for r in motion_refs] if f["type"] == "array" else motion_refs[0]["url"]
    if "duration" in roles:
        payload[roles["duration"]] = _duration_value(fields[roles["duration"]], shot["end"] - shot["start"])
    if "aspect_ratio" in roles:
        ar = project.get("aspect_ratio", "16:9")
        m = re.match(r"^([\d.]+):([\d.]+)$", ar)
        ratio = float(m.group(1)) / float(m.group(2)) if m else 16 / 9
        pick = _nearest_aspect(fields[roles["aspect_ratio"]].get("enum"), ratio)
        if pick:
            payload[roles["aspect_ratio"]] = pick
    size = fields.get("image_size")
    if size and "aspect_ratio" not in roles and set(size.get("enum") or []) & set(SIZE_PRESETS):
        ar = project.get("aspect_ratio", "16:9")
        m = re.match(r"^([\d.]+):([\d.]+)$", ar)
        want = float(m.group(1)) / float(m.group(2)) if m else 16 / 9
        options = [(abs(r - want), name) for name, r in SIZE_PRESETS.items() if name in size["enum"]]
        payload["image_size"] = min(options)[1]
    if fields.get("size", {}).get("flex") and "aspect_ratio" not in roles:     # GPT Image 2/2.5: the exact shape, not the nearest of three
        payload["size"] = flex_size(project.get("aspect_ratio", "16:9"), project.get("quality", "standard"))
    elif "size" in fields and fields["size"].get("enum") and "image_size" not in payload and "aspect_ratio" not in roles:
        ar = project.get("aspect_ratio", "16:9")
        m = re.match(r"^([\d.]+):([\d.]+)$", ar)
        want = float(m.group(1)) / float(m.group(2)) if m else 16 / 9
        dims = [(abs(int(e.split("x")[0]) / int(e.split("x")[1]) - want), e) for e in fields["size"]["enum"]
                if re.fullmatch(r"\d+x\d+", str(e))]
        if dims:
            payload["size"] = min(dims)[1]
    if "resolution" in roles:
        payload[roles["resolution"]] = _pick_quality(fields[roles["resolution"]], project.get("quality", "standard"))
    if man.get("provider") == "byteplus" and man["model"] in BYTEPLUS_MODELS:
        payload["size"] = byteplus_size(man["model"], project)           # BytePlus: the film's shape at the size the quality tier maps to
    payload.update(picture_size_plan(man, project)["payload"])          # High and Max: the largest picture size the model offers (its price is remembered under that size)
    if project.get("quality") == "max" and "bitrate_mode" in fields and "high" in (fields["bitrate_mode"].get("enum") or []):
        payload["bitrate_mode"] = "high"
    if "negative_prompt" in roles and (look["avoid"] or ANAT.guard(shot) or PC.enabled(project)):
        payload[roles["negative_prompt"]] = PC.negative(ANAT.negative(f"{look['avoid']}, text, subtitles, watermark" if look["avoid"] else "text, subtitles, watermark", shot), shot, project, look.get("prompt", ""))
    if "audio" in roles:   # the song is the master audio track (PRD §3), unless the model speaks this scene's lines itself
        payload[roles["audio"]] = bool(native)
    for k, v in (overrides or {}).items():  # Director Mode pins always win
        if k in fields:
            payload[k] = v
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------- providers

class Fal:
    name = "fal"

    def __init__(self):
        self.key = os.environ.get("FAL_KEY")
        if not self.key:
            raise SystemExit("Add your fal.ai key in Settings to render with fal.")
        self.h = {**UA, "Authorization": f"Key {self.key}", "Content-Type": "application/json"}

    def upload(self, path: str) -> str:
        import fal_client
        return fal_client.upload_file(path)

    def submit(self, model: str, payload: dict) -> dict:
        r = requests.post(f"https://queue.fal.run/{model}", json=payload, headers=self.h, timeout=60)
        _raise(r)
        j = r.json()
        return {"id": j["request_id"], "status_url": j.get("status_url"), "response_url": j.get("response_url")}

    def poll(self, model: str, rid: str, meta: dict | None = None) -> dict:
        base = f"https://queue.fal.run/{_fal_app(model)}/requests/{rid}"
        status_url = (meta or {}).get("status_url") or base + "/status"
        response_url = (meta or {}).get("response_url") or base
        s = http_get(status_url, headers=self.h)
        _raise(s)
        st = s.json()
        if st.get("status") != "COMPLETED":
            return {"state": "running", "detail": st.get("status", "").replace("_", " ").lower(),
                    "queue_position": st.get("queue_position")}
        r = http_get(response_url, headers=self.h, timeout=60)
        if r.status_code >= 400:
            return {"state": "failed", "error": _err_text(r)}
        url = _find_media_url(r.json())
        return {"state": "done", "url": url} if url else {"state": "failed", "error": "No video in the result."}


def _fal_app(model: str) -> str:
    # Queue status/result live under the app id: owner/app (first two path segments).
    return "/".join(model.split("/")[:2])


class Kie:
    name = "kie"
    base = "https://api.kie.ai/api/v1/jobs"

    def __init__(self):
        self.key = os.environ.get("KIE_KEY")
        if not self.key:
            raise SystemExit("Add your Kie.ai key in Settings to render with Kie.")
        self.h = {**UA, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def upload(self, path: str) -> str:
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f"data:{mime};base64," + base64.b64encode(f.read()).decode()
        r = requests.post("https://kieai.redpandaai.co/api/file-base64-upload", headers=self.h, timeout=120,
                          json={"base64Data": data, "uploadPath": "filmcrafter", "fileName": os.path.basename(path)})
        _raise(r)
        j = r.json()
        d = j.get("data", j)
        url = d.get("downloadUrl") or d.get("fileUrl") or d.get("url")
        if not url:
            raise RuntimeError(f"Kie upload returned no URL: {str(j)[:200]}")
        return url

    MJ = "https://api.kie.ai/api/v1/mj"

    def _mj_submit(self, payload: dict) -> dict:
        files = [u for u in (payload.get("image_urls") or []) if isinstance(u, str) and u]
        body = {"taskType": "mj_img2img" if files else "mj_txt2img", "prompt": payload.get("prompt", ""), "speed": payload.get("speed", "fast"),
                "aspectRatio": payload.get("aspect_ratio", "16:9"), "version": str(payload.get("version", "7")), "enableTranslation": False}
        if files:
            body["fileUrls"] = files
        for k in ("stylization", "weirdness", "variety"):
            if payload.get(k) not in (None, ""):
                body[k] = int(payload[k])
        r = requests.post(f"{self.MJ}/generate", json=body, headers=self.h, timeout=60)
        _raise(r)
        j = r.json()
        code, msg = j.get("code"), str(j.get("msg") or "")
        if isinstance(code, int) and 400 <= code < 500 and code not in (401, 402, 403, 429):
            raise RequestProblem(f"Kie.ai refused this Midjourney request, so nothing was charged. It said: {msg or 'invalid input'}")
        task = (j.get("data") or {}).get("taskId")
        if code not in (200, None) or not task:
            raise RuntimeError(msg or str(j)[:200])
        return {"id": task}

    def _mj_poll(self, rid: str) -> dict:
        r = http_get(f"{self.MJ}/record-info", params={"taskId": rid}, headers=self.h)
        _raise(r)
        d = r.json().get("data") or {}
        flag = d.get("successFlag")
        if flag == 1:
            info = d.get("resultInfoJson") or {}
            if isinstance(info, str):
                try:
                    info = json.loads(info)
                except ValueError:
                    info = {}
            urls = [(u.get("resultUrl") or u.get("url")) if isinstance(u, dict) else u for u in (info.get("resultUrls") or [])]
            urls = [u for u in urls if isinstance(u, str) and u]
            return {"state": "done", "url": urls[0], "cost": None, "cost_unit": "credits"} if urls else {"state": "failed", "error": "Midjourney finished but sent no picture."}
        if flag in (2, 3):
            return {"state": "failed", "error": d.get("errorMessage") or d.get("failMsg") or "Midjourney could not make this picture (it may have been refused by Midjourney's own filter)."}
        return {"state": "running", "detail": "generating", "progress": None}

    def submit(self, model: str, payload: dict) -> dict:
        if model in MJ_MODELS:
            return self._mj_submit(payload)
        r = requests.post(f"{self.base}/createTask", json={"model": model, "input": payload}, headers=self.h, timeout=60)
        _raise(r)
        j = r.json()
        code, msg = j.get("code"), str(j.get("msg") or "")
        if isinstance(code, int) and 400 <= code < 500 and code not in (401, 402, 403, 429):   # Kie checked the request and refused it: no task was made, nothing is billed
            m = re.search(r"([A-Za-z_]+)\s+supports at most (\d+) files?", msg)
            if m:
                learn_limit("kie", model, m.group(1), int(m.group(2)))
                raise RequestProblem(f"Kie.ai says {m.group(1)} takes at most {m.group(2)} picture{'s' if m.group(2) != '1' else ''} for this model, so nothing was charged. "
                                     "FilmCrafter has remembered that: press Send again.")
            raise RequestProblem(f"Kie.ai refused this request, so nothing was charged. It said: {msg or 'invalid input'}")
        if j.get("code") not in (200, None) or not (j.get("data") or {}).get("taskId"):
            raise RuntimeError(j.get("msg") or str(j)[:200])
        return {"id": j["data"]["taskId"]}

    def poll(self, model: str, rid: str, meta: dict | None = None) -> dict:
        if model in MJ_MODELS:
            return self._mj_poll(rid)
        r = http_get(f"{self.base}/recordInfo", params={"taskId": rid}, headers=self.h)
        _raise(r)
        d = r.json().get("data") or {}
        st = d.get("state")
        if st == "success":
            res = json.loads(d.get("resultJson") or "{}")
            urls = res.get("resultUrls") or []
            last = res.get("lastFrameUrl") or res.get("last_frame_url")       # present only when the request asked for it (return_last_frame)
            return {"state": "done", "url": urls[0] if urls else None, "cost": d.get("creditsConsumed"), "cost_unit": "credits",
                    **({"last_frame_url": last} if isinstance(last, str) and last.startswith("http") else {})} if urls else {"state": "failed", "error": "No video in the result."}
        if st == "fail":
            return {"state": "failed", "error": d.get("failMsg") or d.get("failCode") or "Generation failed."}
        return {"state": "running", "detail": st or "waiting", "progress": d.get("progress")}


class Google:
    """Gemini API: Veo (long-running) and Gemini image models (synchronous). Media goes inline as base64."""
    name = "google"
    base = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self):
        self.key = os.environ.get("GEMINI_API_KEY")
        if not self.key:
            raise SystemExit("Add your Google Gemini API key in Settings to render with Google.")
        self.h = {**UA, "x-goog-api-key": self.key, "Content-Type": "application/json"}

    def upload(self, path: str) -> str:
        # No upload service for these endpoints: keep a local reference and inline it at submit time.
        return "file:" + os.path.abspath(path)

    @staticmethod
    def _inline(ref: str) -> dict:
        path = ref[5:] if ref.startswith("file:") else ref
        mime = mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as f:
            return {"mimeType": mime, "data": base64.b64encode(f.read()).decode()}

    def submit(self, model: str, payload: dict) -> dict:
        if model.startswith("veo-"):
            inst: dict = {"prompt": payload.get("prompt", "")}
            if payload.get("image_url"):
                inst["image"] = {"inlineData": self._inline(payload["image_url"])}
            if payload.get("last_frame_url"):
                inst["lastFrame"] = {"inlineData": self._inline(payload["last_frame_url"])}
            if payload.get("reference_image_urls"):
                inst["referenceImages"] = [{"image": {"inlineData": self._inline(u)}, "referenceType": "asset"}
                                           for u in payload["reference_image_urls"][:3]]
            params = {k2: payload[k1] for k1, k2 in (("aspect_ratio", "aspectRatio"), ("resolution", "resolution"),
                                                      ("duration", "durationSeconds"), ("negative_prompt", "negativePrompt"),
                                                      ("person_generation", "personGeneration"), ("seed", "seed")) if payload.get(k1) not in (None, "")}
            r = requests.post(f"{self.base}/models/{model}:predictLongRunning", json={"instances": [inst], "parameters": params},
                              headers=self.h, timeout=120)
            _raise(r)
            return {"id": r.json()["name"]}
        # Image models answer immediately; keep the bytes until the runner downloads them.
        inputs = [{"type": "text", "text": payload.get("prompt", "")}]
        for u in payload.get("image_urls") or []:
            d = self._inline(u)
            inputs.append({"type": "image", "mime_type": d["mimeType"], "data": d["data"]})
        body = {"model": model, "input": inputs, "response_format": {"type": "image", "mime_type": "image/png",
                **({"aspect_ratio": payload["aspect_ratio"]} if payload.get("aspect_ratio") else {}),
                **({"image_size": payload["image_size"]} if payload.get("image_size") else {})}}
        r = requests.post(f"{self.base}/interactions", json=body, headers=self.h, timeout=300)
        _raise(r)
        j = r.json()
        it = j.get("interaction", j)
        data = (it.get("output_image") or {}).get("data") or next(
            (c.get("data") for st in it.get("steps", []) for c in st.get("content", []) if c.get("type") == "image" and c.get("data")), None)
        if not data:
            raise ProviderError("Google returned no image (it may have been blocked by safety filters).", 422)
        tmp = os.path.join(os.path.expanduser("~"), ".filmcrafter", "incoming")
        os.makedirs(tmp, exist_ok=True)
        path = os.path.join(tmp, f"{uuid.uuid4().hex}.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return {"id": "inline-" + os.path.basename(path), "file": path}

    def poll(self, model: str, rid: str, meta: dict | None = None) -> dict:
        if rid.startswith("inline-"):
            return {"state": "done", "url": "file:" + (meta or {}).get("file", "")}
        r = http_get(f"{self.base}/{rid}", headers=self.h)
        _raise(r)
        op = r.json()
        if not op.get("done"):
            return {"state": "running", "detail": "generating"}
        if op.get("error"):
            return {"state": "failed", "error": op["error"].get("message", "Generation failed.")}
        samples = ((op.get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or []
        uri = samples[0]["video"]["uri"] if samples else None
        return {"state": "done", "url": uri, "auth": True} if uri else {"state": "failed", "error": "No video returned (possibly blocked by safety filters)."}


from .comfy import ComfyUI  # noqa: E402  (comfy imports render lazily)


class OpenAIImages:
    """Keyframes from OpenAI's image models with your OpenAI key. Synchronous: the image comes back in the reply."""
    name = "openai"

    def __init__(self):
        self.key = os.environ.get("FILMCRAFTER_OPENAI_KEY")
        if not self.key:
            raise SystemExit("Add your OpenAI key in Settings to make keyframes with OpenAI.")
        self.h = {}

    def upload(self, path: str) -> str:
        return "file:" + os.path.abspath(path)

    def submit(self, model: str, payload: dict) -> dict:
        from openai import OpenAI
        client = OpenAI(api_key=self.key)
        refs = [u[5:] if u.startswith("file:") else u for u in payload.get("image_urls") or []]
        args = {"model": model, "prompt": payload.get("prompt", ""), "size": payload.get("size") or "1536x1024",
                "quality": payload.get("quality") or "high"}
        try:
            if refs:
                files = [open(p, "rb") for p in refs[:16]]
                try:
                    r = client.images.edit(image=files, **args)
                finally:
                    for f in files:
                        f.close()
            else:
                r = client.images.generate(**args)
        except Exception as e:
            status = getattr(e, "status_code", None)
            raise ProviderError(str(e), status or 500) from e
        data = r.data[0].b64_json if r.data else None
        if not data:
            raise ProviderError("OpenAI returned no image (it may have been blocked by its safety system).", 422)
        tmp = os.path.join(os.path.expanduser("~"), ".filmcrafter", "incoming")
        os.makedirs(tmp, exist_ok=True)
        path = os.path.join(tmp, f"{uuid.uuid4().hex}.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return {"id": "inline-" + os.path.basename(path), "file": path}

    def poll(self, model: str, rid: str, meta: dict | None = None) -> dict:
        return {"state": "done", "url": "file:" + (meta or {}).get("file", "")}

class BytePlusImages:
    """Keyframes from ByteDance's own Seedream models with your BytePlus ModelArk key. Synchronous: the picture comes back in the reply (base64), so no link has to be fetched before it expires."""
    name = "byteplus"

    def __init__(self):
        self.key = os.environ.get("BYTEPLUS_KEY")
        if not self.key:
            raise SystemExit("Add your BytePlus key in Settings to make keyframes with BytePlus.")
        self.h = {}

    def upload(self, path: str) -> str:
        return "file:" + os.path.abspath(path)

    @staticmethod
    def _as_image(ref: str) -> str:
        """A reference as BytePlus takes it: an https link as it is, a file as data:image/<format>;base64,... (the format in lower case)."""
        if ref.startswith("https://"):
            return ref
        if "://" in ref or ref.startswith("data:"):
            raise ProviderError("BytePlus takes a reference picture as a file or an https link only.", 400)
        path = ref[5:] if ref.startswith("file:") else ref
        from PIL import Image
        try:
            with Image.open(path) as im:
                fmt = (im.format or "PNG").lower()
                raw_ok = fmt in ("jpeg", "png", "webp", "bmp", "tiff", "gif", "heic", "heif") and os.path.getsize(path) <= 8 * 1024 * 1024
                if raw_ok:
                    with open(path, "rb") as fh:
                        data = fh.read()
                else:                                       # too large for one request, or a format it does not read: a JPEG copy
                    buf = io.BytesIO()
                    im.convert("RGB").save(buf, format="JPEG", quality=92)
                    data, fmt = buf.getvalue(), "jpeg"
        except (OSError, ValueError) as e:                  # a missing file, or one that is not a picture: nothing has been sent yet
            raise ProviderError("A reference picture could not be read, so nothing was sent.", 400) from e
        return f"data:image/{fmt};base64,{base64.b64encode(data).decode()}"

    def submit(self, model: str, payload: dict) -> dict:
        info = BYTEPLUS_MODELS.get(model)
        if not info:
            raise ProviderError(f"{model} is not a BytePlus picture model FilmCrafter knows.", 400)
        refs = [self._as_image(u) for u in (payload.get("image_urls") or [])[: info["refs"]]]
        body = {"model": model, "prompt": payload.get("prompt", ""), "size": payload.get("size") or "2048x2048", "response_format": "b64_json",
                "watermark": False, "sequential_image_generation": "disabled", "stream": False}
        if info["png"]:
            body["output_format"] = "png"                  # the 5.x models can; 4.x makes JPEG only
        if refs:
            body["image"] = refs[0] if len(refs) == 1 else refs
        try:
            r = requests.post(BYTEPLUS_URL, headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json", **UA}, json=body, timeout=300)
        except requests.Timeout as e:
            raise ProviderError("BytePlus did not answer in time. The picture may still have been made and billed: check your BytePlus usage before trying again.", 504) from e
        except requests.RequestException as e:
            raise ProviderError(f"Could not reach BytePlus ({type(e).__name__}).", 503) from e
        try:
            reply = r.json()
        except ValueError:
            reply = {}
        if r.status_code != 200:
            msg = ((reply.get("error") or {}).get("message") if isinstance(reply.get("error"), dict) else None) or (r.text or r.reason or "")[:300]
            raise ProviderError(f"BytePlus: {msg}", r.status_code)
        item = (reply.get("data") or [None])[0] or {}
        if isinstance(item.get("error"), dict):
            raise ProviderError("BytePlus: " + str(item["error"].get("message") or "the picture was refused"), 422)
        raw = base64.b64decode(item["b64_json"]) if item.get("b64_json") else None
        if raw is None and str(item.get("url") or "").startswith("https://"):
            raw = requests.get(item["url"], timeout=120).content
        if not raw:
            raise ProviderError("BytePlus returned no picture (it may have been blocked by its moderation).", 422)
        tmp = os.path.join(os.path.expanduser("~"), ".filmcrafter", "incoming")
        os.makedirs(tmp, exist_ok=True)
        ext = ".png" if raw[:4] == b"\x89PNG" else ".jpg"
        path = os.path.join(tmp, uuid.uuid4().hex + ext)
        with open(path, "wb") as fh:
            fh.write(raw)
        return {"id": "inline-" + os.path.basename(path), "file": path}

    def poll(self, model: str, rid: str, meta: dict | None = None) -> dict:
        return {"state": "done", "url": "file:" + (meta or {}).get("file", "")}


PROVIDERS = {"fal": Fal, "kie": Kie, "google": Google, "comfyui": ComfyUI, "openai": OpenAIImages, "byteplus": BytePlusImages}


class ProviderError(RuntimeError):
    def __init__(self, msg: str, status: int):
        super().__init__(msg)
        self.status = status


ERROR_KINDS = {
    "auth": "The provider rejected your API key. Check it in Settings.",
    "credits": "Your provider account is out of credits or needs billing set up.",
    "invalid": "The model didn't accept one of the settings.",
    "unavailable": "This model isn't available right now (renamed, retired or not enabled for your account).",
    "rate_limit": "The provider is busy or limiting requests. FilmCrafter will retry.",
    "timeout": "The provider took too long to respond.",
    "policy": "The provider's content filter blocked this request. Try rewording the shot.",
    "service": "The provider had an internal error.",
    "download": "The render finished but the file couldn't be downloaded.",
    "missing_input": "This model needs an input FilmCrafter can't supply automatically.",
    "expired_input": "A reference image had expired at the provider (nothing is charged for this). Retry: it is uploaded again.",
}


def classify_error(e: Exception | str, status: int | None = None) -> str:
    text = str(e).lower()
    status = status if status is not None else getattr(e, "status", None)
    if "could not be downloaded" in text or "publicly accessible url" in text or "failed to download" in text:
        return "expired_input"
    if any(k in text for k in ("safety", "policy", "nsfw", "moderation", "sensitive", "prohibited", "blocked by", "content filter")):
        return "policy"
    if status == 402 or any(k in text for k in ("insufficient", "balance", "credit", "quota", "billing", "payment",
                                                 "top_up", "top up", "topup", "user is locked", "exhausted", "add funds")):
        return "credits"
    if status in (401, 403) or "unauthorized" in text or "invalid api key" in text or "permission" in text:
        return "auth"
    if status == 404 or "not found" in text or "no such model" in text or "not available" in text:
        return "unavailable"
    if status == 429 or "rate limit" in text or "too many requests" in text:
        return "rate_limit"
    if status in (400, 422) or "validation" in text or "invalid" in text or "unsupported" in text:
        return "invalid"
    if isinstance(e, requests.Timeout) or "timed out" in text or "timeout" in text:
        return "timeout"
    if status and status >= 500:
        return "service"
    return "service"


def http_detail(e: Exception) -> tuple[str, int | None]:
    """The provider's own words and status from an HTTP error raised by a client library (httpx, requests)."""
    resp = getattr(e, "response", None)
    status = getattr(resp, "status_code", None)
    if resp is None or status is None:
        return str(e), None
    try:
        body = resp.text
    except Exception:
        body = ""
    return f"{status}: {(body or str(e))[:300]}", status


def describe_error(e: Exception | str, status: int | None = None) -> str:
    """One clear sentence for people, followed by the provider's own words for troubleshooting."""
    kind = classify_error(e, status)
    detail = str(e).strip()
    return f"{ERROR_KINDS[kind]} Provider said: {detail}" if detail else ERROR_KINDS[kind]


def _err_text(r: requests.Response) -> str:
    try:
        j = r.json()
        d = j.get("detail") or j.get("msg") or j.get("message") or j
        if isinstance(d, list):
            d = "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d)
        return f"{r.status_code}: {str(d)[:400]}"
    except ValueError:
        return f"{r.status_code}: {r.text[:300]}"


def _raise(r: requests.Response) -> None:
    if r.status_code >= 400:
        raise ProviderError(_err_text(r), r.status_code)


def _find_media_url(obj) -> str | None:
    if isinstance(obj, dict):
        for k in ("video", "videos", "output", "result"):
            if k in obj:
                u = _find_media_url(obj[k])
                if u:
                    return u
        if isinstance(obj.get("url"), str):
            return obj["url"]
        for v in obj.values():
            u = _find_media_url(v)
            if u:
                return u
    elif isinstance(obj, list):
        for v in obj:
            u = _find_media_url(v)
            if u:
                return u
    elif isinstance(obj, str) and obj.startswith("http") and re.search(r"\.(mp4|mov|webm)(\?|$)", obj):
        return obj
    return None


# ---------------------------------------------------------------- project job store

def _read(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path: str, data) -> None:
    """Atomic JSON write. Windows refuses to replace a file another process has open for a moment
    (the app reading jobs while the renderer saves), so retry briefly instead of failing."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    for i in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1) if i < 10 else 0.5)
    os.replace(tmp, path)


class _FileLock:
    """Cross-process lock for read-modify-write of a project file (renderer, review and the app's own calls)."""

    def __init__(self, path: str, timeout: float = 15.0):
        self.path, self.timeout, self.fd = path + ".lock", timeout, None

    def __enter__(self):
        start = time.time()
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode())
                return self
            except (FileExistsError, PermissionError) as e:
                if isinstance(e, PermissionError) and not os.path.exists(self.path):
                    # Windows: a lock file being deleted by its owner at this very instant refuses to be re-created with "permission denied" (the same "someone holds it" case).
                    if time.time() - start > self.timeout:
                        raise
                    time.sleep(0.03)
                    continue
                try:  # a lock left by a crashed process
                    if time.time() - os.path.getmtime(self.path) > 30:
                        os.remove(self.path)
                        continue
                except OSError:
                    pass
                if time.time() - start > self.timeout:
                    raise RuntimeError("The project's job list is busy. Try again in a moment.")
                time.sleep(0.03)

    def __exit__(self, *exc):
        os.close(self.fd)
        try:
            os.remove(self.path)
        except OSError:
            pass


class Store:
    """jobs.json shared by several processes. Every save merges this process's jobs (by id) into the file's
    current contents under a lock, so concurrent writers never undo each other's updates."""

    def __init__(self, project_dir: str):
        self.dir = project_dir
        self.path = os.path.join(project_dir, "jobs.json")
        self.data = _read(self.path, {"schema_version": 1, "jobs": []})

    @property
    def jobs(self) -> list[dict]:
        return self.data["jobs"]

    def _merge_save(self, only: dict | None = None, fields: dict | None = None) -> None:
        with _FileLock(self.path):
            disk = _read(self.path, {"schema_version": 1, "jobs": []})
            idx = {j["id"]: i for i, j in enumerate(disk["jobs"])}
            if only is not None and only["id"] in idx:
                # apply just the changed fields to the file's copy, then adopt it (other processes' fields survive)
                theirs = disk["jobs"][idx[only["id"]]]
                theirs.update(fields or {})
                only.clear()
                only.update(theirs)
            else:
                for j in ([only] if only is not None else self.data["jobs"]):
                    if j["id"] not in idx:
                        disk["jobs"].append(j)
                    elif j.get("updated", 0) >= disk["jobs"][idx[j["id"]]].get("updated", 0):
                        disk["jobs"][idx[j["id"]]] = j
            _write(self.path, disk)
        # keep our objects (the runner holds references to them) and pick up jobs other processes added
        have = {j["id"] for j in self.data["jobs"]}
        self.data["jobs"] += [j for j in disk["jobs"] if j["id"] not in have]

    def save(self) -> None:
        self._merge_save()

    def update(self, job: dict, **kw) -> None:
        kw = {**kw, "updated": int(time.time())}
        job.update(kw)
        self._merge_save(job, kw)
        emit(event="job", job=job)


def _load_plan(d: str) -> tuple[str, dict]:
    for name in ("directed", "production"):
        p = _read(os.path.join(d, f"{name}.json"), None)
        if p:
            return name, p
    raise SystemExit("This project has no shot plan yet.")


def _shot(plan: dict, shot_id: str) -> tuple[dict, dict]:
    for sc in plan["scenes"]:
        for sh in sc["shots"]:
            if sh["id"] == shot_id:
                return sh, sc
    raise SystemExit(f"Shot {shot_id} not found.")


def _reference_files(d: str, project: dict, shot: dict | None = None, scene: dict | None = None) -> list[dict]:
    """The shot's references from the reference library (project -> scene -> shot, plus its performers)."""
    from . import library
    return library.reference_files(d, project, shot, (scene or {}).get("number"))


def _legacy_reference_files(d: str, project: dict, shot: dict | None = None) -> list[dict]:
    """Reference images for a shot: a clean image per performer when the project has them (so only the
    people in the shot are sent, without sheet text to copy), else the whole character sheet; then the set sheet."""
    refs = project.get("references") or {}
    out = []
    cast = refs.get("cast") or {}
    people = (shot or {}).get("performers") or []
    picked = [n for n in people if cast.get(n) and os.path.exists(os.path.join(d, cast[n]))]
    if picked:
        for n in picked:
            out.append({"label": f"reference for {n} (face, expressions, full-body turnaround)", "path": os.path.join(d, cast[n])})
    elif refs.get("characters") and os.path.exists(os.path.join(d, refs["characters"])):
        out.append({"label": "character sheet (faces, turnarounds, outfits)", "path": os.path.join(d, refs["characters"])})
    if refs.get("sets") and os.path.exists(os.path.join(d, refs["sets"])):
        out.append({"label": "set and props sheet (locations, props, colour palette)", "path": os.path.join(d, refs["sets"])})
    return out


def _still_there(url: str) -> bool:
    """A free check that an uploaded file can still be downloaded (a failed check means: upload again)."""
    try:
        r = requests.head(url, timeout=10, allow_redirects=True, headers=UA)
        return r.status_code < 400
    except requests.RequestException:
        return False


MAX_UPLOAD_SIDE = 3840


def _upload_size(d: str, path: str) -> str:
    """Images larger than 3840 px on a side are sent as a scaled copy (cached); everything else as is."""
    if os.path.splitext(path)[1].lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        return path
    try:
        from PIL import Image
        with Image.open(path) as im:
            if max(im.size) <= MAX_UPLOAD_SIDE:
                return path
            out = os.path.join(d, "cache", "upload-sized", f"{_sha1((path + str(os.path.getmtime(path))).encode()).hexdigest()[:12]}.jpg")
            if not os.path.exists(out):
                os.makedirs(os.path.dirname(out), exist_ok=True)
                im = im.convert("RGB")
                im.thumbnail((MAX_UPLOAD_SIDE, MAX_UPLOAD_SIDE))
                im.save(out, quality=94)
            return out
    except Exception:
        return path


ACCEPTED_IMAGES = (".png", ".jpg", ".jpeg", ".webp")
CONVERTIBLE_IMAGES = (".gif", ".bmp", ".tif", ".tiff", ".avif", ".jfif", ".ico")


def _plain_reference(d: str, f: dict) -> dict | None:
    """An image reference in a type the providers accept. PNG, JPEG and WebP go as they are; other pictures (GIF, BMP, TIFF...)
    become a PNG copy; a text-sign SVG (what a Producer package makes for signs and charts) is drawn as a PNG; anything else
    (a PDF, a complex SVG, a broken file) returns None so it is left out instead of failing the whole render. Cached copies sit in
    the project's cache folder; the original is never changed."""
    if f.get("media", "image") != "image":
        return f
    path = f["path"]
    ext = os.path.splitext(path)[1].lower()
    if ext in ACCEPTED_IMAGES:
        return f
    out = os.path.join(d, "cache", "refs", f"{_sha1((path + str(os.path.getmtime(path))).encode()).hexdigest()[:12]}.png")
    try:
        if not os.path.exists(out):
            if ext == ".svg":
                from .svg_text import to_png
                to_png(path, out)
            elif ext in CONVERTIBLE_IMAGES:
                from PIL import Image
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with Image.open(path) as im:
                    im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(out + ".part.png")
                os.replace(out + ".part.png", out)
            else:
                return None
    except Exception:
        return None
    return {**f, "path": out}


def _uploaded(d: str, provider, files: list[dict]) -> list[dict]:
    """Upload reference images once per provider; reuse URLs until they are close to expiring."""
    cache_path = os.path.join(d, "cache", "uploads.json")
    cache = _read(cache_path, {})
    # Kie deletes temporary uploads after about a day (seen 404 at ~26 h): reuse for 12 h at most
    ttl = 12 * 3600 if provider.name == "kie" else 6 * 86400
    out, skipped = [], []
    for f in files:
        g = _plain_reference(d, f)
        if g is None:
            skipped.append(os.path.basename(f["path"]))
            continue
        f = {**g, "path": _upload_size(d, g["path"])}
        with open(f["path"], "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()[:16]
        key = f"{provider.name}:{digest}"
        hit = cache.get(key)
        if hit and time.time() - hit["at"] > 3600 and not _still_there(hit["url"]):
            hit = None   # the provider already removed it: upload again rather than send a dead link
        if not hit or time.time() - hit["at"] > ttl:
            emit(event="progress", stage=f"uploading {os.path.basename(f['path'])}")
            hit = {"url": provider.upload(f["path"]), "at": int(time.time())}
            cache[key] = hit
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            _write(cache_path, cache)
        out.append({"label": f["label"], "url": hit["url"], "media": f.get("media", "image"), "kind": f.get("kind")})
    if skipped:
        emit(event="progress", stage=f"left out {len(skipped)} reference{'s' if len(skipped) != 1 else ''} image models can't read "
                                     f"({', '.join(skipped[:3])}{'…' if len(skipped) > 3 else ''}); use PNG, JPEG or WebP")
    return out


# ---------------------------------------------------------------- lip-sync audio

SING_WORDS = re.compile(r"\b(sing|sings|singing|sung|vocal|lip|mouths?|chorus|verse|lyric|calls?|calling|says?|saying|shouts?|shouting|speaks?|speaking|announces?|"
                       r"proclaims?|exclaims?|cries|cry|commands?|orders?|declares?|demands?|project(?:s|ing)? (?:her|his|their) voice|mouth open)", re.I)


SPEAK_WORDS = re.compile(r"\b(calls?|calling|says?|saying|shouts?|speaks?|speaking|announces?|proclaims?|exclaims?|declares?|demands?|orders?|commands?)\b", re.I)


def _belongs(line: dict, shot: dict) -> bool:
    """A lyric line is this shot's when a real part of it is heard under the shot: at least 0.3 s, or half of the line. A line that only starts in the
    last fraction of a second belongs to the next shot (asking a 1-second shot to voice it as well would squeeze two lines into nothing)."""
    start, end = float(line["start"]), float(line.get("end") or line["start"])
    over = min(end, shot["end"]) - max(start, shot["start"])
    return over >= 0.3 or over >= 0.5 * max(end - start, 0.01)


NOT_FRAMED = re.compile(r"wide|establishing|aerial|insert|detail|silhouette|from behind|over the shoulder of|\bels?\b|\bws\b", re.I)
FRAMED = re.compile(r"medium|close|two-shot|waist|chest|portrait|\bcu\b|\bmcu\b|\bms\b", re.I)


def _mouth_visible(shot: dict, lines: list[dict]) -> bool:
    """A lyric nobody is named for, heard under a medium or closer shot with a performer in it: the performer is taken to be voicing it even when the shot's
    own wording never says "sings" (a mother's hand on her son's cheek during her chorus). A wide or insert shot is not assumed to show a mouth."""
    heard = sum(max(0.0, min(float(l.get("end") or l["start"]), shot["end"]) - max(float(l["start"]), shot["start"])) for l in lines)
    framing = f"{shot.get('framing', '')} {shot.get('lens', '')}"
    return heard >= 1.0 and bool(FRAMED.search(framing)) and not NOT_FRAMED.search(framing)


def _vocal_heard(d: str, shot: dict) -> float:
    """Seconds of sung or spoken words under the shot, whoever sings them."""
    lines = ((_read(os.path.join(d, "songmap.json"), {}) or {}).get("lyrics") or [])
    return sum(max(0.0, min(float(l.get("end") or l["start"]), shot["end"]) - max(float(l["start"]), shot["start"])) for l in lines if l.get("start") is not None)


def sing_setting(d: str, shot_id: str | None) -> str:
    """What the person said about this shot: "on" (someone on screen sings this vocal), "off" (nobody on screen does: it is a narrator, a voice-over, a memory) or "auto" (the default).
    Chosen per shot on the Video tab; kept in project.json as sing_shots."""
    try:
        v = ((_read(os.path.join(d, "project.json"), {}) or {}).get("sing_shots") or {}).get(shot_id or "")
    except AttributeError:
        return "auto"
    return v if v in ("on", "off") else "auto"


def singing(d: str, shot: dict, plan: dict) -> dict | None:
    """If a performer sings in this shot, the lyric lines under it and who sings them.

    Lyrics nobody is named for are assumed to be sung by the lead, when the lead is on screen in a medium or closer shot (or the shot's own words say someone sings, calls or speaks). A
    shot that shows someone else (the lead as a child, a crowd) is not assumed to sing: that is usually a narrator over a memory, and a mouth synced to a voice that is not theirs looks wrong.
    The person has the last word: a shot marked "on" always sings, "off" never does, and a project whose vocalist is off screen (`vocalist: "offscreen"`) sings nowhere unless a shot is marked "on"."""
    from . import voiceover
    mine = voiceover.for_shot(d, shot.get("id", ""))
    if mine and sing_setting(d, shot.get("id")) != "off":      # the person's own recording is the voice of this shot: it is followed, whatever the song or the model would do
        names = [r["speaker"] for r in mine]
        return {"performer": names[0] if len(names) == 1 else " and ".join(names), "lyrics": [r["line"] for r in mine if r.get("line")] or [""], "spoken": True, "voiceover": True,
                **({"turns": voiceover.windows(d, shot.get("id", ""))} if len(mine) > 1 else {})}
    if (_read(os.path.join(d, "project.json"), {}) or {}).get("film"):
        return None          # a film has no song to follow: without a recording of its own the mouth follows the words in the picture (the old path sent the film's soundtrack, often silence, as "the voice")
    song_map = _read(os.path.join(d, "songmap.json"), {}) or {}
    lines = [l for l in song_map.get("lyrics", []) if l.get("start") is not None
             and l["start"] < shot["end"] and (l.get("end") or l["start"]) > shot["start"]]
    lines = [l for l in lines if _belongs(l, shot)]
    if not lines or not shot.get("performers"):
        return None
    chosen = sing_setting(d, shot.get("id"))
    if chosen == "off":
        return None
    spoken = [l for l in lines if l.get("performer") in shot["performers"]]
    if spoken:   # a spoken scene: who says each line is known exactly, so the speaker is lip-synced
        return {"performer": spoken[0]["performer"], "lyrics": [l["text"] for l in spoken], "spoken": True}
    if any(l.get("performer") for l in lines):
        return None   # someone off-screen is talking
    lead = (plan.get("characters") or [{}])[0].get("name")
    if chosen != "on":
        if ((_read(os.path.join(d, "project.json"), {}) or {}).get("vocalist") == "offscreen"):
            return None
        text = " ".join(str(shot.get(k, "")) for k in ("visual_prompt", "performance", "movement", "description")) + " ".join(shot.get("beats", []))
        if lead and lead not in shot["performers"]:
            if not SING_WORDS.search(text):
                return None                                   # the lead is not in this shot and nothing says anyone here sings
        elif not SING_WORDS.search(text) and not _mouth_visible(shot, lines):
            return None
    singer = lead if lead in shot["performers"] else shot["performers"][0]
    return {"performer": singer, "lyrics": [l["text"] for l in lines]}


NATIVE_DELIVERY = {"happy": "cheerfully", "sad": "sadly", "angry": "angrily", "fearful": "fearfully", "disgusted": "with disgust", "surprised": "in surprise"}


def native_mode(d: str) -> bool:
    """A spoken scene whose lines the video model speaks itself (set in the scene's dialogue editor)."""
    return bool((_read(os.path.join(d, "dialogue.json"), {}) or {}).get("native"))


def native_lines(d: str, shot: dict) -> list[dict]:
    """The spoken lines under this shot in a native-dialogue scene: [{"who", "text"}], in order. Empty for a shot with nobody speaking."""
    if not native_mode(d):
        return []
    lyrics = (_read(os.path.join(d, "songmap.json"), {}) or {}).get("lyrics", [])
    emotion = {(x.get("character"), " ".join(str(x.get("text", "")).split())): x.get("emotion")
               for x in (_read(os.path.join(d, "dialogue.json"), {}) or {}).get("lines", [])}
    out = []
    for l in lyrics:
        if l.get("performer") and l.get("start") is not None and l["start"] < shot["end"] and (l.get("end") or l["start"]) > shot["start"]:
            text = " ".join(str(l["text"]).split())
            out.append({"who": str(l["performer"]), "text": text.replace('"', "'"), "how": NATIVE_DELIVERY.get(emotion.get((l["performer"], text)) or "", "")})
    return out


def native_for(d: str, shot: dict, man: dict) -> dict | None:
    """What the model is asked to say in this shot, or None (not a native scene, no one speaks here, or the model makes no sound)."""
    from . import voiceover
    if voiceover.for_shot(d, shot.get("id", "")):                # a recording is attached: the model is not asked to speak, the recording is followed
        return None
    lines = native_lines(d, shot)
    return {"lines": lines} if lines and "audio" in man["roles"] else None


def native_problem(d: str, shot: dict, man: dict) -> str | None:
    """A shot where someone speaks, in a native scene, can only be made by a model that makes its own sound."""
    if native_lines(d, shot) and "audio" not in man["roles"]:
        return (f"{man['title']} makes no sound of its own, and this scene's dialogue is spoken by the video model. Choose a model that makes "
                "sound (for example Veo 3.1 or Kling 2.6), or turn native dialogue off for this scene.")
    return None


def _vocal_stem(d: str) -> str | None:
    """Isolated vocals from song analysis (Demucs), if available."""
    stems = os.path.join(d, "cache", "stems", "htdemucs")
    if os.path.isdir(stems):
        for sub in os.listdir(stems):
            v = os.path.join(stems, sub, "vocals.wav")
            if os.path.exists(v):
                return v
    return None


CLOSE = re.compile(r"close|tight|\bcu\b|ecu|mcu|portrait|head and shoulders", re.I)


def is_closeup(shot: dict) -> bool:
    return bool(CLOSE.search(f"{shot.get('framing', '')} {shot.get('lens', '')}"))


def wants_lipsync_pass(d: str, project: dict, plan: dict, shot: dict) -> bool:
    """Project rule 'closeups': singing close-ups get a dedicated lip-sync pass after rendering."""
    return project.get("lip_sync") == "closeups" and is_closeup(shot) and bool(singing(d, shot, plan)) and not native_mode(d)


def _lipsync_provider() -> str | None:
    return "fal" if os.environ.get("FAL_KEY") else "kie" if os.environ.get("KIE_KEY") else None


def song_slice(d: str, shot: dict, seconds: float, vocals_only: bool = False) -> str:
    """The exact piece of the song under this shot as a small mp3 (full mix, or the isolated vocal)."""
    import subprocess
    from .export import NO_WINDOW, ffmpeg
    project = _read(os.path.join(d, "project.json"), {})
    src = (_vocal_stem(d) if vocals_only else None) or os.path.join(d, project.get("song", "song.wav"))
    out_dir = os.path.join(d, "cache", "lipsync")
    os.makedirs(out_dir, exist_ok=True)
    tag = "vox" if src != os.path.join(d, project.get("song", "song.wav")) else "mix"
    from .safe import file_part
    out = os.path.join(out_dir, f"{file_part(shot['id'])}_{shot['start']:.3f}_{seconds:.2f}_{tag}.mp3")
    if not os.path.exists(out):
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{shot['start']:.3f}", "-t", f"{seconds:.3f}",
                        "-i", src, "-ac", "2", "-b:a", "192k", out], check=True, creationflags=NO_WINDOW)
    return out


def take_duration(path: str) -> float:
    import subprocess
    from .export import NO_WINDOW, ffmpeg
    err = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True, creationflags=NO_WINDOW).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def compile_lipsync(d: str, man: dict, shot: dict, source: dict, overrides: dict | None) -> dict:
    """Lip-sync pass request: the source take plus the sound to follow, same length: the person's own recording of the shot when there is one, else the isolated vocal under the shot."""
    roles = man["roles"]
    if "src_video" not in roles or "src_audio" not in roles:
        raise SystemExit(f"{man['title']} doesn't take a video and an audio track, so it can't lip-sync a take.")
    take = os.path.join(d, source["output"])
    seconds = take_duration(take) or (shot["end"] - shot["start"])
    from . import voiceover
    mine = voiceover.for_shot(d, shot.get("id", ""))                    # the person's own recording is what the mouth is re-timed to, when there is one
    audio = voiceover.slice_for(d, shot["id"], seconds) if mine else song_slice(d, shot, seconds, vocals_only=True)
    payload = {roles["src_video"]: PROJECT_MEDIA + source["output"],
               roles["src_audio"]: PROJECT_MEDIA + os.path.relpath(audio, d).replace(os.sep, "/")}
    fields = {f["name"]: f for f in man["inputs"]}
    if "sync_mode" in fields:
        payload["sync_mode"] = "cut_off"
    if "separate_vocal" in fields and not mine and not _vocal_stem(d):    # a clean recording has nothing to separate; a song may
        payload["separate_vocal"] = True
    elif "separate_vocal" in fields and mine:
        payload["separate_vocal"] = False
    mode = fields.get("mode")
    if mode and "basic" in (mode.get("enum") or []):   # Kie / Volcengine: "lite" is for one person facing the camera; "basic" copes with other scenes and finds who is speaking
        one_face = len(shot.get("performers") or []) <= 1 and is_closeup(shot)
        payload["mode"] = "lite" if one_face else "basic"
        if payload["mode"] == "basic" and "open_scenedet" in fields:
            payload["open_scenedet"] = True
    for k, v in (overrides or {}).items():
        if k in fields:
            payload[k] = v
    return fill_required(man, payload, [])   # any other required setting gets the model's own default


def enqueue(d: str, shot_ids: list[str], provider: str, model: str | None, overrides: dict | None,
            fix_notes: list[str] | None = None, kind: str = "video", source_job: str | None = None) -> list[dict]:
    project = _read(os.path.join(d, "project.json"), {})
    plan_name, plan = _load_plan(d)
    model = model or default_model(provider, kind)
    if kind == "lipsync":
        src = next((j for j in Store(d).jobs if j["id"] == source_job and j["state"] == "ready" and j.get("output")), None)
        if not src:
            raise SystemExit("Choose a finished take to lip-sync.")
    man = manifest(provider, model)
    if kind in ("video", "image") and (man.get("caps") or {}).get("kind") == "lipsync":
        # a lip-sync model asked to draw a shot: it would be queued, fail, and look like nothing happened. (Only lip-sync models are recognised for certain: a video model with no
        # duration setting looks like a picture model, so that distinction is not enforced here.)
        raise SystemExit(f"{man.get('title') or model} makes a lip-synced version of a take that already exists, so it can't {'render a shot as video' if kind == 'video' else 'make a keyframe'}. Choose {'a video' if kind == 'video' else 'an image'} model.")
    from .routing import guard   # Local First refuses paid cloud work; a project budget refuses a batch that won't fit
    guard(d, shot_ids, provider, man["model"], kind)
    store = Store(d)
    made = []
    overrides = dict(overrides or {})
    motion = overrides.pop("_motion", None)               # compose.py: a motion-control take (character picture + motion video)
    refs_only = bool(overrides.pop("_refs_only", False))  # compose.py: pictures as references, no start frame
    note = str(overrides.pop("_note", "") or "").strip()[:600]   # compose.py: one line of direction for this take
    custom_prompt = str(overrides.pop("_prompt", "") or "").strip()[:4000]   # compose.py: the filmmaker's own words for what happens
    prompt_only = bool(overrides.pop("_prompt_only", False))
    extend_of, extend_s = overrides.pop("_extend_of", None), overrides.pop("_extend_seconds", None)   # extend.py: a continuation from this take's last frame
    variants = max(1, min(4, int(overrides.pop("_variants", 1)))) if kind == "image" else 1   # keyframe options to choose from
    frame_kind = overrides.pop("_frame", "start") if kind == "image" else "start"   # "end": stills for where the shot lands
    hand_fix = overrides.pop("_hand_fix", None) if kind == "image" else None         # handfix.py: redraw one part of the keyframe (the crop is the only reference)
    swap_in = overrides.pop("_swap_in", None)                                         # keyframeset.py: a new keyframe that waits beside the old until it is used
    for sid in [s for s in shot_ids for _ in range(variants)]:
        if not hand_fix and sum(1 for j in store.jobs if j["shot_id"] == sid and j["plan"] == plan_name and j["provider"] == provider
               and j["model"] == man["model"] and j.get("kind", "video") == kind and j.get("frame", "start") == frame_kind
               and j["state"] in ACTIVE) >= variants:
            continue  # never double-queue the same shot on the same model (side-by-side comparisons are fine)
        shot, scene = _shot(plan, sid)
        size_key = picture_size_plan(man, project)["key"] if kind == "image" else ""       # a bigger picture costs more: the job says which size it asks for
        if not (shot.get("visual_prompt") or shot.get("beats") or shot.get("description")):
            # a shot cut from the song alone has no picture described yet; never pay to render a blank prompt
            emit(event="progress", stage=f"{sid} has no description yet, skipped")
            continue
        if _read(os.path.join(d, "shots.json"), {}).get(sid, {}).get("locked"):
            emit(event="progress", stage=f"{sid} is locked, skipped")
            continue
        model_id, extra = man["model"], {}
        job_over = overrides
        if kind == "video" and motion:
            if len(shot_ids) != 1:
                raise SystemExit("Motion control is one shot at a time.")
            if not is_motion_model(man["model"]):
                raise SystemExit(f"{man.get('title') or man['model']} isn't a motion-control model.")
            for key in ("video", "image"):
                if not (isinstance(motion.get(key), str) and os.path.isfile(os.path.join(d, motion[key]))):
                    raise SystemExit("The " + ("motion video" if key == "video" else "character picture") + " for this take is missing from the project.")
            extra = {"motion": {k: motion.get(k) for k in ("video", "image", "orientation", "quality", "background", "note") if motion.get(k) not in (None, "")}}
        elif kind == "video" and extend_of:
            if len(shot_ids) != 1:
                raise SystemExit("Extend one shot at a time.")
            take = next((x for x in store.jobs if x["id"] == extend_of and x["shot_id"] == sid and x["state"] == "ready" and x.get("output")), None)
            if not take:
                raise SystemExit("The take to extend is gone or isn't finished.")
            dfield = next((f for f in man["inputs"] if f["name"] == (man["roles"] or {}).get("duration")), None)
            if not dfield:
                raise SystemExit("This model has no length setting, so it can't make a continuation.")
            job_over = {**overrides, dfield["name"]: _duration_value(dfield, max(0.5, float(extend_s or 4)) - 0.5)}
            extra = {"extend_of": extend_of}
            from . import library
            if not library.shot_state(d).get(sid, {}).get("approved"):   # the take in the video stays in the video until you swap the longer one in
                library.approve(d, sid, extend_of)
        elif kind == "video":
            from . import frames
            end = frames.end_ref(d, plan_name, plan, sid)
            if end:
                m = frames.model_for(provider, man["model"], True)
                model_id = m["model"]
                extra = {"end_frame": end, "end_supported": m["supports_end"], **({"swapped_from": man["model"]} if m["swapped"] else {})}
                if any(j["shot_id"] == sid and j["plan"] == plan_name and j["provider"] == provider and j["model"] == model_id
                       and j.get("kind", "video") == kind and j["state"] in ACTIVE for j in store.jobs):
                    continue
        if frame_kind == "end":
            extra["frame"] = "end"
        if hand_fix:
            extra["hand_fix"] = hand_fix
        if swap_in:
            extra["swap_in"] = str(swap_in)[:20]
        job = {"id": uuid.uuid4().hex[:12], "shot_id": sid, "plan": plan_name, "source_shots": shot.get("source_shots", []),
               "shot_start": shot["start"], "shot_end": shot["end"], "provider": provider, "model": model_id,
               "kind": kind, "source_job": source_job, "overrides": job_over or {}, "fix_notes": fix_notes or [], **({"refs_only": True} if refs_only else {}), **({"note": note} if note else {}), **({"custom_prompt": custom_prompt, "prompt_only": prompt_only} if custom_prompt else {}), "look": resolve_look(project, (scene or {}).get("number"), sid)["id"], **({"size_key": size_key} if size_key else {}), "state": "queued", "provider_job_id": None, "attempts": 0,
               "created": int(time.time()), "updated": int(time.time()), "output": None, "error": None, "cost": None, **extra}
        store.jobs.append(job)
        made.append(job)
    store.save()
    for j in made:
        emit(event="job", job=j)
    return made


def run(d: str, poll_every: float = 6.0) -> None:
    """Drive every active job to completion. Safe to start again after a crash or restart."""
    store = Store(d)
    lock = os.path.join(d, "cache", "render.lock")
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    if os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 60:
        emit(event="progress", stage="another renderer is already running for this project")
        return
    project = _read(os.path.join(d, "project.json"), {})
    providers: dict[str, object] = {}
    paused: set[str] = set()  # providers that said "out of credits" this run

    def prov(name):
        if name not in providers:
            providers[name] = PROVIDERS[name]()
        return providers[name]

    run_started = int(time.time())
    for j in store.jobs:  # crash recovery: a submit that never recorded its id may or may not exist remotely
        if j["state"] == "submitting":
            store.update(j, state="uncertain",
                         error="The app closed while this shot was being sent. It may already be rendering "
                               "(and billed). Check your provider dashboard before retrying.")
    try:
        while True:
            with open(lock, "w") as f:
                f.write(str(os.getpid()))
            active = [j for j in store.jobs if j["state"] in ACTIVE
                      and not (j["state"] == "queued" and j["provider"] in paused)]
            if not active:
                if any(j["state"] == "queued" for j in store.jobs):
                    emit(event="progress", stage="paused: " + ", ".join(sorted(paused)) + " needs a top-up; the rest stay queued")
                break
            for j in active:
                try:
                    p = prov(j["provider"])
                    if j["state"] == "queued":
                        _submit(d, store, project, p, j)
                    elif j["state"] == "submitted":
                        _check(d, store, p, j)
                except SystemExit as e:  # missing key, unknown model, ...
                    msg = str(e)
                    kind = "auth" if "key" in msg.lower() else "unavailable" if "not found" in msg.lower() or "schema" in msg.lower() else "invalid"
                    store.update(j, state="failed", error=msg, error_kind=kind)
                except ProviderError as e:
                    if j["state"] == "submitting":
                        if e.status == 429:  # rate-limited = not accepted: safe to send again later
                            store.update(j, state="queued", error=None, attempts=max(0, j["attempts"] - 1))
                            emit(event="progress", stage=f"{j['shot_id']}: provider busy, will retry")
                            continue
                        if e.status >= 500:  # the provider may or may not have accepted it
                            store.update(j, state="uncertain", error=describe_error(e), error_kind="service")
                            continue
                        if classify_error(e) == "credits":  # refused, not billed: keep it and everything after it queued
                            paused.add(j["provider"])
                            store.update(j, state="queued", error=describe_error(e), error_kind="credits",
                                         attempts=max(0, j["attempts"] - 1))
                            emit(event="progress", stage=f"{j['provider']} is out of credits: rendering paused")
                            continue
                        store.update(j, state="failed", error=describe_error(e), error_kind=classify_error(e))
                        continue
                    if e.status in (429, 500, 502, 503, 504):
                        emit(event="progress", stage=f"{j['shot_id']}: provider busy, will retry")
                        continue
                    store.update(j, state="failed", error=describe_error(e), error_kind=classify_error(e))
                except requests.RequestException as e:  # network blip: keep the job, try next round
                    emit(event="progress", stage=f"{j['shot_id']}: network issue ({type(e).__name__}), retrying")
                    if j["state"] == "submitting":
                        store.update(j, state="uncertain", error=f"Lost connection while sending: {e}", error_kind="timeout")
                    elif j["state"] == "submitted" and "download" in str(e).lower():
                        store.update(j, error=describe_error(e), error_kind="download")
                except RequestProblem as e:  # caught before anything was sent: nothing billed
                    store.update(j, state="failed", error=str(e), error_kind="missing_input")
                except Exception as e:  # one job's unexpected error must not stop the others
                    said, status = http_detail(e)
                    if j["state"] == "submitting":  # it may have reached the provider: never re-send blindly
                        store.update(j, state="uncertain", error=f"Unexpected error while sending: {type(e).__name__}: {e}", error_kind="service")
                    elif status is not None:   # an HTTP refusal from a provider's own library (e.g. fal uploads): explain it
                        kind = classify_error(said, status)
                        if j["provider"] == "fal" and status == 403 and kind == "auth" and "storage" in str(e):
                            kind = "credits"   # fal refuses uploads on an account with no balance
                        store.update(j, state="failed", error=f"{ERROR_KINDS[kind]} Nothing was sent or charged. Provider said: {said}", error_kind=kind)
                    else:
                        store.update(j, state="failed", error=f"Unexpected error: {type(e).__name__}: {e}", error_kind="service", trace=__import__("traceback").format_exc()[-1500:])   # kept in jobs.json so a bug like this can be found
            from .retrycheap import due
            for j in due(store.jobs, run_started):
                try:   # "Retry failed videos on a cheaper model" (off unless the project turned it on): only for renders that failed during this run, once each
                    from .retrycheap import after_failure
                    store.update(j, auto_retry_checked=True)
                    after_failure(d, store, j)
                except Exception as e:
                    emit(event="progress", stage=f"cheaper retry skipped: {e}")
            if any(j["state"] == "submitted" for j in store.jobs):
                time.sleep(poll_every)
    finally:
        if os.path.exists(lock):
            os.remove(lock)
    try:   # Overnight on ComfyUI: approve, queue the next free step, or export when everything is done
        from .overnight import advance
        if advance(d):
            return run(d, poll_every)
    except Exception as e:
        emit(event="progress", stage=f"overnight step failed: {e}")
    emit(event="progress", stage="all renders settled")


def _submit_asset(d: str, store: Store, p, j: dict) -> None:
    """A reference picture made from a spec (refgen): not a shot, so no shot plan, keyframes or continuity are involved."""
    from . import refgen
    man = manifest(j["provider"], j["model"])
    emit(event="progress", stage=f"preparing {j.get('asset_name') or 'picture'}")
    payload = refgen.build_payload(d, p, j, man)
    problems = validate_request(man, payload)
    if problems:
        raise RequestProblem(f"Not sent (nothing was charged). {man['title']}: " + "; ".join(problems) + ".")
    try:
        est = estimate_payload(j["provider"], j["model"], man, payload)
    except Exception:
        est = {"usd": None}
    store.update(j, state="submitting", payload=payload, attempts=j["attempts"] + 1, estimate_usd=est.get("usd"))   # intent first, then the billable call
    emit(event="progress", stage=f"sending {j.get('asset_name') or 'picture'} to {j['provider']}")
    sub = p.submit(j["model"], payload)
    store.update(j, state="submitted", provider_job_id=sub.pop("id"), provider_meta=sub, submitted=int(time.time()))


def _submit_motion(d: str, store: Store, project: dict, p, j: dict) -> None:
    """A motion-control take: the request is the character picture, the motion video and a few settings; nothing else about the shot is sent."""
    _, plan = _load_plan(d) if j["plan"] == "directed" else ("production", _read(os.path.join(d, "production.json"), {}))
    shot, _scene = _shot(plan, j["shot_id"])
    man = manifest(j["provider"], j["model"])
    emit(event="progress", stage=f"preparing motion for {j['shot_id']}")
    payload = compile_motion(d, man, shot, j["motion"], j.get("overrides"))
    problems = validate_request(man, payload)
    if problems:
        raise RequestProblem(f"Not sent (nothing was charged). {man['title']}: " + "; ".join(problems) + ".")
    payload = _resolve_project_media(d, p, payload)
    try:
        est = estimate_payload(j["provider"], j["model"], man, payload)
    except Exception:
        est = {"usd": None}
    store.update(j, state="submitting", payload=payload, attempts=j["attempts"] + 1, estimate_usd=est.get("usd"), keyframe_ref=None)
    emit(event="progress", stage=f"sending {j['shot_id']} to {j['provider']}")
    sub = p.submit(j["model"], payload)
    store.update(j, state="submitted", provider_job_id=sub.pop("id"), provider_meta=sub, submitted=int(time.time()))


LAST_FRAME_FIELD = re.compile(r"^return_last_frame(?:_url)?$")


def last_frame_field(man: dict) -> str | None:
    """The input that makes a model hand back its final frame as a picture (Kie's Seedance family: return_last_frame), if it has one."""
    return next((f["name"] for f in man.get("inputs") or [] if LAST_FRAME_FIELD.match(f["name"]) and f.get("type") == "boolean"), None)


def _submit(d: str, store: Store, project: dict, p, j: dict) -> None:
    if j.get("kind") == "asset":
        return _submit_asset(d, store, p, j)
    if j.get("motion"):
        return _submit_motion(d, store, project, p, j)
    _, plan = _load_plan(d) if j["plan"] == "directed" else ("production", _read(os.path.join(d, "production.json"), {}))
    shot, scene = _shot(plan, j["shot_id"])
    shot = _with_movement(d, shot)
    hf = j.get("hand_fix") if j.get("kind") == "image" else None
    if hf:   # redraw one part of a keyframe: the instruction is the whole prompt and the crop is the only picture
        shot = {"id": shot["id"], "start": shot["start"], "end": shot["end"], "performers": [], "beats": [], "visual_prompt": str(hf.get("instruction") or "")}
    man = manifest(j["provider"], j["model"])
    emit(event="progress", stage=f"preparing {j['shot_id']}")
    if j.get("extend_of"):   # a continuation: it starts where the take ended, and carries the action on from there
        from . import extend
        src_take = next((x for x in store.jobs if x["id"] == j["extend_of"]), None)
        if not src_take or not src_take.get("output"):
            raise SystemExit("The take this continues is gone.")
        start_ref = extend.last_frame(d, src_take)
        shot = {**shot, "continues": True}
    else:
        start_ref = approved_keyframe(d, j["plan"], j["shot_id"]) if j.get("kind", "video") == "video" and not j.get("refs_only") else None
    if j.get("note"):
        shot = {**shot, "note": j["note"]}
    if j.get("custom_prompt"):
        shot = {**shot, "custom_prompt": j["custom_prompt"], "prompt_only": bool(j.get("prompt_only"))}
    ref_files = _reference_files(d, project, shot, scene)
    if j.get("kind") == "image":
        ref_files = [r for r in ref_files if not r["label"].startswith("set and props") and r.get("media", "image") == "image"]
        ref_files += _previous_shot_ref(d, j["plan"], plan, j["shot_id"])
        if j.get("frame") == "end":
            from . import frames
            shot = frames.end_still_prompt(shot, (_read(os.path.join(d, "shots.json"), {}).get(j["shot_id"]) or {}).get("end_state", ""))
            start = approved_keyframe(d, j["plan"], j["shot_id"])
            if start:   # the same shot's first frame first in line: same people, clothes, set and light
                ref_files = [{"label": "the FIRST frame of this same shot: keep its characters, wardrobe, set, lens and light exactly",
                              "path": os.path.join(d, start[len(PROJECT_MEDIA):]), "media": "image", "sheet": False}] + ref_files
    if hf:
        crop = os.path.join(d, str(hf.get("crop") or "-"))
        if not os.path.isfile(crop):
            raise RequestProblem("Not sent (nothing was charged). The part of the picture to fix is missing from the project; mark it again.")
        ref_files = [{"label": "the picture to fix: keep it exactly as it is except for what is asked", "path": crop, "media": "image", "sheet": False}]
    if j.get("kind") != "lipsync":
        from . import library
        kf = start_ref
        if kf:  # the approved keyframe already sets the scene; combined sheets carry titles models copy into frames
            ref_files = [r for r in ref_files if not r.get("sheet")]
        ref_files, _ = library.fit_to_model(ref_files, ref_limits(man, bool(kf)))
    refs = [] if j.get("kind") == "lipsync" else _uploaded(d, p, ref_files)
    if j.get("kind") == "image" and not refs and not hf:
        sib = text_only_model(j["model"], False)
        if sib != j["model"]:                                       # nothing to edit: draw it from the words alone, on the same family's text model
            try:
                alt = manifest(j["provider"], sib)
            except (SystemExit, Exception):
                alt = None                                          # the twin does not exist on this provider: keep the chosen model, whose own check explains what is missing
            if alt is not None:
                man = alt
                emit(event="progress", stage=f"{j['shot_id']}: no reference picture yet, so {sib.split('/')[-1]} draws it from the words")
                store.update(j, model=sib, swapped_from=j["model"])
    if j.get("kind") == "lipsync":
        src = next((x for x in store.jobs if x["id"] == j.get("source_job")), None)
        if not src or not src.get("output"):
            raise SystemExit("The take this lip-sync was based on is gone.")
        payload = compile_lipsync(d, man, shot, src, j.get("overrides"))
    else:
        sung, said = _voice(d, shot, plan, man, p, bool(start_ref)) if j.get("kind", "video") == "video" else (None, None)
        if j.get("kind", "video") == "video":
            refs = _with_keyframe(refs, start_ref, first=not audio_first(d, project, shot, plan, man))
            if j.get("end_frame") and man["caps"].get("last_frame"):
                local = os.path.join(d, j["end_frame"][len(PROJECT_MEDIA):])
                if not os.path.exists(local):
                    raise RequestProblem("Not sent (nothing was charged). The end frame chosen for this shot is missing; choose it again.")
                refs = refs + [{"label": "end frame", "url": _upload_cached(d, p, local), "endframe": True}]
        blocked = native_problem(d, shot, man) if j.get("kind", "video") == "video" else None
        if blocked:
            raise RequestProblem("Not sent (nothing was charged). " + blocked)
        native = native_for(d, shot, man) if j.get("kind", "video") == "video" else None
        payload = compile_request(shot, scene, plan, project, man, refs, j.get("overrides"), j.get("fix_notes"), sung, native, said)
        payload = fill_required(man, payload, refs)
        payload = exclusive_inputs(j["provider"], man["model"], payload, man)
        lf = last_frame_field(man) if j.get("kind", "video") == "video" and not j.get("motion") else None
        if lf:                                                  # the next shot picks up exactly where this one ends: ask the provider for the true last frame
            from . import frames
            if frames.hands_on(d, j["shot_id"]):
                payload[lf] = True
    problems = validate_request(man, payload)
    if problems:
        raise RequestProblem(f"Not sent (nothing was charged). {man['title']}: " + "; ".join(problems) + ".")
    payload = _resolve_project_media(d, p, payload)
    # Persist intent BEFORE the billable call; the id is persisted the moment it returns.
    try:
        est = estimate_payload(j["provider"], j["model"], man, payload)
    except Exception:
        est = {"usd": None}
    kf_used = approved_keyframe(d, j["plan"], j["shot_id"]) if j.get("kind", "video") == "video" and not j.get("refs_only") else None
    voice_ref = None
    if j.get("kind") == "lipsync" or (sung and sung.get("voiceover")):
        try:
            from . import voiceover as _vo
            voice_ref = _vo.clip_record(d, j["shot_id"])                         # which voice the mouth was made to follow, so a later change to it is noticed
        except (OSError, SystemExit):
            voice_ref = None
    store.update(j, state="submitting", payload=payload, attempts=j["attempts"] + 1, estimate_usd=est.get("usd"), keyframe_ref=kf_used, voice_ref=voice_ref)
    emit(event="progress", stage=f"sending {j['shot_id']} to {j['provider']}")
    sub = p.submit(j["model"], payload)
    store.update(j, state="submitted", provider_job_id=sub.pop("id"), provider_meta=sub, submitted=int(time.time()))


def _previous_shot_ref(d: str, plan_name: str, plan: dict, shot_id: str) -> list[dict]:
    """Continuity: the scene's previous approved keyframe, last in line (dropped first when the model takes few refs)."""
    shared: list[str] = []
    try:
        from .continuity import previous_keyframe
        p = previous_keyframe(d, plan_name, plan, shot_id, shared)       # only a shot that shows the same people: another person's picture is copied onto this shot's people
    except Exception:
        p = None
    if not p:
        return []
    who = " and ".join(shared)
    prev_look = None
    try:                                           # which look that picture is in, so a restyled shot can use it fully when it is in the same look and only for layout when it is not
        project = _read(os.path.join(d, "project.json"), {}) or {}
        for sc in plan.get("scenes", []):
            ids = [x["id"] for x in sc.get("shots", []) if isinstance(x, dict) and x.get("id")]
            if shot_id in ids and ids.index(shot_id) > 0:
                prev_look = resolve_look(project, sc.get("number"), ids[ids.index(shot_id) - 1])["id"]
    except Exception:
        prev_look = None
    return [{"label": f"the previous shot of this scene (match its set and light, and the clothes of {who} only; do not copy anyone else from it, not its framing)",
             "path": p, "kind": "continuity", "media": "image", "sheet": False, **({"look": prev_look} if prev_look else {})}]


def _with_movement(d: str, shot: dict) -> dict:
    """Camera and lighting choices made in the shot's camera picker (camera.json) are written over the Director's wording first, and the locked rules of the shot's designs are added."""
    try:
        from . import camera
        shot = camera.apply(d, shot)
    except Exception:
        pass
    extra = {}
    try:   # canonical designs: their locked rules go into the prompt in full (reference labels are short)
        from .library import load as _load_lib, shot_items
        _, lib = _load_lib(d)
        locked = [f"{it['name']}: {'; '.join(it['locked_rules'])}" for it in shot_items(lib, shot, shot.get("scene"))
                  if it.get("locked_rules")]
        if locked:
            extra["locked_design"] = "Locked design, keep exactly: " + " | ".join(locked) + "."
    except Exception:
        pass
    try:
        from .continuity import direction
        c = direction(d, shot)
        if c:
            extra["continuity"] = c
    except Exception:
        pass
    try:   # timed performance beats, where this person is in their arc, their signature gestures (acting.py)
        from . import acting
        from . import character_performance, performance_analysis       # the Performance Director: what you wrote about the people, never a draft
        from . import performance_prompts
        try:                                                              # the look's family decides how a non-human's acting is worded
            from . import animation_principles
            with open(os.path.join(d, "project.json"), encoding="utf-8") as fh:
                fam = animation_principles.family(resolve_look(json.load(fh), shot.get("scene"), shot.get("id"))["id"])
        except Exception:
            fam = ""
        if performance_prompts.text(d, shot, fam):
            extra["performance_text"] = performance_prompts.text(d, shot, fam)
        for key, text in (("acting_beats", acting.beats_text(d, shot, "video")), ("acting_beats_pose", acting.beats_text(d, shot, "image")),
                          ("arc_text", acting.arc_text(d, shot)), ("business_text", acting.business_text(d, shot)),
                          ("acting_nudges", acting.nudge_text(d, shot)), ("acting_carry", acting.carry_text(d, shot)),
                          ("psychology_text", character_performance.prompt_text(d, shot)), ("inner_text", performance_analysis.inner_text(d, shot))):
            if text:
                extra[key] = text
    except Exception:
        pass
    return {**shot, **extra} if extra else shot


def approved_keyframe(d: str, plan_name: str, shot_id: str) -> str | None:
    """The keyframe the user approved for this shot (a `project:` image), if any."""
    kf = _read(os.path.join(d, "keyframes.json"), {}) or {}
    ref = (kf.get(plan_name) or {}).get(shot_id)
    return ref if ref and os.path.exists(os.path.join(d, ref[len(PROJECT_MEDIA):])) else None


# Prompt limits some providers enforce but don't publish in their schema (bytes, with a little headroom).
PROMPT_LIMITS = {"pixverse": 2000, "vidu": 1500}


def known_prompt_limit(model: str) -> int:
    return next((n for k, n in PROMPT_LIMITS.items() if k in model.lower()), 0)


# Models whose picture field means FRAMES, not references: one picture is the first frame and a second is the last frame. Sending a
# character sheet there makes the video start or end on the sheet, so only the approved keyframe (and a chosen end frame) go in.
FRAMES_ONLY = {("kie", "bytedance/seedance-1.5-pro"), ("kie", "happyhorse/image-to-video")}
FRAME_WORDS = re.compile(r"first[- ]?frame|first and last frame|first/last frame|start(?:ing)? (?:frame|image)", re.I)
FRAME_LIST_WORDS = re.compile(r"first and last frame|first/last frame|start and end frame|first frame and (?:the )?last frame|index 0 is the first frame", re.I)


def frame_list_size(man: dict) -> int:
    """2 when the model's one picture list is its first AND last frame (Kling 3.0: `image_urls`, index 0 first, index 1 last), else 0. Read from the model's own description."""
    roles = man.get("roles") or {}
    f = next((x for x in man.get("inputs") or [] if x["name"] == roles.get("ref_images")), None)
    if not f or f.get("type") != "array" or "first_frame" in roles:
        return 0
    return 2 if FRAME_LIST_WORDS.search((f.get("description") or "")[:260]) else 0


def frames_only(man: dict) -> bool:
    if (man.get("provider"), man.get("model")) in FRAMES_ONLY:
        return True
    roles = man.get("roles") or {}
    f = next((x for x in man.get("inputs") or [] if x["name"] == roles.get("ref_images")), None)
    if not f or "first_frame" in roles:
        return False
    head = (f.get("description") or "")[:140]
    if FRAME_WORDS.search(head) and not re.search(r"reference", head, re.I):
        return True
    return f.get("type") == "array" and f.get("max_items") == 1       # a list that holds one picture is that shot's start frame


# Models that take only one image (the provider wants a template for more).
SINGLE_IMAGE = {("kie", "pixverse/image-to-video")}

# Models that accept a first frame OR reference images, never both (the provider refuses the request).
EXCLUSIVE_FIRST_FRAME = {("kie", m) for m in ("bytedance/seedance-2", "bytedance/seedance-2-fast", "bytedance/seedance-2-mini", "bytedance/seedance-2-5")}
EXCLUSIVE_WORDS = re.compile(r"cannot be used simultaneously|mutually exclusive|cannot be provided at the same time|cannot be used together", re.I)


def exclusive_by_docs(man: dict | None) -> bool:
    """True when the model's own documentation says its first frame cannot be combined with reference pictures, videos or audio."""
    if not man:
        return False
    roles = man.get("roles") or {}
    names = {roles.get(r) for r in ("first_frame", "ref_images", "ref_videos", "ref_audio")} - {None}
    return "first_frame" in roles and any(EXCLUSIVE_WORDS.search(f.get("description") or "") for f in man.get("inputs") or [] if f["name"] in names)


def _exclusive_model(man: dict) -> bool:
    """A model that refuses a first frame and reference audio in the same request (the Seedance 2 family)."""
    return (man.get("provider"), man.get("model")) in EXCLUSIVE_FIRST_FRAME or exclusive_by_docs(man)


def _mouth_shown(d: str, shot: dict) -> bool:
    """A medium or closer shot with at least a second of vocal under it: a mouth the viewer will watch."""
    song_map = _read(os.path.join(d, "songmap.json"), {}) or {}
    lines = [l for l in song_map.get("lyrics", []) if l.get("start") is not None and l["start"] < shot["end"] and (l.get("end") or l["start"]) > shot["start"]]
    return bool(lines) and _mouth_visible(shot, lines)


def audio_first(d: str, project: dict, shot: dict, plan: dict, man: dict) -> bool:
    """'Follow the song's audio' applies to this shot: it is sung or spoken, the model can follow reference audio but not together with a first frame, and the project has not turned
    lip-sync off. The keyframe is then sent as a reference picture instead of the first frame, so the song's vocal can be sent and the mouth follows the music instead of only the words in
    the prompt. The opening of the take may differ from the keyframe. lip_sync_mode: "audio_first" does it for every such shot; "auto" only where a mouth is watched (a medium or closer
    shot with a second or more of vocal), so wide shots keep their keyframe; anything else keeps the keyframe as the first frame."""
    mode = project.get("lip_sync_mode")
    if mode not in ("audio_first", "auto") or project.get("lip_sync", "auto") == "off":
        return False
    if "ref_audio" not in (man.get("roles") or {}) or not _exclusive_model(man) or native_for(d, shot, man) or not singing(d, shot, plan):
        return False
    from . import voiceover
    return mode == "audio_first" or bool(voiceover.for_shot(d, shot.get("id", ""))) or _mouth_shown(d, shot)


def model_inputs(refs: list[dict], payload: dict, man: dict, sung: dict | None) -> list[dict]:
    """What the model is given, in order, for the screen to show as pictures: the first frame, each reference picture, the end frame, the song's vocal. `sent` says whether it is really in the
    request (a model that takes a first frame can refuse reference pictures beside it, and takes only so many), so nothing is left to guess."""
    roles = man.get("roles") or {}
    first_key, imgs_key, audio_key = roles.get("first_frame"), roles.get("ref_images"), roles.get("ref_audio")
    imgs = payload.get(imgs_key) if imgs_key else None
    room = len(imgs) if isinstance(imgs, list) else (1 if imgs else 0)
    out, taken = [], 0
    for r in refs:
        if r.get("media", "image") != "image":
            continue
        path = r.get("path") or (str(r["url"])[len(PROJECT_MEDIA):] if str(r.get("url", "")).startswith(PROJECT_MEDIA) else None)
        if r.get("keyframe"):
            out.append({"role": "first_frame", "label": "Starts from this frame (your approved keyframe)", "path": path, "sent": bool(first_key and payload.get(first_key))})
        elif r.get("endframe"):
            out.append({"role": "end_frame", "label": "Ends on this frame", "path": path, "sent": bool(roles.get("last_frame") and payload.get(roles["last_frame"]))})
        else:
            kf = str(r.get("label", "")).startswith("approved keyframe")
            sent = taken < room
            taken += 1 if sent else 0
            out.append({"role": "reference", "label": ("Reference picture (your approved keyframe)" if kf else r.get("label", "Reference picture").split(" (")[0].split(":")[0]), "path": path, "sent": sent})
    if sung and audio_key and payload.get(audio_key):
        out.append({"role": "audio", "label": (f"Your recording{'s' if sung.get('turns') else ''} of {sung.get('performer', 'the speaker')}, for the mouth{'s' if sung.get('turns') else ''} to follow" if sung.get("voiceover")
                                               else f"The song's vocal under this shot, for {sung.get('performer', 'the singer')} to follow"), "path": None, "sent": True})
    return out


def exclusive_inputs(provider: str, model: str, payload: dict, man: dict | None = None) -> dict:
    """With a first frame (the approved keyframe, which already shows the characters), drop what the model refuses to take beside it:
    reference pictures, reference videos and reference audio. The Seedance 2 family's first + last frame are its own two-frame mode and stay together; a last frame alone is dropped."""
    first = ((man or {}).get("roles") or {}).get("first_frame", "first_frame_url")
    known = (provider, model) in EXCLUSIVE_FIRST_FRAME
    if (known or exclusive_by_docs(man)) and payload.get(first):
        roles = (man or {}).get("roles") or {}
        for k in {roles.get("ref_images"), roles.get("ref_videos"), roles.get("ref_audio"), "reference_image_urls", "reference_video_urls", "reference_audio_urls"} - {None}:
            payload.pop(k, None)
    if known and not payload.get(first):
        payload.pop("last_frame_url", None)               # Seedance: a last frame is never sent alone, only with its first frame
    if (provider == "kie" and "pixverse" in model) and isinstance(payload.get("image_urls"), list):
        payload["image_urls"] = payload["image_urls"][:1]   # the keyframe comes first
    return payload


def _with_keyframe(refs: list[dict], kf: str | None, first: bool = True) -> list[dict]:
    """The approved keyframe, first in line: the model's first frame, or (first=False, the 'follow the song's audio' mode) an ordinary reference picture."""
    if not kf:
        return refs
    if not first:
        return [{"label": "approved keyframe for this shot: open the shot like this frame and keep its composition, characters, wardrobe and lighting", "url": kf, "media": "image"}] + refs
    return [{"label": "approved keyframe for this exact shot: start from this frame and keep its composition, "
                      "characters, wardrobe and lighting", "url": kf, "keyframe": True}] + refs


def _said_for(d: str, shot: dict, plan: dict, man: dict) -> dict | None:
    """The line a performer voices in this shot when the model has no way to take the recorded voice (no audio input, no native speech): it is
    still told what is being said or sung, so the mouth moves with the words. The recorded song is laid over the shot later."""
    project = _read(os.path.join(d, "project.json"), {})
    if project.get("lip_sync", "auto") == "off" or native_for(d, shot, man):
        return None
    return singing(d, shot, plan)


def _voice(d: str, shot: dict, plan: dict, man: dict, provider=None, has_keyframe: bool = False) -> tuple[dict | None, dict | None]:
    """(sung, said) for a video shot: the recorded voice sent as audio to follow, or, when the model can't be given it, the words in the prompt.
    A model whose first frame cannot be combined with reference audio (the Seedance 2 family) never gets the recorded voice once a keyframe is its first frame:
    the prompt then describes the words instead of pointing at audio that is not sent."""
    sung = None
    project = _read(os.path.join(d, "project.json"), {})
    if not (has_keyframe and _exclusive_model(man) and not audio_first(d, project, shot, plan, man)):
        sung = _sung_for(d, shot, plan, man, provider)
    return sung, (None if sung else _said_for(d, shot, plan, man))


def _sung_for(d: str, shot: dict, plan: dict, man: dict, provider=None) -> dict | None:
    """Lip-sync audio for singing shots on models that accept reference audio. provider=None: preview only."""
    project = _read(os.path.join(d, "project.json"), {})
    if "ref_audio" not in man["roles"] or project.get("lip_sync", "auto") == "off" or native_for(d, shot, man):
        return None   # a native-dialogue shot is spoken by the model: no recorded voice is sent to follow
    sing = singing(d, shot, plan)
    if not sing:
        return None
    fields = {f["name"]: f for f in man["inputs"]}
    dur = shot["end"] - shot["start"]
    if "duration" in man["roles"]:
        try:
            dur = float(str(_duration_value(fields[man["roles"]["duration"]], dur)).rstrip("s"))
        except ValueError:
            pass
    if sing.get("voiceover"):
        from . import voiceover
        local = voiceover.slice_for(d, shot["id"], dur)                                              # the person's own recording(s) for this shot
    else:
        local = song_slice(d, shot, dur, vocals_only=project.get("lip_sync_audio", "vocals") != "mix")   # the clean vocal when the song has been separated: instruments confuse a mouth
    url = f"(upload) {os.path.basename(local)}" if provider is None else _upload_cached(d, provider, local)
    return {**sing, "url": url}


AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v", ".mkv")


def _upload_cached(d: str, provider, path: str) -> str:
    """Upload one file (a picture, the song clip under a shot, a video) once and reuse its link. The kind comes from the file: an audio clip
    sent as if it were a picture used to be left out and then crashed on the empty result."""
    ext = os.path.splitext(path)[1].lower()
    media = "audio" if ext in AUDIO_EXT else "video" if ext in VIDEO_EXT else "image"
    got = _uploaded(d, provider, [{"label": "", "path": path, "media": media}])
    if not got:
        raise RequestProblem(f"Not sent (nothing was charged). {os.path.basename(path)} is a kind of file this model cannot be given. Use PNG, JPEG or WebP pictures, MP3 or WAV audio.")
    return got[0]["url"]


PROJECT_MEDIA = "project:"


def _resolve_project_media(d: str, provider, payload: dict) -> dict:
    """Director Mode uploads are stored in the project as `project:<relative path>`; upload them now."""
    def conv(v):
        if isinstance(v, str) and v.startswith(PROJECT_MEDIA):
            local = os.path.join(d, v[len(PROJECT_MEDIA):])
            if not os.path.exists(local):
                raise SystemExit(f"Reference file missing: {v[len(PROJECT_MEDIA):]}")
            return _upload_cached(d, provider, local)
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v
    return {k: conv(v) for k, v in payload.items()}


def live_progress(res: dict) -> dict:
    """What a provider said while a job runs, in the two fields the Render queue shows: a short text, and a 0..1 fraction when it gave one."""
    raw = res.get("progress")
    frac = None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0:
        frac = round(min(1.0, raw / 100 if raw > 1 else float(raw)), 3)
    detail = res.get("detail")
    return {"detail": str(detail)[:80] if detail else None, "progress": frac}


def _save_last_frame(d: str, j: dict, url: str) -> str | None:
    """The provider's own last frame of a take, kept in the project (media/<shot>_last_<job>.png). Never fatal: without it the next shot's start is read from the video instead."""
    from .safe import file_part
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        rel = f"media/{file_part(j['shot_id'])}_last_{file_part(j['id'])}.png"
        os.makedirs(os.path.join(d, "media"), exist_ok=True)
        from io import BytesIO
        from PIL import Image
        Image.open(BytesIO(r.content)).convert("RGB").save(os.path.join(d, rel))
        return rel
    except Exception:
        return None


def _check(d: str, store: Store, p, j: dict) -> None:
    res = p.poll(j["model"], j["provider_job_id"], j.get("provider_meta"))
    if res["state"] == "running":
        emit(event="progress", stage=f"rendering {j['shot_id']}", detail=res.get("detail"), job_id=j["id"])
        live = live_progress(res)
        if live["detail"] != j.get("detail") or live["progress"] != j.get("progress"):   # kept on the job so the Render queue can show it, only when it changed
            store.update(j, **live)
        return
    if res["state"] == "failed":
        store.update(j, state="failed", error=describe_error(res.get("error") or "Generation failed."),
                     error_kind=classify_error(res.get("error") or ""))
        return
    out_dir = os.path.join(d, "generations")
    os.makedirs(out_dir, exist_ok=True)
    url = res["url"] or ""
    named = re.search(r"[?&]filename=([^&]+)", url)  # ComfyUI /view?filename=...
    ext = os.path.splitext(requests.utils.unquote(named.group(1)))[1].lower() if named else \
        (".mp4" if j.get("kind", "video") not in ("image", "asset") else (os.path.splitext(url.split("?")[0])[1].lower() or ".png"))
    if ext not in (".mp4", ".mov", ".webm", ".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png" if j.get("kind") in ("image", "asset") else ".mp4"
    out = os.path.join(out_dir, f"{re.sub(r'[^A-Za-z0-9._-]+', '_', j['shot_id'])}__{j['id']}{ext}")
    emit(event="progress", stage=f"downloading {j['shot_id']}")
    if url.startswith("file:"):
        import shutil
        shutil.move(url[5:], out)
    else:
        headers = getattr(p, "h", {}) if res.get("auth") else {}
        with requests.get(url, stream=True, timeout=300, headers=headers) as r:
            r.raise_for_status()
            with open(out + ".part", "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        os.replace(out + ".part", out)
    if j.get("extend_of"):   # the new part is joined to the take it continues; the take itself is untouched
        from . import extend
        base = next((x for x in store.jobs if x["id"] == j["extend_of"]), None)
        part = out[:-4] + "_part" + os.path.splitext(out)[1]
        os.replace(out, part)
        try:
            extend.join(os.path.join(d, base["output"]), part, out)
        except SystemExit as e:
            os.replace(part, out)
            store.update(j, state="failed", error_kind="service", cost=res.get("cost"), cost_unit=res.get("cost_unit"),
                         error=f"The new part was made (and billed) but could not be joined to the original. {e} The new part alone is saved as {os.path.relpath(out, d)}.")
            return
        store.update(j, extension_part=os.path.relpath(part, d).replace(os.sep, "/"))
    if j.get("kind") == "image":   # a keyframe is trimmed to the project's shape if the model made another (21:9 from a 3:2 model, say)
        fit_to_aspect(out, _read(os.path.join(d, "project.json"), {}).get("aspect_ratio"))
    if j.get("kind") == "asset":   # it must open as a real picture before anyone is offered it
        from .refgen import verify_picture
        try:
            verify_picture(out)
        except Exception:
            os.remove(out)
            store.update(j, state="failed", error_kind="invalid", cost=res.get("cost"), cost_unit=res.get("cost_unit"),
                         error="The provider sent back something that isn't a picture. It may still have been billed: check your provider dashboard.")
            return
    if j["provider"] == "kie" and res.get("cost"):
        remember_kie_cost(j["model"], float(res["cost"]), j.get("size_key") or "")
    saved = _save_last_frame(d, j, res.get("last_frame_url")) if res.get("last_frame_url") else None
    store.update(j, state="ready", output=os.path.relpath(out, d).replace(os.sep, "/"), output_url=res["url"],
                 cost=res.get("cost"), cost_unit=res.get("cost_unit"), finished=int(time.time()), **({"last_frame_image": saved} if saved else {}))
    if j.get("kind", "video") in ("video", "lipsync"):
        _review(d, store, j)
    if j.get("kind") == "image":   # keyframe check: a bad still is caught before anyone pays to animate it
        from .stills import after_still
        after_still(d, store, j)
    if j.get("kind", "video") == "video" and not j.get("lipsync_child"):
        _auto_lipsync(d, store, j)


def _auto_lipsync(d: str, store: Store, j: dict) -> None:
    project = _read(os.path.join(d, "project.json"), {})
    try:
        plan = _read(os.path.join(d, f"{j['plan']}.json"), {})
        shot, _ = _shot(plan, j["shot_id"])
    except SystemExit:
        return
    prov = _lipsync_provider()
    if not prov or not wants_lipsync_pass(d, project, plan, shot):
        return
    child = {"id": uuid.uuid4().hex[:12], "shot_id": j["shot_id"], "plan": j["plan"], "source_shots": j.get("source_shots", []),
             "shot_start": j["shot_start"], "shot_end": j["shot_end"], "provider": prov, "model": AUTO_LIPSYNC[prov],
             "kind": "lipsync", "source_job": j["id"], "auto": True, "overrides": {}, "fix_notes": [], "look": j.get("look"),
             "state": "queued", "provider_job_id": None, "attempts": 0, "created": int(time.time()), "updated": int(time.time()),
             "output": None, "error": None, "cost": None}
    store.jobs.append(child)
    store.update(j, lipsync_child=child["id"])
    emit(event="job", job=child)
    emit(event="progress", stage=f"{j['shot_id']} is a singing close-up: lip-sync pass queued")


def _review(d: str, store: Store, j: dict) -> None:
    from .review import review_job
    try:
        plan = _read(os.path.join(d, f"{j['plan']}.json"), {})
        shot, _ = _shot(plan, j["shot_id"])
    except SystemExit:
        return
    emit(event="progress", stage=f"reviewing {j['shot_id']}")
    try:
        store.update(j, review=review_job(d, j, _read(os.path.join(d, "project.json"), {}), shot))
    except Exception as e:
        store.update(j, review={"reviewed": False, "error": f"{type(e).__name__}: {e}"})


def review_backlog_count(d: str) -> int:
    """Finished takes that were never visually checked (free to count)."""
    store = Store(d)
    return sum(1 for j in store.jobs if j["state"] == "ready" and j.get("output") and j.get("kind") != "image" and j["provider"] != "own"
               and (not j.get("review") or not j["review"].get("reviewed")))


def review_pending(d: str, yield_to_renders: bool = False) -> bool:
    """Review finished takes that were never checked (e.g. an OpenAI key was added later).
    With yield_to_renders, stops (returning True) as soon as new renders are queued, so they never wait behind reviews."""
    store = Store(d)
    from .llm import config as _brain
    _b = _brain()
    can_see = bool(os.environ.get("FILMCRAFTER_OPENAI_KEY")) if _b["provider"] == "openai" else bool(_b["vision_model"])
    for j in store.jobs:
        if j["state"] != "ready" or not j.get("output") or j.get("kind") == "image" or j["provider"] == "own":
            # stills aren't video takes; your own media is yours to judge (and checking it would cost money)
            continue
        rv = j.get("review")
        never_checked = not rv or not rv.get("reviewed")
        # Upgrade technical-only reviews once visual checking is possible (not after a technical failure).
        missing_visual = can_see and rv and rv.get("visual") is None \
            and not any(i["severity"] == "major" for i in rv.get("technical", []))
        if never_checked or missing_visual:
            if yield_to_renders and any(x["state"] in ACTIVE for x in Store(d).jobs):
                return True
            _review(d, store, j)
    return False


# ---------------------------------------------------------------- cost estimates (PRD §57)

RES_HEIGHT = {"480p": 480, "720p": 720, "1080p": 1080, "4k": 2160, "2160p": 2160}


def _fal_price(model: str) -> dict | None:
    key = os.environ.get("FAL_KEY")
    if not key:
        return None
    cache_path = os.path.join(CACHE_DIR, "fal_prices.json")
    cache = _read(cache_path, {})
    hit = cache.get(model)
    if hit and time.time() - hit["at"] < (86400 if hit.get("price") else 3600):   # a failed lookup is retried within the hour
        return hit["price"]
    try:
        r = requests.get("https://api.fal.ai/v1/models/pricing", params={"endpoint_id": model},
                         headers={**UA, "Authorization": f"Key {key}"}, timeout=30)
        price = next(iter(r.json().get("prices", [])), None) if r.ok else None
    except (requests.RequestException, ValueError):
        price = None
    if price is None and hit and hit.get("price"):   # keep the last known price rather than forgetting it
        return hit["price"]
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache[model] = {"price": price, "at": int(time.time())}
    _write(cache_path, cache)
    return price


def token_unit(unit: str) -> int | None:
    """How many tokens one unit of a token-priced model is: "1m tokens" / "1M_tokens" / "million tokens" -> 1,000,000; "1k tokens" / "1000 tokens" -> 1,000;
    "token" -> 1. None when it can't be told (the price is then not guessed)."""
    u = str(unit or "").lower()
    m = re.search(r"(\d[\d,]*)\s*([km])?[\s_-]*(?:tokens?|toks?)\b", u)
    if m:
        return int(m.group(1).replace(",", "")) * {"k": 1_000, "m": 1_000_000, None: 1}[m.group(2)]
    if "million" in u:
        return 1_000_000
    if "thousand" in u:
        return 1_000
    return 1 if re.search(r"\btokens?\b", u) else None


MAX_SANE_REQUEST_USD = 100.0      # a single shot costing more than this is a mistake in the arithmetic, not a price


def estimate_payload(provider: str, model: str, man: dict, payload: dict) -> dict:
    """Best-effort USD estimate for one request. Returns {'usd': float|None, 'basis': str}."""
    e = _estimate_payload(provider, model, man, payload)
    if e.get("usd") is not None and e["usd"] > MAX_SANE_REQUEST_USD:
        return {"usd": None, "basis": "The price could not be worked out reliably for this model. Check fal.ai's price list before rendering."}
    return e


def _estimate_payload(provider: str, model: str, man: dict, payload: dict) -> dict:
    if provider == "comfyui":
        return {"usd": 0.0, "basis": "Runs on your ComfyUI: no provider charge."}
    if provider == "openai":
        return {"usd": None, "basis": "OpenAI bills per image by size and quality; see your OpenAI usage page."}
    if provider == "byteplus":
        return byteplus_price(model, payload)
    if provider == "google":
        return {"usd": None, "basis": "Google bills per second of video / per image; see your Google AI Studio usage."}
    if provider != "fal":
        return {"usd": None, "basis": "Kie bills in credits; the exact amount is shown after each render."}
    price = _fal_price(model)
    if not price:
        return {"usd": None, "basis": "Price not published for this model."}
    roles = man["roles"]
    secs = float(str(payload.get(roles.get("duration", "duration"), 5)).rstrip("s") or 5)
    unit, unit_price = price.get("unit", ""), float(price.get("unit_price", 0))
    if "second" in unit:
        return {"usd": round(unit_price * secs, 3), "basis": f"${unit_price}/s × {secs:g}s"}
    if "minute" in unit:
        return {"usd": round(unit_price * secs / 60, 3), "basis": f"${unit_price}/min × {secs:g}s"}
    if "token" in unit:
        # ByteDance video tokens ≈ width × height × fps × seconds / 1024.
        h = RES_HEIGHT.get(str(payload.get(roles.get("resolution", "resolution"), "720p")).lower(), 720)
        m = re.match(r"^(\d+):(\d+)$", str(payload.get(roles.get("aspect_ratio", "aspect_ratio"), "16:9")))
        ar = int(m.group(1)) / int(m.group(2)) if m else 16 / 9
        w_px, h_px = (h * ar, h) if ar >= 1 else (h, h / ar)
        tokens = w_px * h_px * 24 * secs / 1024
        per = token_unit(unit)
        if not per:
            return {"usd": None, "basis": f"Billed per {unit}."}
        return {"usd": round(tokens / per * unit_price, 3), "basis": f"≈{tokens / 1000:.0f}k tokens × ${unit_price}/{per:,} tokens"}
    if any(u in unit for u in ("video", "request", "generation", "image")):
        return {"usd": round(unit_price, 3), "basis": f"${unit_price} per {unit}"}
    if "megapixel" in unit:   # stills: about one megapixel; video: every frame counts
        size = payload.get("image_size")
        if "duration" in roles:
            mp = 1280 * 720 * 24 * secs / 1e6
        elif isinstance(size, dict) and size.get("width") and size.get("height"):
            mp = float(size["width"]) * float(size["height"]) / 1e6          # the size that will really be asked for
        else:
            mp = 1.05
        return {"usd": round(unit_price * mp, 3), "basis": f"${unit_price}/megapixel × ≈{mp:.1f} MP"}
    return {"usd": None, "basis": f"Billed per {unit}."}


KIE_COST_SEED = {   # credits per render seen in real runs (Sept 2026); updated automatically as renders finish
    "google/nano-banana-edit": 4, "gpt/gpt-image-2-5-flare-image-to-image": 16, "gpt-image-2-5-flare-image-to-image": 16,
    "hailuo/2-3-image-to-video-standard": 30,
    "kling-2.6/image-to-video": 55, "wan/3-0-video": 70, "bytedance/seedance-2": 164,
}


def kie_cost_memory() -> dict:
    mem = dict(KIE_COST_SEED)
    mem.update(_read(os.path.join(CACHE_DIR, "kie_costs.json"), {}) or {})
    return mem


def kie_credits_for(jobs: list[dict], model: str, key: str = "") -> float | None:
    """Credits one render of this model cost before, at this size (`key` from picture_size_plan; "" is the basic size). A price learned at another size is never used."""
    seen = sorted(float(j["cost"]) for j in jobs if j.get("provider") == "kie" and j.get("model") == model and j.get("cost") and (j.get("size_key") or "") == key)
    if seen:
        return seen[len(seen) // 2]
    return kie_cost_memory().get(f"{model}|{key}" if key else model)


def remember_kie_cost(model: str, credits: float, key: str = "") -> None:
    path = os.path.join(CACHE_DIR, "kie_costs.json")
    mem = _read(path, {}) or {}
    slot = f"{model}|{key}" if key else model
    old = mem.get(slot)
    mem[slot] = round(credits if old is None else 0.7 * old + 0.3 * credits, 1)   # smooth: durations vary per shot
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        _write(path, mem)
    except OSError:
        pass


def estimate(d: str, shot_ids: list[str], provider: str, model: str | None, kind: str = "video") -> dict:
    project = _read(os.path.join(d, "project.json"), {})
    _, plan = _load_plan(d)
    man = manifest(provider, model or default_model(provider, kind))
    total, per, unknown = 0.0, [], 0
    refs = [{"label": r["label"], "url": "x"} for r in _reference_files(d, project, None)]
    lip_prov = _lipsync_provider() if kind == "video" else None
    lip_shots = 0
    plan_name = "directed" if os.path.exists(os.path.join(d, "directed.json")) else "production"
    swapped, no_end, blocked_native, native_shots, crowded_native = [], [], [], 0, []
    for sid in shot_ids:
        shot, scene = _shot(plan, sid)
        sman, srefs = man, refs
        if kind == "video":   # a shot with an end frame is priced on the model version that will really render it
            from . import frames
            if frames.end_ref(d, plan_name, plan, sid):
                m = frames.model_for(provider, man["model"], True)
                if m["swapped"]:
                    sman = manifest(provider, m["model"])
                    swapped.append({"shot": sid, "model": m["model"], "title": sman["title"]})
                if not m["supports_end"]:
                    no_end.append(sid)
                srefs = refs + [{"label": "end frame", "url": "x", "endframe": True}]
        payload = compile_request(shot, scene, plan, project, sman, srefs, native=native_for(d, shot, sman) if kind == "video" else None,
                                  said=_said_for(d, shot, plan, sman) if kind == "video" else None)
        e = estimate_payload(provider, sman["model"], sman, payload)
        if kind == "video" and native_problem(d, shot, sman):
            blocked_native.append(sid)
        if "audio" in sman["roles"] and payload.get(sman["roles"]["audio"]) is True:
            native_shots += 1
            if sum(max(1.0, len(x["text"].split()) / 2.5) for x in native_lines(d, shot)) > (shot["end"] - shot["start"]) + 0.3:     # about 2.5 words a second, at least a second a line
                crowded_native.append(sid)       # more speech than the shot holds: the model rushes it or cuts it off
        if lip_prov and wants_lipsync_pass(d, project, plan, shot):
            lip_shots += 1
            lman = manifest(lip_prov, AUTO_LIPSYNC[lip_prov])
            secs = payload.get(man["roles"].get("duration", "duration"), 5)
            le = estimate_payload(lip_prov, lman["model"], {**lman, "roles": {**lman["roles"], "duration": "duration"}}, {"duration": secs})
            if e["usd"] is not None and le["usd"] is not None:
                e = {**e, "usd": round(e["usd"] + le["usd"], 3)}
        per.append({"shot_id": sid, **e})
        if e["usd"] is None:
            unknown += 1
        else:
            total += e["usd"]
    out = {"provider": provider, "model": man["model"], "shots": len(shot_ids), "usd": round(total + 1e-9, 2) if not unknown else None,        # half-up: 4.5 cents is shown as 5, never as 4
           "usd_known": round(total + 1e-9, 2), "unknown": unknown, "basis": per[0]["basis"] if per else "",
           "lipsync_shots": lip_shots, "end_frame_models": swapped, "end_frame_unsupported": no_end, "native_blocked": blocked_native,
           "native_shots": native_shots, "native_crowded": crowded_native,
           **({"native_note": f"{native_shots} shot(s) are spoken by the model, so they are rendered with sound on. Some models charge more with "
                              "sound on than the listed price: treat this estimate as a minimum."
                              + (f" {len(crowded_native)} of them ({', '.join(crowded_native[:4])}{'…' if len(crowded_native) > 4 else ''}) hold more speech than "
                                 "fits, so the model may rush or cut it off: shorten the lines or split the shot." if crowded_native else "")} if native_shots else {})}
    if provider == "kie":   # Kie publishes no per-model price: estimate from what this model actually cost before
        skey = picture_size_plan(man, project)["key"] if kind == "image" else ""
        per = kie_credits_for(Store(d).jobs, man["model"], skey)
        if not per and skey:     # a bigger picture than any this model made before: its earlier price does not apply, so say so instead of showing a lower one
            out["size_unpriced"] = True
            out["basis"] = f"Not priced yet at this size ({skey.split('=')[1]}): it costs more than the basic size, and Kie shows the amount only after a picture is made. Counted at a high safety price until then."
        if per:
            from .budget import KIE_USD_PER_CREDIT
            out["kie_credits_est"] = round(per * len(shot_ids))
            out["kie_usd_est"] = round(per * len(shot_ids) * KIE_USD_PER_CREDIT, 2)       # a rough dollar figure, so Kie and fal can be compared
            out["basis"] = f"≈{round(per)} credits per shot (what {man['model'].split('/')[-1]} cost before" + (f", at the larger size {skey.split('=')[1]})" if skey else ")")
    if provider == "kie" and os.environ.get("KIE_KEY"):
        try:
            r = requests.get("https://api.kie.ai/api/v1/chat/credit", headers={**UA, "Authorization": f"Bearer {os.environ['KIE_KEY']}"}, timeout=20)
            out["kie_credits"] = r.json().get("data")
        except requests.RequestException:
            pass
    return out


def resolve(d: str, job_id: str, action: str) -> dict:
    store = Store(d)
    j = next((x for x in store.jobs if x["id"] == job_id), None)
    if not j:
        raise SystemExit("That render job no longer exists.")
    if action == "retry" and j["state"] in ("failed", "uncertain"):
        store.update(j, state="queued", error=None, provider_job_id=None)
    elif action == "recheck" and j["state"] in ("failed", "uncertain") and j.get("provider_job_id"):
        # the provider already has this render: ask it again for the result (never sends or pays twice)
        store.update(j, state="submitted", error=None, error_kind=None)
    elif action == "cancel" and j["state"] == "queued":   # not sent yet, so nothing is billed
        store.update(j, state="dismissed", error="Cancelled before it was sent.")
    elif action == "dismiss" and j["state"] not in ACTIVE:
        store.update(j, state="dismissed")
    elif action == "accept" and j["state"] == "ready":
        store.update(j, review={**(j.get("review") or {}), "accepted": True})
    else:
        raise SystemExit(f"Can't {action} a job that is {j['state']}.")
    return j


def preview(d: str, shot_id: str, provider: str, model: str | None, overrides: dict | None, kind: str = "video") -> dict:
    """Show exactly what would be sent (reference URLs shown as local files). Costs nothing."""
    project = _read(os.path.join(d, "project.json"), {})
    _, plan = _load_plan(d)
    shot, scene = _shot(plan, shot_id)
    shot = _with_movement(d, shot)
    overrides = dict(overrides or {})                  # the compose tab's private settings: shown here exactly as the render will use them
    words = str(overrides.pop("_prompt", "") or "").strip()
    only_words = bool(overrides.pop("_prompt_only", False))
    if words:
        shot = {**shot, "custom_prompt": words, "prompt_only": only_words}
    direction = str(overrides.pop("_note", "") or "").strip()[:600]
    if direction:
        shot = {**shot, "note": direction}
    refs_only = bool(overrides.pop("_refs_only", False))
    man = manifest(provider, model or default_model(provider, kind))
    from . import library
    plan_name = "directed" if os.path.exists(os.path.join(d, "directed.json")) else "production"
    kf = approved_keyframe(d, plan_name, shot_id) if kind == "video" and not refs_only else None
    end, frame_info = None, None
    if kind == "video":   # show what really goes out: the start+end version of the model when the shot lands on an end frame
        from . import frames
        end = frames.end_ref(d, plan_name, plan, shot_id)
        if end:
            m = frames.model_for(provider, man["model"], True)
            if m["swapped"]:
                man = manifest(provider, m["model"])
            frame_info = {"end": end, "model": man["model"], "title": man["title"], "swapped": m["swapped"], "supports_end": m["supports_end"]}
    files = [r for r in _reference_files(d, project, shot, scene)
             if kind != "image" or (not r["label"].startswith("set and props") and r.get("media", "image") == "image")]
    if kind == "image":
        files += _previous_shot_ref(d, plan_name, plan, shot_id)
    if kf:
        files = [r for r in files if not r.get("sheet")]
    files, dropped = library.fit_to_model(files, ref_limits(man, bool(kf)))
    refs = [{"label": r["label"], "url": f"(upload) {os.path.basename(r['path'])}", "media": r.get("media", "image"),
             "path": os.path.relpath(r["path"], d).replace(os.sep, "/")} for r in files]
    af = kind == "video" and audio_first(d, project, shot, plan, man)
    refs = _with_keyframe(refs, kf, first=not af)
    if end and man["caps"].get("last_frame"):
        refs = refs + [{"label": "end frame", "url": f"(upload) {os.path.basename(end)}", "endframe": True,
                        "path": end[len(PROJECT_MEDIA):]}]
    sung, said = _voice(d, shot, plan, man, None, bool(kf)) if kind == "video" else (None, None)
    native = native_for(d, shot, man) if kind == "video" else None
    prompt_blocks: list = []
    payload = fill_required(man, compile_request(shot, scene, plan, project, man, refs, overrides, None, sung, native, said, trace=prompt_blocks), refs)
    payload = exclusive_inputs(provider, man["model"], payload, man)
    blocked = native_problem(d, shot, man) if kind == "video" else None
    return {"manifest": man, "payload": payload, "problems": validate_request(man, payload) + ([blocked] if blocked else []),
            "native_dialogue": bool(native),
            "keyframe": kf, "end_frame": frame_info, "references": refs, "dropped_references": dropped,
            "lip_sync": bool(sung), "singing": singing(d, shot, plan), "sing_setting": sing_setting(d, shot_id), "vocal_heard": round(_vocal_heard(d, shot), 1), "inputs": model_inputs(refs, payload, man, sung), "prompt_blocks": prompt_blocks, "audio_first": af, "lip_sync_mode": project.get("lip_sync_mode") or "first_frame",
            # the song's audio would be followed, but the keyframe is the first frame and this model refuses both: the screen says so and offers the other mode
            "keyframe_blocks_audio": bool(kind == "video" and kf and not sung and not native and "ref_audio" in man["roles"] and _exclusive_model(man) and singing(d, shot, plan)
                                          and project.get("lip_sync", "auto") != "off")}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="filmcrafter-render")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog"); c.add_argument("--provider", required=True); c.add_argument("--kind", default="video"); c.add_argument("--refresh", action="store_true")
    m = sub.add_parser("manifest"); m.add_argument("--provider", required=True); m.add_argument("--model", required=True)
    m.add_argument("--refresh", action="store_true")
    for name in ("preview", "enqueue"):
        s = sub.add_parser(name)
        s.add_argument("project"); s.add_argument("--shots", required=True); s.add_argument("--provider", required=True)
        s.add_argument("--model"); s.add_argument("--overrides", default="{}"); s.add_argument("--fix-notes", default="[]")
        s.add_argument("--kind", default="video", choices=["video", "image", "lipsync"]); s.add_argument("--source-job")
    r = sub.add_parser("run"); r.add_argument("project")
    es = sub.add_parser("estimate"); es.add_argument("project"); es.add_argument("--shots", required=True)
    es.add_argument("--provider", required=True); es.add_argument("--model"); es.add_argument("--kind", default="video")
    rb = sub.add_parser("backlog"); rb.add_argument("project"); rb.add_argument("--run", action="store_true")
    rs = sub.add_parser("resolve"); rs.add_argument("project"); rs.add_argument("--job", required=True)
    rs.add_argument("--action", choices=["retry", "dismiss", "accept", "recheck", "cancel"], required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "catalog":
            emit(event="result", data=catalog(a.provider, a.kind, a.refresh))
        elif a.cmd == "manifest":
            emit(event="result", data=manifest(a.provider, a.model, a.refresh))
        elif a.cmd == "preview":
            emit(event="result", data=preview(a.project, a.shots.split(",")[0], a.provider, a.model, json.loads(a.overrides), a.kind))
        elif a.cmd == "enqueue":
            emit(event="result", data=enqueue(a.project, a.shots.split(","), a.provider, a.model, json.loads(a.overrides),
                                              json.loads(a.fix_notes), a.kind, a.source_job))
        elif a.cmd == "run":
            run(a.project)
        elif a.cmd == "estimate":
            emit(event="result", data=estimate(a.project, a.shots.split(","), a.provider, a.model, a.kind))
        elif a.cmd == "backlog":   # count (free), or review them (--run: one AI look per take)
            if a.run:
                review_pending(a.project)
            emit(event="result", data={"unchecked": review_backlog_count(a.project)})
        elif a.cmd == "resolve":
            emit(event="result", data=resolve(a.project, a.job, a.action))
    except SystemExit as e:
        emit(event="error", message=str(e))
        return 1
    except Exception as e:  # readable failure for the app
        emit(event="error", message=__import__("filmcrafter_engine.errtext", fromlist=["plain"]).plain(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
