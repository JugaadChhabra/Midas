"""Upload capture in the video sync (team tracker 06, #150).

Every video the sync fetches lands in `channel_uploads` with its upload time,
including the ones it keeps out of `videos`: private and scheduled uploads, and
Shorts on a channel with `sync_shorts = false`. Exercised through the real
`sync_channel` against FakeSupabase; only YouTube (the playlist page and
videos.list) and the Shorts-URL probe are stubbed.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app import sync
from tests.fakes import FakeSupabase

CH = "UCchan"
UPLOADED = "2026-11-17T18:45:00Z"      # playlistItem snippet.publishedAt
GO_LIVE = "2026-11-20T04:30:00Z"       # the scheduled video's status.publishAt


def _ts(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def _video(vid: str, *, privacy="public", duration="PT5M", published="2026-11-17T18:45:00Z",
           publish_at=None, title=None) -> dict:
    status = {"privacyStatus": privacy}
    if publish_at:
        status["publishAt"] = publish_at
    return {
        "id": vid,
        "snippet": {"title": title or f"t-{vid}", "description": "", "tags": [],
                    "categoryId": "22", "publishedAt": published},
        "statistics": {"viewCount": "0", "likeCount": "0", "commentCount": "0"},
        "contentDetails": {"duration": duration},
        "status": status,
    }


def _page(entries: list[tuple[str, str | None]]) -> dict:
    """An uploads-playlist page: (video id, the item's snippet.publishedAt)."""
    items = []
    for vid, added in entries:
        item = {"contentDetails": {"videoId": vid}}
        if added is not None:
            item["snippet"] = {"publishedAt": added, "resourceId": {"videoId": vid}}
        items.append(item)
    return {"items": items}


def _sb(*, sync_shorts=True, videos=(), uploads=()) -> FakeSupabase:
    return FakeSupabase({
        "channels": [{"id": CH, "default_language": "mr", "sync_shorts": sync_shorts}],
        "videos": [dict(v) for v in videos],
        "channel_uploads": [dict(u) for u in uploads],
    })


def _sync(sb, page: dict, items: list[dict], *, full=False, probe=False):
    with patch.object(sync, "supabase", return_value=sb), \
         patch.object(sync, "youtube_for_channel", return_value=MagicMock()), \
         patch.object(sync, "yt_channels_list_uploads",
                      return_value={"uploads_playlist_id": "UP", "default_language": None}), \
         patch.object(sync, "yt_playlist_items_page", return_value=page), \
         patch.object(sync, "yt_videos_list_full",
                      side_effect=lambda yt, cid, ids: [i for i in items if i["id"] in ids]), \
         patch.object(sync, "is_actually_short", return_value=probe) as probed:
        result = sync.sync_channel(CH, full=full)
    return result, probed


def _uploads(sb) -> dict[str, dict]:
    return {r["video_id"]: r for r in sb.rows("channel_uploads")}


def _video_ids(sb) -> set[str]:
    return {r["id"] for r in sb.rows("videos")}


# ── what lands where ─────────────────────────────────────────────────────

def test_a_scheduled_video_is_recorded_but_kept_out_of_videos():
    sb = _sb()
    _sync(sb, _page([("sched01", UPLOADED)]),
          [_video("sched01", privacy="private", publish_at=GO_LIVE)])

    row = _uploads(sb)["sched01"]
    assert row["channel_id"] == CH
    assert row["privacy_status"] == "private"
    assert _ts(row["scheduled_publish_at"]) == _ts(GO_LIVE)
    assert row["title"] == "t-sched01"
    assert row["thumbnail_url"] == "https://i.ytimg.com/vi/sched01/hqdefault.jpg"
    assert row["duration_seconds"] == 300
    assert "sched01" not in _video_ids(sb)


def test_an_opted_out_short_is_recorded_but_kept_out_of_videos():
    sb = _sb(sync_shorts=False)
    _sync(sb, _page([("short01", UPLOADED), ("long01", UPLOADED)]),
          [_video("short01", duration="PT45S"), _video("long01")], probe=True)

    uploads = _uploads(sb)
    assert uploads["short01"]["is_short"] is True
    assert uploads["long01"]["is_short"] is False
    assert _video_ids(sb) == {"long01"}


def test_a_public_video_lands_in_both():
    sb = _sb()
    result, _ = _sync(sb, _page([("pub01", UPLOADED)]), [_video("pub01")])
    assert result == {"synced": 1}
    assert "pub01" in _uploads(sb)
    assert _video_ids(sb) == {"pub01"}


# ── the upload time ──────────────────────────────────────────────────────

def test_uploaded_at_is_the_playlist_items_published_at():
    """Not the video's snippet.publishedAt, which moves at go-live (#143)."""
    sb = _sb()
    _sync(sb, _page([("sched01", UPLOADED)]),
          [_video("sched01", privacy="private", publish_at=GO_LIVE,
                  published="2026-11-18T09:00:00Z")])

    row = _uploads(sb)["sched01"]
    assert _ts(row["uploaded_at"]) == _ts(UPLOADED)
    assert _ts(row["playlist_published_at"]) == _ts(UPLOADED)
    assert _ts(row["video_published_at"]) == _ts("2026-11-18T09:00:00Z")
    assert row["first_seen_at"] and row["last_seen_at"]


def test_with_no_playlist_timestamp_uploaded_at_falls_back_to_first_seen():
    sb = _sb()
    _sync(sb, _page([("nots01", None)]), [_video("nots01")])
    row = _uploads(sb)["nots01"]
    assert row["playlist_published_at"] is None
    assert row["uploaded_at"] == row["first_seen_at"]


def test_going_live_updates_privacy_and_keeps_uploaded_at():
    sb = _sb()
    _sync(sb, _page([("sched01", UPLOADED)]),
          [_video("sched01", privacy="private", publish_at=GO_LIVE, title="draft")])
    first = _uploads(sb)["sched01"]

    # Later sync: the video went live. Even if YouTube now reports another
    # playlist timestamp, the recorded upload time stays.
    _sync(sb, _page([("sched01", "2026-11-20T04:30:00Z")]),
          [_video("sched01", privacy="public", title="final", published=GO_LIVE)])

    row = _uploads(sb)["sched01"]
    assert row["privacy_status"] == "public"
    assert row["scheduled_publish_at"] is None
    assert row["title"] == "final"
    assert _ts(row["video_published_at"]) == _ts(GO_LIVE)
    assert row["uploaded_at"] == first["uploaded_at"]
    assert row["playlist_published_at"] == first["playlist_published_at"]
    assert row["first_seen_at"] == first["first_seen_at"]
    assert "sched01" in _video_ids(sb)          # now public: the levers may see it


def test_no_write_to_an_existing_row_carries_uploaded_at():
    stored = {"video_id": "old01", "channel_id": CH, "title": "old", "is_short": False,
              "privacy_status": "private", "scheduled_publish_at": None,
              "thumbnail_url": "https://i.ytimg.com/vi/old01/hqdefault.jpg",
              "uploaded_at": "2026-10-01T00:00:00+00:00",
              "playlist_published_at": "2026-10-01T00:00:00+00:00",
              "video_published_at": "2026-10-01T00:00:00+00:00",
              "first_seen_at": "2026-10-01T01:00:00+00:00",
              "last_seen_at": "2026-10-01T01:00:00+00:00"}
    sb = _sb(uploads=[stored])
    _sync(sb, _page([("old01", "2026-11-01T00:00:00Z")]),
          [_video("old01", privacy="public")], full=True)

    writes = [(op, p) for t, op, p in sb.writes if t == "channel_uploads"]
    assert writes, "the existing row was not touched"
    for op, payload in writes:
        for row in (payload if isinstance(payload, list) else [payload]):
            if op == "update" or row.get("video_id") == "old01":
                assert "uploaded_at" not in row and "first_seen_at" not in row, (op, row)
    row = _uploads(sb)["old01"]
    assert row["uploaded_at"] == "2026-10-01T00:00:00+00:00"
    assert row["privacy_status"] == "public"
    assert row["last_seen_at"] != "2026-10-01T01:00:00+00:00"


# ── is_short re-checks ───────────────────────────────────────────────────

def _stored(vid: str, *, is_short, privacy) -> dict:
    return {"video_id": vid, "channel_id": CH, "title": vid, "is_short": is_short,
            "privacy_status": privacy, "uploaded_at": "2026-11-01T00:00:00+00:00",
            "first_seen_at": "2026-11-01T00:00:00+00:00",
            "last_seen_at": "2026-11-01T00:00:00+00:00"}


def test_a_known_public_short_is_not_probed_again():
    sb = _sb(sync_shorts=False, uploads=[_stored("short01", is_short=True, privacy="public")])
    _, probed = _sync(sb, _page([("short01", UPLOADED)]),
                      [_video("short01", duration="PT45S")], probe=False)
    assert probed.call_count == 0
    assert _uploads(sb)["short01"]["is_short"] is True
    assert _video_ids(sb) == set()


@pytest.mark.parametrize("is_short,privacy", [(False, "private"), (None, "public")])
def test_a_row_still_private_or_unclassified_is_probed_again(is_short, privacy):
    sb = _sb(sync_shorts=False, uploads=[_stored("vid01", is_short=is_short, privacy=privacy)])
    _, probed = _sync(sb, _page([("vid01", UPLOADED)]),
                      [_video("vid01", duration="PT45S")], probe=True)
    assert [c.args[0] for c in probed.call_args_list] == ["vid01"]
    assert _uploads(sb)["vid01"]["is_short"] is True
    assert _video_ids(sb) == set()               # an opted-out Short stays out


def test_re_checks_stay_inside_the_per_sync_probe_cap():
    stored = [_stored(f"p{i}", is_short=None, privacy="private") for i in range(3)]
    sb = _sb(sync_shorts=False, uploads=stored)
    with patch.object(sync, "MAX_SHORTS_PROBES_PER_SYNC", 2):
        _, probed = _sync(sb, _page([(f"p{i}", UPLOADED) for i in range(3)]),
                          [_video(f"p{i}", privacy="private", duration="PT45S") for i in range(3)],
                          probe=True)
    assert probed.call_count == 2


# ── isolation ────────────────────────────────────────────────────────────

class _BrokenUploads(FakeSupabase):
    def table(self, name):
        if name == "channel_uploads":
            raise RuntimeError("channel_uploads is down")
        return super().table(name)


def test_a_channel_uploads_failure_never_fails_the_sync(caplog):
    sb = _BrokenUploads({
        "channels": [{"id": CH, "default_language": "mr", "sync_shorts": True}],
        "videos": [],
    })
    result, _ = _sync(sb, _page([("pub01", UPLOADED), ("priv01", UPLOADED)]),
                      [_video("pub01"), _video("priv01", privacy="private")])
    assert result == {"synced": 1}
    assert _video_ids(sb) == {"pub01"}
    assert "channel_uploads is down" in caplog.text
    channel = sb.rows("channels")[0]
    assert channel.get("last_synced_at")         # the sync ran to the end


# ── unlisted → public (owner, 2026-11-20) ────────────────────────────────
#
# YouTube keeps snippet.publishedAt at the time an unlisted video went up, so
# the switch to public is stamped by whichever pass first sees it: public_at.

def _row(vid: str, *, privacy, uploaded="2026-11-12T07:58:49+00:00", **extra) -> dict:
    return {"video_id": vid, "channel_id": CH, "title": vid, "is_short": False,
            "privacy_status": privacy, "scheduled_publish_at": None,
            "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "duration_seconds": 300, "uploaded_at": uploaded,
            "playlist_published_at": uploaded, "video_published_at": uploaded,
            "public_at": None, "first_seen_at": uploaded, "last_seen_at": uploaded,
            **extra}


def _recheck(sb, items: list[dict]):
    asked: list[str] = []

    def videos_list(yt, cid, ids):
        asked.extend(ids)
        return [i for i in items if i["id"] in ids]

    with patch.object(sync, "supabase", return_value=sb), \
         patch.object(sync, "youtube_for_channel", return_value=MagicMock()), \
         patch.object(sync, "yt_videos_list_full", side_effect=videos_list):
        n = sync.recheck_uploads(CH)
    return n, asked


def _recent(days_ago: float) -> str:
    from datetime import timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_recheck_stamps_public_at_when_an_unlisted_video_goes_public():
    up = _recent(8)
    sb = _sb(uploads=[_row("unl01", privacy="unlisted", uploaded=up)])
    n, _ = _recheck(sb, [_video("unl01", privacy="public", published=up)])

    row = _uploads(sb)["unl01"]
    assert n == 1
    assert row["privacy_status"] == "public"
    assert row["public_at"] is not None
    assert _ts(row["public_at"]) > _ts(up)
    assert _ts(row["video_published_at"]) == _ts(up)     # YouTube's, unchanged
    assert row["uploaded_at"] == up


def test_recheck_reads_only_unsettled_recent_uploads_and_never_writes_videos():
    sb = _sb(uploads=[
        _row("pub01", privacy="public", uploaded=_recent(3)),
        _row("unl01", privacy="unlisted", uploaded=_recent(3)),
        _row("prv01", privacy="private", uploaded=_recent(3)),
        _row("sch01", privacy="private", uploaded=_recent(3),
             scheduled_publish_at=_recent(-1)),
        _row("old01", privacy="unlisted", uploaded=_recent(sync.RECHECK_DAYS + 5)),
    ])
    _, asked = _recheck(sb, [_video(v, privacy="unlisted") for v in ("unl01", "prv01", "sch01")])
    assert sorted(asked) == ["prv01", "sch01", "unl01"]
    assert not [w for w in sb.writes if w[0] == "videos"]


def test_recheck_with_nothing_unsettled_calls_no_youtube():
    sb = _sb(uploads=[_row("pub01", privacy="public", uploaded=_recent(3))])
    with patch.object(sync, "supabase", return_value=sb), \
         patch.object(sync, "youtube_for_channel") as yt:
        assert sync.recheck_uploads(CH) == 0
    yt.assert_not_called()


def test_a_private_video_made_public_gets_youtubes_time_not_a_stamp():
    up = _recent(5)
    published = _recent(1)                   # YouTube moves publishedAt for private → public
    sb = _sb(uploads=[_row("prv01", privacy="private", uploaded=up)])
    _recheck(sb, [_video("prv01", privacy="public", published=published)])

    row = _uploads(sb)["prv01"]
    assert row["public_at"] is None
    assert _ts(row["video_published_at"]) == _ts(published)


def test_public_at_is_stamped_once():
    """Public, back to unlisted, public again: the first go-live day stands."""
    first = "2026-11-14T06:00:00+00:00"
    up = _recent(8)
    sb = _sb(uploads=[_row("unl01", privacy="unlisted", uploaded=up, public_at=first)])
    _recheck(sb, [_video("unl01", privacy="public", published=up)])
    row = _uploads(sb)["unl01"]
    assert row["privacy_status"] == "public"
    assert row["public_at"] == first


def test_a_full_sync_stamps_the_switch_too():
    up = "2026-11-12T07:58:49Z"
    sb = _sb(uploads=[_row("unl01", privacy="unlisted", uploaded="2026-11-12T07:58:49+00:00")])
    _sync(sb, _page([("unl01", up)]), [_video("unl01", privacy="public", published=up)],
          full=True)
    assert _uploads(sb)["unl01"]["public_at"] is not None
