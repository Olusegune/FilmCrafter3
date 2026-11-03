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
