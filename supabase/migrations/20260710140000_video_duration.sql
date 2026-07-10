-- Persist video length in seconds so the autopilot shorts picker can hard-cap
-- source duration (< 4 min), excluding compilations. Populated by the full-sync
-- path (app/sync.py); NULL on rows not yet re-synced (safely excluded by the
-- picker's `.lt(...)`). is_short remains the derived <=180s boolean.
alter table videos add column if not exists duration_seconds int;
