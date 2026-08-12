"""Reach data-days: what a comparison needs, and whether we have it.

The reach pipeline reasons in **data-days** — one calendar day of YouTube
Reporting API impressions/CTR per video, landed in `video_reach_daily` and
ledgered in `reporting_reports_ingested`. Three questions get asked about those
days, by three different callers, and they must all be asked the same way:

  * `reporting_poll` — can I backfill this `video_metrics` window yet?
  * `measurement`    — can I judge this audit yet?
  * `auth`           — may this channel turn measurement on?

Before this module they were three separate walks over the same dates, living
inside `reporting_poll` (a scheduled job) with `measurement` importing upward
from it. Any drift between them was a silent disagreement about whether a
window is observable. Now there is one window vocabulary and one coverage
predicate, and the jobs are callers.

What lives here: data-day arithmetic and coverage.
What does NOT: what the numbers mean. Impression floors, CTR thresholds,
verdicts and the grace policy stay in `measurement`.

Deliberately out of scope — other pipelines with their own clocks, whose
constants change independently of this one:

  * `analytics_client.ANALYTICS_DATA_LAG_DAYS` — YouTube's ~48h freshness on
    the on-demand Analytics API that feeds `video_metrics` views/retention.
  * `playlist_health`'s aggregation cutoff, on a 35-day playlist window.

Both happen to involve the number 2. Neither is this module's 2.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from app.config import settings
from app.db import supabase
from app.rows import all_rows

log = logging.getLogger("midas.reach")

#: Days excluded on EACH side of the apply day when building a comparison.
#:
#: Reach data-days roll over on America/Los_Angeles while an audit's
#: `applied_at` is a UTC date, so the data-days adjacent to the apply day can
#: contain mixed pre/post exposure. One day of slop either side drops them.
#:
#: This is NOT an API freshness lag (see the module docstring). It is a property
#: of the calendar and does not move.
ROLLOVER_SLOP_DAYS = 1

#: A window is a half-open-free, fully inclusive (start, end) pair of ISO dates.
Window = tuple[str, str]


# ── Windows ───────────────────────────────────────────────────────────────

def window_for(applied: date) -> tuple[Window, Window]:
    """The (pre, post) comparison windows for an audit applied on `applied`.

    Each window is MEASUREMENT_WINDOW_DAYS long and shifted outward by the
    rollover slop — shifted, not shortened. With the default 21-day window and
    1 day of slop, an audit applied on day D compares:

        pre  = D-22 … D-2     (21 days)
        post = D+2  … D+22    (21 days)

    leaving D-1, D and D+1 in neither.
    """
    n = settings.MEASUREMENT_WINDOW_DAYS
    slop = ROLLOVER_SLOP_DAYS
    pre = (
        (applied - timedelta(days=n + slop)).isoformat(),
        (applied - timedelta(days=slop + 1)).isoformat(),
    )
    post = (
        (applied + timedelta(days=slop + 1)).isoformat(),
        (applied + timedelta(days=n + slop)).isoformat(),
    )
    return pre, post


def days(window: Window) -> list[str]:
    """Inclusive list of ISO data-days in `window`.

    One walk, used by every caller. Two different walks would disagree about
    which data-days a window needs, and therefore about whether it is
    observable yet.
    """
    s, e = date.fromisoformat(window[0]), date.fromisoformat(window[1])
    return [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]


# ── Coverage ──────────────────────────────────────────────────────────────

def coverage(channel_id: str) -> set[str]:
    """The set of data-days this channel has an ingested reach report for.

    "Covered" means a report was ingested for that data-day. It says nothing
    about whether impressions were non-trivial — the MIN_IMPRESSIONS floor is
    applied later, per video, by `measurement`.
    """
    rows = all_rows(
        supabase().table("reporting_reports_ingested")
        .select("data_date")
        .eq("channel_id", channel_id),
        # The one paged table without an `id` primary key.
        order_by="report_id",
    )
    return {r["data_date"] for r in rows}


def missing_days(covered: set[str], *windows: Window) -> list[str]:
    """Which data-days these windows need and `covered` does not have.

    Empty means every window is fully observable. The days themselves are
    returned rather than a bool because every caller wants them: to explain a
    held verdict, to log a deferred backfill, to tell an operator what to chase.
    """
    need: list[str] = []
    for w in windows:
        need.extend(days(w))
    return [d for d in need if d not in covered]


def contiguous_run(covered: set[str]) -> int:
    """Longest run of consecutive data-days in the set (0 if empty)."""
    if not covered:
        return 0
    ordered = sorted(date.fromisoformat(d) for d in covered)
    best = run = 1
    for prev, cur in zip(ordered, ordered[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        best = max(best, run)
    return best


def frontier(covered: set[str]) -> str | None:
    """The most recent covered data-day, or None.

    The frontier — not today — is what channel-level questions anchor to. Reach
    CSVs for a data-day arrive 1-6 days late (2026-07-02 probe), so `today` and
    the last day we could possibly know about are never the same date.
    """
    return max(covered) if covered else None


# ── Certification ─────────────────────────────────────────────────────────

def certify(channel_id: str, min_days: int = 7) -> dict:
    """Phase 0/0.5 exit gate: is this channel's CTR trustworthy enough to measure?

    Certified when reach reports have been ingested for >= `min_days`
    CONTIGUOUS calendar data-days (default 7 — the Phase 0 ">=1 week" gate).
    This gate is about data *presence*, not per-video signal strength.

    KNOWN GAP, corrected in the commit after this one: 7 contiguous days
    anywhere in history is a far weaker test than what `measurement` actually
    needs (a specific 2 x MEASUREMENT_WINDOW_DAYS of days around the apply
    date). A channel enabled at 7 days has audits whose pre-window reaches
    into data-days no reporting job existed for — permanently unobservable,
    and eventually recorded as measured-and-flat.
    """
    covered = coverage(channel_id)
    run = contiguous_run(covered)
    return {
        "certified": run >= min_days,
        "contiguous_days": run,
        "covered_total": len(covered),
        "latest_day": frontier(covered),
        "min_days": min_days,
    }
