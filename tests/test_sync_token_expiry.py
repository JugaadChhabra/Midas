"""B8: an expired or revoked token, wherever it surfaces in a sync, is a 401
`token_expired` over HTTP and an expected skip in `video_sync`.

The 2026-10-01 tests mocked `TokenExpiredError` at the `routine_sync` boundary,
but the real route functions turn it into `HTTPException(401)`, so the skip
never happened and Hindi failed the run on 2026-10-06. These drive the REAL
`routine_sync` -> `sync_channel` / `refresh_stats` -> `yt_*` helpers; only the
YouTube client and the database are faked.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httplib2
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from app import main, quota, sync
from app.job_status import JobRunFailed
from tests.fakes import FakeSupabase


def _ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def _revoked() -> RefreshError:
    # What google-auth raises from inside `.execute()` when the API answers 401
    # and the refresh token has been revoked or has expired.
    return RefreshError(
        "invalid_grant: Token has been expired or revoked.",
        {"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
    )


def _http_error(status: int, reason: str = "boom") -> HttpError:
    return HttpError(httplib2.Response({"status": status}), reason.encode())


class _Request:
    def __init__(self, respond):
        self._respond = respond

    def execute(self):
        return self._respond()


class FakeYouTube:
    """The Data API client the yt_* helpers call. `fail` maps a resource name
    ("channels", "playlistItems", "videos") to the exception its `.execute()`
    raises; everything else answers from `uploads`, newest first."""

    def __init__(self, uploads: list[str], fail: dict[str, Exception] | None = None):
        self.uploads = uploads
        self.fail = fail or {}

    def _resource(self, name, respond):
        def _list(**kw):
            def _go():
                if name in self.fail:
                    raise self.fail[name]
                return respond(**kw)
            return _Request(_go)
        return type("R", (), {"list": staticmethod(_list)})()

    def channels(self):
        return self._resource("channels", lambda **kw: {"items": [{
            "contentDetails": {"relatedPlaylists": {"uploads": "UU"}},
            "snippet": {},
        }]})

    def playlistItems(self):
        return self._resource("playlistItems", lambda **kw: {
            "items": [{"contentDetails": {"videoId": v}} for v in self.uploads]})

    def videos(self):
        return self._resource("videos", lambda **kw: {"items": [{
            "id": v,
            "snippet": {"title": f"t-{v}", "tags": []},
            "statistics": {"viewCount": "7"},
            "contentDetails": {"duration": "PT5M"},
            "status": {"privacyStatus": "public"},
        } for v in kw["id"].split(",")]})


def _db(channels: list[dict], videos: list[dict] | None = None, **tables) -> FakeSupabase:
    return FakeSupabase({"channels": channels, "videos": videos or [], "quota_log": [], **tables})


def _patched(sb: FakeSupabase, clients: dict[str, FakeYouTube]):
    return [
        patch.object(sync, "supabase", return_value=sb),
        patch.object(quota, "supabase", return_value=sb),
        patch.object(sync, "youtube_for_channel", side_effect=lambda cid: clients[cid]),
    ]


def _enter(patches):
    for p in patches:
        p.start()


@pytest.fixture
def stop_patches():
    yield
    patch.stopall()


# ── HTTP: a token failure mid-call is 401, not 500 ───────────────────────────

def _client():
    return TestClient(main.app, raise_server_exceptions=False)


def test_refresh_stats_token_failure_mid_call_returns_401(stop_patches):
    sb = _db([{"id": "UC1"}], [{"id": "v1", "channel_id": "UC1"}])
    _enter(_patched(sb, {"UC1": FakeYouTube([], fail={"videos": _revoked()})}))

    r = _client().post("/channels/UC1/refresh-stats")

    assert r.status_code == 401
    assert r.json() == {"detail": "token_expired"}


def test_refresh_applied_stats_token_failure_mid_call_returns_401(stop_patches):
    sb = _db([{"id": "UC1"}], [{"id": "v1", "channel_id": "UC1"}],
             audits=[{"video_id": "v1", "status": "applied"}])
    _enter(_patched(sb, {"UC1": FakeYouTube([], fail={"videos": _revoked()})}))

    r = _client().post("/channels/UC1/refresh-applied-stats")

    assert r.status_code == 401
    assert r.json() == {"detail": "token_expired"}


@pytest.mark.parametrize("resource", ["channels", "playlistItems", "videos"])
def test_sync_token_failure_mid_call_returns_401(stop_patches, resource):
    sb = _db([{"id": "UC1"}])
    _enter(_patched(sb, {"UC1": FakeYouTube(["v1"], fail={resource: _revoked()})}))

    r = _client().post("/channels/UC1/sync")

    assert r.status_code == 401
    assert r.json() == {"detail": "token_expired"}


def test_a_youtube_401_that_is_not_a_token_failure_is_not_token_expired(stop_patches):
    sb = _db([{"id": "UC1"}], [{"id": "v1", "channel_id": "UC1"}])
    _enter(_patched(sb, {"UC1": FakeYouTube([], fail={"videos": _http_error(401)})}))

    with pytest.raises(HTTPException) as exc:
        sync.refresh_stats("UC1")
    assert exc.value.detail != "token_expired"


# ── video_sync: the expired channel is skipped, the rest still sync ──────────

def _run_video_sync(sb: FakeSupabase, channels: list[dict]):
    with patch.object(main.eligibility, "channels_for", return_value=channels):
        main._daily_video_sync()


def test_video_sync_skips_expired_tokens_and_syncs_the_rest(stop_patches):
    # Three channels, all stale: "full_expired" dies mid-sync on a full pass,
    # "stats_expired" syncs fine but dies mid-refresh_stats on an incremental
    # pass, and "ok" must still be synced after both.
    channels = [
        {"id": "full_expired", "last_synced_at": _ago(days=2), "last_full_synced_at": None},
        {"id": "stats_expired", "last_synced_at": _ago(days=2), "last_full_synced_at": _ago(days=1)},
        {"id": "ok", "last_synced_at": _ago(days=2), "last_full_synced_at": None},
    ]
    sb = _db([dict(c) for c in channels], [{"id": "s0", "channel_id": "stats_expired"}])
    stats_client = FakeYouTube(["s1", "s0"])
    clients = {
        "full_expired": FakeYouTube(["f1"], fail={"playlistItems": _revoked()}),
        "stats_expired": stats_client,
        "ok": FakeYouTube(["o1", "o2"]),
    }
    _enter(_patched(sb, clients))
    real_refresh = sync.refresh_stats

    def refresh_then_revoke(channel_id):
        # The token is revoked between sync_channel and refresh_stats.
        stats_client.fail["videos"] = _revoked()
        return real_refresh(channel_id)

    with patch.object(sync, "refresh_stats", side_effect=refresh_then_revoke) as rs:
        _run_video_sync(sb, channels)          # no JobRunFailed

    rs.assert_called_once_with("stats_expired")
    videos = {v["id"]: v["channel_id"] for v in sb.rows("videos")}
    assert videos["o1"] == "ok" and videos["o2"] == "ok"
    assert "f1" not in videos
    last_synced = {c["id"]: c["last_synced_at"] for c in sb.rows("channels")}
    assert last_synced["ok"] > channels[2]["last_synced_at"]
    assert last_synced["full_expired"] == channels[0]["last_synced_at"]


@pytest.mark.parametrize("error", [
    _http_error(500),
    _http_error(401),                                 # a 401 that is not a token failure
    RefreshError("invalid_client: The OAuth client was not found."),
], ids=["http-500", "http-401", "refresh-not-invalid-grant"])
def test_video_sync_still_fails_on_a_non_token_error(stop_patches, error):
    channels = [
        {"id": "bad", "last_synced_at": _ago(days=2), "last_full_synced_at": None},
        {"id": "ok", "last_synced_at": _ago(days=2), "last_full_synced_at": None},
    ]
    sb = _db([dict(c) for c in channels])
    _enter(_patched(sb, {"bad": FakeYouTube(["b1"], fail={"videos": error}),
                         "ok": FakeYouTube(["o1"])}))

    with pytest.raises(JobRunFailed) as exc:
        _run_video_sync(sb, channels)

    assert list(exc.value.failed_channels) == ["bad"]
    assert {v["id"] for v in sb.rows("videos")} == {"o1"}
