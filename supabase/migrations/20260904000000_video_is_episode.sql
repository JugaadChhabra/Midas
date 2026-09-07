-- Add videos.is_episode — the denormalised content-type flag the autopilot
-- picker filters on so the SEO flow never audits Shows "episodes" (the flow
-- writes nursery-rhyme write-ups only).
--
-- The Data API exposes no episode flag, so the value is classified from the
-- title / tag pattern in app/content_type.py::is_episode and stamped at sync
-- (mirrors is_short: authoritative logic in Python, denormalised here so the
-- SQL picker can filter cheaply). Existing rows are backfilled by
-- scripts/backfill_is_episode.py.
--
-- Nullable, no default: NULL means "not yet classified" and is treated as
-- non-episode by every reader (`is not true`), so shipping this before the
-- backfill changes nothing.

alter table videos
    add column if not exists is_episode boolean;
