import io
from unittest.mock import patch, MagicMock


def _fake_youtube_insert(returned_video_id: str = "vid_new"):
    """Build a fake youtube object whose .videos().insert().next_chunk() loop returns vid id."""
    fake_yt = MagicMock()
    insert_req = MagicMock()
    # next_chunk returns (status, response) per googleapiclient resumable loop.
    insert_req.next_chunk.side_effect = [
        (None, None),
        (None, {"id": returned_video_id}),
    ]
    fake_yt.videos.return_value.insert.return_value = insert_req
    return fake_yt, insert_req


def test_upload_short_from_file_path_returns_video_id(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fakebytes")
    fake_yt, _ = _fake_youtube_insert("vid_xyz")
    with patch("app.shorts.youtube_upload.youtube_for_channel", return_value=fake_yt):
        from app.shorts.youtube_upload import upload_short
        vid = upload_short("UC_chan", str(src), "Title", "Desc", ["#tag"])
    assert vid == "vid_xyz"


def test_upload_short_from_stream_returns_video_id():
    stream = io.BytesIO(b"fakebytes")
    fake_yt, _ = _fake_youtube_insert("vid_stream")
    with patch("app.shorts.youtube_upload.youtube_for_channel", return_value=fake_yt):
        from app.shorts.youtube_upload import upload_short
        vid = upload_short("UC_chan", stream, "T", "D", [])
    assert vid == "vid_stream"


def test_upload_short_sets_private_visibility(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fakebytes")
    fake_yt, insert_req = _fake_youtube_insert()
    with patch("app.shorts.youtube_upload.youtube_for_channel", return_value=fake_yt):
        from app.shorts.youtube_upload import upload_short
        upload_short("UC_chan", str(src), "T", "D", [])
    insert_kwargs = fake_yt.videos.return_value.insert.call_args.kwargs
    body = insert_kwargs["body"]
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["selfDeclaredMadeForKids"] is False
    assert body["snippet"]["title"] == "T"
    assert "snippet,status" == insert_kwargs["part"]
