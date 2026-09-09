from unittest.mock import patch

from tests.fakes import FakeSupabase


def _sb(videos, shorts_jobs):
    """supabase() stand-in for the shorts source picker, backed by the real fake.

    The picker's videos query filters `is_short=False` and
    `duration_seconds < SHORTS_MAX_SOURCE_SECONDS` and scopes by channel; the
    fake applies those for real, so fixtures carry a channel_id and an
    under-cap duration by default (a test can still override either). The
    shorts_jobs query scopes by channel and `source_video_id`.
    """
    vids = [{"channel_id": "UC1", "duration_seconds": 100, **v} for v in videos]
    jobs = [{"channel_id": "UC1", **j} for j in shorts_jobs]
    return FakeSupabase(tables={"videos": vids, "shorts_jobs": jobs})


CH = {"id": "UC1", "autopilot_shorts_daily_cap": 1, "autopilot_shorts_upload_cap": 2,
      "shorts_cut_mode": "highlights", "shorts_camera_motion": "calm"}


def test_next_uncut_skips_shorts_nonpublic_and_already_cut():
    import app.autopilot as ap
    videos = [
        {"id": "vShort", "channel_id": "UC1", "is_short": True, "privacy_status": "public"},
        {"id": "vPriv", "channel_id": "UC1", "is_short": False, "privacy_status": "private"},
        {"id": "vCut", "channel_id": "UC1", "is_short": False, "privacy_status": "public"},
        {"id": "vGood", "channel_id": "UC1", "is_short": False, "privacy_status": "public"},
    ]
    # NOTE: videos here is the already-filtered is_short=False set the query returns;
    # the query itself applies .eq('is_short', False), so vShort won't be in `videos`.
    long_videos = [v for v in videos if not v["is_short"]]
    sj = [{"source_video_id": "vCut"}]
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj)):
        v = ap._next_uncut_video_for_channel("UC1")
    assert v is not None and v["id"] == "vGood"


def test_next_uncut_retries_video_with_only_failed_jobs():
    """A source whose only shorts_jobs are FAILED is retryable — the earlier
    failures (e.g. transient PO-token download errors) must not burn it out of
    the autopilot pool permanently."""
    import app.autopilot as ap
    long_videos = [{"id": "vFailed", "channel_id": "UC1", "is_short": False, "privacy_status": "public"}]
    sj = [{"source_video_id": "vFailed", "status": "FAILED"}]
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj)):
        v = ap._next_uncut_video_for_channel("UC1")
    assert v is not None and v["id"] == "vFailed"


def test_next_uncut_skips_video_at_retry_cap():
    """A source that has failed MAX_SHORTS_RETRY_ATTEMPTS times is not retried,
    so a permanently-broken video can never wedge the queue."""
    import app.autopilot as ap
    long_videos = [
        {"id": "vPoison", "channel_id": "UC1", "is_short": False, "privacy_status": "public"},
        {"id": "vGood", "channel_id": "UC1", "is_short": False, "privacy_status": "public"},
    ]
    sj = [{"source_video_id": "vPoison", "status": "FAILED"}] * ap.MAX_SHORTS_RETRY_ATTEMPTS
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj)):
        v = ap._next_uncut_video_for_channel("UC1")
    assert v is not None and v["id"] == "vGood"


def test_next_uncut_skips_video_with_done_job():
    """A source with a successful (non-FAILED) job is never re-cut, even if it
    also has earlier FAILED attempts."""
    import app.autopilot as ap
    long_videos = [{"id": "vDone", "channel_id": "UC1", "is_short": False, "privacy_status": "public"}]
    sj = [{"source_video_id": "vDone", "status": "FAILED"},
          {"source_video_id": "vDone", "status": "DONE"}]
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj)):
        v = ap._next_uncut_video_for_channel("UC1")
    assert v is None


def test_run_shorts_action_enqueues_from_nas_folder():
    import app.autopilot as ap
    ch = {"id": "UC1", "nas_folder": "HINDI", "shorts_cut_mode": "highlights",
          "shorts_camera_motion": "calm"}
    with patch.object(ap, "active_job_count", return_value=0), \
         patch("app.shorts.nas_source.enqueue_language_jobs", return_value=3) as enq:
        ap._run_shorts_action(ch)
    enq.assert_called_once_with("HINDI", channel_id="UC1", autopilot=True,
                                cut_mode="highlights", camera_motion="calm")


def test_run_shorts_action_noop_without_folder():
    import app.autopilot as ap
    with patch("app.shorts.nas_source.enqueue_language_jobs") as enq:
        ap._run_shorts_action({"id": "UC1", "nas_folder": None})
    enq.assert_not_called()


def test_run_shorts_action_noop_when_at_capacity():
    import app.autopilot as ap
    ch = {"id": "UC1", "nas_folder": "HINDI"}
    with patch.object(ap, "active_job_count", return_value=99), \
         patch("app.shorts.nas_source.enqueue_language_jobs") as enq:
        ap._run_shorts_action(ch)
    enq.assert_not_called()


def test_run_shorts_action_swallows_unknown_folder():
    import app.autopilot as ap
    ch = {"id": "UC1", "nas_folder": "KLINGON"}
    with patch.object(ap, "active_job_count", return_value=0), \
         patch("app.shorts.nas_source.enqueue_language_jobs", side_effect=ValueError("nope")):
        ap._run_shorts_action(ch)   # must not raise
