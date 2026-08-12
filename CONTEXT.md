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
