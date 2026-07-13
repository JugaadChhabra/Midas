def test_shorts_concurrency_settings_defaults():
    from app.config import settings
    assert settings.SHORTS_MAX_CONCURRENT_JOBS == 2
    assert settings.SHORTS_DISPATCH_INTERVAL_SECONDS == 5


from unittest.mock import MagicMock, patch


def test_in_progress_statuses_excludes_created():
    from app.shorts.runner import IN_PROGRESS_STATUSES, WORKING_STATUSES
    assert "CREATED" not in IN_PROGRESS_STATUSES
    assert set(IN_PROGRESS_STATUSES) == set(WORKING_STATUSES) - {"CREATED"}


def test_active_job_count_counts_working_rows():
    from app.shorts import runner
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {"id": 1}, {"id": 2}, {"id": 3}]
    with patch("app.shorts.runner.supabase", return_value=sb):
        assert runner.active_job_count() == 3
    # counted by the full in-flight status set (includes CREATED)
    sb.table.return_value.select.return_value.in_.assert_called_once_with(
        "status", list(runner.WORKING_STATUSES))


def test_reap_kills_orphans_and_fails_them():
    from app.shorts import runner
    sb = MagicMock()
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {"id": 10, "worker_pid": 4242}, {"id": 11, "worker_pid": None}]
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]
    with patch("app.shorts.runner.supabase", return_value=sb), \
         patch("app.shorts.runner._kill_pid_if_alive") as kill:
        n = runner.reap_stuck_jobs()
    assert n == 2
    # only in-progress statuses are scanned, never CREATED
    sb.table.return_value.select.return_value.in_.assert_called_once_with(
        "status", list(runner.IN_PROGRESS_STATUSES))
    kill.assert_any_call(4242)
    kill.assert_any_call(None)


def test_kill_pid_if_alive_noop_on_falsy():
    from app.shorts import runner
    # Must not raise for None/0.
    runner._kill_pid_if_alive(None)
    runner._kill_pid_if_alive(0)
