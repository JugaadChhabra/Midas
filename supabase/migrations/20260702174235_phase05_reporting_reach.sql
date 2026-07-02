-- Phase 0.5 — Reporting API reach ingestion (closes PHASE_0_GAPS.md Gap 1).
--
-- Shaped by the live probe on 2026-07-02 (channel UC8KjoL0Z9mTHKqB6gFutkJw,
-- job 724b9fa7-ab5c-4c21-b45a-be936112bef1, report 20159147398). Verified CSV
-- shape for report type `channel_reach_basic_a1`:
--
--     date,channel_id,video_id,video_thumbnail_impressions,video_thumbnail_impressions_ctr
--     20260629,UC8KjoL0Z9mTHKqB6gFutkJw,-3-PeYrPZUM,13,0.15384615384615385
--
-- Storage decision (flips the earlier lean toward backfilling video_metrics
-- directly — documented per the no-silent-drift rule):
--
--   The probe surfaced two facts that make a raw DAILY table the source of
--   truth, with video_metrics backfill DERIVED from it:
--
--   1. Reports arrive erratically and out of order — a report for data-day
--      2026-05-27 was generated on 2026-06-28. Upserting weekly windows
--      directly from such a stream would churn and could never certify a
--      window as complete.
--   2. Loop 1's baseline capture (CIL §1.2) needs arbitrary trailing windows
--      anchored at APPLY TIME, which weekly-aligned video_metrics windows
--      cannot serve. Daily grain serves any window.
--
--   video_metrics.impressions / ctr (reserved nullable in Phase 0) are then
--   backfilled by the reporting poll ONLY for windows whose every data-day
--   is covered by an ingested report — never partially.

create table if not exists video_reach_daily (
    id            bigserial primary key,
    -- Not FK'd to videos(id): the reach CSV covers EVERY video on the channel,
    -- including ones we have not synced (or that sync later). Same FK-free
    -- rationale as playlist_metrics.playlist_id (Gap 5 decision).
    video_id      text        not null,
    channel_id    text        not null references channels(id),
    date          date        not null,
    impressions   bigint      not null,
    -- Fraction 0..1 straight from the CSV (0.1538 = 15.38%), NOT a percent.
    ctr           double precision not null,
    -- Provenance: the Reporting API report this row came from. YouTube can
    -- reissue a corrected report for the same data-day; the upsert on
    -- (video_id, date) means the latest ingest wins.
    report_id     text,
    fetched_at    timestamptz default now(),
    unique (video_id, date)
);
create index if not exists video_reach_daily_channel_date_idx on video_reach_daily(channel_id, date desc);

-- Ingest ledger — which Reporting API report files have been processed.
-- Reports arrive out of order and can be reissued (same data-day, new report
-- id), so "have I seen this report id" is the only reliable dedup key.
-- data_date doubles as the coverage record used to certify video_metrics
-- windows as fully-covered before backfilling impressions/ctr.
create table if not exists reporting_reports_ingested (
    -- Assumption (observed, not documented by Google): report ids are
    -- globally unique numeric strings, not per-job scoped. The 2026-07-02
    -- probe saw non-overlapping id ranges across jobs. If that ever proves
    -- wrong, the PK must become (job_id, report_id).
    report_id     text        primary key,
    job_id        text        not null,
    channel_id    text        not null references channels(id),
    -- The data-day this report covers (report startTime, date part).
    data_date     date        not null,
    row_count     integer     not null default 0,
    ingested_at   timestamptz default now()
);
create index if not exists reporting_ingested_channel_date_idx on reporting_reports_ingested(channel_id, data_date desc);
