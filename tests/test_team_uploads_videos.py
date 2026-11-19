"""The uploads drill-down (team tracker 10, #152), through the HTTP seam:
TestClient over the app with a FakeSupabase, reusing the grid's store.

``GET /team/uploads/videos?member_id=&day=&manager_id=`` lists the uploads
behind one grid cell: the uploads on the user's visible channels on that IST
day, credited to that member (``member_id`` omitted = Unassigned) by the same
assignment mapping as the grid.
"""
import pytest

from tests.test_team_uploads import (  # noqa: F401  (``use`` is a fixture)
    ADMIN, CH_A, CH_A2, CH_B, CH_NONE, EXEC, IDLE, MANAGER_A, MANAGER_B, MEET,
    PRANAV, RACHEL, WINDOW, _as, _assignment, _grid, _store, _upload, use,
)


def _videos(uid, **params):
    r = _as(uid).get("/team/uploads/videos", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(body):
    return [v["video_id"] for v in body["videos"]]


# ── what the list holds ──────────────────────────────────────────────────────

def test_a_member_and_day_list_the_videos_behind_the_cell(use):
    use(_store([_upload("v1", CH_A, "2026-11-12 10:00"),
                _upload("v2", CH_A, "2026-11-12 23:30", is_short=True),
                _upload("next", CH_A, "2026-11-13 00:30"),
                _upload("other", CH_A2, "2026-11-12 10:00")]))

    body = _videos(MANAGER_A, member_id=PRANAV, day="2026-11-12")

    assert (body["member_id"], body["name"], body["day"]) == (PRANAV, "Pranav", "2026-11-12")
    # Oldest first; the 00:30 IST upload is the next day's; CH_A2 is unassigned.
    assert _ids(body) == ["v1", "v2"]
    [v1, v2] = body["videos"]
    assert v1 == {
        "video_id": "v1", "title": "v1", "thumbnail_url": None,
        "channel_id": CH_A, "channel_name": "Marathi",
        "uploaded_at": "2026-11-12T04:30:00+00:00",
        "uploaded_at_ist": "2026-11-12T10:00:00+05:30",
        "is_short": False, "privacy_status": "public", "scheduled_publish_at": None,
        "status": "public",
    }
    assert v2["is_short"] is True
    assert v2["uploaded_at_ist"] == "2026-11-12T23:30:00+05:30"


def test_the_status_pill_is_scheduled_public_unlisted_or_private(use):
    use(_store([_upload("s", CH_A, "2026-11-12 09:00", privacy="private",
                        scheduled="2026-11-20T04:30:00+00:00"),
                _upload("pub", CH_A, "2026-11-12 10:00"),
                _upload("unl", CH_A, "2026-11-12 11:00", privacy="unlisted"),
                _upload("pri", CH_A, "2026-11-12 12:00", privacy="private"),
                _upload("unknown", CH_A, "2026-11-12 13:00", is_short=None)]))

    body = _videos(MANAGER_A, member_id=PRANAV, day="2026-11-12")

    by_id = {v["video_id"]: v for v in body["videos"]}
    assert {k: v["status"] for k, v in by_id.items()} == {
        "s": "scheduled", "pub": "public", "unl": "unlisted", "pri": "private",
        "unknown": "public"}
    assert by_id["s"]["scheduled_publish_at"] == "2026-11-20T04:30:00+00:00"
    # An unclassified video says so; the UI shows "?".
    assert by_id["unknown"]["is_short"] is None


def test_unassigned_is_member_id_omitted(use):
    use(_store(
        [_upload("before", CH_A, "2026-11-11 09:00"),
         _upload("held", CH_A, "2026-11-12 09:00"),
         _upload("never", CH_A2, "2026-11-12 09:00", is_short=True)],
        assignments=[_assignment(1, CH_A, PRANAV, "2026-11-12")]))

    body = _videos(MANAGER_A, day="2026-11-12")

    assert (body["member_id"], body["name"]) == (None, "Unassigned")
    assert _ids(body) == ["never"]
    # Before the channel's first assignment: its first assignee's (backfill).
    assert _ids(_videos(MANAGER_A, day="2026-11-11")) == []
    assert _ids(_videos(MANAGER_A, member_id=PRANAV, day="2026-11-11")) == ["before"]


def test_a_reassigned_channel_lists_each_day_under_its_holder(use):
    use(_store(
        [_upload("old", CH_A, "2026-11-12 22:00"),
         _upload("new", CH_A, "2026-11-13 09:00")],
        assignments=[_assignment(1, CH_A, PRANAV, "2026-11-01", "2026-11-13"),
                     _assignment(2, CH_A, MEET, "2026-11-13")]))

    assert _ids(_videos(MANAGER_A, member_id=PRANAV, day="2026-11-12")) == ["old"]
    assert _ids(_videos(MANAGER_A, member_id=PRANAV, day="2026-11-13")) == []
    assert _ids(_videos(MANAGER_A, member_id=MEET, day="2026-11-13")) == ["new"]


def test_a_member_with_nothing_that_day_gets_an_empty_list(use):
    use(_store([_upload("v1", CH_A, "2026-11-12 10:00")]))

    body = _videos(MANAGER_A, member_id=IDLE, day="2026-11-12")

    assert (body["name"], body["videos"]) == ("Idle", [])


# ── scope ────────────────────────────────────────────────────────────────────

def _scattered():
    return _store([_upload("a1", CH_A, "2026-11-12 10:00"),
                   _upload("b1", CH_B, "2026-11-12 10:00"),
                   _upload("n1", CH_NONE, "2026-11-12 10:00")])


def test_a_manager_cannot_drill_into_another_teams_member(use):
    use(_scattered())

    r = _as(MANAGER_A).get("/team/uploads/videos",
                           params={"member_id": RACHEL, "day": "2026-11-12"})

    assert r.status_code == 404
    assert r.json() == {"detail": "team_member_not_found"}


@pytest.mark.parametrize("uid", [ADMIN, EXEC, MANAGER_A])
def test_an_unknown_member_is_404(use, uid):
    use(_scattered())

    r = _as(uid).get("/team/uploads/videos", params={"member_id": 999, "day": "2026-11-12"})

    assert r.status_code == 404
    assert r.json() == {"detail": "team_member_not_found"}


def test_a_managers_unassigned_holds_only_their_own_channels(use):
    use(_scattered())

    assert _ids(_videos(MANAGER_A, day="2026-11-12")) == []
    assert _ids(_videos(EXEC, day="2026-11-12")) == ["n1"]


def test_a_manager_sees_another_teams_member_holding_one_of_their_channels(use):
    # The admin assigned Rachel (Ishwari's) to a channel of Justin's: Justin's
    # grid shows her row, so he can open it, and sees only his channel's uploads.
    use(_store([_upload("a1", CH_A, "2026-11-12 10:00"),
                _upload("b1", CH_B, "2026-11-12 10:00")],
               assignments=[_assignment(1, CH_A, RACHEL, "2026-11-01"),
                            _assignment(2, CH_B, RACHEL, "2026-11-01")]))

    assert _ids(_videos(MANAGER_A, member_id=RACHEL, day="2026-11-12")) == ["a1"]
    assert _ids(_videos(EXEC, member_id=RACHEL, day="2026-11-12")) == ["a1", "b1"]


@pytest.mark.parametrize("uid", [ADMIN, EXEC])
def test_admin_and_exec_narrow_by_manager_like_the_grid(use, uid):
    use(_scattered())

    assert _ids(_videos(uid, day="2026-11-12", manager_id=MANAGER_B)) == []
    assert _ids(_videos(uid, member_id=RACHEL, day="2026-11-12",
                        manager_id=MANAGER_B)) == ["b1"]
    assert _ids(_videos(uid, member_id=RACHEL, day="2026-11-12",
                        manager_id=MANAGER_A)) == []


@pytest.mark.parametrize("params", [{}, {"day": "2026-11-31"}, {"day": "soon"}])
def test_a_missing_or_bad_day_is_422(use, params):
    use(_scattered())

    r = _as(MANAGER_A).get("/team/uploads/videos", params=params)

    assert r.status_code == 422


# ── the list matches the grid ────────────────────────────────────────────────

def _busy():
    return _store(
        [_upload("a-12-late", CH_A, "2026-11-12 23:30"),
         _upload("a-13-early", CH_A, "2026-11-13 00:30", is_short=True),
         _upload("a-14", CH_A, "2026-11-14 12:00", is_short=None),
         _upload("a2-12", CH_A2, "2026-11-12 09:00"),
         _upload("a2-15", CH_A2, "2026-11-15 09:00", is_short=True),
         _upload("b-10", CH_B, "2026-11-10 00:00"),
         _upload("b-16", CH_B, "2026-11-16 23:59", privacy="private",
                 scheduled="2026-11-25T00:00:00+00:00"),
         _upload("n-13", CH_NONE, "2026-11-13 10:00"),
         _upload("outside", CH_A, "2026-11-17 00:00")],
        assignments=[_assignment(1, CH_A, PRANAV, "2026-11-01", "2026-11-14"),
                     _assignment(2, CH_A, MEET, "2026-11-14"),
                     _assignment(3, CH_A2, MEET, "2026-11-13", "2026-11-15"),
                     _assignment(4, CH_B, RACHEL, "2026-11-01")])


@pytest.mark.parametrize("uid,manager_id", [
    (MANAGER_A, None), (MANAGER_B, None), (EXEC, None), (ADMIN, MANAGER_A),
])
def test_every_cells_drill_down_count_equals_the_grid_cell(use, uid, manager_id):
    use(_busy())
    scope = {} if manager_id is None else {"manager_id": manager_id}

    grid = _grid(uid, **WINDOW, **scope)

    assert any(r["total"]["total"] for r in grid["rows"])
    for row in grid["rows"]:
        for day, cell in row["days"].items():
            params = {"day": day, **scope}
            if row["member_id"] is not None:
                params["member_id"] = row["member_id"]
            videos = _videos(uid, **params)["videos"]
            shorts = sum(1 for v in videos if v["is_short"] is True)
            assert {"total": len(videos), "shorts": shorts,
                    "long_form": len(videos) - shorts} == cell, (row["name"], day)


# ── the "By channel" view ────────────────────────────────────────────────────

@pytest.mark.parametrize("uid,manager_id", [
    (MANAGER_A, None), (MANAGER_B, None), (EXEC, None), (ADMIN, MANAGER_A),
])
def test_channel_rows_count_every_upload_once_and_match_their_drill_down(use, uid, manager_id):
    use(_busy())
    scope = {} if manager_id is None else {"manager_id": manager_id}

    grid = _grid(uid, **WINDOW, **scope)

    # One row per channel in scope, by name, and the same uploads as the
    # member rows: the two views total the same.
    assert [r["channel_id"] for r in grid["channel_rows"]] == [c["id"] for c in grid["channels"]]
    for k in ("total", "shorts", "long_form"):
        assert (sum(r["total"][k] for r in grid["channel_rows"])
                == sum(r["total"][k] for r in grid["rows"]))
    for row in grid["channel_rows"]:
        for day, cell in row["days"].items():
            body = _videos(uid, day=day, channel_id=row["channel_id"], **scope)
            assert {v["channel_id"] for v in body["videos"]} <= {row["channel_id"]}
            shorts = sum(1 for v in body["videos"] if v["is_short"] is True)
            assert {"total": len(body["videos"]), "shorts": shorts,
                    "long_form": len(body["videos"]) - shorts} == cell, (row["name"], day)


def test_a_channel_row_holds_uploads_whoever_was_credited(use):
    use(_busy())

    grid = _grid(ADMIN, **WINDOW)
    marathi = next(r for r in grid["channel_rows"] if r["channel_id"] == CH_A)

    # Pranav held Marathi until 11-14, Meet from then: one channel row.
    assert (marathi["name"], marathi["manager_name"]) == ("Marathi", "Justin")
    assert marathi["days"]["2026-11-12"]["total"] == 1
    assert marathi["days"]["2026-11-14"]["total"] == 1
    assert marathi["total"] == {"total": 3, "shorts": 1, "long_form": 2}
    body = _videos(ADMIN, day="2026-11-14", channel_id=CH_A, member_id=PRANAV)
    assert (body["name"], body["channel_id"], body["member_id"]) == ("Marathi", CH_A, None)
    assert _ids(body) == ["a-14"]


def test_a_channel_with_no_uploads_still_gets_a_row(use):
    use(_busy())

    rows = {r["channel_id"]: r for r in _grid(EXEC, **WINDOW)["channel_rows"]}

    assert set(rows) == {CH_A, CH_A2, CH_B, CH_NONE}
    assert rows[CH_NONE]["manager_id"] is None


@pytest.mark.parametrize("channel_id", [CH_B, CH_NONE, "UCunknown"])
def test_a_manager_cannot_drill_into_a_channel_outside_their_scope(use, channel_id):
    use(_busy())

    r = _as(MANAGER_A).get("/team/uploads/videos",
                           params={"day": "2026-11-13", "channel_id": channel_id})

    assert r.status_code == 404
    assert r.json() == {"detail": "channel_not_found"}


def test_admins_manager_filter_narrows_the_channel_drill_down_too(use):
    use(_busy())

    r = _as(ADMIN).get("/team/uploads/videos", params={
        "day": "2026-11-10", "channel_id": CH_B, "manager_id": MANAGER_A})

    assert r.status_code == 404
