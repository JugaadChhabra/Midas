"""Channel assignments (team tracker 08, #149), through the HTTP seam: TestClient
over the app, with users, sessions, channels, members and assignments in a
FakeSupabase.

The ``assign_channel`` SQL function (close the open row, open the new one, in
one transaction) is stubbed here with the same effect on the fake's rows; its
SQL text is guarded in ``tests/test_assign_channel_sql.py``.

A manager assigns only their own members to their own channels (anything else is
a 404); admin and exec assign anything. Deactivating a member ends their open
assignments.
"""
import sys
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import access, db, main, session, team
from tests.fakes import FakeSupabase

ADMIN, EXEC, MANAGER_A, MANAGER_B = 1, 2, 3, 4
TOKENS = {ADMIN: "tok-admin", EXEC: "tok-exec", MANAGER_A: "tok-a", MANAGER_B: "tok-b"}
PRANAV, MEET, RACHEL, LEFT = 10, 11, 12, 13
CH_A, CH_A2, CH_B, CH_NONE = "UCa", "UCa2", "UCb", "UCnone"
OPEN_A = 100


def _user(uid, role, name):
    return {"id": uid, "email": f"u{uid}@example.com", "name": name, "role": role,
            "is_active": True, "password_hash": "unused"}


def _member(mid, name, manager_id, active=True):
    return {"id": mid, "name": name, "manager_id": manager_id, "is_active": active,
            "created_at": "2026-11-18T00:00:00+00:00"}


def _assignment(aid, channel_id, member_id, starts_on, ends_on=None, by=ADMIN):
    return {"id": aid, "channel_id": channel_id, "team_member_id": member_id,
            "starts_on": starts_on, "ends_on": ends_on, "assigned_by": by,
            "created_at": "2026-11-01T00:00:00+00:00"}


def _assign_channel(sb):
    """The SQL function's effect on the fake's rows: lock and close the open
    row (``ends_on`` = the new start), insert the new one. The same member
    already open is returned unchanged."""
    def rpc(params):
        rows = sb._tables["channel_assignments"]
        open_rows = [r for r in rows
                     if r["channel_id"] == params["p_channel_id"] and r["ends_on"] is None]
        if open_rows:
            [current] = open_rows
            assert params["p_starts_on"] >= current["starts_on"], "the API let a back-date through"
            if current["team_member_id"] == params["p_team_member_id"]:
                return dict(current)
            current["ends_on"] = params["p_starts_on"]
        new = _assignment(max((r["id"] for r in rows), default=0) + 1,
                          params["p_channel_id"], params["p_team_member_id"],
                          params["p_starts_on"], by=params["p_assigned_by"])
        new["created_at"] = "2026-11-18T06:00:00+00:00"
        rows.append(new)
        return dict(new)
    return rpc


@pytest.fixture
def store():
    sb = FakeSupabase({
        "app_users": [_user(ADMIN, "admin", "Jugaad"), _user(EXEC, "exec", "Akshay"),
                      _user(MANAGER_A, "manager", "Justin"),
                      _user(MANAGER_B, "manager", "Ishwari")],
        "app_sessions": [{"token_hash": session.hash_token(t), "user_id": uid,
                          "expires_at": "2999-01-01T00:00:00+00:00"}
                         for uid, t in TOKENS.items()],
        "channels": [{"id": CH_A, "name": "Marathi", "manager_id": MANAGER_A},
                     {"id": CH_A2, "name": "Gujarati", "manager_id": MANAGER_A},
                     {"id": CH_B, "name": "Hindi", "manager_id": MANAGER_B},
                     {"id": CH_NONE, "name": "Telugu", "manager_id": None}],
        "member_targets": [],
        "team_members": [_member(PRANAV, "Pranav", MANAGER_A),
                         _member(MEET, "Meet", MANAGER_A),
                         _member(RACHEL, "Rachel", MANAGER_B),
                         _member(LEFT, "Left", MANAGER_A, active=False)],
        "channel_assignments": [
            _assignment(90, CH_A, MEET, "2026-10-01", "2026-11-01"),
            _assignment(OPEN_A, CH_A, PRANAV, "2026-11-01"),
            _assignment(101, CH_B, RACHEL, "2026-11-05", by=MANAGER_B),
        ],
    }, serial=("team_members", "channel_assignments"))
    sb._rpc["assign_channel"] = _assign_channel(sb)
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


def _rows(store, channel_id=None):
    rows = store.rows("channel_assignments")
    return sorted((r for r in rows if channel_id is None or r["channel_id"] == channel_id),
                  key=lambda r: r["id"])


def _open(store, channel_id):
    return [r for r in _rows(store, channel_id) if r["ends_on"] is None]


def _today_ist() -> str:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


# ── POST /channels/{id}/assign ───────────────────────────────────────────────

def test_a_manager_assigns_their_member_to_their_channel(store):
    r = _as(MANAGER_A).post(f"/channels/{CH_A}/assign",
                            json={"team_member_id": MEET, "starts_on": "2026-11-20"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True
    new = body["assignment"]
    assert (new["channel_id"], new["team_member_id"], new["starts_on"], new["ends_on"]) == \
        (CH_A, MEET, "2026-11-20", None)
    assert new["member_name"] == "Meet"
    assert new["assigned_by"] == MANAGER_A
    # The old open row is closed where the new one starts: no day credited twice
    # or to nobody.
    closed = next(r for r in _rows(store) if r["id"] == OPEN_A)
    assert closed["ends_on"] == "2026-11-20"
    assert [r["team_member_id"] for r in _open(store, CH_A)] == [MEET]
    assert store.rpc_calls == [("assign_channel", {
        "p_channel_id": CH_A, "p_team_member_id": MEET,
        "p_starts_on": "2026-11-20", "p_assigned_by": MANAGER_A})]


def test_the_first_assignment_of_a_channel_opens_a_row(store):
    r = _as(MANAGER_A).post(f"/channels/{CH_A2}/assign",
                            json={"team_member_id": PRANAV, "starts_on": "2026-11-18"})

    assert r.status_code == 200, r.text
    [row] = _rows(store, CH_A2)
    assert (row["team_member_id"], row["starts_on"], row["ends_on"]) == (PRANAV, "2026-11-18", None)


def test_starts_on_defaults_to_today_in_india(store):
    before = _today_ist()
    r = _as(MANAGER_A).post(f"/channels/{CH_A2}/assign", json={"team_member_id": PRANAV})
    after = _today_ist()

    assert r.status_code == 200, r.text
    assert r.json()["assignment"]["starts_on"] in {before, after}


def test_today_in_india_is_not_the_utc_or_pacific_day():
    # 20:00 UTC on the 18th is 01:30 IST on the 19th.
    assert team.ist_day(datetime(2026, 11, 18, 20, 0, tzinfo=ZoneInfo("UTC"))) == date(2026, 11, 19)
    assert team.ist_day(datetime(2026, 11, 18, 18, 0, tzinfo=ZoneInfo("UTC"))) == date(2026, 11, 18)


def test_a_start_before_the_open_rows_start_is_refused(store):
    before = _rows(store)
    r = _as(MANAGER_A).post(f"/channels/{CH_A}/assign",
                            json={"team_member_id": MEET, "starts_on": "2026-10-31"})

    assert r.status_code == 400
    assert "2026-11-01" in r.json()["detail"]
    assert _rows(store) == before
    assert store.rpc_calls == []


def test_a_start_on_the_open_rows_start_replaces_it_with_an_empty_range(store):
    r = _as(MANAGER_A).post(f"/channels/{CH_A}/assign",
                            json={"team_member_id": MEET, "starts_on": "2026-11-01"})

    assert r.status_code == 200, r.text
    closed = next(r for r in _rows(store) if r["id"] == OPEN_A)
    assert (closed["starts_on"], closed["ends_on"]) == ("2026-11-01", "2026-11-01")
    assert [r["team_member_id"] for r in _open(store, CH_A)] == [MEET]


def test_assigning_the_member_who_already_holds_it_changes_nothing(store):
    before = _rows(store)
    r = _as(MANAGER_A).post(f"/channels/{CH_A}/assign",
                            json={"team_member_id": PRANAV, "starts_on": "2026-11-20"})

    assert r.status_code == 200
    assert r.json()["changed"] is False
    assert r.json()["assignment"]["id"] == OPEN_A
    assert _rows(store) == before
    assert store.rpc_calls == []


def test_a_manager_cannot_assign_another_managers_member(store):
    r = _as(MANAGER_A).post(f"/channels/{CH_A}/assign",
                            json={"team_member_id": RACHEL, "starts_on": "2026-11-20"})

    assert r.status_code == 404
    assert r.json() == {"detail": access.TEAM_MEMBER_NOT_FOUND}
    assert store.rpc_calls == []


@pytest.mark.parametrize("channel_id", [CH_B, CH_NONE, "UCunknown"])
def test_a_manager_cannot_assign_to_a_channel_not_theirs(store, channel_id):
    r = _as(MANAGER_A).post(f"/channels/{channel_id}/assign",
                            json={"team_member_id": PRANAV, "starts_on": "2026-11-20"})

    assert r.status_code == 404
    assert r.json() == {"detail": access.CHANNEL_NOT_FOUND}
    assert store.rpc_calls == []


@pytest.mark.parametrize("uid", [MANAGER_A, ADMIN])
def test_an_unknown_member_is_404(store, uid):
    r = _as(uid).post(f"/channels/{CH_A}/assign",
                      json={"team_member_id": 999, "starts_on": "2026-11-20"})

    assert r.status_code == 404
    assert r.json() == {"detail": access.TEAM_MEMBER_NOT_FOUND}
    assert store.rpc_calls == []


def test_an_unknown_channel_is_404_for_admin_too(store):
    r = _as(ADMIN).post("/channels/UCunknown/assign",
                        json={"team_member_id": PRANAV, "starts_on": "2026-11-20"})

    assert r.status_code == 404
    assert r.json() == {"detail": access.CHANNEL_NOT_FOUND}
    assert store.rpc_calls == []


def test_a_deactivated_member_cannot_be_assigned(store):
    r = _as(MANAGER_A).post(f"/channels/{CH_A2}/assign",
                            json={"team_member_id": LEFT, "starts_on": "2026-11-20"})

    assert r.status_code == 400
    assert r.json() == {"detail": team.MEMBER_INACTIVE}
    assert _rows(store, CH_A2) == []


@pytest.mark.parametrize("uid", [ADMIN, EXEC])
@pytest.mark.parametrize("channel_id, member_id",
                         [(CH_B, PRANAV), (CH_NONE, RACHEL), (CH_A, RACHEL)])
def test_admin_and_exec_assign_anything(store, uid, channel_id, member_id):
    r = _as(uid).post(f"/channels/{channel_id}/assign",
                      json={"team_member_id": member_id, "starts_on": "2026-11-20"})

    assert r.status_code == 200, r.text
    assert [(o["team_member_id"], o["assigned_by"]) for o in _open(store, channel_id)] == \
        [(member_id, uid)]


@pytest.mark.parametrize("body", [{}, {"team_member_id": PRANAV, "starts_on": "soon"}])
def test_a_malformed_body_is_422(store, body):
    r = _as(MANAGER_A).post(f"/channels/{CH_A2}/assign", json=body)
    assert r.status_code == 422
    assert store.rpc_calls == []


def test_assign_needs_a_session(store):
    r = TestClient(main.app).post(f"/channels/{CH_A}/assign", json={"team_member_id": MEET})
    assert r.status_code == 401


# ── GET /team/assignments ────────────────────────────────────────────────────

def _listed(uid):
    r = _as(uid).get("/team/assignments")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_manager_sees_their_channels_and_their_history(store):
    body = _listed(MANAGER_A)

    assert [c["id"] for c in body["channels"]] == [CH_A2, CH_A]   # by name
    assert {c["manager_id"] for c in body["channels"]} == {MANAGER_A}
    assert [a["id"] for a in body["assignments"]] == [OPEN_A, 90]  # newest start first
    current, past = body["assignments"]
    assert current == {"id": OPEN_A, "channel_id": CH_A, "team_member_id": PRANAV,
                       "member_name": "Pranav", "starts_on": "2026-11-01", "ends_on": None,
                       "assigned_by": ADMIN, "assigned_by_name": "Jugaad",
                       "created_at": "2026-11-01T00:00:00+00:00"}
    assert (past["member_name"], past["ends_on"]) == ("Meet", "2026-11-01")


def test_a_manager_never_sees_another_teams_assignments(store):
    body = _listed(MANAGER_B)

    assert [c["id"] for c in body["channels"]] == [CH_B]
    assert [a["channel_id"] for a in body["assignments"]] == [CH_B]


@pytest.mark.parametrize("uid", [ADMIN, EXEC])
def test_admin_and_exec_see_every_channel_and_assignment(store, uid):
    body = _listed(uid)

    assert {c["id"] for c in body["channels"]} == {CH_A, CH_A2, CH_B, CH_NONE}
    assert {c["id"]: c["manager_name"] for c in body["channels"]}[CH_B] == "Ishwari"
    assert {c["id"]: c["manager_name"] for c in body["channels"]}[CH_NONE] is None
    assert sorted(a["id"] for a in body["assignments"]) == [90, OPEN_A, 101]


def test_a_manager_with_no_channels_sees_nothing(store):
    for c in store._tables["channels"]:
        if c["manager_id"] == MANAGER_B:
            c["manager_id"] = None
    assert _listed(MANAGER_B) == {"channels": [], "assignments": []}


def test_assignments_need_a_session(store):
    assert TestClient(main.app).get("/team/assignments").status_code == 401


def test_a_new_assignment_shows_in_the_list(store):
    _as(MANAGER_A).post(f"/channels/{CH_A}/assign",
                        json={"team_member_id": MEET, "starts_on": "2026-11-20"})

    rows = [(a["team_member_id"], a["starts_on"], a["ends_on"])
            for a in _listed(MANAGER_A)["assignments"] if a["channel_id"] == CH_A]
    assert rows == [(MEET, "2026-11-20", None), (PRANAV, "2026-11-01", "2026-11-20"),
                    (MEET, "2026-10-01", "2026-11-01")]


# ── deactivation ends open assignments ───────────────────────────────────────

def test_deactivating_a_member_ends_their_open_assignments(store):
    store._tables["channel_assignments"].append(_assignment(102, CH_A2, PRANAV, "2026-11-10"))
    today = _today_ist()

    r = _as(MANAGER_A).patch(f"/team/members/{PRANAV}", json={"is_active": False})

    assert r.status_code == 200, r.text
    ended = {r["id"]: r["ends_on"] for r in _rows(store) if r["team_member_id"] == PRANAV}
    assert set(ended) == {OPEN_A, 102}
    assert all(e in {today, (date.fromisoformat(today) + timedelta(days=1)).isoformat()}
               for e in ended.values())
    assert _open(store, CH_A) == [] and _open(store, CH_A2) == []
    # Past rows and other members' rows are untouched.
    assert next(r for r in _rows(store) if r["id"] == 90)["ends_on"] == "2026-11-01"
    assert _open(store, CH_B)[0]["team_member_id"] == RACHEL


def test_a_future_dated_assignment_ends_as_an_empty_range(store):
    store._tables["channel_assignments"].append(_assignment(102, CH_A2, PRANAV, "2999-01-01"))

    _as(MANAGER_A).patch(f"/team/members/{PRANAV}", json={"is_active": False})

    row = next(r for r in _rows(store) if r["id"] == 102)
    assert row["ends_on"] == "2999-01-01"


@pytest.mark.parametrize("uid", [ADMIN, EXEC])
def test_admin_deactivating_also_ends_assignments(store, uid):
    _as(uid).patch(f"/team/members/{RACHEL}", json={"is_active": False})
    assert _open(store, CH_B) == []


def test_a_rename_leaves_assignments_alone(store):
    before = _rows(store)
    _as(MANAGER_A).patch(f"/team/members/{PRANAV}", json={"name": "Pranav K"})
    assert _rows(store) == before


def test_another_managers_deactivation_attempt_ends_nothing(store):
    before = _rows(store)
    r = _as(MANAGER_A).patch(f"/team/members/{RACHEL}", json={"is_active": False})
    assert r.status_code == 404
    assert _rows(store) == before


# ── wiring ───────────────────────────────────────────────────────────────────

def test_assign_uses_the_channel_resolver():
    from tests.test_route_access import _api_routes, _calls

    [route] = [r for r in _api_routes()
               if r.path == "/channels/{channel_id}/assign" and "POST" in r.methods]
    assert access.require_channel in list(_calls(route.dependant))


# ── PUT /team/members/{id}/channels (the Roster's channel picker) ────────────

def _put(uid, member_id, channel_ids):
    return _as(uid).put(f"/team/members/{member_id}/channels", json={"channel_ids": channel_ids})


def test_the_picker_assigns_the_listed_channels_from_today(store):
    r = _put(MANAGER_A, MEET, [CH_A, CH_A2])

    assert r.status_code == 200, r.text
    assert r.json() == {"channel_ids": [CH_A, CH_A2], "added": [CH_A, CH_A2], "ended": []}
    today = _today_ist()
    assert [(o["team_member_id"], o["starts_on"]) for o in _open(store, CH_A)] == [(MEET, today)]
    assert [(o["team_member_id"], o["starts_on"]) for o in _open(store, CH_A2)] == [(MEET, today)]
    # Marathi moved from Pranav: his row closes where Meet's starts.
    assert next(r for r in _rows(store) if r["id"] == OPEN_A)["ends_on"] == today


def test_the_picker_ends_a_channel_left_unticked(store):
    r = _put(MANAGER_A, PRANAV, [])

    assert r.status_code == 200, r.text
    assert r.json() == {"channel_ids": [], "added": [], "ended": [CH_A]}
    assert _open(store, CH_A) == []
    assert next(r for r in _rows(store) if r["id"] == OPEN_A)["ends_on"] == _today_ist()


def test_the_picker_leaves_held_and_listed_channels_alone(store):
    before = _rows(store)
    r = _put(MANAGER_A, PRANAV, [CH_A])

    assert r.status_code == 200, r.text
    assert r.json() == {"channel_ids": [CH_A], "added": [], "ended": []}
    assert _rows(store) == before
    assert store.rpc_calls == []


def test_the_picker_never_ends_a_channel_the_user_cannot_see(store):
    # Pranav still holds Hindi, which belongs to the other team now.
    store._tables["channel_assignments"].append(_assignment(102, CH_B, PRANAV, "2026-11-10"))
    store._tables["channel_assignments"][:] = [
        r for r in store._tables["channel_assignments"] if r["id"] != 101]

    r = _put(MANAGER_A, PRANAV, [CH_A])

    assert r.status_code == 200, r.text
    assert _open(store, CH_B)[0]["team_member_id"] == PRANAV


def test_the_picker_refuses_a_channel_the_user_cannot_see(store):
    before = _rows(store)
    r = _put(MANAGER_A, PRANAV, [CH_A, CH_B])
    assert r.status_code == 404
    assert r.json()["detail"] == access.CHANNEL_NOT_FOUND
    assert _rows(store) == before


def test_the_picker_refuses_another_managers_member(store):
    r = _put(MANAGER_A, RACHEL, [CH_A])
    assert r.status_code == 404
    assert r.json()["detail"] == access.TEAM_MEMBER_NOT_FOUND


def test_the_picker_refuses_a_deactivated_member(store):
    r = _put(MANAGER_A, LEFT, [CH_A2])
    assert r.status_code == 400
    assert _open(store, CH_A2) == []


@pytest.mark.parametrize("uid", [ADMIN, EXEC])
def test_admin_and_exec_pick_any_channel(store, uid):
    r = _put(uid, RACHEL, [CH_B, CH_NONE])
    assert r.status_code == 200, r.text
    assert r.json()["added"] == [CH_NONE]
    assert _open(store, CH_NONE)[0]["team_member_id"] == RACHEL


def test_the_picker_uses_the_member_resolver():
    from tests.test_route_access import _api_routes, _calls

    [route] = [r for r in _api_routes()
               if r.path == "/team/members/{member_id}/channels" and "PUT" in r.methods]
    assert access.require_team_member in list(_calls(route.dependant))
