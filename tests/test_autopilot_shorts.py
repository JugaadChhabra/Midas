from unittest.mock import MagicMock, patch


def _sb(videos, shorts_jobs, recorder):
    """supabase() stand-in for the shorts helpers.
    - videos: .table('videos').select().eq().order().execute().data
    - shorts_jobs select: .table('shorts_jobs').select().eq()[.eq()][.in_()][.gte()].execute().data
    - shorts_jobs insert: recorded, returns a row with id 99
    """
    sb = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "videos":
            # query is .select('*').eq('channel_id',..).eq('is_short', False).order(..).execute()
            t.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value.data = videos
        if name == "shorts_jobs":
            # select chains used: .select(...).eq('channel_id',..).in_('source_video_id',..).execute()
            # and .select(...).eq('channel_id',..).eq('autopilot_generated',..).gte('created_at',..).execute()
            sel = t.select.return_value
            sel.eq.return_value.in_.return_value.execute.return_value.data = shorts_jobs["by_source"]
            sel.eq.return_value.eq.return_value.gte.return_value.execute.return_value.data = shorts_jobs["today"]

            def _insert(fields):
                recorder.append(fields)
                ins = MagicMock()
                ins.execute.return_value.data = [{"id": 99, **fields}]
                return ins
            t.insert.side_effect = _insert
        return t

    sb.table.side_effect = table
    return sb


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
    sj = {"by_source": [{"source_video_id": "vCut"}], "today": []}
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj, [])):
        v = ap._next_uncut_video_for_channel("UC1")
    assert v is not None and v["id"] == "vGood"


def test_run_shorts_action_enqueues_when_eligible():
    import app.autopilot as ap
    rec = []
    long_videos = [{"id": "vGood", "channel_id": "UC1", "is_short": False, "privacy_status": "public"}]
    sj = {"by_source": [], "today": []}
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj, rec)), \
         patch("app.autopilot.has_active_job", return_value=False), \
         patch("app.autopilot.start_job_thread") as start:
        ap._run_shorts_action(CH)
    assert len(rec) == 1
    job = rec[0]
    assert job["source_video_id"] == "vGood"
    assert job["autopilot_generated"] is True
    assert job["upload_cap"] == 2
    assert job["cut_mode"] == "highlights" and job["camera_motion"] == "calm"
    assert job["status"] == "CREATED"
    start.assert_called_once_with(99)


def test_run_shorts_action_noop_when_busy():
    import app.autopilot as ap
    rec = []
    with patch("app.autopilot.supabase", return_value=_sb([], {"by_source": [], "today": []}, rec)), \
         patch("app.autopilot.has_active_job", return_value=True), \
         patch("app.autopilot.start_job_thread") as start:
        ap._run_shorts_action(CH)
    assert rec == [] and start.call_count == 0


def test_run_shorts_action_noop_over_daily_cap():
    import app.autopilot as ap
    rec = []
    long_videos = [{"id": "vGood", "channel_id": "UC1", "is_short": False, "privacy_status": "public"}]
    sj = {"by_source": [], "today": [{"id": 1}]}   # already 1 today, cap is 1
    with patch("app.autopilot.supabase", return_value=_sb(long_videos, sj, rec)), \
         patch("app.autopilot.has_active_job", return_value=False), \
         patch("app.autopilot.start_job_thread") as start:
        ap._run_shorts_action(CH)
    assert rec == [] and start.call_count == 0


def test_run_shorts_action_noop_when_no_eligible_video():
    import app.autopilot as ap
    rec = []
    sj = {"by_source": [], "today": []}
    with patch("app.autopilot.supabase", return_value=_sb([], sj, rec)), \
         patch("app.autopilot.has_active_job", return_value=False), \
         patch("app.autopilot.start_job_thread") as start:
        ap._run_shorts_action(CH)
    assert rec == [] and start.call_count == 0
