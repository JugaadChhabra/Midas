from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.db import supabase
from app.embeddings import bootstrap_embeddings
from app.openrouter import EMBED_MODEL
from app.playlists import reconcile_channel, _record_assignment
from app.playlists_sync import sync_playlists
from app.playlist_health import score_channel
from app.youtube_client import youtube_for_channel, yt_playlist_items_insert, yt_playlist_items_delete
from app.playlists import _current_members

router = APIRouter(tags=["playlists"])


# Phase 1B health endpoints (PHASE_1B_PLAN.md §6).
# Recommend-only — these never invoke YouTube write APIs.

# Recommendation render order — most-actionable first so the UI can render
# top-down without an extra sort step.
_REC_PRIORITY = {
    "remove": 0,
    "revive": 1,
    "keep": 2,
    "insufficient_data": 3,
    None: 4,
}


def _check_channel(channel_id: str) -> dict:
    """Load the channel row or raise 404 — used by both health endpoints."""
    row = (
        supabase().table("channels")
        .select("id,name,playlist_health_enabled")
        .eq("id", channel_id)
        .maybe_single()
        .execute()
        .data
    )
    if not row:
        raise HTTPException(404, f"channel {channel_id} not found")
    return row


def _serialize_playlists(channel_id: str) -> list[dict]:
    """Read back the playlists table for a channel, sorted recommendation-first."""
    rows = (
        supabase().table("playlists")
        .select(
            "id,title,role,origin,item_count,"
            "health_score,health_recommendation,health_computed_at,health_rationale_json"
        )
        .eq("channel_id", channel_id)
        .execute()
        .data or []
    )
    # Sort: action priority first, then score ascending (lowest = worst).
    rows.sort(key=lambda r: (
        _REC_PRIORITY.get(r.get("health_recommendation"), 4),
        # None scores last within their priority bucket; sort by negative
        # would flip the sense, so substitute +inf when missing.
        r.get("health_score") if r.get("health_score") is not None else float("inf"),
    ))
    out: list[dict] = []
    for r in rows:
        rationale = r.get("health_rationale_json") or {}
        out.append({
            "playlist_id": r["id"],
            "title": r.get("title"),
            "role": r.get("role"),
            "origin": r.get("origin"),
            "item_count": r.get("item_count"),
            "current_score": r.get("health_score"),
            # Hoisted from rationale to top-level per PHASE_1B_PLAN.md §6.2
            # so UI consumers don't have to reach into the JSONB blob for
            # the most-commonly-displayed number.
            "percentile": rationale.get("percentile"),
            "action": r.get("health_recommendation"),
            "computed_at": r.get("health_computed_at"),
            "rationale": rationale,
        })
    return out


def _envelope(channel_id: str, enabled: bool, computed_at: str | None) -> dict:
    """Common response shape per PHASE_1B_PLAN.md §6.2."""
    return {
        "enabled": enabled,
        "channel_id": channel_id,
        "computed_at": computed_at,
        "window": {
            "weeks": settings.PLAYLIST_HEALTH_AGG_WEEKS,
            "min_starts_gate": settings.MIN_PLAYLIST_STARTS,
        },
        "thresholds": {
            "remove_pctl": settings.PLAYLIST_HEALTH_REMOVE_PCTL,
            "revive_pctl": settings.PLAYLIST_HEALTH_REVIVE_PCTL,
        },
        # Hardcoded false until Phase 1B Step B (Gap 6 — insightTrafficSource=PLAYLIST
        # member breakdown — see PHASE_1B_PLAN.md §9) lands. Every rationale
        # also carries tier_2_pending=true; this is the per-response mirror.
        "tier_2_available": False,
        "recommendations": [],
    }


@router.post("/channels/{channel_id}/playlists/evaluate")
def evaluate_playlists(channel_id: str):
    """Re-score this channel and return fresh recommendations.

    Honours the per-channel `playlist_health_enabled` flag — if off, returns
    an empty envelope with `enabled=false` (200, not 403; it's a UI
    affordance, not a security gate). Recommend-only: never mutates
    YouTube; only writes to `playlists.health_*` via score_channel.
    """
    channel = _check_channel(channel_id)
    if not channel.get("playlist_health_enabled"):
        return _envelope(channel_id, enabled=False, computed_at=None)

    summary = score_channel(channel_id)
    body = _envelope(channel_id, enabled=True, computed_at=summary.get("computed_at"))
    body["summary"] = {
        "playlists_total": summary["playlists_total"],
        "gated_in": summary["gated_in"],
        "insufficient_data": summary["insufficient_data"],
        "remove": summary["remove"],
        "revive": summary["revive"],
        "keep": summary["keep"],
    }
    body["recommendations"] = _serialize_playlists(channel_id)
    return body


@router.get("/channels/{channel_id}/playlists/health")
def get_playlist_health(channel_id: str):
    """Read the LAST stored scoring without re-running.

    Useful for the UI's initial paint and for ops debugging — does not pay
    the score_channel cost. Same shape as POST /evaluate so the UI can
    consume one envelope.
    """
    channel = _check_channel(channel_id)
    if not channel.get("playlist_health_enabled"):
        return _envelope(channel_id, enabled=False, computed_at=None)
    recommendations = _serialize_playlists(channel_id)
    # Latest computed_at across all rows == when the most recent score_channel
    # call landed for this channel. Use it as the envelope's computed_at.
    computed_ats = [r["computed_at"] for r in recommendations if r.get("computed_at")]
    latest = max(computed_ats) if computed_ats else None
    body = _envelope(channel_id, enabled=True, computed_at=latest)
    body["recommendations"] = recommendations
    return body


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
