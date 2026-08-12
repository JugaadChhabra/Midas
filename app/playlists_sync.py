"""Sync YouTube playlists and their membership into the local DB.

Called once at bootstrap and then daily to stay in sync with manual changes
made directly in YouTube Studio.

Phase 1B addition: also populates `role`, `origin`, `item_count`,
`last_synced_at` on the `playlists` row so the recommend-only health-score
job (app/playlist_health.py — Step 2) has the inventory metadata it needs.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from app import quota
from app.config import settings
from app.db import supabase
from app.quota import JobBudget
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


def _rotation_cutoff() -> str | None:
    """ISO timestamp before which a playlist is due a rotation walk.

    None when rotation is disabled (PLAYLIST_FULL_WALK_DAYS=0), which makes
    `_needs_walk` fall back to the itemCount signal alone.
    """
    days = settings.PLAYLIST_FULL_WALK_DAYS
    if days <= 0:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _walk_plan(yt_playlists: list[dict], existing_by_id: dict[str, dict],
               cutoff: str | None) -> list[dict]:
    """Which playlists to walk, most-informative first.

    Two reasons to walk, and the order between them is the point: a playlist
    whose itemCount moved has *known* drift, while a rotation candidate only
    might. Under a budget that cannot cover everything, known drift must be
    walked first — so `changed` sorts ahead of `rotation`, and within each group
    the least-recently-walked goes first (NULL = never, sorts first) so the
    backlog drains in a fair, resumable order instead of re-walking one head.
    """
    plan = []
    for p in yt_playlists:
        existing = existing_by_id.get(p["id"])
        walked_at = (existing or {}).get("membership_walked_at")
        if existing is None:
            reason = "new"
        elif p.get("item_count") is None or p["item_count"] != existing.get("item_count"):
            # item_count None = YouTube did not report a count, so we cannot
            # conclude "unchanged". Walk rather than assume.
            reason = "changed"
        elif cutoff is not None and (walked_at is None or walked_at < cutoff):
            reason = "rotation"
        else:
            continue
        plan.append({
            "id": p["id"],
            "item_count": p.get("item_count"),
            "reason": reason,
            "walked_at": walked_at,
        })
    # "new" and "changed" rank together — both are observed drift, unlike
    # rotation which is a precaution.
    plan.sort(key=lambda e: (e["reason"] == "rotation", e["walked_at"] or ""))
    return plan


def sync_playlists(channel_id: str, budget: JobBudget | None = None) -> dict:
    """Sync inventory + membership, spending at most `budget` on the walk.

    Opens the quota.spending() block itself rather than trusting the caller to:
    a budget that is asked for permission but never told what was spent answers
    yes forever, which is an unbounded walk wearing a cap. Handing the budget in
    and having it counted are now the same act.
    """
    if budget is None:
        return _sync_playlists(channel_id, None)
    with quota.spending(budget):
        return _sync_playlists(channel_id, budget)


def _sync_playlists(channel_id: str, budget: JobBudget | None) -> dict:
    """Fetch all playlists + their members from YouTube and seed the local tables.

    Existing rows are upserted (title/description may have changed). Membership
    rows are only inserted for (video_id, playlist_id) pairs not already present
    in playlist_assignments — we never overwrite system-generated decisions.

    `budget` bounds what the membership walk may spend (see JobBudget). When it
    runs out the walk stops early and the unwalked playlists are picked up by
    the next run — nothing is lost, only deferred. Pass None (the default, and
    what the manual endpoint does) for the unbounded walk.

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
        .select("id,origin,role,item_count,membership_walked_at")
        .eq("channel_id", channel_id)
        .in_("id", [p["id"] for p in yt_playlists])
        .execute()
    ).data or []
    existing_by_id: dict[str, dict] = {r["id"]: r for r in existing_rows}

    # Decide what to walk BEFORE the upsert below, because the upsert must not
    # write a new item_count for anything still owed a walk — see the comment
    # on `_deferred_item_count`.
    plan = _walk_plan(yt_playlists, existing_by_id, _rotation_cutoff())
    planned_ids = {e["id"] for e in plan}

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

    def _deferred_item_count(playlist_id: str, cur_count):
        """The item_count to persist now.

        For a playlist we are about to walk, persist the PREVIOUS count, not
        YouTube's current one. The count is the drift signal: writing it before
        the walk means a walk the budget cuts short (or a crash mid-pass) leaves
        the row claiming a membership we never read, and tomorrow's plan sees
        "unchanged" and skips it — the change is lost until rotation. The real
        count is written by `_stamp_walked` once the walk actually completes.
        """
        if playlist_id in planned_ids:
            return (existing_by_id.get(playlist_id) or {}).get("item_count")
        return cur_count

    def _stamp_walked(playlist_id: str, item_count) -> None:
        """Record a COMPLETED membership walk: count observed, clock reset."""
        supabase().table("playlists").update({
            "item_count": item_count,
            "membership_walked_at": now,
        }).eq("id", playlist_id).execute()

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
                "item_count": _deferred_item_count(p["id"], p.get("item_count")),
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

    # Incremental walk: re-reading a playlist's full membership every day is the
    # fleet's dominant YouTube-quota cost (one 50-item page per unit, thousands
    # of pages/day on large channels) and almost never surfaces anything new.
    # `_walk_plan` decides who is owed a walk — changed counts first, then the
    # rotation candidates that guard against equal-count swaps — and `budget`
    # bounds how far down that list this run gets.
    # Asked before each page; the spend itself is counted by quota.charge inside
    # the wrapper, under the quota.spending() block the caller opened. Asking is
    # explicit because stopping is a decision; counting is not.
    _PAGE = quota.cost(quota.Op.PLAYLIST_ITEMS_LIST)

    memberships_seeded = 0
    walked = truncated = 0
    for entry in plan:
        playlist_id = entry["id"]
        if budget is not None and not budget.can_spend(_PAGE):
            # Out of budget. Everything left in the plan keeps its stale
            # item_count and old membership_walked_at, so the next run re-plans
            # it and — ordered by walked_at — starts from here.
            truncated = len(plan) - walked
            log.info(
                "sync_playlists(%s): budget exhausted (%s); %d playlists deferred",
                channel_id, budget, truncated,
            )
            break

        page_token = None
        complete = False
        while not complete:
            if budget is not None and not budget.can_spend(_PAGE):
                # Mid-playlist stop. Deliberately NOT stamped: a partially read
                # membership must not look walked, or the pages past this point
                # would never be read.
                break
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
            complete = not page_token

        if not complete:
            truncated = len(plan) - walked
            log.info(
                "sync_playlists(%s): budget exhausted mid-walk of %s (%s); "
                "%d playlists deferred",
                channel_id, playlist_id, budget, truncated,
            )
            break
        walked += 1
        _stamp_walked(playlist_id, entry["item_count"])

    skipped_unchanged = len(yt_playlists) - len(plan)
    log.info(
        "sync_playlists(%s): %d playlists (%d walked, %d skipped unchanged, "
        "%d deferred over budget), seeded %d membership rows",
        channel_id, len(yt_playlists), walked, skipped_unchanged, truncated,
        memberships_seeded,
    )
    return {
        "playlists": len(yt_playlists),
        "planned": len(plan),
        "walked": walked,
        "skipped_unchanged": skipped_unchanged,
        "deferred_over_budget": truncated,
        "memberships_seeded": memberships_seeded,
    }
