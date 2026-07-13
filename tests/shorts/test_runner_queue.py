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
