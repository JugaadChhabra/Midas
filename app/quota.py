import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter

from app.config import settings
from app.db import supabase
from app.rows import all_rows

log = logging.getLogger("midas.quota")

router = APIRouter(tags=["quota"])


def _today_start_iso() -> str:
    # YouTube quota resets at midnight Pacific. We use UTC date here as a close-enough
    # approximation; tightening this is a future improvement.
    today = datetime.now(timezone.utc).date()
    return datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).isoformat()


def units_used_today() -> int:
    # Filter to units > 0 BEFORE Supabase's 1000-row default cap kicks in.
    # Loop 0's metrics_poll writes one units=0 telemetry row per analytics
    # call; without this filter those zero rows can crowd real Data API rows
    # out of the 1000-row window mid-day, silently under-reporting quota and
    # letting can_afford() return True past the real budget. See
    # docs/PHASE_0_GAPS.md Gap 8.
    #
    # Paged, because the row COUNT also exceeds 1000 on a heavy day: the
    # playlist walk logs one row per 1-unit page, and 2026-08-04 wrote 9,239 of
    # them. A single unpaged read stops at the 1000-row cap and reports ~1,000
    # units used against a real 10,006 — the meter that this module's budgets
    # depend on silently reading ~10% of the truth. See the memo on the
    # Supabase 1000-row cap.
    rows = all_rows(
        supabase().table("quota_log")
        .select("units")
        .gte("occurred_at", _today_start_iso())
        .gt("units", 0)
    )
    return sum((row.get("units") or 0) for row in rows)


def units_remaining(reserve: int = 0) -> int:
    """Units left today. `reserve` withholds units for higher-priority work.

    Bulk collection (the playlist membership walk) passes
    `settings.YT_QUOTA_APPLY_RESERVE` so it stops short of the real ceiling and
    leaves room for applying audits — the product's actual output, and the one
    operation a day of collection must never starve. High-priority callers pass
    nothing and see the full remainder, including the reserve.
    """
    return (
        settings.YT_DAILY_QUOTA
        - settings.YT_QUOTA_SAFETY_BUFFER
        - reserve
        - units_used_today()
    )


def can_afford(cost: int, reserve: int = 0) -> bool:
    return units_remaining(reserve) >= cost


class JobBudget:
    """A per-run spend cap for one bulk job, on top of the daily quota.

    Bounds spending two independent ways, and `can_spend` requires both:

      * `budget` — what THIS run may spend in total. Keeps a job whose work is
        effectively unbounded (walking every playlist's membership) from
        consuming a whole day's quota in one pass. Work it does not get to is
        not lost, only deferred: the caller resumes it next run.
      * `reserve` — units withheld for higher-priority work, checked against
        the LIVE fleet-wide meter rather than this job's own spend. A job that
        is under its own budget still stops if something else already spent the
        day.

    Spend is tracked in-process (`note`) because the callers know each call's
    cost, and re-reading `quota_log` per page would add a DB round-trip to a
    loop that runs thousands of times. The live meter is re-read every
    `_RECHECK_EVERY` units so concurrent spend by another job is still seen —
    within that slack, which is why the reserve exists in the first place.
    """

    _RECHECK_EVERY = 50

    def __init__(self, name: str, budget: int, reserve: int = 0):
        self.name = name
        self.budget = budget
        self.reserve = reserve
        self.spent = 0
        self._used_at_recheck = units_used_today()
        self._spent_at_recheck = 0

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.spent)

    def _fleet_remaining(self) -> int:
        if self.spent - self._spent_at_recheck >= self._RECHECK_EVERY:
            self._used_at_recheck = units_used_today()
            self._spent_at_recheck = self.spent
        # Spend since the last re-read is already in self.spent but not yet in
        # the re-read meter, so add the delta rather than double-counting it.
        used = self._used_at_recheck + (self.spent - self._spent_at_recheck)
        return (
            settings.YT_DAILY_QUOTA
            - settings.YT_QUOTA_SAFETY_BUFFER
            - self.reserve
            - used
        )

    def can_spend(self, cost: int) -> bool:
        return cost <= self.remaining and cost <= self._fleet_remaining()

    def note(self, cost: int) -> None:
        """Record `cost` units spent. Call AFTER the API call is issued."""
        self.spent += cost

    def __str__(self) -> str:
        return (
            f"{self.name}: spent {self.spent}/{self.budget} units "
            f"(reserve {self.reserve}, fleet-remaining {self._fleet_remaining()})"
        )


@router.get("/quota")
def quota_status():
    used = units_used_today()
    recent = (
        supabase().table("quota_log")
        .select("occurred_at,channel_id,operation,units,success")
        .order("occurred_at", desc=True)
        .limit(20)
        .execute()
    )
    return {
        "used_today": used,
        "remaining": settings.YT_DAILY_QUOTA - settings.YT_QUOTA_SAFETY_BUFFER - used,
        "limit": settings.YT_DAILY_QUOTA,
        "safety_buffer": settings.YT_QUOTA_SAFETY_BUFFER,
        "recent": recent.data or [],
    }
