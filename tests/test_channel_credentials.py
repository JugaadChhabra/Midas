"""A channel's stored access token is used only until its stored expiry.

Before 2026-10-08 the creds were built without `expiry`, so google-auth called
a months-old token valid, never refreshed it up front, and never saved a new
one: every call relied on the API client's 401-retry. That retry began failing
(video_sync, 6 channels, 2026-10-08).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from google.auth.exceptions import RefreshError

from app import youtube_client
from app.youtube_client import TokenExpiredError, channel_credentials
from tests.fakes import FakeSupabase

_SECRETS = {"token_uri": "https://oauth2.example/token", "client_id": "cid", "client_secret": "cs"}
NEW_EXPIRY = datetime(2026, 10, 8, 13, 0, 0)  # naive UTC, as google-auth sets it


def _row(token_expiry):
    return {"id": "UC1", "access_token": "old-token", "refresh_token": "rt",
            "token_expiry": token_expiry}


def _fake_refresh(self, request):
    self.token = "new-token"
    self.expiry = NEW_EXPIRY


def _run(row, refresh=_fake_refresh):
    db = FakeSupabase({"channels": [row]})
    with patch.object(youtube_client, "supabase", return_value=db), \
         patch.object(youtube_client, "_client_secrets", return_value=_SECRETS), \
         patch("google.oauth2.credentials.Credentials.refresh", autospec=True,
               side_effect=refresh) as refreshed:
        creds = channel_credentials("UC1", row)
    return creds, refreshed, db


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_expired_stored_token_is_refreshed_before_use_and_saved():
    # Office state on 2026-10-08: token_expiry months in the past.
    creds, refreshed, db = _run(_row("2026-07-02T13:03:14+00:00"))

    assert refreshed.call_count == 1
    assert creds.token == "new-token"
    assert db.writes == [("channels", "update", {
        "access_token": "new-token",
        "token_expiry": NEW_EXPIRY.replace(tzinfo=timezone.utc).isoformat(),
    })]


def test_unexpired_stored_token_is_used_without_refresh():
    later = datetime.now(timezone.utc) + timedelta(minutes=30)
    creds, refreshed, db = _run(_row(_iso(later)))

    assert refreshed.call_count == 0
    assert creds.token == "old-token"
    assert db.writes == []


@pytest.mark.parametrize("stored", [None, ""])
def test_missing_expiry_counts_as_expired(stored):
    creds, refreshed, _ = _run(_row(stored))

    assert refreshed.call_count == 1
    assert creds.token == "new-token"


def test_expiry_is_naive_utc_whatever_offset_postgrest_returns():
    # +05:30 and Z spell the same instant as +00:00.
    for raw in ("2026-07-02T18:33:14+05:30", "2026-07-02T13:03:14Z", "2026-07-02T13:03:14.123+00:00"):
        got = youtube_client._stored_expiry({"token_expiry": raw})
        assert got.tzinfo is None
        assert got.replace(microsecond=0) == datetime(2026, 7, 2, 13, 3, 14)


def test_revoked_refresh_token_is_token_expired():
    def revoked(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    with pytest.raises(TokenExpiredError):
        _run(_row("2026-07-02T13:03:14+00:00"), refresh=revoked)
