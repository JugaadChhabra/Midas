import pytest
from unittest.mock import MagicMock, patch




@pytest.fixture(autouse=True)
def _signed_in(authed_client):
    """Every request here is a signed-in admin's (tests/conftest.py
    authed_client): the gate (app/session.py) refuses anything else."""
    global _client
    _client = lambda: authed_client(raise_server_exceptions=False)  # noqa: E731


def _sb_with_channel(found=True):
    sb = MagicMock()
    tbl = sb.table.return_value
    tbl.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
        {"id": "UC123"} if found else None)
    tbl.insert.return_value.execute.return_value.data = [{"id": 42}]
    return sb


BODY = {"channel_id": "UC123", "source_url": "https://youtu.be/dQw4w9WgXcQ"}


def _flag(value):
    # The YouTube-URL submit path is gated on SHORTS_YT_DOWNLOAD_ENABLED. Both
    # states are patched explicitly: the ambient .env decides the real default,
    # so asserting on it would make these tests environment-dependent.
    return patch("app.shorts.routes.settings.SHORTS_YT_DOWNLOAD_ENABLED", value)


def _enabled():
    return _flag(True)


def test_create_job_returns_410_when_flag_off():
    with _flag(False), patch("app.shorts.routes.supabase", return_value=_sb_with_channel()):
        r = _client().post("/shorts/jobs", json=BODY)
    assert r.status_code == 410


def test_create_job_enqueues():
    with _enabled(), patch("app.shorts.routes.supabase", return_value=_sb_with_channel()):
        r = _client().post("/shorts/jobs", json={**BODY, "cut_mode": "coverage"})
    assert r.status_code == 200 and r.json() == {"job_id": 42}


def test_create_job_rejects_non_youtube_url():
    with _enabled(), patch("app.shorts.routes.supabase", return_value=_sb_with_channel()):
        r = _client().post("/shorts/jobs", json={**BODY, "source_url": "https://vimeo.com/1"})
    assert r.status_code == 400


def test_create_job_unknown_channel_404():
    with _enabled(), patch("app.shorts.routes.supabase", return_value=_sb_with_channel(found=False)):
        r = _client().post("/shorts/jobs", json=BODY)
    assert r.status_code == 404
