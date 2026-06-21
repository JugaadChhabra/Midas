import pytest
from unittest.mock import patch, MagicMock


def _mock_response(status_code: int, json_body: dict):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.text = str(json_body)
    return resp


@pytest.fixture(autouse=True)
def _wayin_key(monkeypatch):
    # Ensure a non-empty key for all tests except those that explicitly clear it.
    from app.config import settings
    monkeypatch.setattr(settings, "WAYINVIDEO_API_KEY", "test-key", raising=False)


def test_submit_clipping_returns_project_id():
    with patch("app.shorts.wayin_client.httpx.request") as mock_req:
        mock_req.return_value = _mock_response(200, {"data": {"id": "prj_abc"}})
        from app.shorts.wayin_client import submit_clipping
        pid = submit_clipping("https://www.youtube.com/watch?v=xyz")
    assert pid == "prj_abc"
    args, kwargs = mock_req.call_args
    assert args[0] == "POST"
    assert args[1].endswith("/clips")
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert kwargs["headers"]["x-wayinvideo-api-version"] == "v2"
    assert kwargs["json"]["video_url"] == "https://www.youtube.com/watch?v=xyz"
    assert kwargs["json"]["enable_export"] is True


def test_submit_clipping_sends_reframe_settings(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "WAYINVIDEO_REFRAME", True, raising=False)
    monkeypatch.setattr(settings, "WAYINVIDEO_RATIO", "RATIO_9_16", raising=False)
    monkeypatch.setattr(settings, "WAYINVIDEO_RESOLUTION", "HD_720", raising=False)
    monkeypatch.setattr(settings, "WAYINVIDEO_CAPTIONS", True, raising=False)
    monkeypatch.setattr(settings, "WAYINVIDEO_REFRAME_LAYOUT", "Full", raising=False)
    with patch("app.shorts.wayin_client.httpx.request") as mock_req:
        mock_req.return_value = _mock_response(200, {"data": {"id": "prj_abc"}})
        from app.shorts.wayin_client import submit_clipping
        submit_clipping("https://www.youtube.com/watch?v=xyz")
    body = mock_req.call_args.kwargs["json"]
    assert body["enable_export"] is True
    assert body["enable_ai_reframe"] is True
    assert body["ratio"] == "RATIO_9_16"
    assert body["resolution"] == "HD_720"
    assert body["enable_caption"] is True
    assert body["reframe_layout"] == "Full"


def test_submit_clipping_omits_layout_when_auto(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "WAYINVIDEO_REFRAME", True, raising=False)
    monkeypatch.setattr(settings, "WAYINVIDEO_REFRAME_LAYOUT", "Auto", raising=False)
    with patch("app.shorts.wayin_client.httpx.request") as mock_req:
        mock_req.return_value = _mock_response(200, {"data": {"id": "prj_abc"}})
        from app.shorts.wayin_client import submit_clipping
        submit_clipping("https://www.youtube.com/watch?v=xyz")
    assert "reframe_layout" not in mock_req.call_args.kwargs["json"]


def test_submit_clipping_omits_reframe_when_disabled(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "WAYINVIDEO_REFRAME", False, raising=False)
    with patch("app.shorts.wayin_client.httpx.request") as mock_req:
        mock_req.return_value = _mock_response(200, {"data": {"id": "prj_abc"}})
        from app.shorts.wayin_client import submit_clipping
        submit_clipping("https://www.youtube.com/watch?v=xyz")
    body = mock_req.call_args.kwargs["json"]
    assert "enable_ai_reframe" not in body
    assert "ratio" not in body


def test_submit_clipping_raises_on_http_error():
    with patch("app.shorts.wayin_client.httpx.request") as mock_req:
        mock_req.return_value = _mock_response(429, {"error": "rate limited"})
        from app.shorts.wayin_client import submit_clipping, WayinVideoError
        with pytest.raises(WayinVideoError, match="429") as exc_info:
            submit_clipping("https://www.youtube.com/watch?v=xyz")
        assert exc_info.value.status_code == 429


def test_submit_clipping_raises_when_api_key_missing(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "WAYINVIDEO_API_KEY", "", raising=False)
    from app.shorts.wayin_client import submit_clipping, WayinVideoNotConfigured
    with pytest.raises(WayinVideoNotConfigured, match="WAYINVIDEO_API_KEY"):
        submit_clipping("https://www.youtube.com/watch?v=xyz")


def test_submit_clipping_wraps_network_error():
    import httpx
    with patch("app.shorts.wayin_client.httpx.request") as mock_req:
        mock_req.side_effect = httpx.ConnectError("boom")
        from app.shorts.wayin_client import submit_clipping, WayinVideoError
        with pytest.raises(WayinVideoError, match="network error"):
            submit_clipping("https://www.youtube.com/watch?v=xyz")


def test_get_status_returns_data_payload():
    with patch("app.shorts.wayin_client.httpx.request") as mock_req:
        mock_req.return_value = _mock_response(200, {
            "data": {"id": "prj_abc", "status": "ONGOING"}
        })
        from app.shorts.wayin_client import get_status
        data = get_status("prj_abc")
    assert data["status"] == "ONGOING"
    args, kwargs = mock_req.call_args
    assert args[0] == "GET"
    assert args[1].endswith("/clips/results/prj_abc")


def test_get_status_raises_on_http_error():
    with patch("app.shorts.wayin_client.httpx.request") as mock_req:
        mock_req.return_value = _mock_response(500, {"error": "boom"})
        from app.shorts.wayin_client import get_status, WayinVideoError
        with pytest.raises(WayinVideoError, match="500"):
            get_status("prj_abc")
