# Midas — STATE

> **What this file is.** A ground-truth snapshot of what exists **in this repo**, for
> priming an architecture conversation that cannot read the code.
>
> **Rules for whoever regenerates this:**
> 1. Every claim must be verifiable by reading a file in this repo. Cite the path.
> 2. If something is planned but not built, it goes in §7 (Delta) — never in §2–§6.
> 3. Do not summarise the spec. `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md`
>    holds intent (Part 2 = the design as amended in §0.6; the Part marked "ready to build" = the
>    current build task). `docs/PHASE_A_FINDINGS.md` holds measured evidence. This file holds
>    reality. The gap between the spec and the code is §7.
> 4. Verbatim over paraphrase for config values, metric names, and prompt text.
>
> **Regenerate with:** Claude Code, prompt in §9.

**Generated:** 2026-10-06 (full regeneration from §9; updated for B1a #30: `traffic_poll`, `video_traffic_source_daily`; B1b #31: `playlist_traffic_daily`; B8 #39: token failures skip in `video_sync`; B2 #32: `interventions`, `assign_arm`, `HOLDOUT_PCT`, `channels.agent_enabled`; B3a #33: `app/human_edits.py`, `interventions.ledger_key`; B3b #34: playlist-membership ledger in the walk) · **Commit:** on top of `e9d2ca0` · **Branch:** `phase-b/34-phase-b-b3b-human-edit-ledger-playlist-m`
(Older design docs are deleted in the same change and live only in git history; nothing below cites them.
`scripts/overnight_tickets.sh` is dev tooling, never deployed.)

**The spec**, cited below as **spec**: `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md`. Its
status line: Part 1 (Phase A) done, exit gate passed 2026-10-06; **Part 3 (Phase B) "ready to build"**; Part 2
the approved design, amended 2026-10-06 by P1–P7 (spec Part 2 §0.6).

**Office deployment (from `docs/PHASE_A_FINDINGS.md`).** The office machine has run the Phase A image since
2026-09-29 11:54 UTC, and was restarted ≈12:46 UTC on 2026-10-01 to pick up the `video_sync` job ("Status"
table). The four A4 writers are confirmed frozen from the 2026-09-29 startup log (A0 raw evidence). All 13
channels have `autopilot_enabled = f` (title autopilot off since ≈2026-09-23, owner); 11 have
`autopilot_shorts_enabled = t`, so the autopilot tick still runs, for Shorts only (A0). The office `.env` sets
`AUTOPILOT_TICK_SECONDS` to 30 (restart-day step 2, observed 2026-09-29). The last title apply fleet-wide was
2026-09-24 04:00 UTC (A0, 24 h check PASS 2026-10-01). Two Reporting API jobs exist on Marathi
`UCr5-YUqBiW7PUmeAtxUWuRg`, created 2026-09-29: `channel_traffic_source_a3` and `playlist_traffic_source_a2`;
`channel_traffic_source_a2` is retired (404) (A1.1). A9 passed 2026-10-01: all 8 registered jobs `success`,
Punjabi scored 2026-10-01 07:00 UTC (39 playlists). On 2026-10-06 `/health/jobs` showed `video_sync` **failed**
for Hindi `UCR9qQMyP86aSt-1VgaMg7UA` (`"HTTPException: 401: token_expired"`; re-consented 2026-10-06) and
`metrics_poll` **degraded** (A7 raw result 0). A manual sync of all channels ran 2026-10-06: Marathi has 5,804
videos, synced 2026-10-06 07:48 UTC; Kannada and Telugu have 0 videos in `videos` ("Next session" item 2).
Rollout channel #1 is **Marathi** (owner, 2026-10-06; A7). Phase B code so far is B1, both halves (#30 video,
#31 playlist: `app/traffic_poll.py`, migrations `20261006000000`, `20261006010000`), B8 (#39: `app/sync.py`
`TokenExpired`), B2 (#32: `app/interventions.py`, migration `20261006020000`), B3a (#33: `app/human_edits.py`,
migration `20261006030000`) and B3b (#34: `app/human_edits.py` `record_playlist_additions`, called from the
membership walk in `app/playlists_sync.py`; no migration); none of it is deployed and the migrations are not applied.

**Data caveat for this generation.** The live database runs on the office machine, bound to
`127.0.0.1:55432` there (`docker-compose.yml:21-22`), so it can't be reached from the machine that generated
this file. Live figures below are quoted from `docs/PHASE_A_FINDINGS.md`, each labelled with its date and
section; anything not recorded there is blank. §8 ends with the SQL to refresh them.

---

## 1. Phase status

Stages are the spec's build order (spec Part 2 §6).

| Stage | Theme | Status | Evidence (paths) | Notes |
|---|---|---|---|---|
| **Phase A** | Gates | **done** (exit gate passed 2026-10-06, spec status line) | A4: `app/config.py:115-117,34`, `app/main.py:323-364`, `tests/test_frozen_writers.py`. A5: `app/transcripts.py:24-31`, `app/youtube_metadata.py:58-60`. A6: `app/audits.py:199-286`, `tests/test_strategy_version.py`. A8: `app/job_status.py`, `app/main.py:77-103,562-565`, `tests/test_main_fanout.py`. A10: `app/autopilot.py:477-493,559,627`, `app/audits.py:830-837`, `tests/test_revert_quota_gate.py`. Probes: `scripts/probes/*.py`. Record: `docs/PHASE_A_FINDINGS.md` | Every lever outcome (a) (findings "Phase A conclusion" §1). A5's `default_language = 'bgc'` was already set on Haryanvi (findings "Next session" item 5); the optional i18n probe was not run (A5 table blank). The findings "Exit gate" checklist ticks A11 with this §9-based regeneration (2026-10-06). |
| **Phase B** | Plumbing (spec Part 3, B1–B10) | **in progress** (B1 built, both halves, B2, B3 (both halves) and B8; not deployed) | B1a/B1b: `app/traffic_poll.py`, `app/reporting_client.py` (`ensure_job`, `parse_traffic_csv`, `parse_playlist_traffic_csv`, `TRAFFIC_SOURCE_TYPES`), `app/reporting_poll.py` (`replace_data_day`, `record_ingested`), `supabase/migrations/20261006000000_video_traffic_source_daily.sql`, `supabase/migrations/20261006010000_playlist_traffic_daily.sql`, `tests/test_traffic_poll.py`, `tests/test_reporting_ingest.py`. B8: `app/sync.py:41-70` (`TokenExpired`, `_token_failure_as_401`), `tests/test_sync_token_expiry.py`. B2: `app/interventions.py` (`assign_arm`, `active_for`, `record`), `app/status_vocab.py:143-220` (`Intervention*`, `ACTIVE_INTERVENTION_STATUSES`), `supabase/migrations/20261006020000_interventions.sql`, `HOLDOUT_PCT` (`app/config.py:234`), `tests/test_interventions.py`. B3a: `app/human_edits.py` (`video_links`, `made_by_midas`, `record_description_edits`), `app/sync.py:143-153,262-265,288-297` (`_record_human_edits`), `interventions.record(ledger_key=…)`, `supabase/migrations/20261006030000_interventions_ledger_key.sql`, `tests/test_human_edits.py`. B3b: `app/human_edits.py` (`added_by_midas`, `record_playlist_additions`), `app/playlists_sync.py:297-326,359-368` (`_record_human_memberships`), `tests/test_human_edits_playlists.py` | No `decision_log` table; no `app/decide.py`; only the B3 human ledger writes `interventions` (`human` rows: backlinks on full syncs, playlist memberships on the membership walk); no warm filter; no new embedding recipe; `bho`/`raj` absent from `_LANG_NAMES` (`app/transcripts.py:24-31`) and `_NON_ISO_639_1` (`app/youtube_metadata.py:58-60`). Partial footholds listed in §7.1. |
| **Slice 1** | Backlinks + no change | **not started** | none | No tick routing (the `channels.agent_enabled` column exists, B2, but nothing reads or sets it), no backlink renderer. Title autopilot is off on every channel (header), which is the spec's precondition (spec Part 2 §6.1). |
| **Slice 2** | Playlists + Short links | **not started** (as spec'd) | pre-spec engine frozen: `app/playlists.py`, `app/playlist_discovery.py` | Recommend-only proposal machinery exists (`playlist_proposals`, `app/playlists_router.py:271-297`). The add/remove and creation paths are frozen by default (§4). |
| **Slice 3** | Agent challenger + titles | **not started** | none | No `app/agent/`, no `openrouter.chat_tools`, no `WRITER_MODEL`, no `app/niche_reference.py`. The old title path (`audit_video`) is intact but unreachable from autopilot while `autopilot_enabled = f` (`app/eligibility.py:66-84`). |
| **Slice 4** | Playbook | **not started** | none | No `channels.playbook_json`. `app/reflection.py` (the thing Slice 4 retires) is frozen by `REFLECTION_ENABLED=false` (§4). |
| **Slice 5** | Fleet | **not started** | none | `JobBudget` exists (`app/quota.py:232`) but has no per-channel shares. |

**What runs today (pre-spec machinery, all built before the spec).** The sensor layer
(`app/metrics_poll.py`, `app/reporting_poll.py`, `app/reach.py`, `video_reach_daily`), Loop 1 title
measurement (`app/measurement.py`, `app/verdicts.py`; 21-day CTR windows), playlist inventory and health
scoring (`app/playlists_sync.py`, `app/playlist_health.py`), daily video sync (`app/main.py:243-267`), the Shorts
cutter (`app/shorts/*`), and the NAS backup (`app/backup.py`). The spec keeps the sensor layer, the apply path,
`AuditSuggestion`, quota, `status_vocab`, `reach.certify`, and the playlist write, inventory, health and proposal
machinery (spec Part 2 §0.5 "Kept").

**Channels live** (A7 query 1, `docs/PHASE_A_FINDINGS.md`, 2026-10-06). All 13: `analytics_authorized = t`,
`autopilot_enabled = f`, `reach_warmup = f`. Warm pool and reach frontier are from the same A7 run.

| Channel | id | `default_language` | `measurement_enabled` | `playlist_health_enabled` | `autopilot_shorts_enabled` | Warm videos (≥500 imp, 30 d) | Reach frontier |
|---|---|---|---|---|---|---|---|
| Marathi (**rollout #1**) | `UCr5-YUqBiW7PUmeAtxUWuRg` | `mr` | t | f | t | 566 | 2026-10-04 (221 days) |
| Punjabi | `UC8KjoL0Z9mTHKqB6gFutkJw` | `pa` | t | **t** (only one) | t | 342 | 2026-10-04 (213) |
| Gujarati | `UCOVKJdzghm2gOnuaGeJTonA` | `gu` | t | f | t | 603 | 2026-10-04 (147) |
| English | `UCMpj6iUMCMhB0k4L5EcxJwQ` | `en` | t | f | t | 1,008 | 2026-10-04 (148) |
| Hindi | `UCR9qQMyP86aSt-1VgaMg7UA` | NULL | t | f | t | 1,120 | 2026-09-26 (213; token expired, last synced 2026-09-24) |
| Bhojpuri | `UC8oC7Yiz0WkH3PKb3GW42XA` | NULL | t | f | t | 471 | 2026-10-04 (183) |
| Tamil | `UCWb0eKKkX1NE1r_Tu6oKhdQ` | NULL | t | f | t | 290 | 2026-10-04 (143) |
| Malayalam | `UCX8BttGE4UAFdm1RRIULOPQ` | NULL | t | f | t | 70 | 2026-10-04 (143) |
| Haryanvi | `UCc4Tv_DEGDEKrKAt-vyVNmw` | `bgc` | f | f | t | no reach data | none |
| Rajasthani | `UCFO6AQ_KBQDEaQiTi-dBEWQ` | NULL | f | f | t | no reach data | none |
| 3D Animated Series | `UCqtU4xCSjsSvE53Iy6NUKSg` | `hi` | f | f | t | no reach data | none |
| Kannada | `UCo4_mZK5aAF7ugv4cTfZlEg` | `kn` | f | f | f | no reach data | none (0 videos) |
| Telugu | `UCxK1-ftYdFvU4IuUW3POxRA` | NULL | f | f | f | no reach data | none (0 videos) |

Six channels have no `default_language`, so `eligibility.can_audit` gates them out of title audits
(`app/eligibility.py:66-84`) and `audit_video` refuses them with 400 (`app/audits.py:390-402`).

Flags that exist on `channels`: `analytics_authorized`, `measurement_enabled`, `reach_warmup`,
`playlist_health_enabled`, `autopilot_enabled`, `autopilot_shorts_enabled`, `sync_shorts`, and `agent_enabled`
(`20261006020000`, B2; file only, not applied; nothing reads or sets it).

---

## 2. Schema — as applied

**Migrations** (`supabase/migrations/`, in order; bootstrap `supabase/bootstrap/000_roles.sql`,
`010_storage_shim.sql` run first). The latest is `20261006030000` (B3a, #33). It, `20261006020000` (B2, #32), `20261006010000` (B1b, #31) and
`20261006000000` (B1a, #30) are files only, not yet applied on the office machine.

```
20260505092756_init.sql                          channels, videos, audit_configs, audits
20260505210725_channel_default_language.sql
20260505225504_tracking_autopilot.sql            *_before, *_at_apply, autopilot_*, quota_log
20260506134436_video_privacy_and_optimization.sql
20260508082931_content_intelligence.sql          video_keyframes, storage bucket
20260518000000_playlists.sql                     pgvector, video_embeddings, playlists, playlist_assignments
20260519000000_playlist_proposals.sql
20260519200000_prompt_versions.sql               prompt_versions, threshold_history
20260519200001_reflection_columns.sql
20260610122433_analytics_authorized.sql
20260610134419_metrics_tables.sql                video_metrics, playlist_metrics
20260617120000_shorts_tables.sql
20260618000000_channel_last_full_synced.sql
20260618115221_phase1b_playlist_inventory.sql
20260618133036_phase1b_step_b_traffic_source.sql video_traffic_source_playlist
20260702174235_phase05_reporting_reach.sql       video_reach_daily, reporting_reports_ingested
20260702183233_phase1a_loop1_measurement.sql     audit_strategies, audits.measurement_*, channels.measurement_enabled
20260709120000_shorts_local_cutter.sql
20260709150000_shorts_entrypoints.sql
20260710120000_autopilot_shorts.sql
20260710140000_video_duration.sql
20260713120000_shorts_worker_pid.sql
20260719000000_capture_dashboard_drift.sql       videos.is_short, channels.sync_shorts, audit_configs.shorts_prompt (captured post-hoc)
20260720120000_dashboard_summary_rpc.sql
20260722120000_shorts_nas_source.sql
20260727120000_playlist_video_sims_rpc.sql
20260727130000_discover_orphan_clusters_rpc.sql
20260727140000_fix_orphan_clusters_ambiguous.sql
20260727150000_orphan_clusters_collate_c.sql
20260727160000_next_audit_candidate_rpc.sql
20260728000000_audits_video_created_idx.sql
20260728010000_autopilot_decouple_pause.sql
20260730000000_reach_warmup_flag.sql
20260730010000_next_audit_candidate_exclude_measurement.sql
20260812000000_playlist_membership_walked_at.sql
20260813090000_dashboard_summary_quarantined.sql
20260814000000_video_transcripts.sql
20260814010000_dashboard_summary_unmeasured_baseline.sql
20260904000000_video_is_episode.sql
20260904000100_next_audit_candidate_exclude_episodes.sql
20261006000000_video_traffic_source_daily.sql   video_traffic_source_daily, reporting_reports_ingested.report_type
20261006010000_playlist_traffic_daily.sql       playlist_traffic_daily
20261006020000_interventions.sql                interventions, channels.agent_enabled
20261006030000_interventions_ledger_key.sql     interventions.ledger_key + unique index
```

These are the files. The live DB's migration ledger was not checked (unreachable).

**Tables** (columns are the union across the migrations):

- **`channels`**: `id text pk, name, handle, refresh_token text not null, access_token, token_expiry timestamptz, last_synced_at, created_at, default_language text, autopilot_enabled bool default false, autopilot_paused_reason text, autopilot_last_tick_at, autopilot_daily_cap int default 10, analytics_authorized bool default false, last_full_synced_at, playlist_health_enabled bool default false, measurement_enabled bool default false, autopilot_shorts_enabled bool not null default false, autopilot_shorts_daily_cap int not null default 1, autopilot_shorts_upload_cap int not null default 2, shorts_cut_mode text not null default 'highlights', shorts_camera_motion text not null default 'calm', sync_shorts bool (nullable), nas_folder text, autopilot_paused_at timestamptz, reach_warmup bool default false, agent_enabled boolean not null default false`.
- **`videos`**: `id text pk, channel_id → channels on delete cascade, title, description, tags text[], thumbnail_url, category_id, view_count, like_count, comment_count bigint, published_at, last_fetched_at, privacy_status text, thumbnail_optimized_at, playlists_optimized_at timestamptz, duration_seconds int, is_short bool, is_episode bool (nullable; NULL = not episode)`.
- **`audits`**: `id bigserial pk, video_id → videos on delete cascade, status text default 'pending', suggested_title, suggested_description, suggested_tags text[], thumbnail_feedback, issues_found jsonb, ai_reasoning, applied_at, created_at, title_before, description_before, tags_before text[], view_count_at_apply, like_count_at_apply, comment_count_at_apply bigint, transcript_available bool, transcript_lang, keyframes_extracted int default 0, prompt_version_id → prompt_versions, measurement_status text default 'not_applicable', measurement_started_at, measurement_result jsonb, outcome_decision text default 'none', redo_of_audit_id → audits, strategy_version → audit_strategies`.
  - Status vocab (`app/status_vocab.py:30-44`): `pending|applied|failed|quarantined|blocked_test_and_compare|shadow_pending|reverted|approved|rejected`. No code writes `approved` or `rejected`. `outcome_decision`: `none|kept|reverted|redo_queued`; `redo_queued` is "Reserved … nothing writes it yet" (`app/status_vocab.py:98-100`), and nothing writes `redo_of_audit_id`.
  - Measurement vocab (`app/status_vocab.py:63-73`): `not_applicable|awaiting_window|measuring|win|neutral|regression`. Reason codes (`app/measurement.py:168-171`): `no_timestamp`, `coverage_lost`, `dormant`, `video_gone`, under key `reason_code` (`app/verdicts.py:47`).
  - Partial index `audits_measurement_inflight_idx` on `('awaiting_window','measuring')`; `audits_video_created_idx (video_id, created_at desc)`.
- **`video_metrics`** (`20260610134419`):
  ```sql
  id bigserial pk, video_id text not null → videos on delete cascade, channel_id text not null → channels,
  window_start date not null, window_end date not null,
  impressions bigint, ctr float,
  views bigint, est_minutes_watched bigint, avg_view_duration_sec integer, avg_view_pct float,
  is_pre_change boolean default false, fetched_at timestamptz default now(),
  unique (video_id, window_start, window_end)
  ```
- **`video_reach_daily`**: `video_id text not null (no FK), channel_id → channels, date date, impressions bigint not null, ctr double precision not null (fraction 0..1), report_id text, fetched_at, unique(video_id, date)`. Source: Reporting API `channel_reach_basic_a1` (`app/reporting_client.py:56`).
- **`reporting_reports_ingested`**: `report_id text pk, job_id, channel_id, data_date date, row_count int, ingested_at, report_type text not null default 'channel_reach_basic_a1'` (`report_type` added by `20261006000000`). Shared by reach and both traffic report types; `reach.coverage` counts only `report_type = 'channel_reach_basic_a1'` (`app/reach.py:122-130`).
- **`video_traffic_source_daily`** (`20261006000000`, B1):
  ```sql
  id bigserial primary key, video_id text not null (no FK), channel_id text not null references channels(id),
  date date not null, source_type smallint not null, source_detail text not null default '',
  views bigint not null, engaged_views bigint not null, watch_time_minutes double precision not null,
  report_id text not null, ingested_at timestamptz default now(),
  unique (video_id, date, source_type, source_detail)
  ```
  Index `(channel_id, date desc)`. Source: Reporting API `channel_traffic_source_a3` (`app/reporting_client.py:73`), summed over `country_code`, `subscribed_status`, `live_or_on_demand` (`app/reporting_client.py:443` `parse_traffic_csv` → `:397` `_aggregate_traffic_csv`).
- **`playlist_traffic_daily`** (`20261006010000`, B1b):
  ```sql
  id bigserial primary key, playlist_id text not null (no FK), video_id text not null (no FK),
  channel_id text not null references channels(id),
  date date not null, source_type smallint not null, source_detail text not null default '',
  views bigint not null, playlist_starts bigint not null, watch_time_minutes double precision not null,
  report_id text not null, ingested_at timestamptz default now(),
  unique (playlist_id, video_id, date, source_type, source_detail)
  ```
  Index `(channel_id, date desc)`. Source: Reporting API `playlist_traffic_source_a2` (`app/reporting_client.py:100`), summed over the same three dimensions (`app/reporting_client.py:460` `parse_playlist_traffic_csv`); `engaged_views`, `average_view_duration_seconds` and `playlist_saves_*` are not stored.
- **`interventions`** (`20261006020000`, B2):
  ```sql
  create table if not exists interventions (
      id                  bigserial   primary key,
      video_id            text        not null references videos(id) on delete cascade,
      channel_id          text        not null references channels(id),
      lever               text        not null,   -- backlinks|playlist|short_link|title
      origin              text        not null,   -- midas|human
      arm                 text        not null,   -- treated|holdout|n/a
      status              text        not null,
      payload             jsonb,
      before_state        jsonb,
      -- Title lever only.
      audit_id            bigint      references audits(id),
      strategy_version    text        references audit_strategies(version),
      -- Rules choice, Jev choice and probabilities.
      triage_json         jsonb,
      applied_at          timestamptz,
      -- Human interventions: when sync saw the edit, not when it was made.
      detected_at         timestamptz,
      measurement_status  text,
      measurement_result  jsonb,
      created_at          timestamptz default now()
  );

  -- Spec Part 2 §1.6: at most one active Midas intervention per video, of any
  -- lever. app/interventions.record checks this first; the index makes it hold
  -- under concurrent writers too. The status list mirrors
  -- status_vocab.ACTIVE_INTERVENTION_STATUSES (tests/test_status_vocab.py).
  -- Human interventions are outside it: they never block a Midas change.
  create unique index if not exists interventions_one_active_midas_per_video
      on interventions (video_id)
      where origin = 'midas' and status in ('planned', 'applied', 'measuring', 'holdout');

  -- Backs the on-delete-cascade from videos, and per-video reads of any origin.
  create index if not exists interventions_video_idx on interventions (video_id);
  ```
  Added by `20261006030000` (B3a), verbatim:
  ```sql
  alter table interventions add column if not exists ledger_key text;

  create unique index if not exists interventions_ledger_key_key
      on interventions (ledger_key);
  ```
  Vocab (`app/status_vocab.py:143-220`): lever
  `backlinks|playlist|short_link|title`; origin `midas|human`; arm `treated|holdout|n/a`; status
  `planned|applied|measuring|judged|cancelled|declined|holdout|insufficient_data`, of which
  `ACTIVE_INTERVENTION_STATUSES` = `planned|applied|measuring|holdout`. The partial unique index is the SQL mirror
  of that set (`tests/test_status_vocab.py`). The only writer is the B3 human ledger (`app/human_edits.py`, two
  row kinds). **B3a:** one
  row per link to one of our videos that the team added to a description, `origin='human'`, `lever='backlinks'`,
  `arm='n/a'`, `status='applied'`, `applied_at` NULL, `detected_at` = when the sync saw it, and `payload`
  `{source_video_id, target_video_id, added_targets, removed_targets, timing}` (plus `removed_detected_at` once a
  later sync sees the link gone). `ledger_key` = `backlinks:<source>:<target>:<first 16 hex of sha256 of the new
  description, whitespace collapsed>`. **B3b:** one row per membership of one of the channel's videos in one of its
  playlists that the membership walk sees for the first time, in a playlist it has walked before, and that Midas
  didn't add: `lever='playlist'`, same `origin`/`arm`/`status`/`applied_at`/`detected_at` as B3a, `payload`
  `{playlist_id, video_id, playlist_item_id, timing}`, `ledger_key` = `playlist:<playlist_id>:<video_id>:<playlist_item_id>`.
  `ledger_key` is NULL on any other row. `measurement_status` has no vocab yet.
- **`playlists`**: `id text pk, channel_id → channels on delete cascade, title text not null, description default '', synced_at, role text, origin text default 'inherited', item_count int, last_synced_at, created_by_optimizer_at, strategy_version text, health_score float, health_recommendation text (revive|remove|keep|insufficient_data), health_computed_at, health_rationale_json jsonb, membership_walked_at timestamptz`.
  - Roles assigned: `series | funnel | inherited` (`app/playlists_sync.py:50-63`). `playlist_discovery` inserts rows without `origin` or `created_by_optimizer_at` (`app/playlist_discovery.py:198-205`), so discovery-created playlists land as `origin='inherited'`. Nothing writes `playlists.strategy_version`.
- **`playlist_metrics`**:
  ```sql
  id bigserial pk, playlist_id text not null (no FK), channel_id → channels, window_start date, window_end date,
  playlist_starts bigint, views_per_playlist_start float, avg_time_in_playlist_sec integer,
  playlist_views bigint, playlist_est_minutes_watched bigint, is_pre_change boolean default false,
  fetched_at, unique (playlist_id, window_start, window_end)
  ```
- **`video_traffic_source_playlist`**: `video_id → videos, playlist_id text (no FK), channel_id, window_start, window_end, views bigint, unique(video_id, playlist_id, window_start, window_end)`. Nothing populates it (`TIER2_TRAFFIC_SOURCE_SUPPORTED = False`, `app/metrics_poll.py:85`).
- **`audit_strategies`**: `version text pk, prompt_template text not null, model text not null, config jsonb, status text default 'challenger', notes, created_at`. Seed row `('2026.07-baseline-v1', 'code:app/audits.py DEFAULT_PROMPT + audit_configs.generated_prompt (per-channel)', 'anthropic/claude-haiku-4.5', 'champion', …)`; derived rows are upserted per audit (§6).
- **`video_embeddings`**: `video_id, chunk_index, model_version text not null, embedding vector(3072), unique (video_id, chunk_index, model_version)` (`20260518000000_playlists.sql:10-12`). `model_version` is always `EMBED_MODEL` (`app/embeddings.py:127`).
- **Other tables:** `audit_configs` (`raw_insights, generated_prompt, shorts_prompt, niche_queries jsonb, reflection_mode default 'shadow'`), `prompt_versions`, `threshold_history`, `playlist_assignments`, `playlist_proposals`, `video_keyframes`, `video_transcripts`, `quota_log`, `shorts_jobs`, `shorts_clips`. SQL functions: `dashboard_summary()`, `playlist_video_sims()`, `discover_orphan_clusters()`, `next_audit_candidate()`.

Of the spec's Phase B tables `video_traffic_source_daily`, `playlist_traffic_daily` and `interventions` exist (plus `channels.agent_enabled`); the rest, and the Slice tables and columns, are listed in §7.1.

---

## 3. Config — verbatim

Defaults from `app/config.py`. "Dev `.env`" is the generating machine's local `.env` (not in git). The office
`.env` is hand-carried and was not read; the only office value on record is `AUTOPILOT_TICK_SECONDS=30`
(`docs/PHASE_A_FINDINGS.md` restart-day step 2).

**Settings the spec names** (spec Part 1 A4/A6, Part 2 §8):

| Setting | Code (`app/config.py`) | Spec | Differs? |
|---|---|---|---|
| `PLAYLIST_DISCOVERY_ENABLED` | `:115` `os.getenv("PLAYLIST_DISCOVERY_ENABLED", "false").lower() == "true"` | default false (Part 1 A4) | no |
| `PLAYLIST_RECONCILE_WRITES_ENABLED` | `:116` same form, `"false"` | default false (A4) | no |
| `PLAYLIST_TUNING_ENABLED` | `:117` same form, `"false"` | default false (A4) | no |
| `REFLECTION_ENABLED` | `:34` same form, `"false"` | default false (A4) | no |
| `STRATEGY_LABEL` | `:249` `os.getenv("STRATEGY_LABEL") or "2026.07-baseline"` | prefix of a derived `strategy_version` (A6, Part 2 §8) | derived per audit, not at startup (§7.3) |
| `MIN_IMPRESSIONS` | `:185` `int(os.getenv("MIN_IMPRESSIONS") or "500")` | `WARM_MIN_IMPRESSIONS` starts "Same as `MIN_IMPRESSIONS`" (Part 2 §8) | `WARM_MIN_IMPRESSIONS` absent |
| `MEASUREMENT_WINDOW_DAYS` | `:184` `or "21"` | measurement runs weekly (Part 2 §1.1); 14-day extension (§1.7) | **differs** (21-day window) |
| `PLAYLIST_JOIN_HIGH` / `_LOW` / `PLAYLIST_LEAVE` | `:120-122` `or "0.72"` / `"0.55"` / `"0.60"`, process-global | per channel, recalibrated (Part 2 §4, Part 3 B6) | **differs** |
| `TRAFFIC_INGEST_CHANNELS` | `:226-230` `{c.strip() for c in (os.getenv("TRAFFIC_INGEST_CHANNELS") or "UCr5-YUqBiW7PUmeAtxUWuRg").split(",") if c.strip()}` | the rollout channel (Part 2 §8) | no |
| `HOLDOUT_PCT` | `:234` `float(os.getenv("HOLDOUT_PCT") or "0.20")` | 0.20, per lever, stable hash (Part 2 §8) | no. Read only by `app/interventions.py` `assign_arm` |
| `AUDIT_MODEL` | `:29` `os.getenv("AUDIT_MODEL") or "anthropic/claude-haiku-4.5"`; dev `.env`: `google/gemini-3.7-flash` | reasoning model (Part 2 §3.1) | — |
| `WARM_MIN_IMPRESSIONS` (500), `WARM_WINDOW_DAYS` (28), `WARM_EXPLORE_PCT` (0.10), `BACKLINK_MAX` (3), `BACKLINK_MIN_CANDIDATES` (2), `BACKLINK_EXPERIMENT_WINDOWS` (3), `SIBLING_MIN_VIEWS` (100), `PLAYBOOK_MIN_VIDEOS_PER_PATTERN` (5), `AGENT_MAX_TURNS` (12), `WRITER_MODEL` (= `AUDIT_MODEL`), `DECIDE_BACKEND` (`llm`), `NICHE_REFERENCE_REFRESH_DAYS` (90), `NICHE_REFERENCE_QUOTA_BUDGET` (500) | **absent** | Part 2 §8 start values | **absent** |

**Every other setting, verbatim defaults** (`app/config.py`; dev `.env` overrides noted):
```
SCOPES = youtube, youtube.readonly, yt-analytics.readonly          (:16-22)
PROMPT_GEN_MODEL = os.getenv("PROMPT_GEN_MODEL") or "google/gemini-2.0-flash-001"     # dev .env: anthropic/claude-opus-5:online
REFLECTION_MODEL = os.getenv("REFLECTION_MODEL") or "anthropic/claude-sonnet-4-6"     # dev .env: anthropic/claude-sonnet-5
OTEL_ENABLED "false"  OTEL_ENDPOINT "http://phoenix:6006/v1/traces"  OTEL_SERVICE_NAME "midas"
DRY_RUN = os.getenv("DRY_RUN", "false")        # default: writes go to YouTube
YT_DAILY_QUOTA "10000"  YT_QUOTA_SAFETY_BUFFER "300"  YT_QUOTA_APPLY_RESERVE "1500"
AUTOPILOT_TICK_SECONDS "120"            # dev .env 100; office .env 30
AUTOPILOT_PICKER_USE_RPC "false"        # dev .env true
AUTOPILOT_PAUSE_COOLDOWN_MINUTES "60"
SHORTS_MAX_CONCURRENT_JOBS "2"  SHORTS_DISPATCH_INTERVAL_SECONDS "5"  SHORTS_YT_DOWNLOAD_ENABLED "false"
SHORTS_MAX_SOURCE_SECONDS "300"  SHORTS_CACHE_DIR "./shorts_cache"  LOG_DIR "logs"  LOG_LEVEL "INFO"
YOUTUBE_PROXY_URL ""  WEBSHARE_PROXY_USERNAME ""  WEBSHARE_PROXY_PASSWORD ""
PLAYLIST_HITL "true"  PLAYLIST_MUTATION_CAP "20"
PLAYLIST_SIMS_USE_RPC "false"           # dev .env true
PLAYLIST_DISCOVERY_USE_RPC "false"      # dev .env true
PLAYLIST_RECONCILE_CHANNELS default "UCr5-YUqBiW7PUmeAtxUWuRg,UC8KjoL0Z9mTHKqB6gFutkJw,UCOVKJdzghm2gOnuaGeJTonA,UCc4Tv_DEGDEKrKAt-vyVNmw"   ("*" = all)  (:145-155)
PLAYLIST_SYNC_QUOTA_BUDGET "2000"  PLAYLIST_FULL_WALK_DAYS "30"
MIN_PLAYLIST_STARTS "50"  PLAYLIST_MEASUREMENT_WINDOW_DAYS "35"  PLAYLIST_HEALTH_AGG_WEEKS "4"
PLAYLIST_HEALTH_REMOVE_PCTL "5"  PLAYLIST_HEALTH_REVIVE_PCTL "20"
CTR_WIN_THRESHOLD "0.10"  CTR_REGRESSION_THRESHOLD "-0.10"  MAX_REDO "2"  AUTO_REVERT_ON_REGRESSION "false"
DASHBOARD_USE_RPC "true"  MEASUREMENT_COVERAGE_GRACE_DAYS "14"  REACH_STALE_AFTER_DAYS "7"
REPORTING_MEASURED_CHANNELS_ONLY "true"  METRICS_POLL_MEASURED_ONLY "true"
TRANSCRIPT_MAX_CHARS "8000"  KEYFRAME_MAX_FRAMES "4"  KEYFRAMES_LOCAL_DIR "storage/keyframes"  KEYFRAME_FFMPEG_TIMEOUT "30"
NAS_MODE "smb"  NAS_PORT "445"  NAS_AUTH_PROTOCOL "ntlm"
NAS_SOURCE_ROOT_PATH "Animations/SHORTS CUTTER/RHYMES"  NAS_DESTINATION_ROOT_PATH "Animations/SHORTS CUTTER/COMPLETED"  NAS_LOCAL_ROOT "./nas_data"
DATABASE_URL ""  BACKUP_ENABLED "true"  BACKUP_HOUR "0"  BACKUP_WORK_DIR "./backups"
BACKUP_SLOTS "1"                        # dev .env 2; CLAUDE.md says 2
BACKUP_PG_DUMP "pg_dump"  RESTORE_ON_EMPTY "true"  RESTORE_PSQL "psql"
```
Never read anywhere but `app/config.py`: `MAX_REDO`, `AUTO_REVERT_ON_REGRESSION`, `PLAYLIST_MEASUREMENT_WINDOW_DAYS`.

Hardcoded constants that act like config: `reflection._MIN_DATA_POINTS=10`, `_NEGATIVE_MEDIAN_PCT=-2.0`,
`_NEGATIVE_LEVER_PCT=-5.0`, `_REFLECT_COOLDOWN_DAYS=7` (`app/reflection.py:47-52`); auto-revert `21` days and
`> 10.0` points (`app/reflection.py:649,659`); `playlist_discovery.MIN_CLUSTER_SIZE=4`, `MAX_NEW_PLAYLISTS=2`,
`CLUSTER_SIM_THRESHOLD=0.75` (`app/playlist_discovery.py:19-21`); `playlists.JUDGE_MODEL="anthropic/claude-haiku-4.5"`
(`app/playlists.py:28`); `metrics_poll.WINDOW_DAYS=7` (`app/metrics_poll.py:47`);
`TIER2_TRAFFIC_SOURCE_SUPPORTED=False` (`app/metrics_poll.py:85`); `reach.ROLLOVER_SLOP_DAYS=1` (`app/reach.py:52`);
`sync.SYNC_STALE_AFTER=timedelta(hours=6)`, `FULL_SYNC_INTERVAL=timedelta(days=3)` (`app/sync.py:515,520`);
`audits.DECISION_QUESTION_SET_VERSION="none"` (`app/audits.py:199`); `quota.APPLY=(VIDEOS_LIST, VIDEOS_UPDATE)`
= 51u (`app/quota.py:50-67`); `openrouter.EMBED_MODEL="google/gemini-embedding-2-preview"` (`app/openrouter.py:7`).

---

## 4. Scheduled jobs

All registered in `app/main.py:292` `_register_jobs()`, called from `lifespan()` (`app/main.py:493-504`),
`BackgroundScheduler`, each `max_instances=1, coalesce=True`.

**Failure semantics.** `_run_per_channel` (`app/main.py:77-103`) runs every channel, logs each failure at ERROR
with traceback as `"<label> (job <job_id>) failed for <id>: <err>"`, and after the last channel raises one
`job_status.JobRunFailed` naming the failed channels, so APScheduler records the run as failed.
`video_sync`, `playlist_reconcile`, `playlist_discovery`, `playlist_tuning`, `reflection` and
`playlist_health_score` use it. `metrics_poll`, `reporting_poll` and `traffic_poll` collect channels that raised anything but the
expected skips and raise `JobRunFailed("metrics_poll" | "reporting_poll" | "traffic_poll", …)` (`app/traffic_poll.py:207`, `app/metrics_poll.py:418`,
`app/reporting_poll.py:358`). Per-item errors inside a channel's poll are judged by
`job_status.item_error_verdict` (`app/job_status.py:50`) per category: all attempted items in a category failed →
the channel fails as `"ItemsFailed: <category>: all <n> failed"`; some failed → the poll returns
`{"partial_errors": {…}}` (`app/metrics_poll.py:421`, `app/reporting_poll.py:359`), recorded as `degraded`.
`measurement_eval` raises `JobRunFailed("measurement_eval", failed)` when any audit errored
(`app/main.py:270-279`). `job_status.registry.watch(scheduler)` (`app/main.py:504`) registers every job as
`never_run` and records `status` (`never_run|success|degraded|failed`), `last_run_at`, `error`,
`failed_channels`, `partial_errors`, logging `"JOB FAILED <job_id> at <time>: <error>"` /
`"JOB DEGRADED <job_id> at <time>: …"` (`app/job_status.py:96,103`). In memory only; a restart clears it. Served
at `GET /health/jobs` (`app/main.py:562-565`).

**Freeze flags (A4).** With its flag false a writer is not registered and startup logs
`"<job_id> not registered: <FLAG>=false"`. `playlist_reconcile` always registers; with
`PLAYLIST_RECONCILE_WRITES_ENABLED=false` it runs `sync_playlists` and skips `reconcile_channel`, logging
`"Daily reconcile <id>: add/remove skipped (PLAYLIST_RECONCILE_WRITES_ENABLED=false)"` per channel
(`app/main.py:165-169`) and `"playlist_reconcile registered for sync only: add/remove skipped
(PLAYLIST_RECONCILE_WRITES_ENABLED=false)"` at startup (`app/main.py:323-325`). All four flags default false (§3);
the office startup log confirmed the freeze 2026-09-29 (`docs/PHASE_A_FINDINGS.md` A0).

| Job id | Trigger | Entry point | Status |
|---|---|---|---|
| `autopilot` | interval `AUTOPILOT_TICK_SECONDS` (`app/main.py:298`) | `app/autopilot.py:496` `tick`: quota-dormancy gate → pick channel (`Job.AUTOPILOT` = `can_audit or can_cut_shorts`) → Shorts action → `can_audit` gate → `_resync_if_stale` → daily cap → pick video → ledger quota gate → unsafe-model gate → `audit_video` → validate → ledger quota gate → apply → re-embed | registered. With `autopilot_enabled = f` everywhere it runs only the Shorts action. `_can_afford_apply` (`app/autopilot.py:480-493`) logs `quota_insufficient` and skips without pausing |
| `shorts_dispatch` | interval `SHORTS_DISPATCH_INTERVAL_SECONDS` (5 s) (`:306`) | `app/shorts/dispatcher.py:dispatch_tick` | registered |
| `playlist_reconcile` | cron 02:00 server-local (`:314`) | `main._daily_reconcile` (`:131`) → `sync_playlists` (shared `JobBudget("playlist_sync", PLAYLIST_SYNC_QUOTA_BUDGET, reserve=YT_QUOTA_APPLY_RESERVE)`) + `reconcile_channel` | registered; channels = `PLAYLIST_RECONCILE_CHANNELS` allowlist (`app/eligibility.py:186-195`). **Add/remove frozen** by `PLAYLIST_RECONCILE_WRITES_ENABLED`; inventory sync and the budgeted membership walk still run. **Human-edit ledger (B3b):** for a playlist walked before (`membership_walked_at` not NULL at plan time), each page's memberships the walk has no `playlist_assignments` row for go to `human_edits.record_playlist_additions` before the walk seeds its `sync` rows (`app/playlists_sync.py:297-326`); a playlist's first walk is the baseline and records none. A ledger error is logged as `"sync_playlists <id>: human-edit ledger failed; walk continues: <err>"` and never fails the walk (`_record_human_memberships`, `app/playlists_sync.py:359-368`). The manual `POST /channels/{id}/playlists/bootstrap` runs the same walk (`app/playlists_router.py:192`) |
| `playlist_discovery` | cron Sun 03:00 local (`:327`) | `main._weekly_discovery` → `app/playlist_discovery.py:152` `discover_playlists` | **frozen** (`PLAYLIST_DISCOVERY_ENABLED`). When on: every channel; **creates playlists** (≤2/run), skipped under `DRY_RUN` |
| `reflection` | cron Mon 04:00 local (`:340`) | `app/reflection.py:702` `reflect` | **frozen** (`REFLECTION_ENABLED`). When on: every channel |
| `playlist_tuning` | cron Mon 03:30 local (`:353`) | `app/playlists.py:463` `tune_thresholds` | **frozen** (`PLAYLIST_TUNING_ENABLED`). When on: writes `settings.PLAYLIST_JOIN_HIGH` process-globally (`app/playlists.py:518`) |
| `video_sync` | cron 04:00 UTC (`:365`) | `main._daily_video_sync` (`:243`) → `app/sync.py:546` `routine_sync` per channel | registered, every channel. Read-only: `"fresh"` if synced within 6 h, else a full pass if the last full sync is >3 days old, else incremental + `refresh_stats`. An expired or revoked token is an expected skip, logged `"video_sync <id>: OAuth token expired; skipping until re-consent"` (`app/main.py:260-264`); any other error, including a YouTube 401 that isn't a token failure, fails the channel. The skip works because `sync_channel`, `refresh_stats` and `refresh_applied_stats` are wrapped by `_token_failure_as_401` (`app/sync.py:54`), which turns a `TokenExpiredError` from anywhere in the call (at `youtube_for_channel`, or mid-call from the `yt_*` helpers' `invalid_grant` check, `app/youtube_client.py:63-66`) into `TokenExpired` (`app/sync.py:41`): an `HTTPException(401, "token_expired")` that is also a `TokenExpiredError`. Before B8 these raised a plain `HTTPException(401)`, which failed the run (2026-10-06, Hindi, §8). The autopilot resync catches the same type (`app/autopilot.py:398`). **Human-edit ledger (B3a):** a full pass also reads the stored descriptions and, before the videos upsert, hands every re-read (id, stored, fetched) description to `human_edits.record_description_edits` (`app/sync.py:262-265,288-297`). A ledger error is logged as `"sync <id>: human-edit ledger failed; sync continues: <err>"` and never fails the sync; a per-video error is logged `"human_edits <channel>: ledger failed for <video>: <err>"` and the other videos still run. Incremental passes re-fetch no known video, so they record nothing |
| `metrics_poll` | cron 05:00 UTC (`:378`) | `app/metrics_poll.py:poll_metrics` | registered; `analytics_authorized` channels; videos only if in a measurement window (`METRICS_POLL_MEASURED_ONLY`) |
| `reporting_poll` | cron 06:00 UTC (`:399`) | `app/reporting_poll.py:poll_reporting` | registered; `analytics_authorized AND (measurement_enabled OR reach_warmup)` (`app/eligibility.py:154-168`). Ingests only `channel_reach_basic_a1` |
| `traffic_poll` | cron 06:30 UTC (`:418`) | `app/traffic_poll.py:173` `poll_traffic` | registered; `analytics_authorized` channels in `TRAFFIC_INGEST_CHANNELS` (`app/eligibility.py:170-178`). Two feeds per channel (`_FEEDS`, `app/traffic_poll.py:74`): **video** ensures the `channel_traffic_source_a3` job (`midas-traffic-source`, Marathi `3647f5d8…`) → `video_traffic_source_daily`; **playlist** ensures the `playlist_traffic_source_a2` job (`midas-playlist-traffic-source`, Marathi `381cf084…`) → `playlist_traffic_daily`. Both Marathi jobs are found, not created. Each feed ingests each data-day's newest not-yet-ingested report, a restatement replacing the day (`app/traffic_poll.py:89` `_newest_per_day`, `app/reporting_poll.py:104` `replace_data_day`), and ledgers it with its own `report_type`. Logs `"traffic_poll <id> data-day <d>: <n> rows written to <table> (report <r>)"` (`app/traffic_poll.py:118`). Feeds are isolated (`_poll_channel`, `app/traffic_poll.py:155`): a feed crash is recorded as `"<feed>: <Type>: <msg>"` and fails the channel, but the other feed still runs; per-report errors are judged per feed (categories `video reports`, `playlist reports`). Independent of `reporting_poll` |
| `playlist_health_score` | cron 07:00 UTC (`:432`) | `main._daily_playlist_health_score` (`:220`) → `app/playlist_health.py:score_channel` | registered; `playlist_health_enabled` channels (Punjabi only, §1) |
| `measurement_eval` | cron 08:00 UTC (`:451`) | `main._daily_measurement_eval` → `app/measurement.py:evaluate_with_failures` | registered |
| `nightly_db_backup` | cron `BACKUP_HOUR` local (`:466`) | `app/backup.py:run_nightly_backup` | registered; no-op if `BACKUP_ENABLED=false` |
| `pot_provider_refresh` | interval 2 h (`:482`) | `main._refresh_pot_provider` | only if env `BGUTIL_POT_HTTP_BASE_URL` is set; absent on the office machine (`docs/PHASE_A_FINDINGS.md` A0 step 12) |

Startup side effects: `provision.ensure_database_populated()` (restore from NAS if the DB is empty,
`app/main.py:499`), `shorts.runner.reap_stuck_jobs()` (`:505-509`), `tracing.configure()`.

Spec'd jobs not registered: `niche_reference_refresh` (Part 2 §3.6), weekly lever
measurement and playbook rebuild (Part 2 §1.1, §5).

---

## 5. Surface area

**Routes** (`app/main.py:528-541` mounts every router):

- **Pages/health:** `GET /` → `static/index.html`; `GET /channel` → `static/channel.html`; `GET /health` → `{"ok": True, "dry_run": …}`; `GET /health/jobs` → `{"jobs": {<job_id>: {status, last_run_at, error, failed_channels, partial_errors}}}`; `GET /autoshorts` (`app/shorts/autoshorts.py:85`); `/static/*`.
- **Auth/channels** (`app/auth.py`, prefix `/auth`): `GET /auth/login`, `GET /auth/callback` (stores tokens, sets `analytics_authorized` from granted scopes, clears the `token_expired` pause), `GET /auth/channels`, `PATCH /auth/channels/{id}` (enabling `measurement_enabled` returns 409 unless `reach.certify` passes, `app/auth.py:166-174`).
- **Sync** (`app/sync.py`): `POST /channels/{id}/sync?full=`, `POST /channels/{id}/refresh-stats`, `POST /channels/{id}/refresh-applied-stats`, `GET /channels/{id}/videos`, `GET /videos/{id}`.
- **Audits** (`app/audits.py`): `GET|POST /channels/{id}/audit-config`, `POST /channels/{id}/audit-config/elaborate`, `POST /videos/{id}/audit`, `GET /videos/{id}/audits`, `POST /audits/{id}/apply`, `POST /channels/{id}/audits/apply-pending`, `POST /channels/{id}/audits/reaudit-quarantined`, `POST /channels/{id}/audits/run-bulk`, `POST /audits/{id}/revert` (409 `"quota_insufficient: revert needs <n> units, <m> remaining today"` when `quota.can_afford(quota.cost(Op.VIDEOS_UPDATE))` is false, `app/audits.py:830-837`), `GET /quota-cost-preview`.
- **Measurement** (`app/measurement.py`): `GET /audits/{id}/measurement`, `GET /channels/{id}/outcomes`, `POST /measurement/evaluate`.
- **Reflection** (`app/reflection.py`): `GET /channels/{id}/reflection/history`, `POST /channels/{id}/prompt-versions/{vid}/promote`, `POST /channels/{id}/reflection/trigger`, `GET /channels/{id}/reflection/shadow-comparison`. Promote and trigger return 409 `"Reflection is frozen: REFLECTION_ENABLED=false"` while frozen (`_require_reflection_enabled`, `app/reflection.py:792`).
- **Playlists** (`app/playlists_router.py`): `POST /channels/{id}/playlists/evaluate`, `GET /channels/{id}/playlists/health`, `POST /channels/{id}/playlists/bootstrap` (sync + embed all), `GET /channels/{id}/playlists/status`, `POST /channels/{id}/playlists/reconcile` (409 `"Playlist reconcile writes are frozen: PLAYLIST_RECONCILE_WRITES_ENABLED=false"`, `:263-267`), `GET /channels/{id}/playlists/proposals`, `POST /channels/{id}/playlists/proposals/decide` (executes adds/removes on YouTube; not frozen).
- **Autopilot** (`app/autopilot.py`): `POST /channels/{id}/autopilot/resume`, `GET /channels/{id}/autopilot/log`.
- **Ops:** `GET /dashboard` (`app/dashboard.py:94`), `GET /quota` (`app/quota.py:295`), `GET /channels/{id}/performance`, `/performance/summary`, `/performance.csv` (`app/performance.py`).
- **Shorts** (`app/shorts/routes.py`, prefix `/shorts`): `POST|GET /shorts/jobs`, `POST /shorts/cut`, `GET /shorts/languages`, `POST /shorts/jobs/clear-failed`, `GET /shorts/jobs/{id}`, `GET /shorts/clips/{id}/file`, `POST /shorts/clips/{id}/upload`, `POST /videos/{id}/short`; `POST /autoshorts/jobs` (`app/shorts/autoshorts.py:49`).

**Modules** (`app/`):

| File | Owns |
|---|---|
| `main.py` | FastAPI app, logging, job registration, per-channel fan-out, `video_sync` wrapper |
| `job_status.py` | `JobRunFailed`, `item_error_verdict`, in-memory registry behind `/health/jobs` |
| `config.py` | `Settings` (env) |
| `db.py` | thread-local PostgREST (`supabase-py`) client with retry. The app talks to Postgres only via PostgREST on `SUPABASE_URL` |
| `rows.py` | the 1000-row cap: `all_rows`, `all_rows_parallel`, `rows_for_ids` |
| `channel_audits.py` | `audits_for_channel`; `fetch_all` is a deprecated alias of `rows.all_rows` |
| `eligibility.py` | which channels each job runs for (`Job.*`, `can_audit`, `can_cut_shorts`, `has_work`) |
| `status_vocab.py` | persisted status strings and their mirrors (guarded by `tests/test_status_vocab.py`) |
| `auth.py` | OAuth + channel flag PATCH |
| `sync.py` | video sync, `is_short` probe, stats refresh, routine-sync rules (`is_stale`, `needs_full_sync`, `routine_sync`); token failures in its routes → `TokenExpired` (401 `token_expired`); full syncs feed the human-edit ledger (`_record_human_edits`) |
| `content_type.py` | `is_episode` classifier |
| `audits.py` | `DEFAULT_PROMPT`, `_build_user_block`, strategy stamp, `audit_video`, apply, revert, bulk ops |
| `audit_suggestion.py` | LLM output contract: decode, 15-hashtag cap, `rejection()`, `house_format_spec()` |
| `apply_outcome.py` | typed `ApplyError`/`ApplyOutcome` |
| `youtube_metadata.py` | `videos.update` payload; `_NON_ISO_639_1 = {"bgc": "hi"}` (`:58-60`) |
| `youtube_client.py` | Data API wrappers + quota charging |
| `quota.py` | unit-cost table, daily ledger, `JobBudget`, `/quota` |
| `analytics_client.py` | on-demand Analytics (views/retention, playlist session metrics) |
| `reporting_client.py` / `reporting_poll.py` | Reporting API jobs (`ensure_job` per report type; `ensure_reach_job`, `ensure_traffic_job`, `ensure_playlist_traffic_job`), CSV parsing (reach; video and playlist traffic with aggregation, `_aggregate_traffic_csv`, and the `TRAFFIC_SOURCE_TYPES` code→name table), reach ingestion → `video_reach_daily`, `video_metrics` backfill; the shared latest-wins day replace (`replace_data_day`, `superseded_reports`, `record_ingested`) |
| `human_edits.py` | B3a human-edit ledger, description links: `video_links` (11-character ids from `watch?v=`, `youtu.be/`, `shorts/`, `embed/`, `live/`, `v/` URLs), `made_by_midas` (the description equals an applied audit's `suggested_description` or a reverted one's `description_before`, whitespace collapsed; the seam for Slice 1's `origin='midas'` interventions), `record_description_edits` (diff, keep targets in `videos` on any channel, write `human` backlinks rows with a `ledger_key`, stamp removals on the earlier row). Called only from `sync_channel` on a full sync. B3b, playlist memberships: `added_by_midas` (a `playlist_assignments` `added` row whose `decision_source` isn't `sync`, i.e. `embedding`, `llm_confirmed` or `discovery`, or an `approved` `add` `playlist_proposals` row; never `playlists.origin`), `record_playlist_additions` (write `human` playlist rows with a `ledger_key`). Called only from the membership walk (`app/playlists_sync.py`). Both write through `_record_human` |
| `traffic_poll.py` | B1 daily traffic-source ingestion → `video_traffic_source_daily`, `playlist_traffic_daily` |
| `interventions.py` | B2: `assign_arm` (sha256 of `video_id`, lever vs `HOLDOUT_PCT`), `active_for` (the video's open `midas` intervention), `record` (refuses a second open `midas` one with `ActiveInterventionExists`, and a `human` one with an arm other than `n/a`; a concurrent second insert is refused by the partial unique index as a PostgREST unique-violation error, not `ActiveInterventionExists`). With `ledger_key` it upserts `on_conflict="ledger_key", ignore_duplicates=True` and returns None for a key already stored. Caller: `app/human_edits.py` |
| `reach.py` | data-day windows, coverage, frontier, staleness, `certify` |
| `metrics_poll.py` | daily Analytics poll |
| `measurement.py` / `verdicts.py` | title verdicts, `measurement_result` shape, rollups |
| `performance.py` | per-channel performance table/CSV |
| `dashboard.py` | `/dashboard`; `_aggregate_legacy` kept as fallback/oracle for the RPC |
| `reflection.py` | weekly per-channel prompt rewrite (shadow/live/auto) + auto-revert; `derive_niche_queries`, `_sample_competitors` (frozen) |
| `transcripts.py` | transcript fetch + `video_transcripts` cache; `lang_display_name` (`_LANG_NAMES`, `:24-31`); Data API captions fallback |
| `embeddings.py` / `openrouter.py` | embeddings and `chat_json`/`chat_text` via OpenRouter |
| `playlists.py` | similarity engine: `join_pass` (call commented out, `app/autopilot.py:438-439`), `reconcile_channel`, `tune_thresholds`, `_llm_judge` |
| `playlists_sync.py` | playlist inventory sync, budgeted membership walk, role heuristic; hands memberships new since a playlist's previous walk to the human-edit ledger (`_record_human_memberships`) |
| `playlist_discovery.py` | weekly orphan clustering → creates playlists (frozen) |
| `playlist_health.py` | playlist health scorer (recommend-only) |
| `playlists_router.py` | playlist HTTP endpoints |
| `autopilot.py` | the tick loop |
| `tracing.py` | OpenTelemetry → Phoenix spans (off by default) |
| `backup.py` / `provision.py` / `services/nas_service.py` | NAS snapshot, restore-on-empty, SMB client |
| `keyframes.py` | dead: not imported anywhere in `app/` or `scripts/` |
| `shorts/*` | Shorts cutter (NAS source), dispatcher, worker, upload. `shorts/cutter/download.py` gated off (`SHORTS_YT_DOWNLOAD_ENABLED=false`) |
| `static/*` | vanilla-JS dashboard |

**Scripts:** `scripts/create_reporting_job.py` (`--report-type`, default `channel_reach_basic_a1`),
`scripts/probe_reporting.py`, `scripts/probe_analytics.py`, `scripts/verify_reach_coverage.py`,
`scripts/apply_migrations.py`, backfills, and the Phase A live probes in `scripts/probes/`
(`probe_traffic_source_report.py` defaults to `channel_traffic_source_a3` since 2026-10-06,
`scripts/probes/probe_traffic_source_report.py:61`).

---

## 6. Prompts and LLM calls

- **Audit prompt**: `app/audits.py:44` `DEFAULT_PROMPT`, used when the channel has no `audit_configs.generated_prompt`.
  Precedence: `prompt_override` > `shorts_prompt` (if `is_short`) > `generated_prompt` > `DEFAULT_PROMPT`
  (`app/audits.py:368-375`). Per-channel `generated_prompt` text lives in the DB, not the repo. Verbatim:

  ```
  You are a YouTube SEO expert for nursery-rhyme / kids 3D-rhyme channels.
  Audit this video's metadata and rewrite it to a FIXED house format.

  CONTENT SOURCES
  You will receive the current title/description/tags (often placeholder or
  inadequate) and the video transcript when available (in any language — content
  signal only). Treat the transcript as the primary source of truth for what the
  rhyme is actually about. The current metadata is a starting point, not a
  constraint — rewrite freely to reflect the real content.

  LANGUAGE
  The user message states the channel's configured regional language. Output is
  BILINGUAL: an English layer AND a regional-language layer, exactly as laid out
  below. Never let the transcript's language override the channel's configured
  language.

  {house_format_spec()}

  Rules:
  - Put the fully-formatted multi-line description (all 5 blocks, real newlines) in
    comparisons.description.suggested.
  - Be specific and actionable, not generic. Preserve the channel's voice.
  ```

  `house_format_spec()` (`app/audit_suggestion.py:49-94`), rendered with `TITLE_MAX=100`, `HASHTAG_LIMIT=15`,
  `TAGS_TOTAL_CHARS_MAX=500`, `TAGS_MAX=30` (`app/audit_suggestion.py:36-40`):

  ```
  === REQUIRED TITLE FORMAT ===
  [Regional rhyme name] | [English rhyme name] | [theme] Nursery 3D Rhymes
  - Keep the whole title under 100 characters.
  - Regional name in the channel's language/script; English name in English.
  - theme = one short topical hook drawn from the rhyme (e.g. Colors, Animals,
    Bath Time, Counting).

  === REQUIRED DESCRIPTION FORMAT (this exact order) ===
  1. First line: exactly 3 hashtags (these surface above the title).
  2. English description: 2-4 keyword-rich sentences about the rhyme.
  3. Regional description: the same, in the channel's regional language, keyword-rich.
  4. Keywords: one line of high-value search phrases (comma-separated), English + regional.
  5. Final line(s): exactly 12 hashtags.
  - TOTAL hashtags across the whole description must be EXACTLY 15. Never exceed
    15 — YouTube ignores ALL hashtags on a video that has more than 15.

  === TAGS ===
  - A list mixing broad and specific tags, English + regional. Maximize coverage up
    to ~500 characters total (YouTube's tag limit) — roughly 30 tags.

  Return strictly a JSON object with this exact shape:
  {
    "comparisons": {
      "title":       { "current_problems": "what's weak about the current title", "suggested": "your rewrite in the required title format", "why_better": "1-2 sentences" },
      "description": { "current_problems": "what the current description is missing or doing badly", "suggested": "the FULL multi-line description following all 5 blocks above", "why_better": "..." },
      "tags":        { "current_problems": "gaps or noise in the current tag list", "suggested": ["tag1","tag2",...], "why_better": "..." }
    },
    "issues":   [ { "field":"title|description|tags", "severity":"high|medium|low", "problem":"...", "fix":"..." } ],
    "reasoning": "short overall summary"
  }
  ```

- **`_build_user_block()`**, verbatim (`app/audits.py:144-193`):

  ```python
  def _build_user_block(
      video: dict,
      transcript: str | None,
      transcript_lang: str | None,
      channel_language: str,
  ) -> str:
      """Audit user message: language rule first, then metadata, transcript."""
      channel_lang_name = lang_display_name(channel_language)
      transcript_lang_name = lang_display_name(transcript_lang)

      lines = [
          "LANGUAGE RULE (non-negotiable):",
          f"  Channel configured language: {channel_language} ({channel_lang_name}).",
          "  The transcript is a CONTENT SIGNAL ONLY — use it to understand what the",
          "  video is about. Do NOT use its language for output.",
          f"  ALL output (title, description, tags) must target a {channel_lang_name}-speaking",
          f"  audience. Use whatever mix of {channel_lang_name} and English performs best on",
          "  YouTube for this content type and audience — your editorial call.",
          "  NEVER let the transcript language override the channel's configured language.",
          "",
          "VIDEO METADATA (CURRENT — may be placeholder or inadequate):",
          f"Title: {video.get('title') or ''}",
          f"Description: {(video.get('description') or '')[:1500]}",
          f"Tags: {', '.join(video.get('tags') or [])}",
          f"Views: {video.get('view_count', 0)}",
          f"Likes: {video.get('like_count', 0)}",
          f"Published: {video.get('published_at') or ''}",
      ]

      if transcript:
          lines += [
              "",
              f"VIDEO TRANSCRIPT (detected language: {transcript_lang_name} — content signal only):",
              transcript,
          ]
      else:
          lines += [
              "",
              "VIDEO TRANSCRIPT: not available — base content judgment on metadata only.",
          ]

      lines += [
          "",
          "The current title and description may be placeholder or poorly written.",
          "Use the transcript as the primary signal for what the video is about.",
          "Generate metadata that reflects the actual content — do not just polish what's already there.",
          "",
          "Run the audit now and return only the JSON object.",
      ]
      return "\n".join(lines)
  ```
  - A missing `default_language` makes `audit_video` refuse with 400 (`app/audits.py:390-402`); `eligibility.can_audit` gates such channels out of autopilot (`app/eligibility.py:66-84`).
  - The user block carries no CTR, impressions or traffic-source data; it carries lifetime `view_count` and `like_count`.

- **Audit output handling.** `AuditSuggestion._make` applies `cap_description_hashtags` (keeps the first 15,
  Indic-safe regex `#[^\s#]+`) on every construction path (`app/audit_suggestion.py:46,97-118,143-147`).
  `rejection()` checks title 1–100 chars, description 1–5000 chars, tags a list of strings, ≤30 tags, ≤500 total
  tag chars (`app/audit_suggestion.py:211-230`); it does not check for fewer than 15 hashtags. There is no
  "no change" output: every audit is a rewrite.

- **Strategy stamp** (`app/audits.py:199-286`). `strategy_version(prompt_text, prompt_source, prompt_version_id=None)`
  returns `f"{settings.STRATEGY_LABEL}-{_strategy_hash(inputs)}"`, the hash being the first 12 hex of sha256 over
  `json.dumps(inputs, sort_keys=True, separators=(",", ":"))`. `inputs` = `label`, `prompt_source`
  (`override|shorts|generated|default`; anything else raises `ValueError`), `prompt_sha256` (of the system prompt
  actually sent), `audit_model` (`settings.AUDIT_MODEL`), `decision_question_set_version` (`"none"`),
  `prompt_version_id`, plus `writer_model` only if a `WRITER_MODEL` setting exists (it doesn't).
  `_stamp_strategy` upserts `{version, prompt_template, model: settings.AUDIT_MODEL, config: inputs, status:
  "champion", notes: "auto-registered by _stamp_strategy (derived from config)"}` with `ignore_duplicates=True`,
  once per version per process. `prompt_template` is one of `"audit_video prompt_override (caller-supplied, e.g.
  reflection shadow candidate)"`, `"audit_configs.shorts_prompt (per-channel)"`, `"audit_configs.generated_prompt
  (per-channel)"`, `"code:app/audits.py DEFAULT_PROMPT"` (`app/audits.py:216-221`).

- **Other LLM calls** (all via OpenRouter, `app/openrouter.py`; `chat_json`/`chat_text` default to
  `settings.AUDIT_MODEL`, `app/openrouter.py:93,175`):

  | Call | Model | Path | Prompt |
  |---|---|---|---|
  | Audit | `settings.AUDIT_MODEL` | `audit_video` → `chat_json(user, system=audit_prompt)` (`app/audits.py:416`) | above + DB `audit_configs` |
  | Prompt elaboration | `settings.PROMPT_GEN_MODEL` | `POST /audit-config/elaborate` | `app/audits.py:107-125` (renders `house_format_spec()`) |
  | Niche queries | hardcoded `anthropic/claude-haiku-4.5` | reflection (frozen) | `app/reflection.py:264-272`, below |
  | Platform guidance | hardcoded `perplexity/sonar` via `chat_text` | reflection (frozen) | `app/reflection.py:346-352`, below |
  | Reflection candidate prompt | `settings.REFLECTION_MODEL` | reflection (frozen) | `app/reflection.py:465-507` |
  | Playlist membership judge | `JUDGE_MODEL = "anthropic/claude-haiku-4.5"` | `reconcile_channel` (frozen) and dead `join_pass` | `app/playlists.py:206-213`, below |
  | Playlist title/description proposal | `JUDGE_MODEL` | `discover_playlists` (frozen) | `app/playlist_discovery.py:137-142`, below |
  | Embeddings | `EMBED_MODEL = "google/gemini-embedding-2-preview"` | `embed_video` after apply; `bootstrap_embeddings` | input: title + `"\n\n"` + transcript[:6000] (`app/embeddings.py:112-114`); bootstrap passes `use_transcript=False`, so title only (`app/embeddings.py:176`) |

  Verbatim short prompts:
  ```
  # niche queries (app/reflection.py:264-269)
  This YouTube channel's most-used tags: {top_tags}
  Sample video titles: {titles[:10]}

  Produce 2-3 YouTube search queries that would find similar channels and videos. Be specific to the actual content niche, not the broad category. Return JSON: {"queries": ["query1", "query2"]}

  # platform guidance (app/reflection.py:346-350)
  What are the current best practices for YouTube metadata optimisation (titles, descriptions, tags) for {niche_description} channels in 2025? Focus on what drives search discovery and click-through rate. Be specific and practical.

  # membership judge (app/playlists.py:206-213)
  Playlist: "{playlist["title"]}"
  Playlist description: "{playlist.get("description") or ""}"
  Sample members:
  {members_str}

  Candidate video: "{video["title"]}"

  Does this video thematically belong in this playlist? Answer JSON: {"belong": true/false, "reason": "one sentence"}

  # playlist proposal (app/playlist_discovery.py:137-142)
  These YouTube videos form a thematic cluster:
  {titles_str}

  Propose a concise, descriptive YouTube playlist title and a one-sentence description that captures what they have in common. Answer JSON: {"title": "...", "description": "..."}
  ```
  The judge and proposal prompts carry no `default_language` rule.

- **Models in use.** Code defaults: `AUDIT_MODEL=anthropic/claude-haiku-4.5`, `PROMPT_GEN_MODEL=google/gemini-2.0-flash-001`,
  `REFLECTION_MODEL=anthropic/claude-sonnet-4-6`. Dev `.env`: `google/gemini-3.7-flash`,
  `anthropic/claude-opus-5:online`, `anthropic/claude-sonnet-5`. Office `.env`: blank (not read).

---

## 7. Delta vs the specs

Spec = `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md`. "Part 2" is the design as amended by
§0.6 (P1–P7); "Part 3" is Phase B, the Part marked ready to build.

### 7.1 Spec'd but not built

**Phase B (Part 3)**
- **B1 traffic-source ingestion: office acceptance.** Both halves are built (§2, §4: `traffic_poll`,
  `video_traffic_source_daily`, `playlist_traffic_daily`) and not deployed. The office acceptance (Marathi rows
  from the backfill to the frontier minus 2 days, `traffic_poll` `success`) is B9a. The aggregated rows-per-day
  figure for the findings doc and the retention decision wait for a week of data.
- **B2 `interventions` + holdout: office acceptance.** Built (§2, §3, §5) and not deployed; the acceptance is
  applying `20261006020000` on the office machine (B9). Its only writer is the B3 human ledger.
- **B3 human-edit ledger: office acceptance.** Both halves built (§2, §4, §5: `app/human_edits.py`; B3a description
  links, B3b playlist memberships) and not deployed; the office acceptance is applying `20261006030000` (after
  `20261006020000`) and, after a week, at least one `human` intervention (B9, exit gate). B3b adds no migration.
  *Scope of B3b:* the walk runs only inside `playlist_reconcile`, i.e. for the four allowlisted channels
  (`app/config.py:145-155`; Marathi is in the default). Membership detection for any other channel needs it added
  to `PLAYLIST_RECONCILE_CHANNELS`. B3a sees an old video's edit only on a full sync, every 3 days
  (`app/sync.py:520`).
- **B4 warm filter.** Not built. The picker is newest-first with no impressions filter
  (`supabase/migrations/20260904000100_next_audit_candidate_exclude_episodes.sql:37`
  `order by v.published_at desc, v.id`) and excludes in-window audits rather than active interventions
  (`:35-36`). No `WARM_*` settings.
- **B5 `app/decide.py` + `decision_log`.** Not built. `DECISION_QUESTION_SET_VERSION = "none"` is the placeholder
  B5 replaces (`app/audits.py:199`). No `DECIDE_BACKEND`.
- **B6 scoped re-embed.** Not built. One `model_version` (= `EMBED_MODEL`) holds vectors from two input recipes
  (title + transcript vs title only, §6), neither the spec's title + description + tags. Thresholds are still
  process-global (`app/playlists.py:518`).
- **B7 missing `default_language`.** Code half not built: no `bho`/`raj` in `_LANG_NAMES`
  (`app/transcripts.py:24-31`) or `_NON_ISO_639_1` (`app/youtube_metadata.py:58-60`). Data half: six channels
  NULL on 2026-10-06 (§1).
- **B9/B10.** Nothing to deploy; this file is B10's only output so far.
- **B2's persistence of the A8 registry** ("Persisting it is Phase B work", Part 1 A8): not built; registry is
  in-memory (`app/job_status.py`).

**Slice 1 (Part 2 §1–§2, §3.4, §6.1)**
- Tick routing on `agent_enabled` (§6.1): not built. The column exists (B2) and nothing reads it.
- Rules triage, `no_change` as a `declined` intervention (§2.2): not built.
- Backlink candidate pipeline, fleet siblings (P2, `SIBLING_MIN_VIEWS`), Jev next-watch scoring (§2.3): not built.
- Code checks for links (§2.4): not built. Partially present: `DESCRIPTION_MAX = 5000`, the 15-hashtag cap and
  `rejection()` (`app/audit_suggestion.py`).
- Canonical backlink block renderer (§3.4) and description-only apply (§2.5): not built. `build_update_payload`
  always takes title, description, tags (`app/youtube_metadata.py`).
- Weekly lever measurement with holdout (§1.3), the P1 stop rule (`BACKLINK_EXPERIMENT_WINDOWS`), the §1.7
  `insufficient_data` extension: not built.
- `reach_warmup` on human-run channels (§1.4): not done; all 13 have `reach_warmup = f` (A7, 2026-10-06).

**Slice 2 (Part 2 §4)**
- The P3 curated-playlist test: not built. Jev fit check replacing `playlists._llm_judge`: not built.
- Short → video links recommend-only to the team (P4): no code path.
- Per-channel auto-apply flip for playlist adds: not built (`PLAYLIST_HITL` is one global setting,
  `app/config.py:109`).

**Slice 3 (Part 2 §3)**
- `app/agent/loop.py`, `openrouter.chat_tools`, `AGENT_MAX_TURNS`, tools (`get_traffic_mix`, `get_search_terms`,
  `get_niche_reference`, `get_channel_playbook`, `submit_change`, `decline`): none exist.
- `WRITER_MODEL` and the writer bake-off (§3.3): not built (the stamp reads it via `getattr`, `app/audits.py:247`).
- Title objective aimed at browse/suggested CTR (P5): not built; the house format optimises for search
  ("keyword-rich sentences", "high-value search phrases", `app/audit_suggestion.py:74-76`).
- Niche reference (§3.6): no `app/niche_reference.py`, no `niche_reference_refresh` job, no `channels.niche_reference_*`
  columns. `derive_niche_queries` and `_sample_competitors` still live in the frozen `app/reflection.py:239-339`.

**Slice 4 (Part 2 §5)**: no `channels.playbook_json`, no distiller, no weekly rebuild; `reflection.py` not retired.

**Slice 5 (Part 2 §6)**: no per-channel quota shares in `JobBudget`.

### 7.2 Built but not spec'd

| Item | Where | Note |
|---|---|---|
| Title measurement loop (21-day CTR verdicts, `awaiting_window` stamping on apply) | `app/measurement.py`, `app/verdicts.py`, migration `20260702183233` | Kept only indirectly ("Title … CTR vs a comparable window … Built", Part 2 §1.2). Its windows are not the spec's weekly cadence (7.3) |
| Prompt reflection loop (weekly `generated_prompt` rewrite, `prompt_versions` shadow/live/auto, shadow audits, auto-revert on cohort median) | `app/reflection.py`, `prompt_versions` | **Frozen** (`REFLECTION_ENABLED`). Spec scraps it as the memory (Part 2 §0.5 item 3) and retires it in Slice 4 (§5) |
| Similarity playlist engine: daily add/remove, `tune_thresholds`, `join_pass` | `app/playlists.py` | Add/remove and tuning **frozen**; `join_pass` call commented out (`app/autopilot.py:438-439`) |
| Weekly orphan-cluster playlist **creation** | `app/playlist_discovery.py` | **Frozen** (`PLAYLIST_DISCOVERY_ENABLED`). Spec: "New-playlist creation … stay human-confirmed" (Part 2 §4) |
| Competitor sampling via `search.list` (100u each) and Perplexity guidance | `app/reflection.py:301-352` | Frozen with reflection. Spec moves the competitor half to Slice 3's niche reference |
| `video_traffic_source_playlist` table + tier-2 poller | `20260618133036_…`, `app/metrics_poll.py:85,228` | Disabled (`TIER2_TRAFFIC_SOURCE_SUPPORTED = False`); never populated. Superseded by `playlist_traffic_daily` (B1b), which is populated; the old table and poller are still in the code |
| Playlist health scorer (tier-1 percentile bands) | `app/playlist_health.py`, `docs/PHASE_1B_PLAN.md` | Kept by Part 2 §0.5 ("inventory, health …") but no stage uses it |
| `video_sync` daily job | `app/main.py:243-267,365-376` | Added 2026-10-01 after the A0 pause stopped sync (`docs/PHASE_A_FINDINGS.md` "Phase A conclusion" §3.6). Not in any Part, though B3 depends on sync |
| Shorts cutter (NAS source, worker queue, autopilot Shorts, upload) | `app/shorts/*`, 7 migrations | Separate product line; the spec only says Shorts uploads continue (Part 2 §6.1). Uploads are not charged to the quota ledger (`app/shorts/youtube_upload.py` has no `can_afford`) |
| Self-hosted Postgres + PostgREST, nightly NAS snapshot, restore-on-empty | `app/backup.py`, `app/provision.py`, `docker-compose.yml`, `docs/SELF_HOSTED_DB.md` | Infra; the spec references it only in Part 3's schema discipline |
| OTel/Phoenix tracing | `app/tracing.py`, `docs/OBSERVABILITY.md` | Spec reuses it for the agent (Part 2 §3.1) |
| Egress RPCs with in-app parity fallbacks | migrations `202607*`, `app/dashboard.py`, `app/autopilot.py:92-106` | Supabase free-tier era |
| Transcript cache + captions-API fallback (250u per video) | `app/transcripts.py`, `video_transcripts` | Quota exposure unspecified |
| Episode exclusion | `app/content_type.py`, migrations `20260904*` | Matches Part 2 §2.1 "not an episode" |
| `/dashboard`, `/performance*`, `/autoshorts` UIs | `app/dashboard.py`, `app/performance.py`, `app/static/*` | |
| Dead code: `app/keyframes.py`, `video_keyframes`, `audits.keyframes_extracted`, `videos.thumbnail_optimized_at`/`playlists_optimized_at`, statuses `approved`/`rejected`, `outcome_decision='redo_queued'`, `redo_of_audit_id`, `MAX_REDO`, `AUTO_REVERT_ON_REGRESSION`, `PLAYLIST_MEASUREMENT_WINDOW_DAYS`, `playlists.strategy_version` | various | Pre-spec reservations nothing writes or reads |

### 7.3 Built differently from the spec

1. **Strategy stamp timing (Part 1 A6, Part 2 §8).** Spec: derive at startup from the `DEFAULT_PROMPT` hash and the
   per-channel prompt-version id. Built: derived per audit, hashing the prompt text actually sent and its source
   (`app/audits.py:224-253`), so shorts/override/generated audits stamp differently. Audits before A6 still carry
   `2026.07-baseline-v1`.
2. **Measurement cadence (Part 2 §1.1, §1.7).** Spec: weekly windows, extended once to 14 days. Built: symmetric
   21-day pre/post windows (`MEASUREMENT_WINDOW_DAYS`, `app/reach.py:60-82`) plus `ROLLOVER_SLOP_DAYS=1`, judged
   on CTR only.
3. **Dormancy (Part 2 §2.1).** Spec: keep dormant videos out at selection. Built: dormancy is found only after the
   window (`REASON_DORMANT`, `app/measurement.py:280`); the picker is newest-first (7.1 B4). A7 (2026-10-06):
   4,254 applies landed on dormant videos.
4. **Embedding input (Part 3 B6).** Spec: one recipe (title + description + tags) for every video. Built: two
   recipes under one `model_version` (§6), so `model_version` does not identify the input.
5. **Playlist thresholds (Part 2 §4, B6).** Spec: per channel. Built: process-global, and `tune_thresholds`
   overwrites the global from one channel (`app/playlists.py:518`), frozen.
6. **Discovery provenance.** Created playlists are stored as `origin='inherited'` (`app/playlist_discovery.py:200-205`),
   so a human-edit ledger (B3) could not tell Midas-created playlists from human ones by `origin`. B3b reads
   `playlist_assignments` (`decision_source='discovery'`) instead (`app/human_edits.py` `added_by_midas`).
7. **Traffic ingestion details (Part 2 §7, Part 3 B1).** `video_traffic_source_daily` has an `id bigserial`
   column the spec's list lacks (`app/rows.py` pages in `id` order). The shared ledger gained `report_type`
   (not in the spec) so traffic reports don't count as reach coverage or as reach reissues (`app/reach.py:122-130`,
   `app/reporting_poll.py:85`). Restatements: when a data-day's original and restated reports are both new, only
   the newest by `createTime` (parsed, not compared as text, `app/traffic_poll.py:83` `_created`) is ingested
   (`app/traffic_poll.py:89`); the spec says only that the newer replaces.
   `playlist_traffic_daily` also has an `id bigserial`. The two report types are ingested as isolated feeds of one
   job: a crash in one feed fails the channel's run but doesn't stop the other (`app/traffic_poll.py:155`); the spec
   says only "same failure semantics as `reporting_poll`".
   **Deploy order:** the reach path now reads and writes `report_type`, so `20261006000000` must be applied (and
   PostgREST restarted) before the app restarts on this code, or `reporting_poll` and `measurement_eval` fail.
   Apply `20261006010000` in the same window: without `playlist_traffic_daily` the playlist feed fails every
   report, so `traffic_poll` fails Marathi daily (video rows still land).
8. **Apply cost.** `quota.APPLY` = 51u (`app/quota.py:67`) but apply no longer fetches stats (`app/audits.py:535-543`):
   the gates overestimate by 1u. Spec Part 1 A10 says note it only.
9. **`interventions` DDL (Part 2 §7, Part 3 B2).** The spec lists columns only. Built with `not null` on
   `video_id`, `channel_id`, `lever`, `origin`, `arm` and `status`, `video_id → videos on delete cascade` (as
   `audits`), `created_at default now()`, and a partial unique index that makes §1.6 hold in the database as well
   as in `record` (`supabase/migrations/20261006020000_interventions.sql`). Vocabularies are checked in Python
   (`app/interventions.py` `_require`), not by SQL `check` constraints, as for `audits.status`.
10. **Human-edit ledger details (Part 2 §1.4, Part 3 B3; B3a).** `interventions` gained `ledger_key text` with a
   unique index (`20261006030000`), which Part 2 §7 doesn't list, so a rerun or a racing sync can't duplicate a row.
   "Links to our videos" means any video in `videos`, on any channel, not only the source's channel
   (`app/human_edits.py` `_our_videos`), since sibling channels link into each other (P2), plus the videos fetched
   in the same sync (`also_ours`: the ledger runs before the upsert). A target on a channel with no synced videos
   (Kannada, Telugu, §1) is not ours to the ledger, and that link is not recorded. A link from a video to
   itself is ignored. A removed link creates no row: it is listed in `removed_targets` of any addition seen in the
   same edit, and stamped as `payload.removed_detected_at` on the link's earlier ledger row; a removal of a link
   older than the ledger is not stored anywhere. "Midas made the change" is the new description equalling (with
   whitespace collapsed) an applied audit's `suggested_description` or a reverted audit's `description_before`
   (`made_by_midas`); on a match the whole description change is skipped, additions and removals alike. An apply
   whose description was overridden in the request body isn't recognised, because the applied text isn't stored on
   the audit (`app/audits.py:507-515`). Only full syncs re-read old videos, so incremental syncs record nothing, and a
   video the team edits and Midas then rewrites within one full-sync interval is seen only as Midas's.
   **Deploy order:** apply `20261006030000` with `20261006020000`, before the app restarts on this code, and restart
   PostgREST. Without it every ledger write fails (no `ledger_key` column); the sync still succeeds and logs the
   error per video, but no human edit is recorded until the migration lands, and edits synced meanwhile are lost.
11. **Human-edit ledger, playlist memberships (Part 3 B3.2; B3b).** "Newly added" is "the walk has no
   `playlist_assignments` row of any action for the (video, playlist) pair", which is what the walk already used
   to decide what to seed (`app/playlists_sync.py:297-307`); the walk has no removal detection, so a video the
   team removes and re-adds, or that Midas once removed, is never seen as new. Baseline rule (the spec has none): a
   playlist with `membership_walked_at` NULL at plan time, including one new to the DB, is walked as a baseline and
   records nothing, so a human add made before a playlist's first walk is never recorded. Playlists the walk has
   already stamped (`20260812000000`) are not re-baselined after deploy: their existing memberships already have
   `sync` rows. Only the channel's own videos count (the walk's `known_videos`), and a membership of a video not yet
   in `videos` is skipped; when that video is synced later the next walk of the playlist records it, even if the
   add predates the previous walk. "Midas added it" counts every non-`sync` `added` assignment and every approved
   `add` proposal, including those a person approved through `/playlists/proposals/decide`. Detection timing:
   `detected_at` is the walk that saw it, which re-reads a playlist only when its item count changes or every
   `PLAYLIST_FULL_WALK_DAYS` (30), within `PLAYLIST_SYNC_QUOTA_BUDGET`; an equal-count swap waits for rotation. The
   payload's `timing` says so. A walk cut short by the budget mid-playlist has already recorded the pages it read
   (the ledger runs per page).

### 7.4 Contradictions within the spec

- **`agent_enabled` and Part 2 §7.** Part 3 B2 adds `channels.agent_enabled` (built, `20261006020000`), but
  Part 2 §7 says `bool default false` where B2 says `bool not null default false` (built as B2 says), and B4's
  warm filter omits it while §2.1's eligibility requires it (B4 defers it to Slice 1's tick routing). Part 2 §7,
  headed "Data model (Phase B)", also lists the Slice 3 `niche_reference_*` columns.
- **Re-embed scope.** Part 2 §4: "Embed one consistent input for every video". Part 3 B6: the rollout channel and
  its siblings only. Part 3 says Part 2 "is corrected in the same change"; it wasn't.
- **Sibling detection vs ingestion scope.** P2 / Part 2 §2.3 define a sibling by suggested traffic "to, or …
  from" the source channel over 28 days of `video_traffic_source_daily`. B1 ingests only
  `TRAFFIC_INGEST_CHANNELS` (default: Marathi), so traffic from Marathi into other channels is never ingested, and
  "either direction" (§8 `SIBLING_MIN_VIEWS`) can't be measured until widening.
- **Playbook storage.** Part 2 §5 puts it in `channels.playbook_json`; Part 2 §7 (data model) doesn't list it.
- **Warm window definition.** §8 `WARM_WINDOW_DAYS` = 28 "ingested data-days", and A7's query is labelled
  "28 ingested days", but the query uses `date > current_date - 30` (calendar days). B4's acceptance compares
  against that query's 566.
- **Intervention status vs measurement status.** Part 2 §7 gives `interventions` both `status` and
  `measurement_status`; B2's lifecycle statuses (`planned`, `applied`, `measuring`, `judged`, `cancelled`) put
  measurement state into `status` too, reusing strings already in `AuditStatus` and `MeasurementStatus`. B2 also
  lists `insufficient_data`, which §1.7 describes as a measurement outcome, and `holdout`, which is also an `arm`
  value. As built, all eight are `InterventionStatus` values (`app/status_vocab.py:184-210`) and
  `measurement_status` has no vocabulary; Slice 1's measurement decides how the two columns split.
- **What counts as a Midas edit in B3.** B3 skips "every apply" in Phase B, yet Phase B allows no applies. The
  manual paths that still write to YouTube (`POST /audits/{id}/apply`, `/apply-pending`,
  `/playlists/proposals/decide`) are human-triggered through Midas: B3 doesn't say whether they are `human` or
  `midas`. As built (B3a), a description written by any apply or revert counts as Midas's, however it was
  triggered (`app/human_edits.py` `made_by_midas`); likewise (B3b) a membership from an approved proposal counts
  as Midas's, as B3.2 says (`app/human_edits.py` `added_by_midas`).
- **"Active intervention" exclusion.** Part 2 §1.6 limits *Midas* interventions to one per video; §2.1 and B4
  exclude videos with "an active intervention" of any origin, which would let human edits block Midas picks.
  Part 3 B2's test says "a second active intervention", no origin. As built (B2), §1.6's reading: `active_for`
  and the partial unique index count `origin = 'midas'` only (`app/interventions.py`,
  `20261006020000_interventions.sql`); B4 must decide whether its exclusion also counts human ones.
- **Which statuses are "active".** Neither Part says. As built: `planned`, `applied`, `measuring` and
  `holdout` (a held-out video is the control arm for its window); `declined` is not, so a `no_change` triage
  doesn't hold a video for a window, and the picker could pick it again next tick (Slice 1's concern)
  (`app/status_vocab.py:217-220`).
- **`get_search_terms`.** A3 answered yes (Part 2 §11.1), but §6's Slice 3 row doesn't list the tool and §7 has
  no storage for terms.
- **`WARM_MIN_IMPRESSIONS`** says "Revisit after Phase A live numbers" (§8); Phase A is done and it wasn't revisited.
- **Document framing.** "This file has two parts" (How to use) while it has three; "Ground truth used:
  `STATE.md` @ `bddd373`" predates Phase A.

---

## 8. Operational reality

The live DB is unreachable from here. Every figure is from `docs/PHASE_A_FINDINGS.md`, labelled.

- **Outcome volume** (A7 query 2, 2026-10-06; applied/reverted audits): `awaiting_window` 575 · `neutral` 652 ·
  `not_applicable/dormant` 4,254 · `not_applicable/other` 2,461 · `regression` 106 · `win` 64. Judged (822):
  win 7.8% · regression 12.9% · neutral 79.3%.
- **Per channel** (A7 query 3, 2026-10-06, excluding `not_applicable`): Punjabi awaiting 6 · neutral 147 ·
  regression 4 · win 21; Bhojpuri neutral 1 · regression 3; English regression 4; Gujarati neutral 260 ·
  regression 75 · win 29; Marathi awaiting 569 · neutral 244 · regression 20 · win 14.
- **Dormant applies, last 90 days** (A7 warm-pool query 2, 2026-10-06): Gujarati 3,902 of 4,277 (91%) · Marathi
  352 of 1,201 (29%) · Punjabi 0 of 563 · Haryanvi 0 of 68 · English 0 of 10 · Bhojpuri 0 of 8.
- **Warm pool** (A7, 2026-10-06, ≥500 impressions, last 30 days): Hindi 1,120 · English 1,008 · Gujarati 603 ·
  Marathi 566 · Bhojpuri 471 · Punjabi 342 · Tamil 290 · Malayalam 70; the other five have no reach data.
- **Reach frontier** (A7 query 4, 2026-10-06): 2026-10-04 for Punjabi (213 days), Bhojpuri (183), English (148),
  Gujarati (147), Marathi (221), Tamil (143), Malayalam (143); Hindi 2026-09-26 (213; token). No other channel
  ingests reach.
- **Audit statuses** (A7 query 6, 2026-10-06): applied 8,109 · failed 715 · pending 201 · quarantined 199 ·
  shadow_pending 87 · reverted 3 · blocked_test_and_compare 1.
- **Prompt versions** (A7 query 7, 2026-10-06): shadow only (Punjabi 3, Gujarati 1, Marathi 4) + Marathi retired 1;
  none live.
- **In-window audits at the pause** (A0, 2026-09-29): 1,910 (Marathi 1,198, Gujarati 706, Punjabi 6); last
  window closes 2026-10-16.
- **Data API burn** (A7 query 5, 2026-10-06): ≈8.5k–12.5k/day 09-06 → 09-20 (applies + reconcile); ≤1.4k/day
  since 09-21 except 09-27 (4,374) and 10-06 (3,667, the manual sync). Ceiling 10k/day.
- **Job health** (A7 raw result 0, 2026-10-06): all `success` except `video_sync` **failed** for Hindi
  (`"HTTPException: 401: token_expired"`) and `metrics_poll` **degraded** (Bhojpuri playlists 1/48 · Gujarati
  playlists 1/36 · Marathi videos 3/632 · Malayalam playlists 1/20). On 2026-10-01 all 8 then-registered jobs were
  `success` (A9).
- **Traffic mix** (A1.1, Marathi, data date 2026-09-29, 52,319 report rows, 259,868 views): 14 Playlists 118,342
  (45.5%) · 24 Shorts feed 49,292 (19.0%) · 7 Suggested 48,862 (18.8%) · 3 Browse 17,652 (6.8%) · 8 Other 12,851
  (4.9%) · 4 Channels 7,432 (2.9%) · 5 Search 2,911 (1.1%) · 0 Direct 1,368 · 9 External 668 · 20 Endscreen 254 ·
  18 Playlist pages 148 · 27 Sound 33 · 32 Related video 27 · 26 Hashtag 20 · 17 Notifications 8. Type 14 split:
  `RD…` Mixes 117,929 · our `PL…` playlists **50** · other 363.
- **Routing levers today** (A1.1/A1.3, 2026-09-29): 1,804 description-link pairs on Marathi → 4 attributable
  views (type 7); Short → video (type 32) 27 views from 12 Shorts, none uploaded through Midas. Type-7 suggested
  views from any of our channels: 11,113 of 48,862 (22.7%); Mixes seeded from our videos: 7,024 of 117,929 (6.0%).
- **Sensor shape** (A1.1): `channel_traffic_source_a3` has 15 columns, `playlist_traffic_source_a2` 16; source
  types are numeric codes; steady lag 2 days; the playlist report restates some data dates; ≈52k raw rows per
  Marathi channel-day. On-demand detail for PLAYLIST and SHORTS returns 400; RELATED_VIDEO and YT_SEARCH detail
  work (A1.2, 2026-10-06). Search terms are available, with low-volume suppression in the report (233 of 319
  type-5 rows empty) (A3).
- **Short → video link field** (A2, 2026-10-01): not readable or writable via the Data API.
- **Older recorded facts still in code comments:** the 2026-08-23 verdicts (*"147 neutral / 21 win / 3
  regression"*, `app/reflection.py:32-34`); *"381 dormant, of which 184 published inside their own pre-window"*
  (`app/measurement.py:163-164`); reconcile consumed *"8.5k-9.2k"* units on 2026-08-03/04
  (`supabase/migrations/20260812000000_playlist_membership_walked_at.sql:5`).
- **Blank:** Shorts upload volume and its Data API cost (not charged to the ledger, §7.2); quarantine reasons;
  playlist proposal queue size; the office `.env` contents beyond the tick setting.

**SQL to refresh** (run on the office machine against `midas`, e.g. `docker compose exec db psql -U midas midas`;
`count(1)`, because the office copy-paste path drops `*`):

```sql
-- channels live
select id, name, default_language, analytics_authorized, measurement_enabled, reach_warmup,
       playlist_health_enabled, autopilot_enabled, autopilot_paused_reason, autopilot_shorts_enabled
from channels order by name;

-- outcome volume + dormancy ratio
select measurement_status, measurement_result->>'reason_code' as reason, count(1)
from audits where status in ('applied','reverted') group by 1,2 order by 1,2;

-- per-channel outcomes
select v.channel_id, a.measurement_status, count(1)
from audits a join videos v on v.id=a.video_id
where a.measurement_status <> 'not_applicable' group by 1,2 order by 1,2;

-- reach frontier per channel (the ledger also holds traffic reports since 20261006000000)
select channel_id, max(data_date) frontier, count(1) days_covered
from reporting_reports_ingested where report_type = 'channel_reach_basic_a1' group by 1;

-- daily Data API burn, last 30 days
select date_trunc('day', occurred_at) d, sum(units) units, count(1) filter (where not success) failures
from quota_log where units > 0 and occurred_at > now() - interval '30 days' group by 1 order by 1;

-- quarantine + prompt versions
select status, count(1) from audits group by 1;
select channel_id, status, count(1) from prompt_versions group by 1,2;

-- playlist health freshness
select channel_id, max(health_computed_at), count(1) filter (where health_recommendation is not null)
from playlists group by 1;

-- warm pool size per channel (>= 500 impressions, last 30 days of video_reach_daily)
select channel_id, count(1) warm_videos
from (select channel_id, video_id, sum(impressions) imp
      from video_reach_daily where date > current_date - 30 group by 1,2) t
where imp >= 500 group by 1 order by 2 desc;

-- traffic-source rows per data-day (B1; after the 20261006000000 migration is applied)
select channel_id, date, count(1) rows_, sum(views) views, max(report_id) report
from video_traffic_source_daily group by 1,2 order by 1,2 desc;

-- playlist traffic rows per data-day (B1b; after the 20261006010000 migration is applied)
select channel_id, date, count(1) rows_, sum(views) views, sum(playlist_starts) starts, max(report_id) report
from playlist_traffic_daily group by 1,2 order by 1,2 desc;

-- B9a acceptance: traffic frontier per channel and report type, from the ledger (a day whose report had 0 rows is ingested
-- but has no table rows), and the data-days missing between the first ingested day and current_date - 2
select channel_id, report_type, min(data_date) first_day, max(data_date) frontier, count(distinct data_date) days_ingested
from reporting_reports_ingested
where report_type in ('channel_traffic_source_a3', 'playlist_traffic_source_a2') group by 1,2;

select t.report_type, d::date missing_day
from (values ('channel_traffic_source_a3'), ('playlist_traffic_source_a2')) t(report_type)
cross join lateral generate_series(
       (select min(data_date) from reporting_reports_ingested
        where report_type = t.report_type and channel_id = 'UCr5-YUqBiW7PUmeAtxUWuRg'),
       current_date - 2, interval '1 day') d
where d::date not in (select data_date from reporting_reports_ingested
                      where report_type = t.report_type and channel_id = 'UCr5-YUqBiW7PUmeAtxUWuRg')
order by 1, 2;

-- interventions by origin, lever, arm and status (B2; after the 20261006020000 migration is applied)
select origin, lever, arm, status, count(1) from interventions group by 1,2,3,4 order by 1,2,3,4;

-- B3a: human backlinks detected, newest first (after 20261006030000 is applied); the exit gate needs at least one
select channel_id, video_id, payload->>'target_video_id' target, detected_at, payload->>'removed_detected_at' removed
from interventions where origin = 'human' and lever = 'backlinks' order by detected_at desc limit 50;

-- B3b: human playlist memberships detected, newest first (after 20261006030000 is applied)
select channel_id, video_id, payload->>'playlist_id' playlist, payload->>'playlist_item_id' item, detected_at
from interventions where origin = 'human' and lever = 'playlist' order by detected_at desc limit 50;

-- applied audits in the last 90 days that landed on dormant videos
select v.channel_id, count(1) filter (where a.measurement_result->>'reason_code' = 'dormant') dormant, count(1) total
from audits a join videos v on v.id = a.video_id
where a.applied_at > now() - interval '90 days' group by 1;
```

---

## 9. Regeneration prompt

Run in Claude Code at the repo root:

> Read this repo and rewrite `STATE.md` in place, keeping its exact section structure.
> Rules: every claim must be verifiable from a file in this repo, cited by path; if you
> can't verify it, leave the field blank rather than inferring it. The only spec is
> `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md`. Read it only to compute
> §1 and §7, and don't summarise it. §1's phase table follows the spec's stages (Phase A, Phase B,
> Slices 1–5, spec Part 2 §6), not any older phase numbering. For §7, compare the code against
> Part 2 (as amended in §0.6) and the Part marked "ready to build". Be exhaustive and
> uncharitable: list every spec'd-but-not-built item including partial implementations,
> every built-but-not-spec'd item (including pre-spec machinery that is frozen but still in
> the code), and every substantive divergence. 7.4 lists contradictions *within* the spec,
> for example between Part 2 and the build Part. Older design docs that were deleted are in git history
> only; don't cite or reconstruct them. Paste config values, prompt text and DDL verbatim
> rather than describing them. For §8, query the database for the actual counts if you can
> reach it. Otherwise quote the dated live figures in `docs/PHASE_A_FINDINGS.md` (A7, A1.1),
> labelled with their date and section, and leave the rest blank.
