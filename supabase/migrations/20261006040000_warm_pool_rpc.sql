-- Phase B · B4 (#35): the warm filter, spec Part 2 §2.1 / Part 3 B4.
--
-- A channel's eligible ("warm") pool, most impressions first:
--
--   * public (NULL privacy_status counts as public, as in next_audit_candidate),
--   * not an episode (`is_episode is not true`, as in next_audit_candidate),
--   * on a channel whose reach is certified: the MEASUREMENT_WINDOW_DAYS window
--     ending at the reach frontier is fully covered (app/reach.py certify),
--   * >= p_min_impressions over the channel's latest p_window_days INGESTED
--     reach data-days: distinct data_date in the reporting_reports_ingested
--     ledger for the reach report, not current_date - N,
--   * no active Midas intervention (status_vocab.ACTIVE_INTERVENTION_STATUSES,
--     the same set as interventions_one_active_midas_per_video). Human rows
--     never close, so counting them would bar every video the team ever edited.
--
-- The explore share (WARM_EXPLORE_PCT) is not here: it is random, so the app
-- draws it over this deterministic ranking (app/warm.py explore_order).
--
-- Settings live in the app, so they are parameters. app/warm.py ranked_pool is
-- the in-app twin; tests/test_warm_pool_parity.py runs both on the same rows.
-- Not called from the tick: Slice 1's tick routing wires it in.
-- STABLE + read-only; callable only by service_role (the app).
create or replace function warm_pool(
    p_channel_id               text,
    p_min_impressions          bigint,
    p_window_days              int,
    p_measurement_window_days  int
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
        and i.status in ('planned', 'applied', 'measuring', 'holdout')
    )
  order by rc.impressions desc, v.id;
$$;

revoke execute on function warm_pool(text, bigint, int, int) from public;
grant  execute on function warm_pool(text, bigint, int, int) to service_role;
