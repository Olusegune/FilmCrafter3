"""Vocal performance plans: cleaning, compiling for a model, saving, and making the compiled words the spoken version. Nothing is spoken, sent or paid for."""
import json
import os

import pytest

from filmcrafter_engine import bible, cast_voice as C, performplan as P, shots, story, voicedirect as VD, voiceover as V

SCRIPT = "INT. YARD - DAY\n\nA schoolyard.\n\nLILA\nIt looked weird.\n\nCHLOE\n(quietly)\nI know.\n\nLILA\nSee?\n"
LINE = "I did not think you would come back"          # 8 words
V4, V2 = "eleven_v4", "eleven_multilingual_v2"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the network was used")
    monkeypatch.setattr(C, "_get", boom)
    monkeypatch.setattr(C, "_post", boom)


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    shots.breakdown(d)
    return d


@pytest.fixture
def line(film):
    """A shot and a person who speak, with the long test line set as their spoken version."""
    for s in V.status(film)["shots"]:
        for p in s["people"]:
            if p["lines"]:
                VD.set_performance(film, s["id"], p["name"], LINE)
                return film, s["id"], p["name"]
    raise AssertionError("no spoken line in the test film")


def comp(plan, model=V4, text=LINE):
    return P.compile(plan, text, model)


# ---------------------------------------------------------------- cleaning

def test_a_plan_keeps_only_what_is_allowed_and_in_range():
    c = P.clean({"arc": [{"at": 99, "emotion": "x"}, {"at": 2, "emotion": "A <script>[bad]</script>", "intensity": 7}, {"at": 2, "emotion": "dup"}, {"at": 0, "emotion": ""}, "junk"],
                 "events": [{"kind": "explode", "after_word": 1}, {"kind": "gasp", "after_word": -5, "intensity": "nan"}, {"kind": "laugh", "after_word": 3}],
                 "pauses": [{"after_word": 0, "ms": 5}, {"after_word": 2, "ms": 99999}], "emphasis": [1, 1, 50, "x"], "pace": 9, "physical": {"activity": "flying", "effort": 5, "pain": "x"}}, 5)
    assert c["arc"] == [{"at": 2, "emotion": "a scriptbadscript", "intensity": 1.0}]
    assert [(e["kind"], e["after_word"]) for e in c["events"]] == [("laugh", 3)]          # a position outside the line is dropped, not moved
    assert c["pauses"] == [{"after_word": 2, "ms": 3000}] and c["emphasis"] == [1]
    assert c["pace"] == 1.2 and c["physical"]["activity"] == "still" and c["physical"]["effort"] == 1.0 and c["physical"]["pain"] == 0.0 and c["approved"] is False


def test_lists_are_capped_and_text_is_limited():
    big = P.clean({"arc": [{"at": i % 10, "emotion": f"e{i}"} for i in range(400)], "events": [{"kind": "sigh", "after_word": i % 10} for i in range(400)], "objective": "x" * 5000}, 10)
    assert len(big["arc"]) <= P.MAX_ARC and len(big["events"]) <= P.MAX_EVENTS and len(big["objective"]) == P.NOTE
    assert P.clean(None, 3)["arc"] == [] and P.clean("nonsense", 3)["pace"] == 1.0


def test_words_ignore_tags_and_brackets():
    assert P.words_of("[sighs] I know [laughs nervously] it.") == ["I", "know", "it."]
    assert P.words_of("a [b c") == ["a", "b", "c"]


# ---------------------------------------------------------------- compiling

def test_a_feeling_that_changes_mid_line_becomes_tags_at_the_right_gaps():
    c = comp({"arc": [{"at": 0, "emotion": "confident"}, {"at": 4, "emotion": "scared"}], "events": [{"kind": "gasp", "after_word": 4}]})
    assert c["text"] == "[confident] I did not think [scared] [gasps] you would come back"
    assert c["tags"] == ["confident", "scared", "gasps"] and c["unverified"] == ["confident", "scared"] and c["not_carried"] == []


def test_a_neutral_start_and_a_repeated_feeling_add_nothing():
    c = comp({"arc": [{"at": 0, "emotion": "neutral"}, {"at": 3, "emotion": "neutral"}, {"at": 5, "emotion": "sad"}, {"at": 6, "emotion": "sad"}]})
    assert c["text"].count("[") == 1 and c["text"] == "I did not think you [sad] would come back"


def test_pauses_emphasis_and_sounds_land_on_the_right_words():
    c = comp({"pauses": [{"after_word": 3, "ms": 600}, {"after_word": 8, "ms": 2000}], "emphasis": [2], "events": [{"kind": "laugh", "after_word": 8}, {"kind": "sigh", "after_word": 0}]})
    assert c["text"] == "[sighs] I did NOT... think you would come back ... ... [laughs]"
    assert c["unverified"] == [] and c["tags"] == ["laughs", "sighs"] or set(c["tags"]) == {"laughs", "sighs"}


def test_the_body_changes_the_voice_for_a_model_that_can_be_directed():
    c = comp({"physical": {"activity": "running", "breathlessness": 0.8, "effort": 0.6, "fatigue": 0.6}, "pace": 1.0})
    assert c["text"].startswith("[out of breath] [straining] [tired] ") and "straining" in c["unverified"] and "out of breath" not in c["unverified"]
    assert c["speed"] == round(1.0 - 0.06 - 0.04, 2)
    assert comp({"physical": {"activity": "still", "effort": 0.2}})["text"] == LINE


def test_things_a_voice_model_cannot_be_asked_for_are_said_not_faked():
    c = comp({"physical": {"activity": "eating"}})
    assert c["text"] == LINE and any("food in the mouth" in x["what"] for x in c["not_carried"]) and all("Record it" in x["why"] or "cannot" in x["why"] for x in c["not_carried"])


def test_a_model_that_would_speak_tags_aloud_gets_none_and_is_told_what_was_left_out():
    plan = {"arc": [{"at": 0, "emotion": "sad"}, {"at": 4, "emotion": "angry"}], "events": [{"kind": "gasp", "after_word": 4}], "emphasis": [1], "pauses": [{"after_word": 2, "ms": 800}],
            "physical": {"activity": "running", "breathlessness": 0.9}}
    c = comp(plan, V2)
    assert "[" not in c["text"] and c["tagged"] is False and c["text"] == "I did... not think you would come back"
    left = " | ".join(x["what"] for x in c["not_carried"])
    assert "feeling \"sad\"" in left and "gasp after word 4" in left and "emphasis" in left and "effort, breathlessness" in left
    assert all(x["why"] for x in c["not_carried"])


def test_text_that_already_has_tags_is_planned_from_its_plain_words():
    c = P.compile({"arc": [{"at": 1, "emotion": "sad"}]}, "[whispers] I know [sighs] it", V4)
    assert c["words"] == ["I", "know", "it"] and c["stripped_tags"] == 2 and c["text"] == "I [sad] know it"


def test_a_line_that_grows_too_long_is_refused_not_cut():
    long = " ".join(["word"] * 400)
    with pytest.raises(SystemExit, match="over the 1500"):
        P.compile({"events": [{"kind": "laugh", "after_word": i} for i in range(30)]}, long, V4)


def test_a_feeling_in_the_persons_own_words_is_passed_on_and_marked_unchecked():
    c = comp({"arc": [{"at": 0, "emotion": "tired but trying to smile"}]})
    assert c["text"].startswith("[tired but trying to smile] ") and "tired but trying to smile" in c["unverified"]


# ---------------------------------------------------------------- saving and applying

def test_saving_a_plan_changes_neither_the_written_line_nor_the_spoken_version(line):
    d, sid, who = line
    written = VD._written(d, sid, V.key_of(who))[0]
    r = P.set_plan(d, sid, who, {"arc": [{"at": 0, "emotion": "sad"}], "events": [{"kind": "sigh", "after_word": 0}]}, V4)
    assert r["saved"] and r["applied"] is False and r["compiled"]["text"].startswith("[sad] [sighs] ")
    assert VD.performance_text(d, sid, V.key_of(who)) == LINE and VD._written(d, sid, V.key_of(who))[0] == written


def test_applying_needs_a_saved_approved_plan_and_then_sets_the_spoken_version_only(line):
    d, sid, who = line
    with pytest.raises(SystemExit, match="Save the plan first"):
        P.apply(d, sid, who, V4)
    P.set_plan(d, sid, who, {"events": [{"kind": "gasp", "after_word": 2}]}, V4)
    with pytest.raises(SystemExit, match="Approve the plan"):
        P.apply(d, sid, who, V4)
    P.set_plan(d, sid, who, {"events": [{"kind": "gasp", "after_word": 2}], "approved": True, "objective": "stop her leaving"}, V4)
    r = P.apply(d, sid, who, V4)
    assert r["spoken_version"] == "I did [gasps] not think you would come back" and r["applied"] is True
    assert VD.performance_text(d, sid, V.key_of(who)) == r["spoken_version"]
    assert VD.get_performance(d)["lines"][0]["note"].startswith("Performance plan: stop her leaving")
    assert not os.path.isdir(os.path.join(d, "voice", "_generated"))                     # nothing was spoken


def test_a_plan_made_for_other_words_is_flagged_and_will_not_be_applied(line):
    d, sid, who = line
    P.set_plan(d, sid, who, {"events": [{"kind": "gasp", "after_word": 7}], "approved": True}, V4)
    VD.set_performance(d, sid, who, "Short now")
    g = P.get(d, sid, who, V4)
    assert g["stale"] is True
    with pytest.raises(SystemExit, match="changed after the plan was made"):
        P.apply(d, sid, who, V4)


def test_the_plan_is_compiled_for_the_voices_own_model_unless_told_otherwise(line):
    d, sid, who = line
    C.set_voice(d, who, {"voice_id": "AbCdEfGh1234", "voice_name": "V", "model": V2})
    P.set_plan(d, sid, who, {"events": [{"kind": "laugh", "after_word": 2}]})
    g = P.get(d, sid, who)
    assert g["compiled"]["model"] == V2 and g["compiled"]["tagged"] is False and "[" not in g["compiled"]["text"]
    assert P.get(d, sid, who, V4)["compiled"]["tagged"] is True


def test_the_vocabulary_says_which_tags_have_been_checked(line):
    d, sid, who = line
    g = P.get(d, sid, who, V4)
    assert g["events"]["gasp"]["verified"] is True and g["events"]["grunt"]["verified"] is False and g["events"]["gasp"]["group"] == "emotion"
    assert g["emotions"]["whisper"]["verified"] is True and "running" in g["activities"]


def test_clearing_forgets_the_plan_but_not_the_spoken_version(line):
    d, sid, who = line
    P.set_plan(d, sid, who, {"events": [{"kind": "gasp", "after_word": 2}], "approved": True}, V4)
    P.apply(d, sid, who, V4)
    r = P.clear(d, sid, who)
    assert r["saved"] is False and VD.performance_text(d, sid, V.key_of(who)).startswith("I did [gasps]")
    assert P._load(d)["lines"] == {}


def test_bad_names_are_refused(line):
    d, sid, who = line
    for bad in ("../x", "", "a b"):
        with pytest.raises(SystemExit):
            P.get(d, bad, who)
    with pytest.raises(SystemExit, match="Choose who"):
        P.get(d, sid, "")
    with pytest.raises(SystemExit, match="no written line"):
        P.get(d, sid, "Nobody")


def test_the_command_line_answers_with_json(line, capsys):
    d, sid, who = line
    assert P.main(["set", d, "--data", json.dumps({"shot": sid, "speaker": who, "plan": {"events": [{"kind": "sigh", "after_word": 0}], "approved": True}, "model": V4})]) == 0
    assert P.main(["apply", d, "--data", json.dumps({"shot": sid, "speaker": who, "model": V4})]) == 0
    assert P.main(["get", d, "--data", json.dumps({"shot": "../x", "speaker": who})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert [x["event"] for x in lines] == ["result", "result", "error"] and lines[1]["data"]["spoken_version"].startswith("[sighs] I did")
