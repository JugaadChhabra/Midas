from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from datetime import datetime, timezone

from app.config import settings
from app.db import supabase

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

    supabase().table("channels").upsert({
        "id": channel_id,
        "name": snippet.get("title"),
        "handle": snippet.get("customUrl"),
        "refresh_token": creds.refresh_token,
        "access_token": creds.token,
        "token_expiry": expiry,
    }).execute()

    return HTMLResponse(
        f"<h2>Connected ✓</h2>"
        f"<p>Channel: <b>{snippet.get('title')}</b> ({channel_id})</p>"
        f"<p>Refresh token stored in Supabase. You can close this tab.</p>"
        f"<p><a href='/'>Back to dashboard</a></p>"
    )


@router.get("/channels")
def list_channels():
    res = supabase().table("channels").select("id,name,handle,last_synced_at").execute()
    return res.data
