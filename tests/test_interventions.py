"""Phase B · B2 (#32): the interventions record and the holdout assignment.

assign_arm must give the same answer in every process (it decides which videos
are never changed, so a drift would move videos between arms mid-experiment),
and active_for/record enforce spec Part 2 §1.6: at most one active Midas
intervention per video. Human interventions (B3) never block it.
"""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app import interventions as iv
from app import status_vocab as sv
from tests.fakes import FakeSupabase

REPO = Path(__file__).resolve().parents[1]


# ── assign_arm ───────────────────────────────────────────────────────────

#: Pinned at HOLDOUT_PCT = 0.20. If any of these change, every running
#: experiment's arms have been reshuffled.
FIXED_VECTORS = [
    ("dQw4w9WgXcQ", "backlinks", 0.4869),     # treated
    ("dQw4w9WgXcQ", "title", 0.2481),         # treated, just
    ("abcdefghijk", "backlinks", 0.0079),     # holdout
    ("abcdefghijk", "playlist", 0.7776),      # same video, other lever: treated
    ("jNQXAC9IVRw", "short_link", 0.1954),    # holdout, just
    ("kJQP7kiw5Fk", "backlinks", 0.1084),     # holdout
]


@pytest.mark.parametrize("video_id,lever,bucket", FIXED_VECTORS)
def test_bucket_is_pinned(video_id, lever, bucket):
    assert iv._bucket(video_id, lever) == pytest.approx(bucket, abs=1e-4)


@pytest.mark.parametrize("video_id,lever,bucket", FIXED_VECTORS)
def test_arm_follows_the_pinned_bucket(video_id, lever, bucket, monkeypatch):
    monkeypatch.setattr(iv.settings, "HOLDOUT_PCT", 0.20)
    want = sv.InterventionArm.HOLDOUT if bucket < 0.20 else sv.InterventionArm.TREATED
    assert iv.assign_arm(video_id, lever) == want


def test_arm_is_stable_across_processes():
    """Python's hash() is salted per process; force different salts and compare."""
    code = (
        "from app.interventions import assign_arm\n"
        "print(','.join(assign_arm(f'v{i:05d}', 'backlinks') for i in range(200)))"
    )
    outs = set()
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONPATH": str(REPO), "PYTHONHASHSEED": seed,
               "HOLDOUT_PCT": "0.20"}
        outs.add(subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                                capture_output=True, text=True, check=True).stdout)
    assert len(outs) == 1
    with patch.object(iv.settings, "HOLDOUT_PCT", 0.20):
        assert outs.pop().strip() == ",".join(
            iv.assign_arm(f"v{i:05d}", "backlinks") for i in range(200))


def test_arm_is_stable_across_calls():
    first = [iv.assign_arm(f"v{i}", "title") for i in range(500)]
    assert first == [iv.assign_arm(f"v{i}", "title") for i in range(500)]


def test_holdout_share_is_about_holdout_pct(monkeypatch):
    monkeypatch.setattr(iv.settings, "HOLDOUT_PCT", 0.20)
    arms = [iv.assign_arm(f"vid{i:07d}", "backlinks") for i in range(10_000)]
    share = arms.count(sv.InterventionArm.HOLDOUT) / len(arms)
    assert 0.185 < share < 0.215   # ±3.75 sd at n=10k


def test_holdout_pct_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(iv.settings, "HOLDOUT_PCT", 0.0)
    assert {iv.assign_arm(f"v{i}", "title") for i in range(200)} == {"treated"}
    monkeypatch.setattr(iv.settings, "HOLDOUT_PCT", 1.0)
    assert {iv.assign_arm(f"v{i}", "title") for i in range(200)} == {"holdout"}


def test_levers_give_independent_arms(monkeypatch):
    """Being held out for backlinks says nothing about the title arm: the joint
    holdout rate is about HOLDOUT_PCT², not HOLDOUT_PCT."""
    monkeypatch.setattr(iv.settings, "HOLDOUT_PCT", 0.20)
    ids = [f"vid{i:07d}" for i in range(10_000)]
    a = [iv.assign_arm(v, "backlinks") == "holdout" for v in ids]
    b = [iv.assign_arm(v, "title") == "holdout" for v in ids]
    both = sum(x and y for x, y in zip(a, b)) / len(ids)
    assert 0.03 < both < 0.05      # 0.04 if independent; 0.20 if identical
    assert a != b


def test_unknown_lever_is_refused():
    with pytest.raises(ValueError):
        iv.assign_arm("dQw4w9WgXcQ", "thumbnail")


# ── active_for / record ──────────────────────────────────────────────────

def _row(**kw):
    base = {"id": 1, "video_id": "v1", "channel_id": "c1", "lever": "backlinks",
            "origin": "midas", "arm": "treated", "status": "applied"}
    return {**base, **kw}


def _sb(rows=()):
    return FakeSupabase({"interventions": list(rows)})


def test_active_for_finds_an_active_midas_intervention():
    sb = _sb([_row(status="measuring")])
    with patch.object(iv, "supabase", return_value=sb):
        assert iv.active_for("v1")["id"] == 1


@pytest.mark.parametrize("status", sorted(sv.ACTIVE_INTERVENTION_STATUSES))
def test_every_active_status_counts(status):
    with patch.object(iv, "supabase", return_value=_sb([_row(status=status)])):
        assert iv.active_for("v1") is not None


@pytest.mark.parametrize("status", sorted(
    sv.ALL_INTERVENTION_STATUSES - sv.ACTIVE_INTERVENTION_STATUSES))
def test_finished_statuses_do_not_count(status):
    with patch.object(iv, "supabase", return_value=_sb([_row(status=status)])):
        assert iv.active_for("v1") is None


def test_human_interventions_do_not_count():
    sb = _sb([_row(origin="human", arm="n/a", status="applied")])
    with patch.object(iv, "supabase", return_value=sb):
        assert iv.active_for("v1") is None


def test_other_videos_do_not_count():
    with patch.object(iv, "supabase", return_value=_sb([_row(video_id="v2")])):
        assert iv.active_for("v1") is None


def _record_midas(**kw):
    args = dict(video_id="v1", channel_id="c1", lever="title", origin="midas",
                arm="treated", status="planned")
    return iv.record(**{**args, **kw})


def test_record_writes_the_row():
    sb = _sb()
    with patch.object(iv, "supabase", return_value=sb):
        row = _record_midas(payload={"x": 1}, audit_id=7)
    assert sb.writes == [("interventions", "insert", row)]
    assert row["lever"] == "title" and row["payload"] == {"x": 1} and row["audit_id"] == 7


def test_second_active_midas_intervention_is_rejected():
    sb = _sb()
    with patch.object(iv, "supabase", return_value=sb):
        _record_midas(lever="backlinks")
        with pytest.raises(iv.ActiveInterventionExists):
            _record_midas(lever="title")         # any lever (§1.6)
    assert len(sb.rows("interventions")) == 1


def test_holdout_blocks_like_a_treated_change():
    """A held-out video is in the experiment for the window; changing it would
    contaminate the control arm."""
    sb = _sb([_row(arm="holdout", status="holdout")])
    with patch.object(iv, "supabase", return_value=sb):
        with pytest.raises(iv.ActiveInterventionExists):
            _record_midas()


def test_finished_midas_intervention_does_not_block():
    sb = _sb([_row(status="judged")])
    with patch.object(iv, "supabase", return_value=sb):
        _record_midas()
    assert len(sb.rows("interventions")) == 2


def test_human_intervention_does_not_block_midas():
    sb = _sb([_row(origin="human", arm="n/a", status="applied")])
    with patch.object(iv, "supabase", return_value=sb):
        _record_midas()
    assert len(sb.rows("interventions")) == 2


def test_human_interventions_are_never_blocked():
    """B3 records every human edit it sees, whatever Midas is doing."""
    sb = _sb([_row(status="applied")])
    with patch.object(iv, "supabase", return_value=sb):
        iv.record(video_id="v1", channel_id="c1", lever="backlinks", origin="human",
                  arm="n/a", status="applied", detected_at="2026-10-06T00:00:00+00:00")
    assert len(sb.rows("interventions")) == 2


def test_a_finished_record_does_not_need_the_check():
    """A declined triage is not a change, so it neither blocks nor is blocked."""
    sb = _sb([_row(status="applied")])
    with patch.object(iv, "supabase", return_value=sb):
        _record_midas(status="declined", arm="n/a")
    assert len(sb.rows("interventions")) == 2


@pytest.mark.parametrize("field,value", [
    ("lever", "thumbnail"), ("origin", "robot"), ("arm", "control"), ("status", "done"),
])
def test_record_refuses_values_outside_the_vocabulary(field, value):
    with patch.object(iv, "supabase", return_value=_sb()):
        with pytest.raises(ValueError):
            _record_midas(**{field: value})


@pytest.mark.parametrize("arm", ["treated", "holdout"])
def test_human_interventions_have_no_arm(arm):
    """Spec Part 2 §1.4: there's no holdout for human edits."""
    with patch.object(iv, "supabase", return_value=_sb()):
        with pytest.raises(ValueError):
            iv.record(video_id="v1", channel_id="c1", lever="backlinks", origin="human",
                      arm=arm, status="applied")


def test_record_with_a_ledger_key_skips_a_stored_key():
    """B3's idempotency: the same key again is ON CONFLICT DO NOTHING."""
    sb = _sb()
    args = dict(video_id="v1", channel_id="c1", lever="backlinks", origin="human",
                arm="n/a", status="applied", ledger_key="backlinks:v1:v2:abc")
    with patch.object(iv, "supabase", return_value=sb):
        assert iv.record(**args)["ledger_key"] == "backlinks:v1:v2:abc"
        assert iv.record(**args) is None
    assert len(sb.rows("interventions")) == 1
