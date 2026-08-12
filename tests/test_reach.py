"""Reach data-day arithmetic and coverage — app/reach.py.

Two of these functions had ZERO tests before the module existed: `certify` and
the contiguous-run count behind it were reachable only through a scheduled job
that does network I/O, so the Phase 0 exit gate — the thing that decides whether
a channel may be measured at all — was never exercised. Everything below except
the last test runs with no mocks.
"""
import re
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import reach

APPLIED = date(2026, 6, 1)


@pytest.fixture(autouse=True)
def _fixed_window():
    """Pin the window length so these tests describe behaviour, not config."""
    with patch.object(reach.settings, "MEASUREMENT_WINDOW_DAYS", 21):
        yield


# ── windows ───────────────────────────────────────────────────────────────

def test_windows_exclude_the_apply_day_and_its_neighbours():
    """Reach data-days roll over on Pacific while `applied` is a UTC date, so
    the adjacent days can contain mixed pre/post exposure."""
    pre, post = reach.window_for(APPLIED)
    assert pre == ("2026-05-10", "2026-05-30")
    assert post == ("2026-06-03", "2026-06-23")
    for w in (pre, post):
        assert APPLIED.isoformat() not in reach.days(w)
        assert "2026-05-31" not in reach.days(w)   # apply day - 1
        assert "2026-06-02" not in reach.days(w)   # apply day + 1


def test_both_windows_are_full_length():
    """Shifted outward, not shortened — otherwise pre and post aren't comparable."""
    pre, post = reach.window_for(APPLIED)
    assert len(reach.days(pre)) == 21
    assert len(reach.days(post)) == 21


def test_the_excluded_band_follows_the_slop_constant():
    """The 2s in the boundaries are slop+1, not a hardcoded lag."""
    with patch.object(reach, "ROLLOVER_SLOP_DAYS", 2):
        pre, post = reach.window_for(APPLIED)
        assert pre[1] == "2026-05-29"          # apply day - 3
        assert post[0] == "2026-06-04"         # apply day + 3
        assert len(reach.days(pre)) == 21      # still full length


def test_days_is_inclusive():
    assert reach.days(("2026-01-01", "2026-01-03")) == \
        ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert reach.days(("2026-01-01", "2026-01-01")) == ["2026-01-01"]


# ── coverage predicate ────────────────────────────────────────────────────

def test_missing_days_is_empty_when_every_day_is_covered():
    pre, post = reach.window_for(APPLIED)
    covered = set(reach.days(pre)) | set(reach.days(post))
    assert reach.missing_days(covered, pre, post) == []


def test_missing_days_names_the_gap():
    pre, post = reach.window_for(APPLIED)
    covered = (set(reach.days(pre)) | set(reach.days(post))) - {post[1]}
    assert reach.missing_days(covered, pre, post) == [post[1]]


def test_missing_days_spans_every_window_it_is_given():
    """One call answers for the whole comparison, not one window at a time."""
    pre, post = reach.window_for(APPLIED)
    assert reach.missing_days(set(), pre, post) == reach.days(pre) + reach.days(post)


def test_missing_days_of_no_windows_is_empty():
    assert reach.missing_days({"2026-01-01"}) == []


# ── contiguity and frontier ───────────────────────────────────────────────

def test_contiguous_run_of_nothing_is_zero():
    assert reach.contiguous_run(set()) == 0


def test_contiguous_run_finds_the_longest_not_the_first():
    covered = {
        "2026-01-01", "2026-01-02",                                  # run of 2
        "2026-01-10", "2026-01-11", "2026-01-12", "2026-01-13",      # run of 4
    }
    assert reach.contiguous_run(covered) == 4


def test_contiguous_run_counts_a_lone_day():
    assert reach.contiguous_run({"2026-01-01"}) == 1


def test_contiguous_run_spans_a_month_boundary():
    assert reach.contiguous_run({"2026-01-30", "2026-01-31", "2026-02-01"}) == 3


def test_frontier_is_the_latest_covered_day():
    assert reach.frontier({"2026-01-01", "2026-03-01", "2026-02-01"}) == "2026-03-01"
    assert reach.frontier(set()) is None


# ── certification ─────────────────────────────────────────────────────────

def _run_of(n: int, start=date(2026, 6, 1)) -> set[str]:
    from datetime import timedelta
    return {(start + timedelta(days=i)).isoformat() for i in range(n)}


def test_certify_needs_a_full_contiguous_week():
    with patch.object(reach, "coverage", return_value=_run_of(7)):
        assert reach.certify("c1")["certified"] is True
    with patch.object(reach, "coverage", return_value=_run_of(6)):
        assert reach.certify("c1")["certified"] is False


def test_certify_is_not_satisfied_by_a_week_of_scattered_days():
    """Contiguity is the point — seven days spread over a month is not a week
    of trustworthy CTR."""
    scattered = {f"2026-06-{d:02d}" for d in (1, 4, 8, 12, 16, 20, 24)}
    with patch.object(reach, "coverage", return_value=scattered):
        cov = reach.certify("c1")
    assert cov["certified"] is False
    assert cov["contiguous_days"] == 1
    assert cov["covered_total"] == 7


def test_certify_reports_what_it_measured():
    with patch.object(reach, "coverage", return_value=_run_of(9)):
        cov = reach.certify("c1")
    assert cov == {
        "certified": True,
        "contiguous_days": 9,
        "covered_total": 9,
        "latest_day": "2026-06-09",
        "min_days": 7,
    }


def test_certify_of_an_unpolled_channel_is_not_an_error():
    with patch.object(reach, "coverage", return_value=set()):
        cov = reach.certify("c1")
    assert cov["certified"] is False
    assert cov["latest_day"] is None


# ── the one I/O function ──────────────────────────────────────────────────

def test_coverage_reads_the_ledger_scoped_to_the_channel():
    """Shape, not rows. The ledger has no `id` column, so paging must be
    ordered by report_id or all_rows' total order is undefined."""
    sb = MagicMock()
    eq = sb.table.return_value.select.return_value.eq.return_value
    with patch.object(reach, "supabase", return_value=sb), \
         patch.object(reach, "all_rows", return_value=[
             {"data_date": "2026-06-01"}, {"data_date": "2026-06-02"},
         ]) as all_rows:
        assert reach.coverage("c1") == {"2026-06-01", "2026-06-02"}

    sb.table.assert_called_once_with("reporting_reports_ingested")
    sb.table.return_value.select.assert_called_once_with("data_date")
    sb.table.return_value.select.return_value.eq.assert_called_once_with("channel_id", "c1")
    assert all_rows.call_args[0][0] is eq
    assert all_rows.call_args[1]["order_by"] == "report_id"


# ── nobody re-solves it ───────────────────────────────────────────────────
#
# Same discipline as tests/test_rows.py: the point of the module is that these
# facts have ONE owner, and a source scan is what keeps a second copy from
# appearing. Both patterns below existed in two places before this module.

APP = Path(__file__).resolve().parents[1] / "app"

_WINDOW_LENGTH = re.compile(r"settings\.MEASUREMENT_WINDOW_DAYS")
_MISSING_DAYS = re.compile(r"for\s+\w+\s+in\s+[\w.\[\]()]+\s+if\s+\w+\s+not\s+in\s+cover")


def _app_sources():
    for p in sorted(APP.rglob("*.py")):
        if p.name == "reach.py":
            continue
        yield p


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_declares_its_own_reach_window_length(path):
    """A second reader of MEASUREMENT_WINDOW_DAYS is how the gate and the judge
    came to disagree about how many data-days a comparison needs."""
    assert not _WINDOW_LENGTH.search(path.read_text()), (
        f"{path.name} reads settings.MEASUREMENT_WINDOW_DAYS directly — build "
        "the window with app.reach.window_for so its length has one owner"
    )


@pytest.mark.parametrize("path", list(_app_sources()), ids=lambda p: p.name)
def test_no_module_hand_rolls_the_coverage_diff(path):
    assert not _MISSING_DAYS.search(path.read_text()), (
        f"{path.name} hand-rolls the covered-day diff — use "
        "app.reach.missing_days so the predicate has one owner"
    )
