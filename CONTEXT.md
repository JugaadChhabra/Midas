# Midas — domain language

The words this codebase uses, and what they mean precisely. Added to when a term
gets resolved during design work, not written up front.

## Reach

Impressions and click-through rate per video per day, from YouTube's **Reporting
API** (bulk daily CSV report jobs), landed in `video_reach_daily`.

Not to be confused with the **on-demand Analytics API**, which supplies views and
retention into `video_metrics`. They are separate sensors with separate quota
pools, separate freshness lags, and separate ingestion jobs. Reach is the only
source of CTR: the impressions metrics do not exist on the Analytics query API at
all (see `docs/PHASE_0_GAPS.md` Gap 1).

Owner: `app/reach.py` for the facts, `app/reporting_poll.py` for the ingestion.

## Data-day

One calendar day of reach data for one channel. The atom of the reach pipeline.

Data-days roll over on **America/Los_Angeles**, while audit timestamps are UTC —
which is why comparisons drop the data-days adjacent to an apply date
(`reach.ROLLOVER_SLOP_DAYS`).

A data-day's report arrives **1–6 days after the day itself** (2026-07-02 probe),
so "today" and "the most recent day we could know about" are never the same date.

## Coverage

The set of data-days a channel has an ingested reach report for.

Covered means *a report was ingested for that day* — nothing about whether the
impressions were non-trivial. Signal strength is a separate, later, per-video
judgement (`MIN_IMPRESSIONS`, applied by `measurement`).

## Window

An inclusive (start, end) pair of data-days that a comparison is measured over.

An audit applied on day D compares a **pre** window with a **post** window, each
`MEASUREMENT_WINDOW_DAYS` long, shifted outward by the rollover slop —
`reach.window_for`. Single-video A/B is impossible, so a video's own recent past
is the control (CIL Decision 3).

## Frontier

The most recent covered data-day. What channel-level questions anchor to, because
`today` is always ahead of what any report could cover.

## Certification

Whether a channel's reach coverage is complete enough to start measuring it —
`reach.certify`, enforced when `measurement_enabled` is switched on.

Distinct from **measurability**, which is per-audit: whether *this* audit's two
windows are fully covered yet. Certification is the channel-level gate;
measurability is what `plan_measurement` asks each evaluation pass. They must
agree about how many data-days a comparison needs, which is why both are
expressed through `app/reach.py`.

## Measurement status vs outcome decision

Two persisted columns on `audits`, deliberately separate:

- **measurement status** — what we learned: `awaiting_window`, `measuring`,
  `win`, `neutral`, `regression`, `not_applicable`.
- **outcome decision** — what was done about it: `none`, `kept`, `reverted`,
  `redo_queued`.

`not_applicable` means *never measured* (dormant video, missing timestamp).
`neutral` means *measured, and flat*. The distinction is load-bearing: neutral
counts toward the win rate that promotes prompt versions, and `not_applicable`
does not.

These string values are persisted and mirrored in SQL and JS. They may not be
renamed — see `app/status_vocab.py` and `tests/test_status_vocab.py`.

## Readout

One audit and what its verdict means, as a single row: the relative CTR change
(raw fraction and percentage), the pre/post window rates, which levers it moved
(title / description / tags), and how long since it was applied. The
verdict-derived fields read None until the measurement window closes, so a
Readout describes an audit still awaiting measurement as readily as a measured
one.

The **prompt loop** (`reflection`) and the **performance page** (`performance`)
both read audits this way. The derivation is shared — `app.verdicts.readout` —
so the two surfaces cannot describe the same audit differently; only the wire
key-names stay at each edge (`desc_changed` in the prompt vs
`description_changed` in the performance API, deliberately, see `app/verdicts.py`).

Recency is carried as raw `days_since_apply`, not a flag: what counts as recent
is a caller's policy (the loop's 14-day window), not a property of the verdict.
Owner: `app/verdicts.py` (`Readout`, `readout`, `lever_average`).

## House format

The fixed metadata contract every audit produces: the bilingual title template,
the ordered 5-block description skeleton, the tag rule, the hashtag/title/tag
ceilings, and the JSON shape the model must return. It is one contract seen from
two sides — the **prose** three prompts show the model (`audits.DEFAULT_PROMPT`
for the auditor, `audits.elaborate` for prompt generation, `reflection`'s
meta-prompt for prompt improvement) and the **enforcement** applied to what
comes back (`AuditSuggestion.rejection` / `cap_description_hashtags`).

Both sides read one referent so they cannot disagree: the ceilings are constants
and `house_format_spec()` renders them into the prose the prompts embed. Each
prompt supplies only its own framing around the rendered block; the numbers a
prompt quotes are the numbers `rejection()` checks. Owner:
`app/audit_suggestion.py` (`house_format_spec`, the ceiling constants,
`AuditSuggestion`).
