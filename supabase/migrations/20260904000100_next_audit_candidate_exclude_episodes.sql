-- Exclude Shows "episodes" from the autopilot audit picker.
--
-- The SEO flow writes nursery-rhyme write-ups only; episodes are a different
-- content type (see app/content_type.py). Redefines next_audit_candidate to
-- skip any video flagged videos.is_episode, so the autopilot never spends a
-- tick picking one only for audit_video's guard to refuse it.
--
-- `is not true` so NULL (not yet classified / backfilled) is treated as
-- non-episode — the pre-backfill state audits exactly as before.
--
-- Both picker paths must move together (config.py parity contract); the
-- in-app fallback in app/autopilot.py::_next_video_for_channel applies the
-- same is_episode skip. This carries forward every earlier guard
-- (privacy_status, latest-audit status, measurement_status).
-- STABLE + read-only; callable only by service_role (the app).
create or replace function next_audit_candidate(p_channel_id text)
returns table(id text, is_short boolean, privacy_status text)
language sql
stable
as $$
  with latest as (
    select distinct on (a.video_id) a.video_id, a.status, a.measurement_status
    from audits a
    order by a.video_id, a.created_at desc
  )
  select v.id, v.is_short, v.privacy_status
  from videos v
  left join latest la on la.video_id = v.id
  where v.channel_id = p_channel_id
    and (v.privacy_status is null or v.privacy_status = 'public')
    and v.is_episode is not true
    and (la.status is null
         or la.status not in
            ('applied', 'pending', 'quarantined', 'blocked_test_and_compare', 'shadow_pending'))
    and (la.measurement_status is null
         or la.measurement_status not in ('awaiting_window', 'measuring'))
  order by v.published_at desc, v.id
  limit 1;
$$;

revoke execute on function next_audit_candidate(text) from public;
grant  execute on function next_audit_candidate(text) to service_role;
