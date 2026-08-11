"""Tier 2: metrics_poll narrows the daily sensor to videos under active
measurement (METRICS_POLL_MEASURED_ONLY), instead of every public video."""
from unittest.mock import MagicMock, patch

from app import metrics_poll


def test_measured_video_ids_pages_and_dedups():
    page = [{"video_id": "v1"}, {"video_id": "v1"}, {"video_id": "v2"}, {"video_id": None}]
    sb = MagicMock()

    def table(name):
        assert name == "audits"
        t = MagicMock()
        t.select.return_value.in_.return_value.order.return_value.range.return_value.execute.return_value.data = page
        return t

    sb.table.side_effect = table
    with patch.object(metrics_poll, "supabase", return_value=sb):
        ids = metrics_poll._measured_video_ids()
    assert ids == {"v1", "v2"}  # deduped, None dropped


def test_fetch_channel_videos_measured_chunks_and_filters_by_channel():
    # This channel owns v1/v2/v3; vX belongs to another channel and must not leak in.
    universe = {"v1": "public", "v2": "private", "v3": "public"}
    measured = {"v1", "v2", "v3", "vX"}
    captured_chunks: list[list[str]] = []
    sb = MagicMock()

    def table(name):
        assert name == "videos"
        t = MagicMock()

        def _in(col, ids):
            captured_chunks.append(list(ids))
            r = MagicMock()
            r.execute.return_value.data = [
                {"id": i, "privacy_status": universe[i]} for i in ids if i in universe
            ]
            return r

        t.select.return_value.eq.return_value.in_.side_effect = _in
        return t

    sb.table.side_effect = table
    with patch.object(metrics_poll, "_ID_CHUNK", 2), \
         patch.object(metrics_poll, "supabase", return_value=sb):
        rows = metrics_poll._fetch_channel_videos("chan", measured)

    assert sorted(r["id"] for r in rows) == ["v1", "v2", "v3"]  # vX excluded (other channel)
    assert len(captured_chunks) == 2                            # 4 ids / chunk-size 2
    assert all(len(c) <= 2 for c in captured_chunks)


def test_fetch_channel_videos_empty_measured_makes_no_query():
    sb = MagicMock()
    with patch.object(metrics_poll, "supabase", return_value=sb):
        rows = metrics_poll._fetch_channel_videos("chan", set())
    assert rows == []
    sb.table.assert_not_called()  # zero Analytics/DB work on a quiet day


def test_fetch_channel_videos_wide_net_paginates_all():
    sb = MagicMock()

    def table(name):
        assert name == "videos"
        t = MagicMock()
        t.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = [
            {"id": "v1", "privacy_status": "public"},
            {"id": "v2", "privacy_status": "unlisted"},
        ]
        return t

    sb.table.side_effect = table
    with patch.object(metrics_poll, "supabase", return_value=sb):
        rows = metrics_poll._fetch_channel_videos("chan", None)  # None => legacy wide net
    assert sorted(r["id"] for r in rows) == ["v1", "v2"]


def test_poll_channel_pages_playlists():
    """The playlist inventory read must page like the video read.

    Regression guard: `PAGE` was a function-local in _measured_video_ids /
    _fetch_channel_videos, so _poll_channel's playlist loop raised
    NameError before writing a single row — and poll_metrics swallowed it.
    """
    ranges: list[tuple[int, int]] = []

    def table(name):
        t = MagicMock()
        if name == "playlists":
            def _range(lo, hi):
                ranges.append((lo, hi))
                r = MagicMock()
                # one short page => loop terminates after the first read
                r.execute.return_value.data = [{"id": "pl1"}] if lo == 0 else []
                return r
            t.select.return_value.eq.return_value.order.return_value.range.side_effect = _range
        return t

    sb = MagicMock()
    sb.table.side_effect = table
    with patch.object(metrics_poll, "supabase", return_value=sb), \
         patch.object(metrics_poll, "analytics_for_channel", return_value=MagicMock()), \
         patch.object(metrics_poll, "yt_analytics_playlist_report", return_value=None):
        counts = metrics_poll._poll_channel(
            "c1", "2026-01-01", "2026-01-07", tier_2=False, measured_video_ids=set(),
        )

    assert ranges == [(0, 999)]              # paged, and asked for a full page
    assert counts["playlists_no_data"] == 1  # the playlist was actually polled


def test_poll_metrics_measured_empty_skips_video_poll():
    """No videos under measurement => not a single video Analytics call.

    Asserts the playlist poll still ran, so a crash before the video loop
    can't satisfy this test vacuously (it did, for the NameError above).
    """
    channels = [{"id": "c1", "analytics_authorized": True, "playlist_health_enabled": False}]

    def table(name):
        t = MagicMock()
        if name == "channels":
            t.select.return_value.eq.return_value.execute.return_value.data = channels
        else:  # playlists (and any other) -> one short page
            t.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = [
                {"id": "pl1"}
            ]
        return t

    sb = MagicMock()
    sb.table.side_effect = table
    video_report = MagicMock()
    playlist_report = MagicMock(return_value=None)
    with patch.object(metrics_poll.settings, "METRICS_POLL_MEASURED_ONLY", True), \
         patch.object(metrics_poll, "_measured_video_ids", return_value=set()), \
         patch.object(metrics_poll, "supabase", return_value=sb), \
         patch.object(metrics_poll, "analytics_for_channel", return_value=MagicMock()), \
         patch.object(metrics_poll, "yt_analytics_video_report", video_report), \
         patch.object(metrics_poll, "yt_analytics_playlist_report", playlist_report), \
         patch.object(metrics_poll.log, "exception") as mock_exc:
        metrics_poll.poll_metrics()

    video_report.assert_not_called()      # the narrowing works...
    playlist_report.assert_called_once()  # ...and the pass still did its work
    mock_exc.assert_not_called()          # nothing was swallowed
