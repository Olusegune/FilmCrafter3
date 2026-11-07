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
                                shots as S, sounddesign as SD, musicdirector as MD, vpstudio as VP, vpvideo as VV, worldlock as WL, directorcam as DC, story, voiceid as VI, voiceover as V)

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
        # the music director
        mo = MD.motif_set(d, {"name": "Mama's theme", "kind": "character", "subject": "Mama", "mood": "tender", "tempo": "slow", "instruments": ["piano"], "description": "four rising notes"})["id"]
        dump("music_suggest", MD.suggest(d, 1))
        sp = MD.spot_set(d, {"scene": 1, "start_shot": shot1, "mood": "tender", "energy_in": 1, "energy_out": 3, "motif_ids": [mo], "asset_id": theme["id"], "approval": "approved", "enters": "when she turns"})["id"]
        dump("music_prompt", MD.prompt(d, sp))
        MD.record_set(d, theme["id"], {"by": "Ada", "scenes": [1], "licence_ref": "fixture"})
        dump("music_to_cues", MD.to_cues(d, 1))
        dump("music_get", MD.get(d))
        # virtual production: a synthetic plate with a known answer, keyed, composed and rendered by the real engine
        sys.path.insert(0, os.path.join(ROOT, "analysis", "tests"))
        import test_keying as TK
        from PIL import Image as PILImage
        plate, _, _ = TK.make_plate(spill=1.0)
        bgp = np.full((TK.H, TK.W, 3), [0.55, 0.5, 0.45], np.float32); bgp[: TK.H // 2] = [0.4, 0.55, 0.75]
        ppath, bpath = os.path.join(src, "plate.png"), os.path.join(src, "street.jpg")
        PILImage.fromarray((plate * 255 + 0.5).astype(np.uint8)).save(ppath); PILImage.fromarray((bgp * 255 + 0.5).astype(np.uint8)).save(bpath)
        pid = VP.import_source(d, {"path": ppath, "kind": "plate", "name": "Sarah on green"})["id"]
        bid = VP.import_source(d, {"path": bpath, "kind": "background", "name": "Street"})["id"]
        dump("vp_plate_check", VP.plate_check(d, pid))
        kr = VP.key(d, {"source": pid, "name": "Sarah", "params": {"similarity": 0.06}})
        dump("vp_key", kr)
        cp = VP.compose_set(d, {"name": "Street scene", "background": bid, "size": [TK.W, TK.H], "layers": [{"cutout": kr["id"], "x": 0.5, "y": 1.0, "scale": 0.9, "shadow": {"strength": 0.3}, "match": 0.2}]})["id"]
        dump("vp_render", VP.render(d, cp))
        dump("vp_export", VP.export(d, kr["id"]))
        # virtual production video: a short H.264 clip of a moving subject on a noisy green screen, keyed, exported and rendered by the real engine
        import test_vpvideo as TV
        import subprocess
        fdir = os.path.join(src, "clipframes"); os.makedirs(fdir)
        rng = np.random.default_rng(3)
        for i in range(TV.N):
            PILImage.fromarray((TV.frame(i, rng) * 255 + 0.5).astype(np.uint8)).save(os.path.join(fdir, f"{i + 1:03d}.png"))
        clip = os.path.join(src, "walk.mp4"); TV.encode(fdir, clip)
        dump("vpvideo_capabilities", VV.capabilities())
        cid_src = VV.import_clip(d, {"path": clip, "kind": "plate", "name": "Sarah walks"})["id"]
        ck = VV.key_clip(d, {"source": cid_src, "temporal": 0.5, "params": {"similarity": 0.02}, "name": "Sarah walks cutout"})
        dump("vpvideo_key_clip", ck)
        dump("vpvideo_export_clip", VV.export_clip(d, {"id": ck["id"], "format": "png"}))
        cp2 = VP.compose_set(d, {"name": "Walk", "background": bid, "size": [TV.W, TV.H], "layers": [{"cutout": ck["id"], "x": 0.3, "y": 1.0, "scale": 0.8, "anchor": "bottom", "keys": [{"t": 0, "x": 0.2}, {"t": 1.0, "x": 0.8}]}]})["id"]
        dump("vpvideo_render_video", VV.render_video(d, {"id": cp2, "fps": 12, "seconds": 1}))
        dump("vp_get", VP.get(d))
        # WorldLock: a small market set built from real pictures, seen from two cameras, with an event over the shots
        from PIL import ImageDraw
        def wl_pic(name, w, h, col):
            im = PILImage.new("RGBA", (w, h), col + (255,)); ImageDraw.Draw(im).rectangle((0, 0, w - 1, h - 1), outline=(0, 0, 0, 255), width=2)
            pth = os.path.join(src, name + ".png"); im.save(pth); return pth
        wsid = WL.create(d, {"name": "Market"})["id"]
        wback = WL.asset_add(d, wsid, {"path": wl_pic("wback", 1200, 300, (40, 80, 230)), "name": "Backdrop", "z": 20, "width": 40, "height": 10})["id"]
        WL.asset_add(d, wsid, {"path": wl_pic("wstall", 200, 200, (30, 200, 60)), "name": "Fruit stall", "kind": "landmark", "x": -2.2, "z": 8, "width": 2.4, "height": 3})
        wbasket = WL.asset_add(d, wsid, {"path": wl_pic("wbasket", 60, 60, (230, 30, 30)), "name": "Basket", "kind": "prop", "x": -0.4, "z": 5, "width": 0.5, "height": 0.5})["id"]
        wcam2 = WL.camera_set(d, wsid, {"name": "Right", "x": 0.25, "y": 1.6, "z": 0})["id"]
        wshots = [s["id"] for s in sorted(S.view(d)["shots"], key=lambda x: (int(x["scene"]), x["index"]))]
        WL.event_set(d, wsid, {"shot": wshots[1], "asset": wbasket, "kind": "move", "to": {"x": -1.0, "z": 6.0}, "state": "on the floor"})
        WL.version_save(d, wsid, "Opening layout")
        dump("worldlock_render", WL.render(d, wsid, {"camera": wcam2, "size": [320, 180]}))
        dump("worldlock_check", WL.check(d, wsid))
        dump("worldlock_check_move", WL.check_move(d, wsid, {"from": WL.get(d, wsid)["cameras"][0]["id"], "to": wcam2, "steps": 4}))
        dump("worldlock_list", WL.list_sets(d))
        dump("worldlock_get", WL.get(d, wsid))
        # DirectorCam: a beat planned on a set with two people, saved, previewed and packaged by the real engine
        dsid = WL.create(d, {"name": "Market arrival"})["id"]
        WL.asset_add(d, dsid, {"path": wl_pic("dback", 1200, 400, (40, 80, 230)), "name": "Backdrop", "y": -8, "z": 20, "width": 70, "height": 24})
        doranges = WL.asset_add(d, dsid, {"path": wl_pic("dor", 80, 40, (240, 220, 30)), "name": "Oranges", "kind": "prop", "x": 2.0, "z": 7, "width": 0.8, "height": 0.4})["id"]
        dgp = WL.asset_add(d, dsid, {"path": wl_pic("dgirl", 60, 120, (230, 30, 30)), "name": "Girl picture", "kind": "prop", "x": 50, "z": 50, "width": 0.5, "height": 1.2})["id"]
        WL.character_set(d, dsid, {"name": "Girl", "x": -2.0, "z": 6.0, "facing": 90, "asset": dgp})
        WL.character_set(d, dsid, {"name": "Vendor", "x": 3.5, "z": 8.0, "facing": -90})
        dbeat = "The girl enters the market, sees the oranges, and rushes to help the vendor."
        draft = DC.plan_beat(WL._load(d, dsid), dbeat)
        dump("directorcam_plan_beat", draft)
        dplan = DC.plan_save(d, dsid, {"name": "Market arrival", "beat": dbeat, "shots": draft["shots"]})
        dump("directorcam_plan_get", DC.get_plan(d, dsid, dplan["id"]))
        drush = next(x for x in dplan["shots"] if "rushes" in x["title"])
        dump("directorcam_preview", DC.preview(d, dsid, dplan["id"], drush["id"]))
        dump("directorcam_package", DC.package(d, dsid, dplan["id"], drush["id"], {"provider": "kie", "model": "kling/v2-5-turbo-image-to-video-pro"}))
        dump("directorcam_path", DC.path_action(d, dsid, {"view": drush["camera"], "move": {"kind": "dolly", "amount": 2.0}}))
        dump("directorcam_plans", DC.plans(d, dsid))
        dump("directorcam_worldlock_list", WL.list_sets(d))
        dump("directorcam_worldlock_get", WL.get(d, dsid))
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
