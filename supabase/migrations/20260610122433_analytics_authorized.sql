-- Phase 0 (sensor foundation) — re-consent grant tracking.
-- Per-channel flag indicating the channel has re-authorized with the
-- yt-analytics.readonly scope. Loop 0 polling skips channels where this is false.

alter table channels
  add column if not exists analytics_authorized boolean default false;
