"""Playlist assignment engine.

join_pass      — called per-video after audit; adds to matching existing playlists.
reconcile_channel — called daily; re-scores all videos and syncs adds/removes.
"""
import logging
import math
from datetime import datetime, timezone

from app.config import settings
from app.db import supabase
from app.openrouter import chat_json, EMBED_MODEL
from app.youtube_client import (
    youtube_for_channel,
    yt_playlist_items_insert,
    yt_playlist_items_delete,
)

log = logging.getLogger("midas.playlists")

JUDGE_MODEL = "anthropic/claude-haiku-4.5"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _current_members(playlist_id: str) -> dict[str, str | None]:
    """Return {video_id: playlist_item_id} for videos currently in a playlist.

    Derives state from the append-only playlist_assignments log by taking
    the latest action per video and keeping only 'added' ones.
    """
    rows = (
        supabase().table("playlist_assignments")
        .select("video_id,action,playlist_item_id,decided_at")
        .eq("playlist_id", playlist_id)
        .order("decided_at", desc=True)
        .execute()
    ).data or []

    latest: dict[str, dict] = {}
    for row in rows:
        if row["video_id"] not in latest:
            latest[row["video_id"]] = row

    return {
        vid: row["playlist_item_id"]
        for vid, row in latest.items()
        if row["action"] == "added"
    }


def _parse_embedding(raw) -> list[float]:
    """Supabase returns pgvector columns as a string '[0.1,0.2,...]' — parse to list[float]."""
    if isinstance(raw, str):
        return [float(x) for x in raw.strip("[]").split(",")]
    return [float(x) for x in raw]


def _get_embedding(video_id: str) -> list[float] | None:
    row = (
        supabase().table("video_embeddings")
        .select("embedding")
        .eq("video_id", video_id)
        .eq("chunk_index", "pooled")
        .eq("model_version", EMBED_MODEL)
        .single()
        .execute()
    ).data
    return _parse_embedding(row["embedding"]) if row else None


def _centroid(video_ids: list[str]) -> list[float] | None:
    """Mean of pooled embeddings for the given video IDs. Returns None if none found."""
    if not video_ids:
        return None

    rows = (
        supabase().table("video_embeddings")
        .select("embedding")
        .in_("video_id", video_ids)
        .eq("chunk_index", "pooled")
        .eq("model_version", EMBED_MODEL)
        .execute()
    ).data or []

    if not rows:
        return None

    vectors = [_parse_embedding(r["embedding"]) for r in rows]
    dim = len(vectors[0])
    mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    return mean


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ── Centroid similarity (pgvector RPC, with in-app fallback) ───────────────────
# join_pass / reconcile_channel score videos against playlist centroids. The
# in-app path below (_get_embedding + _centroid + _cosine_sim) pulls pooled
# embeddings — vector(3072), ~39 KB/row — into the app; the daily reconcile does
# this per channel and is the biggest recurring Supabase egress source. When
# PLAYLIST_SIMS_USE_RPC is on, the identical math runs in Postgres via
# playlist_video_sims() and only floats come back. Both paths are kept: the
# in-app one is the correctness oracle (see the live parity test) and the
# automatic fallback if the RPC errors.

def _has_pooled_embedding(video_id: str) -> bool:
    """Cheap existence check (no vector egress) — replaces _get_embedding's
    null-check on the RPC path."""
    row = (
        supabase().table("video_embeddings")
        .select("id")
        .eq("video_id", video_id)
        .eq("chunk_index", "pooled")
        .eq("model_version", EMBED_MODEL)
        .limit(1)
        .execute()
    ).data
    return bool(row)


def _rpc_playlist_sims(channel_id: str, video_id: str | None) -> list[dict]:
    resp = supabase().rpc("playlist_video_sims", {
        "p_channel_id": channel_id,
        "p_model_version": EMBED_MODEL,
        "p_video_id": video_id,
    }).execute()
    return resp.data or []


def _sims_for_video(channel_id: str, video_id: str,
                    playlists: list[dict]) -> dict[str, float] | None:
    """{playlist_id: sim} for one video vs each playlist's current-member centroid.

    Returns None iff the video has no pooled embedding (caller warns and skips).
    Playlists with no embedded members simply don't appear in the dict.
    """
    if settings.PLAYLIST_SIMS_USE_RPC:
        try:
            rows = _rpc_playlist_sims(channel_id, video_id)
            if not _has_pooled_embedding(video_id):
                return None
            return {r["playlist_id"]: r["sim"] for r in rows}
        except Exception:
            log.warning("playlist_video_sims RPC failed; falling back to in-app centroids",
                        exc_info=True)

    emb = _get_embedding(video_id)
    if emb is None:
        return None
    out: dict[str, float] = {}
    for pl in playlists:
        current = _current_members(pl["id"])
        if video_id in current:
            continue  # never scored against a centroid that includes itself
        centroid = _centroid(list(current.keys()))
        if centroid is None:
            continue
        out[pl["id"]] = _cosine_sim(emb, centroid)
    return out


def _sims_matrix(channel_id: str, playlists: list[dict],
                 video_ids: list[str]) -> tuple[dict[tuple[str, str], float], set[str]]:
    """({(playlist_id, video_id): sim}, {playlist_ids_with_centroid}).

    One frozen snapshot of every embedded channel video scored against every
    playlist centroid — the reconcile_channel workhorse.
    """
    if settings.PLAYLIST_SIMS_USE_RPC:
        try:
            rows = _rpc_playlist_sims(channel_id, None)
            sims = {(r["playlist_id"], r["video_id"]): r["sim"] for r in rows}
            centroid_pids = {r["playlist_id"] for r in rows}
            return sims, centroid_pids
        except Exception:
            log.warning("playlist_video_sims RPC failed; falling back to in-app centroids",
                        exc_info=True)

    emb_rows = (
        supabase().table("video_embeddings")
        .select("video_id,embedding")
        .in_("video_id", video_ids)
        .eq("chunk_index", "pooled")
        .eq("model_version", EMBED_MODEL)
        .execute()
    ).data or []
    all_emb = {r["video_id"]: _parse_embedding(r["embedding"]) for r in emb_rows}
    sims: dict[tuple[str, str], float] = {}
    centroid_pids: set[str] = set()
    for pl in playlists:
        members = _current_members(pl["id"])
        centroid = _centroid(list(members.keys()))
        if centroid is None:
            continue
        centroid_pids.add(pl["id"])
        for vid in video_ids:
            e = all_emb.get(vid)
            if e is None:
                continue
            sims[(pl["id"], vid)] = _cosine_sim(e, centroid)
    return sims, centroid_pids


def _member_titles(video_ids: list[str], limit: int = 5) -> list[str]:
    if not video_ids:
        return []
    rows = (
        supabase().table("videos")
        .select("title")
        .in_("id", video_ids[:limit])
        .execute()
    ).data or []
    return [r["title"] for r in rows if r.get("title")]


def _llm_judge(video_id: str, playlist: dict, member_video_ids: list[str]) -> bool:
    """Ask Claude Haiku whether the video belongs in the playlist.

    Returns True if it belongs, False otherwise.
    """
    video = (
        supabase().table("videos")
        .select("title")
        .eq("id", video_id)
        .single()
        .execute()
    ).data
    if not video:
        return False

    titles = _member_titles(member_video_ids)
    members_str = "\n".join(f"- {t}" for t in titles) if titles else "(no members yet)"

    prompt = (
        f'Playlist: "{playlist["title"]}"\n'
        f'Playlist description: "{playlist.get("description") or ""}"\n'
        f"Sample members:\n{members_str}\n\n"
        f'Candidate video: "{video["title"]}"\n\n'
        f'Does this video thematically belong in this playlist? '
        f'Answer JSON: {{"belong": true/false, "reason": "one sentence"}}'
    )
    try:
        result = chat_json(prompt, model=JUDGE_MODEL)
        return bool(result.get("belong", False))
    except Exception as e:
        log.warning("LLM judge failed for video %s / playlist %s: %s", video_id, playlist["id"], e)
        return False


def _queue_proposal(
    video_id: str,
    playlist_id: str,
    action: str,
    similarity: float | None,
    source: str,
) -> None:
    video = supabase().table("videos").select("title").eq("id", video_id).single().execute().data
    playlist = supabase().table("playlists").select("title").eq("id", playlist_id).single().execute().data
    supabase().table("playlist_proposals").insert({
        "video_id": video_id,
        "playlist_id": playlist_id,
        "video_title": (video or {}).get("title"),
        "playlist_title": (playlist or {}).get("title"),
        "action": action,
        "similarity": similarity,
        "decision_source": source,
        "status": "pending",
    }).execute()


def _record_assignment(
    video_id: str,
    playlist_id: str,
    playlist_item_id: str | None,
    action: str,
    similarity: float | None,
    source: str,
) -> None:
    supabase().table("playlist_assignments").insert({
        "video_id": video_id,
        "playlist_id": playlist_id,
        "playlist_item_id": playlist_item_id,
        "action": action,
        "similarity_score": similarity,
        "decision_source": source,
        "model_version": EMBED_MODEL,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }).execute()


# ── Public API ────────────────────────────────────────────────────────────────

def join_pass(channel_id: str, video_id: str) -> int:
    """Score a video against all channel playlists and add where it fits.

    Called right after a video is embedded. Returns the number of playlists joined.
    """
    if settings.DRY_RUN:
        log.info("[DRY_RUN] join_pass skipped for video %s", video_id)
        return 0

    playlists = (
        supabase().table("playlists")
        .select("id,title,description")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []

    if not playlists:
        return 0

    # sim per playlist (pgvector RPC or in-app centroids). None => no embedding.
    sims = _sims_for_video(channel_id, video_id, playlists)
    if sims is None:
        log.warning("join_pass: no embedding for video %s, skipping", video_id)
        return 0

    yt = youtube_for_channel(channel_id)
    joined = 0

    for playlist in playlists:
        playlist_id = playlist["id"]
        current = _current_members(playlist_id)

        if video_id in current:
            continue  # already in this playlist

        sim = sims.get(playlist_id)
        if sim is None:
            # Empty playlist / no embedded members — discovery handles empty clusters
            continue

        if sim < settings.PLAYLIST_JOIN_LOW:
            continue

        if sim >= settings.PLAYLIST_JOIN_HIGH:
            source = "embedding"
            belongs = True
        else:
            belongs = _llm_judge(video_id, playlist, list(current.keys()))
            source = "llm_confirmed"

        if not belongs:
            continue

        if settings.PLAYLIST_HITL:
            _queue_proposal(video_id, playlist_id, "add", sim, source)
            log.info("join_pass: queued proposal %s → %s (sim=%.3f)", video_id, playlist_id, sim)
            joined += 1
        else:
            try:
                item_id = yt_playlist_items_insert(yt, channel_id, playlist_id, video_id)
                _record_assignment(video_id, playlist_id, item_id, "added", sim, source)
                log.info("join_pass: added %s → %s (sim=%.3f, src=%s)", video_id, playlist_id, sim, source)
                joined += 1
            except Exception as e:
                log.warning("join_pass: YouTube insert failed %s → %s: %s", video_id, playlist_id, e)

    return joined


def reconcile_channel(channel_id: str) -> dict:
    """Re-score all videos against all playlists and reconcile membership.

    Centroids are frozen at the start of the run to prevent cascade effects.
    Removals always require LLM confirmation. Hard cap of PLAYLIST_MUTATION_CAP
    mutations per run.

    Returns {"added": int, "removed": int, "skipped_cap": bool}.
    """
    if settings.DRY_RUN:
        log.info("[DRY_RUN] reconcile_channel skipped for %s", channel_id)
        return {"added": 0, "removed": 0, "skipped_cap": False}

    playlists = (
        supabase().table("playlists")
        .select("id,title,description")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []

    videos = (
        supabase().table("videos")
        .select("id")
        .eq("channel_id", channel_id)
        .execute()
    ).data or []

    if not playlists or not videos:
        return {"added": 0, "removed": 0, "skipped_cap": False}

    video_ids = [v["id"] for v in videos]

    # One frozen snapshot: sim of every embedded video to every playlist centroid
    # (pgvector RPC or in-app centroids). Freezing here prevents cascade effects.
    sims, centroid_pids = _sims_matrix(channel_id, playlists, video_ids)

    # Freeze membership too — needed for the in-playlist test and item_ids on removal.
    frozen: dict[str, dict] = {}  # playlist_id → {members: {vid: item_id}, has_centroid: bool}
    for playlist in playlists:
        frozen[playlist["id"]] = {
            "members": _current_members(playlist["id"]),
            "has_centroid": playlist["id"] in centroid_pids,
        }

    yt = youtube_for_channel(channel_id)
    added = removed = 0
    cap = settings.PLAYLIST_MUTATION_CAP
    skipped_cap = False

    for playlist in playlists:
        playlist_id = playlist["id"]
        state = frozen[playlist_id]
        current = state["members"]

        if not state["has_centroid"]:
            continue

        for video_id in video_ids:
            if added + removed >= cap:
                skipped_cap = True
                break

            sim = sims.get((playlist_id, video_id))
            if sim is None:
                continue  # video has no pooled embedding — skip (matches emb-None)

            in_playlist = video_id in current

            if in_playlist and sim < settings.PLAYLIST_LEAVE:
                # Below leave threshold — ask LLM before removing
                if not _llm_judge(video_id, playlist, list(current.keys())):
                    continue
                playlist_item_id = current[video_id]
                if not playlist_item_id:
                    log.warning("reconcile: no playlist_item_id for %s in %s, cannot remove", video_id, playlist_id)
                    continue
                if settings.PLAYLIST_HITL:
                    _queue_proposal(video_id, playlist_id, "remove", sim, "llm_confirmed")
                    log.info("reconcile: queued removal %s from %s (sim=%.3f)", video_id, playlist_id, sim)
                    removed += 1
                else:
                    try:
                        yt_playlist_items_delete(yt, channel_id, playlist_item_id)
                        _record_assignment(video_id, playlist_id, None, "removed", sim, "llm_confirmed")
                        log.info("reconcile: removed %s from %s (sim=%.3f)", video_id, playlist_id, sim)
                        removed += 1
                    except Exception as e:
                        log.warning("reconcile: YouTube delete failed %s from %s: %s", video_id, playlist_id, e)

            elif not in_playlist and sim >= settings.PLAYLIST_JOIN_HIGH:
                if settings.PLAYLIST_HITL:
                    _queue_proposal(video_id, playlist_id, "add", sim, "embedding")
                    log.info("reconcile: queued add %s → %s (sim=%.3f)", video_id, playlist_id, sim)
                    added += 1
                else:
                    try:
                        item_id = yt_playlist_items_insert(yt, channel_id, playlist_id, video_id)
                        _record_assignment(video_id, playlist_id, item_id, "added", sim, "embedding")
                        log.info("reconcile: added %s → %s (sim=%.3f)", video_id, playlist_id, sim)
                        added += 1
                    except Exception as e:
                        log.warning("reconcile: YouTube insert failed %s → %s: %s", video_id, playlist_id, e)

        if skipped_cap:
            break

    log.info("reconcile_channel(%s): added=%d removed=%d cap_hit=%s", channel_id, added, removed, skipped_cap)
    return {"added": added, "removed": removed, "skipped_cap": skipped_cap}
