"""The prompt loop reads measured CTR verdicts, never view velocity.

The old _build_perf_report compared `view_count_at_apply / age_at_apply`
(a video's LIFETIME average views/day) against its post-apply rate. On a
decaying view curve those aren't comparable: measured against 439 audit
pairs with a real pre-apply window, that baseline was inflated in 100% of
cases, median 25.8x — scoring a zero-effect audit at -96%. Production
showed a -99.1% median lift and a 0.4% win rate, so _should_reflect fired
every week and four prompt versions were written to fix a phantom.

Correcting the baseline is not enough (median only moves to -82.6%): any
before/after on raw views is dominated by natural decay. CTR from the
measurement loop is the decay-normalised signal, and measurement.py
already computes it over symmetric pre/post windows.
"""
from unittest.mock import MagicMock, patch

import pytest

from app import reflection


def _audit(aid, status, delta, *, applied_at="2026-07-01T00:00:00+00:00",
           title_before="old", title_after="new", desc_changed=True, tags_changed=True):
    """One measured audit row as audits_for_channel would return it."""
    result = {"pre_window": {}, "post_window": {}}
    if delta is not None:
        result["ctr_delta_relative"] = delta
    return {
        "id": aid,
        "video_id": f"v{aid}",
        "applied_at": applied_at,
        "measurement_status": status,
        "measurement_result": result,
        "title_before": title_before,
        "suggested_title": title_after,
        "description_before": "d1",
        "suggested_description": "d2" if desc_changed else "d1",
        "tags_before": ["a"],
        "suggested_tags": ["b"] if tags_changed else ["a"],
        "ai_reasoning": "because",
    }


def _report(rows):
    with patch.object(reflection, "audits_for_channel"), \
         patch.object(reflection, "fetch_all", return_value=rows):
        return reflection._build_perf_report("ch1")


def test_no_measured_outcomes_yields_no_report():
    """The live state: every applied audit is not_applicable, none measured."""
    assert _report([]) is None


def test_below_min_data_points_yields_no_report():
    rows = [_audit(i, "win", 0.5) for i in range(reflection._MIN_DATA_POINTS - 1)]
    assert _report(rows) is None


def test_win_rate_and_median_come_from_ctr_verdicts():
    rows = (
        [_audit(i, "win", 0.40) for i in range(6)]
        + [_audit(10 + i, "neutral", 0.01) for i in range(2)]
        + [_audit(20 + i, "regression", -0.30) for i in range(2)]
    )
    r = _report(rows)
    assert r["count"] == 10
    assert r["win_rate"] == 60.0                    # 6 wins / 10 measured
    # deltas sorted: [-30, -30, 1, 1, 40, 40, 40, 40, 40, 40] -> median 40.0
    assert r["median_ctr_delta_pct"] == pytest.approx(40.0, abs=0.1)
    assert "median_velocity_lift" not in r


def test_neutral_without_a_delta_still_counts_as_measured():
    """_classify returns (neutral, None) when pre_ctr is 0 — a real verdict."""
    rows = [_audit(i, "win", 0.5) for i in range(5)] + \
           [_audit(10 + i, "neutral", None) for i in range(5)]
    r = _report(rows)
    assert r["count"] == 10          # the None-delta rows are measured...
    assert r["win_rate"] == 50.0     # ...and count against the win rate
    assert r["median_ctr_delta_pct"] is not None   # median over the 5 that have one


def test_regression_count_is_recent_only():
    recent = [_audit(i, "regression", -0.4, applied_at="2099-01-01T00:00:00+00:00")
              for i in range(4)]
    old = [_audit(10 + i, "regression", -0.4, applied_at="2020-01-01T00:00:00+00:00")
           for i in range(6)]
    r = _report(recent + old)
    assert r["count"] == 10
    assert r["regression_count"] == 4


def test_levers_average_ctr_delta_by_changed_field():
    rows = [_audit(i, "win", 0.20, tags_changed=False) for i in range(10)]
    r = _report(rows)
    assert r["levers"]["title"] == pytest.approx(20.0, abs=0.1)
    assert r["levers"]["tags"] is None      # no audit changed tags


def test_report_carries_no_velocity_fields():
    rows = [_audit(i, "win", 0.3) for i in range(10)]
    r = _report(rows)
    blob = repr(r)
    assert "velocity" not in blob
    for a in r["worst_audits"] + r["best_audits"]:
        assert "velocity_lift_pct" not in a
        assert "ctr_delta_pct" in a


# ── the gate ──────────────────────────────────────────────────────────────

def test_should_reflect_refuses_without_measured_outcomes():
    """No measured CTR => the prompt loop must not fire at all."""
    with patch.object(reflection, "supabase") as sb, \
         patch.object(reflection, "_build_perf_report", return_value=None):
        sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        ok, reason = reflection._should_reflect("ch1")
    assert ok is False
    assert reason == "no_measured_outcomes"


def test_velocity_is_gone_from_the_prompt_loop():
    """Regression guard: no view-velocity math anywhere in the report path.

    Checks executable code only — the docstrings deliberately explain why the
    velocity baseline was wrong, so a bare string search would match those.
    """
    import ast
    import inspect
    import textwrap

    for fn in (reflection._build_perf_report, reflection._format_perf_report):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.Module)) and ast.get_docstring(node):
                node.body = node.body[1:]          # drop the docstring node
        code = ast.unparse(tree)
        for banned in ("velocity", "view_count_at_apply", "age_at_apply", "published_at"):
            assert banned not in code, f"{fn.__qualname__} still references {banned}"


# ── auto-revert cohort comparison ─────────────────────────────────────────

def _cohort(rows):
    with patch.object(reflection, "supabase") as sb, \
         patch.object(reflection, "fetch_all", return_value=rows):
        sb.return_value.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.in_.return_value = MagicMock()
        return reflection._cohort_median_ctr_delta(7)


def test_cohort_median_uses_ctr_not_velocity():
    rows = [_audit(i, "win", 0.30) for i in range(6)] + \
           [_audit(10 + i, "regression", -0.10) for i in range(4)]
    # deltas: [30]*6 + [-10]*4 -> sorted median of 10 = (30 + 30)/2 ... no:
    # sorted = [-10,-10,-10,-10,30,30,30,30,30,30]; median = (30+30)/2 = 30.0
    assert _cohort(rows) == pytest.approx(30.0, abs=0.1)


def test_cohort_returns_none_below_min_data_points():
    assert _cohort([_audit(i, "win", 0.3) for i in range(reflection._MIN_DATA_POINTS - 1)]) is None


def test_cohort_ignores_verdicts_without_a_delta():
    """Rows with no ctr_delta_relative can't contribute to a median."""
    rows = [_audit(i, "win", 0.30) for i in range(5)] + \
           [_audit(10 + i, "neutral", None) for i in range(9)]
    assert _cohort(rows) is None      # only 5 usable deltas < _MIN_DATA_POINTS


def test_cohort_has_no_velocity_math():
    import ast, inspect, textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(reflection._cohort_median_ctr_delta)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.Module)) and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.unparse(tree)
    for banned in ("velocity", "view_count_at_apply", "age_at_apply", "published_at"):
        assert banned not in code
