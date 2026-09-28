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


def _run_daily_reconcile(writes: bool, reconcile=None):
    sync = MagicMock(return_value={})
    reconcile = reconcile or MagicMock(return_value={})
    with patch.object(main.settings, "PLAYLIST_RECONCILE_WRITES_ENABLED", writes), \
         patch.object(main, "JobBudget"), \
         patch.object(main.eligibility, "channel_ids_for", return_value=["a", "b"]), \
         patch.object(main, "_reconcile_channel_order", side_effect=lambda ids: ids), \
         patch.object(main, "sync_playlists", sync), \
         patch.object(main, "reconcile_channel", reconcile), \
         patch("app.playlists.yt_playlist_items_insert") as yt_insert, \
         patch("app.playlists.yt_playlist_items_delete") as yt_delete:
        main._daily_reconcile()
    return sync, reconcile, yt_insert, yt_delete


def test_reconcile_with_writes_off_syncs_but_never_adds_or_removes(caplog):
    with caplog.at_level(logging.INFO, logger="midas.main"):
        sync, reconcile, yt_insert, yt_delete = _run_daily_reconcile(writes=False)

    assert [c.args[0] for c in sync.call_args_list] == ["a", "b"]
    reconcile.assert_not_called()
    yt_insert.assert_not_called()
    yt_delete.assert_not_called()
    assert any("PLAYLIST_RECONCILE_WRITES_ENABLED" in r.getMessage()
               and "skipped" in r.getMessage() for r in caplog.records)


def test_reconcile_with_writes_on_still_reconciles():
    sync, reconcile, _, _ = _run_daily_reconcile(writes=True)

    assert [c.args[0] for c in sync.call_args_list] == ["a", "b"]
    assert [c.args[0] for c in reconcile.call_args_list] == ["a", "b"]


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
