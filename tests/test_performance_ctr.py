"""The performance read-model reports measured CTR, not view velocity.

_build_rows computed `before_velocity = view_count_at_apply / age_at_apply`
— a video's LIFETIME average views/day — and derived both `velocity_lift_pct`
and a `regression` flag (`views_per_day < 0.5 * before_velocity`) from it.
That baseline is inflated on any decaying view curve: measured over 439
audits with a real pre-apply window it was too high in 100% of cases,
median 25.8x. The page therefore flagged almost every audit as a regression.

`outcome_distribution` also invented a fourth outcome vocabulary
(accelerated | flat | regression) that overlapped measurement_status
(win | neutral | regression) but was computed from a different signal, so
the dashboard and the measurement loop could disagree about one audit.

Raw descriptive numbers (views at apply, views now, deltas, engagement)
are facts and stay — only the derived verdicts move to CTR.
"""
from unittest.mock import MagicMock, patch

import pytest

from app import performance


def _audit(aid, *, status="applied", m_status=None, delta=None,
           applied_at="2026-07-01T00:00:00+00:00", view_at=1000,
           title_changed=True, tags_changed=True):
    result = {}
    if delta is not None:
        result["ctr_delta_relative"] = delta
    return {
        "id": aid, "video_id": f"v{aid}", "status": status,
        "applied_at": applied_at, "created_at": applied_at,
        "suggested_title": "new" if title_changed else "old",
        "title_before": "old",
        "suggested_description": "d2", "description_before": "d1",
        "suggested_tags": ["b"] if tags_changed else ["a"], "tags_before": ["a"],
        "view_count_at_apply": view_at, "like_count_at_apply": 10,
        "comment_count_at_apply": 1,
        "measurement_status": m_status, "measurement_result": result,
        "ai_reasoning": "why",
    }


def _videos(audits, channel_id="ch1"):
    return [{"id": a["video_id"], "channel_id": channel_id, "title": "t",
             "thumbnail_url": None, "view_count": a["view_count_at_apply"] + 500,
             "like_count": 20, "comment_count": 3,
             "last_fetched_at": None, "published_at": "2026-01-01T00:00:00+00:00"}
            for a in audits]


def _call(audits, fn, *args, **kw):
    """Drive _build_rows / the summary against mocked storage."""
    with patch.object(performance, "audits_for_channel"), \
         patch.object(performance, "fetch_all", return_value=audits), \
         patch.object(performance, "supabase") as sb:
        sb.return_value.table.return_value.select.return_value.in_.return_value \
            .execute.return_value.data = _videos(audits)
        return fn("ch1", *args, **kw)


def _run(audits):
    return _call(audits, performance._build_rows, None)


# ── rows ──────────────────────────────────────────────────────────────────

def test_rows_carry_measurement_verdict_not_velocity():
    rows = _run([_audit(1, m_status="win", delta=0.25)])
    r = rows[0]
    assert r["measurement_status"] == "win"
    assert r["ctr_delta_pct"] == pytest.approx(25.0)
    for gone in ("before_velocity", "after_velocity", "velocity_lift_pct", "regression"):
        assert gone not in r, f"{gone} is still in the row"


def test_rows_keep_raw_descriptive_numbers():
    """Raw view deltas are facts — they were never the broken part."""
    r = _run([_audit(1, m_status="win", delta=0.1, view_at=1000)])[0]
    assert r["view_count_at_apply"] == 1000
    assert r["view_count_now"] == 1500
    assert r["delta_views"] == 500
    assert r["pct_views"] == pytest.approx(50.0)
    assert r["views_per_day_since_apply"] is not None


def test_unmeasured_audit_has_no_verdict():
    r = _run([_audit(1, m_status="not_applicable")])[0]
    assert r["measurement_status"] == "not_applicable"
    assert r["ctr_delta_pct"] is None


def test_rows_are_channel_scoped_at_the_query():
    """Regression guard: this used to select the WHOLE audits table unpaginated
    and filter by channel in Python, truncating at Supabase's 1000-row cap."""
    with patch.object(performance, "audits_for_channel") as afc, \
         patch.object(performance, "fetch_all", return_value=[]) as fa:
        performance._build_rows("ch1", ["applied"])
    afc.assert_called_once()
    assert afc.call_args.args[0] == "ch1"
    fa.assert_called_once()


# ── summary ───────────────────────────────────────────────────────────────

def _summary(audits):
    return _call(audits, performance.performance_summary, status="applied")


def test_summary_win_rate_and_median_from_ctr():
    audits = ([_audit(i, m_status="win", delta=0.30) for i in range(6)]
              + [_audit(10 + i, m_status="regression", delta=-0.20) for i in range(4)])
    s = _summary(audits)
    assert s["win_rate"] == 60.0
    assert s["median_ctr_delta_pct"] == pytest.approx(30.0, abs=0.1)
    assert s["regression_count"] == 4
    assert "median_velocity_lift" not in s


def test_outcome_distribution_uses_the_measurement_vocabulary():
    audits = ([_audit(1, m_status="win", delta=0.3),
               _audit(2, m_status="neutral", delta=0.01),
               _audit(3, m_status="regression", delta=-0.3),
               _audit(4, m_status="not_applicable")])
    od = _summary(audits)["outcome_distribution"]
    assert od == {"win": 1, "neutral": 1, "regression": 1, "total": 3}
    assert "accelerated" not in od and "flat" not in od


def test_unmeasured_audits_are_excluded_from_verdict_stats():
    audits = [_audit(i, m_status="not_applicable") for i in range(10)]
    s = _summary(audits)
    assert s["win_rate"] is None
    assert s["median_ctr_delta_pct"] is None
    assert s["outcome_distribution"]["total"] == 0
    assert s["applied_count"] == 10        # they still exist as applied audits


def test_cohorts_report_ctr_not_velocity():
    audits = [_audit(i, m_status="win", delta=0.20, tags_changed=False)
              for i in range(4)]
    c = _summary(audits)["cohorts"]
    assert c["title_changed"]["avg_ctr_delta_pct"] == pytest.approx(20.0, abs=0.1)
    assert "avg_velocity_lift" not in c["title_changed"]
    assert c["tags_changed"]["n"] == 0


def test_no_velocity_math_left_in_the_module():
    import ast
    import inspect
    import textwrap
    for fn in (performance._build_rows, performance.performance_summary):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.Module)) and ast.get_docstring(node):
                node.body = node.body[1:]
        code = ast.unparse(tree)
        for banned in ("velocity", "published_at", "accelerated"):
            assert banned not in code, f"{fn.__qualname__} still references {banned}"


def test_rows_expose_the_measured_window_pair():
    """The before/after chart needs real rates over matched windows."""
    a = _audit(1, m_status="win", delta=0.25)
    a["measurement_result"].update({
        "pre_window": {"ctr": 0.040}, "post_window": {"ctr": 0.050},
    })
    r = _run([a])[0]
    assert r["ctr_before_pct"] == pytest.approx(4.0)
    assert r["ctr_after_pct"] == pytest.approx(5.0)


def test_rows_without_windows_have_no_ctr_pair():
    r = _run([_audit(1, m_status="not_applicable")])[0]
    assert r["ctr_before_pct"] is None and r["ctr_after_pct"] is None


def test_video_fetch_is_chunked_past_the_row_cap():
    """One .in_() over >1000 ids caps the RESPONSE at 1000 rows, dropping every
    audit whose video fell outside it (1269 of 1985 shown on the live channel)."""
    audits = [_audit(i) for i in range(1200)]
    vids = _videos(audits)
    chunks = []

    with patch.object(performance, "audits_for_channel"), \
         patch.object(performance, "fetch_all", return_value=audits), \
         patch.object(performance, "supabase") as sb:
        def _in(col, ids):
            chunks.append(list(ids))
            r = MagicMock()
            by_id = {v["id"]: v for v in vids}
            r.execute.return_value.data = [by_id[i] for i in ids if i in by_id]
            return r
        sb.return_value.table.return_value.select.return_value.in_.side_effect = _in
        rows = performance._build_rows("ch1", None)

    assert len(chunks) == 3                     # 1200 ids / 500
    assert all(len(c) <= 500 for c in chunks)
    assert len(rows) == 1200                    # nothing dropped
