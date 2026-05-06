from datetime import datetime, timezone
from fastapi import APIRouter

from app.db import supabase

router = APIRouter(tags=["performance"])


def _days_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 86400.0, 2)


@router.get("/channels/{channel_id}/performance")
def channel_performance(channel_id: str):
    # Pull applied audits for this channel's videos.
    audits = (
        supabase().table("audits")
        .select("id,video_id,applied_at,status,"
                "suggested_title,suggested_description,suggested_tags,"
                "title_before,description_before,tags_before,"
                "view_count_at_apply,like_count_at_apply,comment_count_at_apply")
        .eq("status", "applied")
        .order("applied_at", desc=True)
        .execute()
    ).data or []

    if not audits:
        return []

    video_ids = list({a["video_id"] for a in audits})
    videos_by_id: dict[str, dict] = {}
    # Supabase Python client supports `.in_` for filtering.
    vids = (
        supabase().table("videos")
        .select("id,channel_id,title,thumbnail_url,view_count,like_count,comment_count,last_fetched_at")
        .in_("id", video_ids)
        .execute()
    ).data or []
    for v in vids:
        videos_by_id[v["id"]] = v

    rows = []
    for a in audits:
        v = videos_by_id.get(a["video_id"])
        if not v or v.get("channel_id") != channel_id:
            continue
        view_now = v.get("view_count") or 0
        like_now = v.get("like_count") or 0
        comment_now = v.get("comment_count") or 0
        view_at = a.get("view_count_at_apply") or 0
        like_at = a.get("like_count_at_apply") or 0
        comment_at = a.get("comment_count_at_apply") or 0
        rows.append({
            "audit_id": a["id"],
            "video_id": a["video_id"],
            "title_now": v.get("title"),
            "thumbnail_url": v.get("thumbnail_url"),
            "applied_at": a.get("applied_at"),
            "days_since_apply": _days_since(a.get("applied_at")),
            "title_before": a.get("title_before"),
            "title_after": a.get("suggested_title"),
            "description_before": a.get("description_before"),
            "description_after": a.get("suggested_description"),
            "tags_before": a.get("tags_before") or [],
            "tags_after": a.get("suggested_tags") or [],
            "view_count_at_apply": view_at,
            "like_count_at_apply": like_at,
            "comment_count_at_apply": comment_at,
            "view_count_now": view_now,
            "like_count_now": like_now,
            "comment_count_now": comment_now,
            "delta_views": view_now - view_at,
            "delta_likes": like_now - like_at,
            "delta_comments": comment_now - comment_at,
            "stats_last_fetched": v.get("last_fetched_at"),
        })
    return rows
