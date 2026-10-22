-- Slice 1 · S1.4a (#63): the warm pool narrowed for the agent, spec Part 4 S1.4
-- "Pick" (finding 2) / Part 2 §2.1. Replaces warm_pool() from 20261006040000.
--
-- Two exclusions on top of B4's (still: no active Midas intervention), both
-- Midas rows only. Human rows never exclude: they record an edit and never close.
--
--   * cooldown: any Midas intervention, of any lever and any status (declined,
--     cancelled and judged included), created within p_cooldown_days
--     (TRIAGE_COOLDOWN_DAYS). A `no_change` is a `declined` row, which isn't
--     active, so without this the same top video is offered on the next tick;
--   * once per experiment: any Midas `backlinks` intervention of either arm
--     (treated or holdout), at any age. Each video is in the experiment once.
--
-- The signature gains p_cooldown_days, so the four-argument function is dropped
-- rather than left as an overload (PostgREST can't choose between overloads by
-- named arguments). Its only caller is app/warm.py, updated in the same change.
-- app/warm.py _ranked_pool_inapp is the in-app twin;
-- tests/test_warm_pool_parity.py runs both on the same rows.
-- Not called from the tick: S1.4's tick routing wires it in.
-- STABLE + read-only; callable only by service_role (the app).
drop function if exists warm_pool(text, bigint, int, int);

create or replace function warm_pool(
    p_channel_id               text,
    p_min_impressions          bigint,
    p_window_days              int,
    p_measurement_window_days  int,
    p_cooldown_days            int
)
returns table(id text, impressions bigint)
language sql
stable
as $$
  with covered as (
    select distinct r.data_date
    from reporting_reports_ingested r
    where r.channel_id = p_channel_id
      and r.report_type = 'channel_reach_basic_a1'
  ),
  certified as (
    select count(1) = p_measurement_window_days as ok
    from covered c
    where c.data_date > (select max(data_date) from covered) - p_measurement_window_days
  ),
  window_days as (
    select c.data_date
    from covered c
    order by c.data_date desc
    limit p_window_days
  ),
  reach as (
    select d.video_id, sum(d.impressions)::bigint as impressions
    from video_reach_daily d
    where d.channel_id = p_channel_id
      and d.date in (select data_date from window_days)
    group by d.video_id
  )
  select v.id, rc.impressions
  from reach rc
  join videos v on v.id = rc.video_id
  where (select ok from certified)
    and v.channel_id = p_channel_id
    and (v.privacy_status is null or v.privacy_status = 'public')
    and v.is_episode is not true
    and rc.impressions >= p_min_impressions
    and not exists (
      select 1 from interventions i
      where i.video_id = v.id
        and i.origin = 'midas'
        and (
          i.status in ('planned', 'applied', 'measuring', 'holdout')
          or i.created_at > now() - make_interval(days => p_cooldown_days)
          or (i.lever = 'backlinks' and i.arm in ('treated', 'holdout'))
        )
    )
  order by rc.impressions desc, v.id;
$$;

revoke execute on function warm_pool(text, bigint, int, int, int) from public;
grant  execute on function warm_pool(text, bigint, int, int, int) to service_role;
