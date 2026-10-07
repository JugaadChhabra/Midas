"""Phase B · B3a — the human-edit ledger, description links (spec Part 2 §1.4, Part 3 B3; #33).

The SEO team edits descriptions by hand, and those edits are the benchmark
Midas has to beat. When sync re-reads a description, a link to one of our
videos that wasn't there before becomes one `human` backlinks intervention:

    video_links(text)                         -- 11-character ids of linked YouTube videos
    made_by_midas(video_id, description)      -- the one place that says "Midas wrote this"
    record_description_edits(channel_id, ...) -- diff before/after and record the additions

A removed link creates no intervention. It is listed in the payload of any
addition seen in the same edit, and stamped on the link's earlier intervention
if the ledger recorded one.

Detection timing: an old video's description is re-read only by a full sync,
every FULL_SYNC_INTERVAL (3 days, app/sync.py). `detected_at` is when the sync
saw the edit, not when it was made, and every row says so in its payload.

Idempotent: each row carries a `ledger_key` fixed by the edit (source, target,
the new description's hash), and the insert skips a key already stored
(migration 20261006030000).
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone

from app import interventions
from app.db import supabase
from app.rows import all_rows, rows_for_ids
from app.status_vocab import (
    AuditStatus,
    InterventionArm,
    InterventionLever,
    InterventionOrigin,
    InterventionStatus,
)

log = logging.getLogger("midas.human_edits")

# Phase A1.3's extraction found every YouTube link in a description and kept
# junk such as `ExampleURL3`. Tightened here to the URL forms that carry a video
# id, and to exactly 11 id characters: the lookahead refuses a longer token.
# Junk that happens to be 11 characters is dropped later, by _our_videos.
_VIDEO_LINK = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:[^\s#]*?&)?v=|shorts/|embed/|live/|v/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)

DETECTION_TIMING = (
    "detected_at is when a full sync saw this edit, not when it was made: old "
    "videos are re-read only by a full sync, every FULL_SYNC_INTERVAL (3 days)"
)


def video_links(text: str | None) -> set[str]:
    """The ids of YouTube videos linked from `text`."""
    return set(_VIDEO_LINK.findall(text or ""))


def _normalised(text: str | None) -> str:
    return " ".join((text or "").split())


def made_by_midas(video_id: str, description: str | None) -> bool:
    """Whether Midas itself wrote `description` onto the video.

    Phase B: any apply. That is an applied audit's suggested_description, or a
    reverted one's description_before (the revert wrote it back). Compared with
    whitespace collapsed, since YouTube may hand back different line endings.

    Slice 1 adds every `origin='midas'` intervention here (its payload / applied
    description). This function is the only check, so that is the one change.
    """
    target = _normalised(description)
    audits = all_rows(
        supabase().table("audits")
        .select("id,status,suggested_description,description_before")
        .eq("video_id", video_id)
        .in_("status", [AuditStatus.APPLIED, AuditStatus.REVERTED])
    )
    for a in audits:
        written = [a.get("suggested_description")]
        if a.get("status") == AuditStatus.REVERTED:
            written.append(a.get("description_before"))
        if any(w is not None and _normalised(w) == target for w in written):
            return True
    return False


def _our_videos(ids: set[str]) -> set[str]:
    """The subset of `ids` that are videos in `videos`, on any of our channels."""
    rows = rows_for_ids(
        lambda c: supabase().table("videos").select("id").in_("id", c), sorted(ids))
    return {r["id"] for r in rows}


def _ledger_key(video_id: str, target: str, description: str | None) -> str:
    digest = hashlib.sha256(_normalised(description).encode()).hexdigest()[:16]
    return f"{InterventionLever.BACKLINKS}:{video_id}:{target}:{digest}"


def _mark_removed(video_id: str, target: str, now: str) -> None:
    """Stamp the removal on the link's earlier human intervention, if any."""
    rows = all_rows(
        supabase().table("interventions")
        .select("ledger_key,payload")
        .eq("video_id", video_id)
        .eq("origin", InterventionOrigin.HUMAN)
        .eq("lever", InterventionLever.BACKLINKS)
    )
    for r in rows:
        payload = r.get("payload") or {}
        if (r.get("ledger_key") and payload.get("target_video_id") == target
                and "removed_detected_at" not in payload):
            supabase().table("interventions").update(
                {"payload": {**payload, "removed_detected_at": now}}
            ).eq("ledger_key", r["ledger_key"]).execute()


def _record_one(channel_id: str, video_id: str, after: str | None,
                added: set[str], removed: set[str], now: str) -> int:
    if made_by_midas(video_id, after):
        log.info("human_edits %s: description written by Midas; not a human edit", video_id)
        return 0
    recorded = 0
    for target in sorted(added):
        row = interventions.record(
            video_id=video_id,
            channel_id=channel_id,
            lever=InterventionLever.BACKLINKS,
            origin=InterventionOrigin.HUMAN,
            arm=InterventionArm.NOT_APPLICABLE,
            status=InterventionStatus.APPLIED,
            payload={
                "source_video_id": video_id,
                "target_video_id": target,
                "added_targets": sorted(added),
                "removed_targets": sorted(removed),
                "timing": DETECTION_TIMING,
            },
            detected_at=now,
            ledger_key=_ledger_key(video_id, target, after),
        )
        if row is not None:
            recorded += 1
    for target in sorted(removed):
        _mark_removed(video_id, target, now)
    if recorded:
        log.info("human_edits %s: %d human backlink(s) recorded (%s)",
                 video_id, recorded, ", ".join(sorted(added)))
    return recorded


def record_description_edits(channel_id: str,
                             changes: list[tuple[str, str | None, str | None]],
                             also_ours: set[str] = frozenset()) -> int:
    """Record the links the team added, for (video_id, before, after) descriptions.

    `also_ours` are ids known to be ours that may not be in `videos` yet: the
    sync calls this before its upsert, so a link to a video uploaded in the
    same batch would otherwise be dropped, and never seen again.

    Returns the number of interventions written. A failure on one video is
    logged and the others still run.
    """
    diffs: dict[str, tuple[str | None, set[str], set[str]]] = {}
    for video_id, before, after in changes:
        if _normalised(before) == _normalised(after):
            continue
        old, new = video_links(before) - {video_id}, video_links(after) - {video_id}
        if old != new:
            diffs[video_id] = (after, new - old, old - new)
    if not diffs:
        return 0

    linked = {t for _, added, removed in diffs.values() for t in added | removed}
    ours = (linked & set(also_ours)) | _our_videos(linked - set(also_ours))
    now = datetime.now(timezone.utc).isoformat()
    recorded = 0
    for video_id, (after, added, removed) in diffs.items():
        added, removed = added & ours, removed & ours
        if not added and not removed:
            continue
        try:
            recorded += _record_one(channel_id, video_id, after, added, removed, now)
        except Exception as e:
            log.exception("human_edits %s: ledger failed for %s: %s", channel_id, video_id, e)
    return recorded
