"""Video embeddings — the only module that knows how they are stored.

A pooled embedding is keyed by (video_id, chunk_index='pooled', model_version).
That three-part key used to be re-derived at six Python call sites and two SQL
functions, and `_parse_embedding` — the adapter for PostgREST returning pgvector
as a string — had leaked out of storage into two other modules' imports. Change
the key shape and you had to find all eight.

Reads go through `pooled_embedding` / `pooled_embeddings` / `has_pooled_embedding`
/ `embedded_video_ids`. The SQL RPCs cannot import from here; they re-type the
predicate and are pinned by tests/test_embeddings_read.py.
"""
import logging

from app.db import supabase
from app.openrouter import embed, EMBED_MODEL
from app.rows import rows_for_ids
from app.transcripts import fetch_transcript

log = logging.getLogger("midas.embeddings")

#: chunk_index for the whole-video embedding. The column exists so a video can
#: later be embedded in chunks; only the pooled row is used today.
POOLED = "pooled"


def parse_vector(raw) -> list[float]:
    """PostgREST returns pgvector columns as a string '[0.1,0.2,...]'."""
    if isinstance(raw, str):
        return [float(x) for x in raw.strip("[]").split(",")]
    return [float(x) for x in raw]


def _pooled_query(video_ids: list[str], columns: str = "video_id,embedding"):
    """Unexecuted query for the pooled rows of `video_ids`."""
    return (
        supabase().table("video_embeddings")
        .select(columns)
        .in_("video_id", video_ids)
        .eq("chunk_index", POOLED)
        .eq("model_version", EMBED_MODEL)
    )


def pooled_embedding(video_id: str) -> list[float] | None:
    """The video's pooled vector, or None if it has not been embedded."""
    rows = (
        supabase().table("video_embeddings")
        .select("embedding")
        .eq("video_id", video_id)
        .eq("chunk_index", POOLED)
        .eq("model_version", EMBED_MODEL)
        .limit(1)
        .execute()
    ).data or []
    return parse_vector(rows[0]["embedding"]) if rows else None


def pooled_embeddings(video_ids) -> dict[str, list[float]]:
    """{video_id: vector} for those that have one. Chunked and paged."""
    rows = rows_for_ids(_pooled_query, video_ids)
    return {r["video_id"]: parse_vector(r["embedding"]) for r in rows}


def has_pooled_embedding(video_id: str) -> bool:
    """Existence check that does NOT pull the vector (~39 KB of egress/row)."""
    rows = (
        supabase().table("video_embeddings")
        .select("id")
        .eq("video_id", video_id)
        .eq("chunk_index", POOLED)
        .eq("model_version", EMBED_MODEL)
        .limit(1)
        .execute()
    ).data
    return bool(rows)


def embedded_video_ids(video_ids) -> set[str]:
    """Which of `video_ids` already have a pooled embedding (no vectors pulled)."""
    rows = rows_for_ids(lambda chunk: _pooled_query(chunk, "video_id"), video_ids)
    return {r["video_id"] for r in rows}


def embed_video(video_id: str, use_transcript: bool = True, *, force: bool = False) -> bool:
    """Compute and store a pooled embedding for a video. Idempotent.

    Returns True if newly embedded, False if already up-to-date.

    `force` re-embeds a video that already has a vector. Pass it whenever the
    embedded text has changed — an applied audit rewrites the title, and without
    this the video keeps the vector of its OLD title forever, which is not what
    bootstrap_embeddings' "always embed the optimised title" intends.
    """
    if not force and has_pooled_embedding(video_id):
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
            "chunk_index": POOLED,
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

    already_done = embedded_video_ids(video_ids)

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
