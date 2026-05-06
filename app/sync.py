import re
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone

from app.db import supabase
from app.youtube_client import (
    youtube_for_channel,
    yt_channels_list_uploads,
    yt_playlist_items_page,
    yt_videos_list_full,
    yt_videos_list_stats,
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
            privacy = (item.get("status") or {}).get("privacyStatus")
            if privacy != "public":
                continue  # skip unlisted / private
            sn = item["snippet"]
            stats = item.get("statistics", {})
            # Use the stable URL pattern (no expiring signed token).
            # hqdefault is guaranteed to exist for every video; maxresdefault may not.
            stable_thumb = f"https://i.ytimg.com/vi/{item['id']}/hqdefault.jpg"
            rows.append({
                "id": item["id"],
                "channel_id": channel_id,
                "title": sn.get("title"),
                "description": sn.get("description"),
                "tags": sn.get("tags") or [],
                "thumbnail_url": stable_thumb,
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


@router.post("/channels/{channel_id}/refresh-applied-stats")
def refresh_applied_stats(channel_id: str):
    """Refresh stats only for videos with applied audits. Cheap: 1 quota unit per 50 videos."""
    # Find video ids in this channel that have an applied audit
    vids = (
        supabase().table("videos").select("id").eq("channel_id", channel_id).execute().data or []
    )
    channel_video_ids = {v["id"] for v in vids}
    if not channel_video_ids:
        return {"refreshed": 0}
    applied = (
        supabase().table("audits").select("video_id").eq("status", "applied")
        .in_("video_id", list(channel_video_ids)).execute().data or []
    )
    target_ids = list({a["video_id"] for a in applied})
    if not target_ids:
        return {"refreshed": 0}

    yt = youtube_for_channel(channel_id)
    refreshed = 0
    now = datetime.now(timezone.utc).isoformat()
    for i in range(0, len(target_ids), 50):
        batch = target_ids[i:i+50]
        items = yt_videos_list_stats(yt, channel_id, batch)
        for item in items:
            stats = item.get("statistics", {})
            supabase().table("videos").update({
                "view_count": int(stats.get("viewCount") or 0),
                "like_count": int(stats.get("likeCount") or 0),
                "comment_count": int(stats.get("commentCount") or 0),
                "last_fetched_at": now,
            }).eq("id", item["id"]).execute()
            refreshed += 1
    return {"refreshed": refreshed}


@router.get("/channels/{channel_id}/videos")
def list_videos(channel_id: str):
    videos = (
        supabase().table("videos")
        .select("id,title,description,tags,view_count,like_count,published_at,thumbnail_url")
        .eq("channel_id", channel_id)
        .order("published_at", desc=True)
        .execute()
    ).data or []

    if not videos:
        return []

    # Latest audit per video (status + applied_at) so the UI can show a state pill.
    video_ids = [v["id"] for v in videos]
    audits = (
        supabase().table("audits")
        .select("video_id,status,applied_at,created_at")
        .in_("video_id", video_ids)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    latest: dict[str, dict] = {}
    for a in audits:
        if a["video_id"] not in latest:
            latest[a["video_id"]] = a

    for v in videos:
        a = latest.get(v["id"])
        v["audit_status"] = a["status"] if a else None
        v["audit_applied_at"] = a.get("applied_at") if a else None

    return videos
