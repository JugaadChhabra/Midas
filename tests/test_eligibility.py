"""Which channels a job runs for — app/eligibility.py.

Six shapes over one table used to answer this, and the audit predicate alone was
written four times (twice in autopilot, once in the dashboard, once in JS). The
predicates below are pure and mock-free; the queries are asserted by shape, in
the style of tests/test_channel_audits.py.
"""
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from app import eligibility as el
from app.eligibility import Job
from tests.fakes import FakeSupabase


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
#
# Asserted as behaviour — which channels come back — rather than as query shape.
# The double interprets the filters and honours the projection, so these tests say
# what eligibility MEANS instead of restating how it is spelled. See tests/fakes.py.

FLEET = [
    {"id": "audit_only", "autopilot_enabled": True, "autopilot_shorts_enabled": False,
     "analytics_authorized": True, "measurement_enabled": True, "reach_warmup": False,
     "playlist_health_enabled": False, "refresh_token": "tok-1"},
    {"id": "paused", "autopilot_enabled": True, "autopilot_paused_reason": "token_expired",
     "autopilot_shorts_enabled": True, "analytics_authorized": True,
     "measurement_enabled": False, "reach_warmup": True,
     "playlist_health_enabled": True, "refresh_token": "tok-2"},
    {"id": "shorts_only", "autopilot_enabled": False, "autopilot_shorts_enabled": True,
     "analytics_authorized": False, "measurement_enabled": False, "reach_warmup": False,
     "playlist_health_enabled": False, "refresh_token": "tok-3"},
    {"id": "idle", "autopilot_enabled": False, "autopilot_shorts_enabled": False,
     "analytics_authorized": True, "measurement_enabled": False, "reach_warmup": False,
     "playlist_health_enabled": False, "refresh_token": "tok-4"},
]


def _run(job, columns="id", fleet=None, **settings_overrides):
    sb = FakeSupabase({"channels": fleet if fleet is not None else FLEET})
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


def _ids(job, **kw):
    got, _ = _run(job, **kw)
    return sorted(c["id"] for c in got)


def test_analytics_excludes_channels_that_never_consented():
    assert _ids(Job.ANALYTICS) == ["audit_only", "idle", "paused"]


def test_playlist_health_runs_only_where_its_flag_is_on():
    assert _ids(Job.PLAYLIST_HEALTH) == ["paused"]


def test_the_audit_job_excludes_a_paused_channel_the_shorts_job_keeps():
    """The pause is path-specific: a channel can be picked purely for shorts."""
    assert _ids(Job.AUDIT) == ["audit_only"]
    assert _ids(Job.SHORTS) == ["paused", "shorts_only"]
    assert _ids(Job.AUTOPILOT) == ["audit_only", "paused", "shorts_only"]


def test_an_idle_channel_is_no_ones_work():
    assert "idle" not in _ids(Job.AUTOPILOT)


def test_reach_needs_consent_and_an_opt_in():
    """analytics_authorized AND (measurement_enabled OR reach_warmup).
    `shorts_only` has an opt-in but no consent; `idle` has consent but no opt-in."""
    assert _ids(Job.REACH, REPORTING_MEASURED_CHANNELS_ONLY=True) == \
        ["audit_only", "paused"]


def test_reach_widens_to_every_consented_channel_when_the_flag_is_off():
    assert _ids(Job.REACH, REPORTING_MEASURED_CHANNELS_ONLY=False) == \
        ["audit_only", "idle", "paused"]


def test_reconcile_honours_the_env_allowlist():
    assert _ids(Job.RECONCILE, PLAYLIST_RECONCILE_ALL=False,
                PLAYLIST_RECONCILE_CHANNELS={"idle", "paused"}) == ["idle", "paused"]


def test_reconcile_wildcard_restores_every_channel():
    assert _ids(Job.RECONCILE, PLAYLIST_RECONCILE_ALL=True,
                PLAYLIST_RECONCILE_CHANNELS=set()) == \
        ["audit_only", "idle", "paused", "shorts_only"]


def test_every_means_every_channel():
    assert _ids(Job.EVERY) == ["audit_only", "idle", "paused", "shorts_only"]


def test_a_narrow_projection_still_filters_correctly():
    """The bug a live parity check caught and the old mock-based tests could not:
    with columns="id" the predicate read flags that were not selected, matched
    nothing, and every autopilot job returned an empty list — the tick would have
    gone silently quiet. The double honours the projection, so this now fails at
    the assertion rather than in production."""
    assert _ids(Job.AUDIT, columns="id") == ["audit_only"]
    assert _ids(Job.SHORTS, columns="id") == ["paused", "shorts_only"]


def test_the_caller_can_ask_for_the_whole_row():
    """autopilot needs the OAuth token; the dashboard deliberately does not."""
    got, _ = _run(Job.AUDIT, columns="*")
    assert got[0]["refresh_token"] == "tok-1"


def test_a_narrow_projection_does_not_leak_the_token():
    got, _ = _run(Job.AUDIT, columns="id")
    assert "refresh_token" not in got[0]


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
