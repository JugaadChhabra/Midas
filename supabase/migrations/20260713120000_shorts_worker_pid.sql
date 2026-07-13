-- Parallel shorts queue: track which OS process is running a job so the
-- startup reaper can kill an orphaned worker after a mid-job restart.
alter table shorts_jobs
    add column if not exists worker_pid  integer,
    add column if not exists started_at  timestamptz;
