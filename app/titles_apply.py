"""Slice 3 · S3.1 — the title-only write and its revert (spec Part 6 S3.1, Part 2 §2.5, F1; #115).

    apply_title(intervention)            -- write `payload.title` to the live snippet
    revert_title(intervention, *, auto)  -- put `before_state.title` back
                                            (POST /interventions/{id}/revert, and S3.5)

The twin of app/backlinks_apply.py for `snippet.title`: every write fetches the
live snippet (`videos.list`, 1u), changes only its `title`, and sends it back
with `part=snippet` (50u). Description (with any backlink block), tags,
category and language stay as YouTube had them, and no `status` is sent.

Both refuse, sending nothing, while TITLE_APPLY_ENABLED is false, and when the
quota ledger can't afford `quota.APPLY` (51u). Under DRY_RUN neither calls
YouTube or writes anything. Neither overwrites a title someone else changed:
the apply wants the live title to be `payload.title_before` (as triage saw it),
the revert wants it to be `payload.title` (as Midas wrote it), else
`title_changed` and nothing is sent. Failures are typed
(`apply_outcome.ApplyError`); nothing here changes an intervention's status on
failure, which is the caller's to record.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from app import quota
from app.apply_outcome import ApplyError, ApplyOutcome
from app.backlinks_apply import _live_snippet, _require_affordable, _send_snippet
from app.config import settings
from app.db import supabase
from app.status_vocab import (
    InterventionArm,
    InterventionLever,
    InterventionOrigin,
    InterventionStatus,
)

log = logging.getLogger("midas.titles_apply")

#: The detail of a refusal because the live title isn't the one expected.
TITLE_CHANGED = "title_changed"


def _require_plannable(intervention: dict) -> None:
    payload = intervention.get("payload") or {}
    if (intervention.get("origin") != InterventionOrigin.MIDAS
            or intervention.get("lever") != InterventionLever.TITLE
            or intervention.get("arm") != InterventionArm.TREATED
            or intervention.get("status") != InterventionStatus.PLANNED):
        raise ValueError(
            f"intervention {intervention.get('id')} is not a planned, treated Midas "
            f"title intervention")
    if not payload.get("title") or payload.get("title_before") is None:
        raise ValueError(
            f"intervention {intervention.get('id')} has no title or title_before")


def _require_revertable(intervention: dict) -> None:
    if (intervention.get("origin") != InterventionOrigin.MIDAS
            or intervention.get("lever") != InterventionLever.TITLE
            or not intervention.get("applied_at")
            or intervention.get("status") == InterventionStatus.CANCELLED):
        raise ValueError(
            f"intervention {intervention.get('id')} is not an applied Midas title intervention")


def _write_title(channel_id: str, video_id: str, expected: str, title: str,
                 refusal: Exception) -> str:
    """Fetch the live snippet; if its title is `expected`, replace only the
    title with `title` and send it back. Else raise `refusal`, sending nothing.
    Returns the live title."""
    yt, snippet = _live_snippet(channel_id, video_id)
    live = snippet.get("title") or ""
    if live != expected:
        raise refusal
    _send_snippet(yt, channel_id, video_id, {**snippet, "title": title})
    return live


def _store_title(video_id: str, title: str, now: str) -> None:
    supabase().table("videos").update({
        "title": title,
        "last_fetched_at": now,
    }).eq("id", video_id).execute()


def apply_title(intervention: dict) -> dict:
    """Write a planned, treated Midas title intervention's `payload.title` to YouTube.

    On success the row becomes `measuring` with `applied_at` and
    `before_state = {title: live}`, and `videos.title` is the new title. Raises
    ApplyError (nothing sent, the title changed since triage, or YouTube
    refused) or ValueError (not an intervention this applies to).
    """
    if not settings.TITLE_APPLY_ENABLED:
        raise ApplyError(ApplyOutcome.APPLY_DISABLED)
    _require_plannable(intervention)
    video_id, channel_id = intervention["video_id"], intervention["channel_id"]
    payload = intervention["payload"]
    title = payload["title"]
    if settings.DRY_RUN:
        log.warning("[DRY_RUN] would retitle %s: %r", video_id, title)
        return {"status": "dry_run", "title": title}

    _require_affordable("title apply", quota.cost_of(*quota.APPLY))
    live = _write_title(channel_id, video_id, payload["title_before"], title,
                        ApplyError(ApplyOutcome.FAILED, TITLE_CHANGED))

    now = datetime.now(timezone.utc).isoformat()
    supabase().table("interventions").update({
        "status": InterventionStatus.MEASURING,
        "applied_at": now,
        "before_state": {"title": live},
    }).eq("id", intervention["id"]).execute()
    _store_title(video_id, title, now)
    log.info("title %s: applied (intervention %s)", video_id, intervention["id"])
    return {"status": InterventionStatus.MEASURING, "title": title}


def revert_title(intervention: dict, *, auto: bool) -> dict:
    """Put an applied Midas title intervention's `before_state.title` back.

    Only while the live title is still `payload.title`: a title the team
    changed since is theirs, and the revert refuses with 409 `title_changed`.
    The intervention becomes `cancelled`, with the revert in `payload.revert`
    (`auto`: S3.5's automatic revert, else a person's). Raises ApplyError
    (`apply_disabled`, `quota_insufficient`, YouTube failures), HTTPException
    409 `title_changed`, or ValueError (not an intervention this reverts).
    """
    _require_revertable(intervention)
    video_id, channel_id = intervention["video_id"], intervention["channel_id"]
    title = (intervention.get("before_state") or {}).get("title")
    if title is None:
        raise ValueError(f"intervention {intervention.get('id')} has no before_state.title")

    if not settings.TITLE_APPLY_ENABLED:
        raise ApplyError(ApplyOutcome.APPLY_DISABLED)
    if settings.DRY_RUN:
        log.warning("[DRY_RUN] would revert the title of %s to %r", video_id, title)
        return {"status": "dry_run", "title": title}

    _require_affordable("revert", quota.cost_of(*quota.APPLY))
    live = _write_title(channel_id, video_id, intervention["payload"]["title"], title,
                        HTTPException(409, TITLE_CHANGED))

    now = datetime.now(timezone.utc).isoformat()
    supabase().table("interventions").update({
        "status": InterventionStatus.CANCELLED,
        "payload": {**(intervention.get("payload") or {}),
                    "revert": {"reverted_at": now, "live_before": live, "title": title,
                               "auto": auto}},
    }).eq("id", intervention["id"]).execute()
    _store_title(video_id, title, now)
    log.info("title %s: reverted (intervention %s, auto %s)", video_id,
             intervention["id"], auto)
    return {"status": InterventionStatus.CANCELLED, "title": title}
