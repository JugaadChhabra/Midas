"""The daily video_sync job: keeps every channel's video list fresh whatever
autopilot is doing. Before it existed, sync ran only inside autopilot's
title-audit path, so pausing title autopilot stopped it on every channel."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app import main, sync
from app.job_status import JobRunFailed
from app.youtube_client import TokenExpiredError


def _ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


# ── the rules (app.sync) ─────────────────────────────────────────────────────

def test_is_stale():
    assert sync.is_stale({}) is True
    assert sync.is_stale({"last_synced_at": "not-a-date"}) is True
    assert sync.is_stale({"last_synced_at": _ago(hours=7)}) is True
    assert sync.is_stale({"last_synced_at": _ago(hours=1)}) is False


def test_routine_sync_fresh_does_nothing():
    with patch.object(sync, "sync_channel") as sc, patch.object(sync, "refresh_stats") as rs:
        assert sync.routine_sync({"id": "c", "last_synced_at": _ago(hours=1)}) == "fresh"
    sc.assert_not_called()
    rs.assert_not_called()


def test_routine_sync_full_when_due():
    ch = {"id": "c", "last_synced_at": _ago(days=2), "last_full_synced_at": _ago(days=4)}
    with patch.object(sync, "sync_channel") as sc, patch.object(sync, "refresh_stats") as rs:
        assert sync.routine_sync(ch) == "full"
    sc.assert_called_once_with("c", full=True)
    rs.assert_not_called()                       # a full pass refreshes stats itself


def test_routine_sync_incremental_otherwise():
    ch = {"id": "c", "last_synced_at": _ago(days=2), "last_full_synced_at": _ago(days=1)}
    with patch.object(sync, "sync_channel") as sc, patch.object(sync, "refresh_stats") as rs:
        assert sync.routine_sync(ch) == "incremental"
    sc.assert_called_once_with("c")
    rs.assert_called_once_with("c")


# ── the job (app.main) ───────────────────────────────────────────────────────

def _run_job(rows, routine):
    with patch.object(main.eligibility, "channels_for", return_value=rows), \
         patch.object(main.sync, "routine_sync", side_effect=routine):
        main._daily_video_sync()


def test_job_syncs_every_channel_including_autopilot_off():
    seen = []
    rows = [{"id": "a", "autopilot_enabled": False}, {"id": "b"}]
    _run_job(rows, lambda ch: seen.append(ch["id"]) or "incremental")
    assert seen == ["a", "b"]


def test_job_treats_expired_token_as_a_skip_not_a_failure():
    def routine(ch):
        if ch["id"] == "expired":
            raise TokenExpiredError("expired")
        return "incremental"
    _run_job([{"id": "expired"}, {"id": "ok"}], routine)    # no raise


def test_job_fails_the_run_naming_the_channel_but_syncs_the_rest():
    seen = []

    def routine(ch):
        seen.append(ch["id"])
        if ch["id"] == "bad":
            raise RuntimeError("playlistItems.list 500")
        return "incremental"

    with pytest.raises(JobRunFailed) as exc_info:
        _run_job([{"id": "bad"}, {"id": "good"}], routine)
    assert seen == ["bad", "good"]
    assert list(exc_info.value.failed_channels) == ["bad"]


def test_job_is_registered_at_04_utc_regardless_of_freeze_flags():
    sched = BackgroundScheduler(daemon=True)
    with patch.multiple(main.settings, PLAYLIST_DISCOVERY_ENABLED=False,
                        PLAYLIST_RECONCILE_WRITES_ENABLED=False,
                        PLAYLIST_TUNING_ENABLED=False, REFLECTION_ENABLED=False):
        main._register_jobs(sched)
    job = sched.get_job("video_sync")
    assert job is not None
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "4" and fields["minute"] == "0"
    assert str(job.trigger.timezone) == "UTC"
