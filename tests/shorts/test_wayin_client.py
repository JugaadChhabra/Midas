import pytest
from unittest.mock import patch, MagicMock


def _mock_response(status_code: int, json_body: dict):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.text = str(json_body)
    return resp


def test_submit_clipping_returns_project_id():
    with patch("app.shorts.wayin_client.httpx.post") as mock_post:
        mock_post.return_value = _mock_response(200, {"data": {"project_id": "prj_abc"}})
        from app.shorts.wayin_client import submit_clipping
        pid = submit_clipping("https://www.youtube.com/watch?v=xyz")
    assert pid == "prj_abc"
    args, kwargs = mock_post.call_args
    assert "/clipping" in args[0] or "/clipping" in kwargs.get("url", "")
    assert kwargs["headers"]["Authorization"].startswith("Bearer ")
    assert kwargs["headers"]["x-wayinvideo-api-version"] == "v2"
    assert kwargs["json"]["video_url"] == "https://www.youtube.com/watch?v=xyz"
    assert kwargs["json"]["export"] is True


def test_submit_clipping_raises_on_http_error():
    with patch("app.shorts.wayin_client.httpx.post") as mock_post:
        mock_post.return_value = _mock_response(429, {"error": "rate limited"})
        from app.shorts.wayin_client import submit_clipping, WayinVideoError
        with pytest.raises(WayinVideoError, match="429"):
            submit_clipping("https://www.youtube.com/watch?v=xyz")


def test_get_status_returns_data_payload():
    with patch("app.shorts.wayin_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(200, {
            "data": {"project_id": "prj_abc", "status": "ONGOING"}
        })
        from app.shorts.wayin_client import get_status
        data = get_status("prj_abc")
    assert data["status"] == "ONGOING"
    args, kwargs = mock_get.call_args
    assert "prj_abc" in args[0] or "prj_abc" in kwargs.get("url", "")


def test_get_status_raises_on_http_error():
    with patch("app.shorts.wayin_client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(500, {"error": "boom"})
        from app.shorts.wayin_client import get_status, WayinVideoError
        with pytest.raises(WayinVideoError, match="500"):
            get_status("prj_abc")
