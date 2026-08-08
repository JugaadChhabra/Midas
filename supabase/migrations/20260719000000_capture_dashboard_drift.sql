-- Capture three columns that exist in the hosted database but were never
-- written as a migration.
--
-- Found while standing up self-hosted Postgres: applying the ledger from
-- scratch failed at 20260720120000_dashboard_summary_rpc.sql with
-- `column "is_short" does not exist`. All three were added directly through the
-- Supabase dashboard's SQL editor, so the ledger and the live schema had
-- silently diverged — invisible while there was only ever one database.
--
-- Timestamped 20260719 so it lands before 20260720120000, the first migration
-- that references is_short. Nothing references the other two from SQL; they are
-- read by the app (audit_video's shorts prompt selection, and the sync_shorts
-- channel flag).
--
-- Types and nullability are taken from the live data, not guessed:
--   videos.is_short            49144/49144 non-null booleans
--   channels.sync_shorts       2 booleans, 11 NULL -> nullable, no default
--   audit_configs.shorts_prompt 1 row, NULL       -> nullable text

alter table videos
    add column if not exists is_short boolean;

alter table channels
    add column if not exists sync_shorts boolean;

alter table audit_configs
    add column if not exists shorts_prompt text;
