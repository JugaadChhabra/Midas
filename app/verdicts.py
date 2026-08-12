"""What Loop 1 decided about an audit, and how to read it back.

A verdict is the terminal outcome of measuring one applied audit: a status
(win / neutral / regression / not_applicable), the decision taken about it, and
the evidence behind both. `measurement.judge_reach` produces it; it is persisted
as `audits.measurement_status` plus the `audits.measurement_result` JSON.

That JSON had no owner. Four readers destructured it by string key — two in
performance, two in reflection — each re-deriving the same numbers, and the
failure mode was silent in a specific way: `ctr_delta_relative` is legitimately
absent on a neutral verdict (a video under the impressions floor has no
comparable rate), so a reader that looked for the wrong key would find None,
report "no delta", and be indistinguishable from a reader working correctly.
Rename that key in the writer and every median on the fleet quietly becomes
None, with the prompt loop concluding "not enough evidence" rather than failing.

So this module owns both directions: the writer builds through `result_of`, the
readers parse through `from_audit`. One definition, one place to change.

Units: raw fractions, as stored. A relative CTR change of half is 0.5 here, not
50.0 — percentages are a presentation concern and belong at the edge that
renders them. Aggregates are computed on unrounded values and rounded once at
the end, which is why the rollups here return what they do.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from app.status_vocab import AuditStatus, MEASURED_STATUSES, MeasurementStatus


# ── The shape ─────────────────────────────────────────────────────────────

#: Keys in `audits.measurement_result`. Named here because the writer and every
#: reader must agree, and a mismatch does not raise (see the module docstring).
CTR_DELTA = "ctr_delta_relative"
PRE_WINDOW = "pre_window"
POST_WINDOW = "post_window"
RATIONALE = "rationale"

#: The canonical levers an audit can move. Response keys at the edges differ
#: (`description_changed` in the performance API, `desc_changed` in reflection's
#: prompt) and deliberately keep their spellings — only the derivation is shared.
TITLE = "title"
DESCRIPTION = "description"
TAGS = "tags"
ALL_LEVERS = (TITLE, DESCRIPTION, TAGS)


@dataclass(frozen=True)
class Verdict:
    """A terminal measurement outcome and the evidence behind it."""

    status: str
    outcome: str
    result: dict

    @property
    def ctr_delta(self) -> float | None:
        """Relative CTR change as a fraction, or None if there is no signal.

        None is a real answer, not a missing one: a verdict whose post window
        fell under the impressions floor is neutral with nothing to compare.
        """
        return self.result.get(CTR_DELTA)

    @property
    def pre_ctr(self) -> float | None:
        return (self.result.get(PRE_WINDOW) or {}).get("ctr")

    @property
    def post_ctr(self) -> float | None:
        return (self.result.get(POST_WINDOW) or {}).get("ctr")

    @property
    def rationale(self) -> str | None:
        return self.result.get(RATIONALE)


def result_of(*, pre: tuple[str, str], post: tuple[str, str],
              pre_imp: int, pre_ctr: float | None,
              post_imp: int, post_ctr: float | None,
              min_impressions: int, win_threshold: float,
              regression_threshold: float, evaluated_at: str,
              attribution: str = "bundle") -> dict:
    """The evidence half of a verdict, ready to persist.

    The thresholds are recorded alongside the numbers so a later change to them
    cannot silently reinterpret an old verdict.
    """
    return {
        PRE_WINDOW: {"start": pre[0], "end": pre[1],
                     "impressions": pre_imp, "ctr": pre_ctr},
        POST_WINDOW: {"start": post[0], "end": post[1],
                      "impressions": post_imp, "ctr": post_ctr},
        "min_impressions": min_impressions,
        "win_threshold": win_threshold,
        "regression_threshold": regression_threshold,
        "evaluated_at": evaluated_at,
        # v1 is bundle-level attribution (title + description + tags moved
        # together) — a CIL open-question decision. Recorded so Loop 2's
        # distiller can say so rather than implying causation.
        "attribution": attribution,
    }


def from_audit(audit: dict) -> Verdict | None:
    """The verdict on an audit row, or None if it has not been measured.

    Reads `measurement_status` and `measurement_result`; a row still in flight
    (or never measured) has no verdict to give.

    `.outcome` is only populated when the row includes `outcome_decision` —
    every current reader selects the status and result alone, because what was
    DONE about a verdict is a separate question from what the verdict was.
    """
    status = audit.get("measurement_status")
    if status not in MEASURED_STATUSES:
        return None
    return Verdict(status, audit.get("outcome_decision"),
                   audit.get("measurement_result") or {})


# ── Evidence ──────────────────────────────────────────────────────────────

def is_evidence(audit: dict) -> bool:
    """Does this audit's verdict count as evidence about the prompt?

    Measured status alone — deliberately NOT also `status='applied'`.

    Two of the three rollups used to add that filter, and it biases the result in
    one direction. Reverting is what an operator does to a BAD outcome, so
    excluding reverted audits systematically drops the worst evidence and
    flatters the prompt version that produced it. A prompt that wrote a title
    which measurably lost CTR produced a regression; undoing the damage is
    remediation, not erasure.

    Distinct from live state: `performance`'s view-count columns keep their own
    `applied` filter, because a reverted video's before/after view stats describe
    metadata that is no longer there.
    """
    return audit.get("measurement_status") in MEASURED_STATUSES


def evidence(audits) -> list[Verdict]:
    """Every verdict in `audits` that counts as evidence, parsed."""
    return [v for v in (from_audit(a) for a in audits) if v is not None]


# ── Rollups ───────────────────────────────────────────────────────────────
#
# All three aggregate on RAW values and round once, at the end. `performance`
# used to round each delta to one decimal place before taking the median, which
# is a small error that compounds with even-sized cohorts — and, more to the
# point, meant the number the UI showed and the number the prompt loop acted on
# were computed differently.

def win_rate(statuses) -> float | None:
    """Share of measured verdicts that won, as a percentage. None if empty.

    Neutral counts in the denominator: it is a measured outcome, not an absent
    one. `not_applicable` never reaches here — it is not evidence.
    """
    statuses = list(statuses)
    if not statuses:
        return None
    wins = sum(1 for s in statuses if s == MeasurementStatus.WIN)
    return round(100.0 * wins / len(statuses), 1)


def median_ctr_delta_pct(deltas) -> float | None:
    """Median relative CTR change as a percentage. None if nothing comparable.

    `deltas` are raw fractions; None entries are dropped rather than counted as
    zero. A verdict with no delta is a verdict with nothing to compare, which is
    not the same as one that measured no change.
    """
    usable = [d for d in deltas if d is not None]
    if not usable:
        return None
    return round(statistics.median(usable) * 100.0, 1)


def distribution(statuses) -> dict:
    """Counts per measured status, plus the total."""
    statuses = list(statuses)
    counts = {s: sum(1 for x in statuses if x == s) for s in MEASURED_STATUSES}
    return {**counts, "total": len(statuses)}


def rollup(verdicts_: list[Verdict]) -> dict:
    """win_rate / median_ctr_delta_pct / distribution over a set of verdicts."""
    return {
        "win_rate": win_rate(v.status for v in verdicts_),
        "median_ctr_delta_pct": median_ctr_delta_pct(v.ctr_delta for v in verdicts_),
        "distribution": distribution(v.status for v in verdicts_),
    }


# ── Levers ────────────────────────────────────────────────────────────────

def levers(audit: dict) -> frozenset[str]:
    """Which levers this audit actually moved.

    Derived by diffing the applied suggestion against what was there before, so
    an audit that "changed the title" to the same string does not count. Bundle
    attribution means a verdict cannot be apportioned between these — the set
    says what moved together, not which one earned the result.
    """
    moved = set()
    if (audit.get("title_before") or "") != (audit.get("suggested_title") or ""):
        moved.add(TITLE)
    if (audit.get("description_before") or "") != (audit.get("suggested_description") or ""):
        moved.add(DESCRIPTION)
    if list(audit.get("tags_before") or []) != list(audit.get("suggested_tags") or []):
        moved.add(TAGS)
    return frozenset(moved)
