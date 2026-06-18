-- Track the last full (snippet-rebuilding) sync so autopilot can run an
-- incremental sync most ticks and a full pass only every few days.
alter table channels add column if not exists last_full_synced_at timestamptz;
