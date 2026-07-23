from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from datetime import datetime, timezone

from app.config import settings
from app.db import supabase
from app.shorts.nas_source import list_source_languages

router = APIRouter(prefix="/auth", tags=["auth"])


def _flow() -> Flow:
    return Flow.from_client_secrets_file(
        settings.CLIENT_SECRETS_FILE,
        scopes=settings.SCOPES,
        redirect_uri=settings.OAUTH_REDIRECT_URI,
    )


@router.get("/login")
def login():
    flow = _flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # forces refresh_token to be returned every time during dev
    )
    return RedirectResponse(auth_url)


@router.get("/callback")
def callback(request: Request, code: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    flow = _flow()
    flow.fetch_token(code=code)
    creds = flow.credentials

    # Whether Google's token response actually granted the analytics scope.
    # If the user re-consented but unchecked the analytics box, we won't see it
    # and Loop 0 polling will skip this channel until they reconnect again.
    granted_scopes = set(getattr(creds, "granted_scopes", None) or [])
    analytics_authorized = settings.ANALYTICS_SCOPE in granted_scopes

    if not creds.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="No refresh_token returned. Revoke app access at "
                   "https://myaccount.google.com/permissions and retry.",
        )

    # Fetch the channel for the authenticated user so we know which row to upsert.
    youtube = build("youtube", "v3", credentials=creds)
    resp = youtube.channels().list(part="snippet", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise HTTPException(status_code=400, detail="No YouTube channel found on this Google account.")

    channel = items[0]
    channel_id = channel["id"]
    snippet = channel["snippet"]

    expiry = creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None

    payload = {
        "id": channel_id,
        "name": snippet.get("title"),
        "handle": snippet.get("customUrl"),
        "refresh_token": creds.refresh_token,
        "access_token": creds.token,
        "token_expiry": expiry,
        "analytics_authorized": analytics_authorized,
    }
    # Seed default_language from YouTube on first connect. Subsequent reconnects
    # don't overwrite it — the user may have manually overridden it via PATCH.
    existing = (
        supabase().table("channels").select("default_language").eq("id", channel_id)
        .execute().data or []
    )
    has_lang = bool(existing and existing[0].get("default_language"))
    if not has_lang and snippet.get("defaultLanguage"):
        payload["default_language"] = snippet.get("defaultLanguage")

    supabase().table("channels").upsert(payload).execute()

    # If autopilot was paused because the token expired, clear the pause now
    # that we have fresh credentials.
    existing_pause = (
        supabase().table("channels")
        .select("autopilot_paused_reason")
        .eq("id", channel_id)
        .single()
        .execute()
        .data or {}
    ).get("autopilot_paused_reason")
    if existing_pause == "token_expired":
        supabase().table("channels").update({"autopilot_paused_reason": None}).eq("id", channel_id).execute()

    return RedirectResponse(f"/channel?id={channel_id}")


@router.get("/channels")
def list_channels():
    res = supabase().table("channels").select(
        "id,name,handle,last_synced_at,default_language,"
        "autopilot_enabled,autopilot_paused_reason,autopilot_daily_cap,autopilot_last_tick_at,"
        "sync_shorts,analytics_authorized,playlist_health_enabled,"
        "autopilot_shorts_enabled,"
        "shorts_cut_mode,shorts_camera_motion,nas_folder"
    ).execute()
    return res.data


class ChannelSettings(BaseModel):
    default_language: str | None = None
    autopilot_enabled: bool | None = None
    autopilot_daily_cap: int | None = None
    sync_shorts: bool | None = None
    playlist_health_enabled: bool | None = None
    autopilot_shorts_enabled: bool | None = None
    shorts_cut_mode: str | None = None
    shorts_camera_motion: str | None = None
    nas_folder: str | None = None


@router.patch("/channels/{channel_id}")
def update_channel(channel_id: str, body: ChannelSettings):
    patch: dict = {}
    if body.default_language is not None:
        patch["default_language"] = body.default_language or None
    if body.autopilot_enabled is not None:
        patch["autopilot_enabled"] = body.autopilot_enabled
    if body.autopilot_daily_cap is not None:
        patch["autopilot_daily_cap"] = max(1, min(int(body.autopilot_daily_cap), 200))
    if body.sync_shorts is not None:
        patch["sync_shorts"] = body.sync_shorts
    if body.playlist_health_enabled is not None:
        # Phase 1B per-channel rollout gate. Operators flip this per
        # channel as they widen the recommend-only health-scoring loop;
        # the playlist_health_score cron skips channels where it's false.
        patch["playlist_health_enabled"] = body.playlist_health_enabled
    if body.autopilot_shorts_enabled is not None:
        patch["autopilot_shorts_enabled"] = body.autopilot_shorts_enabled
    if body.shorts_cut_mode in ("highlights", "coverage"):
        patch["shorts_cut_mode"] = body.shorts_cut_mode
    if body.shorts_camera_motion in ("locked", "calm", "follow"):
        patch["shorts_camera_motion"] = body.shorts_camera_motion
    if body.nas_folder is not None:
        folder = body.nas_folder.strip().upper()
        if folder and folder not in list_source_languages():
            raise HTTPException(400, f"Unknown NAS folder: {folder}")
        patch["nas_folder"] = folder or None
    if not patch:
        return {"ok": True, "noop": True}
    supabase().table("channels").update(patch).eq("id", channel_id).execute()
    return {"ok": True}
