-- Phase 1B Step B — tier-2 health scoring storage (PO §Control loop,
-- "secondary: playlist-source views to members"). Closes Phase 0 Gap 6 +
-- Phase 1B's tier_2_pending honesty caveat.
--
-- One row per (member video, source playlist) per weekly window.
-- Populated by the metrics_poll extension (Step B) for channels with
-- playlist_health_enabled=true. score_channel aggregates by playlist_id +
-- joins back to playlist_metrics to emit the tier-2 rationale fields.
--
-- Cardinality: 500 videos × ~30 source playlists × weekly windows ≈ 15k
-- rows/week for a large channel (per PHASE_1B_PLAN.md §9.3). UNIQUE
-- constraint keeps upserts idempotent so daily re-runs don't dupe.
--
-- playlist_id is intentionally FK-free for the same reason as
-- playlist_metrics (Gap 5): the source playlist surfaced by Analytics may
-- be a non-Midas-owned playlist (e.g. another creator's playlist that
-- happens to include our video). Forcing FK to playlists(id) would drop
-- those rows.

create table if not exists video_traffic_source_playlist (
    id              bigserial primary key,
    video_id        text        not null references videos(id) on delete cascade,
    playlist_id     text        not null,
    channel_id      text        not null references channels(id),
    window_start    date        not null,
    window_end      date        not null,
    views           bigint,
    fetched_at      timestamptz default now(),
    unique (video_id, playlist_id, window_start, window_end)
);

create index if not exists vtsp_channel_idx     on video_traffic_source_playlist(channel_id);
create index if not exists vtsp_playlist_window on video_traffic_source_playlist(playlist_id, window_end desc);
create index if not exists vtsp_video_window    on video_traffic_source_playlist(video_id, window_end desc);
