"""The Team page's uploads grid (team tracker 09, #151, spec #142).

``GET /team/uploads?from=&to=&manager_id=`` → who uploaded what, per IST day:

  * Reads ``channel_uploads`` (written by the video sync, #150) for the user's
    visible channels in the IST window ``[from 00:00, to + 1 00:00)``, and the
    assignments on those channels (#149). Both paged past the 1000-row cap
    (``app/rows.py``).
  * Credits each upload to the member whose assignment covered its channel on
    the upload's IST day (``starts_on <= day < ends_on``, ``ends_on`` NULL =
    open), else to Unassigned. A scheduled or private video counts on the day
    it was uploaded (``uploaded_at``), not the day it goes public.
  * Counts ``{total, shorts, long_form}`` per member per day; a NULL
    ``is_short`` (not yet classified) counts as long-form.
  * ``manager_id`` narrows the channels to that manager's; honoured only for
    admin and exec (a manager always gets their own channels).
  * The window defaults to the last 7 IST days (ending today); given only one
    end, it runs 7 days from or to it. Longer than ``MAX_DAYS`` (92), or
    backwards, is 422.

Computed in Python, not by a SQL RPC, so the whole grid is testable offline
(decided in #142).

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

from app import access
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

UPLOAD_COLUMNS = "video_id,channel_id,is_short,uploaded_at"
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


def _holder(assignments: list[dict], day: date):
    """The member id holding the channel on ``day``, else None."""
    for a in assignments:
        starts, ends = _day(a["starts_on"]), _day(a.get("ends_on"))
        if starts <= day and (ends is None or day < ends):
            return a["team_member_id"]
    return None


def _zero() -> dict:
    return {"total": 0, "shorts": 0, "long_form": 0}


def _count(cell: dict, is_short) -> None:
    cell["total"] += 1
    cell["shorts" if is_short is True else "long_form"] += 1


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
    if not sees_all:
        manager_id = None
    db = supabase()

    query = access.filter_channels(db.table("channels").select(CHANNEL_COLUMNS), user)
    if manager_id is not None:
        query = query.eq("manager_id", manager_id)
    channels = all_rows(query)
    channel_ids = sorted(c["id"] for c in channels)

    uploads = rows_for_ids(
        lambda ids: (db.table("channel_uploads").select(UPLOAD_COLUMNS)
                     .in_("channel_id", ids)
                     .gte("uploaded_at", ist_midnight(first).isoformat())
                     .lt("uploaded_at", ist_midnight(last + timedelta(days=1)).isoformat())),
        channel_ids, order_by="video_id")
    assignments = rows_for_ids(
        lambda ids: (db.table("channel_assignments").select(ASSIGNMENT_COLUMNS)
                     .in_("channel_id", ids)),
        channel_ids)
    by_channel: dict[str, list[dict]] = {}
    for a in assignments:
        ends = _day(a.get("ends_on"))
        if _day(a["starts_on"]) <= last and (ends is None or ends > first):
            by_channel.setdefault(a["channel_id"], []).append(a)

    cells: dict[int | None, dict[str, dict]] = {}
    for u in uploads:
        day = ist_day(u["uploaded_at"])
        if not first <= day <= last:
            continue
        member = _holder(by_channel.get(u["channel_id"], []), day)
        row = cells.setdefault(member, {})
        _count(row.setdefault(day.isoformat(), _zero()), u.get("is_short"))

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

    def shaped(member_id, name, manager, is_active):
        row = cells.get(member_id, {})
        total = _zero()
        per_day = {}
        for key in day_keys:
            cell = row.get(key, _zero())
            per_day[key] = cell
            for k in total:
                total[k] += cell[k]
        return {"member_id": member_id, "name": name,
                "manager_id": manager, "manager_name": (users.get(manager) or {}).get("name"),
                "is_active": is_active, "days": per_day, "total": total}

    rows = sorted(
        (shaped(m["id"], m["name"], m.get("manager_id"), bool(m.get("is_active")))
         for m in members.values()),
        key=lambda r: ((r["manager_name"] or "").lower(), (r["name"] or "").lower(),
                       r["member_id"]))
    rows.append(shaped(None, UNASSIGNED, None, True))

    managers = sorted(
        ({"id": u["id"], "name": u["name"]} for u in users.values()
         if u.get("role") == UserRole.MANAGER and u.get("is_active")),
        key=lambda u: (u["name"].lower(), u["id"])) if sees_all else []
    shaped_channels = sorted(
        ({k: c.get(k) for k in CHANNEL_COLUMNS.split(",")} for c in channels),
        key=lambda c: ((c["name"] or "").lower(), c["id"]))
    return {"from": first.isoformat(), "to": last.isoformat(), "days": day_keys,
            "manager_id": manager_id, "managers": managers,
            "channels": shaped_channels, "rows": rows}
