"""Write what the real engine answers to each screen's questions, as JSON, into src/__tests__/fixtures/engine/.

The screens' own tests use answers written by hand. These are the engine's real answers (a film with two short text-to-speech lines, a voice, a plan, sound design, cues, an export), so a screen test that
feeds them to the real component catches a field the engine does not send or sends under another name. Run from the repository root:

  analysis\\.venv\\Scripts\\python scripts/make_engine_fixtures.py

Nothing is sent anywhere and nothing is spent. The film is made in a temporary folder.
"""
import json
import os
import shutil
import sys
import tempfile

import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from filmcrafter_engine import (adrsync as AD, audiolib as AL, audiocues as Q, audioqa as QA, bible, cast_voice as C, performplan as PP, proaudio as PA, revoice as RV,  # noqa: E402
                                shots as S, sounddesign as SD, story, voiceid as VI, voiceover as V)

OUT = os.path.join(ROOT, "src", "__tests__", "fixtures", "engine")
DATA = os.path.join(ROOT, "analysis", "tests", "data")
RATE = 22050
VOICE = {"voice_id": "AbCdEfGh1234", "voice_name": "Warm", "model": "eleven_v4"}


def dump(name, obj):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False, default=str, sort_keys=True)
        f.write("\n")


def tone(path, secs, hz, amp=0.3):
    t = np.arange(int(RATE * secs)) / RATE
    sf.write(path, (amp * np.sin(2 * np.pi * hz * t)).astype("float32"), RATE)
    return path


def main():
    tmp = tempfile.mkdtemp()
    try:
        d = story.create(os.path.join(tmp, "films"), "Fixture Film", "screenplay",
                         "INT. KITCHEN - NIGHT\n\nRain on a tin roof. MAMA stirs a steaming pot while LILA walks in and drops a basket of oranges on wet pavement. The door slams.\n\nMAMA\nI did not think you would come back.\n\nEXT. YARD - DAY\n\nChildren play.\n")["dir"]
        bible.seed(d)
        S.breakdown(d)
        lines = [s["id"] for s in V.status(d)["shots"] if any(p["lines"] for p in s["people"])]
        sid = lines[0]
        for who, f in (("Mama", "david"),):
            V.attach(d, sid, who, os.path.join(DATA, f"real_speech_{f}.wav"), fit=False)
        S.set_fields(d, sid, {"generation": {"duration": 3.2}})
        C.set_voice(d, "Mama", VOICE)
        mama = next(c for c in bible.load(d)["characters"] if c["name"].lower() == "mama")
        bible.set_voice_profile(d, mama["id"], {"accent": "nigerian", "age_range": "middle aged", "language": "English", "approved": True})
        VI.lock(d, "Mama")
        VI.rate(d, "Mama", VOICE["voice_id"], accent_score=4, natural_score=5, accent="nigerian")
        cands = [{"voice_id": "BBBBBBBBBBBB", "name": "Joy", "category": "professional", "description": "calm voice", "labels": {"accent": "nigerian", "gender": "female", "age": "middle_aged"}, "preview_url": ""},
                 {"voice_id": VOICE["voice_id"], "name": "Warm", "category": "premade", "description": "", "labels": {"accent": "nigerian"}, "preview_url": ""}]
        VI.library_save(d, "Mama", "fixture")
        dump("voiceid_overview", VI.overview(d))
        dump("voiceid_compare", VI.compare(d, "Mama", cands))
        dump("voiceid_cast_library", VI.cast_library())
        # performance plan
        PP.set_plan(d, sid, "Mama", {"arc": [{"at": 0, "emotion": "neutral"}, {"at": 5, "emotion": "sad", "intensity": 0.8}], "events": [{"kind": "sigh", "after_word": 0}, {"kind": "gasp", "after_word": 4}],
                                      "pauses": [{"after_word": 4, "ms": 800}], "emphasis": [3], "approved": True, "objective": "stop her leaving"}, "eleven_v4")
        dump("performplan_get", PP.get(d, sid, "Mama", "eleven_v4"))
        dump("performplan_get_untagged_model", PP.get(d, sid, "Mama", "eleven_multilingual_v2"))
        # sound design
        shot1 = next(s["id"] for s in sorted(S.view(d)["shots"], key=lambda s: (int(s["scene"]), s["index"])))
        src = os.path.join(tmp, "src"); os.makedirs(src)
        rain = AL.import_files(d, "sfx", [tone(os.path.join(src, "rain.wav"), 2.0, 300, 0.1)], "ambience")["assets"][-1]
        hit = AL.import_files(d, "sfx", [tone(os.path.join(src, "hit.wav"), 0.5, 1500)], None)["assets"][-1]
        theme = AL.import_files(d, "music", [tone(os.path.join(src, "theme.wav"), 3.0, 600, 0.2)], None)["assets"][-1]
        env = next(e for e in bible.load(d)["environments"] if 1 in e["scenes"])
        SD.profile_set(d, env["id"], {"interior": True, "weather": "heavy rain", "room_size": "small", "reverb": "room", "surfaces": ["wet pavement"], "materials": ["tin"],
                                      "layers": [{"name": "Rain on the roof", "distance": "near", "level_db": -6, "asset_id": rain["id"]}, {"name": "Generator", "distance": "far"}], "recurring": "the generator coughs"})
        dump("sounddesign_suggest", SD.suggest(d, shot1))
        SD.event_add(d, {"shot": shot1, "action": "impact", "source_object": "basket of oranges", "by": "LILA", "start": 2.0, "distance": "near", "side": "left", "asset_id": hit["id"], "approval": "approved"})
        SD.event_add(d, {"shot": shot1, "action": "door", "source_object": "door", "start": 3.0})
        r = SD.to_cues(d, 1)
        dump("sounddesign_scene", SD.scene(d, 1))
        dump("sounddesign_to_cues", r)
        dump("sounddesign_candidates", SD.candidates(d, SD._load(d)["events"][1]["id"]))
        Q.add(d, {"asset_id": theme["id"], "scene": 1, "shot": shot1, "start": 0.5})
        # the audio inspector
        os.makedirs(os.path.join(d, "exports"), exist_ok=True)
        shutil.copyfile(os.path.join(DATA, "real_speech_zira.wav"), os.path.join(d, "exports", "cut.wav"))
        dump("audioqa_film", QA.film(d, "exports/cut.wav"))
        # timing and ADR
        shutil.copyfile(os.path.join(DATA, "real_speech_zira.wav"), os.path.join(d, "guide.wav"))
        AD.nudge(d, sid, "Mama", frames=3)
        AD.adr_mark(d, sid, "Mama", True, "a dog barks")
        dump("adrsync_get", AD.get(d, sid, "Mama"))
        dump("adrsync_align", AD.align(d, sid, "Mama", guide="guide.wav"))
        S.set_fields(d, sid, {"generation": {"duration": 3.2}})
        dump("adrsync_fit_plan", AD.fit_plan(d, sid, "Mama", target_seconds=3.1))
        dump("adrsync_fit_make", AD.fit_make(d, sid, "Mama", target_seconds=3.1))
        dump("adrsync_adr_list", AD.adr_list(d))
        dump("adrsync_adr_take", AD.adr_take(d, sid, "Mama", os.path.join(DATA, "real_speech_zira.wav"), performed_by="Dee"))
        dump("cast_takes", C.takes(d, sid, "Mama"))
        # the audio export
        dump("proaudio_plan", PA.plan(d, {}))
        res = PA.export(d, {"target_lufs": -23, "start_tc": "01:00:00:00"})
        res["folder"] = "C:\\\\Films\\\\Fixture Film\\\\exports\\\\audio\\\\Fixture Film"
        dump("proaudio_export", res)
        # speech to speech (what is installed here, and the records a film keeps)
        rs = RV.status(d)
        rs["runtime"]["folder"] = "~/.filmcrafter/voiceconv"                  # not this computer's path
        dump("revoice_status", rs)
        print("wrote", len(os.listdir(OUT)), "fixtures to", OUT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
