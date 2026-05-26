"""Discover new playlist themes from videos that don't fit any existing playlist.

Runs weekly. Groups orphan videos by pairwise cosine similarity and creates
new playlists for tight clusters. Hard cap: 2 new playlists per run.
"""
import logging
import math

from app.config import settings
from app.db import supabase
from app.openrouter import chat_json, EMBED_MODEL
from app.playlists import _current_members, _cosine_sim, _record_assignment
from app.youtube_client import youtube_for_channel, yt_playlists_insert, yt_playlist_items_insert

log = logging.getLogger("midas.playlist_discovery")

MIN_CLUSTER_SIZE = 4
MAX_NEW_PLAYLISTS = 2
CLUSTER_SIM_THRESHOLD = 0.75
JOIN_THRESHOLD = settings.PLAYLIST_JOIN_HIGH
JUDGE_MODEL = "anthropic/claude-haiku-4.5"


def _orphan_video_ids(channel_id: str, all_video_ids: list[str]) -> list[str]:
    """Return video IDs that are not currently in any playlist."""
    playlist_ids = [
        p["id"]
        for p in (
            supabase().table("playlists")
            .select("id")
            .eq("channel_id", channel_id)
            .execute()
        ).data or []
    ]
    if not playlist_ids:
        return all_video_ids

    in_playlist: set[str] = set()
    for pid in playlist_ids:
        in_playlist.update(_current_members(pid).keys())

    return [v for v in all_video_ids if v not in in_playlist]


def _cluster_orphans(
    orphan_ids: list[str],
    embeddings: dict[str, list[float]],
) -> list[list[str]]:
    """Group orphans into clusters using greedy pairwise cosine similarity.

    A video joins an existing cluster if its mean similarity to all current
    cluster members exceeds CLUSTER_SIM_THRESHOLD. Otherwise it starts a new cluster.
    Clusters smaller than MIN_CLUSTER_SIZE are discarded.
    """
    clusters: list[list[str]] = []

    for vid in orphan_ids:
        emb = embeddings.get(vid)
        if emb is None:
            continue

        best_cluster = None
        best_score = 0.0

        for cluster in clusters:
            member_embs = [embeddings[m] for m in cluster if m in embeddings]
            if not member_embs:
                continue
            mean_sim = sum(_cosine_sim(emb, m) for m in member_embs) / len(member_embs)
            if mean_sim > best_score:
                best_score = mean_sim
                best_cluster = cluster

        if best_cluster is not None and best_score >= CLUSTER_SIM_THRESHOLD:
            best_cluster.append(vid)
        else:
            clusters.append([vid])

    return [c for c in clusters if len(c) >= MIN_CLUSTER_SIZE]


def _propose_playlist(video_ids: list[str]) -> dict | None:
    """Ask Claude to propose a playlist title + description for a cluster."""
    rows = (
        supabase().table("videos")
        .select("title")
        .in_("id", video_ids[:10])
        .execute()
    ).data or []
    titles = [r["title"] for r in rows if r.get("title")]
    if not titles:
        return None

    titles_str = "\n".join(f"- {t}" for t in titles)
    prompt = (
        f"These YouTube videos form a thematic cluster:\n{titles_str}\n\n"
        f"Propose a concise, descriptive YouTube playlist title and a one-sentence description "
        f"that captures what they have in common. "
        f'Answer JSON: {{"title": "...", "description": "..."}}'
    )
    try:
        return chat_json(prompt, model=JUDGE_MODEL)
    except Exception as e:
        log.warning("Playlist proposal LLM call failed: %s", e)
        return None


def discover_playlists(channel_id: str) -> dict:
    """Find orphan clusters and create new playlists for them.

    Returns {"clusters_found": int, "playlists_created": int}.
    """
    if settings.DRY_RUN:
        log.info("[DRY_RUN] discover_playlists skipped for %s", channel_id)
        return {"clusters_found": 0, "playlists_created": 0}

    videos = (
        supabase().table("videos")
        .select("id")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []
    all_video_ids = [v["id"] for v in videos]
    if not all_video_ids:
        return {"clusters_found": 0, "playlists_created": 0}

    # Load embeddings once
    emb_rows = (
        supabase().table("video_embeddings")
        .select("video_id,embedding")
        .in_("video_id", all_video_ids)
        .eq("chunk_index", "pooled")
        .eq("model_version", EMBED_MODEL)
        .execute()
    ).data or []
    embeddings: dict[str, list[float]] = {r["video_id"]: r["embedding"] for r in emb_rows}

    orphans = _orphan_video_ids(channel_id, all_video_ids)
    orphans = [v for v in orphans if v in embeddings]  # only embeddable orphans

    if not orphans:
        log.info("discover_playlists(%s): no orphan videos", channel_id)
        return {"clusters_found": 0, "playlists_created": 0}

    clusters = _cluster_orphans(orphans, embeddings)
    log.info("discover_playlists(%s): %d orphans → %d clusters", channel_id, len(orphans), len(clusters))

    if not clusters:
        return {"clusters_found": 0, "playlists_created": 0}

    yt = youtube_for_channel(channel_id)
    created = 0

    for cluster in clusters:
        if created >= MAX_NEW_PLAYLISTS:
            break

        proposal = _propose_playlist(cluster)
        if not proposal or not proposal.get("title"):
            continue

        title = proposal["title"][:100]  # YouTube title limit
        description = (proposal.get("description") or "")[:5000]

        try:
            playlist_id = yt_playlists_insert(yt, channel_id, title, description)
            # Insert into local playlists table
            supabase().table("playlists").insert({
                "id": playlist_id,
                "channel_id": channel_id,
                "title": title,
                "description": description,
            }).execute()
            log.info("discover_playlists: created playlist '%s' (%s)", title, playlist_id)
        except Exception as e:
            log.warning("discover_playlists: failed to create playlist '%s': %s", title, e)
            continue

        # Add all cluster members
        for video_id in cluster:
            try:
                item_id = yt_playlist_items_insert(yt, channel_id, playlist_id, video_id)
                _record_assignment(video_id, playlist_id, item_id, "added", None, "discovery")
            except Exception as e:
                log.warning("discover_playlists: failed to add %s to %s: %s", video_id, playlist_id, e)

        created += 1

    return {"clusters_found": len(clusters), "playlists_created": created}
