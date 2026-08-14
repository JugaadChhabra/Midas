"""The live dashboard_summary() must not coalesce a missing view baseline to zero.

delta_views_7d is computed twice — once in Python (_aggregate_legacy) and once in
SQL (dashboard_summary(), used by _aggregate_rpc). _compute_dashboard tries the RPC
FIRST and only falls back to Python, so the SQL is the number users actually see.

When apply-time stats collection was removed, the Python side was taught to skip
audits with a NULL baseline. The SQL still read
`sum(cur_views - coalesce(view_count_at_apply, 0))`, which for a NULL baseline is
the video's whole lifetime view count booked as growth the audit produced. Fixing
only the Python left the live figure wrong and the fallback right — the worst
arrangement, because the fallback is what tests exercise.

tests/test_dashboard_parity_live.py compares the two paths and would catch this,
but only against a populated database. This is the offline guard: it reads whichever
migration most recently defines the function and asserts the NULL handling, so
someone redefining dashboard_summary() by copying an older migration cannot
silently reintroduce it.
"""
from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"


def _latest_definition() -> tuple[str, str]:
    """(filename, sql) of the newest migration defining dashboard_summary()."""
    defining = sorted(
        p for p in MIGRATIONS.glob("*.sql")
        if "create or replace function dashboard_summary" in p.read_text()
    )
    assert defining, "no migration defines dashboard_summary()"
    latest = defining[-1]          # timestamp-prefixed, so lexical == chronological
    return latest.name, latest.read_text()


def test_the_delta_excludes_null_baselines_instead_of_zeroing_them():
    name, sql = _latest_definition()
    delta = re.search(r"as delta_views_7d", sql)
    assert delta, f"{name} defines the function but not delta_views_7d"

    # The ~600 chars before the alias hold the aggregate expression and its filter.
    expr = sql[max(0, delta.start() - 600):delta.end()]
    assert "coalesce(view_count_at_apply, 0)" not in expr, (
        f"{name} coalesces a missing apply-time baseline to 0, so an unmeasured "
        f"audit contributes its video's entire lifetime view count to "
        f"delta_views_7d. Exclude those rows with a `view_count_at_apply is not "
        f"null` filter instead."
    )
    assert "view_count_at_apply is not null" in expr, (
        f"{name} does not filter NULL baselines out of delta_views_7d; it must, "
        f"since apply-time stats are no longer collected."
    )


def test_a_genuine_zero_baseline_is_still_counted():
    """The filter has to be a NULL check, not a truthiness or `> 0` check — a video
    with no views when it was applied has a real baseline and a real delta."""
    name, sql = _latest_definition()
    delta = re.search(r"as delta_views_7d", sql)
    expr = sql[max(0, delta.start() - 600):delta.end()]
    assert "view_count_at_apply > 0" not in expr, (
        f"{name} filters on `view_count_at_apply > 0`, which discards audits of "
        f"videos that genuinely had 0 views at apply. Filter on IS NOT NULL."
    )
