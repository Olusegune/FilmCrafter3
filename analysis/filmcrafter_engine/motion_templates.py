"""Built-in motion graphics: ready-made titles, lower thirds, callouts and cards, each a few ordinary layers put down together at the moment you choose.

Each template is the same thing a template you save yourself is: a few layers (text, shapes, icons, tints) with their looks, movements and timing relative to each other (see layerkit.py). Nothing
here is a picture or a video: the words are yours (each template has one or two text slots you fill in), and once put down they are ordinary layers you can edit, restyle, move, retime or delete,
and take away again as one group. They are drawn by FilmCrafter itself when the film is made, so they stay sharp at any size and cost nothing.

  python -m filmcrafter_engine.layerkit <builtin_list|builtin_apply> <project> --data '{...}'
"""
from __future__ import annotations

import re
import uuid

SLOT_MAX = 60
MAX_SECONDS = 30.0


def _t(text: str, **kw) -> dict:
    return {"kind": "text", "text": text, **kw}


# id -> name, what it is for, the words you fill in, how long it lasts, and its layers (look, offset in seconds from the start, length in seconds)
BUILTIN: list[dict] = [
    {"id": "lower_third", "name": "Lower third", "use": "A name and a role at the bottom of the picture, for whoever has just appeared.", "seconds": 4.5,
     "slots": [{"id": "name", "label": "Name", "default": "Sarah Okafor"}, {"id": "role", "label": "Role or place", "default": "Head nurse"}],
     "layers": [
         {"offset": 0.0, "length": 4.5, "look": {"kind": "shape", "shape": "rounded", "x": 0.28, "y": 0.84, "width": 0.44, "height": 0.13, "color": "#0e141b", "opacity": 0.78, "filled": True, "anim": "slide_right", "shadow": False}},
         {"offset": 0.1, "length": 4.4, "look": {"kind": "shape", "shape": "line", "x": 0.28, "y": 0.905, "width": 0.44, "height": 0.006, "color": "#e8b45c", "anim": "wipe", "shadow": False}},
         {"offset": 0.25, "length": 4.25, "look": _t("{name}", x=0.28, y=0.82, size=0.05, color="#ffffff", anim="slide_right", shadow=True)},
         {"offset": 0.45, "length": 4.05, "look": _t("{role}", x=0.28, y=0.87, size=0.032, color="#e8b45c", anim="fade", shadow=True)}]},
    {"id": "title_card", "name": "Title card", "use": "The film's title over a dark tint, with a line underneath.", "seconds": 6.0,
     "slots": [{"id": "title", "label": "Title", "default": "The Last Train"}, {"id": "line", "label": "Line under it", "default": "A short film"}],
     "layers": [
         {"offset": 0.0, "length": 6.0, "look": {"kind": "fill", "color": "#000000", "opacity": 0.55, "anim": "fade"}},
         {"offset": 0.6, "length": 5.0, "look": _t("{title}", x=0.5, y=0.46, size=0.11, color="#ffffff", anim="zoom_in", shadow=True, glow=0.35, glow_color="#ffd9a0")},
         {"offset": 1.4, "length": 4.2, "look": _t("{line}", x=0.5, y=0.58, size=0.04, color="#e8b45c", anim="rise", shadow=True)}]},
    {"id": "chapter_title", "name": "Chapter title", "use": "A small label and a chapter name, typed in.", "seconds": 5.0,
     "slots": [{"id": "label", "label": "Label", "default": "CHAPTER ONE"}, {"id": "title", "label": "Chapter name", "default": "The Name on the Chart"}],
     "layers": [
         {"offset": 0.0, "length": 5.0, "look": _t("{label}", x=0.5, y=0.43, size=0.035, color="#e8b45c", anim="fade", shadow=True)},
         {"offset": 0.5, "length": 4.5, "look": _t("{title}", x=0.5, y=0.52, size=0.08, color="#ffffff", anim="typewriter", shadow=True)},
         {"offset": 0.9, "length": 4.1, "look": {"kind": "shape", "shape": "line", "x": 0.5, "y": 0.6, "width": 0.18, "height": 0.004, "color": "#e8b45c", "anim": "wipe", "shadow": False}}]},
    {"id": "location_tag", "name": "Place and time", "use": "Where and when, small and typed, in the corner.", "seconds": 4.0,
     "slots": [{"id": "place", "label": "Place and time", "default": "ST. MARY'S HOSPITAL, 3:12 AM"}],
     "layers": [
         {"offset": 0.0, "length": 4.0, "look": _t("{place}", x=0.25, y=0.09, size=0.032, color="#ffffff", anim="typewriter", shadow=True)}]},
    {"id": "callout", "name": "Callout", "use": "Point at something: a label in a box with an arrow.", "seconds": 4.0,
     "slots": [{"id": "text", "label": "Label", "default": "Look here"}],
     "layers": [
         {"offset": 0.0, "length": 4.0, "look": {"kind": "shape", "shape": "rounded", "x": 0.7, "y": 0.3, "width": 0.24, "height": 0.1, "color": "#e8b45c", "opacity": 0.95, "filled": True, "anim": "pop", "shadow": True}},
         {"offset": 0.15, "length": 3.85, "look": _t("{text}", x=0.7, y=0.3, size=0.04, color="#101820", anim="fade", shadow=False)},
         {"offset": 0.3, "length": 3.7, "look": {"kind": "icon", "icon": "arrow", "x": 0.62, "y": 0.4, "width": 0.07, "color": "#e8b45c", "rotation": 135, "anim": "bounce", "shadow": True}}]},
    {"id": "quote", "name": "Quote", "use": "A line someone said, with who said it.", "seconds": 6.0,
     "slots": [{"id": "quote", "label": "The words", "default": "I am fine."}, {"id": "who", "label": "Said by", "default": "Sarah"}],
     "layers": [
         {"offset": 0.0, "length": 6.0, "look": {"kind": "fill", "color": "#000000", "opacity": 0.4, "anim": "fade"}},
         {"offset": 0.4, "length": 5.2, "look": _t("“{quote}”", x=0.5, y=0.47, size=0.075, color="#ffffff", anim="fade", shadow=True)},
         {"offset": 1.2, "length": 4.4, "look": _t("{who}", x=0.5, y=0.6, size=0.04, color="#e8b45c", anim="rise", shadow=True)}]},
    {"id": "big_number", "name": "Big number", "use": "One number that matters, with what it means.", "seconds": 5.0,
     "slots": [{"id": "number", "label": "Number", "default": "86%"}, {"id": "what", "label": "What it is", "default": "of patients never learn the name"}],
     "layers": [
         {"offset": 0.0, "length": 5.0, "look": _t("{number}", x=0.5, y=0.44, size=0.2, color="#e8b45c", anim="pop", shadow=True, glow=0.4, glow_color="#e8b45c")},
         {"offset": 0.7, "length": 4.3, "look": _t("{what}", x=0.5, y=0.62, size=0.042, color="#ffffff", anim="rise", shadow=True)}]},
    {"id": "end_card", "name": "End card", "use": "The end, with a closing line.", "seconds": 6.0,
     "slots": [{"id": "end", "label": "Words", "default": "The End"}, {"id": "line", "label": "Closing line", "default": "Thank you for watching"}],
     "layers": [
         {"offset": 0.0, "length": 6.0, "look": {"kind": "fill", "color": "#000000", "opacity": 0.8, "anim": "fade"}},
         {"offset": 0.5, "length": 5.2, "look": _t("{end}", x=0.5, y=0.46, size=0.09, color="#ffffff", anim="fade", shadow=True)},
         {"offset": 1.4, "length": 4.3, "look": _t("{line}", x=0.5, y=0.58, size=0.036, color="#e8b45c", anim="rise", shadow=True)}]},
]


def _by_id(tid: str) -> dict:
    t = next((x for x in BUILTIN if x["id"] == tid), None)
    if not t:
        raise SystemExit("That motion graphic is not one of the built-in ones.")
    return t


def list_builtin() -> dict:
    return {"templates": [{"id": t["id"], "name": t["name"], "use": t["use"], "seconds": t["seconds"], "layers": len(t["layers"]), "slots": t["slots"]} for t in BUILTIN]}


def _slot_text(raw, default: str) -> str:
    s = " ".join(str(raw if raw is not None else default).split())[:SLOT_MAX]
    return s or default


def build(tid: str, texts: dict | None) -> dict:
    """The template with the person's words in its slots, as the layer list `layerkit` puts down. Only text slots are filled; nothing else in a layer is taken from what was typed."""
    t = _by_id(tid)
    texts = texts if isinstance(texts, dict) else {}
    words = {s["id"]: _slot_text(texts.get(s["id"]), s["default"]) for s in t["slots"]}
    layers = []
    for l in t["layers"]:
        look = dict(l["look"])
        if isinstance(look.get("text"), str):
            look["text"] = re.sub(r"\{(\w+)\}", lambda m: words.get(m.group(1), ""), look["text"])
        layers.append({"look": look, "offset": l["offset"], "length": l["length"]})
    return {"name": t["name"], "layers": layers, "seconds": t["seconds"]}


def preview(d: str, tid: str, texts: dict | None = None, W: int = 640, H: int = 360) -> dict:
    """A picture of the template with your words, as it looks once it has settled (movement is not shown), over a plain dark frame. Made by the same code that draws it in the film."""
    import hashlib
    import json
    import os
    from PIL import Image
    from . import overlays as O
    t = build(tid, texts)
    key = hashlib.sha256(json.dumps([t["layers"], W, H], sort_keys=True, default=str).encode()).hexdigest()[:16]
    out = os.path.join(d, "cache", "motion_preview", f"{tid}-{key}.png")
    if not os.path.isfile(out):
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        top, bottom = (74, 88, 108), (38, 46, 60)
        for y in range(H):
            k = y / max(1, H - 1)
            frame.paste(tuple(round(a + (b - a) * k) for a, b in zip(top, bottom)) + (255,), (0, y, W, y + 1))
        for l in t["layers"]:
            o = O._clean(d, {**l["look"], "start": 0.0, "end": 1.0})
            path, size = O.render_png(d, o, W, H)
            with Image.open(path) as im:
                if o.get("kind") == "fill":
                    frame.alpha_composite(im.convert("RGBA").resize((W, H)))
                else:
                    frame.alpha_composite(im.convert("RGBA"), O._position(o, size, W, H))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = f"{out}.{os.getpid()}.part.png"
        frame.convert("RGB").save(tmp)
        os.replace(tmp, out)
    return {"path": os.path.relpath(out, d).replace(os.sep, "/"), "id": tid}


def apply_builtin(d: str, tid: str, at, texts: dict | None = None) -> dict:
    from . import layerkit
    return layerkit.put_template(d, build(tid, texts), at)
