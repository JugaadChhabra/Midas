import os
from unittest.mock import MagicMock, patch


def test_worker_main_marks_pid_and_runs_job():
    from app.shorts import worker
    sb = MagicMock()
    with patch("app.shorts.worker.supabase", return_value=sb), \
         patch("app.shorts.worker.run_shorts_job") as run:
        rc = worker.main(["5"])
    assert rc == 0
    run.assert_called_once_with(5)
    # worker recorded its own PID on the job row
    upd = sb.table.return_value.update
    fields = upd.call_args[0][0]
    assert fields["worker_pid"] == os.getpid()
    assert "started_at" in fields
    upd.return_value.eq.assert_called_once_with("id", 5)


def test_worker_main_usage_error_without_arg():
    from app.shorts import worker
    assert worker.main([]) == 2
