-- Phase 2 Track 1 (Piece 2) — exclude in-measurement videos from the picker.
--
-- Redefines next_audit_candidate to stay faithful to app/autopilot.py::
-- _next_video_for_channel after Track 1 Step 2.1: a video whose LATEST audit is
-- mid-measurement (measurement_status in awaiting_window/measuring) is not a
-- valid pick — re-auditing it would change the packaging under an in-flight CTR
-- experiment and confound the verdict (CIL §1.7). This is ADDITIVE to the
-- existing status guard; measurement_status is a separate lifecycle column
-- (CIL §1.1), never merged with status.
--
-- Both picker paths must move together (config.py:39-45 parity contract).
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
