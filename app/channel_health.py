"""Per-channel freshness: which channels have quietly stopped being watched.

On 2026-10-16 four channels' sign-ins died. `video_sync` treats an expired token
as an expected skip and the traffic and reach polls simply found nothing new, so
every job stayed `success` and nobody noticed for a week. The job registry
(`app/job_status.py`) can't see that: it records how runs ended, not whether a
channel's data is still moving. This module asks the database instead, so the
answer also survives a restart.

A channel has a problem when:

  * its video list hasn't synced for `SYNC_STALE_HOURS` (video_sync is daily);
  * it ingests reach (`eligibility.Job.REACH`) and the reach frontier is more
    than `REACH_STALE_DAYS` behind today (reports arrive 1-6 days late);
  * it ingests traffic (`eligibility.Job.TRAFFIC`) and the traffic frontier is
    more than `TRAFFIC_STALE_DAYS` behind (steady lag 2 days, A1.1);
  * its autopilot is paused (`autopilot_paused_reason`, e.g. `token_expired`).

A channel with no videos in `videos` is listed with `no_videos: true` and never
has a problem: there is nothing on it to sync, measure or change, and its feeds
stay empty (Kannada and Telugu had no uploads on 2026-10-26). It is judged again
from the first sync that finds a video.

`check()` serves `GET /health/channels`; `run_daily()` is the `channel_health`
job, which fails (and so shows in /health/jobs and logs `JOB FAILED`) naming each
channel with a problem. Read-only.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter

from app import eligibility, job_status, reach
from app.db import supabase
from app.reporting_client import TRAFFIC_REPORT_TYPE_ID

SYNC_STALE_HOURS = 30
REACH_STALE_DAYS = 7
TRAFFIC_STALE_DAYS = 4

router = APIRouter()


def _hours_since(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (now - then).total_seconds() / 3600


def _frontier_problem(label: str, covered: set[str], today: date, limit: int) -> tuple[int | None, str | None]:
    behind = reach.days_behind(covered, today)
    if behind is None:
        return None, f"{label}: nothing ingested yet"
    if behind > limit:
        return behind, f"{label}: frontier {reach.frontier(covered)} is {behind} days behind"
    return behind, None


def has_videos(channel_id: str) -> bool:
    return bool(
        supabase().table("videos").select("id").eq("channel_id", channel_id).limit(1)
        .execute().data
    )


def channel_status(ch: dict, *, reach_ids: set[str], traffic_ids: set[str],
                   now: datetime, no_videos: bool = False) -> dict:
    """One channel's freshness and the problems found, as `check()` lists it."""
    if no_videos:
        return {"id": ch["id"], "name": ch.get("name"), "last_synced_at": ch.get("last_synced_at"),
                "reach_days_behind": None, "traffic_days_behind": None,
                "autopilot_paused_reason": ch.get("autopilot_paused_reason"),
                "no_videos": True, "problems": []}
    today = now.date()
    problems: list[str] = []

    hours = _hours_since(ch.get("last_synced_at"), now)
    if hours is None:
        problems.append("sync: never synced")
    elif hours > SYNC_STALE_HOURS:
        problems.append(f"sync: last synced {hours:.0f} h ago")

    reach_behind = traffic_behind = None
    if ch["id"] in reach_ids:
        reach_behind, p = _frontier_problem("reach", reach.coverage(ch["id"]), today, REACH_STALE_DAYS)
        problems += [p] if p else []
    if ch["id"] in traffic_ids:
        traffic_behind, p = _frontier_problem(
            "traffic", reach.coverage(ch["id"], report_type=TRAFFIC_REPORT_TYPE_ID),
            today, TRAFFIC_STALE_DAYS)
        problems += [p] if p else []

    if ch.get("autopilot_paused_reason"):
        problems.append(f"autopilot paused: {ch['autopilot_paused_reason']}")

    return {
        "id": ch["id"],
        "name": ch.get("name"),
        "last_synced_at": ch.get("last_synced_at"),
        "reach_days_behind": reach_behind,
        "traffic_days_behind": traffic_behind,
        "autopilot_paused_reason": ch.get("autopilot_paused_reason"),
        "no_videos": False,
        "problems": problems,
    }


def check(*, now: datetime | None = None) -> dict:
    """Every channel's freshness, problems first."""
    now = now or datetime.now(timezone.utc)
    reach_ids = set(eligibility.channel_ids_for(eligibility.Job.REACH))
    traffic_ids = set(eligibility.channel_ids_for(eligibility.Job.TRAFFIC))
    rows = eligibility.channels_for(
        eligibility.Job.EVERY, columns="id,name,last_synced_at,autopilot_paused_reason")
    channels = [channel_status(c, reach_ids=reach_ids, traffic_ids=traffic_ids, now=now,
                               no_videos=not has_videos(c["id"]))
                for c in rows]
    channels.sort(key=lambda c: (not c["problems"], c.get("name") or c["id"]))
    return {"checked_at": now.isoformat(),
            "with_problems": sum(1 for c in channels if c["problems"]),
            "channels": channels}


def run_daily() -> None:
    """The `channel_health` job: fail the run naming every channel with a problem."""
    failed = {c["id"]: "; ".join(c["problems"]) for c in check()["channels"] if c["problems"]}
    if failed:
        raise job_status.JobRunFailed("channel_health", failed)


@router.get("/health/channels")
def health_channels():
    """Which channels have stopped syncing or ingesting (read from the DB)."""
    return check()
