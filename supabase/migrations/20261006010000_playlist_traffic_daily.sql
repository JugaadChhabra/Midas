-- Phase B · B1b (#31) — traffic-source ingestion, playlist half.
--
-- Spec Part 2 §7 / Part 3 B1 (P6). Rows come from the Reporting API report type
-- `playlist_traffic_source_a2` (16 columns, docs/PHASE_A_FINDINGS.md A1.1):
--
--     date,channel_id,playlist_id,video_id,live_or_on_demand,subscribed_status,
--     country_code,traffic_source_type,traffic_source_detail,views,engaged_views,
--     watch_time_minutes,average_view_duration_seconds,playlist_starts,
--     playlist_saves_added,playlist_saves_removed
--
-- summed over country_code, subscribed_status and live_or_on_demand before storage.
-- engaged_views, the average and the playlist_saves_* columns are not stored.
-- Needs 20261006000000 first (reporting_reports_ingested.report_type).

create table if not exists playlist_traffic_daily (
    -- Not in the spec's column list: app/rows.py pages every read in `id` order,
    -- so the table needs one.
    id                  bigserial primary key,
    -- Not FK'd to playlists(id) or videos(id): the report covers playlists and
    -- videos we may not have synced. Same rationale as
    -- video_traffic_source_daily.video_id and video_traffic_source_playlist.playlist_id.
    playlist_id         text             not null,
    video_id            text             not null,
    channel_id          text             not null references channels(id),
    date                date             not null,
    -- YouTube's numeric traffic-source code. Names live in code:
    -- app/reporting_client.py TRAFFIC_SOURCE_TYPES.
    source_type         smallint         not null,
    -- Referring video / playlist id or search term; '' when the report has none.
    source_detail       text             not null default '',
    views               bigint           not null,
    playlist_starts     bigint           not null,
    watch_time_minutes  double precision not null,
    -- The report this row came from. A restated data-day (A1.1 saw this report
    -- restate 09-22, 09-25 and 09-28) replaces the day's rows
    -- (app/reporting_poll.py replace_data_day); it never adds to them.
    report_id           text             not null,
    ingested_at         timestamptz      default now(),
    unique (playlist_id, video_id, date, source_type, source_detail)
);
create index if not exists playlist_traffic_daily_channel_date_idx
    on playlist_traffic_daily (channel_id, date desc);

grant all on playlist_traffic_daily to service_role;
grant all on sequence playlist_traffic_daily_id_seq to service_role;
