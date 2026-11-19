"""Logins, sessions and the global gate (team tracker #144), through the HTTP
seam: TestClient over the app, with the session store in a FakeSupabase."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import main, session
from tests.fakes import FakeSupabase

PASSWORD = "correct horse battery staple"
HASH = session.hash_password(PASSWORD)


def _user(uid=1, email="justin@example.com", role="manager", active=True, **kw):
    return {"id": uid, "email": email, "name": kw.get("name", "Justin"), "role": role,
            "is_active": active, "password_hash": kw.get("password_hash", HASH),
            "created_at": "2026-11-18T00:00:00+00:00"}


def _in(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.fixture
def store():
    sb = FakeSupabase({"app_users": [_user()], "app_sessions": []}, serial=("app_users",))
    with patch.object(session, "supabase", return_value=sb):
        yield sb


def _deactivate_row(sb):
    """The row as an admin's SQL would leave it, behind the app's back."""
    sb.table("app_users").update({"is_active": False}).eq("id", 1).execute()


def _client(**kw):
    return TestClient(main.app, raise_server_exceptions=False, **kw)


def _login(client, email="justin@example.com", password=PASSWORD):
    return client.post("/session/login", json={"email": email, "password": password})


# ── login / logout / me ─────────────────────────────────────────────────────

def test_login_sets_an_httponly_lax_30_day_cookie_and_stores_only_the_hash(store):
    r = _login(_client())

    assert r.status_code == 200
    assert r.json()["user"] == {"id": 1, "email": "justin@example.com",
                                "name": "Justin", "role": "manager"}
    header = r.headers["set-cookie"]
    token = r.cookies[session.COOKIE]
    assert "HttpOnly" in header
    assert "samesite=lax" in header.lower()
    assert f"Max-Age={30 * 86400}" in header
    assert "Path=/" in header
    [row] = store.rows("app_sessions")
    assert row["token_hash"] == session.hash_token(token)
    assert token not in str(row)
    assert row["user_id"] == 1
    expires = datetime.fromisoformat(row["expires_at"])
    assert timedelta(days=29, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=30)


def test_email_is_matched_case_insensitively(store):
    assert _login(_client(), email="  Justin@Example.COM ").status_code == 200


def test_me_returns_the_signed_in_users_name_and_role(store):
    client = _client()
    _login(client)

    r = client.get("/session/me")

    assert r.status_code == 200
    assert r.json() == {"id": 1, "email": "justin@example.com", "name": "Justin",
                        "role": "manager"}


@pytest.mark.parametrize("email,password", [
    ("justin@example.com", "wrong"),
    ("nobody@example.com", PASSWORD),
    ("", ""),
])
def test_a_wrong_email_or_password_gives_the_same_message_and_no_session(store, email, password):
    r = _login(_client(), email=email, password=password)

    assert r.status_code == 401
    assert r.json() == {"detail": "Email or password is wrong."}
    assert session.COOKIE not in r.cookies
    assert store.rows("app_sessions") == []


def test_an_inactive_user_cannot_log_in_and_gets_the_same_message(store):
    _deactivate_row(store)

    r = _login(_client())

    assert r.status_code == 401
    assert r.json() == {"detail": "Email or password is wrong."}
    assert store.rows("app_sessions") == []


def test_logout_deletes_the_session_and_the_cookie_stops_working(store):
    client = _client()
    token = _login(client).cookies[session.COOKIE]

    r = client.post("/session/logout")

    assert r.status_code == 204
    assert store.rows("app_sessions") == []
    assert session.COOKIE in r.headers["set-cookie"]
    # The browser drops the cookie; a replay of the old token is refused too.
    assert _client(cookies={session.COOKIE: token}).get("/session/me").status_code == 401


# ── session validity ────────────────────────────────────────────────────────

def test_a_deactivated_users_session_fails_on_the_next_request(store):
    client = _client()
    _login(client)
    assert client.get("/session/me").status_code == 200

    _deactivate_row(store)

    assert client.get("/session/me").status_code == 401


def test_an_expired_session_is_rejected_and_deleted(store):
    store.table("app_sessions").insert([
        {"token_hash": session.hash_token("old"), "user_id": 1, "expires_at": _in(-1)},
        {"token_hash": session.hash_token("live"), "user_id": 1, "expires_at": _in(1)},
    ]).execute()

    r = _client(cookies={session.COOKIE: "old"}).get("/session/me")

    assert r.status_code == 401
    assert [s["token_hash"] for s in store.rows("app_sessions")] == [session.hash_token("live")]


def test_an_unknown_token_is_rejected(store):
    assert _client(cookies={session.COOKIE: "made-up"}).get("/session/me").status_code == 401


def test_a_session_whose_user_was_deleted_is_rejected(store):
    store.table("app_sessions").insert(
        {"token_hash": session.hash_token("t"), "user_id": 99, "expires_at": _in(1)}).execute()
    assert _client(cookies={session.COOKIE: "t"}).get("/session/me").status_code == 401


# ── the gate ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("GET", "/session/me"),
    ("GET", "/auth/channels"),
    ("GET", "/dashboard"),
    ("GET", "/quota"),
    ("GET", "/health/jobs"),
    ("GET", "/health/channels"),
    ("GET", "/channels/c1/videos"),
    ("POST", "/channels/c1/sync"),
    ("POST", "/audits/1/apply"),
    ("POST", "/session/logout"),
    ("GET", "/shorts/jobs"),
    ("GET", "/static/channel.html"),
    ("GET", "/static/sidebar.js"),
    ("GET", "/no-such-route"),
])
def test_without_a_session_api_routes_answer_401(store, method, path):
    r = _client().request(method, path)
    assert r.status_code == 401
    assert r.json() == {"detail": "not_authenticated"}


@pytest.mark.parametrize("path,location", [
    ("/", "/login"),
    ("/channel?id=UC1", "/login?next=%2Fchannel%3Fid%3DUC1"),
    ("/autoshorts", "/login?next=%2Fautoshorts"),
])
def test_without_a_session_html_pages_redirect_to_login(store, path, location):
    r = _client().get(path, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == location


def test_a_browser_navigation_to_an_api_route_redirects_too(store):
    r = _client().get("/dashboard", headers={"accept": "text/html,*/*"},
                      follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login?next=%2Fdashboard"


def test_health_is_public_for_the_docker_healthcheck(store):
    r = _client().get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_the_login_page_and_its_stylesheet_are_public(store):
    page = _client().get("/login")
    css = _client().get("/static/theme.css")

    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert 'action="/session/login"' in page.text or "/session/login" in page.text
    assert css.status_code == 200


def test_a_signed_in_user_reaches_a_page(store):
    client = _client()
    _login(client)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 200


def test_the_public_allowlist_is_exact():
    """Exact paths, not prefixes: a new route under /health or /static stays
    behind the gate."""
    assert session.PUBLIC_PATHS == {"/login", "/session/login", "/static/theme.css",
                                    "/static/midas.png", "/health"}


# ── the Origin check ────────────────────────────────────────────────────────

def test_a_cross_origin_post_is_refused_even_with_a_session(store):
    client = _client()
    _login(client)

    r = client.post("/session/logout", headers={"origin": "http://evil.example"})

    assert r.status_code == 403
    assert len(store.rows("app_sessions")) == 1


def test_a_cross_origin_login_is_refused(store):
    r = _client().post("/session/login", headers={"origin": "http://evil.example"},
                       json={"email": "justin@example.com", "password": PASSWORD})
    assert r.status_code == 403
    assert store.rows("app_sessions") == []


def test_a_null_origin_is_refused(store):
    r = _client().post("/session/login", headers={"origin": "null"},
                       json={"email": "justin@example.com", "password": PASSWORD})
    assert r.status_code == 403


def test_a_same_origin_post_passes(store):
    client = _client()
    _login(client)

    r = client.post("/session/logout", headers={"origin": "http://testserver"})

    assert r.status_code == 204


def test_a_get_is_not_origin_checked(store):
    client = _client()
    _login(client)
    assert client.get("/session/me", headers={"origin": "http://evil.example"}).status_code == 200


# ── user admin (scripts/manage_users.py) ────────────────────────────────────

def test_create_user_stores_an_argon2_hash_and_the_user_can_log_in(store):
    session.create_user("Ishwari@Example.com", "Ishwari", "manager", "s3cret-pass")

    row = next(u for u in store.rows("app_users") if u["email"] == "ishwari@example.com")
    assert row["password_hash"].startswith("$argon2id$")
    assert "s3cret-pass" not in row["password_hash"]
    assert row["is_active"] is True
    assert _login(_client(), "ishwari@example.com", "s3cret-pass").status_code == 200


@pytest.mark.parametrize("email,name,role", [
    ("justin@example.com", "Dup", "manager"),   # already exists
    ("ok@example.com", "Ok", "owner"),          # not a role
    ("not-an-email", "X", "manager"),
    ("ok@example.com", "  ", "manager"),
])
def test_create_user_refuses_bad_input(store, email, name, role):
    with pytest.raises(session.UserError):
        session.create_user(email, name, role, "pw")
    assert len(store.rows("app_users")) == 1


def test_reset_password_changes_it_and_ends_sessions(store):
    client = _client()
    _login(client)

    session.set_password("justin@example.com", "new-password")

    assert client.get("/session/me").status_code == 401
    assert _login(_client(), password=PASSWORD).status_code == 401
    assert _login(_client(), password="new-password").status_code == 200


def test_deactivate_ends_sessions_and_blocks_login(store):
    client = _client()
    _login(client)

    session.deactivate_user("justin@example.com")

    assert store.rows("app_users")[0]["is_active"] is False
    assert store.rows("app_sessions") == []
    assert client.get("/session/me").status_code == 401
    assert _login(_client()).status_code == 401


def test_admin_functions_refuse_an_unknown_email(store):
    with pytest.raises(session.UserError):
        session.set_password("nobody@example.com", "x")
    with pytest.raises(session.UserError):
        session.deactivate_user("nobody@example.com")
