"""Spans on the loop that produces evidence.

The bug that motivated all of this — one channel with autopilot on and
measurement off, silently discarding 57 applies for a month — was invisible in
logs and took an NDJSON forensic dig to find. These attributes are chosen so it
would have been a one-day question instead.
"""
from unittest.mock import MagicMock, patch

import pytest

from app import tracing


@pytest.fixture(autouse=True)
def _isolated_tracer():
    exporter = tracing._reset_for_tests()
    yield exporter
    tracing._reset_for_tests(disable=True)


def _named(exporter, name):
    hits = [s for s in exporter.get_finished_spans() if s.name == name]
    assert hits, f"no span named {name}; got {[s.name for s in exporter.get_finished_spans()]}"
    return hits[0]


def test_should_reflect_records_its_decision(_isolated_tracer):
    """A trigger stuck on for three months should be one glance, not a dig."""
    from app.reflection import _should_reflect

    report = {
        "count": 171,
        "win_rate": 12.3,
        "distribution": {"win": 21, "neutral": 147, "regression": 3, "total": 171},
        "median_ctr_delta_pct": 0.4,
        "levers": {"title": 1.0, "description": 1.0, "tags": 1.0},
        "worst_audits": [],
        "best_audits": [],
    }
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=report):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        should, reason = _should_reflect("ch1")

    assert (should, reason) == (False, "performing_well")
    attrs = _named(_isolated_tracer, "should_reflect").attributes
    assert attrs["reflection.should"] is False
    assert attrs["reflection.reason"] == "performing_well"
    assert attrs["reflection.win_rate"] == pytest.approx(12.3)
    assert attrs["reflection.wins"] == 21
    assert attrs["reflection.neutrals"] == 147
    assert attrs["reflection.regressions"] == 3


def test_should_reflect_records_the_no_evidence_case(_isolated_tracer):
    from app.reflection import _should_reflect

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=None):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        _should_reflect("ch1")

    attrs = _named(_isolated_tracer, "should_reflect").attributes
    assert attrs["reflection.reason"] == "no_measured_outcomes"
    assert "reflection.win_rate" not in attrs


def test_audit_video_span_records_its_context(_isolated_tracer):
    """An LLM span with no parent cannot answer 'why did this call happen'."""
    from app import audits

    video = {
        "id": "vid1", "channel_id": "ch1", "privacy_status": "public",
        "title": "t", "description": "d", "tags": [], "is_short": False,
    }
    suggestion = {
        "comparisons": {
            "title": {"suggested": "new title"},
            "description": {"suggested": "new desc"},
            "tags": {"suggested": ["a"]},
        },
        "issues": [], "reasoning": "r",
    }

    with patch("app.audits.supabase") as mock_sb, \
         patch("app.audits.chat_json", return_value=suggestion), \
         patch("app.audits.fetch_transcript", return_value=("transcript", "en")), \
         patch("app.audits._ensure_strategy_row"):
        tbl = mock_sb.return_value.table.return_value
        tbl.select.return_value.eq.return_value.single.return_value \
            .execute.return_value.data = video
        tbl.select.return_value.eq.return_value.execute.return_value.data = [{}]
        tbl.insert.return_value.execute.return_value.data = [{"id": 1}]
        audits.audit_video("vid1")

    span = _named(_isolated_tracer, "audit_video")
    assert span.attributes["video_id"] == "vid1"
    assert span.attributes["channel_id"] == "ch1"
    assert span.attributes["audit.transcript_available"] is True


def test_apply_span_records_whether_the_audit_can_ever_be_measured(_isolated_tracer):
    """THE attribute. measurement_enabled=False on the autopilot channel meant
    57 applies produced no evidence and nothing said so."""
    from app import audits

    assert hasattr(audits, "_record_apply_measurability"), (
        "expected a helper recording measurement_enabled on the apply span"
    )
    with tracing.span("apply_audit") as rec:
        audits._record_apply_measurability(rec, {"measurement_enabled": False})

    attrs = _named(_isolated_tracer, "apply_audit").attributes
    assert attrs["apply.measurement_enabled"] is False
    assert attrs["apply.will_be_measured"] is False


def test_apply_span_marks_a_measurable_channel(_isolated_tracer):
    from app import audits

    with tracing.span("apply_audit") as rec:
        audits._record_apply_measurability(rec, {"measurement_enabled": True})

    attrs = _named(_isolated_tracer, "apply_audit").attributes
    assert attrs["apply.will_be_measured"] is True
