"""Who may see which channel: the one place for visibility rules (team tracker
#145, spec #142).

The global gate (``app/session.py``) only checks that a request is signed in.
This module decides what the signed-in user may reach:

  * ``admin`` and ``exec`` see every channel. A ``manager`` sees the channels
    whose ``channels.manager_id`` is them; a channel with no manager is seen by
    admin and exec only (``visible_channel_ids``).
  * A route whose path has a ``{channel_id}`` depends on ``require_channel``,
    which answers 404 (never 403) for a channel the user can't see, so another
    team's channels aren't even revealed to exist.
  * Admin-only routes depend on ``require_role(UserRole.ADMIN)``: 403.

Each dependency here carries ``access_rule = True``. ``tests/test_route_access.py``
walks ``app.routes`` and fails on any route with no such dependency that isn't on
its public allowlist, so a route added later can't skip scoping.

``require_channel`` reads nothing for admin and exec: they see every channel, and
an unknown channel id is left to the route, as before. For a manager it is one
read of ``channels`` per request, so a changed mapping applies at once.

The scheduled jobs never pass through here: this limits the HTTP surface only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.db import supabase
from app.rows import all_rows
from app.status_vocab import UserRole

#: The 404 body for a channel the user can't see (or that doesn't exist).
CHANNEL_NOT_FOUND = "channel_not_found"

#: The 403 body for a route the user's role may not use.
FORBIDDEN = "forbidden"

#: Roles that see every channel.
SEE_ALL = frozenset({UserRole.ADMIN, UserRole.EXEC})


def _access_rule(fn):
    fn.access_rule = True
    return fn


@_access_rule
def current_user(request: Request) -> dict:
    """The signed-in user ``{id, email, name, role}``, set by the gate."""
    user = getattr(request.state, "user", None)
    if user is None:  # the gate let it through without a session: a public path
        raise HTTPException(401, "not_authenticated")
    return user


def sees_all(user: dict) -> bool:
    return user.get("role") in SEE_ALL


def filter_channels(query, user: dict):
    """Narrow an unexecuted query on the ``channels`` table to the user's
    visible channels."""
    return query if sees_all(user) else query.eq("manager_id", user["id"])


def visible_channel_ids(user: dict) -> set[str]:
    """The ids of every channel the user can see."""
    query = filter_channels(supabase().table("channels").select("id"), user)
    return {row["id"] for row in all_rows(query)}


def can_see_channel(user: dict, channel_id: str) -> bool:
    if sees_all(user):
        return True
    rows = (supabase().table("channels").select("id")
            .eq("id", channel_id).eq("manager_id", user["id"])
            .limit(1).execute().data) or []
    return bool(rows)


@_access_rule
def require_channel(channel_id: str, user: dict = Depends(current_user)) -> str:
    """Route dependency for a ``{channel_id}`` path: 404 unless the user can see
    the channel."""
    if not can_see_channel(user, channel_id):
        raise HTTPException(404, CHANNEL_NOT_FOUND)
    return channel_id


def require_role(*roles: str):
    """Route dependency factory: 403 unless the user has one of ``roles``."""
    allowed = frozenset(roles)

    @_access_rule
    def check(user: dict = Depends(current_user)) -> dict:
        if user.get("role") not in allowed:
            raise HTTPException(403, FORBIDDEN)
        return user

    check.roles = allowed
    return check


# ── channel → manager mapping (admin only) ───────────────────────────────

router = APIRouter(tags=["access"])


class ManagerBody(BaseModel):
    #: The manager's ``app_users.id``; null clears the mapping (admin/exec only).
    manager_id: int | None = None


@router.patch(
    "/channels/{channel_id}/manager",
    # The channel first: a manager asking about another team's channel gets 404.
    dependencies=[Depends(require_channel), Depends(require_role(UserRole.ADMIN))],
)
def set_channel_manager(channel_id: str, body: ManagerBody):
    """Map a channel to the manager who sees it. The user must be an active
    ``manager`` (400 otherwise); 404 for an unknown channel."""
    db = supabase()
    if body.manager_id is not None:
        users = (db.table("app_users").select("id,role,is_active")
                 .eq("id", body.manager_id).limit(1).execute().data) or []
        if not users or users[0].get("role") != UserRole.MANAGER or not users[0].get("is_active"):
            raise HTTPException(400, "manager_id must be an active manager")
    rows = (db.table("channels").update({"manager_id": body.manager_id})
            .eq("id", channel_id).execute().data) or []
    if not rows:
        raise HTTPException(404, CHANNEL_NOT_FOUND)
    return {"id": channel_id, "manager_id": body.manager_id}
