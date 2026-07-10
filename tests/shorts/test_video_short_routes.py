from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _sb_video(found=True, channel="UC123", privacy="public"):
    sb = MagicMock()
    tbl = sb.table.return_value
    tbl.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
        {"id": "vid123", "channel_id": channel, "privacy_status": privacy} if found else None)
    tbl.insert.return_value.execute.return_value.data = [{"id": 42}]
    return sb


def test_make_short_creates_job():
    with patch("app.shorts.routes.supabase", return_value=_sb_video()), \
         patch("app.shorts.routes.has_active_job", return_value=False), \
         patch("app.shorts.routes.start_job_thread") as start:
        r = _client().post("/videos/vid123/short")
    assert r.status_code == 200 and r.json() == {"job_id": 42}
    start.assert_called_once_with(42)


def test_make_short_unknown_video_404():
    with patch("app.shorts.routes.supabase", return_value=_sb_video(found=False)):
        r = _client().post("/videos/nope/short")
    assert r.status_code == 404


def test_make_short_conflicts_when_busy():
    with patch("app.shorts.routes.supabase", return_value=_sb_video()), \
         patch("app.shorts.routes.has_active_job", return_value=True):
        r = _client().post("/videos/vid123/short")
    assert r.status_code == 409


def test_make_short_blocks_unlisted():
    with patch("app.shorts.routes.supabase", return_value=_sb_video(privacy="unlisted")), \
         patch("app.shorts.routes.has_active_job", return_value=False), \
         patch("app.shorts.routes.start_job_thread") as start:
        r = _client().post("/videos/vid123/short")
    assert r.status_code == 409
    start.assert_not_called()


def test_make_short_blocks_private():
    with patch("app.shorts.routes.supabase", return_value=_sb_video(privacy="private")), \
         patch("app.shorts.routes.has_active_job", return_value=False), \
         patch("app.shorts.routes.start_job_thread") as start:
        r = _client().post("/videos/vid123/short")
    assert r.status_code == 409
    start.assert_not_called()


def test_make_short_blocks_unknown_privacy():
    # privacy_status not yet synced (NULL) -> refuse; only confirmed-public videos are cut.
    with patch("app.shorts.routes.supabase", return_value=_sb_video(privacy=None)), \
         patch("app.shorts.routes.has_active_job", return_value=False), \
         patch("app.shorts.routes.start_job_thread") as start:
        r = _client().post("/videos/vid123/short")
    assert r.status_code == 409
    start.assert_not_called()


def _sb_clip(status="PENDING"):
    sb = MagicMock()
    tbl = sb.table.return_value
    tbl.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
        {"id": 7, "job_id": 5, "local_path": "/tmp/c.mp4", "title": "t",
         "upload_status": status} if status else None)
    # the job lookup for channel_id
    return sb


def test_upload_clip_uploads_pending():
    sb = MagicMock()
    def table(name):
        t = MagicMock()
        if name == "shorts_clips":
            t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "id": 7, "job_id": 5, "local_path": "/tmp/c.mp4", "title": "t", "upload_status": "PENDING"}
        if name == "shorts_jobs":
            t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "id": 5, "channel_id": "UC123"}
        t.update.return_value.eq.return_value.execute.return_value.data = [{}]
        return t
    sb.table.side_effect = table
    with patch("app.shorts.routes.supabase", return_value=sb), \
         patch("app.shorts.routes.upload_short", return_value="yt_xyz") as up:
        r = _client().post("/shorts/clips/7/upload")
    assert r.status_code == 200 and r.json()["yt_video_id"] == "yt_xyz"
    up.assert_called_once()
