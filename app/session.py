"""Logins: users, sessions, the login page and the global gate (team tracker
#144, spec #142).

Midas used to answer anyone on the office LAN. Now every request passes
``gate``, one HTTP middleware:

  * A non-GET request whose ``Origin`` header names another host is refused
    with 403, whatever the path (CSRF belt-and-braces on top of the
    ``SameSite=Lax`` cookie). A request with no ``Origin`` (curl, a script) is
    let through to the session check, which still needs the cookie.
  * ``PUBLIC_PATHS`` (the login page, the login endpoint, the one stylesheet
    the login page loads, and ``/health`` for the Docker healthcheck) pass
    without a session. Nothing else does: the list is exact paths, not
    prefixes, so ``/health/jobs`` and the rest of ``/static`` stay behind it.
  * Any other request needs a valid session cookie. Without one, a GET that
    wants a page (``PAGES``, or any navigation whose ``Accept`` asks for HTML)
    is redirected to ``/login?next=<path>``; everything else gets 401.

A session is a random token in an ``httpOnly``, ``SameSite=Lax`` cookie
(``COOKIE``), valid ``SESSION_DAYS``. Only its sha256 is stored
(``app_sessions.token_hash``). It is valid while it hasn't expired and its user
is active, checked on every request, so deactivating a user locks them out on
their next request. An expired row is deleted when it's read; there is no
clean-up job. The signed-in user is put on ``request.state.user``.

Passwords are argon2id hashes (argon2-cffi). Users are made, reset and
deactivated by ``scripts/manage_users.py`` through ``create_user``,
``set_password`` and ``deactivate_user``; there is no signup.

The scheduled jobs never pass through here: the gate limits the HTTP surface
only.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from app.db import supabase
from app.status_vocab import ALL_USER_ROLES

log = logging.getLogger("midas.session")

COOKIE = "midas_session"
SESSION_DAYS = 30

#: Reachable without a session. Exact paths only.
PUBLIC_PATHS = frozenset({
    "/login",
    "/session/login",
    "/static/theme.css",   # the login page's only asset; its script is inline
    "/health",             # the Docker healthcheck
})

#: HTML page routes: without a session these redirect to /login, never 401.
PAGES = frozenset({"/", "/channel", "/autoshorts"})

#: The one message for every failed login, so it doesn't say which part was wrong.
LOGIN_FAILED = "Email or password is wrong."

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

LOGIN_HTML = Path(__file__).parent / "static" / "login.html"

_hasher = PasswordHasher()
_dummy_hash: str | None = None


def hash_token(token: str) -> str:
    """The stored form of a session token: sha256, hex."""
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _burn_a_verify(password: str) -> None:
    """Spend the time a real check would, so an unknown email answers as slowly
    as a known one with a wrong password."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash(secrets.token_urlsafe(16))
    _verify(_dummy_hash, password)


def _normal_email(email: str) -> str:
    return (email or "").strip().lower()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _public_user(row: dict) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"]}


def _user_by_email(email: str) -> dict | None:
    rows = (supabase().table("app_users")
            .select("id,email,name,role,is_active,password_hash")
            .eq("email", _normal_email(email)).limit(1).execute().data) or []
    return rows[0] if rows else None


# ── sessions ─────────────────────────────────────────────────────────────

def authenticate(email: str, password: str) -> dict | None:
    """The active user with this email and password, else None (whatever was
    wrong)."""
    user = _user_by_email(email)
    if user is None:
        _burn_a_verify(password or "")
        return None
    if not _verify(user.get("password_hash") or "", password or ""):
        return None
    if not user.get("is_active"):
        return None
    try:
        if _hasher.check_needs_rehash(user["password_hash"]):
            supabase().table("app_users").update(
                {"password_hash": hash_password(password)}).eq("id", user["id"]).execute()
    except Exception:  # an upgrade of the stored hash must never block a login
        log.exception("password rehash failed for user %s", user["id"])
    return _public_user(user)


def start_session(user_id: int) -> str:
    """Store a new session for the user and return its raw token (the cookie)."""
    token = secrets.token_urlsafe(32)
    supabase().table("app_sessions").insert({
        "token_hash": hash_token(token),
        "user_id": user_id,
        "expires_at": (_now() + timedelta(days=SESSION_DAYS)).isoformat(),
    }).execute()
    return token


def user_for_token(token: str | None) -> dict | None:
    """The signed-in user for a cookie token, or None.

    None when there's no such session, it has expired (the row is deleted
    here), or its user is inactive or gone.
    """
    if not token:
        return None
    token_hash = hash_token(token)
    rows = (supabase().table("app_sessions").select("user_id,expires_at")
            .eq("token_hash", token_hash).limit(1).execute().data) or []
    if not rows:
        return None
    expires_at = _parse_ts(rows[0].get("expires_at"))
    if expires_at is None or expires_at <= _now():
        supabase().table("app_sessions").delete().eq("token_hash", token_hash).execute()
        return None
    users = (supabase().table("app_users").select("id,email,name,role,is_active")
             .eq("id", rows[0]["user_id"]).limit(1).execute().data) or []
    if not users or not users[0].get("is_active"):
        return None
    return _public_user(users[0])


def end_session(token: str | None) -> None:
    if token:
        supabase().table("app_sessions").delete().eq("token_hash", hash_token(token)).execute()


# ── user admin (scripts/manage_users.py) ─────────────────────────────────

class UserError(ValueError):
    """A user-admin request that can't be done; the message says why."""


def create_user(email: str, name: str, role: str, password: str) -> dict:
    email = _normal_email(email)
    if not email or "@" not in email:
        raise UserError(f"not an email address: {email!r}")
    if not (name or "").strip():
        raise UserError("a name is required")
    if role not in ALL_USER_ROLES:
        raise UserError(f"role must be one of {sorted(ALL_USER_ROLES)}, not {role!r}")
    if not password:
        raise UserError("a password is required")
    if _user_by_email(email) is not None:
        raise UserError(f"a user with email {email} already exists")
    rows = supabase().table("app_users").insert({
        "email": email,
        "name": name.strip(),
        "role": role,
        "password_hash": hash_password(password),
        "is_active": True,
    }).execute().data or []
    return _public_user(rows[0]) if rows else {"email": email, "name": name.strip(), "role": role}


def set_password(email: str, password: str) -> None:
    """Reset a user's password and end their sessions."""
    if not password:
        raise UserError("a password is required")
    user = _user_by_email(email)
    if user is None:
        raise UserError(f"no user with email {_normal_email(email)}")
    supabase().table("app_users").update(
        {"password_hash": hash_password(password)}).eq("id", user["id"]).execute()
    supabase().table("app_sessions").delete().eq("user_id", user["id"]).execute()


def deactivate_user(email: str) -> None:
    """Deactivate a user and end their sessions. Their sessions would fail on the
    next request anyway (the check reads is_active); deleting them is tidiness."""
    user = _user_by_email(email)
    if user is None:
        raise UserError(f"no user with email {_normal_email(email)}")
    supabase().table("app_users").update({"is_active": False}).eq("id", user["id"]).execute()
    supabase().table("app_sessions").delete().eq("user_id", user["id"]).execute()


# ── the gate ─────────────────────────────────────────────────────────────

def _cross_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return False
    host = request.headers.get("host")
    return origin == "null" or not host or urlsplit(origin).netloc.lower() != host.lower()


def _wants_page(request: Request) -> bool:
    if request.method not in ("GET", "HEAD"):
        return False
    return request.url.path in PAGES or "text/html" in request.headers.get("accept", "")


def _login_redirect(request: Request) -> RedirectResponse:
    target = request.url.path
    if request.url.query:
        target += "?" + request.url.query
    url = "/login" if target == "/" else f"/login?next={quote(target, safe='')}"
    return RedirectResponse(url, status_code=303)


async def gate(request: Request, call_next):
    """The global gate (module docstring). Registered once in app/main.py."""
    if request.method not in SAFE_METHODS and _cross_origin(request):
        return JSONResponse({"detail": "cross_origin_refused"}, status_code=403)
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    token = request.cookies.get(COOKIE)
    user = await run_in_threadpool(user_for_token, token) if token else None
    if user is None:
        if _wants_page(request):
            return _login_redirect(request)
        return JSONResponse({"detail": "not_authenticated"}, status_code=401)
    request.state.user = user
    return await call_next(request)


# ── routes ───────────────────────────────────────────────────────────────

router = APIRouter(tags=["session"])


class LoginBody(BaseModel):
    email: str
    password: str


@router.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(LOGIN_HTML)


@router.post("/session/login")
def login(body: LoginBody, request: Request):
    user = authenticate(body.email, body.password)
    if user is None:
        return JSONResponse({"detail": LOGIN_FAILED}, status_code=401)
    token = start_session(user["id"])
    response = JSONResponse({"user": user})
    response.set_cookie(
        COOKIE, token,
        max_age=SESSION_DAYS * 86400,
        path="/",
        httponly=True,
        samesite="lax",
        # The office LAN serves plain http; a Secure cookie would never be sent.
        secure=request.url.scheme == "https",
    )
    return response


@router.post("/session/logout")
def logout(request: Request):
    end_session(request.cookies.get(COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax")
    return response


@router.get("/session/me")
def me(request: Request):
    return request.state.user
