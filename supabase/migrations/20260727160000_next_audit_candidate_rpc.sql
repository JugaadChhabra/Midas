-- Server-side autopilot picker — the egress fix.
--
-- The autopilot tick (every AUTOPILOT_TICK_SECONDS) pulled a channel's ENTIRE
-- videos list + ALL its audits into the app on every qualifying tick, just to
-- pick the single next video to audit. On big channels that shipped hundreds of
-- KB per tick, hundreds of times a day — the dominant Supabase egress source.
-- This function computes the pick in Postgres and returns exactly ONE row.
--
-- Faithful to app/autopilot.py::_next_video_for_channel:
--   * candidate = PUBLIC video (privacy_status null or 'public'),
--   * whose LATEST audit status is NOT one of the "already handled" states
--     (applied/pending/quarantined/blocked_test_and_compare/shadow_pending) —
--     or which has no audit at all,
--   * newest published first. Tie-break by id so the pick is deterministic and
--     matches the in-app path (which now also orders by published_at desc, id).
--
-- STABLE + read-only; callable only by service_role (the app).
create or replace function next_audit_candidate(p_channel_id text)
returns table(id text, is_short boolean, privacy_status text)
language sql
stable
as $$
  with latest as (
    select distinct on (a.video_id) a.video_id, a.status
    from audits a
    order by a.video_id, a.created_at desc
  )
  select v.id, v.is_short, v.privacy_status
  from videos v
  left join latest la on la.video_id = v.id
  where v.channel_id = p_channel_id
    and (v.privacy_status is null or v.privacy_status = 'public')
    and (la.status is null
         or la.status not in
            ('applied', 'pending', 'quarantined', 'blocked_test_and_compare', 'shadow_pending'))
  order by v.published_at desc, v.id
  limit 1;
$$;

revoke execute on function next_audit_candidate(text) from public;
grant  execute on function next_audit_candidate(text) to service_role;
