"""Sync YouTube playlists and their membership into the local DB.

Called once at bootstrap and then daily to stay in sync with manual changes
made directly in YouTube Studio.

Phase 1B addition: also populates `role`, `origin`, `item_count`,
`last_synced_at` on the `playlists` row so the recommend-only health-score
job (app/playlist_health.py — Step 2) has the inventory metadata it needs.
"""
import logging
import re
from datetime import datetime, timezone

from app.db import supabase
from app.youtube_client import youtube_for_channel, yt_playlists_list, yt_playlist_items_page

log = logging.getLogger("midas.playlists_sync")


# Role classification — regex-only, conservative (PHASE_1B_PLAN.md §4.2).
# Order matters: first match wins. LLM-based classification is a deliberate
# future upgrade; regex misses are acceptable (default `'inherited'` is
# harmless to downstream scoring — only changes the UI badge).
#
# Bare `season|chapter|lesson` were rejected because they false-positive on
# unrelated playlists ("Chapter Books for Kids", "Lesson Plans for Teachers",
# "Season Cooking"). All series matchers now require a numeric qualifier OR
# the unambiguous `episode` keyword.
_SERIES_RX = re.compile(
    r"\b("
    r"episode"               # unambiguous standalone
    r"|ep\.?\s*\d+"          # Ep 5, Ep. 12
    r"|part\s*\d+"           # Part 1
    r"|season\s*\d+"         # Season 2
    r"|chapter\s*\d+"        # Chapter 3
    r"|lesson\s*\d+"         # Lesson 7
    r")\b",
    re.IGNORECASE,
)
_FUNNEL_RX = re.compile(
    r"^\s*(start\s+here|watch\s+first|beginners?|intro\s+to)\b",
    re.IGNORECASE,
)


def _classify_role(title: str, description: str) -> str:
    """Heuristic role classification.

    Returns one of: 'series', 'funnel', 'inherited'. PO's `topic_cluster`
    role needs LLM judgment to detect reliably from title alone and is
    deliberately left to a follow-up — better to default conservatively
    than mislabel.
    """
    text = f"{title or ''} {description or ''}"
    if _SERIES_RX.search(text):
        return "series"
    if _FUNNEL_RX.match(title or ""):
        return "funnel"
    return "inherited"


def sync_playlists(channel_id: str) -> dict:
    """Fetch all playlists + their members from YouTube and seed the local tables.

    Existing rows are upserted (title/description may have changed). Membership
    rows are only inserted for (video_id, playlist_id) pairs not already present
    in playlist_assignments — we never overwrite system-generated decisions.

    Returns {"playlists": int, "memberships_seeded": int}.
    """
    yt = youtube_for_channel(channel_id)

    # 1. Fetch all playlists for the channel
    yt_playlists = yt_playlists_list(yt, channel_id)
    if not yt_playlists:
        log.info("No playlists found for channel %s", channel_id)
        return {"playlists": 0, "memberships_seeded": 0}

    now = datetime.now(timezone.utc).isoformat()

    # Preserve provenance set by other code paths (notably Phase 2B's
    # optimizer-created path). Without this read, every daily sync would
    # silently clobber `origin='optimizer_created'` back to `'inherited'`
    # and overwrite any non-regex `role` classification (e.g. a future LLM
    # classifier or a manual override) with whatever the regex returns.
    existing_rows = (
        supabase().table("playlists")
        .select("id,origin,role")
        .eq("channel_id", channel_id)
        .in_("id", [p["id"] for p in yt_playlists])
        .execute()
    ).data or []
    existing_by_id: dict[str, dict] = {r["id"]: r for r in existing_rows}

    def _preserved_origin(playlist_id: str) -> str:
        existing = existing_by_id.get(playlist_id)
        if existing and existing.get("origin") and existing["origin"] != "inherited":
            return existing["origin"]
        return "inherited"

    def _preserved_role(playlist_id: str, title: str, description: str) -> str:
        # If a previous run (or another code path) classified this playlist
        # as anything other than the default `'inherited'`, keep that value.
        # This lets a future LLM classifier or manual override survive daily
        # re-syncs. If existing role is NULL or `'inherited'`, re-run the
        # regex — handles freshly-renamed playlists picking up a series tag.
        existing = existing_by_id.get(playlist_id)
        if existing and existing.get("role") and existing["role"] != "inherited":
            return existing["role"]
        return _classify_role(title, description)

    # Upsert playlist rows. Phase 1B writes role / origin / item_count /
    # last_synced_at alongside the existing fields. `synced_at` is kept for
    # backward compat with the legacy playlist allocator; `last_synced_at`
    # is the PO-spec name (PHASE_1B_PLAN.md §3.1) consumers should prefer.
    # TODO(phase-2x): drop synced_at once no callers consume it.
    supabase().table("playlists").upsert(
        [
            {
                "id": p["id"],
                "channel_id": channel_id,
                "title": p["title"],
                "description": p["description"],
                "synced_at": now,
                "last_synced_at": now,
                "origin": _preserved_origin(p["id"]),
                "role": _preserved_role(p["id"], p["title"], p["description"]),
                "item_count": p.get("item_count"),
                # created_by_optimizer_at and strategy_version stay NULL —
                # only Phase 2B's optimizer-created path writes them.
            }
            for p in yt_playlists
        ],
        on_conflict="id",
    ).execute()
    log.info("Synced %d playlists for channel %s", len(yt_playlists), channel_id)

    # 2. For each playlist, fetch members and seed playlist_assignments
    # Load all video IDs we know about so we can skip orphaned YouTube videos
    known_videos = {
        v["id"]
        for v in (
            supabase().table("videos")
            .select("id")
            .eq("channel_id", channel_id)
            .execute()
        ).data or []
    }

    # Load existing (video_id, playlist_id) pairs for these playlists only
    # to avoid duplicate sync rows
    playlist_ids = [p["id"] for p in yt_playlists]
    existing_pairs = {
        (r["video_id"], r["playlist_id"])
        for r in (
            supabase().table("playlist_assignments")
            .select("video_id,playlist_id")
            .in_("playlist_id", playlist_ids)
            .execute()
        ).data or []
    }

    memberships_seeded = 0
    for playlist in yt_playlists:
        playlist_id = playlist["id"]
        page_token = None
        while True:
            resp = yt_playlist_items_page(yt, channel_id, playlist_id, page_token)
            for item in resp.get("items", []):
                playlist_item_id = item["id"]
                video_id = item["contentDetails"]["videoId"]

                if video_id not in known_videos:
                    continue  # video not in our DB yet
                if (video_id, playlist_id) in existing_pairs:
                    continue  # already tracked

                supabase().table("playlist_assignments").insert({
                    "video_id": video_id,
                    "playlist_id": playlist_id,
                    "playlist_item_id": playlist_item_id,
                    "action": "added",
                    "decision_source": "sync",
                    "decided_at": now,
                }).execute()
                existing_pairs.add((video_id, playlist_id))
                memberships_seeded += 1

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    log.info(
        "sync_playlists(%s): seeded %d membership rows",
        channel_id, memberships_seeded,
    )
    return {"playlists": len(yt_playlists), "memberships_seeded": memberships_seeded}
