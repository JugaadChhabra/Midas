"""The shell that carries data between Loop 1's two pure stages.

`plan_measurement` and `judge_reach` were already covered (see
test_measurement_judge.py). `_eval_audit`, the thing that orders them, was not —
and it holds the mistakes that would silently invert a verdict rather than raise:

  * reading the post window as the pre window (or vice versa),
  * judging before the baseline is written,
  * re-stamping `measuring` on every pass for the weeks a window can wait,
  * writing anything at all while the window is still open.

None of those would fail a test before this file existed. Swapping the two
window arguments would have passed the whole suite and inverted every win and
regression on the fleet, discoverable only weeks later in the outcomes rollup.

The read crosses an injected seam, so the ordering is asserted at an interface.
The three writes are patched by name — a far more stable point than a query
builder, and enough to observe what was persisted and in what order.
"""
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest

from app import measurement as m
from app import reach
from app.status_vocab import MeasurementStatus, OutcomeDecision

APPLIED = date(2026, 6, 1)
AUDIT_ID = 7
VIDEO_ID = "v1"


@pytest.fixture(autouse=True)
def _fixed_thresholds():
    with patch.object(m.settings, "MEASUREMENT_WINDOW_DAYS", 21), \
         patch.object(m.settings, "MIN_IMPRESSIONS", 500), \
         patch.object(m.settings, "CTR_WIN_THRESHOLD", 0.10), \
         patch.object(m.settings, "CTR_REGRESSION_THRESHOLD", -0.10), \
         patch.object(m.settings, "MEASUREMENT_COVERAGE_GRACE_DAYS", 14):
        yield


@pytest.fixture
def writes():
    """The three named writes, observable and inert."""
    with patch.object(m, "_finalize") as finalize, \
         patch.object(m, "_write_baseline") as baseline, \
         patch.object(m, "_mark_measuring") as measuring:
        yield {"finalize": finalize, "baseline": baseline, "measuring": measuring}


def _audit(**kw):
    return {"id": AUDIT_ID, "video_id": VIDEO_ID,
            "applied_at": "2026-06-01T12:00:00+00:00",
            "measurement_status": MeasurementStatus.AWAITING_WINDOW, **kw}


VIDEO = {"id": VIDEO_ID, "channel_id": "c1"}


def _covered(*windows):
    days = set()
    for w in windows:
        days |= set(reach.days(w))
    return days


def _reader(**by_window):
    """A reach reader backed by a dict, keyed 'pre' / 'post'.

    Returns numbers that make the window it was asked for identifiable, so a
    swapped call shows up as a swapped verdict rather than as nothing.
    """
    pre, post = reach.window_for(APPLIED)
    table = {pre: by_window["pre"], post: by_window["post"]}

    def read(video_id, window):
        assert video_id == VIDEO_ID
        return table[window]

    return MagicMock(side_effect=read)


# ── the ordering ──────────────────────────────────────────────────────────

def test_the_pre_window_is_read_before_the_post_window(writes):
    """The bug this file exists for. Swap the two calls in _eval_audit and this
    is the assertion that fails."""
    pre, post = reach.window_for(APPLIED)
    read = _reader(pre=(5000, 0.04), post=(5000, 0.06))

    m._eval_audit(_audit(), VIDEO, _covered(pre, post), date(2026, 7, 1), read)

    assert read.call_args_list == [call(VIDEO_ID, pre), call(VIDEO_ID, post)]


def test_a_rising_ctr_is_a_win_not_a_regression(writes):
    """The consequence of that ordering, stated as behaviour: CTR went UP, so
    the verdict must be a win. Reading the windows backwards turns this into a
    regression, and nothing else in the suite would notice."""
    pre, post = reach.window_for(APPLIED)
    read = _reader(pre=(5000, 0.04), post=(5000, 0.06))

    status = m._eval_audit(_audit(), VIDEO, _covered(pre, post), date(2026, 7, 1), read)

    assert status == MeasurementStatus.WIN
    persisted = writes["finalize"].call_args[0]
    assert persisted[1] == MeasurementStatus.WIN
    assert persisted[3]["ctr_delta_relative"] == pytest.approx(0.5)


def test_the_baseline_is_written_from_the_pre_window_before_the_verdict(writes):
    """Order matters as well as content: _finalize is what makes the audit
    terminal, so a baseline written after it would be lost on a crash between."""
    pre, post = reach.window_for(APPLIED)
    read = _reader(pre=(5000, 0.04), post=(3000, 0.02))
    manager = MagicMock()
    writes["baseline"].side_effect = lambda **kw: manager.baseline(**kw)
    writes["finalize"].side_effect = lambda *a: manager.finalize(*a)

    m._eval_audit(_audit(), VIDEO, _covered(pre, post), date(2026, 7, 1), read)

    assert [c[0] for c in manager.mock_calls] == ["baseline", "finalize"]
    kw = writes["baseline"].call_args[1]
    assert kw["pre"] == pre                  # the PRE window, not the post one
    assert kw["impressions"] == 5000         # and the pre numbers
    assert kw["ctr"] == pytest.approx(0.04)
    assert kw["video_id"] == VIDEO_ID
    assert kw["channel_id"] == "c1"


# ── the branches that write nothing, or write once ────────────────────────

def test_an_open_window_touches_nothing(writes):
    """No verdict, no baseline, no status change, and no reach read — the row is
    left exactly as it was for another day."""
    read = MagicMock()

    status = m._eval_audit(_audit(), VIDEO, set(), date(2026, 6, 10), read)

    assert status == MeasurementStatus.AWAITING_WINDOW
    read.assert_not_called()
    for w in writes.values():
        w.assert_not_called()


def test_a_decision_made_without_reach_does_not_read_reach(writes):
    """plan_measurement can finalize on timestamps alone; doing a reach read
    anyway would be a wasted round-trip per audit per pass."""
    read = MagicMock()

    status = m._eval_audit(_audit(applied_at=None), VIDEO, set(), date(2026, 7, 1), read)

    assert status == MeasurementStatus.NOT_APPLICABLE
    read.assert_not_called()
    writes["finalize"].assert_called_once()
    writes["baseline"].assert_not_called()


def test_waiting_for_coverage_parks_the_row_once(writes):
    pre, post = reach.window_for(APPLIED)
    covered = _covered(pre, post) - {post[1]}
    read = MagicMock()

    status = m._eval_audit(_audit(), VIDEO, covered, date(2026, 7, 1), read)

    assert status == MeasurementStatus.MEASURING
    writes["measuring"].assert_called_once_with(AUDIT_ID)
    read.assert_not_called()
    writes["finalize"].assert_not_called()


def test_an_already_measuring_row_is_not_re_stamped(writes):
    """A window can wait weeks on late CSVs; re-writing the row every pass is a
    daily UPDATE per in-flight audit for no change."""
    pre, post = reach.window_for(APPLIED)
    covered = _covered(pre, post) - {post[1]}

    status = m._eval_audit(_audit(measurement_status=MeasurementStatus.MEASURING),
                           VIDEO, covered, date(2026, 7, 1), MagicMock())

    assert status == MeasurementStatus.MEASURING
    writes["measuring"].assert_not_called()


# ── the verdict reaches the row ───────────────────────────────────────────

@pytest.mark.parametrize("pre_n,post_n,status,outcome", [
    ((5000, 0.04), (5000, 0.06), MeasurementStatus.WIN, OutcomeDecision.KEPT),
    ((5000, 0.04), (5000, 0.041), MeasurementStatus.NEUTRAL, OutcomeDecision.KEPT),
    ((5000, 0.04), (5000, 0.02), MeasurementStatus.REGRESSION, OutcomeDecision.NONE),
    ((100, 0.04), (5000, 0.06), MeasurementStatus.NOT_APPLICABLE, OutcomeDecision.NONE),
])
def test_what_is_returned_is_what_is_persisted(writes, pre_n, post_n, status, outcome):
    """A returned status that disagreed with the written one would make the job
    summary a fiction."""
    pre, post = reach.window_for(APPLIED)
    read = _reader(pre=pre_n, post=post_n)

    returned = m._eval_audit(_audit(), VIDEO, _covered(pre, post), date(2026, 7, 1), read)

    audit_id, written_status, written_outcome, _result = writes["finalize"].call_args[0]
    assert returned == written_status == status
    assert written_outcome == outcome
    assert audit_id == AUDIT_ID


def test_a_regression_is_logged_for_a_human(writes, caplog):
    """Auto-revert is off, so the log line is the entire handoff to an operator."""
    pre, post = reach.window_for(APPLIED)
    read = _reader(pre=(5000, 0.04), post=(5000, 0.02))

    with caplog.at_level("WARNING", logger="midas.measurement"):
        m._eval_audit(_audit(), VIDEO, _covered(pre, post), date(2026, 7, 1), read)

    assert "REGRESSION" in caplog.text
    assert str(AUDIT_ID) in caplog.text


def test_the_default_reader_is_the_real_one():
    """The seam exists for testing; production must not accidentally get a stub."""
    import inspect
    assert inspect.signature(m._eval_audit).parameters["read_reach"].default \
        is reach.aggregate


# ── the loop around it ────────────────────────────────────────────────────
#
# eval_measurements is I/O orchestration: read the in-flight audits, resolve
# their channels, evaluate each. There is no seam that would make it pure
# without inventing one, so these patch its collaborators by name. The branches
# below are worth pinning even by that means — each one mishandles rows
# silently rather than raising.

def _eval_sb(audits, videos):
    sb = MagicMock()
    tables = {}

    def table(name):
        return tables.setdefault(name, MagicMock())

    sb.table.side_effect = table
    # Two .order() hops: eval_measurements orders by id, and all_rows appends its
    # own total-order key on top. Miss one and the stub is bypassed silently —
    # .data becomes a fresh MagicMock, which iterates as empty, and the test
    # passes while asserting on nothing.
    table("audits").select.return_value.in_.return_value.eq.return_value \
        .order.return_value.order.return_value.range.return_value \
        .execute.return_value.data = audits
    table("videos").select.return_value.in_.return_value \
        .execute.return_value.data = videos
    return sb, tables


def test_an_audit_whose_video_vanished_is_parked_not_crashed():
    """A deleted video must not take the whole pass down with a KeyError, and
    must not be recorded as a measured outcome either."""
    audits = [{"id": 1, "video_id": "gone",
               "measurement_status": MeasurementStatus.AWAITING_WINDOW}]
    sb, _ = _eval_sb(audits, [])
    with patch.object(m, "supabase", return_value=sb), \
         patch.object(m, "_finalize") as finalize, \
         patch.object(m, "_eval_audit") as ev:
        summary = m.eval_measurements()

    ev.assert_not_called()
    _id, status, outcome, result = finalize.call_args[0]
    assert (status, outcome) == (MeasurementStatus.NOT_APPLICABLE, OutcomeDecision.NONE)
    assert "no longer exists" in result["rationale"]
    assert summary["evaluated"] == 1


def test_coverage_is_read_once_per_channel_not_once_per_audit():
    """Three audits on one channel is one ledger read. Per-audit would be a
    full paginated read of the channel's coverage for every row in flight."""
    audits = [{"id": i, "video_id": f"v{i}",
               "measurement_status": MeasurementStatus.AWAITING_WINDOW}
              for i in (1, 2, 3)]
    videos = [{"id": f"v{i}", "channel_id": "c1"} for i in (1, 2, 3)]
    sb, _ = _eval_sb(audits, videos)
    with patch.object(m, "supabase", return_value=sb), \
         patch.object(m.reach, "coverage", return_value=set()) as coverage, \
         patch.object(m, "_eval_audit", return_value=MeasurementStatus.MEASURING):
        m.eval_measurements()

    coverage.assert_called_once_with("c1")


def test_one_bad_audit_does_not_abort_the_pass():
    audits = [{"id": i, "video_id": f"v{i}",
               "measurement_status": MeasurementStatus.AWAITING_WINDOW}
              for i in (1, 2, 3)]
    videos = [{"id": f"v{i}", "channel_id": "c1"} for i in (1, 2, 3)]
    sb, _ = _eval_sb(audits, videos)

    def boom(audit, *a, **kw):
        if audit["id"] == 2:
            raise RuntimeError("postgrest hiccup")
        return MeasurementStatus.WIN

    with patch.object(m, "supabase", return_value=sb), \
         patch.object(m.reach, "coverage", return_value=set()), \
         patch.object(m, "_eval_audit", side_effect=boom):
        summary = m.eval_measurements()

    assert summary["errors"] == 1
    assert summary[MeasurementStatus.WIN] == 2      # the other two still landed


def test_only_still_applied_audits_are_evaluated():
    """A human revert mid-window takes the video off the new metadata, so the
    post window would measure post-revert exposure — and finalizing would
    clobber the operator's outcome_decision='reverted'."""
    sb, tables = _eval_sb([], [])
    with patch.object(m, "supabase", return_value=sb):
        m.eval_measurements()

    select = tables["audits"].select.return_value
    select.in_.assert_called_once_with(
        "measurement_status", list(m.ACTIVE_MEASUREMENT_STATUSES))
    select.in_.return_value.eq.assert_called_once_with("status", m.AuditStatus.APPLIED)
