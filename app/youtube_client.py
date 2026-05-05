from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
import json

from app.config import settings
from app.db import supabase


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
        creds.refresh(GoogleRequest())
        supabase().table("channels").update({
            "access_token": creds.token,
            "token_expiry": creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None,
        }).eq("id", channel_id).execute()

    return build("youtube", "v3", credentials=creds, cache_discovery=False)
