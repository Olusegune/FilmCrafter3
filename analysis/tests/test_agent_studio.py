import json
import os
import pytest
from filmcrafter_engine import agent_studio as A


def project(tmp_path):
    d = tmp_path / "film"; d.mkdir()
    (d / "project.json").write_text(json.dumps({"title": "Test", "aspect_ratio": "16:9"}), encoding="utf-8")
    (d / "jobs.json").write_text(json.dumps({"jobs": []}), encoding="utf-8")
    return str(d)


def test_plan_requires_a_story_and_persists_after_restart(tmp_path):
    d = project(tmp_path)
    with pytest.raises(SystemExit, match="story or script"): A.create_plan(d)
    A.update_brief(d, {"story": "A child follows a paper bird through a sleeping city."})
    made = A.create_plan(d)
    assert made["stages"][0]["state"] == "needs_approval"
    assert A.state(d)["brief"]["story"].startswith("A child")


def test_approval_advances_but_never_creates_a_provider_job(tmp_path):
    d = project(tmp_path)
    A.update_brief(d, {"story": "A child follows a paper bird through a sleeping city."})
    A.create_plan(d); out = A.approve(d, {"stage": "story", "asset_versions": ["plan-v1"]})
    assert out["stages"][0]["state"] == "complete" and out["stages"][1]["state"] == "ready"
    assert json.load(open(os.path.join(d, "jobs.json")))["jobs"] == []


def test_revision_keeps_approvals_and_records_bounded_affected_assets(tmp_path):
    d = project(tmp_path)
    A.update_brief(d, {"story": "A child follows a paper bird through a sleeping city."})
    A.create_plan(d); A.approve(d, {"stage": "story", "asset_versions": ["plan-v1"]})
    out = A.request_changes(d, {"stage": "direction", "note": "Warmer light", "affected": ["S01-03"]})
    assert out["approvals"][0]["asset_versions"] == ["plan-v1"]
    assert out["revisions"][0]["affected"] == ["S01-03"]


def test_budget_and_inputs_are_validated(tmp_path):
    d = project(tmp_path)
    with pytest.raises(SystemExit): A.update_brief(d, {"budget_limit": -1})
    with pytest.raises(SystemExit): A.update_brief(d, {"aspect": "10:1"})
    out = A.update_brief(d, {"budget_limit": 12.5, "checkin_mode": "guided", "story": "x" * 25000})
    assert out["spending"]["limit"] == 12.5 and len(out["brief"]["story"]) == 20000


def test_pause_is_recoverable_and_does_not_touch_running_jobs(tmp_path):
    d = project(tmp_path)
    jobs = {"jobs": [{"id": "j1", "state": "submitted", "estimate_usd": 1.25}]}
    (tmp_path / "film" / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    out = A.pause(d, True)
    assert out["paused"] and out["spending"]["committed"] == 1.25
    assert json.load(open(os.path.join(d, "jobs.json"))) == jobs


def test_accepted_analysis_writes_resumable_whole_film_manifest(tmp_path):
    d = project(tmp_path)
    A.update_brief(d, {"story": "A child follows a paper bird through a sleeping city.", "image_provider": "fal", "image_model": "image-x", "video_provider": "kie", "video_model": "video-y", "music_provider": "kie_suno", "sfx_provider": "elevenlabs_sfx"})
    w = A._load(d)
    w["analysis"] = {"status": "proposed", "logline": "Follow the bird.", "genre": "fantasy", "tone": "wonder", "characters": [{"name": "Mia", "role": "lead", "appearance": "small silhouette", "wardrobe": "yellow coat", "voice": "quiet and curious"}], "locations": [{"name": "City", "design": "sleeping streets", "lighting": "moonlight"}], "props": [{"name": "Bird", "design": "folded paper", "continuity": "keep one torn wing"}], "scenes": [], "sound_direction": "hushed city", "score_prompt": "delicate felt piano", "sfx_plan": [], "motion_graphics": [], "visual_style": "cinematic", "director_style_id": ""}
    A._save(d, w)
    A.accept_analysis(d, {"style": "cinematic", "director_style_id": ""})
    manifest = json.load(open(os.path.join(d, "agent-production.json"), encoding="utf-8"))
    assert manifest["story_unchanged"] is True
    assert manifest["models"]["image_model"] == "image-x" and manifest["models"]["music_provider"] == "kie_suno"
    assert manifest["creative"]["characters"][0]["wardrobe"] == "yellow coat"


def test_provider_choices_are_bounded_plain_text_and_never_become_paths(tmp_path):
    d = project(tmp_path)
    hostile = "../secrets\x00\n" + "x" * 1000
    out = A.update_brief(d, {"story": "A sufficiently long story for a safe production plan.", "image_model": hostile, "music_provider": hostile})
    assert len(out["brief"]["image_model"]) <= 160 and len(out["brief"]["music_provider"]) <= 160
    assert "\x00" not in out["brief"]["image_model"]
    assert not os.path.exists(os.path.join(tmp_path, "secrets"))


def test_corrupt_agent_state_recovers_without_touching_the_project(tmp_path):
    d = project(tmp_path)
    before = open(os.path.join(d, "project.json"), "rb").read()
    open(os.path.join(d, A.FILE), "wb").write(b"{not json")
    out = A.state(d)
    assert out["current"] == "story" and out["analysis"] is None
    assert open(os.path.join(d, "project.json"), "rb").read() == before


def test_manifest_replaces_atomically_and_does_not_leave_temporary_files(tmp_path):
    d = project(tmp_path)
    A.update_brief(d, {"story": "A sufficiently long story for an atomic production package."})
    w = A._load(d); w["analysis"] = {"status": "proposed", "visual_style": "storybook", "director_style_id": "", "characters": [], "locations": [], "props": [], "scenes": [], "sound_direction": "", "score_prompt": "", "sfx_plan": [], "motion_graphics": []}; A._save(d, w)
    A.accept_analysis(d, {})
    w = A._load(d); w["analysis"]["score_prompt"] = "new score"; A._save(d, w); A.accept_analysis(d, {})
    assert json.load(open(os.path.join(d, "agent-production.json"), encoding="utf-8"))["creative"]["score_prompt"] == "new score"
    assert not [x for x in os.listdir(d) if x.endswith(".tmp")]


def test_revision_impact_targets_matching_character_and_preserves_other_approvals(tmp_path):
    d = project(tmp_path)
    plan = {"scenes": [{"number": 1, "heading": "PLAYGROUND", "shots": [
        {"id": "S01-01", "performers": ["Chloe"], "description": "Chloe waits"},
        {"id": "S01-02", "performers": ["Mia"], "description": "Mia enters"}]}]}
    open(os.path.join(d, "directed.json"), "w", encoding="utf-8").write(json.dumps(plan))
    manifest = {"creative": {"characters": [{"name": "Chloe"}, {"name": "Mia"}], "locations": []}}
    open(os.path.join(d, "agent-production.json"), "w", encoding="utf-8").write(json.dumps(manifest))
    w = A._load(d); w["approvals"] = [{"asset_versions": ["S01-01", "S01-02"]}]; A._save(d, w)
    impact = A.run("impact", d, {"stage": "scenes", "note": "Make Chloe's close-up warmer"})
    assert impact["affected_shots"] == ["S01-01"]
    assert impact["preserved_approved_assets"] == 1
    assert impact["needs_clarification"] is False


def test_ambiguous_revision_is_recordable_but_cannot_claim_a_regeneration_scope(tmp_path):
    d = project(tmp_path)
    impact = A.run("impact", d, {"stage": "direction", "note": "Make it better"})
    assert impact["affected_shots"] == [] and impact["needs_clarification"] is True
    out = A.request_changes(d, {"stage": "direction", "note": "Make it better"})
    assert out["revisions"][0]["impact"]["needs_clarification"] is True
    assert json.load(open(os.path.join(d, "jobs.json")))["jobs"] == []


def test_inbox_and_orchestration_recover_actions_after_restart(tmp_path):
    d = project(tmp_path)
    A.update_brief(d, {"story": "A child follows a paper bird through a sleeping city."}); A.create_plan(d)
    jobs = {"jobs": [{"id": "bad-1", "state": "failed", "error": "provider timeout"},
                     {"id": "maybe-1", "state": "uncertain"}]}
    open(os.path.join(d, "jobs.json"), "w", encoding="utf-8").write(json.dumps(jobs))
    restored = A.state(d)
    assert {x["kind"] for x in restored["inbox"]} == {"approval", "failure", "uncertain"}
    assert restored["orchestration"]["status"] == "waiting"
    before = jobs.copy(); A.run("orchestrate", d, {})
    assert json.load(open(os.path.join(d, "jobs.json"))) == before
