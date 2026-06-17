import os
from unittest.mock import patch, MagicMock


def test_normalize_clips_renames_synonyms():
    from app.shorts.pipeline import normalize_clips
    raw = [
        {"rank": 1, "title": "A", "description": "d", "hashtags": ["#x"],
         "start": 12.0, "end": 25.5, "url": "https://w/clip1.mp4"},
        {"rank": 2, "title": "B", "video_url": "https://w/clip2.mp4",
         "start_seconds": 30, "end_seconds": 40},
    ]
    norm = normalize_clips(raw)
    assert norm[0]["source_url"] == "https://w/clip1.mp4"
    assert norm[0]["start_s"] == 12.0
    assert norm[0]["end_s"] == 25.5
    assert norm[1]["source_url"] == "https://w/clip2.mp4"
    assert norm[1]["start_s"] == 30
    assert norm[1]["hashtags"] == []  # default empty list when missing


def test_normalize_clips_fills_rank_if_missing():
    from app.shorts.pipeline import normalize_clips
    raw = [{"title": "A", "url": "u1"}, {"title": "B", "url": "u2"}]
    norm = normalize_clips(raw)
    assert [c["rank"] for c in norm] == [1, 2]


def test_upload_one_clip_streams_then_succeeds():
    """Happy path: streaming upload returns a video id, no local file written."""
    clip = {"id": 5, "rank": 1, "title": "T", "description": "D", "hashtags": ["#a"],
            "source_url": "https://w/clip.mp4"}
    fake_stream_resp = MagicMock()
    fake_stream_resp.iter_bytes.return_value = iter([b"abc"])
    fake_stream_resp.raise_for_status = MagicMock()
    fake_stream_ctx = MagicMock()
    fake_stream_ctx.__enter__.return_value = fake_stream_resp
    fake_stream_ctx.__exit__.return_value = False

    with patch("app.shorts.pipeline.httpx.stream", return_value=fake_stream_ctx), \
         patch("app.shorts.pipeline.upload_short", return_value="vid_ok") as up:
        from app.shorts.pipeline import _upload_one_clip
        patch_dict = _upload_one_clip("UC_chan", clip)

    assert patch_dict["yt_video_id"] == "vid_ok"
    assert patch_dict["upload_status"] == "UPLOADED"
    assert patch_dict.get("local_path") is None
    assert up.called


def test_upload_one_clip_falls_back_to_disk_on_stream_failure(tmp_path, monkeypatch):
    """Streaming upload fails → download to disk → retry → record yt_video_id."""
    monkeypatch.setattr("app.shorts.pipeline.settings.SHORTS_CACHE_DIR", str(tmp_path))

    clip = {"id": 7, "rank": 2, "title": "T2", "description": "D",
            "hashtags": [], "source_url": "https://w/clip.mp4"}

    # First stream() call (streaming upload) — its consumer (upload_short) will raise.
    fake_stream_resp = MagicMock()
    fake_stream_resp.iter_bytes.return_value = iter([b"abc"])
    fake_stream_resp.raise_for_status = MagicMock()
    fake_stream_ctx = MagicMock()
    fake_stream_ctx.__enter__.return_value = fake_stream_resp
    fake_stream_ctx.__exit__.return_value = False

    # Second stream() call (download to disk) — succeeds.
    fake_dl_resp = MagicMock()
    fake_dl_resp.iter_bytes.return_value = iter([b"x" * 100])
    fake_dl_resp.raise_for_status = MagicMock()
    fake_dl_ctx = MagicMock()
    fake_dl_ctx.__enter__.return_value = fake_dl_resp
    fake_dl_ctx.__exit__.return_value = False

    upload_calls = []

    def fake_upload(channel_id, source, title, description, tags):
        upload_calls.append(source)
        if len(upload_calls) == 1:
            raise RuntimeError("network glitch")
        return "vid_fallback"

    with patch("app.shorts.pipeline.httpx.stream", side_effect=[fake_stream_ctx, fake_dl_ctx]), \
         patch("app.shorts.pipeline.upload_short", side_effect=fake_upload):
        from app.shorts.pipeline import _upload_one_clip
        patch_dict = _upload_one_clip("UC_chan", clip)

    assert patch_dict["yt_video_id"] == "vid_fallback"
    assert patch_dict["upload_status"] == "UPLOADED"
    assert patch_dict["local_path"] is not None
    assert os.path.exists(patch_dict["local_path"])


def test_upload_one_clip_records_failure_when_disk_retry_also_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("app.shorts.pipeline.settings.SHORTS_CACHE_DIR", str(tmp_path))
    clip = {"id": 9, "rank": 3, "title": "T", "description": "",
            "hashtags": [], "source_url": "https://w/clip.mp4"}

    fake_resp = MagicMock()
    fake_resp.iter_bytes.return_value = iter([b"abc"])
    fake_resp.raise_for_status = MagicMock()
    fake_ctx = MagicMock()
    fake_ctx.__enter__.return_value = fake_resp
    fake_ctx.__exit__.return_value = False

    with patch("app.shorts.pipeline.httpx.stream", side_effect=[fake_ctx, fake_ctx]), \
         patch("app.shorts.pipeline.upload_short", side_effect=RuntimeError("boom")):
        from app.shorts.pipeline import _upload_one_clip
        patch_dict = _upload_one_clip("UC_chan", clip)

    assert patch_dict["upload_status"] == "FAILED"
    assert "boom" in patch_dict["upload_error"]
    # The downloaded fallback file should be preserved for manual upload.
    assert patch_dict["local_path"] is not None
