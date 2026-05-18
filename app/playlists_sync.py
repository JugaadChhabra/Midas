"""Sync YouTube playlists and their membership into the local DB.

Called once at bootstrap and then daily to stay in sync with manual changes
made directly in YouTube Studio.
"""
import logging
from datetime import datetime, timezone

from app.db import supabase
from app.youtube_client import youtube_for_channel, yt_playlists_list, yt_playlist_items_page

log = logging.getLogger("midas.playlists_sync")


def sync_playlists(channel_id: str) -> dict:
    """Fetch all playlists + their members from YouTube and seed the local tables.

    Existing rows are upserted (title/description may have changed). Membership
    rows are only inserted for (video_id, playlist_id) pairs not already present
    in playlist_assignments — we never overwrite system-generated decisions.

    Returns {"playlists": int, "memberships_seeded": int}.
    """
    yt = youtube_for_channel(channel_id)

    # 1. Fetch all playlists for the channel
    yt_playlists = yt_playlists_list(yt, channel_id)
    if not yt_playlists:
        log.info("No playlists found for channel %s", channel_id)
        return {"playlists": 0, "memberships_seeded": 0}

    now = datetime.now(timezone.utc).isoformat()

    # Upsert playlist rows
    supabase().table("playlists").upsert(
        [
            {
                "id": p["id"],
                "channel_id": channel_id,
                "title": p["title"],
                "description": p["description"],
                "synced_at": now,
            }
            for p in yt_playlists
        ],
        on_conflict="id",
    ).execute()
    log.info("Synced %d playlists for channel %s", len(yt_playlists), channel_id)

    # 2. For each playlist, fetch members and seed playlist_assignments
    # Load all video IDs we know about so we can skip orphaned YouTube videos
    known_videos = {
        v["id"]
        for v in (
            supabase().table("videos")
            .select("id")
            .eq("channel_id", channel_id)
            .execute()
        ).data or []
    }

    # Load existing (video_id, playlist_id) pairs for these playlists only
    # to avoid duplicate sync rows
    playlist_ids = [p["id"] for p in yt_playlists]
    existing_pairs = {
        (r["video_id"], r["playlist_id"])
        for r in (
            supabase().table("playlist_assignments")
            .select("video_id,playlist_id")
            .in_("playlist_id", playlist_ids)
            .execute()
        ).data or []
    }

    memberships_seeded = 0
    for playlist in yt_playlists:
        playlist_id = playlist["id"]
        page_token = None
        while True:
            resp = yt_playlist_items_page(yt, channel_id, playlist_id, page_token)
            for item in resp.get("items", []):
                playlist_item_id = item["id"]
                video_id = item["contentDetails"]["videoId"]

                if video_id not in known_videos:
                    continue  # video not in our DB yet
                if (video_id, playlist_id) in existing_pairs:
                    continue  # already tracked

                supabase().table("playlist_assignments").insert({
                    "video_id": video_id,
                    "playlist_id": playlist_id,
                    "playlist_item_id": playlist_item_id,
                    "action": "added",
                    "decision_source": "sync",
                    "decided_at": now,
                }).execute()
                existing_pairs.add((video_id, playlist_id))
                memberships_seeded += 1

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    log.info(
        "sync_playlists(%s): seeded %d membership rows",
        channel_id, memberships_seeded,
    )
    return {"playlists": len(yt_playlists), "memberships_seeded": memberships_seeded}
