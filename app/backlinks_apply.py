"""Slice 1 · S1.3 — the description-only backlinks write and its revert (spec Part 4 S1.3, Part 2 §2.5; #64).

    apply_backlinks(intervention)     -- render the block onto the live description
    POST /interventions/{id}/revert   -- strip it from the live description

Not `build_update_payload` (Part 4 finding 3): that always sends category,
language and `status` fields and takes title and tags from the caller, and a
`videos.update` replaces the whole snippet. Here every write fetches the live
snippet (`videos.list`, 1u), changes only its `description`, and sends it back
with `part=snippet` (50u): title, tags, category and language stay as YouTube
had them, and no `status` is sent. The live description is the one that counts,
not the stored one: the team may have edited since the last sync.

Both refuse, sending nothing, while BACKLINK_APPLY_ENABLED is false, and when
the quota ledger can't afford `quota.APPLY` (51u). Under DRY_RUN neither calls
YouTube or writes anything. Refusals and YouTube failures are typed
(`apply_outcome.ApplyError`); nothing here changes an intervention's status on
failure, which is the caller's to record (S1.4).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app import backlinks, human_edits, quota
from app.apply_outcome import ApplyError, ApplyOutcome
from app.config import settings
from app.db import supabase
from app.status_vocab import (
    InterventionArm,
    InterventionLever,
    InterventionOrigin,
    InterventionStatus,
)
from app.youtube_client import (
    TokenExpiredError,
    youtube_for_channel,
    yt_videos_list_full,
    yt_videos_update,
)

log = logging.getLogger("midas.backlinks_apply")

router = APIRouter(tags=["interventions"])

SNIPPET_PART = "snippet"


def _require_affordable(what: str, cost: int) -> None:
    """The ledger gate. Raises before anything is sent."""
    if not quota.can_afford(cost):
        raise ApplyError(
            ApplyOutcome.QUOTA_INSUFFICIENT,
            f"quota_insufficient: {what} needs {cost} units, "
            f"{quota.units_remaining()} remaining today",
        )


def _classified(e: Exception) -> ApplyError:
    if isinstance(e, TokenExpiredError):
        return ApplyError(ApplyOutcome.TOKEN_EXPIRED)
    if "quotaExceeded" in str(e):
        return ApplyError(ApplyOutcome.QUOTA_EXCEEDED)
    return ApplyError(ApplyOutcome.FAILED, f"YouTube update failed: {e}")


def _live_snippet(channel_id: str, video_id: str):
    """Fetch the video's live snippet (1u). Returns (client, snippet)."""
    try:
        yt = youtube_for_channel(channel_id)
        items = yt_videos_list_full(yt, channel_id, [video_id])
    except Exception as e:
        raise _classified(e)
    if not items:
        raise ApplyError(ApplyOutcome.FAILED, f"video {video_id} not found on YouTube")
    return yt, items[0]["snippet"]


def _send_snippet(yt, channel_id: str, video_id: str, snippet: dict) -> None:
    """Send `snippet` back with `part=snippet` (50u): no `status` part."""
    try:
        yt_videos_update(yt, channel_id, {"id": video_id, "snippet": snippet},
                         parts=SNIPPET_PART)
    except Exception as e:
        raise _classified(e)


def _write_description(channel_id: str, video_id: str, new_description) -> tuple[str, str]:
    """Fetch the live snippet, replace only its description, send it back.

    `new_description(live)` gives the text to write. Returns (live, written).
    """
    yt, snippet = _live_snippet(channel_id, video_id)
    live = snippet.get("description") or ""
    written = _rendered(new_description, live)
    if written == live:
        return live, written            # nothing to change (a revert with no block left)
    _send_snippet(yt, channel_id, video_id, {**snippet, "description": written})
    return live, written


def _rendered(new_description, description: str | None) -> str:
    try:
        return new_description(description)
    except backlinks.RenderRefused as e:
        raise ApplyError(ApplyOutcome.FAILED, f"render refused: {e}")


def _require_plannable(intervention: dict) -> None:
    if (intervention.get("origin") != InterventionOrigin.MIDAS
            or intervention.get("lever") != InterventionLever.BACKLINKS
            or intervention.get("arm") != InterventionArm.TREATED
            or intervention.get("status") != InterventionStatus.PLANNED):
        raise ValueError(
            f"intervention {intervention.get('id')} is not a planned, treated Midas "
            f"backlinks intervention")
    if not (intervention.get("payload") or {}).get("targets"):
        raise ValueError(f"intervention {intervention.get('id')} has no targets")


def _record_unseen_edit(channel_id: str, video_id: str, stored: str | None, live: str) -> None:
    """Hand a team edit made since the last sync to the ledger before the stored
    description is overwritten, or it would never be seen. Never fails the write."""
    try:
        human_edits.record_description_edits(channel_id, [(video_id, stored, live)])
    except Exception as e:
        log.exception("backlinks %s: human-edit ledger failed; apply continues: %s", video_id, e)


def apply_backlinks(intervention: dict) -> dict:
    """Write a planned, treated Midas backlinks intervention's block to YouTube.

    `intervention` is its row; `payload.targets` are S1.1's `{video_id, title}`
    rows, in link order. On success the row becomes `measuring` with
    `applied_at`, `before_state = {description: live}` and the rendered text in
    `payload.description`, and `videos.description` is the rendered text, so the
    next sync sees no diff. Raises ApplyError (nothing sent, or YouTube refused)
    or ValueError (not an intervention this applies to).
    """
    if not settings.BACKLINK_APPLY_ENABLED:
        raise ApplyError(ApplyOutcome.APPLY_DISABLED)
    _require_plannable(intervention)
    video_id, channel_id = intervention["video_id"], intervention["channel_id"]
    targets = intervention["payload"]["targets"]
    channel = supabase().table("channels").select("default_language").eq(
        "id", channel_id).single().execute().data or {}
    language = channel.get("default_language")
    video = supabase().table("videos").select("description").eq(
        "id", video_id).single().execute().data or {}

    # Rendered onto the stored text first, so a refusal (no heading, too many
    # targets) costs no YouTube call. The write renders again onto the live text.
    rendered = _rendered(lambda d: backlinks.render(d, targets, language),
                         video.get("description"))
    if settings.DRY_RUN:
        log.warning("[DRY_RUN] would add backlinks to %s: %s", video_id,
                    [t["video_id"] for t in targets])
        return {"status": "dry_run", "description": rendered}

    _require_affordable("backlinks apply", quota.cost_of(*quota.APPLY))
    live, rendered = _write_description(
        channel_id, video_id, lambda live: backlinks.render(live, targets, language))
    if live != (video.get("description") or ""):
        _record_unseen_edit(channel_id, video_id, video.get("description"), live)

    now = datetime.now(timezone.utc).isoformat()
    supabase().table("interventions").update({
        "status": InterventionStatus.MEASURING,
        "applied_at": now,
        "before_state": {"description": live},
        "payload": {**intervention["payload"], "description": rendered},
    }).eq("id", intervention["id"]).execute()
    supabase().table("videos").update({
        "description": rendered,
        "last_fetched_at": now,
    }).eq("id", video_id).execute()
    log.info("backlinks %s: block applied (intervention %s, targets %s)", video_id,
             intervention["id"], [t["video_id"] for t in targets])
    return {"status": InterventionStatus.MEASURING, "description": rendered}


@router.post("/interventions/{intervention_id}/revert")
def revert_intervention(intervention_id: int):
    """Remove an applied Midas backlinks block from the video's live description.

    An applied Midas title row goes to `titles_apply.revert_title` (S3.1), with
    its own gates.

    Strips every canonical block (`backlinks.strip`), so anything else the team
    changed since the apply stays. The intervention becomes `cancelled`, with
    the revert in `payload.revert`. 409 `quota_insufficient` when the ledger
    can't afford it, as `POST /audits/{id}/revert`, and 409 `apply_disabled`
    while BACKLINK_APPLY_ENABLED is false.
    """
    row = supabase().table("interventions").select("*").eq(
        "id", intervention_id).single().execute().data
    if not row:
        raise HTTPException(404, "Intervention not found")
    if row.get("lever") == InterventionLever.TITLE:
        from app import titles_apply        # it imports this module's helpers
        try:
            return titles_apply.revert_title(row, auto=False)
        except ValueError:
            raise HTTPException(400, "Only an applied Midas title intervention can be reverted")
    if (row.get("origin") != InterventionOrigin.MIDAS
            or row.get("lever") != InterventionLever.BACKLINKS
            or not row.get("applied_at")
            or row.get("status") == InterventionStatus.CANCELLED):
        raise HTTPException(400, "Only an applied Midas backlinks intervention can be reverted")
    video_id, channel_id = row["video_id"], row["channel_id"]

    if not settings.BACKLINK_APPLY_ENABLED:
        raise ApplyError(ApplyOutcome.APPLY_DISABLED)
    if settings.DRY_RUN:
        video = supabase().table("videos").select("description").eq(
            "id", video_id).single().execute().data or {}
        stripped = backlinks.strip(video.get("description"))
        log.warning("[DRY_RUN] would revert backlinks on %s", video_id)
        return {"status": "dry_run", "description": stripped}

    _require_affordable("revert", quota.cost_of(*quota.APPLY))
    live, stripped = _write_description(channel_id, video_id, backlinks.strip)

    now = datetime.now(timezone.utc).isoformat()
    supabase().table("interventions").update({
        "status": InterventionStatus.CANCELLED,
        "payload": {**(row.get("payload") or {}),
                    "revert": {"reverted_at": now, "live_before": live, "description": stripped}},
    }).eq("id", intervention_id).execute()
    supabase().table("videos").update({
        "description": stripped,
        "last_fetched_at": now,
    }).eq("id", video_id).execute()
    log.info("backlinks %s: block reverted (intervention %s)", video_id, intervention_id)
    return {"status": InterventionStatus.CANCELLED, "description": stripped}
