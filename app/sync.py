import logging
import re
import httpx
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
from googleapiclient.errors import HttpError

from app.db import supabase
from app.youtube_client import (
    TokenExpiredError,
    youtube_for_channel,
    yt_channels_list_uploads,
    yt_playlist_items_page,
    yt_videos_list_full,
    yt_videos_list_stats,
)

SHORTS_MAX_SECONDS = 180  # YouTube Shorts are <= 3 minutes

# Cap on Shorts-URL probes per sync run. A brand-new channel's first sync can
# have thousands of new sub-3-min videos; probing all of them sequentially adds
# huge latency and risks YouTube throttling the caller's IP. We probe the newest
# N new videos (playlist is newest-first) and duration-label the rest — a later
# scripts/backfill_is_short.py run corrects the remainder in a throttled pass.
# Incremental syncs only ever have a handful of new videos, so this never bites
# them; it only bounds the first bulk sync of a large channel.
MAX_SHORTS_PROBES_PER_SYNC = 300

# A desktop UA — the /shorts/ endpoint 30x-redirects real Shorts to /watch for
# some mobile UAs, which would break the probe below.
_SHORTS_PROBE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def is_actually_short(video_id: str, duration_seconds: int | None) -> bool:
    """Whether `video_id` was actually posted as a YouTube Short.

    The Data API v3 exposes no Shorts flag, so we probe the Shorts watch URL:
    ``youtube.com/shorts/<id>`` serves HTTP 200 for a genuine Short and
    30x-redirects to ``/watch`` for a regular video (even a short-duration one).
    A duration-only heuristic mislabels every sub-3-min landscape upload as a
    Short, so the probe is the source of truth for the ambiguous band.

    Videos longer than the Shorts max length can never be Shorts, so we skip
    the network probe entirely for them. On any network error we fall back to
    the duration heuristic so a sync is never blocked by this best-effort check.
    """
    if duration_seconds is None or duration_seconds > SHORTS_MAX_SECONDS:
        return False
    try:
        resp = httpx.get(
            f"https://www.youtube.com/shorts/{video_id}",
            follow_redirects=False,
            timeout=10.0,
            headers={"User-Agent": _SHORTS_PROBE_UA},
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        return duration_seconds <= SHORTS_MAX_SECONDS


def _iso8601_to_seconds(d: str) -> int:
    if not d:
        return 0
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d)
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s

log = logging.getLogger("midas.sync")
router = APIRouter(tags=["sync"])


@router.post("/channels/{channel_id}/sync")
def sync_channel(channel_id: str, full: bool = False):
    """Sync a channel's videos.

    Incremental by default: the uploads playlist is returned newest-first, so we
    page until we hit a video already in the DB and only fetch full metadata for
    the genuinely new ids. This drops a typical resync from ~1+2*ceil(N/50) quota
    units (full re-list of every video) to a handful.

    Pass ``full=True`` for a backfill / first sync or to repair stale metadata —
    it re-fetches every video's snippet so edits to old titles/tags/privacy are
    picked up. Routine privacy-flip detection is handled more cheaply by
    ``refresh_stats`` (statistics+status), so a full sync is only needed
    occasionally.
    """
    try:
        yt = youtube_for_channel(channel_id)
    except TokenExpiredError:
        raise HTTPException(401, "token_expired")

    # Read channel settings first so we know whether to include Shorts.
    # sync_shorts defaults to True (None = not set yet = include Shorts).
    channel_settings = (
        supabase().table("channels").select("default_language,sync_shorts").eq("id", channel_id)
        .single().execute().data or {}
    )
    sync_shorts: bool = channel_settings.get("sync_shorts") is not False

    # Load the ids we already have, plus their stored is_short. is_short never
    # changes for a video, so we reuse the stored value and only probe genuinely
    # new ids (see is_actually_short) — an incremental sync also uses these ids
    # to stop paginating early once it reaches known videos.
    existing_rows = (
        supabase().table("videos").select("id,is_short").eq("channel_id", channel_id).execute().data or []
    )
    existing_is_short: dict[str, bool | None] = {r["id"]: r.get("is_short") for r in existing_rows}
    known_ids: set[str] = set(existing_is_short) if not full else set()

    try:
        channel_meta = yt_channels_list_uploads(yt, channel_id)
    except TokenExpiredError:
        raise HTTPException(401, "token_expired")
    except HttpError as e:
        if e.status_code == 403 and "quotaExceeded" in str(e):
            raise HTTPException(429, "youtube_quota_exceeded")
        raise HTTPException(502, f"YouTube API error: {e}")
    if not channel_meta:
        raise HTTPException(404, "Channel not found on YouTube")
    uploads_playlist = channel_meta["uploads_playlist_id"]

    video_ids: list[str] = []
    page_token: str | None = None
    reached_known = False
    try:
        while not reached_known:
            resp = yt_playlist_items_page(yt, channel_id, uploads_playlist, page_token)
            for item in resp.get("items", []):
                vid = item["contentDetails"]["videoId"]
                if not full and vid in known_ids:
                    # Newest-first ordering: everything past this point is already
                    # stored, so stop walking the playlist entirely.
                    reached_known = True
                    break
                video_ids.append(vid)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    except TokenExpiredError:
        raise HTTPException(401, "token_expired")
    except HttpError as e:
        if e.status_code == 403 and "quotaExceeded" in str(e):
            raise HTTPException(429, "youtube_quota_exceeded")
        raise HTTPException(502, f"YouTube API error: {e}")

    rows: list[dict] = []
    privacy_changed_to_private: list[str] = []
    probes_used = 0            # bounded per sync — see MAX_SHORTS_PROBES_PER_SYNC
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        try:
            items = yt_videos_list_full(yt, channel_id, batch)
        except TokenExpiredError:
            raise HTTPException(401, "token_expired")
        except HttpError as e:
            if e.status_code == 403 and "quotaExceeded" in str(e):
                raise HTTPException(429, "youtube_quota_exceeded")
            raise HTTPException(502, f"YouTube API error: {e}")
        for item in items:
            duration = (item.get("contentDetails") or {}).get("duration", "")
            duration_seconds = _iso8601_to_seconds(duration)
            # Reuse the stored verdict for videos we've already classified.
            # For new ones, probe the Shorts URL (see is_actually_short) — but
            # only up to MAX_SHORTS_PROBES_PER_SYNC per run; past that, fall back
            # to the duration label (a later backfill corrects the remainder).
            prior = existing_is_short.get(item["id"])
            if prior is not None:
                is_short = prior
            elif duration_seconds is None or duration_seconds > SHORTS_MAX_SECONDS:
                is_short = False                       # too long to be a Short; no probe
            elif probes_used < MAX_SHORTS_PROBES_PER_SYNC:
                is_short = is_actually_short(item["id"], duration_seconds)
                probes_used += 1
                if probes_used == MAX_SHORTS_PROBES_PER_SYNC:
                    log.warning(
                        "sync %s hit the %d Shorts-probe cap; remaining new videos "
                        "are duration-labeled — run scripts/backfill_is_short.py to correct them",
                        channel_id, MAX_SHORTS_PROBES_PER_SYNC,
                    )
            else:
                is_short = duration_seconds <= SHORTS_MAX_SECONDS   # duration fallback
            if not sync_shorts and is_short:
                continue  # skip shorts when channel has sync_shorts = false
            privacy = (item.get("status") or {}).get("privacyStatus")
            if privacy == "private":
                # Don't ingest the snippet, but flip any existing row to private
                # so the autopilot stops picking it. Without this the stored
                # privacy_status stays stale at 'public' and audits fail when
                # the transcript / YouTube API rejects the now-private video.
                privacy_changed_to_private.append(item["id"])
                continue
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
                "privacy_status": privacy,
                "is_short": is_short,
                "duration_seconds": duration_seconds,
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
        for i in range(0, len(deduped), 100):
            supabase().table("videos").upsert(deduped[i:i+100]).execute()

    if privacy_changed_to_private:
        supabase().table("videos").update(
            {"privacy_status": "private"}
        ).in_("id", privacy_changed_to_private).execute()

    # Refresh default_language from YouTube unless the channel has a manual override.
    now_iso = datetime.now(timezone.utc).isoformat()
    channel_patch: dict = {"last_synced_at": now_iso}
    if full:
        # Records when we last rebuilt every snippet, so autopilot can space full
        # passes a few days apart and run incremental syncs in between.
        channel_patch["last_full_synced_at"] = now_iso
    if not channel_settings.get("default_language") and channel_meta.get("default_language"):
        channel_patch["default_language"] = channel_meta["default_language"]
    supabase().table("channels").update(channel_patch).eq("id", channel_id).execute()

    return {"synced": len(rows)}


def _refresh_stats_for_ids(channel_id: str, yt, target_ids: list[str]) -> int:
    """Pull statistics+status for the given video ids (1 quota unit per 50) and
    update counts plus privacy_status. Returns the number of videos refreshed.

    Writing privacy_status here is how privacy flips on already-synced videos
    get caught cheaply (option B) without a full snippet re-fetch — both
    public→private (so autopilot stops touching it) and private→public.
    """
    refreshed = 0
    now = datetime.now(timezone.utc).isoformat()
    for i in range(0, len(target_ids), 50):
        batch = target_ids[i:i+50]
        try:
            items = yt_videos_list_stats(yt, channel_id, batch)
        except HttpError as e:
            if e.status_code == 403 and "quotaExceeded" in str(e):
                raise HTTPException(429, "youtube_quota_exceeded")
            raise HTTPException(502, f"YouTube API error: {e}")
        for item in items:
            stats = item.get("statistics", {})
            patch = {
                "view_count": int(stats.get("viewCount") or 0),
                "like_count": int(stats.get("likeCount") or 0),
                "comment_count": int(stats.get("commentCount") or 0),
                "last_fetched_at": now,
            }
            privacy = (item.get("status") or {}).get("privacyStatus")
            if privacy:
                patch["privacy_status"] = privacy
            supabase().table("videos").update(patch).eq("id", item["id"]).execute()
            refreshed += 1
    return refreshed


@router.post("/channels/{channel_id}/refresh-stats")
def refresh_stats(channel_id: str):
    """Refresh view/like/comment counts and privacy_status for every synced
    video on the channel. Cheap: 1 quota unit per 50 videos, and no playlist
    walk. Run this on a routine cadence to keep stats fresh and catch privacy
    flips between full syncs."""
    vids = (
        supabase().table("videos").select("id").eq("channel_id", channel_id).execute().data or []
    )
    target_ids = [v["id"] for v in vids]
    if not target_ids:
        return {"refreshed": 0}
    try:
        yt = youtube_for_channel(channel_id)
    except TokenExpiredError:
        raise HTTPException(401, "token_expired")
    return {"refreshed": _refresh_stats_for_ids(channel_id, yt, target_ids)}


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

    try:
        yt = youtube_for_channel(channel_id)
    except TokenExpiredError:
        raise HTTPException(401, "token_expired")
    return {"refreshed": _refresh_stats_for_ids(channel_id, yt, target_ids)}


@router.get("/channels/{channel_id}/videos")
def list_videos(channel_id: str):
    # `description` and `tags` are intentionally NOT selected here. They are the
    # two largest columns on the row and are only needed when the user expands a
    # single video's audit diff — shipping them for the whole list made this
    # query ~8x slower (≈2.0s → ≈0.24s without them on a 1000-row channel). The
    # UI lazy-loads them per-video via GET /videos/{video_id} on expand.
    videos = (
        supabase().table("videos")
        .select("id,title,view_count,like_count,comment_count,"
                "published_at,thumbnail_url,privacy_status,last_fetched_at,is_short")
        .eq("channel_id", channel_id)
        .order("published_at", desc=True)
        .execute()
    ).data or []

    if not videos:
        return []

    # Pull all audits for these videos so we can enrich each row with:
    # - latest audit status, applied_at
    # - audit_count (how many times re-audited)
    # - issues_count (from latest audit's issues_found.issues)
    # - ai_reasoning_short (latest)
    video_ids = [v["id"] for v in videos]
    audits = (
        supabase().table("audits")
        .select("id,video_id,status,applied_at,created_at,issues_found,ai_reasoning")
        .in_("video_id", video_ids)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    latest: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for a in audits:
        vid = a["video_id"]
        counts[vid] = counts.get(vid, 0) + 1
        if vid not in latest:
            latest[vid] = a

    now = datetime.now(timezone.utc)
    for v in videos:
        a = latest.get(v["id"])
        v["audit_status"] = a["status"] if a else None
        v["audit_applied_at"] = a.get("applied_at") if a else None
        v["audit_id"] = a.get("id") if a else None
        v["audit_count"] = counts.get(v["id"], 0)
        v["audit_last_at"] = (a.get("applied_at") or a.get("created_at")) if a else None
        if a:
            ifd = a.get("issues_found") or {}
            issues = ifd.get("issues") if isinstance(ifd, dict) else None
            v["issues_count"] = len(issues) if isinstance(issues, list) else 0
            reasoning = a.get("ai_reasoning") or ""
            v["ai_reasoning_short"] = (reasoning[:140] + "…") if len(reasoning) > 140 else reasoning
        else:
            v["issues_count"] = 0
            v["ai_reasoning_short"] = ""
        # Approximate view velocity: avg views/day since publish.
        pub = None
        if v.get("published_at"):
            try:
                pub = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
            except ValueError:
                pub = None
        if pub:
            age_days = max(1.0, (now - pub).total_seconds() / 86400.0)
            v["views_per_day"] = round((v.get("view_count") or 0) / age_days, 1)
        else:
            v["views_per_day"] = None

    # Shorts enrichment: latest shorts_jobs row per source_video_id + clip counts.
    # Query by channel_id (indexed, a handful of rows) rather than
    # .in_("source_video_id", [~1000 ids]) — the giant IN list cost ~1.7s to
    # parse for a 9-row result. Jobs are always created with the source video's
    # channel_id, so this returns the same rows for any video shown here; jobs
    # whose source video isn't in this (newest-1000) list are harmlessly ignored
    # by the per-video lookup below.
    jobs = (
        supabase().table("shorts_jobs")
        .select("id,source_video_id,status,created_at")
        .eq("channel_id", channel_id)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    latest_job: dict[str, dict] = {}
    for j in jobs:
        svid = j.get("source_video_id")
        if svid and svid not in latest_job:
            latest_job[svid] = j
    job_ids = [j["id"] for j in latest_job.values()]
    clip_rows = []
    if job_ids:
        clip_rows = (
            supabase().table("shorts_clips")
            .select("job_id,upload_status")
            .in_("job_id", job_ids)
            .execute()
        ).data or []
    clips_by_job: dict[int, list] = {}
    for c in clip_rows:
        clips_by_job.setdefault(c["job_id"], []).append(c)
    for v in videos:
        j = latest_job.get(v["id"])
        v["shorts_status"] = j["status"] if j else None
        v["shorts_job_id"] = j["id"] if j else None
        job_clips = clips_by_job.get(j["id"], []) if j else []
        v["clips_count"] = len(job_clips)
        v["clips_uploaded"] = sum(1 for c in job_clips if c["upload_status"] == "UPLOADED")

    return videos


@router.get("/videos/{video_id}")
def get_video(video_id: str):
    """Single video row including the heavy `description`/`tags` columns that
    the list endpoint omits. Used by the channel page to lazy-load a video's
    full metadata when its audit diff is expanded."""
    row = (
        supabase().table("videos")
        .select("id,title,description,tags,view_count,like_count,comment_count,"
                "published_at,thumbnail_url,privacy_status,last_fetched_at,is_short")
        .eq("id", video_id)
        .single()
        .execute()
    ).data
    if not row:
        raise HTTPException(404, f"Video {video_id} not found")
    return row
