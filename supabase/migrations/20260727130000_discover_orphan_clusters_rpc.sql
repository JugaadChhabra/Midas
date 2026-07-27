-- Server-side orphan clustering (pgvector) — Tier 3′ RPC 2.
--
-- The weekly playlist-discovery pass grouped orphan videos by greedy pairwise
-- cosine similarity. It pulled every orphan's pooled `embedding` — vector(3072),
-- ~39 KB/row — into the app to do it. This function runs the IDENTICAL greedy
-- algorithm in Postgres and returns only (video_id, cluster_id) labels.
--
-- Faithful port of app/playlist_discovery.py::_cluster_orphans:
--   * consider only orphans that HAVE a pooled embedding for p_model_version;
--   * iterate them in a deterministic order (video_id ASC — the Python side is
--     pinned to sorted() to match, replacing the old unspecified DB order);
--   * a video joins the existing cluster with the highest MEAN cosine similarity
--     to that cluster's current members, but only if that mean >= threshold
--     (strict > when comparing clusters, matching the Python tie-break: the first
--     cluster to reach the best score keeps it); otherwise it starts a new cluster;
--   * cosine sim = 1 - (a <=> b); a zero-vector yields NaN from <=>, mapped to 0.0
--     to match _cosine_sim's mag==0 guard;
--   * clusters smaller than p_min_cluster_size are dropped.
--
-- cluster_id is a dense 1..N label assigned in creation order (same order Python
-- creates clusters), so a partition-equality parity check lines up exactly.
--
-- VOLATILE: uses a transaction-local temp table (PostgREST runs each call in its
-- own transaction, so ON COMMIT DROP cleans it up even on pooled connections).
create or replace function discover_orphan_clusters(
    p_channel_id      text,
    p_model_version   text,
    p_orphan_ids      text[],
    p_sim_threshold   double precision,
    p_min_cluster_size int
)
returns table(video_id text, cluster_id int)
language plpgsql
volatile
as $$
declare
    v_ids       text[];
    v_id        text;
    n_clusters  int := 0;
    best_cluster int;
    best_score  double precision;
    cscore      double precision;
    c           int;
begin
    -- Embedded orphans only, deterministic order (matches Python's sorted()).
    select array_agg(e.video_id order by e.video_id)
      into v_ids
    from video_embeddings e
    join videos vv
      on vv.id = e.video_id
     and vv.channel_id = p_channel_id
    where e.chunk_index = 'pooled'
      and e.model_version = p_model_version
      and e.video_id = any(p_orphan_ids);

    if v_ids is null then
        return;  -- no embedded orphans
    end if;

    create temp table _orphan_asg(video_id text primary key, cluster_id int) on commit drop;

    foreach v_id in array v_ids loop
        best_cluster := null;
        best_score   := 0;

        for c in 1..n_clusters loop
            -- mean cosine sim of v_id to every current member of cluster c
            select avg(
                     case
                       when (cand.embedding <=> mem.embedding) <> (cand.embedding <=> mem.embedding)
                            then 0.0                       -- NaN (zero-vector) -> 0.0
                       else 1 - (cand.embedding <=> mem.embedding)
                     end
                   )
              into cscore
            from _orphan_asg a
            join video_embeddings mem
              on mem.video_id = a.video_id
             and mem.chunk_index = 'pooled'
             and mem.model_version = p_model_version
            cross join video_embeddings cand
            where a.cluster_id = c
              and cand.video_id = v_id
              and cand.chunk_index = 'pooled'
              and cand.model_version = p_model_version;

            if cscore is not null and cscore > best_score then
                best_score   := cscore;
                best_cluster := c;
            end if;
        end loop;

        if best_cluster is not null and best_score >= p_sim_threshold then
            insert into _orphan_asg values (v_id, best_cluster);
        else
            n_clusters := n_clusters + 1;
            insert into _orphan_asg values (v_id, n_clusters);
        end if;
    end loop;

    return query
        select a.video_id, a.cluster_id
        from _orphan_asg a
        where a.cluster_id in (
            select cluster_id from _orphan_asg group by cluster_id
            having count(*) >= p_min_cluster_size
        )
        order by a.cluster_id, a.video_id;
end;
$$;

revoke execute on function discover_orphan_clusters(text, text, text[], double precision, int) from public;
grant  execute on function discover_orphan_clusters(text, text, text[], double precision, int) to service_role;
