"""The timeline of "He Is Risen": camera, models, lights and sky as keyframes for the WorldLock animation renderer (`filmcrafter_engine.worldanim`).

Six beats in 60 seconds (hard cuts are a pair of keys with `hold`):
   0-10  Golgotha, late afternoon     slow push toward the crosses; the sky darkens                        (Jesus V.O. "It is finished.")
  10-20  Golgotha, dusk                the earthquake: shake, falling rocks, lightning flashes
  20-28  Garden tomb, night            the sealed tomb under a deep blue sky; a slow dolly
  28-38  Garden tomb, dawn             a second quake; the angel descends; the stone rolls away; light pours out
  38-50  Garden tomb, morning          Mary arrives and stops at the open tomb                              (Angel; Mary)
  50-60  Garden, sunrise               Jesus in the light; Mary turns; a slow pull-back over the hill       (Jesus; Mary) and the title
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

CUT = "hold"


def cam(t, x, y, z, yaw, pitch=0.0, fov=58.0, ease="smooth"):
    return {"t": t, "x": x, "y": y, "z": z, "yaw": yaw, "pitch": pitch, "fov": fov, "ease": ease}


def build(ids: dict, fps: int = 24, size=(1280, 720)) -> dict:
    """`ids` maps the short names (hill, mary, angel, jesus, stone, rock0...) to the model ids made by setup_film.py."""
    m = lambda k: ids[k]
    stone0 = (14.6, 0.0, 17.9)
    tomb_open = (14.7, 19.2)
    camera = [
        # 1. Golgotha, late afternoon: from low and far, a slow push toward the three crosses
        cam(0.0, -4.0, 1.9, -2.0, -8, 6, 60, "smooth"), cam(9.99, -12.0, 2.6, 14.0, -3, 9, 55, CUT),
        # 2. The earthquake: the camera on the slope, looking up at the crosses
        cam(10.0, -22.0, 1.5, 14.0, 18, 11, 62, "smooth"), cam(19.99, -17.0, 1.8, 19.0, 8, 13, 60, CUT),
        # 3. Night at the tomb: a slow dolly in on the stone
        cam(20.0, 5.0, 1.6, 4.0, 18, 3, 56, "smooth"), cam(27.99, 10.5, 1.5, 12.5, 14, 2, 52, CUT),
        # 4. Dawn: the quake and the angel; the camera low, then it rises as the stone rolls
        cam(28.0, 8.0, 1.2, 8.0, 12, 5, 58, "smooth"), cam(32.0, 9.0, 1.6, 9.5, 12, 9, 56, "smooth"), cam(37.99, 10.5, 2.4, 11.0, 8, 10, 52, CUT),
        # 5. Morning: tracking Mary as she walks to the tomb, then a close view of her stopped at the opening
        cam(38.0, 2.0, 1.5, 4.5, 38, 2, 54, "smooth"), cam(44.0, 7.0, 1.55, 9.0, 34, 3, 50, "smooth"), cam(49.99, 9.5, 1.5, 11.5, 30, 3, 44, CUT),
        # 6. Sunrise: Jesus in the garden light; a slow pull back to show the hill, the crosses and the tomb in gold
        cam(50.0, 0.0, 1.5, 7.5, 6, 3, 50, "smooth"), cam(55.0, 0.5, 2.4, 3.0, 8, 5, 56, "smooth"), cam(60.0, -2.0, 4.0, -6.0, 0, 8, 68, "smooth"),
    ]
    shake = [
        {"t0": 10.3, "t1": 18.4, "amount": 0.16, "turn": 0.9, "hz": 8.5},
        {"t0": 28.2, "t1": 32.6, "amount": 0.11, "turn": 0.6, "hz": 9.0},
        {"t0": 36.0, "t1": 37.2, "amount": 0.03, "turn": 0.15, "hz": 7.0},
    ]
    # lights: the sun's colour and strength carry the mood
    sun = [
        {"t": 0, "azimuth": 200, "elevation": 22, "colour": "#e0a86a", "intensity": 1.087, "ease": "smooth"},
        {"t": 9, "colour": "#8f7f9a", "intensity": 0.652, "elevation": 12, "ease": "smooth"},
        {"t": 10, "colour": "#6d6a86", "intensity": 0.58, "elevation": 10, "ease": "hold"},
        # lightning flashes during the quake
        {"t": 11.0, "colour": "#cfd9ff", "intensity": 2.175, "elevation": 40, "ease": "linear"}, {"t": 11.15, "colour": "#6d6a86", "intensity": 0.551, "elevation": 10, "ease": "linear"},
        {"t": 13.4, "colour": "#cfd9ff", "intensity": 2.32, "elevation": 45, "ease": "linear"}, {"t": 13.6, "colour": "#6d6a86", "intensity": 0.522, "elevation": 10, "ease": "linear"},
        {"t": 16.0, "colour": "#e8eeff", "intensity": 2.61, "elevation": 50, "ease": "linear"}, {"t": 16.2, "colour": "#6d6a86", "intensity": 0.493, "elevation": 10, "ease": "smooth"},
        {"t": 19.9, "colour": "#4a5a8c", "intensity": 0.435, "elevation": 20, "ease": "hold"},
        # night: moonlight
        {"t": 20, "azimuth": 150, "elevation": 38, "colour": "#6f86c9", "intensity": 0.609, "ease": "smooth"}, {"t": 27.9, "colour": "#6f86c9", "intensity": 0.609, "ease": "hold"},
        # dawn: the light grows from the tomb
        {"t": 28, "azimuth": 190, "elevation": 8, "colour": "#9a7aa0", "intensity": 0.652, "ease": "smooth"}, {"t": 33, "elevation": 14, "colour": "#ffcf8a", "intensity": 1.45, "ease": "smooth"},
        {"t": 37.9, "elevation": 20, "colour": "#ffd9a0", "intensity": 1.45, "ease": "hold"},
        # morning, then sunrise gold
        {"t": 38, "azimuth": 200, "elevation": 26, "colour": "#ffe0b0", "intensity": 1.45, "ease": "smooth"}, {"t": 49.9, "elevation": 30, "colour": "#ffe0b0", "intensity": 1.45, "ease": "hold"},
        {"t": 50, "azimuth": 215, "elevation": 12, "colour": "#ffc470", "intensity": 1.667, "ease": "smooth"}, {"t": 60, "elevation": 16, "colour": "#ffd890", "intensity": 1.74},
    ]
    fill = [
        {"t": 0, "colour": "#8aa0d8", "intensity": 0.406, "ease": "smooth"}, {"t": 20, "colour": "#5068b0", "intensity": 0.435, "ease": "hold"},
        {"t": 28, "colour": "#a58cc0", "intensity": 0.406, "ease": "smooth"}, {"t": 38, "colour": "#c8d4ff", "intensity": 0.58, "ease": "hold"},
        {"t": 50, "colour": "#ffd6a0", "intensity": 0.58},
    ]
    sky = [
        {"t": 0, "top": "#1c2036", "horizon": "#8a6a52", "fog": 0.010, "ease": "smooth"},
        {"t": 9.9, "top": "#14172b", "horizon": "#5b4f58", "fog": 0.014, "ease": "hold"},
        {"t": 10, "top": "#0d1020", "horizon": "#3d3a52", "fog": 0.016, "ease": "hold"},
        {"t": 19.9, "top": "#0a0d1c", "horizon": "#32334b", "fog": 0.016, "ease": "hold"},
        {"t": 20, "top": "#050813", "horizon": "#162040", "fog": 0.012, "ease": "smooth"}, {"t": 27.9, "top": "#060a18", "horizon": "#1b274a", "fog": 0.012, "ease": "hold"},
        {"t": 28, "top": "#14183a", "horizon": "#6c4a6a", "fog": 0.012, "ease": "smooth"}, {"t": 36, "top": "#2d3f78", "horizon": "#f0a870", "fog": 0.010, "ease": "smooth"},
        {"t": 37.9, "top": "#35508f", "horizon": "#f6c48a", "fog": 0.009, "ease": "hold"},
        {"t": 38, "top": "#4c76b8", "horizon": "#f9d9a8", "fog": 0.008, "ease": "smooth"}, {"t": 49.9, "top": "#5a86c4", "horizon": "#fbe2b8", "fog": 0.008, "ease": "hold"},
        {"t": 50, "top": "#3e5f9c", "horizon": "#ffb866", "fog": 0.009, "ease": "smooth"}, {"t": 60, "top": "#4a74b6", "horizon": "#ffd08a", "fog": 0.009},
    ]
    ambient = [{"t": 0, "v": 0.50, "ease": "smooth"}, {"t": 9.9, "v": 0.42, "ease": "hold"}, {"t": 10, "v": 0.36, "ease": "hold"}, {"t": 19.9, "v": 0.34, "ease": "hold"},
               {"t": 20, "v": 0.30, "ease": "smooth"}, {"t": 27.9, "v": 0.30, "ease": "hold"}, {"t": 28, "v": 0.34, "ease": "smooth"}, {"t": 36, "v": 0.5, "ease": "smooth"}, {"t": 38, "v": 0.58, "ease": "hold"}, {"t": 50, "v": 0.55}]
    models = {
        # visibility: figures appear only when the story needs them
        # model yaw = the direction it faces (as a camera yaw) + 180, because glTF fronts are mirrored to face -Z
        m("mary"): [
            {"t": 0, "visible": False, "ease": "hold"}, {"t": 37.9, "visible": True, "x": 3.2, "y": 0.0, "z": 7.0, "yaw": -131, "ease": "linear"},
            {"t": 44.0, "x": 11.0, "z": 14.0, "yaw": -131, "ease": "smooth"}, {"t": 46.5, "x": 11.6, "z": 15.4, "yaw": -155, "ease": "hold"},
            {"t": 52.0, "x": 11.6, "z": 15.4, "yaw": -155, "ease": "smooth"}, {"t": 54.0, "x": 11.6, "z": 15.4, "yaw": 70},
        ],
        m("angel"): [
            {"t": 0, "visible": False, "ease": "hold"}, {"t": 28.9, "visible": True, "x": 12.0, "y": 9.0, "z": 16.6, "yaw": 0, "scale": 1.0, "ease": "smooth"},
            {"t": 32.0, "y": 0.0, "ease": "smooth"}, {"t": 37.0, "y": 0.0, "x": 12.0, "ease": "hold"}, {"t": 49.9, "y": 0.0, "ease": "hold"}, {"t": 50.0, "visible": False},
        ],
        m("jesus"): [
            {"t": 0, "visible": False, "ease": "hold"}, {"t": 50.0, "visible": True, "x": 6.0, "y": 0.0, "z": 13.5, "yaw": -30, "ease": "smooth"}, {"t": 60, "x": 6.0, "z": 13.0, "yaw": -30},
        ],
        m("stone"): [
            {"t": 0, "x": stone0[0], "z": stone0[2], "yaw": -14, "roll": 0, "ease": "hold"},
            {"t": 31.0, "x": stone0[0], "z": stone0[2], "roll": 0, "ease": "smooth"}, {"t": 35.0, "x": stone0[0] + 3.8, "z": stone0[2], "roll": -150},
        ],
    }
    # rocks fall from the hill and roll toward the camera during the quake (start places are those of setup_film.py)
    for i, (x0, y0, z0, t0) in enumerate(((-22, 2.0, 30, 11.0), (-9, 2.0, 29, 12.4), (-17, 3.2, 28.5, 14.0), (-12, 3.2, 31, 15.2))):
        models[m(f"rock{i}")] = [{"t": t0, "x": x0, "y": y0, "z": z0, "roll": 0, "pitch": 0, "ease": "smooth"},
                                 {"t": t0 + 1.7, "x": x0 + (2.5 if i % 2 else -2.5), "y": 0.25, "z": z0 - 5.0, "roll": 110 * (1 if i % 2 else -1), "pitch": 70}]
    return {"name": "he-is-risen", "fps": fps, "seconds": 60.0, "size": list(size), "camera": camera, "shake": shake,
            "lights": {"Sun": sun, "Sky fill": fill}, "sky": sky, "ambient": ambient, "models": models, "crf": 16}


if __name__ == "__main__":
    w = json.load(open(os.path.join(os.path.dirname(HERE), "..", "..", "film_work", "film.json")))
    print(json.dumps(build(w["ids"])["camera"][:2]))
