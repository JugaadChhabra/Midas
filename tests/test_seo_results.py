"""The Results page's read (SEO results 02, #169), through the HTTP seam:
TestClient over the app, with users, sessions, channels, interventions,
lever_verdicts and videos in a FakeSupabase.

``GET /seo/results?channel_id=&lever=`` → ``generated_at``, ``next_judgement``,
``channels[].levers.backlinks`` and ``fleet.levers.backlinks``: what Midas wrote
on each visible channel, how much of it is judged, the treated-vs-holdout means
and lift over the judged ``midas`` rows (Shorts and ``insufficient_data`` kept
out, counted apart), and the weekly verdict rows.
"""
import sys
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import db, main, session
from app.config import settings
from tests.fakes import FakeQuery, FakeSupabase

ADMIN, EXEC, MANAGER_A, MANAGER_B = 1, 2, 3, 4
TOKENS = {ADMIN: "tok-admin", EXEC: "tok-exec", MANAGER_A: "tok-a", MANAGER_B: "tok-b"}
CH_A, CH_A2, CH_B, CH_NONE = "UCa", "UCa2", "UCb", "UCnone"


def _user(uid, role, name):
    return {"id": uid, "email": f"u{uid}@example.com", "name": name, "role": role,
            "is_active": True, "password_hash": "unused"}


def _channel(cid, name, manager_id, language, agent=True):
    return {"id": cid, "name": name, "manager_id": manager_id, "default_language": language,
            "agent_enabled": agent, "autopilot_daily_cap": 10}


_ids = iter(range(1, 10_000_000))


def _iv(channel_id, arm="treated", status="measuring", *, origin="midas", video="v1",
        applied=True, delta=None, judged_at="2026-11-10T09:00:00+00:00", payload=None,
        lever="backlinks"):
    """One intervention row. ``delta`` given → it has a measurement result."""
    result = None
    if delta is not None:
        result = {"delta": delta, "pre": 1, "post": 1 + delta, "judged_at": judged_at}
    return {"id": next(_ids), "channel_id": channel_id, "video_id": video, "lever": lever,
            "origin": origin, "arm": arm, "status": status, "payload": payload or {},
            "applied_at": "2026-11-01T08:00:00+00:00" if applied else None,
            "detected_at": None, "created_at": "2026-11-01T08:00:00+00:00",
            "measurement_status": "done" if delta is not None else "awaiting_window",
            "measurement_result": result}


def _verdict(channel_id, week, *, lift=1.0, cumulative=1.0, windows=1, verdict="helped",
             stop=False, scope="treated_vs_holdout", lever="backlinks"):
    return {"id": next(_ids), "channel_id": channel_id, "lever": lever, "arm_scope": scope,
            "week_start": week, "n_treated": 2, "n_holdout": 1, "treated_mean_delta": lift,
            "holdout_mean_delta": 0.0, "lift": lift, "cumulative_lift": cumulative,
            "windows_judged": windows, "verdict": verdict, "stop_rule_triggered": stop,
            "computed_at": f"{week}T09:00:00+00:00"}


def _store(interventions=(), verdicts=(), videos=None, channels=None):
    return FakeSupabase({
        "app_users": [_user(ADMIN, "admin", "Jugaad"), _user(EXEC, "exec", "Akshay"),
                      _user(MANAGER_A, "manager", "Justin"),
                      _user(MANAGER_B, "manager", "Ishwari")],
        "app_sessions": [{"token_hash": session.hash_token(t), "user_id": uid,
                          "expires_at": "2999-01-01T00:00:00+00:00"}
                         for uid, t in TOKENS.items()],
        "channels": channels if channels is not None else [
            _channel(CH_A, "Marathi", MANAGER_A, "mr"),
            _channel(CH_A2, "Gujarati", MANAGER_A, "gu"),
            _channel(CH_B, "Hindi", MANAGER_B, "hi"),
            _channel(CH_NONE, "Telugu", None, "te", agent=False),
        ],
        "interventions": list(interventions),
        "lever_verdicts": list(verdicts),
        "videos": videos if videos is not None else [
            {"id": "v1", "channel_id": CH_A, "title": "One", "thumbnail_url": None,
             "is_short": False},
            {"id": "short1", "channel_id": CH_A, "title": "A Short", "thumbnail_url": None,
             "is_short": True},
        ],
        "audits": [],
    })


@pytest.fixture
def use():
    """Patch the fake in for every app module that reads ``supabase``, with the
    levers' kill switches on and titles on Marathi."""
    started = []

    def _use(sb):
        patches = [patch.object(mod, "supabase", return_value=sb)
                   for name, mod in list(sys.modules.items())
                   if name.startswith("app") and getattr(mod, "supabase", None) is db.supabase]
        patches.append(patch.multiple(settings, BACKLINK_APPLY_ENABLED=True,
                                      TITLE_APPLY_ENABLED=True, TITLE_CHANNELS={CH_A}))
        for p in patches:
            p.start()
            started.append(p)
        return sb

    yield _use
    for p in reversed(started):
        p.stop()


@pytest.fixture
def capped():
    """PostgREST's 1000-row cap: an unranged read answers its first 1000 rows,
    so a read that doesn't page loses the rest, as it would live."""
    real = FakeQuery.execute

    def execute(self):
        result = real(self)
        if self._write is None and isinstance(result.data, list):
            result.data = result.data[:1000]
        return result

    with patch.object(FakeQuery, "execute", execute):
        yield


def _as(uid):
    return TestClient(main.app, raise_server_exceptions=False,
                      cookies={session.COOKIE: TOKENS[uid]})


def _results(uid=ADMIN, **params):
    r = _as(uid).get("/seo/results", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _cell(body, channel_id, lever="backlinks"):
    return next(c for c in body["channels"] if c["id"] == channel_id)["levers"][lever]


# ── one channel's cell ──────────────────────────────────────────────────────

def test_counts_and_verdict_fields(use):
    rows = [
        _iv(CH_A, "treated", "measuring"),                                   # awaiting
        _iv(CH_A, "treated", "judged", delta=4.0),
        _iv(CH_A, "treated", "judged", delta=2.0),
        _iv(CH_A, "holdout", "judged", applied=False, delta=1.0),
        _iv(CH_A, "holdout", "holdout", applied=False),                      # awaiting
        _iv(CH_A, "n/a", "declined", applied=False),
        _iv(CH_A, "treated", "cancelled", applied=False,
            payload={"error": {"reason": "dry_run"}}),
        _iv(CH_A, "treated", "cancelled", applied=False,
            payload={"error": {"reason": "dry_run"}}),
        _iv(CH_A, "treated", "cancelled", applied=False,
            payload={"error": {"reason": "failed"}}),
        _iv(CH_A, "treated", "cancelled",
            payload={"revert": {"reverted_at": "2026-11-05T10:00:00+00:00"}}),
        _iv(CH_A, "treated", "insufficient_data", delta=0.0),
        _iv(CH_A, "treated", "judged", lever="title", delta=9.0),            # another lever
    ]
    verdicts = [
        _verdict(CH_A, "2026-11-09", lift=0.5, cumulative=1.2, windows=2, verdict="no_change"),
        _verdict(CH_A, "2026-11-02", lift=2.0, cumulative=2.0, windows=1, verdict="helped"),
        _verdict(CH_A, "2026-11-09", scope="human", verdict=None),           # not this scope
        _verdict(CH_A, "2026-11-09", lever="title", scope="pipeline_vs_holdout"),
    ]
    sb = use(_store(rows, verdicts))

    cell = _cell(_results(channel_id=CH_A), CH_A)

    assert cell["counts"] == {
        "written": 5, "holdout": 2, "declined": 1,
        "cancelled": {"dry_run": 2, "failed": 1}, "reverted": {"auto": 0, "manual": 1},
        "judged": 3, "insufficient_data": 1, "awaiting": 2, "shorts_excluded": 0,
        "team": 0, "team_judged": 0,
    }
    assert (cell["n_treated"], cell["n_holdout"]) == (2, 1)
    assert cell["treated_mean_delta"] == pytest.approx(3.0)
    assert cell["holdout_mean_delta"] == pytest.approx(1.0)
    assert cell["lift"] == pytest.approx(2.0)
    # The stored weekly verdict's own numbers: the latest week's.
    assert cell["cumulative_lift"] == pytest.approx(1.2)
    assert cell["windows_judged"] == 2
    assert cell["verdict"] == "no_change"
    assert cell["stop_rule_triggered"] is False
    assert cell["stopped_week"] is None
    assert [w["week_start"] for w in cell["weeks"]] == ["2026-11-02", "2026-11-09"]
    assert [w["lift"] for w in cell["weeks"]] == [2.0, 0.5]
    assert cell["weeks"][0]["verdict"] == "helped"
    assert cell["state"] == {"on": True, "reason": None}
    assert sb.writes == []


def test_a_channel_with_nothing_yet_has_empty_numbers(use):
    use(_store())

    cell = _cell(_results(), CH_B)

    assert cell["counts"]["written"] == 0
    assert cell["treated_mean_delta"] is None and cell["lift"] is None
    assert cell["verdict"] is None and cell["windows_judged"] == 0
    assert cell["weeks"] == []


def test_insufficient_data_shorts_and_team_rows_stay_out_of_the_means(use):
    rows = [
        _iv(CH_A, "treated", "judged", delta=3.0),
        _iv(CH_A, "holdout", "judged", applied=False, delta=1.0),
        _iv(CH_A, "treated", "judged", video="short1", delta=100.0),         # a Short
        _iv(CH_A, "holdout", "judged", video="short1", applied=False, delta=-50.0),
        _iv(CH_A, "treated", "insufficient_data", delta=40.0),
        _iv(CH_A, "n/a", "applied", origin="human", delta=77.0, applied=False),
        _iv(CH_A, "n/a", "judged", origin="human", delta=77.0, applied=False),
    ]
    use(_store(rows))

    cell = _cell(_results(), CH_A)

    assert cell["treated_mean_delta"] == pytest.approx(3.0)
    assert cell["holdout_mean_delta"] == pytest.approx(1.0)
    assert cell["lift"] == pytest.approx(2.0)
    assert (cell["n_treated"], cell["n_holdout"]) == (1, 1)
    counts = cell["counts"]
    assert counts["judged"] == 2
    assert counts["shorts_excluded"] == 2          # judged + shorts_excluded = the DB's judged
    assert counts["insufficient_data"] == 1
    assert (counts["team"], counts["team_judged"]) == (2, 1)
    assert counts["written"] == 3                  # team rows aren't Midas's writes


# ── the fleet row ───────────────────────────────────────────────────────────

def test_the_fleet_lift_is_pooled_not_an_average_of_channel_lifts(use):
    rows = ([_iv(CH_A, "treated", "judged", delta=9.0) for _ in range(3)]
            + [_iv(CH_A, "holdout", "judged", applied=False, delta=0.0)]
            + [_iv(CH_A2, "treated", "judged", delta=0.0)]
            + [_iv(CH_A2, "holdout", "judged", applied=False, delta=3.0) for _ in range(3)])
    use(_store(rows))

    body = _results()

    assert _cell(body, CH_A)["lift"] == pytest.approx(9.0)
    assert _cell(body, CH_A2)["lift"] == pytest.approx(-3.0)   # averaged: 3.0
    fleet = body["fleet"]["levers"]["backlinks"]
    assert fleet["treated_mean_delta"] == pytest.approx(27 / 4)
    assert fleet["holdout_mean_delta"] == pytest.approx(9 / 4)
    assert fleet["lift"] == pytest.approx(4.5)
    assert fleet["cumulative_lift"] == pytest.approx(4.5)
    assert (fleet["n_treated"], fleet["n_holdout"]) == (4, 4)
    assert fleet["counts"]["written"] == 4
    assert fleet["counts"]["judged"] == 8
    # One pooled week (every row judged in the week of 11-09).
    assert [(w["week_start"], w["n_treated"], w["n_holdout"]) for w in fleet["weeks"]] == \
        [("2026-11-09", 4, 4)]
    assert fleet["weeks"][0]["lift"] == pytest.approx(4.5)
    assert fleet["windows_judged"] == 1


def test_the_fleet_sums_counts_over_the_visible_channels(use):
    rows = [_iv(CH_A, "treated", "cancelled", applied=False,
                payload={"error": {"reason": "dry_run"}}),
            _iv(CH_A2, "treated", "cancelled", applied=False,
                payload={"error": {"reason": "dry_run"}}),
            _iv(CH_A2, "treated", "cancelled", applied=False,
                payload={"error": {"reason": "token_expired"}}),
            _iv(CH_B, "treated", "measuring")]
    use(_store(rows))

    fleet = _results()["fleet"]["levers"]["backlinks"]

    assert fleet["counts"]["cancelled"] == {"dry_run": 2, "token_expired": 1}
    assert fleet["counts"]["written"] == 1
    assert fleet["counts"]["awaiting"] == 1
    assert fleet["state"]["channels_on"] == 3      # Telugu: Midas isn't on there
    assert fleet["state"]["channels"] == 4
    assert fleet["state"]["on"] is True


# ── stop rule and lever state ──────────────────────────────────────────────

def test_a_fired_stop_rule(use):
    verdicts = [
        _verdict(CH_A, "2026-11-02", cumulative=0.5, windows=1, verdict="no_change"),
        _verdict(CH_A, "2026-11-09", cumulative=0.2, windows=2, verdict="no_change"),
        _verdict(CH_A, "2026-11-16", cumulative=0.1, windows=3, verdict="no_change", stop=True),
        _verdict(CH_A, "2026-11-23", cumulative=1.5, windows=4, verdict="helped", stop=True),
    ]
    use(_store(verdicts=verdicts))

    body = _results()
    cell = _cell(body, CH_A)

    assert cell["stop_rule_triggered"] is True
    assert cell["stopped_week"] == "2026-11-16"
    assert cell["state"] == {"on": False, "reason": "stopped: it didn't help on this channel"}
    assert [w["stop_rule_triggered"] for w in cell["weeks"]] == [False, False, True, True]
    assert _cell(body, CH_A2)["stop_rule_triggered"] is False
    assert body["fleet"]["levers"]["backlinks"]["stopped_channels"] == 1


@pytest.mark.parametrize("case", ["on", "agent_off", "no_heading", "stopped", "switched_off"])
def test_lever_state_matches_the_channel_page(use, case):
    channels = [_channel(CH_A, "Marathi", MANAGER_A, "mr")]
    verdicts = []
    if case == "agent_off":
        channels[0]["agent_enabled"] = False
    if case == "no_heading":
        channels[0]["default_language"] = "xx"
    if case == "stopped":
        verdicts = [_verdict(CH_A, "2026-11-16", windows=3, stop=True)]
    use(_store(verdicts=verdicts, channels=channels))

    with patch.multiple(settings, BACKLINK_APPLY_ENABLED=case != "switched_off"):
        page = _as(ADMIN).get(f"/channels/{CH_A}/seo").json()["levers"]["backlinks"]
        cell = _cell(_results(), CH_A)

    assert cell["state"] == page
    assert cell["state"]["on"] is (case == "on")


# ── scope ──────────────────────────────────────────────────────────────────

def _spread():
    return [_iv(CH_A, "treated", "measuring"), _iv(CH_A2, "treated", "measuring"),
            _iv(CH_B, "treated", "measuring"), _iv(CH_B, "treated", "measuring")]


def test_a_manager_sees_only_their_channels(use):
    use(_store(_spread()))

    body = _results(MANAGER_A)

    assert [c["id"] for c in body["channels"]] == [CH_A2, CH_A]   # by name
    assert [c["name"] for c in body["channels"]] == ["Gujarati", "Marathi"]
    assert body["fleet"]["levers"]["backlinks"]["counts"]["written"] == 2


def test_another_teams_or_an_unknown_channel_is_404(use):
    use(_store(_spread()))

    for uid, cid in ((MANAGER_A, CH_B), (MANAGER_A, CH_NONE), (MANAGER_A, "UCnope"),
                     (ADMIN, "UCnope"), (EXEC, "UCnope")):
        r = _as(uid).get("/seo/results", params={"channel_id": cid})
        assert r.status_code == 404, (uid, cid)
        assert r.json() == {"detail": "channel_not_found"}


def test_a_named_channel_narrows_channels_and_fleet(use):
    use(_store(_spread()))

    body = _results(MANAGER_B, channel_id=CH_B)

    assert [c["id"] for c in body["channels"]] == [CH_B]
    assert body["fleet"]["levers"]["backlinks"]["counts"]["written"] == 2


def test_exec_and_admin_see_every_channel(use):
    use(_store(_spread()))

    for uid in (EXEC, ADMIN):
        body = _results(uid)
        assert [c["id"] for c in body["channels"]] == [CH_A2, CH_B, CH_A, CH_NONE]
        assert body["fleet"]["levers"]["backlinks"]["counts"]["written"] == 4


def test_a_manager_with_no_channels_gets_an_empty_board(use):
    use(_store(_spread(), channels=[_channel(CH_B, "Hindi", MANAGER_B, "hi")]))

    body = _results(MANAGER_A)

    assert body["channels"] == []
    assert body["fleet"]["levers"]["backlinks"]["counts"]["written"] == 0


# ── paging, lever filter, read-only ────────────────────────────────────────

def test_more_than_1000_interventions_are_counted_in_full(use, capped):
    rows = ([_iv(CH_A, "treated", "judged", delta=2.0) for _ in range(1200)]
            + [_iv(CH_A, "holdout", "judged", applied=False, delta=1.0) for _ in range(1100)])
    videos = [{"id": "v1", "channel_id": CH_A, "title": "One", "thumbnail_url": None,
               "is_short": False}]
    verdicts = [_verdict(CH_A, (date(2000, 1, 3) + timedelta(weeks=i)).isoformat(), windows=i + 1)
                for i in range(1100)]
    use(_store(rows, verdicts, videos=videos))

    cell = _cell(_results(), CH_A)

    assert cell["counts"]["written"] == 1200
    assert cell["counts"]["judged"] == 2300
    assert (cell["n_treated"], cell["n_holdout"]) == (1200, 1100)
    assert len(cell["weeks"]) == 1100


def test_lever_filter(use):
    use(_store([_iv(CH_A, "treated", "measuring")]))

    assert set(_cell(_results(lever="backlinks"), CH_A)) >= {"state", "counts", "lift"}
    r = _as(ADMIN).get("/seo/results", params={"lever": "nonsense"})
    assert r.status_code == 400
    assert r.json() == {"detail": "unknown lever: nonsense"}


def test_nothing_is_written(use):
    rows = [_iv(CH_A, "treated", "judged", delta=1.0),
            _iv(CH_A, "holdout", "judged", applied=False, delta=0.0)]
    sb = use(_store(rows, [_verdict(CH_A, "2026-11-16", stop=True)]))

    for uid in (ADMIN, EXEC, MANAGER_A, MANAGER_B):
        _results(uid)
    _results(MANAGER_A, channel_id=CH_A)

    assert sb.writes == []


def test_next_judgement_is_the_next_monday_0900_utc(use):
    use(_store())

    body = _results()

    generated = datetime.fromisoformat(body["generated_at"])
    nxt = datetime.fromisoformat(body["next_judgement"])
    assert nxt.weekday() == 0 and (nxt.hour, nxt.minute, nxt.second) == (9, 0, 0)
    assert nxt.utcoffset() == timedelta(0)
    assert generated < nxt <= generated + timedelta(days=7)


# ── the page ───────────────────────────────────────────────────────────────

def test_the_page_is_served_to_a_signed_in_user(use):
    use(_store())

    r = _as(MANAGER_A).get("/results")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "/seo/results" in r.text


def test_the_rail_lists_results_after_roster(use):
    use(_store())

    js = _as(ADMIN).get("/static/sidebar.js").text

    roster, results = js.index("href: '/team'"), js.index("href: '/results'")
    assert roster < results


# ── titles (SEO results 03, #170) ──────────────────────────────────────────

def _title(channel_id, path, arm="treated", status="judged", delta=None, *, applied=True,
           pre=200, payload=None, created="2026-11-01T08:00:00+00:00",
           judged_at="2026-11-10T09:00:00+00:00"):
    """A `midas` title row. ``delta`` given → it carries a measurement result."""
    body = dict(payload or {})
    if path:
        body.setdefault("path", path)
    row = _iv(channel_id, arm, status, applied=applied, payload=body, lever="title")
    row["created_at"] = created
    row["measurement_result"] = (None if delta is None else
                                 {"delta": delta, "pre": pre, "post": 5, "judged_at": judged_at})
    return row


def _title_rows(channel_id):
    """The title-test endpoint's own mix of rows: both paths, declines, cancels
    by reason, an auto-reverted and a manually reverted title."""
    return [
        _title(channel_id, "pipeline", delta=0.2),
        _title(channel_id, "pipeline", "treated", "insufficient_data", 0.4, pre=10),
        _title(channel_id, "pipeline", "treated", "cancelled", applied=False,
               payload={"error": {"reason": "checks_failed"}}),
        _title(channel_id, "pipeline", "treated", "cancelled", delta=-0.6,
               payload={"revert": {"auto": True}}),
        _title(channel_id, "pipeline", "treated", "cancelled", applied=True,
               payload={"revert": {"auto": False}}),
        _title(channel_id, "agent", delta=0.1),
        _title(channel_id, "agent", "treated", "judged", -0.1, applied=False),      # a decline
        _title(channel_id, "agent", "treated", "cancelled", applied=False,
               payload={"error": {"reason": "turn_cap"}}),
        _title(channel_id, "agent", "treated", "declined", applied=False),
        _title(channel_id, None, "holdout", "judged", 0.0, applied=False),
        _title(channel_id, None, "holdout", "judged", 0.1, applied=False),
        _title(channel_id, None, "holdout", "holdout", applied=False),
    ]


def test_title_paths_against_the_shared_holdout_equal_the_title_test(use):
    stop = _verdict(CH_A, "2026-11-16", scope="agent_vs_holdout", lever="title", windows=2,
                    stop=True, verdict="worse", cumulative=-0.2)
    use(_store(_title_rows(CH_A), [stop]))

    cell = _cell(_results(), CH_A, "title")
    oracle = _as(ADMIN).get(f"/channels/{CH_A}/title-test").json()

    for path in ("pipeline", "agent"):
        assert {k: cell["paths"][path][k] for k in oracle["paths"][path]} == oracle["paths"][path]
    p, a = cell["paths"]["pipeline"], cell["paths"]["agent"]
    # Declines sit in the agent's mean: (0.1 + -0.1) / 2, against the holdout's 0.05.
    assert a["treated_mean_delta"] == pytest.approx(0.0)
    assert a["holdout_mean_delta"] == pytest.approx(0.05)
    assert a["lift"] == pytest.approx(-0.05)
    assert (a["n_treated"], a["n_holdout"]) == (2, 2)
    # The reverted titles stay in the pipeline's mean, as decided: (0.2 - 0.6) / 2.
    assert p["treated_mean_delta"] == pytest.approx(-0.2)
    assert p["lift"] == pytest.approx(-0.25)
    assert (p["n_treated"], p["n_holdout"]) == (2, 2)
    assert (p["stopped"], a["stopped"]) == (False, True)
    assert (a["stop_rule_triggered"], a["stopped_week"]) == (True, "2026-11-16")
    assert (p["stop_rule_triggered"], p["stopped_week"]) == (False, None)
    assert [w["week_start"] for w in a["weeks"]] == ["2026-11-16"]
    assert p["weeks"] == [] and p["verdict"] is None
    # The cell's own means pool both paths against the holdout.
    assert (cell["n_treated"], cell["n_holdout"]) == (4, 2)
    assert cell["treated_mean_delta"] == pytest.approx(-0.1)
    assert cell["holdout_mean_delta"] == pytest.approx(0.05)
    assert cell["lift"] == pytest.approx(-0.15)
    assert cell["stop_rule_triggered"] is True and cell["stopped_week"] == "2026-11-16"


def test_title_counts_split_cancelled_by_reason_and_reverts_auto_from_manual(use):
    use(_store(_title_rows(CH_A)))

    counts = _cell(_results(), CH_A, "title")["counts"]

    assert counts == {
        "written": 5,                       # treated rows that reached YouTube
        "holdout": 3, "declined": 2,        # the agent's two (one judged, one not)
        "cancelled": {"checks_failed": 1, "turn_cap": 1},
        "reverted": {"auto": 1, "manual": 1},
        "judged": 6,                        # in a mean: the reverted-after-judged one too
        "insufficient_data": 1, "awaiting": 1, "shorts_excluded": 0,
        "team": 0, "team_judged": 0,
    }


def test_the_cell_shows_the_lead_paths_verdict_and_weeks(use):
    rows = [_title(CH_A, "pipeline", delta=0.3), _title(CH_A, "pipeline", delta=0.3),
            _title(CH_A, "agent", delta=0.0), _title(CH_A, None, "holdout", "judged", 0.0,
                                                     applied=False)]
    verdicts = [
        _verdict(CH_A, "2026-11-09", scope="pipeline_vs_holdout", lever="title", lift=0.1,
                 cumulative=0.1, windows=1, verdict="helped"),
        _verdict(CH_A, "2026-11-16", scope="pipeline_vs_holdout", lever="title", lift=0.3,
                 cumulative=0.2, windows=2, verdict="helped"),
        _verdict(CH_A, "2026-11-16", scope="agent_vs_holdout", lever="title", lift=0.0,
                 cumulative=0.0, windows=1, verdict="no_change"),
        _verdict(CH_A, "2026-11-16", lever="backlinks"),             # another lever
    ]
    use(_store(rows, verdicts))

    cell = _cell(_results(), CH_A, "title")

    assert (cell["verdict"], cell["windows_judged"]) == ("helped", 2)
    assert cell["cumulative_lift"] == pytest.approx(0.2)
    assert [w["week_start"] for w in cell["weeks"]] == ["2026-11-09", "2026-11-16"]
    assert cell["paths"]["agent"]["verdict"] == "no_change"
    assert cell["paths"]["agent"]["windows_judged"] == 1


def test_a_title_lever_stopped_on_both_paths_reads_stopped(use):
    verdicts = [_verdict(CH_A, "2026-11-16", scope=s, lever="title", windows=4, stop=True)
                for s in ("pipeline_vs_holdout", "agent_vs_holdout")]
    use(_store(verdicts=verdicts))

    with patch.multiple(settings, TITLE_AGENT_PCT=0.5):
        page = _as(ADMIN).get(f"/channels/{CH_A}/seo").json()["levers"]["title"]
        cell = _cell(_results(), CH_A, "title")

    assert cell["state"] == page == {"on": False,
                                     "reason": "stopped: it didn't help on this channel"}
    assert cell["paths"]["pipeline"]["stopped"] and cell["paths"]["agent"]["stopped"]


def test_the_fleet_pools_titles_over_every_visible_channel(use):
    rows = ([_title(CH_A, "pipeline", delta=9.0) for _ in range(3)]
            + [_title(CH_A, None, "holdout", "judged", 0.0, applied=False)]
            + [_title(CH_A2, "pipeline", delta=0.0)]
            + [_title(CH_A2, None, "holdout", "judged", 3.0, applied=False) for _ in range(3)]
            + [_title(CH_A2, "agent", delta=1.0), _title(CH_A2, "agent", "treated", "cancelled",
                                                         applied=False,
                                                         payload={"error": {"reason": "turn_cap"}})])
    use(_store(rows, [_verdict(CH_A, "2026-11-16", scope="pipeline_vs_holdout", lever="title",
                               windows=4, stop=True)]))

    fleet = _results()["fleet"]["levers"]["title"]

    assert fleet["treated_mean_delta"] == pytest.approx(28 / 5)
    assert fleet["holdout_mean_delta"] == pytest.approx(9 / 4)
    assert fleet["lift"] == pytest.approx(28 / 5 - 9 / 4)      # not (9 + -3 + ...) / channels
    assert (fleet["n_treated"], fleet["n_holdout"]) == (5, 4)
    assert fleet["counts"]["written"] == 5 and fleet["counts"]["judged"] == 9
    assert fleet["counts"]["cancelled"] == {"turn_cap": 1}
    pipe, agent = fleet["paths"]["pipeline"], fleet["paths"]["agent"]
    assert pipe["mean_delta"] == pytest.approx(27 / 4)
    assert pipe["cumulative_lift"] == pytest.approx(27 / 4 - 9 / 4)
    assert pipe["n_treated"] == 4 and pipe["n_holdout"] == 4
    assert agent["mean_delta"] == pytest.approx(1.0)
    assert (pipe["stopped_channels"], agent["stopped_channels"]) == (1, 0)
    assert fleet["stopped_channels"] == 1
    assert fleet["verdict"] is None and fleet["stop_rule_triggered"] is None


def test_first_title_verdicts_is_the_earliest_a_pending_row_can_be_judged(use):
    # d0 = the Pacific date of applied_at: 11-16, then 11-20. Post ends d0 + 14;
    # the traffic report lags 2 days more.
    rows = [_title(CH_A, "pipeline", "treated", "measuring", applied=True),
            _title(CH_A2, "pipeline", "treated", "measuring", applied=True),
            _title(CH_A, "pipeline", delta=0.1)]                      # judged: not pending
    rows[0]["applied_at"] = "2026-11-20T15:00:00+00:00"
    rows[1]["applied_at"] = "2026-11-16T15:00:00+00:00"
    use(_store(rows))

    body = _results()

    assert body["first_title_verdicts"] == "2026-12-02"
    assert _cell(body, CH_A, "title")["first_verdict"] == "2026-12-06"
    assert _cell(body, CH_A2, "title")["first_verdict"] == "2026-12-02"
    assert _cell(body, CH_B, "title")["first_verdict"] is None


def test_first_title_verdicts_counts_a_holdout_by_its_created_day(use):
    row = _title(CH_A, None, "holdout", "holdout", applied=False, created="2026-11-18T20:00:00+00:00")
    use(_store([row]))

    assert _results()["first_title_verdicts"] == "2026-12-04"


def test_no_pending_title_rows_means_no_first_verdict_date(use):
    use(_store([_title(CH_A, "pipeline", delta=0.1)]))

    assert _results()["first_title_verdicts"] is None


def test_title_results_are_scoped_to_the_users_channels(use):
    rows = [_title(CH_A, "pipeline", delta=1.0), _title(CH_B, "pipeline", delta=5.0),
            _title(CH_B, "pipeline", "treated", "measuring", applied=True)]
    rows[2]["applied_at"] = "2026-11-10T15:00:00+00:00"
    sb = use(_store(rows))

    mine = _results(MANAGER_A)
    theirs = _results(MANAGER_B)

    assert [c["id"] for c in mine["channels"]] == [CH_A2, CH_A]   # by name
    assert mine["fleet"]["levers"]["title"]["counts"]["written"] == 1
    assert mine["fleet"]["levers"]["title"]["paths"]["pipeline"]["mean_delta"] == pytest.approx(1.0)
    assert mine["first_title_verdicts"] is None             # B's pending row isn't A's
    assert theirs["first_title_verdicts"] == "2026-11-26"
    assert theirs["fleet"]["levers"]["title"]["counts"]["written"] == 2
    assert _results(EXEC)["fleet"]["levers"]["title"]["counts"]["written"] == 3
    assert _as(MANAGER_A).get("/seo/results", params={"channel_id": CH_B}).status_code == 404
    assert sb.writes == []


def test_the_lever_filter_keeps_only_titles(use):
    use(_store([_title(CH_A, "pipeline", "treated", "measuring")]))

    body = _results(lever="title")

    assert set(_cell(body, CH_A, "title")) >= {"paths", "counts", "first_verdict"}
    assert "backlinks" not in body["fleet"]["levers"]
    assert "title" not in _results(lever="backlinks")["fleet"]["levers"]
    assert _results(lever="backlinks")["first_title_verdicts"] is None


def test_more_than_1000_title_rows_are_counted_in_full(use, capped):
    use(_store([_title(CH_A, "pipeline", delta=0.1) for _ in range(1100)]))

    cell = _cell(_results(), CH_A, "title")

    assert cell["counts"]["written"] == 1100
    assert cell["paths"]["pipeline"]["judged"] == 1100
