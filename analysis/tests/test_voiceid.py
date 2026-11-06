"""Voice identity: the profile, the lock that notices a change, listening ratings, the casting comparison and the cast library. Nothing is sent to ElevenLabs and nothing is paid for."""
import json

import pytest

from filmcrafter_engine import bible, cast_voice as C, shots, story, voiceid as VI

SCRIPT = "INT. YARD - DAY\n\nA schoolyard.\n\nLILA\nIt looked weird.\n\nCHLOE\n(quietly)\nI know.\n\nLILA\nSee?\n"
V1, V2 = "AbCdEfGh1234", "ZyXwVu987654"


def make_film(tmp_path, name="films"):
    d = story.create(str(tmp_path / name), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    shots.breakdown(d)
    return d


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """Anything that would reach ElevenLabs fails the test; the cast library lives in the test folder."""
    def boom(*a, **k):
        raise AssertionError("the network was used")
    monkeypatch.setattr(C, "_get", boom)
    monkeypatch.setattr(C, "_post", boom)
    monkeypatch.setattr(VI, "LIB_PATH", str(tmp_path / "home" / "cast_library.json"))
    monkeypatch.setenv("ELEVENLABS_KEY", "test-key-not-real")


@pytest.fixture
def film(tmp_path):
    return make_film(tmp_path)


def char(d, name):
    return next(c for c in bible.load(d)["characters"] if c["name"].lower() == name.lower())


def give(d, name, vid=V1, model="eleven_v4", made="library", voice_name="Warm"):
    return C.set_voice(d, name, {"voice_id": vid, "voice_name": voice_name, "model": model}, made=made)


def approve(d, name, on=True):
    bible.set_voice_profile(d, char(d, name)["id"], {"approved": on})


# ---------------------------------------------------------------- the profile

def test_identity_fields_are_kept_with_the_profile_and_old_fields_are_untouched(film):
    c = char(film, "Lila")
    bible.set_voice_profile(film, c["id"], {"accent": "yorkshire", "age_range": "teens"})
    bible.set_voice_profile(film, c["id"], {"language": "English", "pitch_range": "high", "mannerisms": "hums when she thinks", "pronunciation": "Chloe = KLOH-ee"})
    p = char(film, "Lila")["voice_profile"]
    assert p["accent"] == "yorkshire" and p["age_range"] == "teens" and p["language"] == "English" and p["mannerisms"] == "hums when she thinks" and p["pronunciation"] == "Chloe = KLOH-ee"
    assert p["approved"] is False


def test_the_assistant_is_still_asked_only_for_the_original_fields():
    assert set(bible.IDENTITY_FIELDS).isdisjoint(bible.VOICE_PROFILE_FIELDS)
    from filmcrafter_engine import voicedirect as VD
    assert set(VD.clean_profile({"description": "x"}).keys()) - {"search"} == set(bible.VOICE_PROFILE_FIELDS)


# ---------------------------------------------------------------- the lock

def test_a_lock_records_the_voice_and_model_and_reports_ok(film):
    give(film, "Lila")
    approve(film, "Lila")
    me = next(p for p in VI.overview(film)["people"] if p["name"] == "Lila")
    assert me["consistency"]["state"] == "unlocked" and "would not be noticed" in me["consistency"]["words"]
    r = VI.lock(film, "Lila")["lock"]
    assert r["voice_id"] == V1 and r["model"] == "eleven_v4"
    me = next(p for p in VI.overview(film)["people"] if p["name"] == "Lila")
    assert me["consistency"]["state"] == "ok" and me["lock"]["voice_name"] == "Warm"


def test_a_locked_voice_that_changes_is_reported_in_plain_words(film):
    give(film, "Lila")
    VI.lock(film, "Lila")
    give(film, "Lila", vid=V2, voice_name="Bright")
    ov = VI.overview(film)
    me = next(p for p in ov["people"] if p["name"] == "Lila")
    assert me["consistency"]["state"] == "changed" and "changed from Warm to Bright" in me["consistency"]["words"] and ov["flagged"] == 1


def test_a_changed_model_or_reference_is_noticed_even_with_the_same_voice(film, monkeypatch):
    give(film, "Lila")
    monkeypatch.setattr(VI, "_reference_sha", lambda d, k: "aaa")
    VI.lock(film, "Lila")
    give(film, "Lila", model="eleven_multilingual_v2")
    monkeypatch.setattr(VI, "_reference_sha", lambda d, k: "bbb")
    words = next(p for p in VI.overview(film)["people"] if p["name"] == "Lila")["consistency"]["words"]
    assert "model changed from eleven_v4 to eleven_multilingual_v2" in words and "reference voice" in words


def test_a_voice_taken_off_a_locked_character_is_reported_missing(film):
    give(film, "Lila")
    VI.lock(film, "Lila")
    C.clear_voice(film, "Lila")
    assert next(p for p in VI.overview(film)["people"] if p["name"] == "Lila")["consistency"]["state"] == "missing"


def test_locking_needs_a_voice_and_unlocking_keeps_the_history(film):
    with pytest.raises(SystemExit, match="no voice to lock"):
        VI.lock(film, "Lila")
    give(film, "Lila")
    VI.lock(film, "Lila")
    VI.lock(film, "Lila")                                                       # locking again replaces it, and says so
    VI.unlock(film, "Lila")
    me = next(p for p in VI.overview(film)["people"] if p["name"] == "Lila")
    assert me["lock"] is None and [h["why"] for h in me["history"]] == ["replaced by a new lock", "unlocked"]


def test_nobody_is_changed_by_the_lock_itself(film):
    give(film, "Lila")
    approve(film, "Lila")
    VI.lock(film, "Lila")
    assert C._cast(film)["people"]["lila"]["voice_id"] == V1
    assert char(film, "Lila")["voice_profile"]["approved"] is True
    with pytest.raises(SystemExit, match="approved"):
        give(film, "Lila", vid=V2)                                              # the existing guard still stops a silent replacement


# ---------------------------------------------------------------- listening ratings

def test_ratings_must_be_whole_numbers_from_one_to_five(film):
    give(film, "Lila")
    for bad in (0, 6, 2.5, True, "x"):
        with pytest.raises(SystemExit, match="1 to 5"):
            VI.rate(film, "Lila", V1, accent_score=bad)
    with pytest.raises(SystemExit, match="Give the accent or the natural rating"):
        VI.rate(film, "Lila", V1)
    with pytest.raises(SystemExit, match="Choose one of the voices"):
        VI.rate(film, "Lila", "../x", accent_score=3)


def test_the_accent_status_is_what_you_rated_and_says_it_is_not_a_measurement(film):
    give(film, "Lila")
    assert VI.accent_status([])["status"] == "untested"
    r = VI.rate(film, "Lila", V1, accent_score=5, natural_score=4, accent="Yorkshire", note="lovely")
    assert r["accent"]["status"] == "accepted" and "not a measurement" in r["accent"]["words"] and r["rating"]["accent"] == "yorkshire"
    for _ in range(3):
        VI.rate(film, "Lila", V1, accent_score=1)                                # 5, 1, 1, 1: an average of exactly 2
    assert VI.accent_status(VI._records(film)["people"]["lila"]["ratings"])["status"] == "not_convincing"
    VI.rate(film, "Lila", V1, accent_score=5)
    VI.rate(film, "Lila", V1, accent_score=5)
    assert VI.accent_status(VI._records(film)["people"]["lila"]["ratings"])["status"] == "mixed"


def test_only_ratings_of_the_voice_they_have_now_count_in_the_overview(film):
    give(film, "Lila")
    VI.rate(film, "Lila", V1, accent_score=5, natural_score=4)
    VI.rate(film, "Lila", V2, accent_score=1, natural_score=1)
    me = next(p for p in VI.overview(film)["people"] if p["name"] == "Lila")
    assert me["ratings"] == 1 and me["natural"] == 4.0 and me["accent"]["status"] == "accepted"
    give(film, "Lila", vid=V2)
    me = next(p for p in VI.overview(film)["people"] if p["name"] == "Lila")
    assert me["accent"]["status"] == "not_convincing"


def test_ratings_are_capped_so_the_record_cannot_grow_without_end(film):
    give(film, "Lila")
    for _ in range(VI.RATINGS_KEEP + 15):
        VI.rate(film, "Lila", V1, accent_score=3)
    assert len(VI._records(film)["people"]["lila"]["ratings"]) == VI.RATINGS_KEEP


# ---------------------------------------------------------------- casting comparison

def voice(vid, name, labels=None, desc="", cat="premade"):
    return {"voice_id": vid, "name": name, "category": cat, "description": desc, "labels": labels or {}, "preview_url": ""}


def test_candidates_are_ranked_by_fit_with_reasons_cost_licence_and_where_they_run(film):
    bible.set_voice_profile(film, char(film, "Lila")["id"], {"description": "a young girl, bright and quick", "accent": "british", "age_range": "young"})
    give(film, "Lila")
    cands = [voice("AAAAAAAAAAAA", "Old Man", {"gender": "male", "age": "old"}), voice("BBBBBBBBBBBB", "Bright Girl", {"gender": "female", "age": "young", "accent": "british"}, "bright voice", "professional"),
             voice("CCCCCCCCCCCC", "Girl", {"age": "young"}, "", "premade")]
    out = VI.compare(film, "Lila", cands)
    names = [r["voice"]["name"] for r in out["rows"]]
    assert names[0] == "Bright Girl" and names.index("Girl") < names.index("Old Man")
    top = out["rows"][0]
    assert "british accent" in top["why"] and top["available"]["local"] is False and "ElevenLabs" in top["available"]["where"]
    assert top["audition_credits"] == C._credits(VI.AUDITION, "eleven_v4")["amount"] and "estimate" in top["audition_basis"]
    assert "cloned or community voice" in top["licence"]
    assert "own voices" in next(r for r in out["rows"] if r["voice"]["name"] == "Girl")["licence"]
    assert "listen and rate" in out["note"] and "emotion" not in {k for r in out["rows"] for k in r}


def test_the_comparison_shows_the_current_voice_and_what_you_rated(film):
    give(film, "Lila")
    VI.rate(film, "Lila", V1, accent_score=5, natural_score=5)
    out = VI.compare(film, "Lila", [voice(V1, "Warm", {"age": "young"}), voice(V2, "Other", {"age": "young"})])
    warm = next(r for r in out["rows"] if r["voice"]["voice_id"] == V1)
    assert warm["current"] is True and warm["rated"]["natural"] == 5.0 and warm["rated"]["accent"]["status"] == "accepted"
    assert next(r for r in out["rows"] if r["voice"]["voice_id"] == V2)["rated"]["count"] == 0


def test_bad_candidates_are_dropped_and_cut_down(film):
    junk = [None, "x", {"voice_id": "../etc"}, {"voice_id": "short"}, voice("DDDDDDDDDDDD", "N" * 500, {"gender": "female"}, "d" * 900)]
    out = VI.compare(film, "Lila", junk * 20)
    assert [r["voice"]["voice_id"] for r in out["rows"]] == ["DDDDDDDDDDDD"] * len(out["rows"])
    assert len(out["rows"][0]["voice"]["name"]) == 80 and len(out["rows"][0]["voice"]["description"]) == 200


# ---------------------------------------------------------------- the cast library

def test_a_character_is_kept_on_this_computer_and_used_in_another_film(film, tmp_path):
    bible.set_voice_profile(film, char(film, "Lila")["id"], {"accent": "scottish", "mannerisms": "laughs at her own jokes"})
    give(film, "Lila", made="design")
    saved = VI.library_save(film, "Lila", "my heroine")["saved"]
    assert saved["voice"]["voice_id"] == V1 and saved["profile"]["accent"] == "scottish" and "approved" not in saved["profile"] and "Designed in FilmCrafter" in saved["rights"]
    assert json.dumps(saved).count("audio") == 0
    second = make_film(tmp_path, "films2")
    res = VI.library_use(second, "Chloe", saved["id"])
    assert res["voice"]["voice_id"] == V1 and "accent" in res["profile"]
    chloe = char(second, "Chloe")["voice_profile"]
    assert chloe["accent"] == "scottish" and chloe["mannerisms"] == "laughs at her own jokes" and chloe["approved"] is False
    assert C._cast(second)["people"]["chloe"]["made"] == "design"
    assert [e["name"] for e in VI.cast_library()["entries"]] == ["Lila"]


def test_saving_needs_a_voice_and_saving_again_does_not_duplicate(film):
    with pytest.raises(SystemExit, match="no voice to keep"):
        VI.library_save(film, "Lila")
    give(film, "Lila")
    VI.library_save(film, "Lila")
    VI.library_save(film, "Lila", "again")
    assert len(VI.cast_library()["entries"]) == 1 and VI.cast_library()["entries"][0]["note"] == "again"


def test_an_approved_voice_is_not_replaced_from_the_library_without_a_yes(film, tmp_path):
    give(film, "Lila")
    saved = VI.library_save(film, "Lila")["saved"]
    other = make_film(tmp_path, "films3")
    give(other, "Chloe", vid=V2)
    approve(other, "Chloe")
    with pytest.raises(SystemExit, match="approved"):
        VI.library_use(other, "Chloe", saved["id"])
    assert C._cast(other)["people"]["chloe"]["voice_id"] == V2
    VI.library_use(other, "Chloe", saved["id"], replace_approved=True)
    assert C._cast(other)["people"]["chloe"]["voice_id"] == V1


def test_a_cloned_voice_needs_the_owners_agreement_confirmed_again_in_the_new_film(film, tmp_path):
    give(film, "Lila", made="clone")
    saved = VI.library_save(film, "Lila")["saved"]
    assert "cloned from a recording" in saved["rights"]
    other = make_film(tmp_path, "films4")
    with pytest.raises(SystemExit, match="owner agrees"):
        VI.library_use(other, "Chloe", saved["id"])
    assert "chloe" not in C._cast(other)["people"]
    VI.library_use(other, "Chloe", saved["id"], rights_confirmed=True)
    assert C._cast(other)["people"]["chloe"]["voice_id"] == V1


def test_unknown_names_and_ids_are_refused(film):
    with pytest.raises(SystemExit, match="not in the Production Bible"):
        VI.lock(film, "Nobody")
    with pytest.raises(SystemExit, match="Choose a character"):
        VI.lock(film, "")
    with pytest.raises(SystemExit, match="not in the cast library"):
        VI.library_use(film, "Lila", "nope")


# ---------------------------------------------------------------- the command line

def test_the_command_line_answers_with_json(film, capsys):
    give(film, "Lila")
    assert VI.main(["lock", film, "--data", json.dumps({"person": "Lila"})]) == 0
    assert VI.main(["overview", film]) == 0
    assert VI.main(["rate", film, "--data", json.dumps({"person": "Lila", "voice_id": V1, "accent_score": 4})]) == 0
    assert VI.main(["lock", film, "--data", json.dumps({"person": "Nobody"})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert [x["event"] for x in lines] == ["result", "result", "result", "error"]
    assert lines[1]["data"]["people"][0]["name"] in ("Lila", "Chloe")
