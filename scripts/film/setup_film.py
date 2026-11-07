"""Makes the FilmCrafter project for "He Is Risen" and its WorldLock set from the generated models. Run once; it is idempotent only in that it refuses to overwrite an existing project.

  python scripts/film/setup_film.py <work folder>
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, HERE)

from filmcrafter_engine import bible, shots as S, story, worldlock as WL  # noqa: E402
import make_assets  # noqa: E402

SCREENPLAY = """HE IS RISEN

EXT. GOLGOTHA - LATE AFTERNOON

Storm clouds over the hill. Three crosses stand against a darkening sky. The wind is the only voice.

JESUS (V.O.)
It is finished.

EXT. GOLGOTHA - DUSK

The earth shakes. Rocks fall from the hill. The sky flashes. The city in the distance trembles.

EXT. GARDEN TOMB - NIGHT

A new tomb cut in the rock. A great stone seals it. Stars. Stillness.

EXT. GARDEN TOMB - DAWN

The earth shakes again. The ANGEL descends and rolls the stone away. Light pours out of the tomb.

EXT. GARDEN TOMB - MORNING

MARY MAGDALENE comes with spices and finds the tomb open. She stops.

ANGEL
He is not here: for he is risen.

MARY MAGDALENE
Where have they laid him?

EXT. GARDEN - SUNRISE

JESUS stands in the garden light. Mary turns.

JESUS
Mary.

MARY MAGDALENE
Rabboni!

Sunrise over the hill, the three crosses, the open tomb.

TITLE: HE IS RISEN
"""


def main(work):
    films = os.path.join(work, "films")
    os.makedirs(films, exist_ok=True)
    assets = os.path.join(work, "assets")
    make_assets.make(assets)
    r = story.create(films, "He Is Risen", "screenplay", SCREENPLAY)
    d = r["dir"]
    bible.seed(d)
    S.breakdown(d)
    sid = WL.create(d, {"name": "Jerusalem: the hill and the garden", "world": {"bounds": {"x": [-40, 40], "y": [0, 30], "z": [-10, 90]}}})["id"]
    add = lambda file, **kw: WL.model_add(d, sid, {"path": os.path.join(assets, file + ".glb"), **kw})["id"]
    ids = {}
    WL.ground_set(d, sid, {"visible": True, "y": 0, "colours": ["#5d6b3d", "#566338"], "extent": 140})
    WL.sky_set(d, sid, {"top": "#1b2238", "horizon": "#6b5a58", "fog": 0.012})
    ids["hill"] = add("hill", name="Golgotha", x=-15, y=0, z=34, scale=1.6)
    ids["cross_c"] = add("cross", name="Cross (centre)", x=-15, y=3.8, z=34, scale=1.0)
    ids["cross_l"] = add("cross_small", name="Cross (left)", x=-19, y=3.7, z=34.5, scale=1.0, yaw=8)
    ids["cross_r"] = add("cross_small", name="Cross (right)", x=-11, y=3.7, z=34.5, scale=1.0, yaw=-8)
    for i, (x, z, s) in enumerate(((-22, 30, 1.4), (-9, 29, 1.0), (-17, 28.5, 0.8), (-12, 31, 0.7))):
        ids[f"rock{i}"] = add("rock", name=f"Rock {i + 1}", x=x, y=2.0 if i < 2 else 3.2, z=z, scale=s)
    ids["tomb"] = add("tomb", name="Garden tomb", x=14, y=0, z=22, yaw=-14, scale=1.5)
    ids["stone"] = add("stone", name="Stone", x=14.6, y=0, z=17.9, scale=1.6, yaw=-14)
    ids["tree1"] = add("tree", name="Olive tree 1", x=4, y=0, z=26, scale=1.6)
    ids["tree2"] = add("tree", name="Olive tree 2", x=24, y=0, z=16, scale=1.4)
    ids["cyp1"] = add("cypress", name="Cypress 1", x=22, y=0, z=24, scale=1.5)
    ids["cyp2"] = add("cypress", name="Cypress 2", x=-4, y=0, z=18, scale=1.3)
    ids["city"] = add("city", name="Jerusalem", x=0, y=0, z=82, scale=1.5)
    ids["boulder"] = add("boulder", name="Boulder", x=8, y=0, z=20, scale=1.1)
    ids["mary"] = add("mary", name="Mary Magdalene", x=3.2, y=0, z=7.0, yaw=-131)
    ids["angel"] = add("angel", name="Angel", x=12.0, y=0, z=16.6, yaw=0)
    ids["jesus"] = add("jesus", name="Jesus", x=6.0, y=0, z=13.5, yaw=-30)
    WL.light_set(d, sid, {"name": "Sun", "azimuth": 200, "elevation": 35, "colour": "#ffd9a0", "intensity": 0.9})
    WL.light_set(d, sid, {"name": "Sky fill", "azimuth": 160, "elevation": 60, "colour": "#9db4ff", "intensity": 0.35})
    json.dump({"film": d, "set": sid, "ids": ids}, open(os.path.join(work, "film.json"), "w"), indent=1)
    print(json.dumps({"film": d, "set": sid}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "film_work")
