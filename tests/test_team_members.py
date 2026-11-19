"""The Team page and its roster (team tracker 07, #148), through the HTTP seam:
TestClient over the app, with users, sessions and team members in a
FakeSupabase.

A manager sees, adds, renames and deactivates their own members only; another
manager's member is a 404, the same as an unknown one. Admin and exec see every
member and choose the manager when they add one.
"""
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import access, db, main, session, team
from tests.fakes import FakeSupabase

ADMIN, EXEC, MANAGER_A, MANAGER_B, INACTIVE_MANAGER = 1, 2, 3, 4, 5
TOKENS = {ADMIN: "tok-admin", EXEC: "tok-exec", MANAGER_A: "tok-a", MANAGER_B: "tok-b"}
PRANAV, MEET, RACHEL, LEFT = 10, 11, 12, 13


def _user(uid, role, name, active=True):
    return {"id": uid, "email": f"u{uid}@example.com", "name": name, "role": role,
            "is_active": active, "password_hash": "unused"}


def _member(mid, name, manager_id, active=True):
    return {"id": mid, "name": name, "manager_id": manager_id, "is_active": active,
            "created_at": "2026-11-18T00:00:00+00:00"}


@pytest.fixture
def store():
    sb = FakeSupabase({
        "app_users": [_user(ADMIN, "admin", "Jugaad"), _user(EXEC, "exec", "Akshay"),
                      _user(MANAGER_A, "manager", "Justin"),
                      _user(MANAGER_B, "manager", "Ishwari"),
                      _user(INACTIVE_MANAGER, "manager", "Gone", active=False)],
        "app_sessions": [{"token_hash": session.hash_token(t), "user_id": uid,
                          "expires_at": "2999-01-01T00:00:00+00:00"}
                         for uid, t in TOKENS.items()],
        "team_members": [_member(PRANAV, "Pranav", MANAGER_A),
                         _member(MEET, "Meet", MANAGER_A),
                         _member(RACHEL, "Rachel", MANAGER_B),
                         _member(LEFT, "Left", MANAGER_A, active=False)],
        # Deactivating a member ends their open assignments (#149;
        # tests/test_team_assignments.py).
        "channel_assignments": [],
    }, serial=("team_members",))
    patches = [patch.object(mod, "supabase", return_value=sb)
               for name, mod in list(sys.modules.items())
               if name.startswith("app") and getattr(mod, "supabase", None) is db.supabase]
    for p in patches:
        p.start()
    try:
        yield sb
    finally:
        for p in reversed(patches):
            p.stop()


def _as(uid):
    return TestClient(main.app, raise_server_exceptions=False,
                      cookies={session.COOKIE: TOKENS[uid]})


def _row(store, mid):
    return next(m for m in store.rows("team_members") if m["id"] == mid)


def _member_writes(store):
    return [w for w in store.writes if w[0] == "team_members"]


# ── the page ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/team", "/uploads"])
def test_the_team_page_is_served_to_any_signed_in_user(store, path):
    for uid in TOKENS:
        r = _as(uid).get(path)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "/static/theme.css" in r.text
        assert "/static/sidebar.js" in r.text


@pytest.mark.parametrize("path", ["/team", "/uploads"])
def test_the_team_page_redirects_to_login_without_a_session(store, path):
    r = TestClient(main.app).get(path, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login?next=" + path.replace("/", "%2F")


def test_the_roster_routes_need_a_session(store):
    client = TestClient(main.app)
    assert client.get("/team/members").status_code == 401
    assert client.post("/team/members", json={"name": "X"}).status_code == 401
    assert client.patch(f"/team/members/{PRANAV}", json={"name": "X"}).status_code == 401


# ── GET /team/members ────────────────────────────────────────────────────────

def _listed(uid, **params):
    r = _as(uid).get("/team/members", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_manager_lists_only_their_own_members(store):
    body = _listed(MANAGER_A)

    assert [m["name"] for m in body["members"]] == ["Left", "Meet", "Pranav"]
    assert {m["manager_id"] for m in body["members"]} == {MANAGER_A}
    assert body["managers"] == [{"id": MANAGER_A, "name": "Justin"}]

    assert [m["name"] for m in _listed(MANAGER_B)["members"]] == ["Rachel"]


def test_members_carry_their_state_and_manager(store):
    [left] = [m for m in _listed(MANAGER_A)["members"] if m["id"] == LEFT]
    assert left == {"id": LEFT, "name": "Left", "manager_id": MANAGER_A,
                    "manager_name": "Justin", "is_active": False,
                    "created_at": "2026-11-18T00:00:00+00:00"}


@pytest.mark.parametrize("uid", [ADMIN, EXEC])
def test_admin_and_exec_list_every_member_with_the_active_managers(store, uid):
    body = _listed(uid)

    assert sorted(m["id"] for m in body["members"]) == sorted([PRANAV, MEET, RACHEL, LEFT])
    assert {m["id"]: m["manager_name"] for m in body["members"]}[RACHEL] == "Ishwari"
    # Ordered by manager, then name, so the page can group them.
    assert [m["name"] for m in body["members"]] == ["Rachel", "Left", "Meet", "Pranav"]
    assert body["managers"] == [{"id": MANAGER_B, "name": "Ishwari"},
                                {"id": MANAGER_A, "name": "Justin"}]


# ── POST /team/members ───────────────────────────────────────────────────────

def test_a_manager_adds_a_member_under_themselves(store):
    r = _as(MANAGER_A).post("/team/members", json={"name": "  Heramb  "})

    assert r.status_code == 201, r.text
    member = r.json()
    assert member["name"] == "Heramb"
    assert member["manager_id"] == MANAGER_A
    assert member["is_active"] is True
    assert _row(store, member["id"])["name"] == "Heramb"
    assert "Heramb" in [m["name"] for m in _listed(MANAGER_A)["members"]]
    assert "Heramb" not in [m["name"] for m in _listed(MANAGER_B)["members"]]


def test_a_manager_naming_their_own_id_is_fine(store):
    r = _as(MANAGER_A).post("/team/members", json={"name": "Heramb", "manager_id": MANAGER_A})
    assert r.status_code == 201
    assert r.json()["manager_id"] == MANAGER_A


def test_a_manager_cannot_add_a_member_to_another_team(store):
    r = _as(MANAGER_A).post("/team/members", json={"name": "Spy", "manager_id": MANAGER_B})

    assert r.status_code == 403
    assert r.json() == {"detail": access.FORBIDDEN}
    assert _member_writes(store) == []


@pytest.mark.parametrize("uid", [ADMIN, EXEC])
def test_admin_and_exec_choose_the_manager(store, uid):
    r = _as(uid).post("/team/members", json={"name": "Asha", "manager_id": MANAGER_B})

    assert r.status_code == 201, r.text
    assert r.json()["manager_id"] == MANAGER_B
    assert "Asha" in [m["name"] for m in _listed(MANAGER_B)["members"]]


@pytest.mark.parametrize("uid", [ADMIN, EXEC])
def test_admin_and_exec_must_name_a_manager(store, uid):
    r = _as(uid).post("/team/members", json={"name": "Asha"})

    assert r.status_code == 400
    assert r.json() == {"detail": team.MANAGER_REQUIRED}
    assert _member_writes(store) == []


@pytest.mark.parametrize("manager_id", [ADMIN, EXEC, INACTIVE_MANAGER, 999])
def test_the_manager_must_be_an_active_manager(store, manager_id):
    r = _as(ADMIN).post("/team/members", json={"name": "Asha", "manager_id": manager_id})

    assert r.status_code == 400
    assert r.json() == {"detail": team.NOT_A_MANAGER}
    assert _member_writes(store) == []


@pytest.mark.parametrize("name", ["", "   ", "x" * (team.NAME_MAX + 1)])
def test_a_name_is_required_and_bounded(store, name):
    r = _as(MANAGER_A).post("/team/members", json={"name": name})

    assert r.status_code == 422
    assert _member_writes(store) == []


# ── PATCH /team/members/{id} ─────────────────────────────────────────────────

def test_a_manager_renames_their_member(store):
    r = _as(MANAGER_A).patch(f"/team/members/{PRANAV}", json={"name": " Pranav K "})

    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Pranav K"
    assert _row(store, PRANAV)["name"] == "Pranav K"
    assert _row(store, PRANAV)["is_active"] is True


def test_a_manager_deactivates_their_member_and_the_row_stays(store):
    r = _as(MANAGER_A).patch(f"/team/members/{MEET}", json={"is_active": False})

    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert _row(store, MEET)["is_active"] is False
    assert _row(store, MEET)["name"] == "Meet"
    assert MEET in [m["id"] for m in _listed(MANAGER_A)["members"]]


def test_a_deactivated_member_can_be_reactivated(store):
    r = _as(MANAGER_A).patch(f"/team/members/{LEFT}", json={"is_active": True})
    assert r.status_code == 200
    assert _row(store, LEFT)["is_active"] is True


@pytest.mark.parametrize("body", [{"name": "Hijacked"}, {"is_active": False}])
def test_a_manager_editing_another_managers_member_gets_404(store, body):
    r = _as(MANAGER_A).patch(f"/team/members/{RACHEL}", json=body)

    assert r.status_code == 404
    assert r.json() == {"detail": access.TEAM_MEMBER_NOT_FOUND}
    assert _row(store, RACHEL) == _member(RACHEL, "Rachel", MANAGER_B)
    assert _member_writes(store) == []


@pytest.mark.parametrize("uid", [MANAGER_A, ADMIN])
def test_an_unknown_member_is_the_same_404(store, uid):
    known = _as(MANAGER_A).patch(f"/team/members/{RACHEL}", json={"name": "X"})
    unknown = _as(uid).patch("/team/members/999", json={"name": "X"})

    assert (unknown.status_code, unknown.json()) == (known.status_code, known.json())


@pytest.mark.parametrize("uid", [ADMIN, EXEC])
def test_admin_and_exec_edit_any_member(store, uid):
    r = _as(uid).patch(f"/team/members/{RACHEL}", json={"name": "Rachel D", "is_active": False})

    assert r.status_code == 200
    assert _row(store, RACHEL)["name"] == "Rachel D"
    assert _row(store, RACHEL)["is_active"] is False
    assert _row(store, RACHEL)["manager_id"] == MANAGER_B


def test_patch_cannot_move_a_member_to_another_manager(store):
    _as(MANAGER_A).patch(f"/team/members/{PRANAV}", json={"manager_id": MANAGER_B})
    _as(ADMIN).patch(f"/team/members/{PRANAV}", json={"manager_id": MANAGER_B, "name": "P"})

    assert _row(store, PRANAV)["manager_id"] == MANAGER_A


def test_an_empty_patch_is_refused(store):
    r = _as(MANAGER_A).patch(f"/team/members/{PRANAV}", json={})

    assert r.status_code == 400
    assert r.json() == {"detail": team.NOTHING_TO_CHANGE}
    assert _member_writes(store) == []


@pytest.mark.parametrize("name", ["", "  ", "x" * (team.NAME_MAX + 1)])
def test_a_rename_needs_a_bounded_name(store, name):
    r = _as(MANAGER_A).patch(f"/team/members/{PRANAV}", json={"name": name})

    assert r.status_code == 422
    assert _row(store, PRANAV)["name"] == "Pranav"


# ── wiring ───────────────────────────────────────────────────────────────────

def test_the_member_patch_uses_the_member_resolver():
    from tests.test_route_access import _api_routes, _calls

    [route] = [r for r in _api_routes()
               if r.path == "/team/members/{member_id}" and "PATCH" in r.methods]
    assert access.require_team_member in list(_calls(route.dependant))
