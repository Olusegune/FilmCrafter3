"""Handing a film to an editor: EDL, OpenTimelineIO, Final Cut Pro XML, manifest, subtitles, copied media."""
import csv
import json
import os
import xml.etree.ElementTree as ET

import pytest

from filmcrafter_engine import bible, interchange as X, make, shots, story

SCRIPT = """INT. KITCHEN - MORNING

Sarah pours tea.

SARAH
He said he would call.

JOHN
Did you say something?

EXT. PLATFORM - NIGHT

Rain on the roof.
"""


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path), "Last Train", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    ids = [s["id"] for s in shots.breakdown(d)["shots"]]
    make.sync(d)
    rd = make.render_dir(d)
    os.makedirs(os.path.join(rd, "media"), exist_ok=True)
    jobs = []
    for i, sid in enumerate(ids[:-1]):                                          # the last shot has no take on purpose
        open(os.path.join(rd, "media", f"v{i}.mp4"), "wb").write(b"\x00\x00\x00\x18ftypmp42")
        jobs.append({"id": f"v{i}", "shot_id": sid, "plan": "production", "state": "ready", "kind": "video", "provider": "kie", "model": "wan", "output": f"media/v{i}.mp4", "created": 1 + i, "updated": 1 + i, "cost": 0.5, "overrides": {}})
    json.dump({"schema_version": 1, "jobs": jobs}, open(os.path.join(rd, "jobs.json"), "w"))
    return d


def test_timecode_and_subtitle_time():
    assert X.tc(0) == "00:00:00:00" and X.tc(24) == "00:00:01:00" and X.tc(24 * 3600 + 25) == "01:00:01:01" and X.tc(-5) == "00:00:00:00"
    assert X.srt_time(3.5) == "00:00:03,500" and X.srt_time(-1) == "00:00:00,000"


def test_the_folder_has_every_hand_off_file(film):
    r = X.write(film)
    out = r["dir"]
    for name in r["files"].values():
        assert os.path.isfile(os.path.join(out, name))
    assert set(r["files"]) >= {"edl", "otio", "fcpxml", "manifest"} and r["placed"] == r["shots"] - 1 and len(r["missing"]) == 1
    assert os.path.isfile(os.path.join(out, "shots.json")) and os.path.isdir(os.path.join(out, "media")) and len(os.listdir(os.path.join(out, "media"))) == r["placed"]
    assert r["audio"] and os.path.isfile(os.path.join(out, r["audio"]))


def test_the_edl_places_each_take_one_after_another(film):
    out = X.write(film)["dir"]
    text = open(os.path.join(out, "Last_Train.edl"), encoding="utf-8").read()
    assert text.startswith("TITLE: Last Train\nFCM: NON-DROP FRAME")
    events = [l for l in text.splitlines() if l[:3].isdigit()]
    assert len(events) == len(os.listdir(os.path.join(out, "media")))
    rec_in = [l.split()[-2] for l in events]
    assert rec_in[0] == "00:00:00:00" and rec_in == sorted(rec_in)


def test_the_otio_is_valid_json_with_clips_gaps_and_a_soundtrack(film):
    out = X.write(film)["dir"]
    t = json.load(open(os.path.join(out, "Last_Train.otio"), encoding="utf-8"))
    assert t["OTIO_SCHEMA"] == "Timeline.1"
    tracks = t["tracks"]["children"]
    assert [k["kind"] for k in tracks] == ["Video", "Audio"]
    kinds = [c["OTIO_SCHEMA"] for c in tracks[0]["children"]]
    assert kinds.count("Clip.1") == len(os.listdir(os.path.join(out, "media"))) and kinds[-1] == "Gap.1"
    clip = next(c for c in tracks[0]["children"] if c["OTIO_SCHEMA"] == "Clip.1")
    assert clip["media_reference"]["target_url"].startswith("media/") and clip["source_range"]["duration"]["rate"] == 24


def test_the_fcpxml_parses_and_matches_the_cut(film):
    out = X.write(film)["dir"]
    root = ET.parse(os.path.join(out, "Last_Train.fcpxml")).getroot()
    assert root.tag == "fcpxml" and root.get("version") == "1.9"
    clips = root.findall(".//spine/asset-clip")
    assert len(clips) == len(os.listdir(os.path.join(out, "media")))
    offs = [int(c.get("offset").split("/")[0]) for c in clips]
    assert offs[0] == 0 and offs == sorted(offs)
    assert root.find(".//format").get("width") == "1920"


def test_the_manifest_lists_every_shot_including_ones_with_no_take(film):
    out = X.write(film)["dir"]
    rows = list(csv.DictReader(open(os.path.join(out, "shots.csv"), encoding="utf-8")))
    assert len(rows) == len(make._contracts(film)) and rows[-1]["take"] == "" and rows[0]["model"] == "wan" and rows[0]["cost"] == "0.5"
    j = json.load(open(os.path.join(out, "shots.json"), encoding="utf-8"))
    assert j["shots"][-1]["take"] is None and j["fps"] == 24


def test_subtitles_carry_the_dialogue_timed_inside_each_shot(film):
    out = X.write(film)["dir"]
    s = open(os.path.join(out, "Last_Train.srt"), encoding="utf-8").read()
    assert "Sarah: He said he would call." in s and "John: Did you say something?" in s and "-->" in s


def test_nothing_to_hand_off_without_shots(tmp_path):
    d = story.create(str(tmp_path), "T", "screenplay", SCRIPT)["dir"]
    with pytest.raises(SystemExit, match="no shots"):
        X.write(d)


def test_a_missing_take_file_is_left_out_not_a_broken_link(film):
    rd = make.render_dir(film)
    os.remove(os.path.join(rd, "media", "v0.mp4"))
    r = X.write(film)
    assert "S01-01" in r["missing"]
    assert "S01-01 scene" not in open(os.path.join(r["dir"], "Last_Train.edl"), encoding="utf-8").read()


def test_the_command_line(film, capsys):
    assert X.main(["write", film]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["event"] == "result"
    assert X.main(["write", film + "-nope"]) == 1


def test_the_real_opentimelineio_library_reads_the_otio_and_the_edl(film):
    otio = pytest.importorskip("opentimelineio")
    out = X.write(film)["dir"]
    tl = otio.adapters.read_from_file(os.path.join(out, "Last_Train.otio"))
    placed = len(os.listdir(os.path.join(out, "media")))
    assert tl.name == "Last Train" and len(tl.video_tracks()[0].find_clips()) == placed
    try:
        edl = otio.adapters.read_from_file(os.path.join(out, "Last_Train.edl"), adapter_name="cmx_3600", rate=24)
    except Exception as e:                                                         # the error's name differs between versions of the library, and newer versions ship the CMX 3600 reader as a separate package
        if "cmx_3600" in str(e) or "adapter" in str(e).lower():
            pytest.skip("the CMX 3600 adapter is not installed")
        raise
    assert len(edl.video_tracks()[0].find_clips()) == placed
    assert edl.duration().to_frames() == sum(c.duration().to_frames() for c in tl.video_tracks()[0].find_clips())     # the same cut (the OTIO also keeps a gap where a shot has no take yet)


def test_the_edl_names_each_clip_after_the_copy_in_the_folder(film):
    r = X.write(film)
    out = r["dir"]
    names = {f for f in os.listdir(os.path.join(out, "media"))}
    edl_names = [line.split(": ", 1)[1] for line in open(os.path.join(out, [f for f in os.listdir(out) if f.endswith(".edl")][0]), encoding="utf-8").read().splitlines() if line.startswith("* FROM CLIP NAME")]
    assert edl_names and all(n in names for n in edl_names), (edl_names, names)
    assert len(set(edl_names)) == len(edl_names)                              # one clip per event, never the same file twice
