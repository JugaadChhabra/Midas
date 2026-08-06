"""AutoShorts demo surface: the URL entry point and the clip-file endpoint.

The behaviour worth locking down is that a demo job never publishes (upload_cap
0) and that the file endpoint refuses paths outside SHORTS_CACHE_DIR.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _sb_with_channel(found=True):
    sb = MagicMock()
    tbl = sb.table.return_value
    tbl.select.return_value.limit.return_value.execute.return_value.data = (
        [{"id": "UC123"}] if found else [])
    tbl.insert.return_value.execute.return_value.data = [{"id": 7}]
    return sb


def _flag(value):
    return patch("app.shorts.autoshorts.settings.SHORTS_YT_DOWNLOAD_ENABLED", value)


URL = "https://youtu.be/dQw4w9WgXcQ"


def test_creates_job_that_publishes_nothing():
    sb = _sb_with_channel()
    with _flag(True), patch("app.shorts.autoshorts.supabase", return_value=sb), \
         patch("app.shorts.autoshorts._spawn"):
        r = _client().post("/autoshorts/jobs", json={"url": URL})
    assert r.status_code == 200 and r.json() == {"job_id": 7}
    row = sb.table.return_value.insert.call_args[0][0]
    # upload_cap 0 is what makes the runner hold every clip instead of uploading.
    assert row["upload_cap"] == 0
    assert row["source_url"] == URL
    assert row["autopilot_generated"] is False


def test_rejects_non_youtube_url():
    with _flag(True), patch("app.shorts.autoshorts.supabase", return_value=_sb_with_channel()):
        r = _client().post("/autoshorts/jobs", json={"url": "https://vimeo.com/1"})
    assert r.status_code == 400


def test_503_when_flag_off():
    with _flag(False), patch("app.shorts.autoshorts.supabase", return_value=_sb_with_channel()):
        r = _client().post("/autoshorts/jobs", json={"url": URL})
    assert r.status_code == 503


def test_503_when_no_channel_connected():
    with _flag(True), patch("app.shorts.autoshorts.supabase",
                            return_value=_sb_with_channel(found=False)):
        r = _client().post("/autoshorts/jobs", json={"url": URL})
    assert r.status_code == 503


def _sb_with_clip(local_path):
    sb = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value
     .single.return_value.execute.return_value.data) = {"local_path": local_path,
                                                        "title": "clip"}
    return sb


def test_clip_file_serves_a_file_inside_the_cache(tmp_path):
    clip = tmp_path / "job1" / "clip_1.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"fake mp4 bytes")
    with patch("app.shorts.routes.settings.SHORTS_CACHE_DIR", str(tmp_path)), \
         patch("app.shorts.routes.supabase", return_value=_sb_with_clip(str(clip))):
        r = _client().get("/shorts/clips/1/file")
    assert r.status_code == 200 and r.content == b"fake mp4 bytes"
    # Served inline so the page's <video> can play it.
    assert "attachment" not in r.headers.get("content-disposition", "")


def test_clip_file_download_flag_sets_attachment(tmp_path):
    clip = tmp_path / "clip_1.mp4"
    clip.write_bytes(b"x")
    with patch("app.shorts.routes.settings.SHORTS_CACHE_DIR", str(tmp_path)), \
         patch("app.shorts.routes.supabase", return_value=_sb_with_clip(str(clip))):
        r = _client().get("/shorts/clips/1/file?download=1")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]


def test_clip_file_refuses_path_outside_the_cache(tmp_path):
    outside = tmp_path / "secret.env"
    outside.write_bytes(b"SUPABASE_KEY=hunter2")
    cache = tmp_path / "cache"
    cache.mkdir()
    with patch("app.shorts.routes.settings.SHORTS_CACHE_DIR", str(cache)), \
         patch("app.shorts.routes.supabase", return_value=_sb_with_clip(str(outside))):
        r = _client().get("/shorts/clips/1/file")
    assert r.status_code == 404


def test_clip_file_404_when_no_local_path():
    with patch("app.shorts.routes.supabase", return_value=_sb_with_clip(None)):
        r = _client().get("/shorts/clips/1/file")
    assert r.status_code == 404


def test_job_is_started_locally_not_left_on_the_shared_queue():
    """Never enqueue as CREATED: any dispatcher sharing this Supabase could claim
    it, and a NAS-only one can only fail it with 'download is retired'."""
    from app.shorts.status import CREATED, DOWNLOADING
    sb = _sb_with_channel()
    with _flag(True), patch("app.shorts.autoshorts.supabase", return_value=sb), \
         patch("app.shorts.autoshorts._spawn") as spawn:
        r = _client().post("/autoshorts/jobs", json={"url": URL})
    assert r.status_code == 200
    row = sb.table.return_value.insert.call_args[0][0]
    assert row["status"] == DOWNLOADING and row["status"] != CREATED
    spawn.assert_called_once_with(7)


def test_failed_spawn_marks_the_job_failed_not_stuck():
    from app.shorts.status import FAILED
    sb = _sb_with_channel()
    with _flag(True), patch("app.shorts.autoshorts.supabase", return_value=sb), \
         patch("app.shorts.autoshorts._spawn", side_effect=OSError("no fork")):
        r = _client().post("/autoshorts/jobs", json={"url": URL})
    assert r.status_code == 500
    # The row must not be left sitting in DOWNLOADING forever.
    assert sb.table.return_value.update.call_args[0][0]["status"] == FAILED
