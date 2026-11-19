"""The uploads grid (team tracker 09, #151), through the HTTP seam: TestClient
over the app, with users, sessions, channels, members, assignments and
channel_uploads in a FakeSupabase.

``GET /team/uploads?from=&to=&manager_id=`` credits each upload in the IST
window to the member whose ``[starts_on, ends_on)`` assignment covered the
channel on the upload's IST day, else to Unassigned, and counts it per day as
``{total, shorts, long_form}`` (NULL ``is_short`` = long-form).
"""
import sys
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import db, main, session, team_uploads
from tests.fakes import FakeSupabase

ADMIN, EXEC, MANAGER_A, MANAGER_B = 1, 2, 3, 4
TOKENS = {ADMIN: "tok-admin", EXEC: "tok-exec", MANAGER_A: "tok-a", MANAGER_B: "tok-b"}
PRANAV, MEET, RACHEL, IDLE = 10, 11, 12, 13
CH_A, CH_A2, CH_B, CH_NONE = "UCa", "UCa2", "UCb", "UCnone"

WINDOW = {"from": "2026-11-10", "to": "2026-11-16"}


def _user(uid, role, name):
    return {"id": uid, "email": f"u{uid}@example.com", "name": name, "role": role,
            "is_active": True, "password_hash": "unused"}


def _member(mid, name, manager_id, active=True):
    return {"id": mid, "name": name, "manager_id": manager_id, "is_active": active,
            "created_at": "2026-11-01T00:00:00+00:00"}


def _assignment(aid, channel_id, member_id, starts_on, ends_on=None):
    return {"id": aid, "channel_id": channel_id, "team_member_id": member_id,
            "starts_on": starts_on, "ends_on": ends_on, "assigned_by": ADMIN,
            "created_at": "2026-11-01T00:00:00+00:00"}


def _utc(ist: str) -> str:
    """An IST wall-clock time ("2026-11-12 23:30") as the UTC timestamp
    PostgREST returns."""
    at = datetime.fromisoformat(ist).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return at.astimezone(ZoneInfo("UTC")).isoformat()


def _upload(video_id, channel_id, ist, is_short=False, privacy="public", scheduled=None):
    return {"video_id": video_id, "channel_id": channel_id, "title": video_id,
            "is_short": is_short, "duration_seconds": 30 if is_short else 300,
            "privacy_status": privacy, "scheduled_publish_at": scheduled,
            "thumbnail_url": None, "uploaded_at": _utc(ist),
            "playlist_published_at": _utc(ist), "video_published_at": None,
            "first_seen_at": _utc(ist), "last_seen_at": _utc(ist)}


def _store(uploads=(), assignments=None):
    sb = FakeSupabase({
        "app_users": [_user(ADMIN, "admin", "Jugaad"), _user(EXEC, "exec", "Akshay"),
                      _user(MANAGER_A, "manager", "Justin"),
                      _user(MANAGER_B, "manager", "Ishwari")],
        "app_sessions": [{"token_hash": session.hash_token(t), "user_id": uid,
                          "expires_at": "2999-01-01T00:00:00+00:00"}
                         for uid, t in TOKENS.items()],
        "channels": [
            {"id": CH_A, "name": "Marathi", "manager_id": MANAGER_A,
             "last_synced_at": "2026-11-16T10:00:00+00:00"},
            {"id": CH_A2, "name": "Gujarati", "manager_id": MANAGER_A,
             "last_synced_at": "2026-11-16T08:00:00+00:00"},
            {"id": CH_B, "name": "Hindi", "manager_id": MANAGER_B,
             "last_synced_at": "2026-11-16T09:00:00+00:00"},
            {"id": CH_NONE, "name": "Telugu", "manager_id": None, "last_synced_at": None},
        ],
        "team_members": [_member(PRANAV, "Pranav", MANAGER_A),
                         _member(MEET, "Meet", MANAGER_A),
                         _member(RACHEL, "Rachel", MANAGER_B),
                         _member(IDLE, "Idle", MANAGER_A)],
        "channel_assignments": assignments if assignments is not None else [
            _assignment(1, CH_A, PRANAV, "2026-11-01"),
            _assignment(2, CH_B, RACHEL, "2026-11-01"),
        ],
        "channel_uploads": list(uploads),
    })
    return sb


@pytest.fixture
def use():
    """Patch the fake in for every app module that reads ``supabase``."""
    started = []

    def _use(sb):
        # Collect first: patching app.db changes what db.supabase is.
        patches = [patch.object(mod, "supabase", return_value=sb)
                   for name, mod in list(sys.modules.items())
                   if name.startswith("app") and getattr(mod, "supabase", None) is db.supabase]
        for p in patches:
            p.start()
            started.append(p)
        return sb

    yield _use
    for p in reversed(started):
        p.stop()


def _as(uid):
    return TestClient(main.app, raise_server_exceptions=False,
                      cookies={session.COOKIE: TOKENS[uid]})


def _grid(uid, **params):
    r = _as(uid).get("/team/uploads", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _row(body, member_id):
    [row] = [r for r in body["rows"] if r["member_id"] == member_id]
    return row


def _cell(body, member_id, day):
    return _row(body, member_id)["days"][day]


# ── the grid ─────────────────────────────────────────────────────────────────

def test_the_grid_has_a_column_per_ist_day_and_a_cell_per_member_and_day(use):
    use(_store([_upload("v1", CH_A, "2026-11-12 10:00"),
                _upload("v2", CH_A, "2026-11-12 11:00", is_short=True)]))

    body = _grid(MANAGER_A, **WINDOW)

    assert body["days"] == [f"2026-11-{d}" for d in range(10, 17)]
    assert (body["from"], body["to"]) == ("2026-11-10", "2026-11-16")
    assert _cell(body, PRANAV, "2026-11-12") == {"total": 2, "shorts": 1, "long_form": 1}
    assert _cell(body, PRANAV, "2026-11-13") == {"total": 0, "shorts": 0, "long_form": 0}
    assert _row(body, PRANAV)["total"] == {"total": 2, "shorts": 1, "long_form": 1}
    assert _row(body, PRANAV)["name"] == "Pranav"


def test_an_upload_counts_on_its_ist_day_not_its_utc_day(use):
    # Both are on 2026-11-12 in UTC (18:00 and 19:00); in IST one is the 12th at
    # 23:30 and the other the 13th at 00:30.
    use(_store([_upload("late", CH_A, "2026-11-12 23:30"),
                _upload("early", CH_A, "2026-11-13 00:30")]))

    body = _grid(MANAGER_A, **WINDOW)

    assert _cell(body, PRANAV, "2026-11-12")["total"] == 1
    assert _cell(body, PRANAV, "2026-11-13")["total"] == 1


def test_the_window_edges_are_ist_midnights(use):
    use(_store([_upload("before", CH_A, "2026-11-09 23:59"),
                _upload("first", CH_A, "2026-11-10 00:00"),
                _upload("last", CH_A, "2026-11-16 23:59"),
                _upload("after", CH_A, "2026-11-17 00:00")]))

    body = _grid(MANAGER_A, **WINDOW)

    assert _row(body, PRANAV)["total"]["total"] == 2
    assert _cell(body, PRANAV, "2026-11-10")["total"] == 1
    assert _cell(body, PRANAV, "2026-11-16")["total"] == 1


def test_a_reassignment_mid_range_credits_each_member_their_own_days(use):
    use(_store(
        [_upload("old", CH_A, "2026-11-12 22:00"),
         _upload("new", CH_A, "2026-11-13 09:00"),
         _upload("newer", CH_A, "2026-11-14 09:00", is_short=True)],
        assignments=[_assignment(1, CH_A, PRANAV, "2026-11-01", "2026-11-13"),
                     _assignment(2, CH_A, MEET, "2026-11-13")]))

    body = _grid(MANAGER_A, **WINDOW)

    assert _row(body, PRANAV)["total"] == {"total": 1, "shorts": 0, "long_form": 1}
    assert _cell(body, PRANAV, "2026-11-12")["total"] == 1
    assert _row(body, MEET)["total"] == {"total": 2, "shorts": 1, "long_form": 1}
    assert _cell(body, MEET, "2026-11-13")["total"] == 1


def test_an_upload_on_a_channel_never_assigned_is_unassigned(use):
    use(_store(
        [_upload("held", CH_A, "2026-11-12 09:00"),
         _upload("never", CH_A2, "2026-11-12 09:00", is_short=True)],
        assignments=[_assignment(1, CH_A, PRANAV, "2026-11-12")]))

    body = _grid(MANAGER_A, **WINDOW)

    unassigned = _row(body, None)
    assert unassigned["name"] == "Unassigned"
    assert unassigned["total"] == {"total": 1, "shorts": 1, "long_form": 0}
    assert _row(body, PRANAV)["total"]["total"] == 1
    # Unassigned is the last row.
    assert body["rows"][-1]["member_id"] is None


def test_the_first_assignee_is_credited_with_the_channels_history(use):
    # Assigned today, Pranav gets the channel's earlier uploads too (backfill).
    use(_store(
        [_upload("before", CH_A, "2026-11-10 09:00"),
         _upload("held", CH_A, "2026-11-15 09:00", is_short=True)],
        assignments=[_assignment(1, CH_A, PRANAV, "2026-11-15")]))

    body = _grid(MANAGER_A, **WINDOW)

    assert _cell(body, PRANAV, "2026-11-10")["total"] == 1
    assert _row(body, PRANAV)["total"] == {"total": 2, "shorts": 1, "long_form": 1}
    assert _row(body, None)["total"]["total"] == 0


def test_a_later_assignee_gets_only_their_own_days_not_the_history(use):
    use(_store(
        [_upload("history", CH_A, "2026-11-10 09:00"),
         _upload("first", CH_A, "2026-11-12 09:00"),
         _upload("second", CH_A, "2026-11-14 09:00")],
        assignments=[_assignment(1, CH_A, PRANAV, "2026-11-12", "2026-11-14"),
                     _assignment(2, CH_A, MEET, "2026-11-14")]))

    body = _grid(MANAGER_A, **WINDOW)

    assert _row(body, PRANAV)["total"]["total"] == 2
    assert _cell(body, PRANAV, "2026-11-10")["total"] == 1
    assert _row(body, MEET)["total"]["total"] == 1


def test_the_backfill_reaches_past_the_window_to_find_the_first_assignee(use):
    # The first assignment starts after the window: its history still counts.
    use(_store(
        [_upload("old", CH_A, "2026-11-11 09:00")],
        assignments=[_assignment(1, CH_A, MEET, "2026-11-20")]))

    body = _grid(MANAGER_A, **WINDOW)

    assert _row(body, MEET)["total"]["total"] == 1
    assert _row(body, None)["total"]["total"] == 0


def test_an_upload_of_unknown_type_counts_as_long_form(use):
    use(_store([_upload("unknown", CH_A, "2026-11-12 09:00", is_short=None)]))

    body = _grid(MANAGER_A, **WINDOW)

    assert _cell(body, PRANAV, "2026-11-12") == {"total": 1, "shorts": 0, "long_form": 1}


def test_a_scheduled_video_counts_on_its_upload_day_not_its_go_live_day(use):
    use(_store([_upload("sched", CH_A, "2026-11-11 15:00", privacy="private",
                        scheduled="2026-11-20T04:30:00+00:00")]))

    body = _grid(MANAGER_A, **WINDOW)

    assert _cell(body, PRANAV, "2026-11-11")["total"] == 1
    assert _row(body, PRANAV)["total"]["total"] == 1


def test_members_with_nothing_uploaded_still_get_a_row(use):
    use(_store())

    body = _grid(MANAGER_A, **WINDOW)

    names = [r["name"] for r in body["rows"]]
    assert names == ["Idle", "Meet", "Pranav", "Unassigned"]
    assert all(r["total"]["total"] == 0 for r in body["rows"])


def test_every_visible_channel_reports_when_it_last_synced(use):
    use(_store())

    body = _grid(MANAGER_A, **WINDOW)

    assert body["channels"] == [
        {"id": CH_A2, "name": "Gujarati", "manager_id": MANAGER_A,
         "last_synced_at": "2026-11-16T08:00:00+00:00"},
        {"id": CH_A, "name": "Marathi", "manager_id": MANAGER_A,
         "last_synced_at": "2026-11-16T10:00:00+00:00"},
    ]


def test_paging_reads_past_the_1000_row_cap(use):
    many = [_upload(f"v{i:05d}", CH_A, "2026-11-12 10:00", is_short=i % 3 == 0)
            for i in range(1500)]
    use(_store(many))

    body = _grid(MANAGER_A, **WINDOW)

    assert _cell(body, PRANAV, "2026-11-12") == {"total": 1500, "shorts": 500, "long_form": 1000}


# ── scope ────────────────────────────────────────────────────────────────────

def _scattered():
    return _store([_upload("a1", CH_A, "2026-11-12 10:00"),
                   _upload("b1", CH_B, "2026-11-12 10:00"),
                   _upload("b2", CH_B, "2026-11-13 10:00", is_short=True),
                   _upload("n1", CH_NONE, "2026-11-12 10:00")])


def test_a_manager_sees_only_their_own_channels_and_members(use):
    use(_scattered())

    body = _grid(MANAGER_B, **WINDOW)

    assert [c["id"] for c in body["channels"]] == [CH_B]
    assert [r["member_id"] for r in body["rows"]] == [RACHEL, None]
    assert _row(body, RACHEL)["total"] == {"total": 2, "shorts": 1, "long_form": 1}
    assert _row(body, None)["total"]["total"] == 0


def test_a_manager_cannot_widen_their_scope_with_manager_id(use):
    use(_scattered())

    body = _grid(MANAGER_B, manager_id=MANAGER_A, **WINDOW)

    assert [c["id"] for c in body["channels"]] == [CH_B]
    assert body["manager_id"] is None
    assert sum(r["total"]["total"] for r in body["rows"]) == 2


def test_exec_sees_every_channel_without_a_filter(use):
    use(_scattered())

    body = _grid(EXEC, **WINDOW)

    assert {c["id"] for c in body["channels"]} == {CH_A, CH_A2, CH_B, CH_NONE}
    assert sum(r["total"]["total"] for r in body["rows"]) == 4
    # The channel with no manager's upload has no assignment: Unassigned.
    assert _row(body, None)["total"]["total"] == 1
    assert {m["id"] for m in body["managers"]} == {MANAGER_A, MANAGER_B}


@pytest.mark.parametrize("uid", [ADMIN, EXEC])
def test_admin_and_exec_filter_by_manager(use, uid):
    use(_scattered())

    body = _grid(uid, manager_id=MANAGER_B, **WINDOW)

    assert body["manager_id"] == MANAGER_B
    assert [c["id"] for c in body["channels"]] == [CH_B]
    assert [r["member_id"] for r in body["rows"]] == [RACHEL, None]
    assert _row(body, RACHEL)["total"]["total"] == 2


# ── the window ───────────────────────────────────────────────────────────────

def test_the_default_window_is_the_last_7_ist_days(use):
    use(_store())
    before = datetime.now(ZoneInfo("Asia/Kolkata")).date()

    body = _grid(MANAGER_A)

    after = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    assert len(body["days"]) == 7
    assert date.fromisoformat(body["to"]) in {before, after}
    assert date.fromisoformat(body["from"]) == date.fromisoformat(body["to"]) - timedelta(days=6)


def test_a_range_of_92_days_is_allowed(use):
    use(_store())

    body = _grid(MANAGER_A, **{"from": "2026-08-17", "to": "2026-11-16"})

    assert len(body["days"]) == 92


@pytest.mark.parametrize("params", [
    {"from": "2026-08-16", "to": "2026-11-16"},       # 93 days
    {"from": "2026-11-16", "to": "2026-11-10"},       # backwards
    {"from": "2026-11-31", "to": "2026-12-01"},       # not a date
])
def test_a_bad_range_is_422(use, params):
    use(_store())

    r = _as(MANAGER_A).get("/team/uploads", params=params)

    assert r.status_code == 422


def test_only_from_given_runs_7_days_from_it(use):
    use(_store())

    body = _grid(MANAGER_A, **{"from": "2026-11-01"})

    assert (body["from"], body["to"]) == ("2026-11-01", "2026-11-07")


def test_only_to_given_runs_7_days_up_to_it(use):
    use(_store())

    body = _grid(MANAGER_A, **{"to": "2026-11-07"})

    assert (body["from"], body["to"]) == ("2026-11-01", "2026-11-07")


def test_signed_out_is_401():
    r = TestClient(main.app, raise_server_exceptions=False).get(
        "/team/uploads", headers={"Accept": "application/json"})

    assert r.status_code == 401


# ── the IST day ──────────────────────────────────────────────────────────────

def test_the_ist_day_is_not_the_utc_or_pacific_day():
    # 20:00 UTC on the 18th is 01:30 IST on the 19th, and still the 18th in
    # Los Angeles (the quota day).
    at = datetime(2026, 11, 18, 20, 0, tzinfo=ZoneInfo("UTC"))
    assert team_uploads.ist_day(at) == date(2026, 11, 19)
    assert team_uploads.ist_day(datetime(2026, 11, 18, 18, 29, tzinfo=ZoneInfo("UTC"))) \
        == date(2026, 11, 18)
