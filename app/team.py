"""The Team page and its roster (team tracker 07, #148, spec #142).

Each manager keeps a roster of their team members: records only, no logins.
A manager sees, adds, renames and deactivates their own members; admin and
exec see every member and choose the manager when they add one.

  * ``GET /team`` serves ``static/team.html`` (any signed-in user; its data
    comes from the scoped routes below).
  * ``GET /team/members`` → ``{"members", "managers"}``: a manager's own
    members (``managers`` = themselves), or, for admin and exec, every member
    (``managers`` = the active managers, for the add form and the grouping).
    Deactivated members are listed too, with ``is_active`` false, ordered by
    manager name then member name.
  * ``POST /team/members`` ``{name, manager_id?}`` → 201 with the member. A
    manager adds under themselves (naming another manager is 403); admin and
    exec must name an active ``manager`` (400 otherwise).
  * ``PATCH /team/members/{id}`` ``{name?, is_active?}``: rename, deactivate
    or reactivate. Another manager's member is a 404, the same as an unknown
    one (``access.require_team_member``). A member never moves to another
    manager here.

Members are deactivated, never deleted, so their past uploads stay credited.
Deactivating a member ends their open channel assignments.

Channel assignments (team tracker 08, #149): one member holds a channel over
``[starts_on, ends_on)``, IST dates, ``ends_on`` NULL while current.

  * ``POST /channels/{id}/assign`` ``{team_member_id, starts_on?}`` →
    ``{"assignment", "changed"}``. ``starts_on`` defaults to today in IST and
    may not be before the open row's start (400). Closing the open row and
    opening the new one is one transaction, the ``assign_channel`` SQL
    function called as an RPC. A manager assigns only their own members
    (another's, or an unknown id: 404 ``team_member_not_found``) to their own
    channels (``require_channel``: 404 ``channel_not_found``); admin and exec
    assign anything. A deactivated member is 400. The member already holding
    the channel: nothing changes (``changed`` false).
  * ``GET /team/assignments`` → ``{"channels", "assignments"}``: the user's
    visible channels (with their manager, for the admin's channel → manager
    control) and every assignment on them, current and past.
  * ``PUT /team/members/{id}/channels`` ``{channel_ids}`` → ``{"channel_ids",
    "added", "ended"}``: the Roster's channel picker. Sets the channels the
    member holds from today (IST): each listed channel they don't hold is
    assigned to them (from whoever held it), and each visible channel they hold
    but isn't listed is ended today, left unassigned. A channel the user can't
    see is a 404 (``channel_not_found``) and is never ended, so a channel that
    moved to another team stays as it is. A deactivated member is 400.

Targets: each member's daily upload target, Shorts and long-form apart, per ISO
weekday (1 = Monday … 7 = Sunday), in ``member_targets``.

  * ``GET /team/members`` carries each member's ``targets``:
    ``{"1": {"shorts", "long_form"}, … "7": …}``, or null when none is set.
  * ``PUT /team/members/{id}/targets`` ``{"days": {"1": {"shorts",
    "long_form"}, …}}`` → ``{"targets"}``: a weekday left out is 0; all zero
    clears the target (null). A manager sets their own members' (another's:
    404), the admin anyone's; exec is 403.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field, StringConstraints

from app import access
from app.db import supabase
from app.rows import all_rows, rows_for_ids
from app.status_vocab import UserRole

router = APIRouter(tags=["team"])

STATIC_DIR = Path(__file__).parent / "static"

#: The longest member name accepted.
NAME_MAX = 100

MANAGER_REQUIRED = "manager_id is required"
NOT_A_MANAGER = "manager_id must be an active manager"
NOTHING_TO_CHANGE = "nothing to change"
MEMBER_INACTIVE = "team member is deactivated"
ASSIGN_CONFLICT = "the channel's assignment changed meanwhile; try again"

#: Assignment days are IST dates. Deliberately not the quota day
#: (``quota.QUOTA_TZ``, America/Los_Angeles): the two must not share a helper.
IST = ZoneInfo("Asia/Kolkata")

ASSIGNMENT_COLUMNS = "id,channel_id,team_member_id,starts_on,ends_on,assigned_by,created_at"

MEMBER_COLUMNS = "id,name,manager_id,is_active,created_at"

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                        max_length=NAME_MAX)]


class NewMember(BaseModel):
    name: Name
    #: The member's manager. A manager may omit it (or name themselves);
    #: admin and exec must give it.
    manager_id: int | None = None


class MemberChange(BaseModel):
    name: Name | None = None
    is_active: bool | None = None


#: The most a day's target may ask, per type: a typo guard.
TARGET_MAX = 500

WEEKDAYS = range(1, 8)


class DayTarget(BaseModel):
    shorts: Annotated[int, Field(ge=0, le=TARGET_MAX)] = 0
    long_form: Annotated[int, Field(ge=0, le=TARGET_MAX)] = 0


class Targets(BaseModel):
    #: ISO weekday (1 = Monday) → that day's target.
    days: dict[Annotated[int, Field(ge=1, le=7)], DayTarget]


class MemberChannels(BaseModel):
    channel_ids: list[str]


class Assign(BaseModel):
    team_member_id: int
    #: The IST date the member takes the channel; today (IST) when omitted.
    starts_on: date | None = None


def ist_day(at: datetime | None = None) -> date:
    """The IST date of ``at`` (now when omitted)."""
    return (at or datetime.now(timezone.utc)).astimezone(IST).date()


@router.get("/team", dependencies=[Depends(access.current_user)])
def team_page():
    return FileResponse(STATIC_DIR / "team.html")


# The same page: the rail's Uploads entry; team.html picks its panel by path.
@router.get("/uploads", dependencies=[Depends(access.current_user)])
def uploads_page():
    return FileResponse(STATIC_DIR / "team.html")


def _users() -> dict[int, dict]:
    rows = all_rows(supabase().table("app_users").select("id,name,role,is_active"))
    return {u["id"]: u for u in rows}


def _shaped(member: dict, users: dict[int, dict]) -> dict:
    manager = users.get(member.get("manager_id")) or {}
    return {**{k: member.get(k) for k in MEMBER_COLUMNS.split(",")},
            "manager_name": manager.get("name")}


def _active_manager(user_id: int | None) -> dict | None:
    rows = (supabase().table("app_users").select("id,name,role,is_active")
            .eq("id", user_id).limit(1).execute().data) or []
    user = rows[0] if rows else None
    if user and user.get("role") == UserRole.MANAGER and user.get("is_active"):
        return user
    return None


@router.get("/team/members")
def list_members(user: dict = Depends(access.current_user)):
    query = supabase().table("team_members").select(MEMBER_COLUMNS)
    if not access.sees_all(user):
        query = query.eq("manager_id", user["id"])
    members = all_rows(query)
    users = _users()
    targets = targets_for([m["id"] for m in members])
    shaped = sorted(({**_shaped(m, users), "targets": targets.get(m["id"])} for m in members),
                    key=lambda m: ((m["manager_name"] or "").lower(), m["name"].lower(), m["id"]))
    if access.sees_all(user):
        managers = sorted(
            ({"id": u["id"], "name": u["name"]} for u in users.values()
             if u.get("role") == UserRole.MANAGER and u.get("is_active")),
            key=lambda u: (u["name"].lower(), u["id"]))
    else:
        managers = [{"id": user["id"], "name": user["name"]}]
    return {"members": shaped, "managers": managers}


@router.post("/team/members", status_code=201)
def create_member(body: NewMember, user: dict = Depends(access.current_user)):
    if access.sees_all(user):
        if body.manager_id is None:
            raise HTTPException(400, MANAGER_REQUIRED)
        manager_id = body.manager_id
        if _active_manager(manager_id) is None:
            raise HTTPException(400, NOT_A_MANAGER)
    else:
        if body.manager_id not in (None, user["id"]):
            raise HTTPException(403, access.FORBIDDEN)
        manager_id = user["id"]
    rows = (supabase().table("team_members")
            .insert({"name": body.name, "manager_id": manager_id})
            .execute().data) or []
    if not rows:
        raise HTTPException(500, "team member not stored")
    return _shaped({"is_active": True, **rows[0]}, _users())


@router.patch("/team/members/{member_id}")
def update_member(member_id: int, body: MemberChange,
                  _: int = Depends(access.require_team_member)):
    change = body.model_dump(exclude_none=True)
    if not change:
        raise HTTPException(400, NOTHING_TO_CHANGE)
    rows = (supabase().table("team_members").update(change)
            .eq("id", member_id).execute().data) or []
    if not rows:
        raise HTTPException(404, access.TEAM_MEMBER_NOT_FOUND)
    if change.get("is_active") is False:
        _end_assignments(member_id)
    return _shaped(rows[0], _users())


# ── targets ──────────────────────────────────────────────────────────────

def targets_for(member_ids) -> dict[int, dict]:
    """Each member's targets, ``{"1": {"shorts", "long_form"}, … "7"}`` (every
    weekday present); a member with none set is left out."""
    ids = sorted({i for i in member_ids if i is not None})
    if not ids:
        return {}
    # member_targets has no `id` column (its key is team_member_id, weekday), so
    # the paging sort can't be rows.ORDER_KEY: order by the primary key instead.
    rows = rows_for_ids(lambda chunk: supabase().table("member_targets")
                        .select("team_member_id,weekday,shorts,long_form")
                        .in_("team_member_id", chunk)
                        .order("team_member_id"), ids, order_by="weekday")
    out: dict[int, dict] = {}
    for r in rows:
        week = out.setdefault(r["team_member_id"],
                              {str(d): {"shorts": 0, "long_form": 0} for d in WEEKDAYS})
        week[str(r["weekday"])] = {"shorts": r["shorts"] or 0, "long_form": r["long_form"] or 0}
    return {m: w for m, w in out.items()
            if any(d["shorts"] or d["long_form"] for d in w.values())}


@router.put("/team/members/{member_id}/targets")
def set_targets(member_id: int, body: Targets,
                user: dict = Depends(access.current_user),
                _: int = Depends(access.require_team_member)):
    if user.get("role") == UserRole.EXEC:
        raise HTTPException(403, access.FORBIDDEN)
    db = supabase()
    known = (db.table("team_members").select("id").eq("id", member_id)
             .limit(1).execute().data) or []
    if not known:
        raise HTTPException(404, access.TEAM_MEMBER_NOT_FOUND)
    days = {d: body.days.get(d, DayTarget()) for d in WEEKDAYS}
    if not any(t.shorts or t.long_form for t in days.values()):
        db.table("member_targets").delete().eq("team_member_id", member_id).execute()
        return {"targets": None}
    now = datetime.now(timezone.utc).isoformat()
    db.table("member_targets").upsert(
        [{"team_member_id": member_id, "weekday": d, "shorts": t.shorts,
          "long_form": t.long_form, "updated_by": user["id"], "updated_at": now}
         for d, t in days.items()],
        on_conflict="team_member_id,weekday").execute()
    return {"targets": targets_for([member_id]).get(member_id)}


# ── channel assignments (#149) ───────────────────────────────────────────

def _end_assignments(member_id: int, channel_ids: set[str] | None = None) -> None:
    """End a member's open assignments today (IST), so their channels show as
    unassigned from today: all of them (deactivation), or those on
    ``channel_ids``. A row starting later than today ends where it starts: an
    empty range, crediting nothing."""
    today = ist_day()
    db = supabase()
    open_rows = all_rows(db.table("channel_assignments").select("id,channel_id,starts_on")
                         .eq("team_member_id", member_id).is_("ends_on", "null"))
    for row in open_rows:
        if channel_ids is not None and row["channel_id"] not in channel_ids:
            continue
        ends_on = max(today, date.fromisoformat(str(row["starts_on"])[:10]))
        (db.table("channel_assignments").update({"ends_on": ends_on.isoformat()})
         .eq("id", row["id"]).is_("ends_on", "null").execute())


def _open_assignment(channel_id: str) -> dict | None:
    rows = (supabase().table("channel_assignments").select(ASSIGNMENT_COLUMNS)
            .eq("channel_id", channel_id).is_("ends_on", "null")
            .limit(1).execute().data) or []
    return rows[0] if rows else None


def _shaped_assignment(row: dict, members: dict[int, dict], users: dict[int, dict]) -> dict:
    return {**{k: row.get(k) for k in ASSIGNMENT_COLUMNS.split(",")},
            "member_name": (members.get(row.get("team_member_id")) or {}).get("name"),
            "assigned_by_name": (users.get(row.get("assigned_by")) or {}).get("name")}


def _member_names(ids) -> dict[int, dict]:
    ids = sorted({i for i in ids if i is not None})
    if not ids:
        return {}
    rows = all_rows(supabase().table("team_members").select("id,name").in_("id", ids))
    return {m["id"]: m for m in rows}


@router.post("/channels/{channel_id}/assign")
def assign_channel(channel_id: str, body: Assign,
                   user: dict = Depends(access.current_user),
                   _: str = Depends(access.require_channel)):
    db = supabase()
    # require_channel passes admin and exec without a read; an unknown channel
    # is still a 404 here, before the RPC's foreign key would refuse it.
    if access.sees_all(user):
        known = (db.table("channels").select("id").eq("id", channel_id)
                 .limit(1).execute().data) or []
        if not known:
            raise HTTPException(404, access.CHANNEL_NOT_FOUND)

    members = (db.table("team_members").select(MEMBER_COLUMNS)
               .eq("id", body.team_member_id).limit(1).execute().data) or []
    member = members[0] if members else None
    if member is None or not (access.sees_all(user) or member.get("manager_id") == user["id"]):
        raise HTTPException(404, access.TEAM_MEMBER_NOT_FOUND)
    if not member.get("is_active"):
        raise HTTPException(400, MEMBER_INACTIVE)

    starts_on = body.starts_on or ist_day()
    current = _open_assignment(channel_id)
    if current is not None:
        current_start = date.fromisoformat(str(current["starts_on"])[:10])
        if starts_on < current_start:
            raise HTTPException(
                400, f"starts_on {starts_on.isoformat()} is before the current "
                     f"assignment's start {current_start.isoformat()}")
        if current.get("team_member_id") == member["id"]:
            return {"assignment": _shaped_assignment(current, {member["id"]: member}, _users()),
                    "changed": False}

    row = _assign(channel_id, member["id"], starts_on, user["id"])
    return {"assignment": _shaped_assignment(row, {member["id"]: member}, _users()),
            "changed": True}


def _assign(channel_id: str, member_id: int, starts_on: date, by: int) -> dict:
    """The ``assign_channel`` RPC: close the channel's open row and open the
    member's, in one transaction."""
    try:
        result = supabase().rpc("assign_channel", {
            "p_channel_id": channel_id, "p_team_member_id": member_id,
            "p_starts_on": starts_on.isoformat(), "p_assigned_by": by,
        }).execute().data
    except APIError as exc:
        # A concurrent assign got in first (the one-open-row index, or the
        # function's back-date backstop).
        raise HTTPException(409, ASSIGN_CONFLICT) from exc
    row = result[0] if isinstance(result, list) else result
    if not row:
        raise HTTPException(500, "assignment not stored")
    return row


@router.put("/team/members/{member_id}/channels")
def set_member_channels(member_id: int, body: MemberChannels,
                        user: dict = Depends(access.current_user),
                        _: int = Depends(access.require_team_member)):
    db = supabase()
    members = (db.table("team_members").select(MEMBER_COLUMNS)
               .eq("id", member_id).limit(1).execute().data) or []
    if not members:
        raise HTTPException(404, access.TEAM_MEMBER_NOT_FOUND)
    member = members[0]
    wanted = set(body.channel_ids)
    visible = access.visible_channel_ids(user)
    if wanted - visible:
        raise HTTPException(404, access.CHANNEL_NOT_FOUND)
    if wanted and not member.get("is_active"):
        raise HTTPException(400, MEMBER_INACTIVE)

    held = {r["channel_id"] for r in all_rows(
        db.table("channel_assignments").select("channel_id")
        .eq("team_member_id", member_id).is_("ends_on", "null"))}
    # Only channels the user can see are ended: one that moved to another
    # team isn't in the picker, so its absence from the list says nothing.
    ended = sorted((held - wanted) & visible)
    added = sorted(wanted - held)
    if ended:
        _end_assignments(member_id, set(ended))
    today = ist_day()
    for channel_id in added:
        current = _open_assignment(channel_id)
        if current is not None:
            # Today, or the open row's own start if that is later (a
            # future-dated assignment): the RPC refuses a back-date.
            current_start = date.fromisoformat(str(current["starts_on"])[:10])
            _assign(channel_id, member_id, max(today, current_start), user["id"])
        else:
            _assign(channel_id, member_id, today, user["id"])
    return {"channel_ids": sorted((held - set(ended)) | wanted),
            "added": added, "ended": ended}


@router.get("/team/assignments")
def list_assignments(user: dict = Depends(access.current_user)):
    channels = all_rows(access.filter_channels(
        supabase().table("channels").select("id,name,manager_id"), user))
    if not channels:
        return {"channels": [], "assignments": []}
    query = supabase().table("channel_assignments").select(ASSIGNMENT_COLUMNS)
    if not access.sees_all(user):
        query = query.in_("channel_id", sorted(c["id"] for c in channels))
    rows = all_rows(query)
    users = _users()
    members = _member_names(r.get("team_member_id") for r in rows)
    shaped_channels = sorted(
        ({"id": c["id"], "name": c.get("name"), "manager_id": c.get("manager_id"),
          "manager_name": (users.get(c.get("manager_id")) or {}).get("name")}
         for c in channels),
        key=lambda c: ((c["name"] or "").lower(), c["id"]))
    assignments = sorted(
        (_shaped_assignment(r, members, users) for r in rows),
        key=lambda a: (str(a["starts_on"]), a["id"]), reverse=True)
    return {"channels": shaped_channels, "assignments": assignments}
