"""Channel targets, the Board's moves and its read
(docs/superpowers/specs/2026-11-20-channel-targets-board-design.md), through the
HTTP seam, reusing the assignments tests' store.

``move_channel`` (SQL) is stubbed with its effect on the fake's rows; its text is
guarded below, in the style of tests/test_assign_channel_sql.py.
"""
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app import team
from tests.fakes import FakeSupabase
from tests.test_team_assignments import (  # noqa: F401  (``store`` is a fixture)
    ADMIN, CH_A, CH_A2, CH_B, CH_NONE, EXEC, MANAGER_A, MANAGER_B, MEET, OPEN_A,
    PRANAV, RACHEL, LEFT, _as, _assign_channel, store,
)

TODAY = team.ist_day().isoformat()


@pytest.fixture
def board(store):
    store._tables.setdefault("channel_targets", [])
    store._tables.setdefault("channel_uploads", [])
    assign = _assign_channel(store)

    def move(params):
        channels = {c["id"]: c for c in store._tables["channels"]}
        if params["p_team_member_id"] is not None:
            member = next(m for m in store._tables["team_members"]
                          if m["id"] == params["p_team_member_id"])
            channels[params["p_channel_id"]]["manager_id"] = member["manager_id"]
            assign({"p_channel_id": params["p_channel_id"],
                    "p_team_member_id": params["p_team_member_id"],
                    "p_starts_on": params["p_starts_on"], "p_assigned_by": params["p_moved_by"]})
        else:
            channels[params["p_channel_id"]]["manager_id"] = params["p_manager_id"]
            for a in store._tables["channel_assignments"]:
                if a["channel_id"] == params["p_channel_id"] and a["ends_on"] is None:
                    a["ends_on"] = max(params["p_starts_on"], a["starts_on"])
        return {}
    store._rpc["move_channel"] = move
    return store


def _channel(store, cid):
    return next(c for c in store.rows("channels") if c["id"] == cid)


def _open(store, cid):
    rows = [a for a in store.rows("channel_assignments")
            if a["channel_id"] == cid and a["ends_on"] is None]
    return rows[0]["team_member_id"] if rows else None


# ── channel targets ──────────────────────────────────────────────────────────

def _targets(uid, cid, days):
    return _as(uid).put(f"/channels/{cid}/targets", json={"days": days})


def test_a_manager_sets_their_channels_weekly_targets(board):
    r = _targets(MANAGER_A, CH_A, {"1": {"shorts": 3, "long_form": 1}, "6": {"shorts": 2}})

    assert r.status_code == 200, r.text
    week = r.json()["targets"]
    assert set(week) == {str(d) for d in range(1, 8)}
    assert week["1"] == {"shorts": 3, "long_form": 1}
    assert week["6"] == {"shorts": 2, "long_form": 0}
    assert week["2"] == {"shorts": 0, "long_form": 0}
    assert {r["updated_by"] for r in board.rows("channel_targets")} == {MANAGER_A}


def test_setting_targets_again_replaces_them_and_all_zero_clears(board):
    _targets(MANAGER_A, CH_A, {"1": {"shorts": 3}})
    week = _targets(MANAGER_A, CH_A, {"2": {"long_form": 4}}).json()["targets"]
    assert week["1"] == {"shorts": 0, "long_form": 0}
    assert len(board.rows("channel_targets")) == 7

    r = _targets(MANAGER_A, CH_A, {})
    assert r.json() == {"targets": None}
    assert board.rows("channel_targets") == []


def test_exec_cannot_set_targets_and_a_manager_not_another_teams(board):
    assert _targets(EXEC, CH_B, {"3": {"shorts": 1}}).status_code == 403
    assert _targets(MANAGER_A, CH_B, {"3": {"shorts": 1}}).status_code == 404
    assert _targets(ADMIN, "UCunknown", {"3": {"shorts": 1}}).status_code == 404
    assert board.rows("channel_targets") == []
    assert _targets(ADMIN, CH_B, {"3": {"shorts": 1}}).status_code == 200


@pytest.mark.parametrize("days", [{"0": {"shorts": 1}}, {"8": {"shorts": 1}},
                                  {"1": {"shorts": -1}}, {"1": {"long_form": 501}}])
def test_a_bad_target_is_422(board, days):
    assert _targets(MANAGER_A, CH_A, days).status_code == 422


def test_targets_read_sorts_only_by_columns_the_table_has(monkeypatch):
    """channel_targets has no `id`; sorting by it is a 500 on every page that
    reads targets (the fake doesn't know column names, so check them here)."""
    from tests import fakes
    columns = {"channel_id", "weekday", "shorts", "long_form", "updated_by", "updated_at"}
    sorted_by = []
    real_order = fakes.FakeQuery.order

    def spy(self, column, desc=False, **kw):
        if self._table == "channel_targets":
            sorted_by.append(column)
        return real_order(self, column, desc, **kw)

    monkeypatch.setattr(fakes.FakeQuery, "order", spy)
    sb = FakeSupabase({"channel_targets": [
        {"channel_id": "UCa", "weekday": 1, "shorts": 2, "long_form": 1}]})
    with patch.object(team, "supabase", return_value=sb):
        assert team.targets_for(["UCa"])["UCa"]["1"] == {"shorts": 2, "long_form": 1}
    assert sorted_by and set(sorted_by) <= columns


# ── moving a channel ─────────────────────────────────────────────────────────

def _move(uid, cid, **body):
    return _as(uid).post(f"/channels/{cid}/move", json=body)


def test_a_manager_moves_their_channel_to_another_of_their_members(board):
    r = _move(MANAGER_A, CH_A, team_member_id=MEET)

    assert r.status_code == 200, r.text
    assert r.json() == {"before": {"team_member_id": PRANAV, "manager_id": MANAGER_A},
                        "after": {"team_member_id": MEET, "manager_id": MANAGER_A},
                        "changed": True}
    assert _open(board, CH_A) == MEET
    [(_, params)] = [c for c in board.rpc_calls if c[0] == "move_channel"]
    assert params["p_starts_on"] == TODAY


def test_moving_to_the_holder_changes_nothing(board):
    r = _move(MANAGER_A, CH_A, team_member_id=PRANAV)

    assert r.json()["changed"] is False
    assert not [c for c in board.rpc_calls if c[0] == "move_channel"]


def test_a_channel_dropped_on_another_managers_member_moves_manager_too(board):
    r = _move(ADMIN, CH_A, team_member_id=RACHEL)

    assert r.status_code == 200, r.text
    assert r.json()["after"] == {"team_member_id": RACHEL, "manager_id": MANAGER_B}
    assert _channel(board, CH_A)["manager_id"] == MANAGER_B
    assert _open(board, CH_A) == RACHEL


def test_into_the_tray_unholds_it_and_keeps_its_manager(board):
    r = _move(MANAGER_A, CH_A)

    assert r.json()["after"] == {"team_member_id": None, "manager_id": MANAGER_A}
    assert _open(board, CH_A) is None
    assert _channel(board, CH_A)["manager_id"] == MANAGER_A


def test_the_admin_drops_a_channel_in_another_managers_tray_or_no_manager(board):
    assert _move(ADMIN, CH_A, manager_id=MANAGER_B).json()["after"] == \
        {"team_member_id": None, "manager_id": MANAGER_B}
    assert _channel(board, CH_A)["manager_id"] == MANAGER_B
    assert _move(ADMIN, CH_A, manager_id=None).status_code == 200
    assert _channel(board, CH_A)["manager_id"] is None


@pytest.mark.parametrize("uid,cid,body,status", [
    (EXEC, CH_A, {"team_member_id": MEET}, 403),
    (MANAGER_A, CH_A, {"team_member_id": RACHEL}, 404),      # another team's member
    (MANAGER_A, CH_B, {"team_member_id": PRANAV}, 404),      # another team's channel
    (MANAGER_A, CH_A, {"manager_id": MANAGER_B}, 403),       # another team's tray
    (MANAGER_A, CH_A, {"manager_id": None}, 403),            # no manager: admin only
    (MANAGER_A, CH_A2, {"team_member_id": LEFT}, 400),       # deactivated
    (ADMIN, CH_A, {"manager_id": EXEC}, 400),                # not a manager
    (ADMIN, "UCunknown", {"team_member_id": PRANAV}, 404),
])
def test_moves_that_are_refused(board, uid, cid, body, status):
    before = [dict(a) for a in board.rows("channel_assignments")]

    assert _move(uid, cid, **body).status_code == status
    assert board.rows("channel_assignments") == before
    assert not [c for c in board.rpc_calls if c[0] == "move_channel"]


def test_undo_moves_back_to_before(board):
    before = _move(MANAGER_A, CH_A, team_member_id=MEET).json()["before"]
    _move(MANAGER_A, CH_A, **before)

    assert _open(board, CH_A) == PRANAV


# ── the board's read ─────────────────────────────────────────────────────────

def _board(uid):
    r = _as(uid).get("/team/board")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_admin_sees_every_manager_member_and_channel(board):
    _targets(ADMIN, CH_A, {str(d): {"shorts": 2} for d in range(1, 8)})

    body = _board(ADMIN)

    assert [m["name"] for m in body["managers"]] == ["Ishwari", "Justin"]
    assert {m["id"] for m in body["members"]} == {PRANAV, MEET, RACHEL, LEFT}
    chs = {c["id"]: c for c in body["channels"]}
    assert set(chs) == {CH_A, CH_A2, CH_B, CH_NONE}
    assert (chs[CH_A]["holder_id"], chs[CH_A]["since"]) == (PRANAV, "2026-11-01")
    assert chs[CH_A2]["holder_id"] is None
    assert chs[CH_A]["today_target"] == {"shorts": 2, "long_form": 0}
    assert chs[CH_A2]["today_target"] is None and chs[CH_A2]["targets"] is None
    assert chs[CH_A]["today"] == {"total": 0, "shorts": 0, "long_form": 0}
    assert body["me"] == {"id": ADMIN, "role": "admin"}


def test_a_manager_sees_only_their_own_block(board):
    body = _board(MANAGER_A)

    assert [m["id"] for m in body["managers"]] == [MANAGER_A]
    assert {m["id"] for m in body["members"]} == {PRANAV, MEET, LEFT}
    assert {c["id"] for c in body["channels"]} == {CH_A, CH_A2}


def test_today_counts_the_uploads_live_today(board):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    board._tables["channel_uploads"].extend([
        {"video_id": "v1", "channel_id": CH_A, "is_short": True, "privacy_status": "public",
         "scheduled_publish_at": None, "public_at": None, "video_published_at": now,
         "uploaded_at": now},
        {"video_id": "v2", "channel_id": CH_A, "is_short": False, "privacy_status": "public",
         "scheduled_publish_at": None, "public_at": None, "video_published_at": now,
         "uploaded_at": now}])

    chs = {c["id"]: c for c in _board(MANAGER_A)["channels"]}

    assert chs[CH_A]["today"] == {"total": 2, "shorts": 1, "long_form": 1}


# ── move_channel() SQL guard ─────────────────────────────────────────────────

MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"


def _move_sql() -> str:
    defining = sorted((p.name, p.read_text()) for p in MIGRATIONS.glob("*.sql")
                      if re.search(r"create or replace function move_channel\b", p.read_text()))
    assert defining, "no migration defines move_channel()"
    m = re.search(r"create or replace function move_channel\b(.*?)\$\$;", defining[-1][1], re.S)
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", m.group(1))).lower()


def test_move_channel_is_one_plpgsql_body_pairing_the_manager_and_the_assignment():
    code = _move_sql()
    assert "language plpgsql" in code and "security definer" not in code
    # To a member: the manager follows the member, then assign_channel().
    assert code.index("update channels set manager_id = v_manager") \
        < code.index("assign_channel(p_channel_id, p_team_member_id")
    # To a tray: the open row is locked before it is closed, never back-dated.
    assert "for update" in code
    assert "greatest(p_starts_on, v_open.starts_on)" in code


def test_move_channel_is_granted_to_service_role_only():
    sql = " ".join(p.read_text() for p in MIGRATIONS.glob("*.sql")).lower()
    assert "revoke execute on function move_channel(text, bigint, bigint, date, bigint) from public" in sql
    assert "grant  execute on function move_channel(text, bigint, bigint, date, bigint) to service_role" in sql
