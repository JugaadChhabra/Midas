"""The startup catch-up of missed daily jobs (app/catch_up.py), and the job
registry kept across restarts that it reads (app/job_status.py)."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from apscheduler.events import EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.background import BackgroundScheduler

from app import catch_up
from app.job_status import JobRunFailed, JobStatusRegistry

UTC = timezone.utc
# A Monday: the office machine came up 08:02 UTC on 2026-11-03, after the
# 04:00-07:00 jobs, as it had most days since 10-29.
MONDAY_0802 = datetime(2026, 11, 2, 8, 2, tzinfo=UTC)

# The real CATCH_UP jobs' triggers (app/main.py _register_jobs), BACKUP_HOUR 0.
TRIGGERS = {
    "video_sync": dict(hour=4, minute=0),
    "metrics_poll": dict(hour=5, minute=0),
    "reporting_poll": dict(hour=6, minute=0),
    "traffic_poll": dict(hour=6, minute=30),
    "playlist_health_score": dict(hour=7, minute=0),
    "measurement_eval": dict(hour=8, minute=0),
    "lever_measurement": dict(day_of_week="mon", hour=9, minute=0),
    "channel_health": dict(hour=10, minute=0),
    "nightly_db_backup": dict(hour=0, minute=0),
}


def _scheduler(calls, *, fail=()):
    sched = BackgroundScheduler(daemon=True, timezone=UTC)
    for job_id, fields in TRIGGERS.items():
        def fn(job_id=job_id):
            calls.append(job_id)
            if job_id in fail:
                raise JobRunFailed(job_id, {"c1": "RuntimeError: boom"})
        sched.add_job(fn, "cron", timezone=UTC, id=job_id, **fields)
    return sched


def _ran(registry, job_id, at):
    registry.on_event(JobExecutionEvent(EVENT_JOB_EXECUTED, job_id, "default", at))


def _run(sched, registry, clock):
    sched.start(paused=True)                     # next fire times computed, nothing fires
    try:
        return catch_up.run(sched, registry, clock=clock)
    finally:
        sched.shutdown(wait=False)


# --- due --------------------------------------------------------------------


def test_due_is_the_latest_fire_time_in_the_last_24_hours():
    sched = _scheduler([])
    traffic = sched.get_job("traffic_poll")
    assert catch_up.due(traffic, MONDAY_0802) == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
    # Before today's fire, yesterday's still counts.
    early = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
    assert catch_up.due(traffic, early) == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)


def test_a_weekly_job_is_due_only_within_a_day_of_its_fire():
    weekly = _scheduler([]).get_job("lever_measurement")
    assert catch_up.due(weekly, MONDAY_0802) is None            # 09:00 today not yet
    tuesday = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
    assert catch_up.due(weekly, tuesday) == datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    assert catch_up.due(weekly, tuesday + timedelta(hours=2)) is None


# --- run --------------------------------------------------------------------


def test_a_late_start_runs_every_missed_job_in_order_and_records_each():
    calls, reg = [], JobStatusRegistry()
    ran = _run(_scheduler(calls), reg, lambda: MONDAY_0802)

    # Nothing recorded: channel_health's 10:00 yesterday counts too.
    expected = ["video_sync", "metrics_poll", "reporting_poll", "traffic_poll",
                "playlist_health_score", "measurement_eval", "channel_health",
                "nightly_db_backup"]
    assert calls == ran == expected
    for job_id in expected:
        assert reg.snapshot()[job_id]["status"] == "success"
        assert reg.last_run_at(job_id) == MONDAY_0802


def test_runs_recorded_before_a_restart_are_not_run_again():
    calls, reg = [], JobStatusRegistry()
    _ran(reg, "nightly_db_backup", datetime(2026, 11, 2, 0, 0, tzinfo=UTC))
    _ran(reg, "video_sync", datetime(2026, 11, 2, 4, 0, tzinfo=UTC))
    _ran(reg, "metrics_poll", datetime(2026, 11, 1, 5, 0, tzinfo=UTC))   # yesterday's
    _ran(reg, "channel_health", datetime(2026, 11, 1, 10, 0, tzinfo=UTC))

    ran = _run(_scheduler(calls), reg, lambda: MONDAY_0802)
    assert ran == ["metrics_poll", "reporting_poll", "traffic_poll", "playlist_health_score",
                   "measurement_eval"]


def test_a_failing_job_is_recorded_and_the_rest_still_run():
    calls, reg = [], JobStatusRegistry()
    ran = _run(_scheduler(calls, fail={"reporting_poll"}), reg, lambda: MONDAY_0802)

    assert "traffic_poll" in ran and "nightly_db_backup" in ran
    entry = reg.snapshot()["reporting_poll"]
    assert entry["status"] == "failed"
    assert entry["failed_channels"] == {"c1": "RuntimeError: boom"}


def test_a_job_that_falls_due_during_the_catch_up_runs_after_it_once():
    """Monday, up at 08:50: lever_measurement (09:00) falls due while the
    polls run, so it runs after them rather than on stale traffic, and each
    job runs once."""
    calls, reg = [], JobStatusRegistry()
    times = iter([datetime(2026, 11, 2, 8, 50, tzinfo=UTC)] * 7
                 + [datetime(2026, 11, 2, 9, 5, tzinfo=UTC)] * 10)
    ran = _run(_scheduler(calls), reg, lambda: next(times))

    assert ran[-1] == "lever_measurement"
    assert ran.index("traffic_poll") < ran.index("lever_measurement")
    assert len(ran) == len(set(ran))


def test_the_jobs_are_resumed_after_the_catch_up():
    calls, reg = [], JobStatusRegistry()
    sched = _scheduler(calls)
    sched.start(paused=True)
    try:
        catch_up.run(sched, reg, clock=lambda: MONDAY_0802)
        assert all(sched.get_job(j).next_run_time is not None for j in catch_up.CATCH_UP)
    finally:
        sched.shutdown(wait=False)


def test_a_job_not_registered_is_skipped():
    calls, reg = [], JobStatusRegistry()
    sched = _scheduler(calls)
    sched.remove_job("nightly_db_backup")
    assert "nightly_db_backup" not in _run(sched, reg, lambda: MONDAY_0802)


def test_every_catch_up_job_is_registered_by_main():
    from app import main

    sched = BackgroundScheduler(daemon=True)
    with patch.multiple(main.settings, PLAYLIST_DISCOVERY_ENABLED=False,
                        PLAYLIST_RECONCILE_WRITES_ENABLED=False,
                        PLAYLIST_TUNING_ENABLED=False, REFLECTION_ENABLED=False):
        main._register_jobs(sched)
    assert all(sched.get_job(j) is not None for j in catch_up.CATCH_UP)


# --- the registry kept across restarts ---------------------------------------


def test_the_registry_survives_a_restart(tmp_path):
    path = tmp_path / "job_status.json"
    before = JobStatusRegistry()
    before.persist_to(path)
    _ran(before, "traffic_poll", MONDAY_0802)

    after = JobStatusRegistry()
    after.persist_to(path)
    assert after.last_run_at("traffic_poll") == MONDAY_0802
    assert after.snapshot()["traffic_poll"]["status"] == "success"


def test_an_unreadable_file_starts_empty(tmp_path):
    path = tmp_path / "job_status.json"
    path.write_text("{not json", encoding="utf-8")
    reg = JobStatusRegistry()
    reg.persist_to(path)
    assert reg.snapshot() == {}
    _ran(reg, "video_sync", MONDAY_0802)                     # and the next run rewrites it
    assert json.loads(path.read_text(encoding="utf-8"))["video_sync"]["status"] == "success"


def test_watch_drops_saved_jobs_that_are_no_longer_registered(tmp_path):
    path = tmp_path / "job_status.json"
    path.write_text(json.dumps({"reflection": {"status": "success",
                                               "last_run_at": MONDAY_0802.isoformat()}}),
                    encoding="utf-8")
    reg = JobStatusRegistry()
    reg.persist_to(path)
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(lambda: None, "cron", hour=3, id="video_sync")
    reg.watch(sched)
    assert set(reg.snapshot()) == {"video_sync"}


def test_a_failed_write_never_fails_the_run(tmp_path):
    reg = JobStatusRegistry()
    reg.persist_to(tmp_path / "missing_dir" / "job_status.json")
    _ran(reg, "video_sync", MONDAY_0802)
    assert reg.snapshot()["video_sync"]["status"] == "success"


def test_a_frequent_job_rewrites_the_file_at_most_once_a_minute(tmp_path):
    path = tmp_path / "job_status.json"
    reg = JobStatusRegistry()
    reg.persist_to(path)
    _ran(reg, "shorts_dispatch", MONDAY_0802)
    _ran(reg, "shorts_dispatch", MONDAY_0802 + timedelta(seconds=5))
    saved = json.loads(path.read_text(encoding="utf-8"))["shorts_dispatch"]
    assert saved["last_run_at"] == MONDAY_0802.isoformat()     # the second run not written
    assert reg.last_run_at("shorts_dispatch") == MONDAY_0802 + timedelta(seconds=5)
    # A cron job right after is still saved.
    _ran(reg, "video_sync", MONDAY_0802)
    assert "video_sync" in json.loads(path.read_text(encoding="utf-8"))
