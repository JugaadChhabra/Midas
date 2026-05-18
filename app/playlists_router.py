from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import BaseModel

from app.db import supabase
from app.embeddings import bootstrap_embeddings
from app.openrouter import EMBED_MODEL
from app.playlists import reconcile_channel, _record_assignment
from app.playlists_sync import sync_playlists
from app.youtube_client import youtube_for_channel, yt_playlist_items_insert, yt_playlist_items_delete
from app.playlists import _current_members

router = APIRouter(tags=["playlists"])


@router.post("/channels/{channel_id}/playlists/bootstrap")
def bootstrap(channel_id: str):
    """Sync playlists from YouTube then embed all un-embedded videos.

    Run once per channel before auto-playlist allocation starts.
    """
    sync_result = sync_playlists(channel_id)
    embedded = bootstrap_embeddings(channel_id)
    return {**sync_result, "videos_embedded": embedded}


@router.get("/channels/{channel_id}/playlists/status")
def playlist_status(channel_id: str):
    """Embedding coverage and playlist assignment stats for a channel."""
    videos = (
        supabase().table("videos")
        .select("id")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    total_videos = len(videos)
    video_ids = [v["id"] for v in videos]

    embedded = 0
    if video_ids:
        embedded = len(
            (
                supabase().table("video_embeddings")
                .select("video_id")
                .in_("video_id", video_ids)
                .eq("chunk_index", "pooled")
                .eq("model_version", EMBED_MODEL)
                .execute()
            ).data or []
        )

    playlists = (
        supabase().table("playlists")
        .select("id,title")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []

    # Count videos currently in at least one playlist
    in_playlist: set[str] = set()
    for p in playlists:
        rows = (
            supabase().table("playlist_assignments")
            .select("video_id,action,decided_at")
            .eq("playlist_id", p["id"])
            .order("decided_at", desc=True)
            .execute()
        ).data or []
        seen: set[str] = set()
        for row in rows:
            if row["video_id"] not in seen:
                seen.add(row["video_id"])
                if row["action"] == "added":
                    in_playlist.add(row["video_id"])

    return {
        "total_videos": total_videos,
        "embedded": embedded,
        "playlists": len(playlists),
        "videos_in_playlists": len(in_playlist),
        "orphans": total_videos - len(in_playlist),
    }


@router.post("/channels/{channel_id}/playlists/reconcile")
def reconcile(channel_id: str):
    """Manually trigger a playlist reconcile for a channel."""
    return reconcile_channel(channel_id)


@router.get("/channels/{channel_id}/playlists/proposals")
def list_proposals(channel_id: str):
    """List pending playlist proposals for a channel."""
    playlist_ids = [
        p["id"] for p in (
            supabase().table("playlists").select("id").eq("channel_id", channel_id).execute()
        ).data or []
    ]
    if not playlist_ids:
        return []
    return (
        supabase().table("playlist_proposals")
        .select("*")
        .in_("playlist_id", playlist_ids)
        .eq("status", "pending")
        .order("proposed_at", desc=False)
        .execute()
    ).data or []


class DecideBody(BaseModel):
    ids: list[int]
    decision: str  # 'approved' | 'rejected'


@router.post("/channels/{channel_id}/playlists/proposals/decide")
def decide_proposals(channel_id: str, body: DecideBody):
    """Approve or reject a list of proposal IDs. Approved adds/removes execute immediately."""
    if body.decision not in ("approved", "rejected"):
        from fastapi import HTTPException
        raise HTTPException(400, "decision must be 'approved' or 'rejected'")

    now = datetime.now(timezone.utc).isoformat()
    executed = rejected = 0

    if body.decision == "rejected":
        supabase().table("playlist_proposals").update(
            {"status": "rejected", "decided_at": now}
        ).in_("id", body.ids).execute()
        return {"executed": 0, "rejected": len(body.ids)}

    proposals = (
        supabase().table("playlist_proposals")
        .select("*")
        .in_("id", body.ids)
        .eq("status", "pending")
        .execute()
    ).data or []

    yt_clients: dict[str, object] = {}

    for p in proposals:
        playlist_id = p["playlist_id"]
        video_id = p["video_id"]

        # Get YouTube client for this playlist's channel
        playlist_row = supabase().table("playlists").select("channel_id").eq("id", playlist_id).single().execute().data
        if not playlist_row:
            continue
        ch = playlist_row["channel_id"]
        if ch not in yt_clients:
            yt_clients[ch] = youtube_for_channel(ch)
        yt = yt_clients[ch]

        try:
            if p["action"] == "add":
                item_id = yt_playlist_items_insert(yt, ch, playlist_id, video_id)
                _record_assignment(video_id, playlist_id, item_id, "added", p.get("similarity"), p["decision_source"])
            else:
                members = _current_members(playlist_id)
                playlist_item_id = members.get(video_id)
                if playlist_item_id:
                    yt_playlist_items_delete(yt, ch, playlist_item_id)
                    _record_assignment(video_id, playlist_id, None, "removed", p.get("similarity"), p["decision_source"])

            supabase().table("playlist_proposals").update(
                {"status": "approved", "decided_at": now}
            ).eq("id", p["id"]).execute()
            executed += 1
        except Exception as e:
            import logging
            logging.getLogger("midas.playlists").warning("Failed to execute proposal %s: %s", p["id"], e)

    return {"executed": executed, "rejected": rejected}
