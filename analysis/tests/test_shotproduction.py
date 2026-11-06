"""A shot's production mode: a full scene (as before) or a plate made to be keyed. The setting is checked, stored in the shot, and changes the picture prompt the render project gets."""
import pytest

from filmcrafter_engine import bible, make, shots as S, story, vpstudio as V

SCRIPT = "INT. KITCHEN - DAY\n\nSARAH stirs a pot.\n\nSARAH\nBreakfast is ready.\n"


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d, S.view(d)["shots"][0]["id"]


def contract(d, sid):
    return next(c for c in make._contracts(d) if c["id"] == sid)


def visual(d, sid):
    return make._visual(contract(d, sid))


def test_a_shot_with_no_production_setting_is_a_full_scene_and_its_prompt_is_unchanged(film):
    d, sid = film
    assert contract(d, sid).get("production", {}).get("mode", "full") == "full"
    text = visual(d, sid)
    assert "Made as a plate" not in text and "kitchen" in text.lower()                                      # the place is in it, as always
    S.set_fields(d, sid, {"production": {"mode": "full", "screen": "blue"}})
    assert visual(d, sid) == text                                                                           # saying "full scene" changes nothing


def test_a_green_screen_shot_asks_for_a_flat_screen_and_leaves_the_place_out(film):
    d, sid = film
    before = visual(d, sid)
    S.set_fields(d, sid, {"production": {"mode": "green_screen", "screen": "green", "framing": "half", "light": "left", "angle": "low", "movement": "turn"}})
    t = visual(d, sid)
    for w in ("Made as a plate to be keyed", "waist up", "#00B140", "camera left", "low camera angle", "turns slowly", "no green on the subject"):
        assert w in t
    assert "kitchen" not in t.lower().split("made as a plate")[0]                                           # the place is not drawn: the background is put in later
    assert t.startswith(before.split(" In ")[0])                                                            # the action and the people are still first


def test_a_blue_screen_and_a_transparent_shot_are_made_as_plates_too(film):
    d, sid = film
    S.set_fields(d, sid, {"production": {"mode": "transparent", "screen": "blue"}})
    t = visual(d, sid)
    assert "#0047BB" in t and "no blue on the subject" in t


def test_the_setting_is_cleaned_and_junk_falls_back_to_a_full_scene(film):
    d, sid = film
    S.set_fields(d, sid, {"production": {"mode": "layered", "screen": "red", "framing": "x", "light": 5, "angle": None, "movement": ["a"]}})
    assert contract(d, sid)["production"] == {"mode": "full", "screen": "green", "framing": "full", "light": "front", "angle": "eye", "movement": "still"}
    S.set_fields(d, sid, {"production": "junk"})
    assert contract(d, sid)["production"]["mode"] == "full"
    assert V.clean_production(None)["mode"] == "full" and V.MODES == ("full", "green_screen", "transparent")


def test_changing_the_mode_does_not_touch_the_rest_of_the_shot(film):
    d, sid = film
    c0 = contract(d, sid)
    S.set_fields(d, sid, {"production": {"mode": "green_screen"}})
    c1 = contract(d, sid)
    ignore = ("production", "updated", "edited")
    assert {k: v for k, v in c1.items() if k not in ignore} == {k: v for k, v in c0.items() if k not in ignore}
