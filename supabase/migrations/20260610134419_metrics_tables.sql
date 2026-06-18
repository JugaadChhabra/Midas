-- Phase 0 sensor storage (CIL §0.3, PO §Sensor).
--
-- Shaped by the live probe on 2026-06-10 (channel UCr5-YUqBiW7PUmeAtxUWuRg).
--
-- Spec deltas absorbed here (per plan.md "0 absorbs the fix before any
-- abstraction is written"):
--
--   1. videoThumbnailImpressions / videoThumbnailImpressionsClickRate are not
--      available via the on-demand Analytics API; they only ship via the bulk
--      Reporting API. The `impressions` and `ctr` columns are kept (nullable)
--      so a future Reporting-API ingestion task can backfill without ALTER.
--      The Loop 0 metrics_poll job leaves them NULL for now.
--
--   2. CIL §0.3 declared `avg_view_duration_sec FLOAT`. Live API column type
--      is INTEGER (seconds). Stored as INTEGER to preserve fidelity.
--
--   3. PO §Sensor declared `avg_time_in_playlist_min FLOAT`. Live API column
--      type is INTEGER and the unit is SECONDS, not minutes. Column renamed
--      to `avg_time_in_playlist_sec INTEGER`.
--
--   4. PO §Sensor's `playlistStarts` etc. are documented as web-only counts —
--      stored verbatim; trend/relative comparison is the only valid use.
--
--   5. PO §Sensor's isCurated filter is now fully deprecated (live API rejects
--      the filter); not represented in the schema.

create table if not exists video_metrics (
    id                      bigserial primary key,
    video_id                text        not null references videos(id) on delete cascade,
    channel_id              text        not null references channels(id),
    window_start            date        not null,
    window_end              date        not null,
    -- Reporting API backfill columns (nullable until that ingestion exists).
    impressions             bigint,
    ctr                     float,
    -- Analytics API on-demand columns (populated by metrics_poll).
    views                   bigint,
    est_minutes_watched     bigint,
    avg_view_duration_sec   integer,
    avg_view_pct            float,
    is_pre_change           boolean     default false,
    fetched_at              timestamptz default now(),
    unique (video_id, window_start, window_end)
);
create index if not exists video_metrics_channel_idx on video_metrics(channel_id);
create index if not exists video_metrics_video_window_idx on video_metrics(video_id, window_end desc);

create table if not exists playlist_metrics (
    id                              bigserial primary key,
    -- Not FK'd to playlists(id): playlists table is being extended in Phase 1B,
    -- and member playlists may exist on YouTube before we've synced them.
    playlist_id                     text        not null,
    channel_id                      text        not null references channels(id),
    window_start                    date        not null,
    window_end                      date        not null,
    playlist_starts                 bigint,
    views_per_playlist_start        float,
    avg_time_in_playlist_sec        integer,
    playlist_views                  bigint,
    playlist_est_minutes_watched    bigint,
    is_pre_change                   boolean     default false,
    fetched_at                      timestamptz default now(),
    unique (playlist_id, window_start, window_end)
);
create index if not exists playlist_metrics_channel_idx on playlist_metrics(channel_id);
create index if not exists playlist_metrics_playlist_window_idx on playlist_metrics(playlist_id, window_end desc);
