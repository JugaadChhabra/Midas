"""Which channels a job runs for — app/eligibility.py.

Six shapes over one table used to answer this, and the audit predicate alone was
written four times (twice in autopilot, once in the dashboard, once in JS). The
predicates below are pure and mock-free; the queries are asserted by shape, in
the style of tests/test_channel_audits.py.
"""
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import eligibility as el
from app.eligibility import Job


# ── predicates ────────────────────────────────────────────────────────────

def test_audit_path_needs_enabled_and_unpaused():
    assert el.can_audit({"autopilot_enabled": True}) is True
    assert el.can_audit({"autopilot_enabled": True,
                         "autopilot_paused_reason": None}) is True
    assert el.can_audit({"autopilot_enabled": True,
                         "autopilot_paused_reason": "token_expired"}) is False
    assert el.can_audit({"autopilot_enabled": False}) is False
    assert el.can_audit({}) is False


def test_shorts_path_ignores_the_audit_pause():
    """Decoupled deliberately: an audit-side blip must not silence a NAS folder."""
    ch = {"autopilot_shorts_enabled": True, "autopilot_enabled": False,
          "autopilot_paused_reason": "repeated_failures"}
    assert el.can_cut_shorts(ch) is True
    assert el.can_audit(ch) is False
    assert el.has_work(ch) is True


def test_has_work_is_either_path():
    assert el.has_work({"autopilot_enabled": True}) is True
    assert el.has_work({"autopilot_shorts_enabled": True}) is True
    assert el.has_work({"autopilot_enabled": False,
                        "autopilot_shorts_enabled": False}) is False


# ── selection ─────────────────────────────────────────────────────────────

def _sb(rows):
    """A supabase stub whose paged reads return `rows` for any filter chain."""
    sb = MagicMock()
    sel = sb.table.return_value.select.return_value
    for chain in (
        sel,                                  # no filter (EVERY, RECONCILE)
        sel.eq.return_value,                  # one flag
        sel.or_.return_value,                 # autopilot's two flags
        sel.eq.return_value.or_.return_value,  # REACH with the opt-in narrowing
    ):
        chain.order.return_value.range.return_value.execute.return_value.data = rows
    return sb


def _run(job, rows, columns="id", **settings_overrides):
    sb = _sb(rows)
    patches = [patch.object(el, "supabase", return_value=sb)]
    for k, v in settings_overrides.items():
        patches.append(patch.object(el.settings, k, v))
    for p in patches:
        p.start()
    try:
        return el.channels_for(job, columns=columns), sb
    finally:
        for p in reversed(patches):
            p.stop()


def test_analytics_selects_on_the_consent_flag():
    _, sb = _run(Job.ANALYTICS, [{"id": "c1"}])
    sb.table.return_value.select.return_value.eq.assert_called_once_with(
        "analytics_authorized", True)


def test_playlist_health_selects_on_its_own_flag():
    _, sb = _run(Job.PLAYLIST_HEALTH, [{"id": "c1"}])
    sb.table.return_value.select.return_value.eq.assert_called_once_with(
        "playlist_health_enabled", True)


def test_autopilot_asks_sql_for_either_flag_then_filters_in_python():
    """The OR keeps the read small; the pause check has to happen in Python
    because a paused channel is still a valid shorts candidate."""
    rows = [
        {"id": "audit", "autopilot_enabled": True},
        {"id": "paused", "autopilot_enabled": True, "autopilot_paused_reason": "x"},
        {"id": "shorts", "autopilot_shorts_enabled": True},
    ]
    got, sb = _run(Job.AUTOPILOT, rows)
    sb.table.return_value.select.return_value.or_.assert_called_once_with(
        "autopilot_enabled.eq.true,autopilot_shorts_enabled.eq.true")
    assert [c["id"] for c in got] == ["audit", "shorts"]


def test_the_audit_job_excludes_a_paused_channel_the_shorts_job_keeps():
    rows = [{"id": "paused", "autopilot_enabled": True,
             "autopilot_paused_reason": "token_expired",
             "autopilot_shorts_enabled": True}]
    audit, _ = _run(Job.AUDIT, rows)
    shorts, _ = _run(Job.SHORTS, rows)
    assert audit == []
    assert [c["id"] for c in shorts] == ["paused"]


def test_reach_narrows_to_the_measurement_optin_by_default():
    _, sb = _run(Job.REACH, [{"id": "c1"}], REPORTING_MEASURED_CHANNELS_ONLY=True)
    eq = sb.table.return_value.select.return_value.eq
    eq.assert_called_once_with("analytics_authorized", True)
    eq.return_value.or_.assert_called_once_with(
        "measurement_enabled.eq.true,reach_warmup.eq.true")


def test_reach_widens_when_the_flag_is_off():
    _, sb = _run(Job.REACH, [{"id": "c1"}], REPORTING_MEASURED_CHANNELS_ONLY=False)
    sb.table.return_value.select.return_value.eq.return_value.or_.assert_not_called()


def test_reconcile_honours_the_env_allowlist():
    rows = [{"id": "in1"}, {"id": "out"}, {"id": "in2"}]
    got, _ = _run(Job.RECONCILE, rows,
                  PLAYLIST_RECONCILE_ALL=False,
                  PLAYLIST_RECONCILE_CHANNELS={"in1", "in2"})
    assert [c["id"] for c in got] == ["in1", "in2"]


def test_reconcile_wildcard_restores_every_channel():
    rows = [{"id": "a"}, {"id": "b"}]
    got, _ = _run(Job.RECONCILE, rows, PLAYLIST_RECONCILE_ALL=True,
                  PLAYLIST_RECONCILE_CHANNELS=set())
    assert [c["id"] for c in got] == ["a", "b"]


def test_every_applies_no_filter():
    got, sb = _run(Job.EVERY, [{"id": "a"}, {"id": "b"}])
    sel = sb.table.return_value.select.return_value
    sel.eq.assert_not_called()
    sel.or_.assert_not_called()
    assert len(got) == 2


def test_the_caller_chooses_the_projection():
    """autopilot needs the whole row (OAuth tokens); the dashboard deliberately
    does not read them."""
    _, sb = _run(Job.AUTOPILOT, [], columns="*")
    sb.table.return_value.select.assert_called_once_with("*")


@pytest.mark.parametrize("job,needed", [
    (Job.AUDIT, ["autopilot_enabled", "autopilot_paused_reason"]),
    (Job.SHORTS, ["autopilot_shorts_enabled"]),
    (Job.AUTOPILOT, ["autopilot_enabled", "autopilot_paused_reason",
                     "autopilot_shorts_enabled"]),
])
def test_a_narrow_projection_still_includes_what_the_predicate_reads(job, needed):
    """The failure this prevents is silent, and was real: with columns="id" the
    Python predicate read absent keys, matched nothing, and the job went quiet.
    A live parity check caught it; these assertions are why it can't return."""
    _, sb = _run(job, [], columns="id")
    selected = sb.table.return_value.select.call_args[0][0]
    for col in needed:
        assert col in selected, f"{job} filters on {col} but did not select it"


def test_a_wildcard_projection_is_left_alone():
    _, sb = _run(Job.AUDIT, [], columns="*")
    assert sb.table.return_value.select.call_args[0][0] == "*"


def test_the_predicate_columns_are_not_duplicated():
    _, sb = _run(Job.AUDIT, [], columns="id,autopilot_enabled")
    selected = sb.table.return_value.select.call_args[0][0].split(",")
    assert len(selected) == len(set(selected))


def test_an_unknown_job_raises():
    with pytest.raises(ValueError, match="unknown job"):
        el.channels_for("nightly_vibes")


# ── nobody re-solves it ───────────────────────────────────────────────────

APP = Path(__file__).resolve().parents[1] / "app"

#: The audit predicate, spelled out rather than asked for. Matches both the
#: direct form and the de Morgan inverse autopilot used at its second site.
_AUDIT_PREDICATE = re.compile(
    r"""\(?["']autopilot_enabled["']\)?\s*(?:and\s+not|or)\s+"""
    r"""\w+(?:\.get\()?\s*\(?["']autopilot_paused_reason["']""")
#: A module selecting channels by a gating flag instead of naming its job.
_OWN_CHANNEL_QUERY = re.compile(
    r"""table\(["']channels["']\)[\s\S]{0,200}?"""
    r"""\.eq\(\s*["'](?:analytics_authorized|playlist_health_enabled|"""
    r"""measurement_enabled|autopilot_enabled)["']""")


def _app_sources():
    for p in sorted(APP.rglob("*.py")):
        if p.name == "eligibility.py":
            continue
        yield p


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_spells_out_the_audit_predicate(path):
    assert not _AUDIT_PREDICATE.search(path.read_text()), (
        f"{path.name} spells out the audit predicate — call "
        "app.eligibility.can_audit so the page and the tick cannot disagree"
    )


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_selects_channels_by_a_gating_flag(path):
    hits = _OWN_CHANNEL_QUERY.findall(path.read_text())
    assert not hits, (
        f"{path.name} selects channels by a gating flag — ask "
        "app.eligibility.channels_for(Job.X) so eligibility has one owner"
    )
