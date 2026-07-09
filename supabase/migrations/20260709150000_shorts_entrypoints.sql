-- Shorts entry points (docs/superpowers/specs/2026-07-09-shorts-entrypoints-design.md).
-- upload_cap: max clips to auto-upload for a job (null = upload all). The manual
-- per-video button sets null; autopilot (Phase B2) sets a small integer.
-- autopilot_generated: marks jobs created by the autopilot shorts action (Phase B2),
-- added here so the autopilot phase needs no further migration.
alter table shorts_jobs add column if not exists upload_cap int;
alter table shorts_jobs add column if not exists autopilot_generated boolean not null default false;
