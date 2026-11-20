"""The Board's read (the Roster page, rebuilt 2026-11-20 as a Scratch-like board;
docs/superpowers/specs/2026-11-20-channel-targets-board-design.md).

``GET /team/board`` → ``{"today", "me", "managers", "members", "channels"}``:

  * ``managers``: the managers whose blocks the user sees: the admin and exec
    every active manager (plus any inactive one still owning a channel or a
    member), a manager only themselves. ``{id, name, is_active}``, by name.
  * ``members``: those managers' members, deactivated ones included
    (``is_active`` false), ``{id, name, manager_id, is_active}``, by name.
  * ``channels``: the user's visible channels (``access.filter_channels``), each
    ``{id, name, manager_id, holder_id, since, targets, today_target, today}``:
    ``holder_id``/``since`` from the open assignment (null when loose),
    ``targets`` per ISO weekday (``team.targets_for``, null when none),
    ``today_target`` today's weekday's (null when none), and ``today`` the
    uploads that went live on the channel today, IST, ``{total, shorts,
    long_form}``, read by the uploads grid's own code (``team_uploads._credited``).

Read-only: the moves are ``team.move_channel`` and ``PATCH /team/members/{id}``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app import access, team, team_uploads
from app.db import supabase
from app.rows import all_rows, rows_for_ids
from app.status_vocab import UserRole

router = APIRouter(tags=["team"])


@router.get("/team/board")
def board(user: dict = Depends(access.current_user)):
    db = supabase()
    channels = all_rows(access.filter_channels(
        db.table("channels").select("id,name,manager_id"), user))
    sees_all = access.sees_all(user)
    users = {u["id"]: u for u in all_rows(db.table("app_users").select("id,name,role,is_active"))}

    member_query = db.table("team_members").select("id,name,manager_id,is_active")
    if not sees_all:
        member_query = member_query.eq("manager_id", user["id"])
    members = all_rows(member_query)

    if sees_all:
        manager_ids = ({u["id"] for u in users.values()
                        if u.get("role") == UserRole.MANAGER and u.get("is_active")}
                       | {c["manager_id"] for c in channels if c.get("manager_id")}
                       | {m["manager_id"] for m in members if m.get("manager_id")})
    else:
        manager_ids = {user["id"]}
    managers = sorted(
        ({"id": i, "name": (users.get(i) or {}).get("name") or f"Manager {i}",
          "is_active": bool((users.get(i) or {}).get("is_active"))} for i in manager_ids),
        key=lambda m: (m["name"].lower(), m["id"]))

    ids = sorted(c["id"] for c in channels)
    open_rows = rows_for_ids(
        lambda chunk: (db.table("channel_assignments").select("id,channel_id,team_member_id,starts_on")
                       .in_("channel_id", chunk).is_("ends_on", "null")), ids)
    holding = {a["channel_id"]: a for a in open_rows}
    targets = team.targets_for(ids)
    today = team_uploads.ist_day()
    credited, _, _ = team_uploads._credited(db, channels, today, today)
    counts: dict[str, dict] = {}
    for _member, _day, u in credited:
        team_uploads._count(counts.setdefault(u["channel_id"], team_uploads._zero()),
                            u.get("is_short"))

    shaped_channels = sorted(({
        "id": c["id"], "name": c.get("name"), "manager_id": c.get("manager_id"),
        "holder_id": (holding.get(c["id"]) or {}).get("team_member_id"),
        "since": str((holding.get(c["id"]) or {}).get("starts_on") or "")[:10] or None,
        "targets": targets.get(c["id"]),
        "today_target": team_uploads._weekday_target(targets.get(c["id"]), today),
        "today": counts.get(c["id"], team_uploads._zero()),
    } for c in channels), key=lambda c: ((c["name"] or "").lower(), c["id"]))
    shaped_members = sorted(
        ({k: m.get(k) for k in ("id", "name", "manager_id", "is_active")} for m in members),
        key=lambda m: ((m["name"] or "").lower(), m["id"]))
    return {"today": today.isoformat(),
            "me": {"id": user["id"], "role": user.get("role")},
            "managers": managers, "members": shaped_members, "channels": shaped_channels}
