-- Phase B · B1 (#30) — traffic-source ingestion, video half.
--
-- Spec Part 2 §7 / Part 3 B1 (P6). Rows come from the Reporting API report type
-- `channel_traffic_source_a3` (15 columns, docs/PHASE_A_FINDINGS.md A1.1):
--
--     date,channel_id,video_id,live_or_on_demand,subscribed_status,country_code,
--     traffic_source_type,traffic_source_detail,views,engaged_views,watch_time_minutes,
--     average_view_duration_seconds,average_view_duration_percentage,red_views,
--     red_watch_time_minutes
--
-- summed over country_code, subscribed_status and live_or_on_demand before storage
-- (≈52k raw rows per Marathi channel-day). The averages and the red_* columns are
-- not stored.

create table if not exists video_traffic_source_daily (
    -- Not in the spec's column list: app/rows.py pages every read in `id` order,
    -- so the table needs one.
    id                  bigserial primary key,
    -- Not FK'd to videos(id): the report covers every video on the channel,
    -- including ones we have not synced (A1.1: 74 of 1,004 ids). Same rationale
    -- as video_reach_daily.video_id.
    video_id            text             not null,
    channel_id          text             not null references channels(id),
    date                date             not null,
    -- YouTube's numeric traffic-source code. Names live in code:
    -- app/reporting_client.py TRAFFIC_SOURCE_TYPES.
    source_type         smallint         not null,
    -- Referring video / playlist id or search term; '' when the report has none.
    source_detail       text             not null default '',
    views               bigint           not null,
    engaged_views       bigint           not null,
    watch_time_minutes  double precision not null,
    -- The report this row came from. A restated data-day replaces the day's rows
    -- (app/reporting_poll.py replace_data_day); it never adds to them.
    report_id           text             not null,
    ingested_at         timestamptz      default now(),
    unique (video_id, date, source_type, source_detail)
);
create index if not exists video_traffic_source_daily_channel_date_idx
    on video_traffic_source_daily (channel_id, date desc);

grant all on video_traffic_source_daily to service_role;
grant all on sequence video_traffic_source_daily_id_seq to service_role;

-- The ingest ledger now holds more than one report type per channel, and its
-- data_date doubles as reach coverage (app/reach.py coverage). Without a type, a
-- traffic report for a day would count as reach coverage for that day and let the
-- video_metrics backfill certify a window whose reach never landed. Every row
-- before this migration is a reach report.
alter table reporting_reports_ingested
    add column if not exists report_type text not null default 'channel_reach_basic_a1';
