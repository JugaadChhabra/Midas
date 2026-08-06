"""The persisted status vocabulary has one owner, and its mirrors can't drift.

`audits.status` was spelled out at nine sites across Python, SQL and JS;
`measurement_status` at four; `autopilot_paused_reason` at five. Two of those
mirrors live outside Python and cannot import the constants, so they are parsed
and compared here instead:

  * the next_audit_candidate() SQL function re-types the picker's skip lists,
  * app/static/status.js maps audit statuses to pills.

The live parity tests (test_autopilot_picker_parity_live.py,
test_autopilot_measurement_exclusion_parity_live.py) exist because those copies
could disagree. They need credentials and skip silently without them; these
don't.

None of these strings may be RENAMED — they are persisted. This file pins the
values so a rename fails loudly instead of orphaning rows.
"""
import json
import re
from pathlib import Path

import pytest

from app import status_vocab as sv
from app.apply_outcome import ApplyOutcome

REPO = Path(__file__).resolve().parents[1]
PICKER_SQL = REPO / "supabase/migrations/20260730010000_next_audit_candidate_exclude_measurement.sql"
STATUS_JS = REPO / "app/static/status.js"


def _sql_not_in_lists(sql: str) -> list[set[str]]:
    """Every `not in ('a', 'b', ...)` literal list in the function body."""
    return [
        {v.strip().strip("'") for v in m.group(1).split(",")}
        for m in re.finditer(r"not\s+in\s*\(([^)]*)\)", sql, re.I | re.S)
    ]


# ── the values themselves (persisted — renaming breaks existing rows) ─────

def test_audit_status_values_are_the_persisted_strings():
    assert sv.AuditStatus.PENDING == "pending"
    assert sv.AuditStatus.APPLIED == "applied"
    assert sv.AuditStatus.FAILED == "failed"
    assert sv.AuditStatus.QUARANTINED == "quarantined"
    assert sv.AuditStatus.BLOCKED_TEST_AND_COMPARE == "blocked_test_and_compare"
    assert sv.AuditStatus.SHADOW_PENDING == "shadow_pending"
    assert sv.AuditStatus.REVERTED == "reverted"


def test_measurement_status_values_are_the_persisted_strings():
    assert sv.MeasurementStatus.NOT_APPLICABLE == "not_applicable"
    assert sv.ACTIVE_MEASUREMENT_STATUSES == ("awaiting_window", "measuring")
    assert sv.MEASURED_STATUSES == ("win", "neutral", "regression")


def test_paused_reason_values_are_the_persisted_strings():
    assert sv.PausedReason.TOKEN_EXPIRED == "token_expired"
    assert sv.PausedReason.REPEATED_FAILURES == "repeated_failures"
    assert sv.PausedReason.UNSAFE_MODEL == "unsafe_model"


def test_not_applicable_is_not_a_measured_verdict():
    """It means "never measured", so it must never count as evidence."""
    assert sv.MeasurementStatus.NOT_APPLICABLE not in sv.MEASURED_STATUSES


# ── apply_outcome overlaps this vocabulary and must agree ────────────────

def test_apply_outcome_agrees_with_the_vocabulary():
    assert ApplyOutcome.TEST_AND_COMPARE.value == sv.AuditStatus.BLOCKED_TEST_AND_COMPARE
    assert ApplyOutcome.FAILED.value == sv.AuditStatus.FAILED
    assert ApplyOutcome.TOKEN_EXPIRED.value == sv.PausedReason.TOKEN_EXPIRED


# ── mirror 1: the SQL picker ─────────────────────────────────────────────

def test_sql_picker_skip_list_matches_python():
    lists = _sql_not_in_lists(PICKER_SQL.read_text())
    assert set(sv.AUDIT_PICKER_SKIP_STATUSES) in lists, (
        "next_audit_candidate()'s status skip list has drifted from "
        "AUDIT_PICKER_SKIP_STATUSES"
    )


def test_sql_picker_measurement_exclusion_matches_python():
    lists = _sql_not_in_lists(PICKER_SQL.read_text())
    assert set(sv.ACTIVE_MEASUREMENT_STATUSES) in lists, (
        "next_audit_candidate()'s measurement exclusion has drifted from "
        "ACTIVE_MEASUREMENT_STATUSES"
    )


# ── mirror 2: the dashboard pills ────────────────────────────────────────

def _js_audit_status_keys() -> set[str]:
    src = STATUS_JS.read_text()
    block = re.search(r"const AUDIT_STATUS = \{(.*?)\n  \};", src, re.S)
    assert block, "AUDIT_STATUS object not found in status.js"
    return set(re.findall(r"^\s*([a-z_]+):", block.group(1), re.M))


def test_every_audit_status_renders_as_a_labelled_pill():
    """status.js calls itself one source of truth; it was missing two values,
    which rendered as unlabelled grey pills showing the raw string."""
    missing = set(sv.ALL_AUDIT_STATUSES) - _js_audit_status_keys()
    assert not missing, f"status.js has no pill for: {sorted(missing)}"


def test_status_js_invents_no_statuses_of_its_own():
    extra = _js_audit_status_keys() - set(sv.ALL_AUDIT_STATUSES) - {"none"}
    assert not extra, f"status.js maps statuses the backend never writes: {sorted(extra)}"


# ── no module re-types the vocabulary ────────────────────────────────────

@pytest.mark.parametrize("module,attr", [
    ("app.metrics_poll", "ACTIVE_MEASUREMENT_STATUSES"),
    ("app.reflection", "MEASURED_STATUSES"),
    ("app.performance", "MEASURED_STATUSES"),
])
def test_re_exports_are_the_same_object_not_a_copy(module, attr):
    import importlib
    mod = importlib.import_module(module)
    assert getattr(mod, attr) is getattr(sv, attr), (
        f"{module}.{attr} is a separate copy — it can drift from status_vocab"
    )
