"""Phase B · B2 — the interventions record and the holdout split (spec Part 2 §1.3, §1.6, §7; #32).

Every lever writes here, and so does the human-edit ledger (B3):

    assign_arm(video_id, lever)  -- 'treated' | 'holdout', stable across processes
    active_for(video_id)         -- the video's open Midas intervention, or None
    record(...)                  -- insert one row, refusing a second open Midas one

The arm is a sha256 of (video_id, lever), never Python's hash(): that one is
salted per process, so a restart would reshuffle the arms mid-experiment. The
lever is in the hash so that being held out for one lever says nothing about
another.

One change at a time (§1.6) applies to Midas only. A human edit never blocks a
Midas change, and is never blocked by one: the ledger records what the team
did, whatever Midas is doing. The database enforces the same rule with a
partial unique index (migration 20261006020000), so two writers can't race
past the check here.

Nothing in Phase B creates `midas` interventions; they start in Slice 1.
"""
from __future__ import annotations

import hashlib

from app.config import settings
from app.db import supabase
from app.status_vocab import (
    ACTIVE_INTERVENTION_STATUSES,
    ALL_INTERVENTION_ARMS,
    ALL_INTERVENTION_LEVERS,
    ALL_INTERVENTION_ORIGINS,
    ALL_INTERVENTION_STATUSES,
    InterventionArm,
    InterventionOrigin,
)


class ActiveInterventionExists(Exception):
    """The video already has an open Midas intervention (spec Part 2 §1.6)."""


def _require(value: str, allowed: frozenset, what: str) -> None:
    if value not in allowed:
        raise ValueError(f"unknown intervention {what} {value!r}; expected one of {sorted(allowed)}")


def _bucket(video_id: str, lever: str) -> float:
    """A uniform point in [0, 1) fixed by (video_id, lever)."""
    digest = hashlib.sha256(f"{video_id}\x00{lever}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def assign_arm(video_id: str, lever: str) -> str:
    """'holdout' for about HOLDOUT_PCT of videos per lever, 'treated' for the rest."""
    _require(lever, ALL_INTERVENTION_LEVERS, "lever")
    if _bucket(video_id, lever) < settings.HOLDOUT_PCT:
        return InterventionArm.HOLDOUT
    return InterventionArm.TREATED


def active_for(video_id: str) -> dict | None:
    """The video's open Midas intervention, if any. Human ones never count."""
    rows = (
        supabase().table("interventions")
        .select("*")
        .eq("video_id", video_id)
        .eq("origin", InterventionOrigin.MIDAS)
        .in_("status", sorted(ACTIVE_INTERVENTION_STATUSES))
        .limit(1)
        .execute()
        .data or []
    )
    return rows[0] if rows else None


def record(*, video_id: str, channel_id: str, lever: str, origin: str, arm: str,
           status: str, payload: dict | None = None, before_state: dict | None = None,
           audit_id: int | None = None, strategy_version: str | None = None,
           triage_json: dict | None = None, applied_at: str | None = None,
           detected_at: str | None = None, ledger_key: str | None = None) -> dict | None:
    """Insert one intervention and return the stored row.

    Raises ActiveInterventionExists when this would be a second open Midas
    intervention on the video. A row that isn't open (declined, judged, ...)
    neither needs nor gets the check.

    With a `ledger_key` (the human-edit ledger, B3) the insert is idempotent:
    a row with the same key already stored means this one is skipped and None
    is returned (migration 20261006030000).
    """
    _require(lever, ALL_INTERVENTION_LEVERS, "lever")
    _require(origin, ALL_INTERVENTION_ORIGINS, "origin")
    _require(arm, ALL_INTERVENTION_ARMS, "arm")
    _require(status, ALL_INTERVENTION_STATUSES, "status")
    if origin == InterventionOrigin.HUMAN and arm != InterventionArm.NOT_APPLICABLE:
        # §1.4: human edits have no holdout; they're compared against unchanged videos.
        raise ValueError(f"human interventions take arm {InterventionArm.NOT_APPLICABLE!r}, not {arm!r}")

    if origin == InterventionOrigin.MIDAS and status in ACTIVE_INTERVENTION_STATUSES:
        existing = active_for(video_id)
        if existing is not None:
            raise ActiveInterventionExists(
                f"video {video_id} already has active Midas intervention "
                f"{existing.get('id')} ({existing.get('lever')}, {existing.get('status')})"
            )

    row = {
        "video_id": video_id,
        "channel_id": channel_id,
        "lever": lever,
        "origin": origin,
        "arm": arm,
        "status": status,
        "payload": payload,
        "before_state": before_state,
        "audit_id": audit_id,
        "strategy_version": strategy_version,
        "triage_json": triage_json,
        "applied_at": applied_at,
        "detected_at": detected_at,
    }
    if ledger_key is not None:
        row["ledger_key"] = ledger_key
        stored = (
            supabase().table("interventions")
            .upsert(row, on_conflict="ledger_key", ignore_duplicates=True)
            .execute().data or []
        )
        return stored[0] if stored else None
    return supabase().table("interventions").insert(row).execute().data[0]
