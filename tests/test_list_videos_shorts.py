from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def test_list_videos_includes_shorts_fields():
    videos = [{"id": "v1", "channel_id": "UC1", "title": "Long one", "is_short": False,
               "published_at": "2026-07-01T00:00:00Z", "view_count": 100},
              {"id": "v2", "channel_id": "UC1", "title": "A short", "is_short": True,
               "published_at": "2026-07-02T00:00:00Z", "view_count": 5}]
    jobs = [{"id": 9, "source_video_id": "v1", "status": "DONE", "created_at": "2026-07-03T00:00:00Z"}]
    clips = [{"job_id": 9, "upload_status": "UPLOADED"}, {"job_id": 9, "upload_status": "PENDING"}]

    sb = MagicMock()
    def table(name):
        t = MagicMock()
        if name == "videos":
            t.select.return_value.eq.return_value.order.return_value.execute.return_value.data = videos
        if name == "audits":
            t.select.return_value.in_.return_value.order.return_value.execute.return_value.data = []
        if name == "shorts_jobs":
            t.select.return_value.in_.return_value.order.return_value.execute.return_value.data = jobs
        if name == "shorts_clips":
            t.select.return_value.in_.return_value.execute.return_value.data = clips
        return t
    sb.table.side_effect = table

    with patch("app.sync.supabase", return_value=sb):
        r = _client().get("/channels/UC1/videos")
    data = r.json()
    v1 = next(v for v in data if v["id"] == "v1")
    v2 = next(v for v in data if v["id"] == "v2")
    assert v1["is_short"] is False and v2["is_short"] is True
    assert v1["shorts_status"] == "DONE" and v1["shorts_job_id"] == 9
    assert v1["clips_count"] == 2 and v1["clips_uploaded"] == 1
    assert v2["shorts_status"] is None and v2["clips_count"] == 0
