-- dashboard_summary(): stop inventing a 7-day view delta for unmeasured audits.
--
-- The apply path no longer collects view/like/comment counts at apply time, so
-- audits.view_count_at_apply is NULL from now on. This function summed
-- `cur_views - coalesce(view_count_at_apply, 0)`, which for a NULL baseline is the
-- video's whole lifetime view count reported as growth the audit produced.
--
-- The Python readers were fixed in the same change (app/performance.py,
-- app/dashboard.py::_delta_views_7d) but this is the path that actually runs:
-- _compute_dashboard tries _aggregate_rpc() first and only falls back to
-- _aggregate_legacy(), so fixing the Python alone left the live number wrong.
--
-- Redefinition only — everything else is carried over verbatim from
-- 20260813090000_dashboard_summary_quarantined.sql.

create or replace function dashboard_summary()
returns jsonb
language sql
stable
as $$
  with pub as (
    select id, channel_id, is_short, coalesce(view_count, 0) as view_count
    from videos
    where privacy_status is null or privacy_status = 'public'
  ),
  latest as (
    select distinct on (video_id) video_id, status
    from audits
    order by video_id, created_at desc
  ),
  vcount as (
    select channel_id,
           count(*)                              as video_count,
           count(*) filter (where not is_short)  as regular_count,
           count(*) filter (where is_short)      as shorts_count
    from pub
    group by channel_id
  ),
  acount as (
    select v.channel_id,
           count(*) filter (where not v.is_short)           as audited_regular,
           count(*) filter (where v.is_short)               as audited_shorts,
           count(*) filter (where l.status = 'pending')     as pending_count,
           count(*) filter (where l.status = 'quarantined') as quarantined_count,
           count(*) filter (where l.status = 'applied')     as applied_latest
    from latest l
    join pub v on v.id = l.video_id
    group by v.channel_id
  ),
  applied as (
    select v.channel_id, a.applied_at, a.view_count_at_apply,
           coalesce(v.view_count, 0) as cur_views
    from audits a
    join videos v on v.id = a.video_id
    where a.status = 'applied'
  ),
  days as (
    select generate_series(
      (date_trunc('day', now() at time zone 'utc'))::date - 6,
      (date_trunc('day', now() at time zone 'utc'))::date,
      interval '1 day')::date as d
  ),
  byday as (
    select v.channel_id,
           (a.applied_at at time zone 'utc')::date as d,
           count(*) as n
    from audits a
    join videos v on v.id = a.video_id
    where a.status = 'applied'
      and a.applied_at >= (date_trunc('day', now() at time zone 'utc') - interval '6 days')
    group by 1, 2
  ),
  beat as (
    -- cross join channels x days so a channel with no applies still gets seven
    -- slots; without it the strip would be shorter for quiet channels and the
    -- bars would stop lining up across rows.
    select c.id as channel_id,
           jsonb_agg(coalesce(b.n, 0) order by d.d) as applied_by_day
    from channels c
    cross join days d
    left join byday b on b.channel_id = c.id and b.d = d.d
    group by c.id
  ),
  apcount as (
    select channel_id,
      count(*) filter (
        where applied_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'
      ) as applied_today,
      count(*) filter (where applied_at >= now() - interval '7 days') as applied_7d,
      count(*) as applied_total,
      -- Unmeasured audits are EXCLUDED, not coalesced to zero. Apply-time stats
      -- are no longer collected, so view_count_at_apply is NULL on new audits, and
      -- `- coalesce(..., 0)` made this the sum of those videos' ENTIRE lifetime
      -- view counts — one freshly-applied back-catalogue video could swamp the
      -- fleet's real 7-day movement and read as a huge win. A stored 0 is a real
      -- baseline and still counts; only NULL means nobody measured.
      coalesce(sum(cur_views - view_count_at_apply)
               filter (where applied_at >= now() - interval '7 days'
                         and view_count_at_apply is not null), 0) as delta_views_7d
    from applied
    group by channel_id
  )
  select jsonb_build_object(
    'channels', coalesce((
      select jsonb_agg(jsonb_build_object(
        'channel_id',        c.id,
        'video_count',       coalesce(vc.video_count, 0),
        'regular_count',     coalesce(vc.regular_count, 0),
        'shorts_count',      coalesce(vc.shorts_count, 0),
        'audited_regular',   coalesce(ac.audited_regular, 0),
        'audited_shorts',    coalesce(ac.audited_shorts, 0),
        'pending_count',     coalesce(ac.pending_count, 0),
        'quarantined_count', coalesce(ac.quarantined_count, 0),
        'applied_latest',    coalesce(ac.applied_latest, 0),
        'applied_today',     coalesce(ap.applied_today, 0),
        'applied_7d',        coalesce(ap.applied_7d, 0),
        'applied_total',     coalesce(ap.applied_total, 0),
        'delta_views_7d',    coalesce(ap.delta_views_7d, 0),
        'applied_by_day',    coalesce(bt.applied_by_day, '[]'::jsonb)
      ))
      from channels c
      left join vcount  vc on vc.channel_id = c.id
      left join acount  ac on ac.channel_id = c.id
      left join apcount ap on ap.channel_id = c.id
      left join beat    bt on bt.channel_id = c.id
    ), '[]'::jsonb),
    'shorts', (
      select jsonb_build_object(
        'cut_total',      count(*),
        'uploaded_total', count(*) filter (where upload_status = 'UPLOADED')
      )
      from shorts_clips
    )
  );
$$;
