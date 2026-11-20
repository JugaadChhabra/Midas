"""The Team page's uploads grid (team tracker 09, #151, spec #142).

``GET /team/uploads?from=&to=&manager_id=`` → what went live, per IST day:

  * Reads ``channel_uploads`` (written by the video sync, #150) for the user's
    visible channels going live in the IST window ``[from 00:00, to + 1
    00:00)``, and the assignments on those channels (#149). Both paged past the
    1000-row cap (``app/rows.py``).
  * A video counts on its go-live IST day (``live_at``: a scheduled video's
    go-live time, else YouTube's publish time; a private, unscheduled video
    never went live and isn't counted; owner, 2026-11-19). A day in the future
    shows what is already scheduled for it.
  * Credits each upload to the member whose assignment covered its channel on
    that day (``starts_on <= day < ends_on``, ``ends_on`` NULL =
    open). An upload from before the channel's first assignment is credited to
    that first assignee (backfill: assigning a channel brings its history with
    it; owner, 2026-11-19). Unassigned holds only uploads on a channel nobody
    has been assigned yet, or in a gap between two assignments.
  * Counts ``{total, shorts, long_form}`` per member per day; a NULL
    ``is_short`` (not yet classified) counts as long-form.
  * ``manager_id`` narrows the channels to that manager's; honoured only for
    admin and exec (a manager always gets their own channels).
  * The window defaults to the last 7 IST days (ending today); given only one
    end, it runs 7 days from or to it. Longer than ``MAX_DAYS`` (92), or
    backwards, is 422.

``GET /team/uploads/videos?member_id=&day=&manager_id=`` (#152) → the uploads
behind one cell, credited by the same code (``_scope``, ``_credited``), so a
cell's count and its list can't disagree.

Computed in Python, not by a SQL RPC, so the whole grid is testable offline
(decided in #142).

``channel_rows`` (the "By channel" view) holds the same uploads by channel: one
row per in-scope channel, every day, zeros included, whoever was credited. The
drill-down takes ``channel_id`` for one of its cells.

Each member row carries ``targets`` (``team.targets_for``: per ISO weekday,
``{shorts, long_form}``, or null when none is set); the page colours a
finished day red when it falls short.

Rows: every active member of the managers in scope, plus anyone credited or
assigned on an in-scope channel in the window (a deactivated member keeps the
row their uploads need), ordered by manager name then member name; then
Unassigned (``member_id`` null), always present. Each row has every day of the
window, zeros included, and its window ``total``.

Upload days are IST. This module keeps its own IST conversion: the quota day
(``quota.QUOTA_TZ``, America/Los_Angeles) is a different concept and must not
share a helper.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from app import access, team
from app.db import supabase
from app.rows import all_rows, rows_for_ids
from app.status_vocab import UserRole

router = APIRouter(tags=["team"])

#: Upload days are IST dates.
IST = ZoneInfo("Asia/Kolkata")

#: The default window, in days, ending today (IST).
DEFAULT_DAYS = 7

#: The longest window accepted; longer is 422.
MAX_DAYS = 92

UNASSIGNED = "Unassigned"

UPLOAD_COLUMNS = ("video_id,channel_id,is_short,uploaded_at,privacy_status,"
                  "scheduled_publish_at,video_published_at,public_at")


def live_at(upload: dict) -> str | None:
    """When the video goes (or went) live, which places it in the grid (owner,
    2026-11-19: the team schedules weekend videos ahead, and a video counts on
    the day viewers get it). A scheduled video: its go-live time
    (``scheduled_publish_at``, still set until a sync sees it live; equal to
    the go-live time either way). Else a private video never went live: None,
    left out. Else a video seen going from unlisted to public: when a sync saw
    it go public (``public_at``, owner 2026-11-20: YouTube's publish time stays
    at the unlisted upload). Else (public, unlisted) YouTube's publish time
    (``video_published_at``), falling back to ``uploaded_at`` when unknown."""
    if upload.get("scheduled_publish_at"):
        return upload["scheduled_publish_at"]
    if upload.get("privacy_status") == "private":
        return None
    return (upload.get("public_at") or upload.get("video_published_at")
            or upload.get("uploaded_at"))
ASSIGNMENT_COLUMNS = "id,channel_id,team_member_id,starts_on,ends_on"
CHANNEL_COLUMNS = "id,name,manager_id,last_synced_at"


def ist_day(at: datetime | str | None = None) -> date:
    """The IST date of ``at`` (a datetime or an ISO timestamp; now when
    omitted). A naive datetime is taken as UTC."""
    if at is None:
        at = datetime.now(timezone.utc)
    elif isinstance(at, str):
        at = datetime.fromisoformat(at.replace("Z", "+00:00"))
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(IST).date()


def ist_midnight(day: date) -> datetime:
    """The start of an IST day, in UTC."""
    return datetime.combine(day, time.min, tzinfo=IST).astimezone(timezone.utc)


def _parse_day(value: str | None, name: str) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"{name} must be a date (YYYY-MM-DD)") from None


def window(from_: date | None, to: date | None) -> tuple[date, date]:
    """The IST days ``[from, to]`` asked for, defaults filled; 422 when
    backwards or longer than ``MAX_DAYS``."""
    span = timedelta(days=DEFAULT_DAYS - 1)
    if from_ is None and to is None:
        to = ist_day()
    if from_ is None:
        from_ = to - span
    elif to is None:
        to = from_ + span
    if to < from_:
        raise HTTPException(422, "to is before from")
    if (to - from_).days + 1 > MAX_DAYS:
        raise HTTPException(422, f"the range is longer than {MAX_DAYS} days")
    return from_, to


def _day(value) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def _holder(assignments: list[dict], day: date, first: dict | None = None):
    """The member id holding the channel on ``day``; before the channel's
    ``first`` assignment, that assignment's member (the backfill); else None."""
    for a in assignments:
        starts, ends = _day(a["starts_on"]), _day(a.get("ends_on"))
        if starts <= day and (ends is None or day < ends):
            return a["team_member_id"]
    if first is not None and day < _day(first["starts_on"]):
        return first["team_member_id"]
    return None


def _zero() -> dict:
    return {"total": 0, "shorts": 0, "long_form": 0}


def _count(cell: dict, is_short) -> None:
    cell["total"] += 1
    cell["shorts" if is_short is True else "long_form"] += 1


def _scope(db, user: dict, manager_id: int | None) -> tuple[list[dict], int | None]:
    """The user's visible channels, narrowed to ``manager_id``'s for admin and
    exec (a manager's ``manager_id`` is ignored and comes back None)."""
    if not access.sees_all(user):
        manager_id = None
    query = access.filter_channels(db.table("channels").select(CHANNEL_COLUMNS), user)
    if manager_id is not None:
        query = query.eq("manager_id", manager_id)
    return all_rows(query), manager_id


def _credited(db, channels: list[dict], first: date, last: date,
              columns: str = UPLOAD_COLUMNS):
    """The uploads on ``channels`` going live (``live_at``) in the IST days
    ``[first, last]``, each with the member credited for it (the assignment
    holding its channel on its go-live IST day; before the channel's first assignment, its first assignee; else None
    = Unassigned), and the assignments in the window by channel.

    The one crediting rule, shared by the grid and its drill-down so a cell and
    its list can't disagree."""
    channel_ids = sorted(c["id"] for c in channels)
    start = ist_midnight(first).isoformat()
    end = ist_midnight(last + timedelta(days=1)).isoformat()

    # live_at reads one of four columns; one plain range read per column (no
    # PostgREST or-filter), merged by video id, the exact day decided below.
    def in_window(column, null_column=None):
        def query(ids):
            q = (db.table("channel_uploads").select(columns).in_("channel_id", ids)
                 .gte(column, start).lt(column, end))
            return q.is_(null_column, "null") if null_column else q
        return rows_for_ids(query, channel_ids, order_by="video_id")

    merged: dict[str, dict] = {}
    for u in (in_window("scheduled_publish_at") + in_window("public_at")
              + in_window("video_published_at")
              + in_window("uploaded_at", null_column="video_published_at")):
        merged[u["video_id"]] = u
    uploads = [merged[k] for k in sorted(merged)]
    assignments = rows_for_ids(
        lambda ids: (db.table("channel_assignments").select(ASSIGNMENT_COLUMNS)
                     .in_("channel_id", ids)),
        channel_ids)
    by_channel: dict[str, list[dict]] = {}
    earliest: dict[str, dict] = {}
    for a in assignments:
        held = earliest.get(a["channel_id"])
        if held is None or (str(a["starts_on"]), a["id"]) < (str(held["starts_on"]), held["id"]):
            earliest[a["channel_id"]] = a
    for a in assignments:
        ends = _day(a.get("ends_on"))
        if _day(a["starts_on"]) <= last and (ends is None or ends > first):
            by_channel.setdefault(a["channel_id"], []).append(a)

    credited = []
    for u in uploads:
        at = live_at(u)
        if at is None:
            continue
        day = ist_day(at)
        if first <= day <= last:
            credited.append((_holder(by_channel.get(u["channel_id"], []), day,
                                     earliest.get(u["channel_id"])), day, u))
    return credited, by_channel


@router.get("/team/uploads")
def uploads_grid(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    manager_id: int | None = Query(None),
    user: dict = Depends(access.current_user),
):
    first, last = window(_parse_day(from_, "from"), _parse_day(to, "to"))
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    day_keys = [d.isoformat() for d in days]
    sees_all = access.sees_all(user)
    db = supabase()
    channels, manager_id = _scope(db, user, manager_id)
    credited, by_channel = _credited(db, channels, first, last)

    cells: dict[int | None, dict[str, dict]] = {}
    channel_cells: dict[str, dict[str, dict]] = {}
    for member, day, u in credited:
        row = cells.setdefault(member, {})
        _count(row.setdefault(day.isoformat(), _zero()), u.get("is_short"))
        by_ch = channel_cells.setdefault(u["channel_id"], {})
        _count(by_ch.setdefault(day.isoformat(), _zero()), u.get("is_short"))

    # Rows: the in-scope managers' active members, plus whoever is credited or
    # assigned in the window.
    users = {u["id"]: u for u in all_rows(db.table("app_users").select("id,name,role,is_active"))}
    if not sees_all:
        managers_in_scope = [user["id"]]
    elif manager_id is not None:
        managers_in_scope = [manager_id]
    else:
        managers_in_scope = sorted({c["manager_id"] for c in channels if c.get("manager_id")}
                                   | {u["id"] for u in users.values()
                                      if u.get("role") == UserRole.MANAGER and u.get("is_active")})
    def member_query():
        return db.table("team_members").select("id,name,manager_id,is_active")

    members = {m["id"]: m for m in rows_for_ids(
        lambda ids: member_query().in_("manager_id", ids), managers_in_scope)
        if m.get("is_active")}
    wanted = ({m for m in cells if m is not None}
              | {a["team_member_id"] for rows in by_channel.values() for a in rows}) - set(members)
    for m in rows_for_ids(lambda ids: member_query().in_("id", ids), sorted(wanted)):
        members[m["id"]] = m

    def days_and_total(row: dict) -> tuple[dict, dict]:
        total = _zero()
        per_day = {}
        for key in day_keys:
            cell = row.get(key, _zero())
            per_day[key] = cell
            for k in total:
                total[k] += cell[k]
        return per_day, total

    def shaped(member_id, name, manager, is_active):
        per_day, total = days_and_total(cells.get(member_id, {}))
        return {"member_id": member_id, "name": name,
                "manager_id": manager, "manager_name": (users.get(manager) or {}).get("name"),
                "is_active": is_active, "days": per_day, "total": total}

    rows = sorted(
        (shaped(m["id"], m["name"], m.get("manager_id"), bool(m.get("is_active")))
         for m in members.values()),
        key=lambda r: ((r["manager_name"] or "").lower(), (r["name"] or "").lower(),
                       r["member_id"]))
    targets = team.targets_for(members)
    for row in rows:
        row["targets"] = targets.get(row["member_id"])
    rows.append({**shaped(None, UNASSIGNED, None, True), "targets": None})

    managers = sorted(
        ({"id": u["id"], "name": u["name"]} for u in users.values()
         if u.get("role") == UserRole.MANAGER and u.get("is_active")),
        key=lambda u: (u["name"].lower(), u["id"])) if sees_all else []
    shaped_channels = sorted(
        ({k: c.get(k) for k in CHANNEL_COLUMNS.split(",")} for c in channels),
        key=lambda c: ((c["name"] or "").lower(), c["id"]))
    channel_rows = []
    for c in shaped_channels:
        per_day, total = days_and_total(channel_cells.get(c["id"], {}))
        channel_rows.append({
            "channel_id": c["id"], "name": c["name"], "manager_id": c.get("manager_id"),
            "manager_name": (users.get(c.get("manager_id")) or {}).get("name"),
            "days": per_day, "total": total})
    return {"from": first.isoformat(), "to": last.isoformat(), "days": day_keys,
            "manager_id": manager_id, "managers": managers,
            "channels": shaped_channels, "rows": rows, "channel_rows": channel_rows}


# ── the drill-down (#152) ─────────────────────────────────────────────────────

VIDEO_COLUMNS = ("video_id,channel_id,title,thumbnail_url,is_short,privacy_status,"
                 "scheduled_publish_at,uploaded_at,video_published_at,public_at")

#: The status pill: ``scheduled`` while a go-live time is set (YouTube clears
#: ``status.publishAt`` once the video is live), else the privacy status. Shown
#: only, never stored.
SCHEDULED = "scheduled"


def _status(upload: dict) -> str | None:
    if upload.get("scheduled_publish_at"):
        return SCHEDULED
    return upload.get("privacy_status")


def _ist_time(at: str) -> str:
    """An ISO timestamp as IST wall-clock time, ``+05:30`` (sorts as time)."""
    return datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone(IST).isoformat()


def _member(db, user: dict, member_id: int, channels: list[dict]) -> dict:
    """The member asked for; 404 when unknown or, for a manager, neither theirs
    nor ever assigned to one of their channels (whose rows their grid shows)."""
    rows = (db.table("team_members").select("id,name,manager_id")
            .eq("id", member_id).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, access.TEAM_MEMBER_NOT_FOUND)
    member = rows[0]
    if access.sees_all(user) or member.get("manager_id") == user["id"]:
        return member
    held = rows_for_ids(
        lambda ids: (db.table("channel_assignments").select("id")
                     .eq("team_member_id", member_id).in_("channel_id", ids)),
        sorted(c["id"] for c in channels))
    if not held:
        raise HTTPException(404, access.TEAM_MEMBER_NOT_FOUND)
    return member


@router.get("/team/uploads/videos")
def uploads_videos(
    day: str = Query(...),
    member_id: int | None = Query(None),
    manager_id: int | None = Query(None),
    channel_id: str | None = Query(None),
    user: dict = Depends(access.current_user),
):
    """The uploads behind one grid cell: on the user's visible channels (and
    ``manager_id``'s, for admin and exec, as the grid), on IST ``day``,
    credited to ``member_id`` (omitted = Unassigned) by the grid's own rule.
    With ``channel_id`` (the "By channel" view), that channel's uploads that
    day instead, whoever was credited; ``member_id`` is then ignored, and a
    channel outside the scope is 404 ``channel_not_found``. Oldest first."""
    the_day = _parse_day(day, "day")
    if the_day is None:
        raise HTTPException(422, "day must be a date (YYYY-MM-DD)")
    db = supabase()
    channels, manager_id = _scope(db, user, manager_id)
    names = {c["id"]: c.get("name") for c in channels}
    if channel_id is not None:
        if channel_id not in names:
            raise HTTPException(404, access.CHANNEL_NOT_FOUND)
        member_id = None
        name = names[channel_id] or channel_id
        channels = [c for c in channels if c["id"] == channel_id]
        wanted = lambda member: True  # noqa: E731
    else:
        name = UNASSIGNED
        if member_id is not None:
            name = _member(db, user, member_id, channels)["name"]
        wanted = lambda member: member == member_id  # noqa: E731

    credited, _ = _credited(db, channels, the_day, the_day, VIDEO_COLUMNS)
    uploads = sorted((u for member, _, u in credited if wanted(member)),
                     key=lambda u: (_ist_time(live_at(u)), u["video_id"]))
    videos = [{
        "video_id": u["video_id"], "title": u.get("title"),
        "thumbnail_url": u.get("thumbnail_url"),
        "channel_id": u["channel_id"], "channel_name": names.get(u["channel_id"]),
        "uploaded_at": u["uploaded_at"], "uploaded_at_ist": _ist_time(u["uploaded_at"]),
        "live_at": live_at(u), "live_at_ist": _ist_time(live_at(u)),
        "is_short": u.get("is_short"), "privacy_status": u.get("privacy_status"),
        "scheduled_publish_at": u.get("scheduled_publish_at"), "status": _status(u),
    } for u in uploads]
    return {"day": the_day.isoformat(), "member_id": member_id, "channel_id": channel_id,
            "name": name, "manager_id": manager_id, "videos": videos}
