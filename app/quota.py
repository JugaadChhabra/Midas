import logging
import math
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter

from app.config import settings
from app.db import supabase
from app.rows import all_rows

log = logging.getLogger("midas.quota")

router = APIRouter(tags=["quota"])


class Op:
    """A metered YouTube Data API operation.

    The string is what lands in `quota_log.operation` — persisted, so these
    values may not be renamed (same rule as app/status_vocab.py).
    """

    CHANNELS_LIST = "channels.list"
    PLAYLIST_ITEMS_LIST = "playlistItems.list"
    VIDEOS_LIST = "videos.list"
    CAPTIONS_LIST = "captions.list"
    CAPTIONS_DOWNLOAD = "captions.download"
    VIDEOS_UPDATE = "videos.update"
    PLAYLISTS_LIST = "playlists.list"
    PLAYLISTS_INSERT = "playlists.insert"
    PLAYLIST_ITEMS_INSERT = "playlistItems.insert"
    PLAYLIST_ITEMS_DELETE = "playlistItems.delete"
    SEARCH_LIST = "search.list"


#: What each operation costs, per call. YouTube's published prices.
#:
#: This table is the ONLY place a unit cost appears. It used to live as a
#: literal in each youtube_client wrapper — where it was written to the ledger
#: but never read — while every gate that had to decide "can I afford this?"
#: re-invented the number: `APPLY_COST = 51` in audits, `1 + 50` in autopilot,
#: `51 * n` and `1 + 2 * ceil(n/50)` in the preview endpoint, `PAGE_COST = 1` in
#: playlists_sync. Five copies of arithmetic derived from a table nobody could
#: consult.
UNIT_COST = {
    Op.CHANNELS_LIST: 1,
    Op.PLAYLIST_ITEMS_LIST: 1,
    Op.VIDEOS_LIST: 1,
    Op.CAPTIONS_LIST: 50,
    Op.CAPTIONS_DOWNLOAD: 200,
    Op.VIDEOS_UPDATE: 50,
    Op.PLAYLISTS_LIST: 1,
    Op.PLAYLISTS_INSERT: 50,
    Op.PLAYLIST_ITEMS_INSERT: 50,
    Op.PLAYLIST_ITEMS_DELETE: 50,
    Op.SEARCH_LIST: 100,
}

#: Ids accepted by one `videos.list` call. A batching fact about the API, so it
#: belongs with the prices: callers sizing a bulk read need both.
IDS_PER_CALL = 50

#: What applying one audit spends: refresh the stats baseline, then update.
#: Named because it is the product's actual output and three places quote it.
APPLY = (Op.VIDEOS_LIST, Op.VIDEOS_UPDATE)


def cost(op: str, n: int = 1) -> int:
    """Units for `n` calls of `op`. KeyError on an unpriced operation — loudly,
    because silently charging 0 is how a spender escapes its budget."""
    return UNIT_COST[op] * n


def cost_of(*ops: str) -> int:
    """Units for one call of each operation — a composite like APPLY."""
    return sum(UNIT_COST[op] for op in ops)


def calls_for(n_ids: int) -> int:
    """How many batched list calls `n_ids` ids take (at least one)."""
    return max(1, math.ceil(max(1, n_ids) / IDS_PER_CALL))


# ── The quota day ─────────────────────────────────────────────────────────
#
# Google's counter resets at midnight Pacific, and this module owns that
# boundary because two places need it and they must not each derive it.
#
# This used to sum the ledger from midnight UTC with a comment calling it a
# close-enough approximation. It was not close enough, and the error ran the
# wrong way: from 00:00 UTC until the true boundary, Google's current day had
# already been running for up to 17 hours, and every unit spent in it was
# excluded from `units_used_today`. The nightly playlist walk — by far the
# heaviest spender, thousands of units — falls entirely inside that window, so
# each morning the meter reported the whole night's spend as free quota while
# the API was already returning quotaExceeded. Meanwhile dashboard.py counted
# down to a hardcoded `QUOTA_RESET_HOUR_UTC = 7` in the same response payload:
# one response, two disagreeing definitions of the same instant.
#
# Derived from the zone rather than fixed at 07:00 UTC because the offset moves:
# PDT resets at 07:00 UTC, PST at 08:00. A hardcoded hour is wrong from November
# to March.

#: Where YouTube's quota clock lives.
QUOTA_TZ = ZoneInfo("America/Los_Angeles")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def quota_day_start(now: datetime | None = None) -> datetime:
    """The instant Google's current quota day began, in UTC."""
    local = (now or _now()).astimezone(QUOTA_TZ)
    midnight = datetime.combine(local.date(), datetime.min.time(), tzinfo=QUOTA_TZ)
    return midnight.astimezone(timezone.utc)


def seconds_until_reset(now: datetime | None = None) -> int:
    """How long until the counter resets. Always positive: at the boundary
    itself the answer is a full day, not zero."""
    now = now or _now()
    local = now.astimezone(QUOTA_TZ)
    next_midnight = datetime.combine(
        local.date() + timedelta(days=1), datetime.min.time(), tzinfo=QUOTA_TZ
    )
    return int((next_midnight.astimezone(timezone.utc) - now).total_seconds())


def _today_start_iso() -> str:
    return quota_day_start().isoformat()


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


def can_afford(units: int, reserve: int = 0) -> bool:
    return units_remaining(reserve) >= units


# ── Charging ──────────────────────────────────────────────────────────────

_local = threading.local()


@contextmanager
def spending(budget: "JobBudget"):
    """Make `budget` the active budget on this thread for the duration.

    Inside this block, every `charge()` is counted against `budget` without the
    caller doing anything. That is the point: a budget whose accounting depends
    on each call site remembering to report its spend is a budget that will be
    wrong, and was — sync_playlists asked for permission before each membership
    page but never counted the playlist-inventory pages it read first, so the
    nightly walk under-reported itself.

    Deciding to stop stays explicit (`can_spend` at the call site); only the
    accounting is automatic. Thread-local because the scheduler runs each job on
    its own thread, so two jobs can hold different budgets — the same reason
    app/db.py caches its client per thread.
    """
    prev = getattr(_local, "budget", None)
    _local.budget = budget
    try:
        yield budget
    finally:
        _local.budget = prev


def charge(channel_id: str | None, op: str, success: bool, n: int = 1) -> int:
    """Record `n` calls of `op` against the ledger. Returns units charged.

    Called from the API wrappers, so the cost is charged where it is actually
    incurred rather than wherever someone remembered to. Never raises: a failed
    ledger write must not take down the call it was measuring.
    """
    units = cost(op, n)
    try:
        supabase().table("quota_log").insert({
            "channel_id": channel_id,
            "operation": op,
            "units": units,
            "success": success,
        }).execute()
    except Exception:
        pass
    budget = getattr(_local, "budget", None)
    if budget is not None:
        budget.note(units)
    return units


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
