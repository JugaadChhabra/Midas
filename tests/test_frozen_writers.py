"""A4: the four unmeasured writers are frozen behind flags that default off.

Registration is checked by introspecting an unstarted scheduler that
``main._register_jobs`` fills — nothing is started, nothing fires.
"""
import logging
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.testclient import TestClient

from app import main
from tests.fakes import FakeSupabase

FROZEN_JOBS = [
    ("PLAYLIST_DISCOVERY_ENABLED", "playlist_discovery"),
    ("PLAYLIST_TUNING_ENABLED", "playlist_tuning"),
    ("REFLECTION_ENABLED", "reflection"),
]
ALL_FLAGS = [flag for flag, _ in FROZEN_JOBS] + ["PLAYLIST_RECONCILE_WRITES_ENABLED"]


def _registered_ids(**flags) -> set[str]:
    sched = BackgroundScheduler(daemon=True)
    with patch.multiple(main.settings, **flags):
        main._register_jobs(sched)
    return {job.id for job in sched.get_jobs()}


def test_every_freeze_flag_defaults_off():
    # Settings reads the environment at import, so check the default in a
    # fresh interpreter with every flag unset.
    env = {k: v for k, v in os.environ.items() if k not in ALL_FLAGS}
    code = ("from app.config import settings; "
            f"print([getattr(settings, f) for f in {ALL_FLAGS!r}])")
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == str([False] * len(ALL_FLAGS))


@pytest.mark.parametrize("flag,job_id", FROZEN_JOBS)
def test_frozen_job_absent_when_flag_off(flag, job_id):
    assert job_id not in _registered_ids(**{flag: False})


@pytest.mark.parametrize("flag,job_id", FROZEN_JOBS)
def test_frozen_job_present_when_flag_on(flag, job_id):
    assert job_id in _registered_ids(**{flag: True})


@pytest.mark.parametrize("flag,job_id", FROZEN_JOBS)
def test_frozen_job_logs_one_line_naming_the_flag(flag, job_id, caplog):
    with caplog.at_level(logging.INFO, logger="midas.main"):
        _registered_ids(**{flag: False})

    naming = [r for r in caplog.records if flag in r.getMessage()]
    assert len(naming) == 1
    assert job_id in naming[0].getMessage()


@pytest.mark.parametrize("writes", [False, True])
def test_reconcile_registers_regardless_of_writes_flag(writes):
    # Sync still has to run daily, so the job stays registered either way.
    assert "playlist_reconcile" in _registered_ids(PLAYLIST_RECONCILE_WRITES_ENABLED=writes)


def test_unfrozen_jobs_still_register_with_every_flag_off():
    ids = _registered_ids(**{flag: False for flag in ALL_FLAGS})
    assert {"autopilot", "shorts_dispatch", "playlist_reconcile", "metrics_poll",
            "reporting_poll", "playlist_health_score", "measurement_eval",
            "nightly_db_backup"} <= ids


def _run_daily_reconcile(writes: bool):
    """Run the real _daily_reconcile → reconcile_channel over a FakeSupabase.

    One embedded video sits well above PLAYLIST_JOIN_HIGH for a playlist it is
    not in, and one member sits below PLAYLIST_LEAVE with the judge agreeing,
    so with writes on (and HITL off) reconcile inserts AND deletes — the
    writes-on case proves the fixture reaches both YouTube calls.
    """
    import app.playlists as pl

    fake = FakeSupabase(tables={
        "playlists": [{"id": "p1", "channel_id": "a", "title": "Colors", "description": ""}],
        "videos": [{"id": "v_in", "channel_id": "a"}, {"id": "v_out", "channel_id": "a"}],
        "playlist_assignments": [{
            "playlist_id": "p1", "video_id": "v_out", "action": "added",
            "playlist_item_id": "item_out", "decided_at": "2026-09-01T00:00:00+00:00",
        }],
    })
    sims = {("p1", "v_in"): 0.95, ("p1", "v_out"): 0.10}
    sync = MagicMock(return_value={})
    with patch.multiple(main.settings, PLAYLIST_RECONCILE_WRITES_ENABLED=writes,
                        PLAYLIST_HITL=False, DRY_RUN=False), \
         patch.object(main, "JobBudget"), \
         patch.object(main.eligibility, "channel_ids_for", return_value=["a"]), \
         patch.object(main, "_reconcile_channel_order", side_effect=lambda ids: ids), \
         patch.object(main, "sync_playlists", sync), \
         patch.object(pl, "supabase", return_value=fake), \
         patch.object(pl, "_sims_matrix", return_value=(sims, {"p1"})), \
         patch.object(pl, "_llm_judge", return_value=True), \
         patch.object(pl, "youtube_for_channel"), \
         patch.object(pl, "yt_playlist_items_insert", return_value="item_new") as yt_insert, \
         patch.object(pl, "yt_playlist_items_delete") as yt_delete:
        main._daily_reconcile()
    return sync, yt_insert, yt_delete, fake


def test_reconcile_with_writes_off_syncs_but_never_adds_or_removes(caplog):
    with caplog.at_level(logging.INFO, logger="midas.main"):
        sync, yt_insert, yt_delete, fake = _run_daily_reconcile(writes=False)

    assert [c.args[0] for c in sync.call_args_list] == ["a"]
    yt_insert.assert_not_called()
    yt_delete.assert_not_called()
    assert fake.writes == []
    assert any("PLAYLIST_RECONCILE_WRITES_ENABLED" in r.getMessage()
               and "skipped" in r.getMessage() for r in caplog.records)


def test_reconcile_with_writes_on_adds_and_removes():
    sync, yt_insert, yt_delete, _ = _run_daily_reconcile(writes=True)

    assert [c.args[0] for c in sync.call_args_list] == ["a"]
    yt_insert.assert_called_once()
    yt_delete.assert_called_once()


@pytest.mark.parametrize("path,flag", [
    ("/channels/c1/playlists/reconcile", "PLAYLIST_RECONCILE_WRITES_ENABLED"),
    ("/channels/c1/reflection/trigger", "REFLECTION_ENABLED"),
    ("/channels/c1/prompt-versions/7/promote", "REFLECTION_ENABLED"),
])
def test_frozen_endpoint_returns_409_naming_the_flag(path, flag):
    with patch.object(main.settings, flag, False), \
         patch("app.playlists_router.reconcile_channel") as reconcile, \
         patch("app.reflection.reflect") as reflect, \
         patch("app.reflection._promote_version") as promote:
        r = TestClient(main.app).post(path)

    assert r.status_code == 409
    assert flag in r.json()["detail"]
    reconcile.assert_not_called()
    reflect.assert_not_called()
    promote.assert_not_called()


def test_reconcile_endpoint_runs_when_writes_on():
    with patch.object(main.settings, "PLAYLIST_RECONCILE_WRITES_ENABLED", True), \
         patch("app.playlists_router.reconcile_channel", return_value={"added": 0}) as reconcile:
        r = TestClient(main.app).post("/channels/c1/playlists/reconcile")

    assert r.status_code == 200
    reconcile.assert_called_once_with("c1")


def test_reflection_trigger_runs_when_enabled():
    with patch.object(main.settings, "REFLECTION_ENABLED", True), \
         patch("app.reflection.reflect", return_value={"reflected": False}) as reflect:
        r = TestClient(main.app).post("/channels/c1/reflection/trigger")

    assert r.status_code == 200
    reflect.assert_called_once_with("c1")
