"""The persisted status vocabulary has one owner, and its mirrors can't drift.

`audits.status` was spelled out at nine sites across Python, SQL and JS;
`measurement_status` at four; `autopilot_paused_reason` at five. Two of those
mirrors live outside Python and cannot import the constants, so they are parsed
and compared here instead:

  * the next_audit_candidate() SQL function re-types the picker's skip lists,
  * app/static/status.js maps audit statuses to pills,
  * the interventions migration's partial unique index re-types the active
    intervention statuses (spec Part 2 §1.6), and so does the warm_pool()
    SQL function (B4; replaced by S1.4a, which also re-types the backlinks
    lever and its experiment arms).

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
INTERVENTIONS_SQL = REPO / "supabase/migrations/20261006020000_interventions.sql"
WARM_POOL_SQL = REPO / "supabase/migrations/20261023000000_warm_pool_agent_exclusions.sql"
LEVER_VERDICTS_SQL = REPO / "supabase/migrations/20261023010000_lever_verdicts.sql"
TITLE_SCOPES_SQL = REPO / "supabase/migrations/20261030010000_lever_verdicts_title_scopes.sql"
PLAYLIST_ARMS_SQL = REPO / "supabase/migrations/20261027000000_playlist_arms.sql"
SHORT_LINKS_SQL = REPO / "supabase/migrations/20261027010000_short_link_recommendations.sql"
CHANNEL_HTML = REPO / "app/static/channel.html"


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


def test_intervention_values_are_the_persisted_strings():
    assert sv.ALL_INTERVENTION_LEVERS == {"backlinks", "playlist", "short_link", "title"}
    assert sv.ALL_INTERVENTION_ORIGINS == {"midas", "human"}
    assert sv.ALL_INTERVENTION_ARMS == {"treated", "holdout", "n/a"}
    assert sv.InterventionStatus.PLANNED == "planned"
    assert sv.InterventionStatus.APPLIED == "applied"
    assert sv.InterventionStatus.MEASURING == "measuring"
    assert sv.InterventionStatus.JUDGED == "judged"
    assert sv.InterventionStatus.CANCELLED == "cancelled"
    assert sv.InterventionStatus.DECLINED == "declined"
    assert sv.InterventionStatus.HOLDOUT == "holdout"
    assert sv.InterventionStatus.INSUFFICIENT_DATA == "insufficient_data"
    assert sv.ALL_INTERVENTION_STATUSES == {
        "planned", "applied", "measuring", "judged", "cancelled",
        "declined", "holdout", "insufficient_data",
    }


def test_intervention_measurement_values_are_the_persisted_strings():
    """interventions.measurement_status (S1.6a); the outcome lives in `status`."""
    assert sv.InterventionMeasurement.AWAITING_WINDOW == "awaiting_window"
    assert sv.InterventionMeasurement.EXTENDED == "extended"
    assert sv.InterventionMeasurement.DONE == "done"
    assert sv.ALL_INTERVENTION_MEASUREMENTS == {"awaiting_window", "extended", "done"}
    assert not sv.ALL_INTERVENTION_MEASUREMENTS & {
        sv.InterventionStatus.JUDGED, sv.InterventionStatus.INSUFFICIENT_DATA}


def test_decision_used_values_are_the_persisted_strings():
    """decision_log.used (B5, spec Part 2 §7)."""
    assert sv.DecisionUsed.RULES == "rules"
    assert sv.DecisionUsed.JEV == "jev"
    assert sv.ALL_DECISION_USED == {"rules", "jev"}


def test_active_intervention_statuses_are_the_open_ones():
    """Spec Part 2 §1.6. A held-out video is in the experiment; a declined,
    judged, cancelled or insufficient_data one is not."""
    assert sv.ACTIVE_INTERVENTION_STATUSES == {"planned", "applied", "measuring", "holdout"}
    assert sv.ACTIVE_INTERVENTION_STATUSES <= sv.ALL_INTERVENTION_STATUSES


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


# ── mirror 3: the one-active-Midas-intervention index ─────────────────────

def test_sql_active_intervention_index_matches_python():
    sql = INTERVENTIONS_SQL.read_text()
    m = re.search(r"interventions_one_active_midas_per_video.*?where\s+(.*?);", sql, re.S | re.I)
    assert m, "interventions_one_active_midas_per_video not found"
    where = m.group(1)
    assert re.search(r"origin\s*=\s*'midas'", where)
    statuses = re.search(r"status\s+in\s*\(([^)]*)\)", where, re.I)
    assert {v.strip().strip("'") for v in statuses.group(1).split(",")} == \
        set(sv.ACTIVE_INTERVENTION_STATUSES), (
        "the partial unique index's status list has drifted from "
        "ACTIVE_INTERVENTION_STATUSES")


def test_sql_warm_pool_intervention_exclusion_matches_python():
    sql = WARM_POOL_SQL.read_text()
    m = re.search(r"from interventions i\s+where(.*?)\)\s*order by", sql, re.S | re.I)
    assert m, "warm_pool()'s intervention exclusion not found"
    where = m.group(1)
    assert re.search(r"origin\s*=\s*'midas'", where)
    statuses = re.search(r"status\s+in\s*\(([^)]*)\)", where, re.I)
    assert {v.strip().strip("'") for v in statuses.group(1).split(",")} == \
        set(sv.ACTIVE_INTERVENTION_STATUSES), (
        "warm_pool()'s intervention exclusion has drifted from "
        "ACTIVE_INTERVENTION_STATUSES")
    # S1.4a's once-per-experiment rule: a midas backlinks holdout row, or a
    # treated one that reached YouTube (review fix, 2026-10-23).
    lever = re.search(r"lever\s*=\s*'([^']+)'", where)
    assert lever and lever.group(1) == sv.InterventionLever.BACKLINKS
    arms = set(re.findall(r"arm\s*=\s*'([^']+)'", where))
    assert arms == {sv.InterventionArm.TREATED, sv.InterventionArm.HOLDOUT}
    assert re.search(r"arm\s*=\s*'treated'\s+and\s+i\.applied_at\s+is\s+not\s+null", where)


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


def test_lever_verdict_values_are_the_persisted_strings():
    """lever_verdicts.arm_scope and .verdict (S1.6b), as the migration's comments list them;
    S3.5's title scopes, as its `comment on column` lists every arm_scope."""
    assert sv.ALL_LEVER_VERDICT_SCOPES == {"treated_vs_holdout", "human",
                                           "pipeline_vs_holdout", "agent_vs_holdout"}
    assert sv.ALL_LEVER_VERDICTS == {"helped", "no_change", "worse"}
    ddl = LEVER_VERDICTS_SQL.read_text()
    for column, values in (("arm_scope", {"treated_vs_holdout", "human"}),
                           ("verdict", sv.ALL_LEVER_VERDICTS)):
        [line] = [l for l in ddl.splitlines() if l.strip().startswith(column + " ")]
        assert set(line.split("--")[1].strip().split("|")) == values
    [comment] = re.findall(r"comment on column lever_verdicts\.arm_scope is '([^']*)'",
                           TITLE_SCOPES_SQL.read_text())
    assert set(comment.split("|")) == sv.ALL_LEVER_VERDICT_SCOPES


def test_playlist_arm_values_are_the_persisted_strings():
    """playlist_arms.arm, .status and .measurement_status (Slice 2 S2.1), as the
    migration's comments list them."""
    assert sv.ALL_PLAYLIST_ARMS == {"treated", "holdout"}
    assert sv.ALL_PLAYLIST_ARM_STATUSES == {
        "planned", "applying", "dosed", "no_dose", "holdout", "judged", "insufficient_data"}
    assert sv.ALL_PLAYLIST_ARM_MEASUREMENTS == {"awaiting_window", "measuring", "done"}
    assert not sv.ALL_PLAYLIST_ARM_MEASUREMENTS & {
        sv.PlaylistArmStatus.JUDGED, sv.PlaylistArmStatus.INSUFFICIENT_DATA}
    ddl = PLAYLIST_ARMS_SQL.read_text()
    for column, values in (("arm", sv.ALL_PLAYLIST_ARMS),
                           ("status", sv.ALL_PLAYLIST_ARM_STATUSES),
                           ("measurement_status", sv.ALL_PLAYLIST_ARM_MEASUREMENTS)):
        [line] = [l for l in ddl.splitlines() if l.strip().startswith(column + " ")]
        assert set(line.split("--")[1].strip().split("|")) == values


def test_short_link_status_values_are_the_persisted_strings():
    """short_link_recommendations.status (Slice 2 S2.4), as the migration's
    comment lists them, and its default."""
    assert sv.ALL_SHORT_LINK_STATUSES == {"pending", "set", "not_chosen", "dismissed"}
    [line] = [l for l in SHORT_LINKS_SQL.read_text().splitlines()
              if l.strip().startswith("status ")]
    assert set(line.split("--")[1].strip().split("|")) == sv.ALL_SHORT_LINK_STATUSES
    assert f"default '{sv.ShortLinkStatus.PENDING}'" in line


def test_the_experiment_decision_source_is_labelled_in_the_proposals_card():
    """playlist_proposals.decision_source `experiment` (S2.1), and its mirror,
    DECIDED_BY in channel.html: unlabelled, the card would show the raw string."""
    assert sv.PlaylistProposalSource.EXPERIMENT == "experiment"
    block = re.search(r"const DECIDED_BY = \{(.*?)\n  \};", CHANNEL_HTML.read_text(), re.S)
    assert block, "DECIDED_BY not found in channel.html"
    assert re.search(r"^\s*experiment:\s*'Playlist test',", block.group(1), re.M)
