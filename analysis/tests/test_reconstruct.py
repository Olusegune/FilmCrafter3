"""AI-assisted set reconstruction on a real film folder, with a stand-in for the AI's answer (the real call is tried separately and costs money). What is tested for real: the pictures copied in, the cost and what is sent
(counted from the request the stand-in receives), the refusal to send without confirmation, the cleaning of a messy answer, the geometry from a bounding box (checked by projecting the result back), the draft set
as flat pictures and as boxes (real renders), the lock, and that a reference picture's original file is never touched."""
import json
import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
from filmcrafter_engine import bible, llm, placeset as PS, reconstruct as R, shots as S, story, worldlock as WL, worldmath as WM  # noqa: E402

SCRIPT = "INT. KITCHEN - DAY\n\nSARAH stirs a pot.\n\nSARAH\nBreakfast is ready.\n"


@pytest.fixture
def film(tmp_path):
    d = story.create(str(tmp_path / "films"), "T", "screenplay", SCRIPT)["dir"]
    bible.seed(d)
    S.breakdown(d)
    return d


def pid_of(d):
    return bible.load(d)["environments"][0]["id"]


@pytest.fixture
def photo(tmp_path):
    """A room: a grey wall, a brown table (left, near), a red chair (right, far)."""
    im = Image.new("RGB", (800, 450), (150, 150, 150))
    dr = ImageDraw.Draw(im)
    dr.rectangle((100, 250, 300, 420), fill=(120, 70, 30))       # table
    dr.rectangle((560, 230, 640, 330), fill=(200, 30, 30))       # chair
    p = str(tmp_path / "room.png")
    im.save(p)
    return p


ANSWER = {"scene": {"kind": "kitchen", "summary": "A small kitchen.", "indoor": True, "room_width_m": 4.0, "room_depth_m": 5.0, "lighting": "daylight from the left"},
          "objects": [
              {"name": "Table", "kind": "furniture", "picture": 0, "bbox": [0.125, 0.55, 0.375, 0.93], "distance_m": 3.0, "width_m": 1.2, "height_m": 0.8, "depth_m": 0.8, "facing": "toward the camera", "on_floor": True, "confidence": 0.8, "reason": "A flat top on legs.", "hidden": "the far side"},
              {"name": "Chair", "kind": "furniture", "picture": 0, "bbox": [0.7, 0.51, 0.8, 0.73], "distance_m": 4.5, "width_m": 0.5, "height_m": 0.9, "depth_m": 0.5, "facing": "toward the camera", "on_floor": True, "confidence": 0.5, "reason": "A seat with a back.", "hidden": "its back"},
              {"name": "Wall", "kind": "structure", "picture": 0, "bbox": [0, 0, 1, 1], "distance_m": 6.0, "width_m": 6.0, "height_m": 3.0, "depth_m": 0.1, "facing": "toward the camera", "on_floor": True, "confidence": 0.9, "reason": "The back wall.", "hidden": ""},
              {"name": "", "kind": "prop", "picture": 0, "bbox": [0.1, 0.1, 0.2, 0.2], "distance_m": 1, "width_m": 1, "height_m": 1, "depth_m": 1, "facing": "unknown", "on_floor": False, "confidence": 1, "reason": "x", "hidden": ""},
              {"name": "Sliver", "kind": "prop", "picture": 0, "bbox": [0.5, 0.5, 0.5, 0.9], "distance_m": 1, "width_m": 1, "height_m": 1, "depth_m": 1, "facing": "unknown", "on_floor": False, "confidence": 1, "reason": "x", "hidden": ""},
          ], "uncertainty": ["What is behind the table."], "missing_views": ["The opposite wall."]}


class Fake:
    def __init__(self, answer=ANSWER):
        self.answer, self.calls = answer, []
        self.models = SimpleNamespace(list=self._no_list)
        self.responses = SimpleNamespace(create=self.create)

    @staticmethod
    def _no_list():
        raise RuntimeError("no listing")

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(output_text=json.dumps(self.answer))


@pytest.fixture
def ai(monkeypatch):
    f = Fake()
    monkeypatch.setattr(llm, "client", lambda: f)
    monkeypatch.setattr(llm, "is_local", lambda: False)
    monkeypatch.setattr(llm, "price_per_mtok", lambda: None)
    return f


def test_a_reference_is_copied_in_and_the_original_is_untouched(film, photo):
    pid = pid_of(film)
    before = (os.path.getsize(photo), os.path.getmtime(photo))
    r = R.add_reference(film, pid, photo)
    assert len(r["references"]) == 1 and r["references"][0]["width"] == 800 and os.path.isfile(os.path.join(film, *r["references"][0]["file"].split("/")))
    assert (os.path.getsize(photo), os.path.getmtime(photo)) == before
    assert "hidden sides are not known" in r["limits"] and "No image-to-3D generator" in r["image_to_3d"]


def test_references_are_limited_and_must_be_pictures(film, photo, tmp_path):
    pid = pid_of(film)
    junk = tmp_path / "x.png"
    junk.write_bytes(b"nope")
    with pytest.raises(SystemExit, match="could not be read"):
        R.add_reference(film, pid, str(junk))
    with pytest.raises(SystemExit, match="Choose a picture"):
        R.add_reference(film, pid, str(tmp_path / "missing.png"))
    for _ in range(R.MAX_REFS):
        R.add_reference(film, pid, photo)
    with pytest.raises(SystemExit, match="At most 6"):
        R.add_reference(film, pid, photo)


def test_the_places_own_pictures_can_be_used(film, photo):
    pid = pid_of(film)
    bible.add_media(film, "environment", pid, photo, "Reference", "master")
    r = R.add_reference(film, pid, from_place=True)
    assert len(r["references"]) == 1


def test_nothing_is_sent_without_confirmation_and_the_estimate_says_what_would_be(film, photo, ai):
    pid = pid_of(film)
    with pytest.raises(SystemExit, match="Add at least one reference"):
        R.estimate(film, pid)
    R.add_reference(film, pid, photo)
    e = R.estimate(film, pid)
    assert e["pictures"] == 1 and e["usd"] > 0 and "512 pixels" in e["sends"] and e["local"] is False
    with pytest.raises(SystemExit, match="Confirm to go ahead"):
        R.propose(film, pid)
    assert ai.calls == []                                                   # nothing left the machine


def test_a_local_brain_needs_no_confirmation(film, photo, ai, monkeypatch):
    monkeypatch.setattr(llm, "is_local", lambda: True)
    pid = pid_of(film)
    R.add_reference(film, pid, photo)
    assert R.propose(film, pid)["proposal"]["items"]
    assert len(ai.calls) == 1


def test_the_proposal_is_cleaned_and_says_how_unsure_it_is(film, photo, ai):
    pid = pid_of(film)
    R.add_reference(film, pid, photo)
    r = R.propose(film, pid, confirmed=True)
    p = r["proposal"]
    assert [i["name"] for i in p["items"]] == ["Table", "Chair", "Wall"]                 # the nameless and the zero-width ones are dropped
    assert all(i["status"] == "proposed" and i["source"] == "inferred" for i in p["items"])
    assert p["uncertainty"] == ["What is behind the table."] and p["missing_views"] == ["The opposite wall."] and p["scene"]["kind"] == "kitchen"
    assert len(r["spend"]) == 1 and r["spend"][0]["usd_estimated"] > 0 and "not billed here" in r["spend"][0]["note"]
    req = ai.calls[0]
    imgs = [c for c in req["input"][1]["content"] if c["type"] == "input_image"]
    assert len(imgs) == 1 and imgs[0]["image_url"].startswith("data:image/jpeg;base64,") and req["text"]["format"]["strict"] is True
    assert "Never invent things you cannot see" in req["input"][0]["content"]


def test_a_broken_answer_changes_nothing(film, photo, monkeypatch):
    class Bad(Fake):
        def create(self, **kw):
            return SimpleNamespace(output_text="not json")
    monkeypatch.setattr(llm, "client", lambda: Bad())
    monkeypatch.setattr(llm, "is_local", lambda: False)
    monkeypatch.setattr(llm, "price_per_mtok", lambda: None)
    pid = pid_of(film)
    R.add_reference(film, pid, photo)
    with pytest.raises(SystemExit):
        R.propose(film, pid, confirmed=True)
    assert R.status(film, pid)["proposal"] is None


def test_the_geometry_projects_back_onto_the_bounding_box():
    it = {"bbox": [0.125, 0.55, 0.375, 0.93], "distance_m": 3.0, "on_floor": True, "depth_m": 0.8}
    g = R.draft_geometry(it, 55.0, 800 / 450)
    cam = {"x": 0, "y": 1.6, "z": 0, "yaw": 0, "pitch": 0, "fov": 55.0}
    sx, sy, _ = WM.project((g["x"], g["y"], g["z"]), cam, (800, 450))                  # the base centre of the region seen
    assert abs(sx - 0.25 * 800) < 3 and abs(sy - 0.93 * 450) < 3
    sx2, sy2, _ = WM.project((g["x"] - g["width"] / 2, g["y"] + g["height"], g["z"]), cam, (800, 450))   # its top left corner
    assert abs(sx2 - 0.125 * 800) < 3 and abs(sy2 - 0.55 * 450) < 4
    assert g["box_y"] == 0.0 and g["box_height"] >= g["y"] + g["height"] - 0.01        # a volume on the floor reaches from the floor to the top seen
    far = R.draft_geometry({**it, "distance_m": 6.0}, 55.0, 800 / 450)
    assert far["width"] == pytest.approx(g["width"] * 2, rel=0.02)                      # twice as far, the same picture region, twice the size


def test_correcting_an_item_and_accepting(film, photo, ai):
    pid = pid_of(film)
    R.add_reference(film, pid, photo)
    R.propose(film, pid, confirmed=True)
    r = R.item_set(film, pid, "it-01", {"name": "Kitchen table", "distance_m": 2.5, "status": "accepted", "kind": "bogus"})
    t = r["proposal"]["items"][0]
    assert t["name"] == "Kitchen table" and t["distance_m"] == 2.5 and t["status"] == "accepted" and t["kind"] == "furniture" and t["edited"]
    with pytest.raises(SystemExit, match="isn't in the proposal"):
        R.item_set(film, pid, "it-99", {})
    r = R.accept_all(film, pid, 0.7)
    assert [i["status"] for i in r["proposal"]["items"]] == ["accepted", "proposed", "accepted"]       # the 0.5-confidence chair is left for the person to decide
    assert R.item_set(film, pid, "", {"assumed": {"fov": 70}})["assumed"]["fov"] == 70.0


def test_the_draft_as_flat_pictures_shows_the_reference_from_the_reference_camera(film, photo, ai):
    pid = pid_of(film)
    R.add_reference(film, pid, photo)
    R.propose(film, pid, confirmed=True)
    with pytest.raises(SystemExit, match="Accept at least one"):
        R.build(film, pid)
    R.accept_all(film, pid)
    r = R.build(film, pid, "layers")
    sid = r["built"]["set"]
    s = WL.get(film, sid)
    assert len(s["assets"]) == 3 and all("inferred" in a["tags"] and "Hidden sides are not known" in a["note"] for a in s["assets"]) and not s["locked"] and s["name"].endswith("(draft from a picture)")
    assert PS.status(film, pid)["set"]["mode"] == "reconstructed" and "correct it" in PS.status(film, pid)["next"]
    v = WL.render(film, sid, {"camera": s["cameras"][0]["id"], "size": [400, 225]})
    im = np.asarray(Image.open(os.path.join(film, *v["file"].split("/"))).convert("RGB"), dtype=np.float32)
    assert np.abs(im[int(0.75 * 225), int(0.25 * 400)] - np.array([120, 70, 30])).max() < 40        # the table is where it was in the picture, and brown
    assert np.abs(im[int(0.62 * 225), int(0.75 * 400)] - np.array([200, 30, 30])).max() < 40         # and the chair, red


def test_the_draft_as_boxes_has_volumes_of_the_visible_size(film, photo, ai):
    pid = pid_of(film)
    R.add_reference(film, pid, photo)
    R.propose(film, pid, confirmed=True)
    R.accept_all(film, pid)
    r = R.build(film, pid, "boxes")
    s = WL.get(film, r["built"]["set"])
    assert len(s["models"]) == 2 and len(s["assets"]) == 1                    # the table and chair as boxes; the wide wall stays a flat picture
    t = next(m for m in s["models"] if m["name"] == "Table")
    assert t["summary"]["size"][0] == pytest.approx(R.draft_geometry(ANSWER["objects"][0], 55.0, 800 / 450)["width"], abs=0.02) and t["summary"]["triangles"] == 12
    v = WL.render(film, s["id"], {"camera": s["cameras"][0]["id"], "size": [400, 225]})
    im = np.asarray(Image.open(os.path.join(film, *v["file"].split("/"))).convert("RGB"), dtype=np.float32)
    assert im.std() > 5                                                        # something is drawn


def test_approving_locks_the_draft_and_it_stays_a_draft_until_then(film, photo, ai):
    pid = pid_of(film)
    R.add_reference(film, pid, photo)
    R.propose(film, pid, confirmed=True)
    R.accept_all(film, pid)
    with pytest.raises(SystemExit, match="Build the draft first"):
        R.approve(film, pid)
    r = R.build(film, pid)
    sid = r["built"]["set"]
    assert WL.get(film, sid)["locked"] is False
    r = R.approve(film, pid)
    assert r["approved"] and WL.get(film, sid)["locked"] is True
    with pytest.raises(SystemExit, match="locked"):
        WL.asset_set(film, sid, {"id": WL.get(film, sid)["assets"][0]["id"], "x": 1})
    with pytest.raises(SystemExit, match="approved"):
        R.build(film, pid)
    assert "locked" in PS.status(film, pid)["next"]


def test_a_place_with_another_kind_of_set_cannot_be_rebuilt_over(film, photo, ai):
    pid = pid_of(film)
    R.add_reference(film, pid, photo)
    R.propose(film, pid, confirmed=True)
    R.accept_all(film, pid)
    bible.add_media(film, "environment", pid, photo, "Reference", "master")
    PS.from_pictures(film, pid)
    with pytest.raises(SystemExit, match="already has a set"):
        R.build(film, pid)


def test_models_of_other_sets_are_offered_for_reuse_by_name_only(film, photo, ai, tmp_path):
    from glbtools import cube_faces, glb
    other = WL.create(film, {"name": "Other"})["id"]
    g = str(tmp_path / "t.glb")
    open(g, "wb").write(glb(cube_faces(1.0)))
    WL.model_add(film, other, {"path": g, "name": "Table"})
    pid = pid_of(film)
    R.add_reference(film, pid, photo)
    r = R.propose(film, pid, confirmed=True)
    assert r["proposal"]["reuse"] and r["proposal"]["reuse"][0]["name"] == "Table"
    R.accept_all(film, pid)
    s = WL.get(film, R.build(film, pid, "boxes")["built"]["set"])
    assert all(m["name"] != "Table" or m["summary"]["triangles"] == 12 for m in s["models"])        # a box, never the other set's model


def test_the_command_line(film, photo, ai, capsys):
    pid = pid_of(film)
    assert R.main(["add_reference", film, "--data", json.dumps({"place": pid, "path": photo})]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["event"] == "result"
    assert R.main(["propose", film, "--data", json.dumps({"place": pid})]) == 1
    assert "Confirm to go ahead" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])["message"]
