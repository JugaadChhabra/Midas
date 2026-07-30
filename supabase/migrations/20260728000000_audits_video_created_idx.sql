-- Speed up dashboard_summary()'s latest-audit-per-video lookup.
--
-- dashboard_summary() (20260720120000_dashboard_summary_rpc.sql) computes the
-- latest audit per video with:
--     select distinct on (video_id) video_id, status
--     from audits order by video_id, created_at desc
-- The only prior audits indexes are audits(video_id) and audits(status), neither
-- of which provides the (video_id, created_at desc) ordering that DISTINCT ON
-- needs — so Postgres sorted the whole audits table on every /dashboard call.
-- As audits grew this crossed Supabase's statement timeout (57014), the RPC
-- errored, and the endpoint fell back to the ~2 MB in-app legacy aggregation.
--
-- This composite index lets the DISTINCT ON become an index scan instead of a
-- full sort, bringing the RPC back under the timeout and restoring the
-- ~100x egress cut the RPC path exists for.
create index if not exists audits_video_created_idx
  on audits (video_id, created_at desc);
