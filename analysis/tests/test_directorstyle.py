import json
from filmcrafter_engine import directorstyle as D
from filmcrafter_engine.filmmakers import LIBRARY


def proj(tmp_path, extra=None):
    d = tmp_path / "p"; d.mkdir(); (d / "project.json").write_text(json.dumps({"title": "P", "look": {"style": "stop-motion"}, "story": "unchanged", **(extra or {})}), encoding="utf-8"); return str(d)


def test_worldwide_library_contains_requested_filmmakers(tmp_path):
    out = D.list_styles(proj(tmp_path)); names = {x["name"] for x in out["styles"]}; regions = {x["region"] for x in out["styles"]}
    assert {"Ryan Coogler", "Christopher Nolan", "Denis Villeneuve", "Kemi Adetiba", "Park Chan-wook", "Hype Williams"} <= names
    assert {"Africa", "Asia", "Europe", "Latin America", "North America", "Music video"} <= regions
    assert len(LIBRARY) >= 60


def test_selecting_is_optional_and_changes_no_look_story_or_timing(tmp_path):
    d = proj(tmp_path, {"timing": {"fps": 24}}); before = json.load(open(d + "/project.json"))
    got = D.set_style(d, "christopher-nolan"); after = json.load(open(d + "/project.json"))
    assert got["name"] == "Christopher Nolan" and after["look"] == before["look"] and after["story"] == before["story"] and after["timing"] == before["timing"]
    D.clear(d); assert "director_style" not in json.load(open(d + "/project.json"))


def test_only_traits_not_a_person_name_are_in_the_prompt_payload(tmp_path):
    d = proj(tmp_path); D.set_style(d, "ryan-coogler"); saved = json.load(open(d + "/project.json"))["director_style"]
    payload = " ".join(saved["traits"].values())
    assert saved["name"] == "Ryan Coogler" and "Ryan Coogler" not in payload and "Coogler" not in payload
