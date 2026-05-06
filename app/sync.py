import re
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone

from app.db import supabase
from app.youtube_client import (
    youtube_for_channel,
    yt_channels_list_uploads,
    yt_playlist_items_page,
    yt_videos_list_full,
)

SHORTS_MAX_SECONDS = 180  # YouTube Shorts are <= 3 minutes


def _iso8601_to_seconds(d: str) -> int:
    if not d:
        return 0
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d)
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s

router = APIRouter(tags=["sync"])


@router.post("/channels/{channel_id}/sync")
def sync_channel(channel_id: str):
    yt = youtube_for_channel(channel_id)

    uploads_playlist = yt_channels_list_uploads(yt, channel_id)
    if not uploads_playlist:
        raise HTTPException(404, "Channel not found on YouTube")

    video_ids: list[str] = []
    page_token: str | None = None
    while True:
        resp = yt_playlist_items_page(yt, channel_id, uploads_playlist, page_token)
        video_ids.extend(item["contentDetails"]["videoId"] for item in resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    rows: list[dict] = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        items = yt_videos_list_full(yt, channel_id, batch)
        for item in items:
            duration = (item.get("contentDetails") or {}).get("duration", "")
            if _iso8601_to_seconds(duration) <= SHORTS_MAX_SECONDS:
                continue  # skip shorts
            sn = item["snippet"]
            stats = item.get("statistics", {})
            thumbs = sn.get("thumbnails", {})
            best = thumbs.get("maxres") or thumbs.get("high") or thumbs.get("default") or {}
            rows.append({
                "id": item["id"],
                "channel_id": channel_id,
                "title": sn.get("title"),
                "description": sn.get("description"),
                "tags": sn.get("tags") or [],
                "thumbnail_url": best.get("url"),
                "category_id": sn.get("categoryId"),
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "published_at": sn.get("publishedAt"),
                "last_fetched_at": datetime.now(timezone.utc).isoformat(),
            })

    if rows:
        deduped = list({r["id"]: r for r in rows}.values())
        supabase().table("videos").upsert(deduped).execute()

    supabase().table("channels").update({
        "last_synced_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", channel_id).execute()

    return {"synced": len(rows)}


@router.get("/channels/{channel_id}/videos")
def list_videos(channel_id: str):
    res = (
        supabase().table("videos")
        .select("id,title,description,tags,view_count,like_count,published_at,thumbnail_url")
        .eq("channel_id", channel_id)
        .order("published_at", desc=True)
        .execute()
    )
    return res.data
