# tests/shorts/test_runner_nas.py
from pathlib import Path
from unittest.mock import MagicMock, patch


def _fake_sb(job_row, recorder):
    sb = MagicMock()

    def table(name):
        t = MagicMock()
        t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = job_row
        def _update(fields):
            recorder.append((name, "update", fields))
            u = MagicMock()
            u.eq.return_value.execute.return_value.data = [{}]
            return u
        def _insert(fields):
            recorder.append((name, "insert", fields))
            i = MagicMock()
            i.execute.return_value.data = [{"id": 1, **fields}]
            return i
        t.update.side_effect = _update
        t.insert.side_effect = _insert
        return t

    sb.table.side_effect = table
    return sb


NAS_JOB = {"id": 9, "channel_id": None, "language": "HINDI",
           "source_nas_path": "HINDI/song.mp4", "cut_mode": "highlights",
           "camera_motion": "calm", "status": "CREATED"}


def test_nas_job_cuts_pushes_clips_and_moves_source(tmp_path):
    recorder = []
    clips = [{"path": str(tmp_path / "c1.mp4"), "rank": 1, "start_s": 0.0, "end_s": 10.0, "verdict": "PASS"}]
    (tmp_path / "c1.mp4").write_bytes(b"clip")
    nas = MagicMock()
    nas.copy_to_local.return_value = tmp_path / "src" / "song.mp4"

    with patch("app.shorts.runner.supabase", return_value=_fake_sb(NAS_JOB, recorder)), \
         patch("app.shorts.runner.nas_service", nas), \
         patch("app.shorts.runner._cut_video",
               return_value={"clips": clips, "message": "ok", "language": "hi", "cut_mode": "highlights"}), \
         patch("app.shorts.runner.upload_short") as up, \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as st:
        st.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        st.NAS_SOURCE_ROOT_PATH = "RHYMES"
        st.NAS_DESTINATION_ROOT_PATH = "COMPLETED"
        from app.shorts.runner import run_shorts_job
        run_shorts_job(9)

    up.assert_not_called()                                     # no YouTube upload
    nas.copy_from_local.assert_called_once()                   # clip pushed to NAS
    _, kwargs_or_args = nas.copy_from_local.call_args
    nas.move.assert_called_once_with("RHYMES/HINDI/song.mp4", "COMPLETED/HINDI/song.mp4")
    clip_inserts = [f for (tbl, op, f) in recorder if tbl == "shorts_clips" and op == "insert"]
    assert clip_inserts and clip_inserts[0]["nas_path"] == "COMPLETED/HINDI/c1.mp4"
    assert clip_inserts[0]["upload_status"] == "SAVED"
    assert any(op == "update" and f.get("status") == "DONE" for (_, op, f) in recorder)


def test_nas_job_leaves_source_on_cut_failure(tmp_path):
    recorder = []
    nas = MagicMock()
    nas.copy_to_local.return_value = tmp_path / "src" / "song.mp4"
    with patch("app.shorts.runner.supabase", return_value=_fake_sb(NAS_JOB, recorder)), \
         patch("app.shorts.runner.nas_service", nas), \
         patch("app.shorts.runner._cut_video", side_effect=RuntimeError("boom")), \
         patch("app.shorts.runner._notify_macos"), \
         patch("app.shorts.runner.settings") as st:
        st.SHORTS_CACHE_DIR = str(tmp_path / "cache")
        st.NAS_SOURCE_ROOT_PATH = "RHYMES"
        st.NAS_DESTINATION_ROOT_PATH = "COMPLETED"
        from app.shorts.runner import run_shorts_job
        run_shorts_job(9)
    nas.move.assert_not_called()                               # source stays for retry
    assert any(op == "update" and f.get("status") == "FAILED" for (_, op, f) in recorder)
