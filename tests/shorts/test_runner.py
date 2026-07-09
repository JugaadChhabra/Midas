from unittest.mock import MagicMock, patch


def _fake_sb(job_row, recorder):
    """supabase() stand-in: single() returns job_row; update/insert are recorded."""
    sb = MagicMock()

    def table(name):
        t = MagicMock()
        t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = job_row
        t.select.return_value.in_.return_value.limit.return_value.execute.return_value.data = []

        def _update(fields):
            recorder.append((name, "update", fields))
            u = MagicMock()
            u.eq.return_value.execute.return_value.data = [{}]
            return u

        def _insert(fields):
            recorder.append((name, "insert", fields))
            i = MagicMock()
            i.execute.return_value.data = [{"id": 77, **fields}]
            return i

        t.update.side_effect = _update
        t.insert.side_effect = _insert
        return t

    sb.table.side_effect = table
    return sb


JOB = {"id": 5, "channel_id": "UC123", "source_url": "https://youtu.be/dQw4w9WgXcQ",
       "cut_mode": "highlights", "status": "CREATED"}


def test_run_shorts_job_happy_path(tmp_path):
    recorder = []
    clips = [{"path": str(tmp_path / "c1.mp4"), "rank": 1, "start_s": 0.0, "end_s": 10.0}]
    (tmp_path / "c1.mp4").write_bytes(b"clip")

    with patch("app.shorts.runner.supabase", return_value=_fake_sb(JOB, recorder)), \
         patch("app.shorts.runner._fetch_video", return_value=(tmp_path / "src.mkv", "My_Video")), \
         patch("app.shorts.runner._cut_video", return_value={"clips": clips, "message": "ok", "language": "en", "cut_mode": "highlights"}), \
         patch("app.shorts.runner.upload_short", return_value="yt_abc123") as up, \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as settings:
        settings.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        from app.shorts.runner import run_shorts_job
        run_shorts_job(5)

    up.assert_called_once()
    assert up.call_args.args[0] == "UC123"
    inserts = [(t, f) for t, op, f in recorder if op == "insert"]
    assert inserts and inserts[0][0] == "shorts_clips"
    assert inserts[0][1]["local_path"] == clips[0]["path"]
    job_updates = [f for t, op, f in recorder if t == "shorts_jobs" and op == "update"]
    assert any(u.get("status") == "DOWNLOADING" for u in job_updates)
    assert any(u.get("status") == "UPLOADING" for u in job_updates)
    assert job_updates[-1]["status"] == "DONE"


def test_run_shorts_job_marks_failed_on_error(tmp_path):
    recorder = []
    with patch("app.shorts.runner.supabase", return_value=_fake_sb(JOB, recorder)), \
         patch("app.shorts.runner._fetch_video", side_effect=RuntimeError("boom")), \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as settings:
        settings.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        from app.shorts.runner import run_shorts_job
        run_shorts_job(5)

    job_updates = [f for t, op, f in recorder if t == "shorts_jobs" and op == "update"]
    assert job_updates[-1]["status"] == "FAILED"
    assert "boom" in job_updates[-1]["error_message"]


def test_reap_stuck_jobs():
    sb = MagicMock()
    stuck = [{"id": 1}, {"id": 2}]
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = stuck
    with patch("app.shorts.runner.supabase", return_value=sb):
        from app.shorts.runner import reap_stuck_jobs
        assert reap_stuck_jobs() == 2
