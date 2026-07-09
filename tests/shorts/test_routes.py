from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _sb_with_channel(found=True):
    sb = MagicMock()
    tbl = sb.table.return_value
    tbl.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
        {"id": "UC123"} if found else None)
    tbl.insert.return_value.execute.return_value.data = [{"id": 42}]
    return sb


BODY = {"channel_id": "UC123", "source_url": "https://youtu.be/dQw4w9WgXcQ"}


def test_create_job_starts_thread():
    with patch("app.shorts.routes.supabase", return_value=_sb_with_channel()), \
         patch("app.shorts.routes.has_active_job", return_value=False), \
         patch("app.shorts.routes.start_job_thread") as start:
        r = _client().post("/shorts/jobs", json={**BODY, "cut_mode": "coverage"})
    assert r.status_code == 200 and r.json() == {"job_id": 42}
    start.assert_called_once_with(42)


def test_create_job_rejects_non_youtube_url():
    with patch("app.shorts.routes.supabase", return_value=_sb_with_channel()):
        r = _client().post("/shorts/jobs", json={**BODY, "source_url": "https://vimeo.com/1"})
    assert r.status_code == 400


def test_create_job_conflicts_when_job_running():
    with patch("app.shorts.routes.supabase", return_value=_sb_with_channel()), \
         patch("app.shorts.routes.has_active_job", return_value=True):
        r = _client().post("/shorts/jobs", json=BODY)
    assert r.status_code == 409


def test_create_job_unknown_channel_404():
    with patch("app.shorts.routes.supabase", return_value=_sb_with_channel(found=False)):
        r = _client().post("/shorts/jobs", json=BODY)
    assert r.status_code == 404
