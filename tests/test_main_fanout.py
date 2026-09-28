import logging
import threading
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.testclient import TestClient

from app.job_status import JobRunFailed, JobStatusRegistry

RUN_AT = datetime(2026, 9, 28, 7, 0, tzinfo=timezone.utc)


def test_run_per_channel_calls_every_channel():
    from app import main

    seen = []
    with patch.object(main.eligibility, "channel_ids_for", return_value=["a", "b", "c"]):
        main._run_per_channel(lambda cid: seen.append(cid), "Test job")

    assert seen == ["a", "b", "c"]


def test_run_per_channel_isolates_failures():
    from app import main

    seen = []

    def fn(cid):
        seen.append(cid)
        if cid == "b":
            raise RuntimeError("boom on b")

    with patch.object(main.eligibility, "channel_ids_for", return_value=["a", "b", "c"]):
        # One channel failing must not stop the others — but the run as a
        # whole must end failed, so APScheduler stops calling it a success.
        with pytest.raises(JobRunFailed) as exc_info:
            main._run_per_channel(fn, "Test job")

    assert seen == ["a", "b", "c"]
    assert exc_info.value.failed_channels == {"b": "RuntimeError: boom on b"}
    assert "b" in str(exc_info.value)
    assert "Test job" in str(exc_info.value)


def test_run_per_channel_logs_each_failure_with_label_channel_and_traceback(caplog):
    from app import main

    def fn(cid):
        raise ValueError(f"bad {cid}")

    with caplog.at_level(logging.ERROR, logger="midas.main"):
        with pytest.raises(JobRunFailed) as exc_info:
            main._run_per_channel(fn, "Test job", channel_ids=["x", "y"])

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2
    for record, cid in zip(errors, ["x", "y"]):
        assert "Test job" in record.getMessage()
        assert cid in record.getMessage()
        assert record.exc_info is not None
    assert set(exc_info.value.failed_channels) == {"x", "y"}


def test_run_per_channel_uses_explicit_channel_ids():
    from app import main

    seen = []
    # When channel_ids is supplied, eligibility must not be consulted at all.
    with patch.object(main.eligibility, "channel_ids_for",
                      side_effect=AssertionError("should not be called")):
        main._run_per_channel(lambda cid: seen.append(cid), "Test job", channel_ids=["x", "y"])

    assert seen == ["x", "y"]



def test_daily_reconcile_fails_the_channel_when_a_step_raises():
    """Sync failing still lets reconcile run for that channel, and every other
    channel still runs — but the cycle ends failed, naming the channel."""
    from app import main

    reconciled = []

    def sync(cid, budget):
        if cid == "a":
            raise RuntimeError("playlists.list 500")
        return {}

    with patch.object(main, "JobBudget"), \
         patch.object(main.eligibility, "channel_ids_for", return_value=["a", "b"]), \
         patch.object(main, "_reconcile_channel_order", side_effect=lambda ids: ids), \
         patch.object(main, "sync_playlists", side_effect=sync), \
         patch.object(main, "reconcile_channel", side_effect=reconciled.append):
        with pytest.raises(JobRunFailed) as exc_info:
            main._daily_reconcile()

    assert reconciled == ["a", "b"]
    assert list(exc_info.value.failed_channels) == ["a"]
    assert "sync: RuntimeError: playlists.list 500" in exc_info.value.failed_channels["a"]

# --- job-status registry + /health/jobs -------------------------------------


def _event(code, job_id, exception=None):
    return JobExecutionEvent(code, job_id, "default", RUN_AT, exception=exception)


def test_registry_lists_registered_jobs_as_never_run():
    reg = JobStatusRegistry()
    reg.register("playlist_health_score")

    assert reg.snapshot() == {
        "playlist_health_score": {
            "status": "never_run",
            "last_run_at": None,
            "error": None,
            "failed_channels": {},
        }
    }


def test_one_channel_failing_ends_the_job_failed_and_names_the_channel():
    """Acceptance: two channels, one raises — the other still runs, the job
    ends failed, and the registry lists the failing channel."""
    from app import main

    seen = []

    def fn(cid):
        seen.append(cid)
        if cid == "bad":
            raise NameError("name 'METRIC_ROW_PAGE' is not defined")

    with pytest.raises(JobRunFailed) as exc_info:
        main._run_per_channel(fn, "Daily playlist_health_score", channel_ids=["bad", "good"])
    assert seen == ["bad", "good"]

    reg = JobStatusRegistry()
    reg.register("playlist_health_score")
    reg.on_event(_event(EVENT_JOB_ERROR, "playlist_health_score", exc_info.value))

    entry = reg.snapshot()["playlist_health_score"]
    assert entry["status"] == "failed"
    assert entry["last_run_at"] == RUN_AT.isoformat()
    assert entry["failed_channels"] == {
        "bad": "NameError: name 'METRIC_ROW_PAGE' is not defined",
    }
    assert "bad" in entry["error"]


def test_all_channels_succeeding_ends_the_job_successful():
    from app import main

    assert main._run_per_channel(lambda cid: None, "Test job", channel_ids=["a", "b"]) is None

    reg = JobStatusRegistry()
    reg.register("reflection")
    reg.on_event(_event(EVENT_JOB_ERROR, "reflection", RuntimeError("earlier")))
    reg.on_event(_event(EVENT_JOB_EXECUTED, "reflection"))

    # A success after a failure clears the failure detail.
    assert reg.snapshot()["reflection"] == {
        "status": "success",
        "last_run_at": RUN_AT.isoformat(),
        "error": None,
        "failed_channels": {},
    }


def test_non_fanout_job_failure_records_error_without_channels():
    reg = JobStatusRegistry()
    reg.on_event(_event(EVENT_JOB_ERROR, "nightly_db_backup", OSError("NAS unreachable")))

    entry = reg.snapshot()["nightly_db_backup"]
    assert entry["status"] == "failed"
    assert entry["error"] == "OSError: NAS unreachable"
    assert entry["failed_channels"] == {}


def test_failed_job_is_logged_distinctly(caplog):
    reg = JobStatusRegistry()
    with caplog.at_level(logging.ERROR, logger="midas.job_status"):
        reg.on_event(_event(EVENT_JOB_ERROR, "reflection",
                            JobRunFailed("Weekly reflection", {"c1": "boom"})))

    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "JOB FAILED" in record.getMessage()
    assert "reflection" in record.getMessage()
    assert "c1" in record.getMessage()


def test_watch_registers_every_scheduled_job_and_records_real_runs():
    """Wiring through a real (unstarted, then started) scheduler: every added
    job appears before it fires, and APScheduler's own events reach the
    registry once it does."""
    reg = JobStatusRegistry()
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(lambda: None, "cron", hour=3, id="idle_job")

    def _fails():
        raise JobRunFailed("Test job", {"c9": "RuntimeError: nope"})

    sched.add_job(_fails, "date", run_date=datetime.now(timezone.utc), id="failing_job")
    reg.watch(sched)
    assert reg.snapshot()["idle_job"]["status"] == "never_run"
    assert reg.snapshot()["failing_job"]["status"] == "never_run"

    done = threading.Event()
    sched.add_listener(lambda _e: done.set(), EVENT_JOB_ERROR)
    sched.start()
    try:
        assert done.wait(5), "scheduler never ran failing_job"
    finally:
        sched.shutdown(wait=True)

    entry = reg.snapshot()["failing_job"]
    assert entry["status"] == "failed"
    assert entry["failed_channels"] == {"c9": "RuntimeError: nope"}
    assert reg.snapshot()["idle_job"]["status"] == "never_run"


def test_health_jobs_endpoint_returns_the_registry():
    from app import job_status, main

    reg = JobStatusRegistry()
    reg.register("autopilot")
    reg.register("playlist_health_score")
    reg.on_event(_event(EVENT_JOB_ERROR, "playlist_health_score",
                        JobRunFailed("Daily playlist_health_score", {"c1": "NameError: x"})))

    with patch.object(job_status, "registry", reg):
        r = TestClient(main.app).get("/health/jobs")

    assert r.status_code == 200
    body = r.json()
    assert body["jobs"]["autopilot"]["status"] == "never_run"
    assert body["jobs"]["playlist_health_score"]["status"] == "failed"
    assert body["jobs"]["playlist_health_score"]["failed_channels"] == {"c1": "NameError: x"}


def test_health_endpoint_unchanged():
    from app import main

    r = TestClient(main.app).get("/health")
    assert r.json() == {"ok": True, "dry_run": main.settings.DRY_RUN}
