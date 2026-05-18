import logging

from app.db import supabase
from app.openrouter import embed, EMBED_MODEL
from app.transcripts import fetch_transcript

log = logging.getLogger("midas.embeddings")


def embed_video(video_id: str, use_transcript: bool = True) -> bool:
    """Compute and store a pooled embedding for a video. Idempotent.

    Returns True if newly embedded, False if already up-to-date.
    """
    existing = (
        supabase().table("video_embeddings")
        .select("id")
        .eq("video_id", video_id)
        .eq("chunk_index", "pooled")
        .eq("model_version", EMBED_MODEL)
        .execute()
    ).data
    if existing:
        return False

    video = (
        supabase().table("videos")
        .select("id,title,channel_id,privacy_status")
        .eq("id", video_id)
        .single()
        .execute()
    ).data
    if not video:
        return False

    transcript = None
    if use_transcript and video.get("privacy_status") in (None, "public"):
        transcript, _ = fetch_transcript(video_id, channel_id=video["channel_id"])

    text = (video.get("title") or "").strip()
    if transcript:
        text += "\n\n" + transcript[:6000]

    if not text:
        log.warning("No text to embed for video %s", video_id)
        return False

    vectors = embed([text])

    supabase().table("video_embeddings").upsert(
        {
            "video_id": video_id,
            "chunk_index": "pooled",
            "embedding": vectors[0],
            "model_version": EMBED_MODEL,
        },
        on_conflict="video_id,chunk_index,model_version",
    ).execute()

    log.info("Embedded video %s (%d-dim)", video_id, len(vectors[0]))
    return True


def bootstrap_embeddings(channel_id: str) -> int:
    """Embed audited, non-short videos in a channel that have no pooled embedding yet.

    Only embeds videos whose latest audit is 'applied' — so we always embed the
    optimised title, not whatever the uploader originally wrote. Shorts are excluded
    since they are never added to playlists.

    Returns the count of newly embedded videos.
    """
    applied_video_ids = {
        r["video_id"]
        for r in (
            supabase().table("audits")
            .select("video_id")
            .eq("status", "applied")
            .execute()
        ).data or []
    }
    if not applied_video_ids:
        return 0

    videos = (
        supabase().table("videos")
        .select("id")
        .eq("channel_id", channel_id)
        .eq("is_short", False)
        .in_("id", list(applied_video_ids))
        .execute()
    ).data or []
    if not videos:
        return 0

    video_ids = [v["id"] for v in videos]

    existing = (
        supabase().table("video_embeddings")
        .select("video_id")
        .in_("video_id", video_ids)
        .eq("chunk_index", "pooled")
        .eq("model_version", EMBED_MODEL)
        .execute()
    ).data or []
    already_done = {e["video_id"] for e in existing}

    count = 0
    for vid in video_ids:
        if vid in already_done:
            continue
        try:
            if embed_video(vid, use_transcript=False):
                count += 1
        except Exception as e:
            log.warning("Failed to embed video %s: %s", vid, e)

    log.info("bootstrap_embeddings(%s): %d/%d newly embedded", channel_id, count, len(video_ids))
    return count
