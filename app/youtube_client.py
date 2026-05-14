from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
import json

from app.config import settings
from app.db import supabase


class TokenExpiredError(Exception):
    """Raised when the OAuth refresh token is revoked or expired."""


def _client_secrets() -> dict:
    with open(settings.CLIENT_SECRETS_FILE) as f:
        return json.load(f)["web"]


def youtube_for_channel(channel_id: str):
    row = supabase().table("channels").select("*").eq("id", channel_id).single().execute().data
    if not row:
        raise ValueError(f"Channel {channel_id} not found")

    secrets = _client_secrets()
    creds = Credentials(
        token=row.get("access_token"),
        refresh_token=row["refresh_token"],
        token_uri=secrets["token_uri"],
        client_id=secrets["client_id"],
        client_secret=secrets["client_secret"],
        scopes=settings.SCOPES,
    )

    if not creds.valid:
        try:
            creds.refresh(GoogleRequest())
        except RefreshError as e:
            if "invalid_grant" in str(e):
                raise TokenExpiredError(channel_id) from e
            raise
        supabase().table("channels").update({
            "access_token": creds.token,
            "token_expiry": creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None,
        }).eq("id", channel_id).execute()

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# ── Quota-logged YouTube call helpers ────────────────────────────────────
# Each helper executes the API call and writes a quota_log row regardless of success.

def _log_quota(channel_id: str | None, operation: str, units: int, success: bool):
    try:
        supabase().table("quota_log").insert({
            "channel_id": channel_id,
            "operation": operation,
            "units": units,
            "success": success,
        }).execute()
    except Exception:
        pass


def _guard_token(e: Exception, channel_id: str | None) -> None:
    """Re-raise as TokenExpiredError if the exception is an invalid_grant."""
    if "invalid_grant" in str(e):
        raise TokenExpiredError(channel_id) from e


def yt_channels_list_uploads(yt, channel_id: str) -> dict | None:
    """Return uploads playlist id and snippet metadata. Cost: 1."""
    success = False
    try:
        resp = yt.channels().list(part="contentDetails,snippet", id=channel_id).execute()
        success = True
        items = resp.get("items", [])
        if not items:
            return None
        item = items[0]
        return {
            "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
            "default_language": (item.get("snippet") or {}).get("defaultLanguage"),
        }
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "channels.list", 1, success)


def yt_playlist_items_page(yt, channel_id: str, playlist_id: str, page_token: str | None) -> dict:
    """One page of playlistItems. Cost: 1."""
    success = False
    try:
        resp = yt.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        success = True
        return resp
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "playlistItems.list", 1, success)


def yt_videos_list_full(yt, channel_id: str | None, ids: list[str]) -> list[dict]:
    """Full snippet+statistics+contentDetails+status for up to 50 videos. Cost: 1."""
    success = False
    try:
        resp = yt.videos().list(part="snippet,statistics,contentDetails,status", id=",".join(ids)).execute()
        success = True
        return resp.get("items", [])
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "videos.list", 1, success)


def yt_videos_list_stats(yt, channel_id: str | None, ids: list[str]) -> list[dict]:
    """Statistics only. Cost: 1."""
    success = False
    try:
        resp = yt.videos().list(part="statistics", id=",".join(ids)).execute()
        success = True
        return resp.get("items", [])
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "videos.list", 1, success)


def yt_captions_list(yt, channel_id: str | None, video_id: str) -> list[dict]:
    """List caption tracks for a video. Cost: 50."""
    success = False
    try:
        resp = yt.captions().list(part="snippet", videoId=video_id).execute()
        success = True
        return resp.get("items", [])
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "captions.list", 50, success)


def yt_captions_download(yt, channel_id: str | None, caption_id: str) -> bytes:
    """Download a caption track in VTT format. Cost: 200."""
    success = False
    try:
        data = yt.captions().download(id=caption_id, tfmt="vtt").execute()
        success = True
        return data if isinstance(data, bytes) else data.encode()
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "captions.download", 200, success)


def yt_videos_update(yt, channel_id: str | None, payload: dict, parts: str = "snippet,status") -> dict:
    """Update a video. Cost: 50."""
    success = False
    try:
        resp = yt.videos().update(part=parts, body=payload).execute()
        success = True
        return resp
    except Exception as e:
        _guard_token(e, channel_id)
        raise
    finally:
        _log_quota(channel_id, "videos.update", 50, success)
