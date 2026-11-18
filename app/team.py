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
Ending a deactivated member's channel assignments comes with the assignments
themselves (#149).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, StringConstraints

from app import access
from app.db import supabase
from app.rows import all_rows
from app.status_vocab import UserRole

router = APIRouter(tags=["team"])

STATIC_DIR = Path(__file__).parent / "static"

#: The longest member name accepted.
NAME_MAX = 100

MANAGER_REQUIRED = "manager_id is required"
NOT_A_MANAGER = "manager_id must be an active manager"
NOTHING_TO_CHANGE = "nothing to change"

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


@router.get("/team", dependencies=[Depends(access.current_user)])
def team_page():
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
    shaped = sorted((_shaped(m, users) for m in members),
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
    return _shaped(rows[0], _users())
