from pathlib import Path
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


def test_run_shorts_job_upload_cap_uploads_top_n(tmp_path):
    recorder = []
    job = {"id": 5, "channel_id": "UC123", "source_url": "https://youtu.be/dQw4w9WgXcQ",
           "cut_mode": "highlights", "camera_motion": "calm", "upload_cap": 2, "status": "CREATED"}
    clips = [
        {"path": str(tmp_path / "c1.mp4"), "rank": 1, "start_s": 0.0, "end_s": 10.0, "verdict": "CHECK"},
        {"path": str(tmp_path / "c2.mp4"), "rank": 2, "start_s": 10.0, "end_s": 20.0, "verdict": "PASS"},
        {"path": str(tmp_path / "c3.mp4"), "rank": 3, "start_s": 20.0, "end_s": 30.0, "verdict": "PASS"},
        {"path": str(tmp_path / "c4.mp4"), "rank": 4, "start_s": 30.0, "end_s": 40.0, "verdict": "CHECK"},
    ]
    for c in clips:
        Path(c["path"]).write_bytes(b"clip")
    with patch("app.shorts.runner.supabase", return_value=_fake_sb(job, recorder)), \
         patch("app.shorts.runner._fetch_video", return_value=(tmp_path / "src.mkv", "My_Video")), \
         patch("app.shorts.runner._cut_video", return_value={"clips": clips, "message": "ok", "language": "en", "cut_mode": "highlights"}), \
         patch("app.shorts.runner.upload_short", return_value="yt_abc") as up, \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as settings:
        settings.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        from app.shorts.runner import run_shorts_job
        run_shorts_job(5)

    # Only 2 clips uploaded (the two PASS clips, ranks 2 and 3), 4 clip rows inserted total.
    assert up.call_count == 2
    inserted = [f for t, op, f in recorder if t == "shorts_clips" and op == "insert"]
    assert len(inserted) == 4
    pending = [f for f in inserted if f["upload_status"] == "PENDING"]
    uploading = [f for f in inserted if f["upload_status"] == "UPLOADING"]
    assert len(pending) == 2 and len(uploading) == 2
    # The uploaded clips are the PASS ones (ranks 2 and 3).
    assert {f["rank"] for f in uploading} == {2, 3}


def test_run_shorts_job_no_cap_uploads_all(tmp_path):
    recorder = []
    job = {"id": 6, "channel_id": "UC123", "source_url": "https://youtu.be/dQw4w9WgXcQ",
           "cut_mode": "highlights", "camera_motion": "calm", "upload_cap": None, "status": "CREATED"}
    clips = [
        {"path": str(tmp_path / "d1.mp4"), "rank": 1, "start_s": 0.0, "end_s": 10.0, "verdict": "CHECK"},
        {"path": str(tmp_path / "d2.mp4"), "rank": 2, "start_s": 10.0, "end_s": 20.0, "verdict": "PASS"},
    ]
    for c in clips:
        Path(c["path"]).write_bytes(b"clip")
    with patch("app.shorts.runner.supabase", return_value=_fake_sb(job, recorder)), \
         patch("app.shorts.runner._fetch_video", return_value=(tmp_path / "src.mkv", "My_Video")), \
         patch("app.shorts.runner._cut_video", return_value={"clips": clips, "message": "ok", "language": "en", "cut_mode": "highlights"}), \
         patch("app.shorts.runner.upload_short", return_value="yt_abc") as up, \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as settings:
        settings.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        from app.shorts.runner import run_shorts_job
        run_shorts_job(6)

    assert up.call_count == 2  # all clips uploaded


def test_reap_stuck_jobs():
    sb = MagicMock()
    stuck = [{"id": 1}, {"id": 2}]
    sb.table.return_value.select.return_value.in_.return_value.execute.return_value.data = stuck
    with patch("app.shorts.runner.supabase", return_value=sb):
        from app.shorts.runner import reap_stuck_jobs
        assert reap_stuck_jobs() == 2
