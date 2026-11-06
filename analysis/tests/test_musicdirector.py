"""The music director: motifs, spotting, asking for music in words, records, cues from spots, and the report. Real films, real audio files, the real cue list and the real mixer."""
import json
import os

import numpy as np
import pytest
import soundfile as sf

from filmcrafter_engine import audiocues as Q, audiolib as AL, audiomix as M, bible, musicdirector as MD, shots as S, story

R = M.RATE
SCRIPT = ("INT. KITCHEN - DAY\n\nSARAH stirs a pot and hums. She smiles and hugs her brother.\n\nSARAH\nBreakfast is ready.\n\n"
          "EXT. ROAD - NIGHT\n\nA car chases SARAH down the road. She runs and screams. Blood on the glass.\n\n"
          "INT. HALL - DAY\n\nSARAH sits alone in the empty hall. She cries.\n")


def tone(path, secs, hz=300, amp=0.3):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    t = np.arange(int(R * secs)) / R
    sf.write(path, (amp * np.sin(2 * np.pi * hz * t)).astype("float32"), R)
    return path


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def music(film, tmp_path, name="theme.wav", secs=12.0, hz=300, commercial=None):
    a = AL.import_files(film, "music", [tone(str(tmp_path / "src" / name), secs, hz)])["assets"][-1]
    if commercial:
        AL.update(film, a["id"], {"licence": {"commercial": commercial}})
    return a


def scenes(film):
    return sorted({int(s["scene"]) for s in S.view(film)["shots"]})


def shots_of(film, n):
    return sorted((s for s in S.view(film)["shots"] if int(s["scene"]) == n), key=lambda s: s["index"])


# ---------------------------------------------------------------- an empty film

def test_a_film_with_no_music_plan_reports_every_scene_as_undecided(film):
    g = MD.get(film)
    assert g["motifs"] == [] and g["spots"] == [] and g["records"] == {}
    assert g["report"]["undecided"] == scenes(film) and g["report"]["music_share"] == 0.0 and g["report"]["needs_attention"] is True
    assert not os.path.exists(os.path.join(film, "audio", "music.json"))                                  # reading wrote nothing


def test_it_refuses_a_folder_that_is_not_a_film(tmp_path):
    with pytest.raises(SystemExit, match="isn't a FilmCrafter film"):
        MD.get(str(tmp_path))


# ---------------------------------------------------------------- motifs

def test_a_motif_is_named_checked_and_changed_in_place(film):
    m = MD.motif_set(film, {"name": "  Sarah's  theme ", "kind": "character", "subject": "sarah", "mood": "hopeful", "tempo": "slow, 60 bpm", "instruments": ["Piano", "piano", " cello "], "description": "Four rising notes"})
    mid = m["id"]
    got = m["motifs"][0]
    assert got["name"] == "Sarah's theme" and got["instruments"] == ["piano", "cello"] and got["kind"] == "character"
    MD.motif_set(film, {"id": mid, "mood": "sad"})
    assert MD.get(film)["motifs"][0]["mood"] == "sad" and MD.get(film)["motifs"][0]["name"] == "Sarah's theme" and len(MD.get(film)["motifs"]) == 1


def test_motif_mistakes_are_refused_and_change_nothing(film):
    MD.motif_set(film, {"name": "A", "kind": "theme"})
    for data, why in (({"name": "", "kind": "theme"}, "name"), ({"name": "B", "kind": "weather"}, "character, a place or a theme"), ({"name": "a", "kind": "theme"}, "already a motif"),
                      ({"id": "mo-00000000", "name": "x"}, "isn't in the film")):
        with pytest.raises(SystemExit, match=why):
            MD.motif_set(film, data)
    assert len(MD.get(film)["motifs"]) == 1
    for i in range(MD.MAX_MOTIFS - 1):
        MD.motif_set(film, {"name": f"m{i}", "kind": "theme"})
    with pytest.raises(SystemExit, match="At most"):
        MD.motif_set(film, {"name": "one too many", "kind": "theme"})


def test_removing_a_motif_moves_it_aside_and_takes_it_off_the_spots(film):
    mid = MD.motif_set(film, {"name": "A", "kind": "theme"})["id"]
    sid = MD.spot_set(film, {"scene": 1, "motif_ids": [mid]})["id"]
    MD.motif_remove(film, mid)
    g = MD.get(film)
    assert g["motifs"] == [] and g["spots"][0]["motif_ids"] == [] and g["spots"][0]["id"] == sid
    removed = json.load(open(os.path.join(film, "audio", "music.json"), encoding="utf-8"))["removed"]
    assert removed[0]["kind"] == "motif" and removed[0]["item"]["name"] == "A"
    with pytest.raises(SystemExit, match="isn't in the film"):
        MD.motif_remove(film, mid)


# ---------------------------------------------------------------- spots

def test_a_spot_is_checked_against_the_film(film):
    sh = shots_of(film, 1)
    s = MD.spot_set(film, {"scene": 1, "start_shot": sh[0]["id"], "mood": "warm", "energy_in": 9, "energy_out": -3, "level_db": -99, "fade_in": 50})
    sp = s["spots"][0]
    assert sp["decision"] == "score" and sp["energy_in"] == 5 and sp["energy_out"] == 0 and sp["level_db"] == -40.0 and sp["fade_in"] == 10.0 and sp["approval"] == "suggested" and sp["source"] == "manual"
    for data, why in (({"scene": 99}, "isn't in the film"), ({"scene": "x"}, "Choose a scene"), ({"scene": 1, "start_shot": shots_of(film, 2)[0]["id"]}, "isn't in this scene"),
                      ({"scene": 1, "decision": "loud"}, "score, source or silence"), ({"scene": 1, "motif_ids": ["mo-00000000"]}, "isn't in the film"), ({"scene": 1, "asset_id": "nope"}, "not in this film's library"),
                      ({"scene": 1, "approval": "maybe"}, "approved, rejected"), ({"id": "sp-00000000"}, "isn't in the film")):
        with pytest.raises(SystemExit, match=why):
            MD.spot_set(film, data)
    assert len(MD.get(film)["spots"]) == 1


def test_a_spot_can_only_name_music_from_the_library_and_a_sound_effect_is_not_music(film, tmp_path):
    fx = AL.import_files(film, "sfx", [tone(str(tmp_path / "src" / "fx.wav"), 2.0)])["assets"][-1]
    with pytest.raises(SystemExit, match="not in this film's library"):
        MD.spot_set(film, {"scene": 1, "asset_id": fx["id"]})


def test_at_most_a_few_spots_per_scene_and_removing_one_keeps_it(film):
    ids = [MD.spot_set(film, {"scene": 1})["id"] for _ in range(MD.MAX_SPOTS_PER_SCENE)]
    with pytest.raises(SystemExit, match="At most"):
        MD.spot_set(film, {"scene": 1})
    MD.spot_set(film, {"scene": 2})                                                                         # another scene is unaffected
    MD.spot_remove(film, ids[0])
    assert len(MD.get(film)["spots"]) == MD.MAX_SPOTS_PER_SCENE
    assert json.load(open(os.path.join(film, "audio", "music.json"), encoding="utf-8"))["removed"][0]["item"]["id"] == ids[0]


# ---------------------------------------------------------------- suggesting from the words

def test_suggest_reads_the_words_and_says_which_words_it_acted_on(film):
    chase = MD.suggest(film, 2)
    p = chase["proposal"]
    assert p["decision"] == "score" and p["mood"] == "tension" and p["energy_out"] == 4 and p["source"] == "derived"
    assert {b["word"] for b in chase["because"]} >= {"chases", "runs", "screams"}
    assert p["start_shot"] in {s["id"] for s in shots_of(film, 2)} and p["end_shot"] == shots_of(film, 2)[-1]["id"]
    grief = MD.suggest(film, 3)["proposal"]
    assert grief["mood"] == "sorrow" and grief["energy_out"] == 2
    assert MD.suggest(film, 1)["proposal"]["mood"] in ("warmth", "tension")
    assert not os.path.exists(os.path.join(film, "audio", "music.json"))                                    # suggesting saves nothing


def test_suggest_proposes_silence_when_the_words_call_for_nothing(tmp_path):
    d = story.create(str(tmp_path / "f2"), "Q", "screenplay", "INT. OFFICE - DAY\n\nBOB files a form.\n\nBOB\nDone.\n")["dir"]
    bible.seed(d)
    S.breakdown(d)
    r = MD.suggest(d, 1)
    assert r["proposal"]["decision"] == "silence" and r["because"] == [] and "choice, not a gap" in r["note"]


def test_suggest_names_the_motifs_of_the_people_and_places_in_the_scene(film):
    mid = MD.motif_set(film, {"name": "Sarah", "kind": "character", "subject": "Sarah"})["id"]
    MD.motif_set(film, {"name": "Road", "kind": "place", "subject": "nowhere"})
    r = MD.suggest(film, 2)
    assert r["motifs"] == [mid] and r["proposal"]["motif_ids"] == [mid]
    with pytest.raises(SystemExit, match="isn't in the film"):
        MD.suggest(film, 42)


# ---------------------------------------------------------------- asking for the music

def test_the_prompt_is_built_from_the_spot_and_its_motifs_and_sends_nothing(film):
    mid = MD.motif_set(film, {"name": "Sarah's theme", "kind": "character", "subject": "Sarah", "description": "four rising notes", "tempo": "slow", "key": "D minor", "instruments": ["piano"]})["id"]
    sh = shots_of(film, 2)
    sid = MD.spot_set(film, {"scene": 2, "start_shot": sh[0]["id"], "end_shot": sh[-1]["id"], "mood": "tension", "energy_in": 2, "energy_out": 5, "motif_ids": [mid], "enters": "the car lights come on",
                             "intent": "She is hunted."})["id"]
    p = MD.prompt(film, sid)
    assert "Instrumental film score cue, no vocals." in p["prompt"] and "Mood: tension." in p["prompt"] and "Instruments: piano." in p["prompt"]
    assert "from 2 to 5" in p["prompt"] and "Motif (Sarah's theme): four rising notes, slow, key D minor." in p["prompt"] and "Enters: the car lights come on." in p["prompt"] and "She is hunted." in p["prompt"]
    assert p["duration"] == pytest.approx(max(3.0, sum(float(s["duration"]) for s in sh)), abs=0.1) and p["instrumental"] is True and "Nothing has been sent" in p["how"]
    assert len(p["prompt"]) <= MD.PROMPT_CHARS and p["shots"] == [s["id"] for s in sh]


def test_only_a_scored_spot_needs_music_words(film):
    sid = MD.spot_set(film, {"scene": 1, "decision": "silence"})["id"]
    with pytest.raises(SystemExit, match="scored"):
        MD.prompt(film, sid)
    with pytest.raises(SystemExit, match="isn't in the film"):
        MD.prompt(film, "sp-00000000")


def test_candidates_come_from_the_library_and_never_include_sound_effects(film, tmp_path):
    a = music(film, tmp_path, "tense strings.wav")
    AL.update(film, a["id"], {"name": "tense strings", "description": "tension strings"})
    AL.import_files(film, "sfx", [tone(str(tmp_path / "src" / "tense door.wav"), 2.0)])
    sid = MD.spot_set(film, {"scene": 2, "mood": "tension"})["id"]
    c = MD.candidates(film, sid)
    assert [x["id"] for x in c["candidates"]] == [a["id"]] and c["terms"].startswith("tension")


# ---------------------------------------------------------------- records

def test_a_record_keeps_who_decided_what_and_its_history(film, tmp_path):
    a = music(film, tmp_path)
    MD.record_set(film, a["id"], {"by": "Ada", "scenes": [3, 1, "2", -4, "x"], "licence_ref": "Bought on 2026-10-02, receipt 123"})
    MD.record_set(film, a["id"], {"by": "Ben", "status": "revoked", "scenes": [1]})
    rec = MD.get(film)["records"][a["id"]]
    assert rec["status"] == "revoked" and rec["by"] == "Ben" and rec["scenes"] == [1] and len(rec["history"]) == 2
    assert rec["history"][0]["by"] == "Ada" and rec["history"][0]["scenes"] == [1, 2, 3] and rec["history"][0]["licence_ref"].startswith("Bought")
    assert AL.load(film)["assets"][0]["licence"]["commercial"] == "unknown"                                  # recording a decision does not change what the library says about the licence


def test_a_record_needs_music_a_person_and_a_valid_status(film, tmp_path):
    a = music(film, tmp_path)
    fx = AL.import_files(film, "sfx", [tone(str(tmp_path / "src" / "fx.wav"), 1.0)])["assets"][-1]
    for aid, data, why in (("nope", {"by": "A"}, "not in this film's library"), (fx["id"], {"by": "A"}, "not in this film's library"), (a["id"], {"by": ""}, "who"), (a["id"], {"by": "A", "status": "ok"}, "approved or revoked")):
        with pytest.raises(SystemExit, match=why):
            MD.record_set(film, aid, data)
    for i in range(MD.MAX_HISTORY + 5):
        MD.record_set(film, a["id"], {"by": f"p{i}"})
    assert len(MD.get(film)["records"][a["id"]]["history"]) == MD.MAX_HISTORY


# ---------------------------------------------------------------- into the real cue list and mix

def _approved_spot(film, a, **kw):
    sh = shots_of(film, 1)
    sid = MD.spot_set(film, {"scene": 1, "start_shot": sh[0]["id"], "end_shot": sh[-1]["id"], "asset_id": a["id"], "approval": "approved", "level_db": -9, "fade_in": 1, "fade_out": 2, **kw})["id"]
    return sid, sh


def test_an_approved_spot_with_music_becomes_one_cue_and_doing_it_again_updates_it(film, tmp_path):
    a = music(film, tmp_path)
    sid, sh = _approved_spot(film, a, mood="warm")
    r = MD.to_cues(film, 1)
    assert r["made"] == [sid] and r["updated"] == [] and r["waiting"] == [] and r["blocked"] == []
    cues = [c for c in Q.listing(film)["cues"] if c["kind"] == "music"]
    assert len(cues) == 1
    c = cues[0]
    assert c["asset_id"] == a["id"] and c["shot"] == sh[0]["id"] and c["gain_db"] == -9.0 and c["fade_in"] == 1.0 and c["fade_out"] == 2.0 and c["approval"] == "approved" and c["ducking"] == "auto"
    assert c["duration"] == pytest.approx(sum(float(s["duration"]) for s in sh), abs=0.01) and "warm" in c["note"]
    MD.spot_set(film, {"id": sid, "level_db": -12})
    r2 = MD.to_cues(film, 1)
    assert r2["made"] == [] and r2["updated"] == [sid]
    assert [c["gain_db"] for c in Q.listing(film)["cues"] if c["kind"] == "music"] == [-12.0]
    assert MD.get(film)["spots"][0]["cue"] == {"approval": "approved"}


def test_the_cue_made_from_a_spot_is_really_heard_in_the_mix(film, tmp_path):
    a = music(film, tmp_path, secs=12.0, hz=440)
    _approved_spot(film, a)
    MD.to_cues(film, 1)
    times, at = {}, 0.0
    for s in sorted(S.view(film)["shots"], key=lambda x: (int(x["scene"]), x["index"])):
        times[s["id"]] = (at, at + float(s["duration"]))
        at += float(s["duration"])
    base = str(tmp_path / "silence.wav")
    sf.write(base, np.zeros((int(at * R), 2), dtype="float32"), R, subtype="PCM_16")
    out = str(tmp_path / "mixed.wav")
    r = M.mix_cues(film, base, times, at, out, {**M.settings(film), "ducking_db": 0, "target_lufs": None})
    assert r and r["path"]
    x = sf.read(out, dtype="float32", always_2d=True)[0]
    first = shots_of(film, 1)
    end1 = times[first[-1]["id"]][1]
    inside = float(np.sqrt(np.mean(np.square(x[int(1.5 * R):int(min(end1 - 2.5, 3.5) * R), 0]))))
    after = float(np.sqrt(np.mean(np.square(x[int((end1 + 0.5) * R):int(min(at, end1 + 2.0) * R), 0])))) if at > end1 + 1 else 0.0
    assert inside > 0.02 and after < 0.001                                                                    # music while scene 1 runs, none in the next scene


def test_spots_that_are_not_approved_scored_or_given_music_make_no_cue_and_are_listed(film, tmp_path):
    a = music(film, tmp_path)
    MD.spot_set(film, {"scene": 1, "asset_id": a["id"]})                                                    # suggested only
    MD.spot_set(film, {"scene": 1, "decision": "silence", "approval": "approved"})
    MD.spot_set(film, {"scene": 1, "decision": "source", "approval": "approved"})
    w = MD.spot_set(film, {"scene": 1, "approval": "approved"})["id"]                                        # scored, approved, no music yet
    r = MD.to_cues(film, 1)
    assert r["made"] == [] and [x["id"] for x in r["waiting"]] == [w] and sorted(x["decision"] for x in r["silent"]) == ["silence", "source"]
    assert [c for c in Q.listing(film)["cues"] if c["kind"] == "music"] == []


def test_music_whose_licence_says_no_commercial_use_is_never_put_into_the_film(film, tmp_path):
    bad = music(film, tmp_path, "bad.wav", commercial="no")
    unk = music(film, tmp_path, "unk.wav", hz=500)
    sid, _ = _approved_spot(film, bad)
    r = MD.to_cues(film, 1)
    assert r["made"] == [] and r["blocked"][0]["id"] == sid and "not allowed" in r["blocked"][0]["why"]
    MD.spot_set(film, {"id": sid, "asset_id": unk["id"]})
    assert MD.to_cues(film, 1)["made"] == [sid]                                                              # an unknown licence is let through, and shown by the report


# ---------------------------------------------------------------- the report

def test_the_report_says_what_still_needs_a_decision(film, tmp_path):
    a = music(film, tmp_path)
    used = MD.motif_set(film, {"name": "Used", "kind": "theme"})["id"]
    once = MD.motif_set(film, {"name": "Once", "kind": "theme"})["id"]
    MD.motif_set(film, {"name": "Never", "kind": "theme"})
    MD.spot_set(film, {"scene": 1, "energy_in": 1, "energy_out": 1, "motif_ids": [used, once], "asset_id": a["id"], "approval": "approved"})
    MD.spot_set(film, {"scene": 2, "energy_in": 5, "energy_out": 5, "motif_ids": [used]})
    MD.to_cues(film, 1)
    rep = MD.report(film)
    assert rep["undecided"] == [3] and rep["needs_attention"] is True
    notes = {m["name"]: m["note"] for m in rep["motifs"]}
    assert notes["Never"] == "Never used." and "one scene only" in notes["Once"] and notes["Used"] == ""
    assert rep["jumps"] == [{"from_scene": 1, "to_scene": 2, "from_energy": 1, "to_energy": 5, "note": rep["jumps"][0]["note"]}]
    rec = rep["records"][0]
    assert rec["id"] == a["id"] and rec["status"] == "none" and rec["problems"] == ["Commercial use is not known.", "No recorded decision."]
    assert 0 < rep["music_share"] < 1
    MD.record_set(film, a["id"], {"by": "Ada", "scenes": [1]})
    AL.update(film, a["id"], {"licence": {"commercial": "yes"}})
    assert MD.report(film)["records"][0]["problems"] == [] and MD.report(film)["records"][0]["by"] == "Ada"


def test_a_scene_decided_as_silence_is_decided_and_a_rejected_spot_does_not_count(film):
    MD.spot_set(film, {"scene": 1, "decision": "silence"})
    MD.spot_set(film, {"scene": 2, "approval": "rejected"})
    assert MD.report(film)["undecided"] == [2, 3]


def test_junk_entries_are_ignored_and_a_file_of_the_wrong_shape_is_refused_and_left_alone(film):
    path = os.path.join(film, "audio", "music.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({"schema": 1, "motifs": [3, {"id": "mo-1", "name": "x", "kind": "theme"}], "spots": [], "records": {"a": 5}}, open(path, "w", encoding="utf-8"))
    g = MD.get(film)
    assert [m["id"] for m in g["motifs"]] == ["mo-1"] and g["records"] == {}
    open(path, "w", encoding="utf-8").write('{"schema": 1, "spots": "junk"}')
    with pytest.raises(SystemExit, match="left untouched"):
        MD.spot_set(film, {"scene": 1})
    assert open(path, encoding="utf-8").read() == '{"schema": 1, "spots": "junk"}'


# ---------------------------------------------------------------- the command line

def test_the_command_line_answers_with_json(film, capsys):
    assert MD.main(["motif_set", film, "--data", json.dumps({"name": "A", "kind": "theme"})]) == 0
    assert MD.main(["suggest", film, "--data", json.dumps({"scene": 2})]) == 0
    assert MD.main(["spot_set", film, "--data", json.dumps({"scene": 2, "mood": "tension"})]) == 0
    assert MD.main(["report", film]) == 0
    assert MD.main(["spot_set", film, "--data", json.dumps({"scene": 99})]) == 1
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip().startswith("{")]
    assert [x["event"] for x in lines] == ["result"] * 4 + ["error"] and lines[1]["data"]["proposal"]["decision"] == "score"
