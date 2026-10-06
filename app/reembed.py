"""B6: re-embed a channel with one input recipe, and calibrate its thresholds.

The production `model_version` (= EMBED_MODEL) holds vectors from two recipes:
title + transcript after an apply, title only from `bootstrap_embeddings`. It
can't say what was embedded, so this module embeds one recipe, title +
description + tags for every video, under a version that names it
(`MODEL_VERSION`). Nothing in production reads that version yet: the playlist
engine and its RPCs still filter on EMBED_MODEL.

Calibration recomputes the three playlist thresholds per channel on the new
vectors and stores them on `channels.playlist_thresholds`. It never writes the
process-global `settings.PLAYLIST_*`, and nothing reads the stored values yet.

A one-off, run by `scripts/reembed.py`; not a scheduled job.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import NamedTuple

from app.db import supabase
from app.embeddings import POOLED, embedded_video_ids, pooled_embeddings
from app.openrouter import EMBED_MODEL, embed
from app.playlists import _cosine_sim
from app.rows import all_rows, rows_for_ids

log = logging.getLogger("midas.reembed")

#: Names the input recipe. Bump it if `recipe_text` changes, so vectors from two
#: recipes never share a version again.
RECIPE = "tdt-v1"
MODEL_VERSION = f"{EMBED_MODEL}|{RECIPE}"

#: Texts per embeddings call. A failed batch is retried one video at a time, so
#: one bad text can't fail its neighbours; a video that still fails is counted
#: and retried on rerun.
BATCH_SIZE = 50

#: Bytes per token for the estimate. UTF-8 bytes rather than characters, so
#: Indic scripts (3 bytes a character) estimate higher than Latin text; 3 rather
#: than the usual 4 to err on the expensive side.
_BYTES_PER_TOKEN = 3

#: Calibration percentiles of member similarity (`MemberSims`; see
#: `calibrate_channel`), and the fewest member similarities to calibrate from.
JOIN_HIGH_PCTL = 50
LEAVE_PCTL = 10
JOIN_LOW_PCTL = 5
MIN_MEMBER_SIMS = 30


def recipe_text(video: dict) -> str:
    """The embedded text: title, description, tags, always in this shape.

    A pure function of the row: no transcript, no privacy or channel branch,
    and an empty field is an empty block rather than a dropped one.
    """
    title = (video.get("title") or "").strip()
    description = (video.get("description") or "").strip()
    tags = ", ".join(video.get("tags") or [])
    return f"{title}\n\n{description}\n\n{tags}"


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / _BYTES_PER_TOKEN)


def _channel_videos(channel_id: str) -> list[dict]:
    return all_rows(
        supabase().table("videos")
        .select("id,title,description,tags")
        .eq("channel_id", channel_id)
    )


def _todo(channel_id: str) -> tuple[list[dict], list[dict]]:
    """(every video of the channel, those not yet embedded under MODEL_VERSION)."""
    videos = _channel_videos(channel_id)
    done = embedded_video_ids([v["id"] for v in videos], model_version=MODEL_VERSION)
    return videos, [v for v in videos if v["id"] not in done]


def estimate_channel(channel_id: str, usd_per_mtok: float) -> dict:
    """Video count, token estimate and cost of the remaining work. Reads the DB
    only: no OpenRouter call."""
    videos, todo = _todo(channel_id)
    tokens = sum(estimate_tokens(recipe_text(v)) for v in todo)
    return {
        "channel_id": channel_id,
        "videos": len(videos),
        "remaining": len(todo),
        "tokens": tokens,
        "usd": tokens * usd_per_mtok / 1_000_000,
    }


def _embed_batch(batch: list[dict]) -> None:
    vectors = embed([recipe_text(v) for v in batch])
    if len(vectors) != len(batch):
        raise RuntimeError(f"{len(vectors)} vectors for {len(batch)} texts")
    supabase().table("video_embeddings").upsert(
        [
            {"video_id": v["id"], "chunk_index": POOLED,
             "embedding": vec, "model_version": MODEL_VERSION}
            for v, vec in zip(batch, vectors)
        ],
        on_conflict="video_id,chunk_index,model_version",
    ).execute()


def reembed_channel(channel_id: str) -> dict:
    """Embed every video of the channel not yet under MODEL_VERSION. Resumable."""
    videos, todo = _todo(channel_id)
    embedded = failed = 0
    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        try:
            _embed_batch(batch)
            embedded += len(batch)
            continue
        except Exception as e:
            if len(batch) > 1:
                log.warning("reembed %s: batch of %d failed; retrying one by one: %s",
                            channel_id, len(batch), e)
            else:
                log.warning("reembed %s: video %s failed; rerun to retry: %s",
                            channel_id, batch[0]["id"], e)
                failed += 1
                continue
        for v in batch:
            try:
                _embed_batch([v])
                embedded += 1
            except Exception as e:
                failed += 1
                log.warning("reembed %s: video %s failed; rerun to retry: %s",
                            channel_id, v["id"], e)
    log.info("reembed %s: %d embedded, %d failed, %d already done",
             channel_id, embedded, failed, len(videos) - len(todo))
    return {
        "channel_id": channel_id,
        "videos": len(videos),
        "skipped": len(videos) - len(todo),
        "embedded": embedded,
        "failed": failed,
    }


def _members(channel_id: str) -> dict[str, list[str]]:
    """{playlist_id: [video_id]} of current members of the channel's playlists:
    each pair's latest `playlist_assignments` action is `added` (as
    `playlists._current_members`).

    `playlist_assignments` has no channel_id, so the channel's playlists come
    from `playlists`, as in the `playlist_video_sims` RPC.
    """
    playlist_ids = [r["id"] for r in all_rows(
        supabase().table("playlists").select("id").eq("channel_id", channel_id))]
    rows = rows_for_ids(
        lambda chunk: supabase().table("playlist_assignments")
        .select("id,playlist_id,video_id,action,decided_at")
        .in_("playlist_id", chunk),
        playlist_ids,
    )
    # Order across chunks isn't meaningful (rows_for_ids), so sort here.
    rows.sort(key=lambda r: (r.get("decided_at") or "", r["id"]))
    latest: dict[tuple[str, str], str] = {}
    for r in rows:
        latest[(r["playlist_id"], r["video_id"])] = r["action"]
    out: dict[str, list[str]] = {}
    for (pid, vid), action in latest.items():
        if action == "added":
            out.setdefault(pid, []).append(vid)
    return out


class MemberSims(NamedTuple):
    """Each current member's cosine to its playlist's centroid, two ways.

    `apart`: the centroid of the OTHER members, which is how a video outside the
    playlist is scored (join_pass, reconcile's adds). `included`: the centroid
    of all members, itself included, which is what reconcile compares with
    PLAYLIST_LEAVE (`playlists._sims_matrix`, and the `playlist_video_sims` RPC).
    """
    apart: list[float]
    included: list[float]
    playlists: int


def member_similarities(channel_id: str) -> MemberSims:
    """Similarities of every member with a MODEL_VERSION vector, in playlists
    with at least 3 such members (so `apart` has two others to average)."""
    members = _members(channel_id)
    vectors = pooled_embeddings(
        sorted({v for vids in members.values() for v in vids}), model_version=MODEL_VERSION)
    apart: list[float] = []
    included: list[float] = []
    scored = 0
    for vids in members.values():
        vecs = [vectors[v] for v in vids if v in vectors]
        if len(vecs) < 3:
            continue
        scored += 1
        # Cosine ignores scale, so a sum stands in for each mean.
        total = [sum(col) for col in zip(*vecs)]
        for v in vecs:
            apart.append(_cosine_sim(v, [t - x for t, x in zip(total, v)]))
            included.append(_cosine_sim(v, total))
    return MemberSims(apart, included, scored)


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear interpolation between closest ranks."""
    k = (len(sorted_values) - 1) * pct / 100
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def calibrate_channel(channel_id: str) -> dict:
    """Recompute the channel's playlist thresholds on MODEL_VERSION vectors.

    From current members' similarity to their playlists (`MemberSims`):
    `join_high` is the median of `apart` (a non-member at least as close as the
    typical member is added directly) and `join_low` its 5th percentile (below
    it the judge isn't asked); `leave` is the 10th percentile of `included` (a
    member below it is an outlier, sent to the judge for removal), measured as
    reconcile measures it. `join_low` <= `join_high` always, and `join_low` <=
    `leave` in practice; `leave` against `join_high` isn't guaranteed, since
    the two come from different distributions.

    Stored on `channels.playlist_thresholds`; `settings` is never written.
    """
    sims = member_similarities(channel_id)
    apart, included = sorted(sims.apart), sorted(sims.included)
    if len(apart) < MIN_MEMBER_SIMS:
        log.info("calibrate %s: %d member similarities, need %d; nothing stored",
                 channel_id, len(apart), MIN_MEMBER_SIMS)
        return {"skipped": True, "reason": "insufficient_data", "member_sims": len(apart)}

    result = {
        "model_version": MODEL_VERSION,
        "join_high": round(_percentile(apart, JOIN_HIGH_PCTL), 4),
        "join_low": round(_percentile(apart, JOIN_LOW_PCTL), 4),
        "leave": round(_percentile(included, LEAVE_PCTL), 4),
        "member_sims": len(apart),
        "playlists": sims.playlists,
        "method": (f"join_high p{JOIN_HIGH_PCTL}, join_low p{JOIN_LOW_PCTL} of member-apart; "
                   f"leave p{LEAVE_PCTL} of member-included"),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase().table("channels").update(
        {"playlist_thresholds": result}).eq("id", channel_id).execute()
    log.info("calibrate %s: join_high %.4f, join_low %.4f, leave %.4f (%d sims)",
             channel_id, result["join_high"], result["join_low"], result["leave"], len(apart))
    return result
