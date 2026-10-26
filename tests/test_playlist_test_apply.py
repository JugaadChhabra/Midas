"""Slice 2 · S2.2 — the playlist test's queued, budgeted apply (spec Part 5 S2.2,
Part 2 §2.5; #88).

Runs against the FakeSupabase double and a fake YouTube client that records
every call: the real playlist_test, playlists_router, quota and human_edits code,
with only the database and YouTube faked.
"""
import json
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import httplib2
import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from googleapiclient.errors import HttpError

from app import human_edits, job_status, main, playlist_test, playlists_router, quota
from app.job_status import JobRunFailed
from tests.fakes import FakeSupabase

CH, OTHER = "c1", "c2"


def http_error(status: int, reason: str, message: str = "") -> HttpError:
    content = {"error": {"code": status, "message": message or reason,
                         "errors": [{"reason": reason, "message": message or reason}]}}
    return HttpError(httplib2.Response({"status": status}), json.dumps(content).encode())


MANUAL_SORT = lambda: http_error(400, "manualSortRequired", "Manual sort required.")  # noqa: E731
QUOTA = lambda: http_error(403, "quotaExceeded", "You have exceeded your quota.")       # noqa: E731
BROKEN = lambda: http_error(404, "videoNotFound", "Video not found.")                  # noqa: E731
TOKEN = lambda: Exception("invalid_grant: Token has been expired or revoked.")          # noqa: E731


class _Call:
    def __init__(self, result):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeYouTube:
    """Records every `playlistItems().insert` body. `fail` maps a video id to
    the errors its next inserts raise, in order; `manual_sort=False` refuses
    every position, as YouTube does on a playlist that isn't sorted manually."""

    def __init__(self, fail=None, manual_sort=True):
        self.calls: list[dict] = []
        self.fail = {k: list(v) for k, v in (fail or {}).items()}
        self.manual_sort = manual_sort

    def playlistItems(self):
        return self

    def insert(self, part, body):
        assert part == "snippet"
        self.calls.append(body)
        snippet = body["snippet"]
        vid = snippet["resourceId"]["videoId"]
        if self.fail.get(vid):
            return _Call(self.fail[vid].pop(0)())
        if "position" in snippet and not self.manual_sort:
            return _Call(MANUAL_SORT())
        return _Call({"id": f"item-{vid}-{len(self.calls)}"})

    def sent(self):
        return [(c["snippet"]["playlistId"], c["snippet"]["resourceId"]["videoId"],
                 c["snippet"].get("position")) for c in self.calls]


def arm(arm_id, playlist_id, proposal_ids, *, channel=CH, status="planned", which="treated",
        **kw):
    return {"id": arm_id, "channel_id": channel, "playlist_id": playlist_id, "arm": which,
            "status": status, "proposal_ids": list(proposal_ids),
            "first_applied_at": None, "last_applied_at": None, **kw}


def proposal(pid, arm_id, playlist_id, video_id, *, status="approved", **kw):
    return {"id": pid, "video_id": video_id, "playlist_id": playlist_id,
            "video_title": f"Title {video_id}", "playlist_title": f"Playlist {playlist_id}",
            "action": "add", "similarity": 0.95, "decision_source": "experiment",
            "status": status, "arm_id": arm_id, "applied_at": None,
            "playlist_item_id": None, "apply_error": None, "decided_at": None, **kw}


def dose(arm_id, playlist_id, n, *, first_pid=None, channel=CH, **arm_kw):
    """A treated arm with `n` approved proposals, ranked v0 first."""
    first_pid = first_pid or arm_id * 100
    ps = [proposal(first_pid + i, arm_id, playlist_id, f"{playlist_id}-v{i}") for i in range(n)]
    return arm(arm_id, playlist_id, [p["id"] for p in ps], channel=channel, **arm_kw), ps


def world(arms, proposals, *, assignments=()):
    return FakeSupabase({
        "playlist_arms": list(arms),
        "playlist_proposals": list(proposals),
        "playlist_assignments": list(assignments),
        "quota_log": [],
    })


@contextmanager
def wired(sb, yt, *, used=0, **settings):
    """`used` = units already spent today by everything else."""
    settings = {"PLAYLIST_APPLY_ENABLED": True, "DRY_RUN": False,
                "PLAYLIST_TEST_DAILY_UNITS": 2000, "PLAYLIST_TEST_MAX_ATTEMPTS": 3,
                "YT_DAILY_QUOTA": 10000, "YT_QUOTA_SAFETY_BUFFER": 300,
                "YT_QUOTA_COLLECTION_RESERVE": 3000, **settings}
    meter = lambda: used + sum(r["units"] for r in sb.rows("quota_log"))  # noqa: E731
    with patch.object(playlist_test, "supabase", return_value=sb), \
         patch("app.playlists.supabase", return_value=sb), \
         patch("app.quota.supabase", return_value=sb), \
         patch("app.human_edits.supabase", return_value=sb), \
         patch.object(quota, "units_used_today", meter), \
         patch.object(playlist_test, "youtube_for_channel", return_value=yt), \
         patch.multiple(playlist_test.settings, **settings):
        yield


def proposals_by_id(sb):
    return {p["id"]: p for p in sb.rows("playlist_proposals")}


def arms_by_id(sb):
    return {a["id"]: a for a in sb.rows("playlist_arms")}


# ── approval queues ───────────────────────────────────────────────────────

def _decide(sb, yt, ids, decision="approved"):
    with patch.object(playlists_router, "supabase", return_value=sb), \
         patch("app.playlists.supabase", return_value=sb), \
         patch("app.quota.supabase", return_value=sb), \
         patch.object(playlists_router, "youtube_for_channel", return_value=yt):
        return playlists_router.decide_proposals(
            CH, playlists_router.DecideBody(ids=ids, decision=decision))


def _proposals_world(*proposals):
    return FakeSupabase({
        "playlist_proposals": list(proposals),
        "playlists": [{"id": "PL1", "channel_id": CH}],
        "playlist_assignments": [],
        "quota_log": [],
    })


def test_approving_a_test_proposal_queues_it_and_sends_nothing():
    sb = _proposals_world(proposal(1, 7, "PL1", "v1", status="pending"))
    yt = FakeYouTube()
    out = _decide(sb, yt, [1])
    assert yt.calls == []
    assert out == {"executed": 0, "rejected": 0, "queued": 1}
    [p] = sb.rows("playlist_proposals")
    assert p["status"] == "approved" and p["decided_at"]
    assert p["applied_at"] is None and p["playlist_item_id"] is None
    assert sb.rows("playlist_assignments") == [] and sb.rows("quota_log") == []
    assert [w[:2] for w in sb.writes] == [("playlist_proposals", "update")]


def test_rejecting_a_test_proposal_marks_it_rejected_and_sends_nothing():
    sb = _proposals_world(proposal(1, 7, "PL1", "v1", status="pending"))
    yt = FakeYouTube()
    assert _decide(sb, yt, [1], "rejected") == {"executed": 0, "rejected": 1}
    assert yt.calls == []
    [p] = sb.rows("playlist_proposals")
    assert p["status"] == "rejected" and p["decided_at"]


def test_reject_relabels_only_pending_proposals():
    """An approved test add may already be on YouTube; rejecting it must not
    hide that (nor relabel an approved legacy proposal already executed)."""
    sb = _proposals_world(
        proposal(1, 7, "PL1", "v1", status="pending"),
        proposal(2, 7, "PL1", "v2", applied_at="2026-10-27T11:00:00+00:00", playlist_item_id="i2"),
        proposal(3, 7, "PL1", "v3"))
    yt = FakeYouTube()
    assert _decide(sb, yt, [1, 2, 3], "rejected") == {"executed": 0, "rejected": 1}
    assert yt.calls == []
    assert {pid: p["status"] for pid, p in proposals_by_id(sb).items()} == {
        1: "rejected", 2: "approved", 3: "approved"}


def test_a_proposal_without_arm_id_still_executes_at_once_unchanged():
    legacy = {"id": 2, "video_id": "v2", "playlist_id": "PL1", "action": "add",
              "similarity": 0.8, "decision_source": "embedding", "status": "pending"}
    sb = _proposals_world(legacy, proposal(3, 7, "PL1", "v3", status="pending"))
    yt = FakeYouTube()
    out = _decide(sb, yt, [2, 3])
    # The pre-S2.2 add: sent at once, appended (no position: the same body as
    # before `position` existed), recorded as the proposal's own source.
    assert yt.calls == [{"snippet": {"playlistId": "PL1",
                                     "resourceId": {"kind": "youtube#video", "videoId": "v2"}}}]
    assert out == {"executed": 1, "rejected": 0, "queued": 1}
    [a] = sb.rows("playlist_assignments")
    assert (a["video_id"], a["playlist_id"], a["action"], a["decision_source"],
            a["playlist_item_id"]) == ("v2", "PL1", "added", "embedding", "item-v2-1")
    assert {p["id"]: p["status"] for p in sb.rows("playlist_proposals")} == {
        2: "approved", 3: "approved"}


def test_without_test_proposals_the_response_is_as_before():
    legacy = {"id": 2, "video_id": "v2", "playlist_id": "PL1", "action": "add",
              "similarity": 0.8, "decision_source": "embedding", "status": "pending"}
    sb = _proposals_world(legacy)
    assert _decide(sb, FakeYouTube(), [2]) == {"executed": 1, "rejected": 0}


def test_the_insert_wrapper_sends_a_position_only_when_given():
    yt = FakeYouTube()
    sb = FakeSupabase({"quota_log": []})
    with patch("app.quota.supabase", return_value=sb):
        playlist_test.yt_playlist_items_insert(yt, CH, "PL1", "v1")
        playlist_test.yt_playlist_items_insert(yt, CH, "PL1", "v2", position=0)
    assert "position" not in yt.calls[0]["snippet"]
    assert yt.calls[1]["snippet"]["position"] == 0


# ── the kill switch and DRY_RUN ───────────────────────────────────────────

def test_the_kill_switch_sends_and_writes_nothing():
    a, ps = dose(1, "PL1", 3)
    sb, yt = world([a], ps), FakeYouTube()
    with wired(sb, yt, PLAYLIST_APPLY_ENABLED=False):
        assert playlist_test.run_apply() is None
    assert yt.calls == [] and sb.writes == []


def test_dry_run_sends_and_writes_nothing(caplog):
    a, ps = dose(1, "PL1", 3)
    sb, yt = world([a], ps), FakeYouTube()
    with wired(sb, yt, DRY_RUN=True), caplog.at_level("WARNING"):
        assert playlist_test.run_apply() is None
    assert yt.calls == [] and sb.writes == []
    assert "[DRY_RUN]" in caplog.text and "PL1-v0" in caplog.text


def test_the_kill_switch_defaults_off_and_the_settings_start_values():
    from app.config import Settings
    s = Settings()
    assert (s.PLAYLIST_APPLY_ENABLED, s.PLAYLIST_TEST_DAILY_UNITS,
            s.PLAYLIST_TEST_MAX_ATTEMPTS) == (False, 2000, 3)


# ── order ─────────────────────────────────────────────────────────────────

def test_adds_go_in_at_the_top_in_candidate_rank():
    a, ps = dose(1, "PL1", 3)
    a["proposal_ids"] = [102, 100, 101]               # rank: v2, v0, v1
    sb, yt = world([a], ps), FakeYouTube()
    with wired(sb, yt):
        playlist_test.run_apply()
    assert yt.sent() == [("PL1", "PL1-v2", 0), ("PL1", "PL1-v0", 1), ("PL1", "PL1-v1", 2)]
    for p in sb.rows("playlist_proposals"):
        assert p["applied_at"] and p["playlist_item_id"] and p["apply_error"] is None


def test_a_refused_position_is_retried_once_appended_and_noted():
    a, ps = dose(1, "PL1", 2)
    sb, yt = world([a], ps), FakeYouTube(manual_sort=False)
    with wired(sb, yt):
        assert playlist_test.run_apply() is None
    # The first add is refused at position 0 and appended; the playlist isn't
    # sorted manually, so the second goes straight in appended, in rank.
    assert yt.sent() == [("PL1", "PL1-v0", 0), ("PL1", "PL1-v0", None), ("PL1", "PL1-v1", None)]
    got = proposals_by_id(sb)
    assert got[100]["applied_at"] and got[100]["playlist_item_id"] == "item-PL1-v0-2"
    assert got[100]["apply_error"]["reason"] == playlist_test.POSITION_REFUSED
    assert "manualSortRequired" in got[100]["apply_error"]["detail"]
    assert got[101]["applied_at"] and got[101]["apply_error"] is None


def test_a_playlist_that_refused_a_position_is_appended_to_in_later_runs():
    a, ps = dose(1, "PL1", 3, status="applying")
    ps[0].update(applied_at="2026-10-28T11:00:00+00:00", playlist_item_id="i0",
                 apply_error={"reason": playlist_test.POSITION_REFUSED, "detail": "x"})
    ps[1]["apply_error"] = {"reason": "failed", "detail": "x", "attempts": 1}
    sb, yt = world([a], ps), FakeYouTube(manual_sort=False)
    with wired(sb, yt):
        playlist_test.run_apply()
    assert yt.sent() == [("PL1", "PL1-v1", None), ("PL1", "PL1-v2", None)]


def test_a_quota_stop_on_a_channels_only_add_does_not_fail_the_run():
    a, ps = dose(1, "PL1", 1)
    sb, yt = world([a], ps), FakeYouTube(fail={"PL1-v0": [QUOTA]})
    with wired(sb, yt):
        assert playlist_test.run_apply() == {
            "partial_errors": {CH: "youtube_quota_exceeded: stopped for the day"}}
    assert arms_by_id(sb)[1]["status"] == "planned"


def test_a_400_that_is_not_about_the_position_is_a_normal_error():
    a, ps = dose(1, "PL1", 1)
    sb = world([a], ps)
    yt = FakeYouTube(fail={"PL1-v0": [lambda: http_error(400, "invalidValue", "Bad video id.")]})
    with wired(sb, yt), pytest.raises(JobRunFailed):
        playlist_test.run_apply()
    assert len(yt.calls) == 1
    err = proposals_by_id(sb)[100]["apply_error"]
    assert (err["reason"], err["attempts"]) == ("failed", 1)


def test_a_retry_goes_in_at_its_rank_among_the_adds_already_sent():
    a, ps = dose(1, "PL1", 3, status="applying")
    ps[0].update(applied_at="2026-10-28T11:00:00+00:00", playlist_item_id="i0")
    ps[1]["apply_error"] = {"reason": "failed", "detail": "x", "attempts": 1}
    ps[2].update(applied_at="2026-10-28T11:00:01+00:00", playlist_item_id="i2")
    sb, yt = world([a], ps), FakeYouTube()
    with wired(sb, yt):
        playlist_test.run_apply()
    assert yt.sent() == [("PL1", "PL1-v1", 1)]


# ── the budget ────────────────────────────────────────────────────────────

def test_a_playlist_that_does_not_fit_the_budget_is_not_half_sent_and_the_job_stops():
    a1, p1 = dose(1, "PL1", 5)                         # 250u
    a2, p2 = dose(2, "PL2", 5)                         # 250u: over a 400u budget
    a3, p3 = dose(3, "PL3", 1)                         # 50u: would fit, but the day is over
    sb, yt = world([a1, a2, a3], p1 + p2 + p3), FakeYouTube()
    with wired(sb, yt, PLAYLIST_TEST_DAILY_UNITS=400):
        assert playlist_test.run_apply() is None
    assert [s[0] for s in yt.sent()] == ["PL1"] * 5
    got = proposals_by_id(sb)
    assert not any(got[p["id"]]["applied_at"] for p in p2 + p3)
    assert arms_by_id(sb)[2]["status"] == "planned"


def test_the_ledger_above_the_collection_reserve_also_stops_the_job():
    a, ps = dose(1, "PL1", 5)                          # 250u
    sb, yt = world([a], ps), FakeYouTube()
    # 10000 − 300 buffer − 3000 reserve − 6500 used = 200u left: not enough.
    with wired(sb, yt, used=6500):
        assert playlist_test.run_apply() is None
    assert yt.calls == []
    with wired(sb, yt, used=6450):                     # 250u left: fits exactly
        playlist_test.run_apply()
    assert len(yt.calls) == 5


def test_the_budget_counts_what_was_spent_across_channels():
    a1, p1 = dose(1, "PL1", 4)                         # 200u
    a2, p2 = dose(2, "PL2", 4, channel=OTHER)          # 200u: over a 300u budget
    sb, yt = world([a1, a2], p1 + p2), FakeYouTube()
    with wired(sb, yt, PLAYLIST_TEST_DAILY_UNITS=300):
        playlist_test.run_apply()
    assert {s[0] for s in yt.sent()} == {"PL1"}


# ── what a sent add writes ────────────────────────────────────────────────

def test_a_sent_add_is_recorded_as_an_experiment_assignment_and_midas_owns_it():
    a, ps = dose(1, "PL1", 2)
    sb, yt = world([a], ps), FakeYouTube()
    with wired(sb, yt):
        playlist_test.run_apply()
    rows = sorted(sb.rows("playlist_assignments"), key=lambda r: r["video_id"])
    assert [(r["video_id"], r["playlist_id"], r["action"], r["decision_source"])
            for r in rows] == [("PL1-v0", "PL1", "added", "experiment"),
                               ("PL1-v1", "PL1", "added", "experiment")]
    assert [r["playlist_item_id"] for r in rows] == [
        proposals_by_id(sb)[100]["playlist_item_id"], proposals_by_id(sb)[101]["playlist_item_id"]]
    # The membership walk asks the ledger who added these: Midas, from the
    # assignments alone (the approved proposals aside).
    ledger = FakeSupabase({"playlist_assignments": rows, "playlist_proposals": []})
    with patch("app.human_edits.supabase", return_value=ledger):
        assert human_edits.added_by_midas("PL1", ["PL1-v0", "PL1-v1", "other"]) == {
            "PL1-v0", "PL1-v1"}


def test_every_insert_is_charged_to_the_ledger():
    a, ps = dose(1, "PL1", 2)
    sb, yt = world([a], ps), FakeYouTube()
    with wired(sb, yt):
        playlist_test.run_apply()
    assert [(r["operation"], r["units"]) for r in sb.rows("quota_log")] == [
        ("playlistItems.insert", 50)] * 2


# ── arm status, retries, test_dates ───────────────────────────────────────

def test_an_arm_is_dosed_with_its_first_and_last_applied_at():
    a, ps = dose(1, "PL1", 2)
    sb, yt = world([a], ps), FakeYouTube()
    with wired(sb, yt):
        playlist_test.run_apply()
    got, sent = arms_by_id(sb)[1], sorted(p["applied_at"] for p in sb.rows("playlist_proposals"))
    assert got["status"] == "dosed"
    assert (got["first_applied_at"], got["last_applied_at"]) == (sent[0], sent[-1])


def test_an_undecided_proposal_does_not_hold_a_dosed_arm_open():
    a, ps = dose(1, "PL1", 2)
    ps[1]["status"] = "pending"
    sb, yt = world([a], ps), FakeYouTube()
    with wired(sb, yt):
        playlist_test.run_apply()
    got = arms_by_id(sb)[1]
    assert got["status"] == "dosed" and got["first_applied_at"] == got["last_applied_at"]
    assert len(yt.calls) == 1


def test_an_arm_with_nothing_approved_yet_stays_planned_while_proposals_are_pending():
    a, ps = dose(1, "PL1", 2)
    ps[0]["status"], ps[1]["status"] = "pending", "rejected"
    sb, yt = world([a], ps), FakeYouTube()
    with wired(sb, yt):
        playlist_test.run_apply()
    assert yt.calls == [] and arms_by_id(sb)[1]["status"] == "planned"


def test_an_add_failing_while_retryable_keeps_the_arm_applying():
    a, ps = dose(1, "PL1", 2)
    sb, yt = world([a], ps), FakeYouTube(fail={"PL1-v1": [BROKEN]})
    with wired(sb, yt):
        playlist_test.run_apply()
    assert arms_by_id(sb)[1]["status"] == "applying"


def test_a_planned_arm_with_nothing_approved_becomes_no_dose():
    a, ps = dose(1, "PL1", 2)
    for p in ps:
        p["status"] = "rejected"
    sb, yt = world([a], ps), FakeYouTube()
    with wired(sb, yt):
        playlist_test.run_apply()
    assert yt.calls == []
    got = arms_by_id(sb)[1]
    assert got["status"] == "no_dose" and got["first_applied_at"] is None


def test_a_failing_add_is_tried_in_at_most_max_attempts_runs_then_the_arm_settles():
    a, ps = dose(1, "PL1", 2)
    sb = world([a], ps)
    yt = FakeYouTube(fail={"PL1-v1": [BROKEN] * 5})
    for run in range(1, 5):
        with wired(sb, yt):
            try:
                playlist_test.run_apply()
            except JobRunFailed:
                pass
    tries = [s for s in yt.sent() if s[1] == "PL1-v1"]
    assert len(tries) == 3
    p = proposals_by_id(sb)[101]
    assert p["applied_at"] is None and p["apply_error"]["attempts"] == 3
    assert p["apply_error"]["reason"] == "failed" and "videoNotFound" in p["apply_error"]["detail"]
    # The arm is applying while the add can be retried, then dosed.
    assert arms_by_id(sb)[1]["status"] == "dosed"


def test_an_arm_whose_every_add_failed_for_good_is_no_dose():
    a, ps = dose(1, "PL1", 1)
    sb = world([a], ps)
    yt = FakeYouTube(fail={"PL1-v0": [BROKEN] * 3})
    statuses = []
    for _ in range(3):
        with wired(sb, yt, PLAYLIST_TEST_MAX_ATTEMPTS=3), pytest.raises(JobRunFailed):
            playlist_test.run_apply()
        statuses.append(arms_by_id(sb)[1]["status"])
    assert statuses == ["planned", "planned", "no_dose"]


def test_test_dates_wait_until_no_treated_arm_is_open():
    rows = [
        arm(1, "PL1", [], status="dosed", first_applied_at="2026-10-28T11:00:00+00:00",
            last_applied_at="2026-10-28T11:05:00+00:00"),
        # 06:30 UTC on 10-31 is still 10-30 in Pacific (YouTube's data-day).
        arm(2, "PL2", [], status="dosed", first_applied_at="2026-10-29T11:00:00+00:00",
            last_applied_at="2026-10-31T06:30:00+00:00"),
        arm(3, "PL3", [], status="no_dose"),
        arm(4, "PL4", [], which="holdout", status="holdout"),
        arm(5, "PL5", [], channel=OTHER, status="applying"),
    ]
    sb = world(rows, [])
    with wired(sb, FakeYouTube()):
        assert playlist_test.test_dates(CH) == (date(2026, 10, 28), date(2026, 10, 30))
        assert playlist_test.test_dates(OTHER) is None
        assert playlist_test.test_dates("never-drawn") is None
    sb = world([arm(1, "PL1", [], status="applying",
                    first_applied_at="2026-10-28T11:00:00+00:00")], [])
    with wired(sb, FakeYouTube()):
        assert playlist_test.test_dates(CH) is None
    sb = world([arm(1, "PL1", [], status="no_dose")], [])
    with wired(sb, FakeYouTube()):
        assert playlist_test.test_dates(CH) is None


# ── typed reactions ───────────────────────────────────────────────────────

def test_youtube_quota_exceeded_stops_the_job_without_using_up_an_attempt():
    a1, p1 = dose(1, "PL1", 2)
    a2, p2 = dose(2, "PL2", 1)
    a3, p3 = dose(3, "PL3", 1, channel=OTHER)
    sb = world([a1, a2, a3], p1 + p2 + p3)
    yt = FakeYouTube(fail={"PL1-v1": [QUOTA]})
    with wired(sb, yt):
        assert playlist_test.run_apply() == {
            "partial_errors": {CH: "youtube_quota_exceeded: stopped for the day"}}
    assert [s[1] for s in yt.sent()] == ["PL1-v0", "PL1-v1"]
    err = proposals_by_id(sb)[101]["apply_error"]
    assert (err["reason"], err["attempts"]) == ("youtube_quota_exceeded", 0)
    assert arms_by_id(sb)[1]["status"] == "applying"


def test_a_token_error_skips_the_channel_and_fails_the_run_after_the_others():
    a1, p1 = dose(1, "PL1", 2)
    a2, p2 = dose(2, "PL2", 1, channel=OTHER)
    sb = world([a1, a2], p1 + p2)
    yt = FakeYouTube(fail={"PL1-v0": [TOKEN]})
    with wired(sb, yt), pytest.raises(JobRunFailed) as raised:
        playlist_test.run_apply()
    assert list(raised.value.failed_channels) == [CH]
    assert "token_expired" in raised.value.failed_channels[CH]
    # The channel stopped at its first add; the other channel still ran.
    assert [s[1] for s in yt.sent()] == ["PL1-v0", "PL2-v0"]
    err = proposals_by_id(sb)[100]["apply_error"]
    assert (err["reason"], err["attempts"]) == ("token_expired", 0)


# ── the job ──────────────────────────────────────────────────────────────

def test_playlist_test_apply_is_registered_daily_1100_utc():
    sched = BackgroundScheduler(daemon=True)
    main._register_jobs(sched)
    job = sched.get_job("playlist_test_apply")
    assert job is not None and job.func is playlist_test.run_apply
    assert job.max_instances == 1 and job.coalesce is True
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert (fields["day_of_week"], fields["hour"], fields["minute"]) == ("*", "11", "0")
    assert str(job.trigger.timezone) == "UTC"


def test_every_add_failing_fails_the_channel_some_is_degraded():
    a1, p1 = dose(1, "PL1", 2)
    a2, p2 = dose(2, "PL2", 2, channel=OTHER)
    sb = world([a1, a2], p1 + p2)
    yt = FakeYouTube(fail={"PL1-v0": [BROKEN], "PL1-v1": [BROKEN], "PL2-v0": [BROKEN]})
    with wired(sb, yt), pytest.raises(JobRunFailed) as raised:
        playlist_test.run_apply()
    assert raised.value.failed_channels == {CH: "ItemsFailed: playlist adds: all 2 failed"}
    assert proposals_by_id(sb)[201]["applied_at"]          # OTHER's second add landed


def test_a_channel_that_crashes_fails_the_run_once_every_channel_ran():
    a1, p1 = dose(1, "PL1", 1)
    a2, p2 = dose(2, "PL2", 1, channel=OTHER)
    sb, yt = world([a1, a2], p1 + p2), FakeYouTube()
    real = playlist_test.apply_channel

    def flaky(cid, budget):
        if cid == CH:
            raise RuntimeError("boom")
        return real(cid, budget)

    with wired(sb, yt), patch.object(playlist_test, "apply_channel", flaky), \
         pytest.raises(JobRunFailed) as raised:
        playlist_test.run_apply()
    assert raised.value.failed_channels == {CH: job_status.describe(RuntimeError("boom"))}
    assert [s[1] for s in yt.sent()] == ["PL2-v0"]


def test_only_channels_with_open_treated_arms_are_worked():
    a1, p1 = dose(1, "PL1", 1, status="dosed")
    a2, p2 = dose(2, "PL2", 1, which="holdout", status="holdout")
    sb, yt = world([a1, a2], p1 + p2), FakeYouTube()
    with wired(sb, yt):
        assert playlist_test.run_apply() is None
    assert yt.calls == [] and sb.writes == []


def test_the_card_lists_every_pending_proposal_past_the_row_cap_test_ones_first():
    """The card read one capped page, oldest first: with 1,000+ old engine
    proposals pending, the playlist test's (newer) never showed (#93 D3)."""
    from tests.test_backlink_candidates import postgrest_cap
    old = [{**proposal(i, None, "PL1", f"old{i:05d}", status="pending"),
            "decision_source": "embedding", "proposed_at": f"2026-09-01T00:00:{i % 60:02d}+00:00"}
           for i in range(1, 1201)]
    test = [{**proposal(5000 + i, 7, "PL1", f"new{i}", status="pending"),
             "proposed_at": "2026-10-26T04:10:00+00:00"} for i in range(3)]
    done = {**proposal(6000, 7, "PL1", "done"), "proposed_at": "2026-10-26T04:10:00+00:00"}
    sb = _proposals_world(*old, *test, done)
    with patch.object(playlists_router, "supabase", return_value=sb), postgrest_cap():
        listed = playlists_router.list_proposals(CH)
    assert len(listed) == 1203
    assert [p["id"] for p in listed[:3]] == [5000, 5001, 5002]
    assert len({p["id"] for p in listed}) == 1203
