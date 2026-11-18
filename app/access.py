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
  * A route addressed by another object's id (a video, audit, intervention,
    Short-link recommendation, Shorts job or clip) depends on that object's
    resolver (``require_video`` …): object → channel, then the same check, and
    the same 404 for an unknown object as for an invisible one (#146).
  * A list or global route depends on ``current_user`` and narrows what it
    reads to ``visible_channel_ids`` (``scope_to_visible``); a channel named in
    a body or query string goes through ``check_channel`` (the same 404) (#147).
  * Admin-only routes depend on ``require_role(UserRole.ADMIN)``: 403.

Each dependency here carries ``access_rule = True``. ``tests/test_route_access.py``
walks ``app.routes`` and fails on any route with no such dependency that isn't on
its short open list, so a route added later can't skip scoping.

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


def check_channel(user: dict, channel_id: str | None) -> None:
    """404 unless the user can see ``channel_id``: for a channel named in a
    request body or query string rather than the path (#147)."""
    if not channel_id or not can_see_channel(user, channel_id):
        raise HTTPException(404, CHANNEL_NOT_FOUND)


def scope_to_visible(query, user: dict, column: str = "channel_id"):
    """Narrow an unexecuted query on a table with a channel column to the
    user's visible channels (#147). None when the user sees no channel: the
    caller answers its empty result without a query."""
    if sees_all(user):
        return query
    ids = visible_channel_ids(user)
    return query.in_(column, sorted(ids)) if ids else None


@_access_rule
def require_channel(channel_id: str, user: dict = Depends(current_user)) -> str:
    """Route dependency for a ``{channel_id}`` path: 404 unless the user can see
    the channel."""
    if not can_see_channel(user, channel_id):
        raise HTTPException(404, CHANNEL_NOT_FOUND)
    return channel_id


# ── object-id routes (#146) ──────────────────────────────────────────────
#
# A route addressed by another object's id resolves the object to its channel,
# then applies the same check. An unknown object and one on a channel the user
# can't see answer the same 404 (one detail per object type), so another team's
# objects aren't revealed to exist. As in ``require_channel``, admin and exec
# read nothing and pass: an unknown id is left to the route, as before.

VIDEO_NOT_FOUND = "video_not_found"
AUDIT_NOT_FOUND = "audit_not_found"
INTERVENTION_NOT_FOUND = "intervention_not_found"
SHORT_LINK_NOT_FOUND = "short_link_not_found"
SHORTS_JOB_NOT_FOUND = "shorts_job_not_found"
SHORTS_CLIP_NOT_FOUND = "shorts_clip_not_found"


def _one(table: str, columns: str, object_id) -> dict | None:
    rows = (supabase().table(table).select(columns)
            .eq("id", object_id).limit(1).execute().data) or []
    return rows[0] if rows else None


def _video_channel(video_id: str | None) -> str | None:
    video = _one("videos", "channel_id", video_id) if video_id else None
    return video and video.get("channel_id")


def _job_channel(job_id) -> str | None:
    job = _one("shorts_jobs", "channel_id", job_id) if job_id is not None else None
    return job and job.get("channel_id")


def _resolve(user: dict, channel_of, object_id, detail: str):
    """404 ``detail`` unless the user sees the channel ``channel_of(id)`` names
    (None: the object doesn't exist)."""
    if sees_all(user):
        return object_id
    channel_id = channel_of(object_id)
    if not channel_id or not can_see_channel(user, channel_id):
        raise HTTPException(404, detail)
    return object_id


@_access_rule
def require_video(video_id: str, user: dict = Depends(current_user)) -> str:
    """``/videos/{video_id}…``: the video's channel."""
    return _resolve(user, _video_channel, video_id, VIDEO_NOT_FOUND)


@_access_rule
def require_audit(audit_id: int, user: dict = Depends(current_user)) -> int:
    """``/audits/{audit_id}…``: the audited video's channel."""
    def channel_of(i):
        audit = _one("audits", "video_id", i)
        return audit and _video_channel(audit.get("video_id"))
    return _resolve(user, channel_of, audit_id, AUDIT_NOT_FOUND)


@_access_rule
def require_intervention(intervention_id: int, user: dict = Depends(current_user)) -> int:
    """``/interventions/{intervention_id}…``: the intervention's channel."""
    def channel_of(i):
        row = _one("interventions", "channel_id", i)
        return row and row.get("channel_id")
    return _resolve(user, channel_of, intervention_id, INTERVENTION_NOT_FOUND)


@_access_rule
def require_short_link(recommendation_id: int, user: dict = Depends(current_user)) -> int:
    """``/short-links/{recommendation_id}…``: the recommendation's channel, else
    (the column is nullable) its Short's."""
    def channel_of(i):
        rec = _one("short_link_recommendations", "channel_id,short_id", i)
        return rec and (rec.get("channel_id") or _video_channel(rec.get("short_id")))
    return _resolve(user, channel_of, recommendation_id, SHORT_LINK_NOT_FOUND)


@_access_rule
def require_shorts_job(job_id: int, user: dict = Depends(current_user)) -> int:
    """``/shorts/jobs/{job_id}``: the job's channel."""
    return _resolve(user, _job_channel, job_id, SHORTS_JOB_NOT_FOUND)


@_access_rule
def require_shorts_clip(clip_id: int, user: dict = Depends(current_user)) -> int:
    """``/shorts/clips/{clip_id}…``: the clip's job's channel."""
    def channel_of(i):
        clip = _one("shorts_clips", "job_id", i)
        return clip and _job_channel(clip.get("job_id"))
    return _resolve(user, channel_of, clip_id, SHORTS_CLIP_NOT_FOUND)


# ── team members (#148) ──────────────────────────────────────────────────
#
# A team member isn't on a channel: it belongs to a manager. A manager reaches
# only their own members; another manager's member and an unknown id answer the
# same 404. Admin and exec read nothing and pass, as above.

TEAM_MEMBER_NOT_FOUND = "team_member_not_found"


@_access_rule
def require_team_member(member_id: int, user: dict = Depends(current_user)) -> int:
    """``/team/members/{member_id}``: the member's manager must be the user."""
    if sees_all(user):
        return member_id
    member = _one("team_members", "manager_id", member_id)
    if not member or member.get("manager_id") != user["id"]:
        raise HTTPException(404, TEAM_MEMBER_NOT_FOUND)
    return member_id


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


#: Admin-only routes (#147): OAuth connect, quota, job health, manual triggers.
require_admin = require_role(UserRole.ADMIN)


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
