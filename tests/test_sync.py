from unittest.mock import patch, MagicMock


def _video_item(vid: str, *, privacy="public", duration="PT5M",
                views=0, likes=0, comments=0):
    """Full videos.list item (snippet+statistics+contentDetails+status)."""
    return {
        "id": vid,
        "snippet": {"title": f"t-{vid}", "description": "", "tags": [],
                    "categoryId": "22", "publishedAt": "2026-01-01T00:00:00Z"},
        "statistics": {"viewCount": str(views), "likeCount": str(likes),
                       "commentCount": str(comments)},
        "contentDetails": {"duration": duration},
        "status": {"privacyStatus": privacy},
    }


def _playlist_page(video_ids, next_token=None):
    return {
        "items": [{"contentDetails": {"videoId": v}} for v in video_ids],
        "nextPageToken": next_token,
    }


def _fake_supabase(known_ids, recorder):
    """Stateful fake: channels.select returns {}, videos.select(id) returns
    known_ids, and upserts/updates are captured into `recorder`."""
    sb_fn = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "channels":
            t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {}
            t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "videos":
            t.select.return_value.eq.return_value.execute.return_value.data = [
                {"id": i} for i in known_ids
            ]

            def _upsert(rows):
                recorder["upserts"].append(rows)
                return MagicMock()
            t.upsert.side_effect = _upsert

            def _update(payload):
                recorder["updates"].append(payload)
                m = MagicMock()
                m.eq.return_value.execute.return_value = MagicMock()
                m.in_.return_value.execute.return_value = MagicMock()
                return m
            t.update.side_effect = _update
        return t

    sb_fn.table.side_effect = table
    return sb_fn


# ── incremental discovery ────────────────────────────────────────────────

def test_incremental_sync_stops_at_first_known_video():
    """Uploads playlist is newest-first; sync should stop paginating and stop
    collecting once it hits a video already in the DB, and only fetch full
    metadata for the new ids."""
    recorder = {"upserts": [], "updates": []}
    fetched_batches = []

    def fake_full(yt, cid, ids):
        fetched_batches.append(list(ids))
        return [_video_item(v) for v in ids]

    # Page 1 contains 2 new then 1 known; page 2 must NOT be requested.
    pages = [_playlist_page(["new1", "new2", "known1"], next_token="PAGE2")]

    with patch("app.sync.supabase", return_value=_fake_supabase(["known1", "known2"], recorder)), \
         patch("app.sync.youtube_for_channel", return_value=MagicMock()), \
         patch("app.sync.yt_channels_list_uploads",
               return_value={"uploads_playlist_id": "UP", "default_language": None}), \
         patch("app.sync.yt_playlist_items_page", side_effect=pages) as page_call, \
         patch("app.sync.yt_videos_list_full", side_effect=fake_full):
        from app.sync import sync_channel
        result = sync_channel("UCchan")

    assert result == {"synced": 2}
    assert fetched_batches == [["new1", "new2"]]   # known1 never re-fetched
    assert page_call.call_count == 1               # early exit, no page 2


def test_full_sync_fetches_everything_across_pages():
    recorder = {"upserts": [], "updates": []}
    fetched = []

    def fake_full(yt, cid, ids):
        fetched.extend(ids)
        return [_video_item(v) for v in ids]

    pages = [
        _playlist_page(["a", "b"], next_token="P2"),
        _playlist_page(["c", "known1"], next_token=None),
    ]

    with patch("app.sync.supabase", return_value=_fake_supabase(["known1"], recorder)), \
         patch("app.sync.youtube_for_channel", return_value=MagicMock()), \
         patch("app.sync.yt_channels_list_uploads",
               return_value={"uploads_playlist_id": "UP", "default_language": None}), \
         patch("app.sync.yt_playlist_items_page", side_effect=pages), \
         patch("app.sync.yt_videos_list_full", side_effect=fake_full):
        from app.sync import sync_channel
        result = sync_channel("UCchan", full=True)

    assert result == {"synced": 4}
    assert sorted(fetched) == ["a", "b", "c", "known1"]   # ignores known set


def test_first_sync_with_empty_db_fetches_all():
    recorder = {"upserts": [], "updates": []}
    fetched = []

    def fake_full(yt, cid, ids):
        fetched.extend(ids)
        return [_video_item(v) for v in ids]

    pages = [_playlist_page(["x", "y"], next_token=None)]

    with patch("app.sync.supabase", return_value=_fake_supabase([], recorder)), \
         patch("app.sync.youtube_for_channel", return_value=MagicMock()), \
         patch("app.sync.yt_channels_list_uploads",
               return_value={"uploads_playlist_id": "UP", "default_language": None}), \
         patch("app.sync.yt_playlist_items_page", side_effect=pages), \
         patch("app.sync.yt_videos_list_full", side_effect=fake_full):
        from app.sync import sync_channel
        result = sync_channel("UCchan")

    assert result == {"synced": 2}
    assert sorted(fetched) == ["x", "y"]


# ── stats + status refresh (privacy-flip detection, option B) ─────────────

def test_refresh_stats_updates_counts_and_privacy_flip():
    """refresh_stats pulls statistics+status for existing videos and writes the
    new privacy_status (catching public→private flips) plus fresh counts."""
    recorder = {"upserts": [], "updates": []}

    def fake_stats(yt, cid, ids):
        # v1 went private since last sync; v2 stays public with new views.
        return [
            _video_item("v1", privacy="private", views=10, likes=2),
            _video_item("v2", privacy="public", views=99, likes=5),
        ]

    with patch("app.sync.supabase", return_value=_fake_supabase(["v1", "v2"], recorder)), \
         patch("app.sync.youtube_for_channel", return_value=MagicMock()), \
         patch("app.sync.yt_videos_list_stats", side_effect=fake_stats):
        from app.sync import refresh_stats
        result = refresh_stats("UCchan")

    assert result == {"refreshed": 2}
    by_privacy = [u for u in recorder["updates"] if "privacy_status" in u]
    v1_update = next(u for u in by_privacy if u.get("view_count") == 10)
    assert v1_update["privacy_status"] == "private"
    v2_update = next(u for u in by_privacy if u.get("view_count") == 99)
    assert v2_update["privacy_status"] == "public"


def test_full_sync_stamps_last_full_synced_at():
    """A full sync records last_full_synced_at so autopilot can space full
    passes; an incremental sync must NOT stamp it."""
    captured = {"patches": []}

    def fake_full(yt, cid, ids):
        return [_video_item(v) for v in ids]

    def make_sb():
        sb_fn = MagicMock()

        def table(name):
            t = MagicMock()
            if name == "channels":
                t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {}

                def _update(payload):
                    captured["patches"].append(payload)
                    m = MagicMock()
                    m.eq.return_value.execute.return_value = MagicMock()
                    return m
                t.update.side_effect = _update
            elif name == "videos":
                t.select.return_value.eq.return_value.execute.return_value.data = []
                t.upsert.return_value.execute.return_value = MagicMock()
                t.update.return_value.in_.return_value.execute.return_value = MagicMock()
            return t
        sb_fn.table.side_effect = table
        return sb_fn

    common = dict(
        uploads={"uploads_playlist_id": "UP", "default_language": None},
        pages=[_playlist_page(["a"], next_token=None)],
    )
    for is_full in (True, False):
        captured["patches"].clear()
        with patch("app.sync.supabase", return_value=make_sb()), \
             patch("app.sync.youtube_for_channel", return_value=MagicMock()), \
             patch("app.sync.yt_channels_list_uploads", return_value=common["uploads"]), \
             patch("app.sync.yt_playlist_items_page", side_effect=list(common["pages"])), \
             patch("app.sync.yt_videos_list_full", side_effect=fake_full):
            from app.sync import sync_channel
            sync_channel("UCchan", full=is_full)
        channel_patch = next(p for p in captured["patches"] if "last_synced_at" in p)
        assert ("last_full_synced_at" in channel_patch) is is_full


def test_sync_bounds_probes_per_run():
    """Only the newest MAX_SHORTS_PROBES_PER_SYNC new videos are probed; the
    rest fall back to the duration label so a big first sync can't hammer
    YouTube with thousands of probes."""
    recorder = {"upserts": [], "updates": []}

    def fake_full(yt, cid, ids):
        return [_video_item(v, duration="PT1M30S") for v in ids]  # 90s, all sub-180

    # newest-first: n1, n2, n3
    pages = [_playlist_page(["n1", "n2", "n3"], next_token=None)]
    with patch("app.sync.supabase", return_value=_fake_supabase([], recorder)), \
         patch("app.sync.youtube_for_channel", return_value=MagicMock()), \
         patch("app.sync.yt_channels_list_uploads",
               return_value={"uploads_playlist_id": "UP", "default_language": None}), \
         patch("app.sync.yt_playlist_items_page", side_effect=pages), \
         patch("app.sync.yt_videos_list_full", side_effect=fake_full), \
         patch("app.sync.MAX_SHORTS_PROBES_PER_SYNC", 2), \
         patch("app.sync.is_actually_short", return_value=False) as probe:
        from app.sync import sync_channel
        sync_channel("UCchan")

    assert probe.call_count == 2   # only the newest 2 are probed
    upserted = {r["id"]: r for batch in recorder["upserts"] for r in batch}
    assert upserted["n1"]["is_short"] is False   # probed
    assert upserted["n2"]["is_short"] is False   # probed
    assert upserted["n3"]["is_short"] is True    # duration fallback (<=180s)


# ── is_short detection (URL probe, not duration heuristic) ────────────────

def test_is_actually_short_skips_probe_for_long_video():
    """A video over the Shorts max length can never be a Short, so no network
    probe is made — is_short is False purely from duration."""
    from app.sync import is_actually_short
    with patch("app.sync.httpx.get") as get:
        assert is_actually_short("vid", 300) is False
        get.assert_not_called()


def test_is_actually_short_true_when_shorts_url_serves_200():
    from app.sync import is_actually_short
    resp = MagicMock(status_code=200)
    with patch("app.sync.httpx.get", return_value=resp) as get:
        assert is_actually_short("vid", 90) is True
        assert "youtube.com/shorts/vid" in get.call_args.args[0]


def test_is_actually_short_false_when_shorts_url_redirects():
    """A regular sub-3-min video 30x-redirects /shorts/<id> to /watch."""
    from app.sync import is_actually_short
    resp = MagicMock(status_code=303)
    with patch("app.sync.httpx.get", return_value=resp):
        assert is_actually_short("vid", 116) is False


def test_is_actually_short_falls_back_to_duration_on_network_error():
    import httpx
    from app.sync import is_actually_short
    with patch("app.sync.httpx.get", side_effect=httpx.ConnectError("boom")):
        assert is_actually_short("vid", 90) is True    # <=180 -> short by fallback


def test_sync_reuses_stored_is_short_and_probes_only_new_videos():
    """is_short never changes for a video, so a full sync must reuse the stored
    value for known ids and probe only genuinely new ids."""
    recorder = {"upserts": [], "updates": []}

    def fake_full(yt, cid, ids):
        # both are sub-180s so, absent reuse, both would be probed
        return [_video_item(v, duration="PT1M30S") for v in ids]

    # 'known1' already stored as is_short=True; 'newvid' is new.
    def make_sb():
        sb_fn = MagicMock()

        def table(name):
            t = MagicMock()
            if name == "channels":
                t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {}
                t.update.return_value.eq.return_value.execute.return_value = MagicMock()
            elif name == "videos":
                t.select.return_value.eq.return_value.execute.return_value.data = [
                    {"id": "known1", "is_short": True},
                ]
                t.upsert.side_effect = lambda rows: recorder["upserts"].append(rows) or MagicMock()
                m = MagicMock()
                m.in_.return_value.execute.return_value = MagicMock()
                t.update.return_value = m
            return t
        sb_fn.table.side_effect = table
        return sb_fn

    pages = [_playlist_page(["newvid", "known1"], next_token=None)]
    with patch("app.sync.supabase", return_value=make_sb()), \
         patch("app.sync.youtube_for_channel", return_value=MagicMock()), \
         patch("app.sync.yt_channels_list_uploads",
               return_value={"uploads_playlist_id": "UP", "default_language": None}), \
         patch("app.sync.yt_playlist_items_page", side_effect=pages), \
         patch("app.sync.yt_videos_list_full", side_effect=fake_full), \
         patch("app.sync.is_actually_short", return_value=False) as probe:
        from app.sync import sync_channel
        sync_channel("UCchan", full=True)

    # probe called only for the new id, never for the already-stored one
    probed_ids = [c.args[0] for c in probe.call_args_list]
    assert probed_ids == ["newvid"]
    upserted = {r["id"]: r for batch in recorder["upserts"] for r in batch}
    assert upserted["known1"]["is_short"] is True     # reused, not re-probed
    assert upserted["newvid"]["is_short"] is False     # from probe


def test_yt_videos_list_stats_requests_status_part():
    mock_yt = MagicMock()
    mock_yt.videos.return_value.list.return_value.execute.return_value = {"items": []}
    with patch("app.youtube_client._log_quota"):
        from app.youtube_client import yt_videos_list_stats
        yt_videos_list_stats(mock_yt, "ch", ["v1"])
    part = mock_yt.videos.return_value.list.call_args.kwargs["part"]
    assert "statistics" in part
    assert "status" in part
