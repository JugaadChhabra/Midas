"""Which channels a job runs for.

Every scheduled pass needs the same answer and used to derive it separately:
autopilot with an `or_` of two flags plus a Python re-filter, reporting_poll with
an `analytics_authorized` filter conditionally narrowed by an env flag,
metrics_poll with the same filter plus a third flag passed downward as a keyword,
main with an env allowlist intersected against every id in Python, and another
main job with a single flag `eq`. Six shapes over one table, plus a seventh that
skipped the table entirely.

The cost of that spread was not the duplication. It was that a channel's real
eligibility — env setting AND per-channel flag AND, for shorts, a NAS folder and
a concurrency cap — was never written down in one place, so `config.py` grew a
knob every time the answer changed and the audit predicate ended up expressed
four different ways (twice in autopilot, once in the dashboard, once in JS).

This module owns the question. Callers name the job, not the filter.

What it does NOT own: which columns you need (say so — projections vary for good
reasons, and the dashboard deliberately avoids reading OAuth tokens), and what
order to visit them in. Ordering is per-job policy that reads other tables
(reconcile fairness reads `playlists`) and stays with the callers.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.db import supabase
from app.rows import all_rows

log = logging.getLogger("midas.eligibility")


class Job:
    """A per-channel pass. Not persisted — internal vocabulary only."""

    #: autopilot's metadata path (audit → apply)
    AUDIT = "audit"
    #: autopilot's NAS shorts-cutting path
    SHORTS = "shorts"
    #: either autopilot path — what a tick actually looks for
    AUTOPILOT = "autopilot"
    #: reporting_poll — reach CSV ingestion
    REACH = "reach"
    #: metrics_poll — on-demand Analytics (views/retention)
    ANALYTICS = "analytics"
    #: playlist_health scoring
    PLAYLIST_HEALTH = "playlist_health"
    #: the nightly playlist inventory + membership reconcile
    RECONCILE = "reconcile"
    #: passes that deliberately run for every channel
    EVERY = "every"


# ── Per-channel predicates ────────────────────────────────────────────────
#
# Read a row, answer a question. Separate from the queries below because a tick
# re-checks eligibility on a row it already holds: a channel can be picked for
# shorts while its audit path is paused, so the pause is re-tested at the point
# of use, not only at selection.

def can_audit(channel: dict) -> bool:
    """Audit path open? Enabled, and not paused.

    The pause is path-specific — it gates auditing only. This exact predicate
    previously appeared in autopilot twice (once inverted via de Morgan) and in
    the dashboard's counter, which is three chances to disagree about what
    "active" means on the page that reports it.
    """
    return bool(channel.get("autopilot_enabled") and not channel.get("autopilot_paused_reason"))


def can_cut_shorts(channel: dict) -> bool:
    """Shorts path open?

    Deliberately independent of the audit pause: shorts run whenever the flag is
    on, so an audit-side blip never silences a full NAS folder. A folder and the
    concurrency cap are checked at dispatch, not here — they are about whether
    there is work, not whether the channel is allowed.
    """
    return bool(channel.get("autopilot_shorts_enabled"))


def has_work(channel: dict) -> bool:
    """Either autopilot path open."""
    return can_audit(channel) or can_cut_shorts(channel)


# ── Selection ─────────────────────────────────────────────────────────────

#: Columns a job's Python-side predicate reads. Unioned into whatever projection
#: the caller asked for, because a filter cannot run on a column that was not
#: selected — and would not fail when one is missing, it would silently match
#: nothing. Found exactly that way: channel_ids_for() requests only `id`, so
#: every autopilot job returned an empty list and the tick would have gone quiet.
_PREDICATE_COLUMNS = {
    Job.AUDIT: ("autopilot_enabled", "autopilot_paused_reason"),
    Job.SHORTS: ("autopilot_shorts_enabled",),
    Job.AUTOPILOT: ("autopilot_enabled", "autopilot_paused_reason",
                    "autopilot_shorts_enabled"),
}


def _projection(job: str, columns: str) -> str:
    """`columns` plus whatever `job`'s predicate needs to read."""
    needed = _PREDICATE_COLUMNS.get(job)
    if not needed or columns.strip() == "*":
        return columns
    have = [c.strip() for c in columns.split(",") if c.strip()]
    return ",".join(have + [c for c in needed if c not in have])


def channels_for(job: str, columns: str = "id") -> list[dict]:
    """The channels `job` should run for.

    `columns` is the projection the caller needs — autopilot wants the whole row
    (OAuth tokens included), most jobs want just the id. Columns the job's own
    predicate depends on are added automatically.
    """
    if job == Job.EVERY:
        return all_rows(supabase().table("channels").select(columns))

    if job in (Job.AUDIT, Job.SHORTS, Job.AUTOPILOT):
        # One query for both flags, then the predicate — the flags are OR'd in
        # SQL to keep the read small, and the exact path is decided in Python
        # where `can_audit`'s pause check lives.
        rows = all_rows(
            supabase().table("channels").select(_projection(job, columns))
            .or_("autopilot_enabled.eq.true,autopilot_shorts_enabled.eq.true")
        )
        keep = {Job.AUDIT: can_audit, Job.SHORTS: can_cut_shorts, Job.AUTOPILOT: has_work}[job]
        return [c for c in rows if keep(c)]

    if job == Job.ANALYTICS:
        return all_rows(
            supabase().table("channels").select(columns)
            .eq("analytics_authorized", True)
        )

    if job == Job.REACH:
        # analytics_authorized AND (measurement_enabled OR reach_warmup), unless
        # the env flag widens it back to every authorized channel.
        #
        # reach_warmup is what breaks the bootstrap cycle: a channel cannot be
        # certified for measurement without ingested coverage, and coverage is
        # only ingested for channels opted in here. Warmup opts a channel in
        # WITHOUT turning measurement on.
        q = (
            supabase().table("channels").select(columns)
            .eq("analytics_authorized", True)
        )
        if settings.REPORTING_MEASURED_CHANNELS_ONLY:
            q = q.or_("measurement_enabled.eq.true,reach_warmup.eq.true")
        return all_rows(q)

    if job == Job.PLAYLIST_HEALTH:
        return all_rows(
            supabase().table("channels").select(columns)
            .eq("playlist_health_enabled", True)
        )

    if job == Job.RECONCILE:
        # An env allowlist rather than a DB flag, because it exists to cap a
        # quota cost rather than to express a per-channel intent. "*" means every
        # channel (the pre-allowlist behaviour).
        rows = all_rows(supabase().table("channels").select(columns))
        if settings.PLAYLIST_RECONCILE_ALL:
            return rows
        allowed = [c for c in rows if c["id"] in settings.PLAYLIST_RECONCILE_CHANNELS]
        log.info("reconcile scoped to %d/%d channels (allowlist)", len(allowed), len(rows))
        return allowed

    raise ValueError(f"unknown job: {job}")


def channel_ids_for(job: str) -> list[str]:
    """`channels_for` when only the ids are wanted."""
    return [c["id"] for c in channels_for(job)]
