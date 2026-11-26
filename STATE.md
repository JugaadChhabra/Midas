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

**Generated:** 2026-11-26 (the Results page, ticket 04 of #167 (#171): a `playlist` cell (`playlist_test.playlist_test_summary`'s figures) and a `short_link` cell (the team's work) on `GET /seo/results`, Playlist test and Short links column groups on `/results`; earlier, ticket 03 of #170: a `title` cell on `GET /seo/results` with `paths: {pipeline, agent}` and `first_title_verdicts`, a Titles column group and lever chips on `/results`, `lever_verdicts.title_paths` split out of `title_test_summary`; ticket 02 of #167: `GET /seo/results` (`app/seo_results.py`), a backlinks cell per visible channel and a pooled fleet row, served at `/results` with Results in the rail; earlier: Shorts: an `episode` cut mode for series folders, 45-50 s clips front to back; the shorts cache emptied after each NAS job and swept daily by `shorts_cache_cleanup`; the Roster board: no "No manager" card, manager-less channels float grey on the canvas; plain nested cards, pinch/Ctrl-scroll zoom, a "+ target" chip and a counting legend; targets moved from members to channels: `channel_targets`, `PUT /channels/{id}/targets`, `member_targets` dropped; the Roster is a zoomable board of nested cards, `GET /team/board`, `POST /channels/{id}/move` (the `move_channel` SQL function), the admin moves members between managers; the Uploads grid is a section per member with their channels, no By member / By channel switch; the channel page rebuilt around interventions, `GET /channels/{id}/seo`; an unlisted video counts on the day a sync saw it go public: `channel_uploads.public_at`, the 2-hourly `upload_recheck` job; member targets: `member_targets`, `PUT /team/members/{id}/targets`, red grid cells; the drill-down is a card grid; Roster: per-member channel picker (`PUT /team/members/{id}/channels`) and the admin's per-manager picker replace the Channels list; the drill-down groups by channel; Team page's Uploads tab redesigned; a channel whose `channel_uploads` history is missing gets a full sync; earlier: the host moved to a Mac mini; the logo `app/static/midas.png` in the rail, the login page and the tab icon, and added to `session.PUBLIC_PATHS`) ·
**Commit:** on top of `39d0fe9` · **Branch:** `seo-results/04-playlist-short-links`

**The spec**, cited below as **spec**: `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md`. Part 1
(Phase A) and Part 3 (Phase B) are done; Parts 4–6 (Slices 1–3) are built and live; Part 2 is the approved design,
amended by P1–P7 (spec Part 2 §0.6).

**Office deployment.** Since 2026-11-19 the host is a Mac mini (Apple Silicon) at `http://mac-mini.local:8000`, in
`~/midas`, restored from the NAS snapshot with row counts matching the Windows machine's, which is retired (its `.env`
renamed). It runs the image built from `main` at `c2d1dfd` (the team tracker's migrations applied 2026-11-18, users
and channel managers set, #153). It is not a git checkout: only `.env`, `docker-compose.yml`, `client_secret.json`
and `deploy/postgrest-proxy.conf` live there. What is switched on, per lever and channel, is in
`docs/PLAN_TO_2026-11-27.md` ("What is live"); the rollback steps are in `docs/agents/office-runbook.md` (gitignored).
The move used `move-out.ps1` (Windows: final NAS snapshot of the stopped DB, config zip, `.env` renamed) and
`move-in.sh` (Mac: restore from the NAS on first boot, row counts compared), steps in `docs/MOVE_TO_MAC_MINI.md`; the
first-boot restore died silently inside the service and was rerun by hand with `docker compose run --rm --no-deps
midas` (cause not found). The image is `linux/amd64` only
(`.github/workflows/docker-publish.yml`), so on the Mac it runs under Rosetta (`docker-compose.yml` `platform`).

**Data caveat.** The live database runs on the office machine, bound to `127.0.0.1:55432` there
(`docker-compose.yml:21-22`), so it can't be reached from the machine that generated this file. Live figures are
quoted from `docs/PHASE_A_FINDINGS.md`, `docs/PHASE_B_FINDINGS.md` and `docs/PLAN_TO_2026-11-27.md`, each with its
date; anything not recorded there is blank. §8 ends with the SQL to refresh them.

---

## 1. Phase status

Stages are the spec's build order (spec Part 2 §6). Evidence lists the main files; §5 has every module.

| Stage | Theme | Status | Evidence (paths) | Notes |
|---|---|---|---|---|
| **Phase A** | Gates | **done** (exit gate passed 2026-10-06) | A4: `app/config.py:121-123,34`, `app/main.py:335-377`, `tests/test_frozen_writers.py`. A5: `app/transcripts.py:25-31`, `app/youtube_metadata.py:58-59` (the `bgc` entries). A6: `app/audits.py:196-278`, `tests/test_strategy_version.py`. A8: `app/job_status.py`, `app/main.py:82-108,634-637`, `tests/test_main_fanout.py`. A10: `app/autopilot.py:450-466,515`, `app/audits.py:847-852`, `tests/test_revert_quota_gate.py`. Probes: `scripts/probes/*.py`. Record: `docs/PHASE_A_FINDINGS.md` | The four A4 writers stay frozen (§4). |
| **Phase B** | Plumbing (spec Part 3, B1–B10) | **done** (exit gate passed 2026-10-13; `docs/PHASE_B_FINDINGS.md`) | `app/traffic_poll.py`, `app/reporting_client.py`, `app/reporting_poll.py`, `app/sync.py` (`TokenExpired`), `app/interventions.py`, `app/human_edits.py`, `app/warm.py`, `app/decide.py`, `app/reembed.py`, `scripts/reembed.py`; migrations `20261006000000`–`20261006060000` | The B6 vectors and `channels.playlist_thresholds` are written only by the one-off `scripts/reembed.py`, and read by `backlinks.candidates`, `playlist_test` and `short_links`. The `bho`/`raj` language entries are unused: Bhojpuri and Rajasthani use plain `hi` (owner, `app/youtube_metadata.py:60-61`). Leftovers in §7.1. |
| **Slice 1** | Backlinks + no change | **live** on Marathi (`autopilot_daily_cap` 15), English, Hindi, Bhojpuri, Gujarati (10), Tamil, Malayalam, Haryanvi, Rajasthani (8); off on Punjabi, 3D Animated (a cartoon series), Kannada and Telugu (no uploads) (`docs/PLAN_TO_2026-11-27.md`, 2026-11-16). Exit gate pending: the first weekly verdict (#70) | `app/backlinks.py`, `app/backlinks_apply.py`, `app/agent_tick.py`, `app/autopilot.py` `_agent_tick`, `app/lever_measurement.py`, `app/lever_verdicts.py`, `scripts/preview_backlinks.py`; migrations `20261023000000`, `20261023010000` | `BACKLINK_APPLY_ENABLED=true` in the office `.env`; while it is false, or the language has no heading in `backlinks.HEADINGS`, backlinks don't run (§3). Targets are on the source's own channel only (`BACKLINK_SIBLINGS_ENABLED` false) and re-uploads are left out (`BACKLINK_DUPLICATE_SIM`) (§7.3 item 35). Backlink rows on Shorts written before the pick left Shorts out (Marathi: 44 treated, 11 holdout) keep their blocks (owner) and enter no verdict (`lever_verdicts._without_shorts`). Marathi's warm long videos were used up on 2026-10-29 (the pool was 226 Shorts, 0 long videos). The stop rule needs 3 windows. The next-watch question is asked in shadow per candidate pair; its rules answer is always `yes`, since `candidates` keeps only pairs ≥ `join_low`. |
| **Slice 2** | Playlist test (P3) + Short links (P4) | **live on Marathi** since 2026-10-26: the playlist test is drawn (37 treated arms with 151 approved adds, 2 `no_dose`, 40 holdout) and dosed, `PLAYLIST_APPLY_ENABLED=true`; Short links are recommend-only (the team doesn't use the card yet). Docs (#94) open | `app/playlist_test.py`, `app/short_links.py`, `scripts/playlist_test.py`, `scripts/short_links.py`, the Short links card in `app/static/channel.html`; migrations `20261027000000`, `20261027010000` | The candidates concentrate on a handful of high-impression videos: Marathi's `join_high` (0.9014) is below most videos' cosine to a playlist's centroid (0.90–0.93), so it barely filters and the ranking is by impressions. Over 1,000 frozen-engine proposals are still `pending` on the dashboard card, and approving one writes to YouTube at once. Approving a test proposal (`arm_id` set) only marks it `approved` (`app/playlists_router.py` `decide_proposals`); the daily `playlist_test_apply` job sends it. The card's toast still says "Executed 0 change(s) on YouTube." for them; the response carries `queued`. The weekly `lever_measurement` job writes `lever = 'playlist'` verdicts once the post weeks are in; nothing reads them to stop anything. Short links: the weekly `short_link_refresh` job writes `pending` recommendations, the team ticks a target it set in Studio (a `human` `short_link` intervention), and the weekly job also records links it sees in type-32 traffic and writes `short_link` `human` verdict rows; nothing reaches YouTube. The frozen engine's add/remove and creation paths stay off (§4). |
| **Slice 3** | Agent challenger + titles | **live, pipeline only**, on Hindi, Marathi, Gujarati and English since 2026-11-16: office `.env` `TITLE_APPLY_ENABLED=true`, `TITLE_AGENT_PCT=0` (the agent waits for fact checks: in the previews it changed an episode number and dropped TMKOC), `TITLE_EXCLUDE_VIDEOS=bKTmEfCOkRE,5TiKqa8hPgs,k8Bnw8PPx7w` (two LIVE streams, a 5M-subscriber video); `WRITER_MODEL` unset (= `AUDIT_MODEL`, `google/gemini-3.7-flash` at the office). Docs (#122) open | `app/titles.py`, `app/titles_apply.py`, `app/agent/loop.py`, `app/agent/tools.py`, `app/title_measurement.py`, `app/lever_verdicts.py`, `scripts/preview_titles.py`, `scripts/title_bakeoff.py`; migrations `20261030000000`–`20261030020000` | Triage answers `title` after backlinks, on `TITLE_CHANNELS` channels while `TITLE_APPLY_ENABLED` is on (code defaults: Marathi, false). A treated video is written by the pipeline or, on the agent path (`TITLE_AGENT_PCT`), by the agent, which may decline; every agent row stores its run in `interventions.trajectory`. The weekly `lever_measurement` job measures title rows, writes a verdict per path against the shared holdout, and stops a path by its stop rule or harm guard; a stopped path, or one with no share, is closed (`titles.path_closed`), its videos go to the other path if that one is open, both closed close the lever, and losing titles are put back (`revert_title(auto=True)`). No title verdict yet: the first rows judge after their 14-day post window (~2026-12-01). The tick has no house-format title path: no tick path calls `audit_video`, a channel with `agent_enabled` off does only the Shorts action, and the manual house-format applies refuse on an agent channel unless `?force=true` (§5). No `app/niche_reference.py`. |
| **Slice 4** | Playbook | **not started** | none | No `channels.playbook_json`. `app/reflection.py` (the thing Slice 4 retires) is frozen by `REFLECTION_ENABLED=false` (§4). |
| **Slice 5** | Fleet | **not started** | none | `JobBudget` exists (`app/quota.py:232`) but has no per-channel shares. |

**What runs today (pre-spec machinery, all built before the spec).** The sensor layer
(`app/metrics_poll.py`, `app/reporting_poll.py`, `app/reach.py`, `video_reach_daily`), Loop 1 title
measurement (`app/measurement.py`, `app/verdicts.py`; 21-day CTR windows), playlist inventory and health
scoring (`app/playlists_sync.py`, `app/playlist_health.py`), daily video sync (`app/main.py:248-275`), the Shorts
cutter (`app/shorts/*`), and the NAS backup (`app/backup.py`). The spec keeps the sensor layer, the apply path,
`AuditSuggestion`, quota, `status_vocab`, `reach.certify`, and the playlist write, inventory, health and proposal
machinery (spec Part 2 §0.5 "Kept").

**Channels** (ids and languages from A7 query 1, `docs/PHASE_A_FINDINGS.md`; levers from
`docs/PLAN_TO_2026-11-27.md`, 2026-11-16). All 13 are `analytics_authorized`. Punjabi is the only channel with
`playlist_health_enabled`; `reach_warmup = t` on Haryanvi, Rajasthani, 3D Animated, Kannada and Telugu, the other
eight ingest reach through `measurement_enabled`; Marathi has `sync_shorts = t`. The agent channels have
`agent_enabled = autopilot_enabled = t`.

| Channel | id | `default_language` | Backlinks | Titles | Notes |
|---|---|---|---|---|---|
| Marathi | `UCr5-YUqBiW7PUmeAtxUWuRg` | `mr` | live, cap 15 | live | rollout #1; playlist test, Short links |
| Punjabi | `UC8KjoL0Z9mTHKqB6gFutkJw` | `pa` | off | off | owner, 2026-11-16; Shorts continue |
| Gujarati | `UCOVKJdzghm2gOnuaGeJTonA` | `gu` | live, cap 10 | live | |
| English | `UCMpj6iUMCMhB0k4L5EcxJwQ` | `en` | live, cap 10 | live | |
| Hindi | `UCR9qQMyP86aSt-1VgaMg7UA` | `hi` | live, cap 10 | live | |
| Bhojpuri | `UC8oC7Yiz0WkH3PKb3GW42XA` | `hi` | live, cap 10 | off | |
| Tamil | `UCWb0eKKkX1NE1r_Tu6oKhdQ` | `ta` | live, cap 8 | off | |
| Malayalam | `UCX8BttGE4UAFdm1RRIULOPQ` | `ml` | live, cap 8 | off | |
| Haryanvi | `UCc4Tv_DEGDEKrKAt-vyVNmw` | `bgc` | live, cap 8 | off | |
| Rajasthani | `UCFO6AQ_KBQDEaQiTi-dBEWQ` | `hi` | live, cap 8 | off | |
| 3D Animated Series | `UCqtU4xCSjsSvE53Iy6NUKSg` | `hi` | off | off | a cartoon series, not rhymes |
| Kannada | `UCo4_mZK5aAF7ugv4cTfZlEg` | `kn` | off | off | no uploads |
| Telugu | `UCxK1-ftYdFvU4IuUW3POxRA` | `te` | off | off | no uploads |

Flags that exist on `channels`: `analytics_authorized`, `measurement_enabled`, `reach_warmup`,
`playlist_health_enabled`, `autopilot_enabled`, `autopilot_shorts_enabled`, `sync_shorts`, and `agent_enabled`
(read by `autopilot.tick` and `eligibility.can_run_agent`).

---

## 2. Schema — as applied

**Migrations** (`supabase/migrations/`, after `supabase/bootstrap/000_roles.sql`, `010_storage_shim.sql`):

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
20261006040000_warm_pool_rpc.sql                warm_pool() function (B4)
20261006050000_decision_log.sql                 decision_log (B5)
20261006060000_channels_playlist_thresholds.sql  channels.playlist_thresholds (B6)
20261023000000_warm_pool_agent_exclusions.sql   warm_pool() replaced: + p_cooldown_days, cooldown, once per experiment (S1.4a)
20261023010000_lever_verdicts.sql               lever_verdicts (S1.6b)
20261027000000_playlist_arms.sql                playlist_arms, playlist_proposals.arm_id/applied_at/playlist_item_id/apply_error (S2.1)
20261027010000_short_link_recommendations.sql   short_link_recommendations (S2.4)
20261030000000_interventions_trajectory.sql     interventions.trajectory (S3.4)
20261030010000_lever_verdicts_title_scopes.sql  comment on lever_verdicts.arm_scope: + pipeline_vs_holdout|agent_vs_holdout (S3.5)
20261030020000_warm_pool_title_holds.sql        warm_pool() replaced: + title rows hold once per experiment (S3.5)
20261118000000_app_users_sessions.sql           app_users, app_sessions (team tracker #144)
20261118010000_channels_manager_id.sql          channels.manager_id → app_users, channels_manager_idx (team tracker #145)
20261118020000_team_members.sql                 team_members, team_members_manager_idx (team tracker #148)
20261118030000_channel_assignments.sql          channel_assignments, assign_channel() (team tracker #149)
20261118040000_channel_uploads.sql              channel_uploads + its freeze trigger (team tracker #150)
20261120000000_member_targets.sql               member_targets (team tracker: daily upload targets; dropped by 20261121000000)
20261120010000_channel_uploads_public_at.sql    channel_uploads.public_at (unlisted → public seen by a sync)
20261121000000_channel_targets.sql              channel_targets, drop member_targets, move_channel() (the Board)
```

**Tables** (columns are the union across the migrations):

- **`channels`**: `id text pk, name, handle, refresh_token text not null, access_token, token_expiry timestamptz, last_synced_at, created_at, default_language text, autopilot_enabled bool default false, autopilot_paused_reason text, autopilot_last_tick_at, autopilot_daily_cap int default 10, analytics_authorized bool default false, last_full_synced_at, playlist_health_enabled bool default false, measurement_enabled bool default false, autopilot_shorts_enabled bool not null default false, autopilot_shorts_daily_cap int not null default 1, autopilot_shorts_upload_cap int not null default 2, shorts_cut_mode text not null default 'highlights', shorts_camera_motion text not null default 'calm', sync_shorts bool (nullable), nas_folder text, autopilot_paused_at timestamptz, reach_warmup bool default false, agent_enabled boolean not null default false, playlist_thresholds jsonb, manager_id bigint → app_users (nullable)`.
  `manager_id` (`20261118010000`, verbatim without its header comment: `alter table channels add column if not exists manager_id bigint references app_users(id);` and `create index if not exists channels_manager_idx on channels (manager_id);`): the manager who sees the channel; NULL = admin and exec only. Read by `app/access.py`, written only by `PATCH /channels/{id}/manager`.
  `playlist_thresholds` = `{model_version, join_high, join_low, leave, member_sims, playlists, method, computed_at}` from `app/reembed.py` `calibrate_channel`; read by `app/backlinks.py` `candidates` (`join_low`, only for `reembed.MODEL_VERSION`).
- **`videos`**: `id text pk, channel_id → channels on delete cascade, title, description, tags text[], thumbnail_url, category_id, view_count, like_count, comment_count bigint, published_at, last_fetched_at, privacy_status text, thumbnail_optimized_at, playlists_optimized_at timestamptz, duration_seconds int, is_short bool, is_episode bool (nullable; NULL = not episode)`.
- **`audits`**: `id bigserial pk, video_id → videos on delete cascade, status text default 'pending', suggested_title, suggested_description, suggested_tags text[], thumbnail_feedback, issues_found jsonb, ai_reasoning, applied_at, created_at, title_before, description_before, tags_before text[], view_count_at_apply, like_count_at_apply, comment_count_at_apply bigint, transcript_available bool, transcript_lang, keyframes_extracted int default 0, prompt_version_id → prompt_versions, measurement_status text default 'not_applicable', measurement_started_at, measurement_result jsonb, outcome_decision text default 'none', redo_of_audit_id → audits, strategy_version → audit_strategies`.
  Status `pending|applied|failed|quarantined|blocked_test_and_compare|shadow_pending|reverted|approved|rejected` (`approved`/`rejected` unused); `outcome_decision` `none|kept|reverted|redo_queued` (`redo_queued` unused); measurement `not_applicable|awaiting_window|measuring|win|neutral|regression`, `reason_code` `no_timestamp|coverage_lost|dormant|video_gone`.
- **`video_metrics`** (`20260610134419`):
  ```sql
  id bigserial pk, video_id text not null → videos on delete cascade, channel_id text not null → channels,
  window_start date not null, window_end date not null,
  impressions bigint, ctr float,
  views bigint, est_minutes_watched bigint, avg_view_duration_sec integer, avg_view_pct float,
  is_pre_change boolean default false, fetched_at timestamptz default now(),
  unique (video_id, window_start, window_end)
  ```
- **`video_reach_daily`**: `video_id text not null (no FK), channel_id → channels, date date, impressions bigint not null, ctr double precision not null (fraction 0..1), report_id text, fetched_at, unique(video_id, date)`. From `channel_reach_basic_a1`.
- **`reporting_reports_ingested`**: `report_id text pk, job_id, channel_id, data_date date, row_count int, ingested_at, report_type text not null default 'channel_reach_basic_a1'`. Shared by reach and traffic reports.
- **`video_traffic_source_daily`** (`20261006000000`):
  ```sql
  id bigserial primary key, video_id text not null (no FK), channel_id text not null references channels(id),
  date date not null, source_type smallint not null, source_detail text not null default '',
  views bigint not null, engaged_views bigint not null, watch_time_minutes double precision not null,
  report_id text not null, ingested_at timestamptz default now(),
  unique (video_id, date, source_type, source_detail)
  ```
  From `channel_traffic_source_a3`, summed over country, subscribed and live dimensions. `source_detail` kept only where `app/traffic_poll.py` `keeps_detail` says; the rest folded into the blank-detail row (per-type totals exact).
- **`playlist_traffic_daily`** (`20261006010000`):
  ```sql
  id bigserial primary key, playlist_id text not null (no FK), video_id text not null (no FK),
  channel_id text not null references channels(id),
  date date not null, source_type smallint not null, source_detail text not null default '',
  views bigint not null, playlist_starts bigint not null, watch_time_minutes double precision not null,
  report_id text not null, ingested_at timestamptz default now(),
  unique (playlist_id, video_id, date, source_type, source_detail)
  ```
  From `playlist_traffic_source_a2`.
- **`interventions`** (`20261006020000`):
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
  Added by `20261006030000`, verbatim:
  ```sql
  alter table interventions add column if not exists ledger_key text;

  create unique index if not exists interventions_ledger_key_key
      on interventions (ledger_key);
  ```
  Added by `20261030000000`, verbatim without its header comment:
  ```sql
  alter table interventions add column if not exists trajectory jsonb;
  ```
  Vocab (`app/status_vocab.py`): lever `backlinks|playlist|short_link|title`; origin `midas|human`; arm
  `treated|holdout|n/a`; status `planned|applied|measuring|judged|cancelled|declined|holdout|insufficient_data`;
  active = `planned|applied|measuring|holdout` (mirrored by the partial index). Writers, payloads:
  - `app/agent_tick.py` `backlinks`: `declined` (arm `n/a`) `{rationale}`; `holdout` `{targets}`; treated `planned`
    `{targets}` → `measuring` or `cancelled` + `error {reason, detail}`; all with `triage_json`.
  - `app/agent_tick.py` `_run_title`: `holdout` `{title_before}`; treated `planned` `{title_before, title,
    candidates, reason, path}` + `strategy_version` → `measuring`/`cancelled`; or `cancelled` `{title_before, path,
    title: null, candidates, reason: null, error}` (`checks_failed`) / `{title_before, path, error}`
    (`writer_exception`). Agent path adds treated `declined` `{title_before, path: "agent", rationale}` and
    `cancelled` `turn_cap`; every agent row has `trajectory`.
  - `app/titles_apply.py`: apply sets `measuring`, `applied_at`, `before_state {title}`; revert `cancelled`,
    `payload.revert {reverted_at, live_before, title, auto}`.
  - `human` rows (arm `n/a`, `applied`, `applied_at` NULL, `detected_at` = when seen), with `ledger_key`:
    `app/human_edits.py` `backlinks` `{source_video_id, target_video_id, added_targets, removed_targets, timing}`
    (+`removed_detected_at`), key `backlinks:<source>:<target>:<first 16 hex of sha256 of the new description,
    whitespace collapsed>`; `playlist` `{playlist_id, video_id, playlist_item_id, timing}`, key
    `playlist:<playlist_id>:<video_id>:<playlist_item_id>`; `app/short_links.py` `short_link` (`video_id` = target),
    key `short_link:<short_id>:<target_video_id>`: `set_short_link` `{short_id, target_video_id, recommendation_id,
    timing: "ticked"}`, `detect` (type-32 traffic) `{short_id, target_video_id, recommended, timing:
    "inferred_from_traffic"}`.
  `trajectory` (via `interventions.record(trajectory=)`): `{model, writer_model, max_turns, turns, end: {kind,
  reason, detail}, submits: [{title, check, reasoning}], messages: [{role, content, tool_calls: [{id, name,
  arguments}], tool_call_id, name}]}`, texts cut to 2,000 chars (`TRAJECTORY_CHARS`).
  Measurement: `status` carries the outcome (`judged`/`insufficient_data`), `measurement_status` only progress
  (`awaiting_window|extended|done`). `app/lever_measurement.py` (backlinks, human `short_link`): `{pre, post, delta,
  source_views, missing_days, window: {d0, pre: [start, end], post: [start, end], post_days, extended}, judged_at,
  computed_at}`. `app/title_measurement.py` (`title` `measuring`, `holdout`, `declined`): `{pre, post, delta,
  impressions: {pre, post}, ctr: {pre, post}, missing_days, window: {d0, pre: [start, end], post: [start, end]},
  judged_at, computed_at}`, `delta` a log ratio; `lever_verdicts.auto_revert` reverts losing titles.
- **`playlists`**: `id text pk, channel_id → channels on delete cascade, title text not null, description default '', synced_at, role text, origin text default 'inherited', item_count int, last_synced_at, created_by_optimizer_at, strategy_version text, health_score float, health_recommendation text (revive|remove|keep|insufficient_data), health_computed_at, health_rationale_json jsonb, membership_walked_at timestamptz`. Roles `series|funnel|inherited`; discovery-created ones land `origin='inherited'`.
- **`playlist_metrics`**:
  ```sql
  id bigserial pk, playlist_id text not null (no FK), channel_id → channels, window_start date, window_end date,
  playlist_starts bigint, views_per_playlist_start float, avg_time_in_playlist_sec integer,
  playlist_views bigint, playlist_est_minutes_watched bigint, is_pre_change boolean default false,
  fetched_at, unique (playlist_id, window_start, window_end)
  ```
- **`video_traffic_source_playlist`**: `video_id → videos, playlist_id text (no FK), channel_id, window_start, window_end, views bigint, unique(video_id, playlist_id, window_start, window_end)`. Never populated.
- **`audit_strategies`**: `version text pk, prompt_template text not null, model text not null, config jsonb, status text default 'challenger', notes, created_at`. Seed `2026.07-baseline-v1`; rows upserted per audit and per title strategy (`app/titles.py` `strategy_version`, §6).
- **`video_embeddings`**: `video_id, chunk_index, model_version text not null, embedding vector(3072), unique (video_id, chunk_index, model_version)`. Production uses `model_version = EMBED_MODEL`; `app/reembed.py` writes `MODEL_VERSION` = `"google/gemini-embedding-2-preview|tdt-v1"`, read by `app/backlinks.py` `candidates`.
- **`app_users`**, **`app_sessions`** (`20261118000000`, team tracker #144), verbatim without the header comment.
  Read and written only by `app/session.py` (the gate, `/session/*`, and the user-admin functions behind
  `scripts/manage_users.py`). `email` stored lower-cased; `password_hash` an argon2id hash (`argon2-cffi`); `role`
  mirrored by `status_vocab.UserRole` (`admin|exec|manager`). A session row is keyed by the sha256 hex of its cookie
  token (the raw token is never stored); expired rows are deleted when read:
  ```sql
  create table if not exists app_users (
      id             bigserial    primary key,
      email          text         not null unique,
      name           text         not null,
      password_hash  text         not null,
      role           text         not null check (role in ('admin', 'exec', 'manager')),
      is_active      boolean      not null default true,
      created_at     timestamptz  not null default now()
  );

  create table if not exists app_sessions (
      token_hash   text         primary key,
      user_id      bigint       not null references app_users(id) on delete cascade,
      expires_at   timestamptz  not null,
      created_at   timestamptz  not null default now()
  );

  -- Backs the cascade, and "every session of this user" (deactivate).
  create index if not exists app_sessions_user_idx on app_sessions (user_id);

  grant all on app_users to service_role;
  grant all on sequence app_users_id_seq to service_role;
  grant all on app_sessions to service_role;
  ```

- **`team_members`** (`20261118020000`, team tracker #148), verbatim without the header comment. Each manager's
  roster: records only, no logins. Read and written only by `app/team.py` (`/team/members`) and
  `app/access.py` `require_team_member`; also read by `app/team_uploads.py` (`GET /team/uploads`, #151, and `GET /team/uploads/videos`, #152). Deactivated (`is_active` false), never deleted:
  ```sql
  create table if not exists team_members (
      id          bigserial    primary key,
      name        text         not null,
      manager_id  bigint       not null references app_users(id),
      is_active   boolean      not null default true,
      created_at  timestamptz  not null default now()
  );

  -- Backs "the members of this manager" (every manager's roster read).
  create index if not exists team_members_manager_idx on team_members (manager_id);

  grant all on team_members to service_role;
  grant all on sequence team_members_id_seq to service_role;
  ```

- **`channel_assignments`** and **`assign_channel()`** (`20261118030000`, team tracker #149), verbatim without the
  header comment. Which team member holds which channel over `[starts_on, ends_on)`, IST dates (`team.IST`,
  `Asia/Kolkata`), `ends_on` NULL while current; one open row per channel. Written only by `app/team.py`:
  `POST /channels/{id}/assign` through the `assign_channel` RPC (closes the open row at the new start and opens
  the new one in one transaction; guarded by `tests/test_assign_channel_sql.py`), and `PATCH /team/members/{id}`
  deactivating a member (sets `ends_on` = today IST, or the row's `starts_on` if later, on their open rows). Read by
  `GET /team/assignments`, `GET /team/uploads` and `GET /team/uploads/videos` (`app/team_uploads.py`, #151, #152):
  ```sql
  create table if not exists channel_assignments (
      id              bigserial    primary key,
      channel_id      text         not null references channels(id) on delete cascade,
      team_member_id  bigint       not null references team_members(id),
      starts_on       date         not null,   -- IST date
      ends_on         date,                    -- exclusive; null = current
      assigned_by     bigint       references app_users(id),
      created_at      timestamptz  not null default now(),
      -- ends_on = starts_on is an empty range: an assignment replaced on the day
      -- it started, which credits nothing.
      constraint channel_assignments_range check (ends_on is null or ends_on >= starts_on)
  );

  -- At most one open assignment per channel.
  create unique index if not exists channel_assignments_one_open
      on channel_assignments (channel_id) where ends_on is null;

  -- Backs "the open assignments of this member" (deactivation).
  create index if not exists channel_assignments_member_idx
      on channel_assignments (team_member_id);

  grant all on channel_assignments to service_role;
  grant all on sequence channel_assignments_id_seq to service_role;

  -- Close the channel's open assignment and open the new one, in one transaction
  -- (PostgREST runs one statement per request; a function call is one
  -- transaction). The open row is locked first, so two concurrent assigns
  -- serialise; with no open row, the unique index refuses the second insert.
  -- The same member already open is returned unchanged. A start before the open
  -- row's start raises (the API refuses it first; this is the backstop).
  -- Guarded by tests/test_assign_channel_sql.py.
  create or replace function assign_channel(
      p_channel_id      text,
      p_team_member_id  bigint,
      p_starts_on       date,
      p_assigned_by     bigint
  )
  returns channel_assignments
  language plpgsql
  as $$
  declare
      v_open  channel_assignments;
      v_new   channel_assignments;
  begin
      select * into v_open
        from channel_assignments
       where channel_id = p_channel_id and ends_on is null
         for update;

      if found then
          if p_starts_on < v_open.starts_on then
              raise exception 'starts_on % is before the open assignment''s start %',
                  p_starts_on, v_open.starts_on
                  using errcode = '22023';
          end if;
          if v_open.team_member_id = p_team_member_id then
              return v_open;
          end if;
          update channel_assignments set ends_on = p_starts_on where id = v_open.id;
      end if;

      insert into channel_assignments (channel_id, team_member_id, starts_on, assigned_by)
      values (p_channel_id, p_team_member_id, p_starts_on, p_assigned_by)
      returning * into v_new;
      return v_new;
  end;
  $$;

  revoke execute on function assign_channel(text, bigint, date, bigint) from public;
  grant  execute on function assign_channel(text, bigint, date, bigint) to service_role;
  ```

- **`channel_uploads`** (`20261118040000`, team tracker #150), verbatim without the header comment. Every video
  the video sync fetches, with its upload time, including what `videos` leaves out: private and scheduled uploads,
  and Shorts on a `sync_shorts = false` channel (so the levers and the autopilot, which read `videos`, never see
  them). No FK to `videos`; a video deleted from YouTube keeps its row. Written only by `app/sync.py`
  `sync_channel` (`_record_uploads`), read only by `app/team_uploads.py` (`GET /team/uploads`, #151; `GET /team/uploads/videos`, #152). `uploaded_at` = the
  uploads-playlist item's `snippet.publishedAt` (#143's decision), else the first sync that saw it
  (`first_seen_at`); both raw timestamps are kept so it can be recomputed if #153's probe check picks
  `video_published_at`. Write-once in app code: new rows are inserted with ignore-duplicates; an existing row
  gets only `sync.UPLOAD_MUTABLE` (`title, privacy_status, scheduled_publish_at, is_short, thumbnail_url,
  video_published_at`) when one changed, plus `last_seen_at`; the trigger is the backstop. **Backfill:** none
  run; the 3-day full sync (`FULL_SYNC_INTERVAL`) fills each channel's history after deploy (a manual
  `POST /channels/{id}/sync?full=true` does one sooner), and videos deleted before that never appear. An
  incremental sync records only the videos it fetches (above the first id known in `videos`), so a scheduled
  video below a newer known one is updated at the next full sync:
  ```sql
  create table if not exists channel_uploads (
      video_id               text         primary key,
      channel_id             text         not null references channels(id) on delete cascade,
      title                  text,
      is_short               boolean,                 -- null = not yet classified
      duration_seconds       int,
      privacy_status         text,                    -- latest seen: private|unlisted|public
      scheduled_publish_at   timestamptz,             -- video status.publishAt; null once live
      thumbnail_url          text,
      uploaded_at            timestamptz  not null,   -- write-once (trigger below)
      playlist_published_at  timestamptz,             -- playlistItem snippet.publishedAt
      video_published_at     timestamptz,             -- video snippet.publishedAt, latest seen
      first_seen_at          timestamptz  not null default now(),
      last_seen_at           timestamptz  not null default now()
  );

  -- Backs "this channel's uploads in a date window" (the Team page's grid).
  create index if not exists channel_uploads_channel_uploaded
      on channel_uploads (channel_id, uploaded_at);

  -- uploaded_at and first_seen_at are write-once, whichever code path updates.
  create or replace function channel_uploads_freeze_uploaded_at()
  returns trigger
  language plpgsql
  as $$
  begin
      new.uploaded_at   := old.uploaded_at;
      new.first_seen_at := old.first_seen_at;
      return new;
  end;
  $$;

  drop trigger if exists channel_uploads_freeze on channel_uploads;
  create trigger channel_uploads_freeze
      before update on channel_uploads
      for each row execute function channel_uploads_freeze_uploaded_at();

  grant all on channel_uploads to service_role;
  ```
  Added by `20261120010000`, verbatim without its header comment:
  `alter table channel_uploads add column if not exists public_at timestamptz;`. When a sync or `upload_recheck`
  first found a row stored `unlisted` now `public` (`sync._went_public`; owner 2026-11-20: YouTube keeps
  `snippet.publishedAt` at the unlisted upload and records no switch); stamped once, NULL otherwise, including
  videos public before the column existed. A private video made public needs none (YouTube moves its
  `publishedAt`).

- **`channel_targets`** (`20261121000000`; replaces `member_targets` of `20261120000000`, dropped there), verbatim
  without the header comment. Each channel's daily upload target per ISO weekday (1 = Monday), Shorts and long-form
  apart; the current target only, no history, so a change recolours past days on the grid. Whoever is credited with
  the channel on a day (`team_uploads._holder`, the grid's crediting rule, backfill included) carries that day's
  target. Written only by `PUT /channels/{id}/targets` (`app/team.py`), read by `team.targets_for`
  (`GET /team/uploads`, `GET /team/board`):
  ```sql
  create table if not exists channel_targets (
      channel_id   text         not null references channels(id) on delete cascade,
      weekday      smallint     not null check (weekday between 1 and 7),
      shorts       int          not null default 0 check (shorts >= 0),
      long_form    int          not null default 0 check (long_form >= 0),
      updated_by   bigint       references app_users(id),
      updated_at   timestamptz  not null default now(),
      primary key (channel_id, weekday)
  );

  grant all on channel_targets to service_role;
  ```

- **`move_channel()`** (`20261121000000`), verbatim without its header comment. The Board's channel move in one
  transaction: to a member, the channel's `manager_id` becomes the member's and `assign_channel()` runs; to a tray
  (`p_team_member_id` null), `manager_id` = `p_manager_id` and the open assignment ends at `p_starts_on` (or its own
  start if later). Called only by `POST /channels/{id}/move`; guarded by `tests/test_team_board.py`:
  ```sql
  create or replace function move_channel(
      p_channel_id      text,
      p_team_member_id  bigint,
      p_manager_id      bigint,
      p_starts_on       date,
      p_moved_by        bigint
  )
  returns jsonb
  language plpgsql
  as $$
  declare
      v_manager  bigint;
      v_open     channel_assignments;
      v_row      channel_assignments;
  begin
      if p_team_member_id is not null then
          select manager_id into v_manager from team_members where id = p_team_member_id;
          if not found then
              raise exception 'team member % not found', p_team_member_id using errcode = '22023';
          end if;
          update channels set manager_id = v_manager where id = p_channel_id;
          v_row := assign_channel(p_channel_id, p_team_member_id, p_starts_on, p_moved_by);
          return jsonb_build_object('manager_id', v_manager, 'team_member_id', p_team_member_id,
                                    'assignment_id', v_row.id);
      end if;

      update channels set manager_id = p_manager_id where id = p_channel_id;
      select * into v_open
        from channel_assignments
       where channel_id = p_channel_id and ends_on is null
         for update;
      if found then
          update channel_assignments
             set ends_on = greatest(p_starts_on, v_open.starts_on)
           where id = v_open.id;
      end if;
      return jsonb_build_object('manager_id', p_manager_id, 'team_member_id', null,
                                'assignment_id', null);
  end;
  $$;

  revoke execute on function move_channel(text, bigint, bigint, date, bigint) from public;
  grant  execute on function move_channel(text, bigint, bigint, date, bigint) to service_role;
  ```

- **Other tables:** `audit_configs` (`raw_insights, generated_prompt, shorts_prompt, niche_queries jsonb, reflection_mode default 'shadow'`), `prompt_versions`, `threshold_history`, `playlist_assignments`, `playlist_proposals`, `video_keyframes`, `video_transcripts`, `quota_log`, `shorts_jobs`, `shorts_clips`. SQL functions: `dashboard_summary()`, `playlist_video_sims()`, `discover_orphan_clusters()`, `next_audit_candidate()`, `warm_pool()`, `assign_channel()` (above).

- **`warm_pool()`**, verbatim without its header comment, as of `20261030020000` (in-app twin `app/warm.py` `_ranked_pool_inapp`; the agent tick picks via `warm.warm_pool`). Excludes active Midas rows, any `midas` row within `p_cooldown_days`, and at any age backlinks holdout/applied rows and title holdout or non-`cancelled` treated rows:
  ```sql
  -- 20261023000000 only (20261030020000 has no drop):
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
            or (i.lever = 'backlinks'
                and (i.arm = 'holdout' or (i.arm = 'treated' and i.applied_at is not null)))
            or (i.lever = 'title'
                and (i.arm = 'holdout'
                     or (i.arm = 'treated'
                         and (i.applied_at is not null or i.status <> 'cancelled'))))
          )
      )
    order by rc.impressions desc, v.id;
  $$;

  revoke execute on function warm_pool(text, bigint, int, int, int) from public;
  grant  execute on function warm_pool(text, bigint, int, int, int) to service_role;
  ```

- **`decision_log`** (`20261006050000`), verbatim without its header comment. Written only by `app/decide.py` `decide()` (from `app/agent_tick.py`, `app/short_links.py`); `decide.link` sets `intervention_id`. `subject` = video id (`TRIAGE`) or `<source>-><target>` (`NEXT_WATCH`):
  ```sql
  create table if not exists decision_log (
      id                    bigserial   primary key,
      decided_at            timestamptz not null default now(),
      question_set_version  text        not null,
      subject               text        not null,   -- video / pair / candidate
      rules_answer          text        not null,
      jev_answer            text,
      jev_probs             jsonb,
      used                  text        not null,   -- rules|jev
      intervention_id       bigint      references interventions(id) on delete set null
  );
  ```
  `used` (`DecisionUsed`): always `rules` in shadow; `jev_answer`/`jev_probs` = the backend's answer (`llm`), NULL on failure.

- **`lever_verdicts`** (`20261023010000`), verbatim without its header comment. Written weekly by `app/lever_verdicts.py` `write_verdicts` (`backlinks`, `short_link`, `title`) and `app/playlist_test.py` `measure_channel` (`playlist`); read by `lever_verdicts.stopped` (the stop rule), `GET /channels/{id}/lever-verdicts`, `/playlist-test`, `/title-test`:
  ```sql
  create table if not exists lever_verdicts (
      id                   bigserial        primary key,
      channel_id           text             not null references channels(id),
      lever                text             not null,   -- backlinks
      arm_scope            text             not null,   -- treated_vs_holdout|human
      week_start           date             not null,
      n_treated            int              not null,
      n_holdout            int              not null,
      treated_mean_delta   double precision,
      holdout_mean_delta   double precision,
      lift                 double precision,
      cumulative_lift      double precision,
      windows_judged       int              not null,
      verdict              text,                        -- helped|no_change|worse
      stop_rule_triggered  boolean          not null default false,
      computed_at          timestamptz      not null default now(),
      unique (channel_id, lever, arm_scope, week_start)
  );
  ```
  `arm_scope` `treated_vs_holdout|human|pipeline_vs_holdout|agent_vs_holdout` (`20261030010000`, verbatim without its header comment: `comment on column lever_verdicts.arm_scope is 'treated_vs_holdout|human|pipeline_vs_holdout|agent_vs_holdout';`); `verdict` `helped|no_change|worse`, NULL on `human`.
  - backlinks `treated_vs_holdout`: per UTC week of `judged_at`; `lift` = treated − holdout mean delta, `cumulative_lift` over all weeks; verdict ±`BACKLINK_MIN_LIFT`; stop at `windows_judged` ≥ `BACKLINK_EXPERIMENT_WINDOWS` and `cumulative_lift` < `BACKLINK_MIN_LIFT`. Shorts excluded.
  - `human` (backlinks, `short_link`): `n_treated`, `treated_mean_delta`, `windows_judged` only; never stops.
  - `playlist`: per post week k of dosed vs holdout arms; verdict ±`PLAYLIST_MIN_LIFT`; stop at k ≥ `PLAYLIST_EXPERIMENT_WINDOWS` and `cumulative_lift` < `PLAYLIST_MIN_LIFT`.
  - `title`: each path vs the shared holdout (declines in the agent mean); verdict ±`TITLE_MIN_LIFT`; stop at (≥ `TITLE_EXPERIMENT_WINDOWS` and `cumulative_lift` < `TITLE_MIN_LIFT`) or (≥ `TITLE_HARM_WINDOWS` and `cumulative_lift` ≤ −`TITLE_HARM_LIFT`).

- **`playlist_arms`** (`20261027000000`), verbatim without its header comment, plus four `playlist_proposals` columns (that table: `id, video_id → videos, playlist_id → playlists, video_title, playlist_title, action, similarity, decision_source, status default 'pending', proposed_at, decided_at`). `app/playlist_test.py`: `draw` (once per channel) writes arms and `pending` `experiment` proposals; `apply_channel` moves treated arms `planned` → `applying` → `dosed`/`no_dose` and fills the proposals' apply columns (`apply_error {reason, detail, attempts}`); `measure_channel` writes `measurement_result {pre_weekly, weeks: [{k, start, end, starts, delta}], missing_days, added_video_views: [{k, views}], computed_at}` and ends arms `judged`/`insufficient_data`:
  ```sql
  create table if not exists playlist_arms (
      id                  bigserial    primary key,
      channel_id          text         not null references channels(id),
      playlist_id         text         not null,
      arm                 text         not null,   -- treated|holdout
      status              text         not null,   -- planned|applying|dosed|no_dose|holdout|judged|insufficient_data
      eligible_members    int,
      proposal_ids        bigint[],
      first_applied_at    timestamptz,
      last_applied_at     timestamptz,
      measurement_status  text,                    -- awaiting_window|measuring|done
      measurement_result  jsonb,
      drawn_at            timestamptz  default now(),
      unique (playlist_id)
  );

  -- decision_source gains 'experiment' (the playlist test's proposals); it has
  -- no check constraint, so nothing changes in the column itself.
  alter table playlist_proposals add column if not exists arm_id           bigint references playlist_arms(id);
  alter table playlist_proposals add column if not exists applied_at       timestamptz;
  alter table playlist_proposals add column if not exists playlist_item_id text;
  alter table playlist_proposals add column if not exists apply_error      jsonb;
  ```
  Vocab: `PlaylistArm`, `PlaylistArmStatus`, `PlaylistArmMeasurement`, `PlaylistProposalSource` (`experiment`).

- **`short_link_recommendations`** (`20261027010000`), verbatim without its header comment. Inserted only by `app/short_links.py` `refresh` (weekly): per new Short, `pending` target rows with B6 `similarity`, warm `impressions`, type-24 `feed_views`, and the pair's `NEXT_WATCH` `decision_log_id`. `set_short_link`/`dismiss_short_link` set `status`, `decided_at`, `intervention_id`; `detect` fills `seen_at`:
  ```sql
  create table if not exists short_link_recommendations (
      id                bigserial         primary key,
      channel_id        text              references channels(id),
      short_id          text              not null references videos(id) on delete cascade,
      target_video_id   text              not null references videos(id) on delete cascade,
      rank              smallint          not null,
      similarity        double precision  not null,
      impressions       bigint,
      feed_views        bigint,
      decision_log_id   bigint            references decision_log(id) on delete set null,
      status            text              not null default 'pending',   -- pending|set|not_chosen|dismissed
      decided_at        timestamptz,
      seen_at           timestamptz,
      intervention_id   bigint            references interventions(id) on delete set null,
      created_at        timestamptz       default now(),
      unique (short_id, target_video_id)
  );
  ```
  Vocab `ShortLinkStatus`.

Unbuilt spec tables: §7.1.

---

## 3. Config — verbatim

Defaults from `app/config.py`. "Dev `.env`" = the local, untracked `.env`. Office `.env` not read; on record: `AUTOPILOT_TICK_SECONDS=30` (`docs/PHASE_A_FINDINGS.md`) and the lever switches in §1 (`docs/PLAN_TO_2026-11-27.md`).

**Settings the spec names** (spec Part 1 A4/A6, Part 2 §8):

| Setting | Code (`app/config.py`) | Spec | Differs? |
|---|---|---|---|
| `PLAYLIST_DISCOVERY_ENABLED` | `os.getenv("PLAYLIST_DISCOVERY_ENABLED", "false").lower() == "true"` | default false (Part 1 A4) | no |
| `PLAYLIST_RECONCILE_WRITES_ENABLED` | `:122` same form, `"false"` | default false (A4) | no |
| `PLAYLIST_TUNING_ENABLED` | `:123` same form, `"false"` | default false (A4) | no |
| `REFLECTION_ENABLED` | `:34` same form, `"false"` | default false (A4) | no |
| `STRATEGY_LABEL` | `os.getenv("STRATEGY_LABEL") or "2026.07-baseline"` | prefix of a derived `strategy_version` (A6, Part 2 §8) | derived per audit, not at startup (§7.3) |
| `MIN_IMPRESSIONS` | `int(os.getenv("MIN_IMPRESSIONS") or "500")` | `WARM_MIN_IMPRESSIONS` starts "Same as `MIN_IMPRESSIONS`" (Part 2 §8) | no (separate setting, same default) |
| `MEASUREMENT_WINDOW_DAYS` | `or "21"` | measurement runs weekly (Part 2 §1.1); 14-day extension (§1.7) | **differs** (21-day window) |
| `PLAYLIST_JOIN_HIGH` / `_LOW` / `PLAYLIST_LEAVE` | `:126-128` `or "0.72"` / `"0.55"` / `"0.60"`, process-global | per channel, recalibrated (Part 2 §4, Part 3 B6) | **differs** in use: B6 calibrates per channel into `channels.playlist_thresholds` (`app/reembed.py` `calibrate_channel`), but the engine still reads these globals |
| `TRAFFIC_INGEST_CHANNELS` | `{c.strip() for c in (os.getenv("TRAFFIC_INGEST_CHANNELS") or "UCr5-YUqBiW7PUmeAtxUWuRg").split(",") if c.strip()}` | the rollout channel (Part 2 §8) | no |
| `HOLDOUT_PCT` | `float(os.getenv("HOLDOUT_PCT") or "0.20")` | 0.20, per lever, stable hash (Part 2 §8) | no; `interventions.assign_arm` |
| `WARM_MIN_IMPRESSIONS` | `int(os.getenv("WARM_MIN_IMPRESSIONS") or "500")` | 500 (Part 2 §8) | no; `app/warm.py` |
| `WARM_WINDOW_DAYS` | `int(os.getenv("WARM_WINDOW_DAYS")     or "28")` | 28 "Ingested data-days" (Part 2 §8) | no; `app/warm.py` |
| `WARM_EXPLORE_PCT` | `float(os.getenv("WARM_EXPLORE_PCT")   or "0.10")` | 0.10 "Picks from the non-top warm pool" (Part 2 §8) | no; `warm.warm_pool` |
| `DECIDE_BACKEND` | `os.getenv("DECIDE_BACKEND") or "llm"` | `llm`; `jev` once access is set up (Part 2 §8) | no; `app/decide.py` |
| `BACKLINK_MIN_CANDIDATES` | `int(os.getenv("BACKLINK_MIN_CANDIDATES") or "2")` | 2 (Part 2 §8) | no; `decide.TRIAGE` rules |
| `BACKLINK_MAX` | `int(os.getenv("BACKLINK_MAX") or "3")` | 3 (Part 4 Config, Part 2 §8) | no; `backlinks.render` |
| `AUDIT_MODEL` | `os.getenv("AUDIT_MODEL") or "anthropic/claude-haiku-4.5"`; dev `.env`: `google/gemini-3.7-flash` | reasoning model (Part 2 §3.1) | — |
| `SIBLING_MIN_VIEWS` | `int(os.getenv("SIBLING_MIN_VIEWS") or "100")` | 100, inbound only (Part 4 Config, Part 2 §8) | no; `backlinks.siblings` |
| `BACKLINK_SIBLINGS_ENABLED` | `os.getenv("BACKLINK_SIBLINGS_ENABLED", "false").lower() == "true"` | not in the spec (P2 links to siblings) | **yes**: while false (default, owner 2026-11-16) `backlinks.target_pool` reads no siblings, so every target is on the source's own channel (§7.3 item 35) |
| `BACKLINK_DUPLICATE_SIM` | `float(os.getenv("BACKLINK_DUPLICATE_SIM") or "0.98")` | not in the spec | **yes**: `backlinks.candidates` drops a target whose B6 cosine to the source or a better kept target is ≥ it (a re-upload; §7.3 item 35) |
| `TRIAGE_COOLDOWN_DAYS` | `int(os.getenv("TRIAGE_COOLDOWN_DAYS") or "7")` | 7 (Part 4 Config, finding 2; Part 2 §2.1, §8) | no; `app/warm.py` |
| `BACKLINK_APPLY_ENABLED` | `os.getenv("BACKLINK_APPLY_ENABLED", "false").lower() == "true"` | false, the kill switch for YouTube writes (Part 4 Config) | **yes, stricter**: while false and titles are closed, `_agent_tick` returns `apply_disabled` before any pick, where the spec cancels treated rows; with titles open, triage's `backlinks_enabled` keeps backlinks out |
| `TITLE_APPLY_ENABLED` | `os.getenv("TITLE_APPLY_ENABLED", "false").lower() == "true"` | false, the kill switch for title writes (Part 6 Config, F1); "while false no title row is written" | no; `app/titles_apply.py`, `agent_tick.titles_open` |
| `LEVER_MIN_SOURCE_VIEWS` | `int(os.getenv("LEVER_MIN_SOURCE_VIEWS") or "100")` | 100, §1.7 floor on the source's post-window views (Part 4 Config, Part 2 §1.7, §8) | no; `lever_measurement.evaluate` |
| `BACKLINK_EXPERIMENT_WINDOWS` | `int(os.getenv("BACKLINK_EXPERIMENT_WINDOWS") or "3")` | 3, the P1 time box (Part 4 Config, Part 2 §8) | no; `lever_verdicts.write_verdicts` |
| `BACKLINK_MIN_LIFT` | `float(os.getenv("BACKLINK_MIN_LIFT") or "1.0")` | 1.0 attributable views per treated video per week (Part 4 Config, D6, Part 2 §8) | no; `lever_verdicts.write_verdicts` |
| `PLAYLIST_HOLDOUT_PCT` | `float(os.getenv("PLAYLIST_HOLDOUT_PCT") or "0.5")` | 0.5, per playlist, stable hash (Part 5 Config, E4) | no; `playlist_test.assign_arm` |
| `PLAYLIST_TEST_MAX_ADDS` | `int(os.getenv("PLAYLIST_TEST_MAX_ADDS") or "5")` | 5, per treated playlist (Part 5 Config, E5) | no; `app/playlist_test.py` |
| `PLAYLIST_APPLY_ENABLED` | `os.getenv("PLAYLIST_APPLY_ENABLED", "false").lower() == "true"` | false, the kill switch for the test's YouTube writes (Part 5 Config) | no; `playlist_test.run_apply` |
| `PLAYLIST_TEST_DAILY_UNITS` | `int(os.getenv("PLAYLIST_TEST_DAILY_UNITS") or "2000")` | 2000, `JobBudget` for `playlist_test_apply` (Part 5 Config, E5) | no; `playlist_test.run_apply` |
| `PLAYLIST_TEST_MAX_ATTEMPTS` | `int(os.getenv("PLAYLIST_TEST_MAX_ATTEMPTS") or "3")` | 3, runs a failing add is retried (Part 5 Config) | no; `playlist_test._sendable` |
| `PLAYLIST_EXPERIMENT_WINDOWS` | `int(os.getenv("PLAYLIST_EXPERIMENT_WINDOWS") or "4")` | 4, weekly windows before the answer (Part 5 Config, E8) | no; `app/playlist_test.py` |
| `PLAYLIST_MIN_LIFT` | `float(os.getenv("PLAYLIST_MIN_LIFT") or "1.0")` | 1.0 starts per playlist per week (Part 5 Config, E8) | no; `playlist_test.measure_channel` |
| `SHORT_LINK_CHANNELS` | `{c.strip() for c in (os.getenv("SHORT_LINK_CHANNELS") or "UCr5-YUqBiW7PUmeAtxUWuRg").split(",") if c.strip()}` | Marathi, comma list (Part 5 Config, E13) | no; `short_links.run_weekly`, ∩ `TRAFFIC_INGEST_CHANNELS` |
| `SHORT_LINK_TARGETS` | `int(os.getenv("SHORT_LINK_TARGETS") or "3")` | 3 (Part 5 Config, E10) | no; `short_links.targets` |
| `SHORT_LINK_MIN_FEED_VIEWS` | `int(os.getenv("SHORT_LINK_MIN_FEED_VIEWS") or "1")` | 1 type-24 view over 28 ingested data-days (Part 5 Config, E9) | no; `short_links.shorts` |
| `SHORT_LINK_MAX_PER_RUN` | `int(os.getenv("SHORT_LINK_MAX_PER_RUN") or "50")` | 50 Shorts per weekly run (Part 5 Config) | no; `short_links._plan` |
| `SHORT_LINK_SEEN_MIN_VIEWS` | `int(os.getenv("SHORT_LINK_SEEN_MIN_VIEWS") or "1")` | 1 type-32 view for a pair to count as set (Part 5 Config, S2.6) | no; `short_links.seen_pairs` |
| `WRITER_MODEL` | `os.getenv("WRITER_MODEL") or AUDIT_MODEL` | = `AUDIT_MODEL`, set from the bake-off (Part 6 Config, F9) | no; `app/titles.py`, `app/agent/loop.py` |
| `TITLE_CANDIDATES` | `int(os.getenv("TITLE_CANDIDATES") or "3")` | 3 candidates per writer call (Part 6 Config) | no; `app/titles.py`, `app/agent/tools.py` |
| `TITLE_MAX_IMPRESSIONS` | `int(os.getenv("TITLE_MAX_IMPRESSIONS") or "5000000")` | 5000000, plus the top 1% (Part 6 Config, F2) | no; `titles._ceiling` |
| `TITLE_AGENT_PCT` | `float(os.getenv("TITLE_AGENT_PCT") or "0.5")` | 0.5, 0 = pipeline only (Part 6 Config, F5) | no; `titles.title_path`, `titles.route`, `titles._share` |
| `TITLE_CHANNELS` | `{c.strip() for c in (os.getenv("TITLE_CHANNELS") or "UCr5-YUqBiW7PUmeAtxUWuRg").split(",") if c.strip()}` | Marathi, comma list (Part 6 Config, F3) | no; `agent_tick.titles_open` |
| `TITLE_DAILY_CAP` | `int(os.getenv("TITLE_DAILY_CAP") or "10")` | 10 treated title rows per channel per day, inside `autopilot_daily_cap` (Part 6 Config, F4) | no; `agent_tick._title_enabled` |
| `TITLE_AGENT_DAILY_RUNS` | `int(os.getenv("TITLE_AGENT_DAILY_RUNS") or "20")` | 20 agent runs per channel per day, declines included (Part 6 Config, F14) | no; `agent_tick._title_enabled` |
| `TITLE_EXCLUDE_VIDEOS` | `{v.strip() for v in (os.getenv("TITLE_EXCLUDE_VIDEOS") or "").split(",") if v.strip()}` | empty, comma list (Part 6 Config, F12) | no; `agent_tick._assess`, `titles.would_title` |
| `AGENT_MAX_TURNS` | `int(os.getenv("AGENT_MAX_TURNS") or "12")` | 12 (Part 6 Config, Part 2 §8) | no; `agent.loop.run_title_agent` |
| `TITLE_WINDOW_DAYS` | `int(os.getenv("TITLE_WINDOW_DAYS") or "14")` | 14, post window; pre is 14 (Part 6 Config, F6) | no; `app/title_measurement.py` |
| `TITLE_MIN_PRE_VIEWS` | `int(os.getenv("TITLE_MIN_PRE_VIEWS") or "100")` | 100 browse + suggested views in the pre window, else `insufficient_data` (Part 6 Config, F6) | search counted too (§7.3 item 34); `title_measurement.evaluate`, `app/lever_verdicts.py` |
| `TITLE_MIN_LIFT` | `float(os.getenv("TITLE_MIN_LIFT") or "0.05")` | 0.05, log-ratio verdict band and stop bar (Part 6 Config, F7) | no; `lever_verdicts.title_verdicts` |
| `TITLE_EXPERIMENT_WINDOWS` | `int(os.getenv("TITLE_EXPERIMENT_WINDOWS") or "4")` | 4 (Part 6 Config, F7) | no; `lever_verdicts.title_verdicts` |
| `TITLE_HARM_WINDOWS` | `int(os.getenv("TITLE_HARM_WINDOWS") or "2")` | 2 (Part 6 Config, F7) | no; `lever_verdicts.title_verdicts` |
| `TITLE_HARM_LIFT` | `float(os.getenv("TITLE_HARM_LIFT") or "0.10")` | 0.10 (Part 6 Config, F7) | no; `lever_verdicts.title_verdicts` |
| `TITLE_REVERT_LIFT` | `float(os.getenv("TITLE_REVERT_LIFT") or "0.30")` | 0.30 (Part 6 Config, F8) | no; `lever_verdicts.auto_revert` |
| `TITLE_REVERTS_PER_DAY` | `int(os.getenv("TITLE_REVERTS_PER_DAY") or "10")` | 10 per channel per run (Part 6 Config, F8) | no; `lever_verdicts.auto_revert` |
| `PLAYBOOK_MIN_VIDEOS_PER_PATTERN` (5), `NICHE_REFERENCE_REFRESH_DAYS` (90), `NICHE_REFERENCE_QUOTA_BUDGET` (500) | **absent** | Part 2 §8 start values | **absent** |

**Every other setting, verbatim defaults** (`app/config.py`; dev `.env` overrides noted):
```
SCOPES = youtube, youtube.readonly, yt-analytics.readonly          (:16-22)
PROMPT_GEN_MODEL = os.getenv("PROMPT_GEN_MODEL") or "google/gemini-2.0-flash-001"     # dev .env: anthropic/claude-opus-5:online
REFLECTION_MODEL = os.getenv("REFLECTION_MODEL") or "anthropic/claude-sonnet-4-6"     # dev .env: anthropic/claude-sonnet-5
OTEL_ENABLED "false"  OTEL_ENDPOINT "http://phoenix:6006/v1/traces"  OTEL_SERVICE_NAME "midas"
DRY_RUN = os.getenv("DRY_RUN", "false")        # default: writes go to YouTube
YT_DAILY_QUOTA "10000"  YT_QUOTA_SAFETY_BUFFER "300"  YT_QUOTA_APPLY_RESERVE "1500"
YT_QUOTA_COLLECTION_RESERVE "3000"     # fleet readiness, not in the spec: autopilot applies (app/autopilot.py _can_afford_apply) stop this far short of the ceiling, leaving the day's syncs and polls room
AUTOPILOT_TICK_SECONDS "120"            # dev .env 100; office .env 30
AUTOPILOT_PICKER_USE_RPC "false"        # dev .env true; read only by autopilot._next_video_for_channel, which nothing calls
AUTOPILOT_PAUSE_COOLDOWN_MINUTES "60"
SHORTS_MAX_CONCURRENT_JOBS "2"  SHORTS_DISPATCH_INTERVAL_SECONDS "5"  SHORTS_YT_DOWNLOAD_ENABLED "false"
SHORTS_MAX_SOURCE_SECONDS "300"  SHORTS_CACHE_DIR "./shorts_cache"  SHORTS_CACHE_KEEP_DAYS "7"  LOG_DIR "logs"  LOG_LEVEL "INFO"
YOUTUBE_PROXY_URL ""  WEBSHARE_PROXY_USERNAME ""  WEBSHARE_PROXY_PASSWORD ""
PLAYLIST_HITL "true"  PLAYLIST_MUTATION_CAP "20"
PLAYLIST_SIMS_USE_RPC "false"           # dev .env true
PLAYLIST_DISCOVERY_USE_RPC "false"      # dev .env true
WARM_POOL_USE_RPC "false"               # (:253) B4; not in the spec: the RPC/in-app switch, as for the picker
PLAYLIST_RECONCILE_CHANNELS default "UCr5-YUqBiW7PUmeAtxUWuRg,UC8KjoL0Z9mTHKqB6gFutkJw,UCOVKJdzghm2gOnuaGeJTonA,UCc4Tv_DEGDEKrKAt-vyVNmw"   ("*" = all)  (:151-161)
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
`decide.QUESTION_SET_VERSION="2026.11-s3-v1"` (`app/decide.py:39`); `agent_tick.CONTEXT_DAYS=28`, `agent_tick.POOL_TTL_SECONDS=3600` (`app/agent_tick.py`); `lever_measurement.WEEK=7`, `EXTENDED_DAYS=14`, `RESTATEMENT_HORIZON_DAYS=28` (`app/lever_measurement.py`); `playlist_test.MIN_EMBEDDED_MEMBERS=3` (`app/playlist_test.py`); `short_links.FEED_WINDOW_DAYS=28` (`app/short_links.py`); `title_measurement.PRE_DAYS=14`, `SOURCE_TYPES=(3, 5, 7)` (`app/title_measurement.py:60,63`); `agent.loop.TRAJECTORY_CHARS=2000` (`app/agent/loop.py:47`); `session.SESSION_DAYS=30`, `session.COOKIE="midas_session"` (`app/session.py`); `agent.tools.SEARCH_TERMS=25`, `TOP_PERFORMERS=10`, `HISTORY=10` (`app/agent/tools.py:31-34`); `titles.DESCRIPTION_CHARS=1500`, `SEARCH_TERMS=10`, `TOP_PERFORMERS=5` (`app/titles.py:58-61`); `reembed.RECIPE="tdt-v1"`, `BATCH_SIZE=50`,
`_BYTES_PER_TOKEN=3`, `JOIN_HIGH_PCTL=50`, `LEAVE_PCTL=10`, `JOIN_LOW_PCTL=5`, `MIN_MEMBER_SIMS=30` (`app/reembed.py:33-51`); `quota.APPLY=(VIDEOS_LIST, VIDEOS_UPDATE)`
= 51u (`app/quota.py:50-67`); `openrouter.EMBED_MODEL="google/gemini-embedding-2-preview"` (`app/openrouter.py:7`).

---

## 4. Scheduled jobs

All registered in `app/main.py` `_register_jobs()`, called from `lifespan()`; `BackgroundScheduler`, each
`max_instances=1, coalesce=True`.

**Failure semantics.** `_run_per_channel` (`video_sync`, `playlist_reconcile`, `playlist_discovery`,
`playlist_tuning`, `reflection`, `playlist_health_score`) runs every channel, then raises one `JobRunFailed`
naming the failed ones. **Standard failure model** (the
polls and the newer jobs): a channel that raises anything but an expected skip fails the run once every channel
has run (`JobRunFailed("<job>", …)`); per-item errors go through `job_status.item_error_verdict` per category: all
failed → the channel fails as `"ItemsFailed: <category>: all <n> failed"`, some → `partial_errors`, recorded
`degraded`. `measurement_eval` raises `JobRunFailed` when any audit errored. `job_status.registry` records each job's `status`
(`never_run|success|degraded|failed`) and errors, kept in `LOG_DIR/job_status.json`, served at `GET /health/jobs`.

**Freeze flags (A4).** With its flag false a writer is not registered and startup logs
`"<job_id> not registered: <FLAG>=false"`. `playlist_reconcile` always registers; with
`PLAYLIST_RECONCILE_WRITES_ENABLED=false` it runs `sync_playlists` and skips `reconcile_channel`, logging
`"Daily reconcile <id>: add/remove skipped (PLAYLIST_RECONCILE_WRITES_ENABLED=false)"` per channel and
`"playlist_reconcile registered for sync only: add/remove skipped (PLAYLIST_RECONCILE_WRITES_ENABLED=false)"` at
startup. All four flags default false (§3); confirmed at the office 2026-09-29.

| Job id | Trigger | Entry point | Status |
|---|---|---|---|
| `autopilot` | interval `AUTOPILOT_TICK_SECONDS` | `app/autopilot.py` `tick`: pick channel (`Job.AUTOPILOT`) → Shorts action → if `agent_enabled`, `_agent_tick` (`can_run_agent`; no lever open → `apply_disabled`/`no_heading`) → daily cap → quota gate → `agent_tick.run`: warm pick → triage → record → treated apply (`apply_backlinks` or `apply_title`); else `shorts_only` | registered. `_can_afford_apply` skips with `quota_insufficient`, no pause. Daily cap (`autopilot_daily_cap`, default 10, `_applies_today`): applied audits and `midas` interventions applied today, plus today's unsent treated rows (not `declined`). Apply errors via `_react_to_apply_error` (quotaExceeded → fleet dormancy, token expiry → pause, `failed` → failure count); unclassified → `agent_failed` |
| `shorts_dispatch` | interval `SHORTS_DISPATCH_INTERVAL_SECONDS` (5 s) | `app/shorts/dispatcher.py:dispatch_tick` | registered |
| `shorts_cache_cleanup` | cron 03:15 local | `app/shorts/cache_cleanup.py` `run_daily` → `clean_cache` | registered (not in the spec; not caught up). Deletes `SHORTS_CACHE_DIR` entries: never a job in `WORKING_STATUSES`; a NAS job's folder (clips on the NAS) or one whose job isn't in `shorts_jobs`, at once; a YouTube-URL/AutoShorts job's folder or any other entry untouched for `SHORTS_CACHE_KEEP_DAYS` (7). Also `scripts/clean_shorts_cache.py` |
| `playlist_reconcile` | cron 02:00 server-local | `main._daily_reconcile` → `sync_playlists` (shared `JobBudget("playlist_sync", PLAYLIST_SYNC_QUOTA_BUDGET, reserve=YT_QUOTA_APPLY_RESERVE)`) + `reconcile_channel` | registered; `PLAYLIST_RECONCILE_CHANNELS` allowlist. **Add/remove frozen**; inventory sync and the budgeted membership walk run. Walk feeds `human_edits.record_playlist_additions` |
| `playlist_discovery` | cron Sun 03:00 local | `main._weekly_discovery` → `app/playlist_discovery.py` `discover_playlists` | **frozen** (`PLAYLIST_DISCOVERY_ENABLED`). When on: every channel; **creates playlists** (≤2/run), skipped under `DRY_RUN` |
| `reflection` | cron Mon 04:00 local | `app/reflection.py` `reflect` | **frozen** (`REFLECTION_ENABLED`). When on: every channel |
| `playlist_tuning` | cron Mon 03:30 local | `app/playlists.py` `tune_thresholds` | **frozen** (`PLAYLIST_TUNING_ENABLED`). When on: writes `settings.PLAYLIST_JOIN_HIGH` process-globally |
| `video_sync` | cron 04:00 UTC | `main._daily_video_sync` → `app/sync.py` `routine_sync` per channel | registered, every channel. Read-only: full pass if last full sync >3 days or the channel's `channel_uploads` history is missing (`sync.uploads_need_backfill`), else incremental + `refresh_stats` + `recheck_uploads` (a failure there is logged, never fails the sync). Expired/revoked token is a skip recorded `degraded`; any other error fails the channel. Full passes feed `human_edits.record_description_edits` |
| `upload_recheck` | interval `main.UPLOAD_RECHECK_HOURS` (2 h) | `main._upload_recheck` → `app/sync.py` `recheck_uploads` per channel | registered, every channel (not in the spec; not caught up). Read-only: re-reads the channel's `channel_uploads` rows uploaded within `sync.RECHECK_DAYS` (92) that are `private`, `unlisted` or scheduled (1u per 50), writes `channel_uploads` only, stamping `public_at` on unlisted → public. Expired token: a skip, `degraded`, as `video_sync` |
| `metrics_poll` | cron 05:00 UTC | `app/metrics_poll.py:poll_metrics` | registered; `analytics_authorized` channels; videos only in a measurement window (`METRICS_POLL_MEASURED_ONLY`). Standard failure model |
| `reporting_poll` | cron 06:00 UTC | `app/reporting_poll.py:poll_reporting` | registered; `analytics_authorized AND (measurement_enabled OR reach_warmup)`. Ingests only `channel_reach_basic_a1`. Standard failure model |
| `traffic_poll` | cron 06:30 UTC | `app/traffic_poll.py` `poll_traffic` | registered; `analytics_authorized` channels in `TRAFFIC_INGEST_CHANNELS`. Two isolated feeds: `channel_traffic_source_a3` → `video_traffic_source_daily`, `playlist_traffic_source_a2` → `playlist_traffic_daily`, restatements replace the day. Standard failure model; categories `video reports`, `playlist reports` |
| `playlist_health_score` | cron 07:00 UTC | `main._daily_playlist_health_score` → `app/playlist_health.py:score_channel` | registered; `playlist_health_enabled` channels (Punjabi only, §1) |
| `measurement_eval` | cron 08:00 UTC | `main._daily_measurement_eval` → `app/measurement.py:evaluate_with_failures` | registered |
| `lever_measurement` | cron Mon 09:00 UTC | `app/lever_verdicts.py` `run_weekly` | registered; every channel (`Job.EVERY`). Halves, each in its own `try` (standard failure model, category in brackets): `short_links.detect` (`short-link pairs`); `lever_measurement.measure_channel` + `write_verdicts` for backlinks, `short_link` (`interventions`); titles: `title_measurement.measure_channel` (`title interventions`), `write_verdicts(lever='title')`, `auto_revert` (`title reverts`); `playlist_test.measure_channel` (`playlist arms`). Only YouTube write: `revert_title(auto=True)` |
| `channel_health` | cron 10:00 UTC | `app/channel_health.py` `run_daily` | registered (not in the spec). Read-only `check()`; `JobRunFailed` if any channel has a problem: `last_synced_at` > `SYNC_STALE_HOURS` (30) or NULL, reach frontier > `REACH_STALE_DAYS` (7) behind, `channel_traffic_source_a3` frontier > `TRAFFIC_STALE_DAYS` (4) behind, or `autopilot_paused_reason` set. |
| `playlist_test_apply` | cron 11:00 UTC | `app/playlist_test.py` `run_apply` | registered; nothing while `PLAYLIST_APPLY_ENABLED` false. Sends approved adds of treated arms within `JobBudget("playlist_test_apply", PLAYLIST_TEST_DAILY_UNITS)` and `YT_QUOTA_COLLECTION_RESERVE`, else stops for the day. `failed` uses an attempt (`PLAYLIST_TEST_MAX_ATTEMPTS`); `youtube_quota_exceeded` stops the job (`degraded`); `token_expired` fails the channel. Standard failure model; category `playlist adds` |
| `short_link_refresh` | cron Mon 10:30 UTC | `app/short_links.py` `run_weekly` | registered; `refresh` per channel in `SHORT_LINK_CHANNELS` ∩ `TRAFFIC_INGEST_CHANNELS`. Refused thresholds → `degraded`. Standard failure model; category `shorts` |
| `nightly_db_backup` | cron `BACKUP_HOUR` local | `app/backup.py:run_nightly_backup` | registered; no-op if `BACKUP_ENABLED=false` |
| `pot_provider_refresh` | interval 2 h | `main._refresh_pot_provider` | only if env `BGUTIL_POT_HTTP_BASE_URL` is set; absent at the office |

Startup side effects: `provision.ensure_database_populated()` (restore from NAS if empty),
`shorts.runner.reap_stuck_jobs()`, `tracing.configure()`, then `startup_catch_up` (`app/catch_up.py`): runs each
`CATCH_UP` daily job whose fire time in the last `LOOKBACK` (24 h) has no recorded run. Not caught
up: `playlist_reconcile`, `playlist_test_apply`, `short_link_refresh`.

Spec'd jobs not registered: `niche_reference_refresh` (Part 2 §3.6) and playbook rebuild (Part 2 §1.1, §5).

---

## 5. Surface area

**Routes** (`app/main.py:603-625` mounts every router).

**The global gate** (`app/session.py` `gate`, registered by `app.middleware("http")(session.gate)` in
`app/main.py`), in order: a non-GET/HEAD/OPTIONS request whose `Origin` header isn't the request's `Host` (or is
`null`) → 403 `{"detail": "cross_origin_refused"}`, on every path (no `Origin` passes to the next step); a path in
`session.PUBLIC_PATHS` passes without a session: exactly `/login`, `/session/login`, `/static/theme.css`, `/static/midas.png`, `/health`
(exact paths, so `/health/jobs`, `/health/channels` and the rest of `/static` are gated); anything else needs a
valid `midas_session` cookie (an unexpired `app_sessions` row whose user is active, checked on every request; an
expired row is deleted), else a GET/HEAD for a page (`session.PAGES` = `/`, `/channel`, `/autoshorts`, `/team`, `/uploads`, `/results`, or any
request whose `Accept` has `text/html`) → 303 to `/login?next=<path and query>` (`/login` for `/`), and every other
request → 401 `{"detail": "not_authenticated"}`. The signed-in user is on `request.state.user` (`{id, email, name,
role}`). The gate checks login only; what a signed-in user may reach is `app/access.py`'s (below). Scheduled jobs
don't pass through either.

**Access** (`app/access.py`, team tracker #145). `admin` and `exec` see every channel; a `manager` sees the channels
whose `channels.manager_id` is them (`visible_channel_ids`, `filter_channels`); a channel with no manager is seen by
admin and exec only. Every route whose path has a `{channel_id}` (34 routes, plus `PATCH /channels/{id}/manager`)
has `dependencies=[Depends(require_channel)]`: 404 `{"detail": "channel_not_found"}` for a channel the user can't
see, the same body as an unknown one (never 403); for admin and exec it reads nothing and passes, leaving an unknown
id to the route as before; for a manager it reads `channels` once per request. `require_role(*roles)` → 403
`{"detail": "forbidden"}`. `current_user` = `request.state.user` (401 if unset).
Routes addressed by another object's id (#146) depend on that object's resolver, which maps the object to its channel
and applies the same check: `require_video` (`videos.channel_id`) on `GET /videos/{id}`, `POST /videos/{id}/audit`,
`GET /videos/{id}/audits`, `POST /videos/{id}/short`; `require_audit` (the audit's video's channel) on
`POST /audits/{id}/apply`, `POST /audits/{id}/revert`, `GET /audits/{id}/measurement`; `require_intervention`
(`interventions.channel_id`) on `POST /interventions/{id}/revert`; `require_short_link`
(`short_link_recommendations.channel_id`, else the Short's channel) on `POST /short-links/{id}/set|dismiss`;
`require_shorts_job` (`shorts_jobs.channel_id`) on `GET /shorts/jobs/{id}`; `require_shorts_clip` (the clip's job's
channel) on `GET /shorts/clips/{id}/file`, `POST /shorts/clips/{id}/upload`. For a manager, an unknown object and one
on a channel they can't see answer the same 404: `{"detail": "video_not_found"}`, `"audit_not_found"`,
`"intervention_not_found"`, `"short_link_not_found"`, `"shorts_job_not_found"`, `"shorts_clip_not_found"`; admin and
exec read nothing and pass, leaving an unknown id to the route's own 404 as before.
`require_team_member` (#148, `team_members.manager_id` = the user) on `PATCH /team/members/{id}`: for a manager,
another manager's member and an unknown id answer the same 404 `{"detail": "team_member_not_found"}`; admin and exec
read nothing and pass.
List and global routes (#147) depend on `current_user` and narrow what they read to `visible_channel_ids`
(`access.scope_to_visible`: `in_` the visible ids, or nothing read when there are none); a channel named in a body
or query string goes through `access.check_channel` (the same 404 `channel_not_found`). Admin-only routes depend on
`access.require_admin` (= `require_role(UserRole.ADMIN)`, 403 `{"detail": "forbidden"}` to exec and managers):
`GET /auth/login`, `GET /auth/callback`, `GET /quota`, `GET /quota-cost-preview`, `GET /health/jobs`,
`GET /health/channels`, `POST /measurement/evaluate`, and `PATCH /channels/{id}/manager`.
Each dependency carries
`access_rule = True`; `tests/test_route_access.py` walks `app.routes` and fails on a route with none that isn't on its
open list (`/login`, `/session/login`, `/health`, `/session/logout`, `/`, `/channel`). There is no pending list: every
other route is scoped, and a new unscoped route fails CI.

- **Access** (`app/access.py` `router`): `PATCH /channels/{id}/manager` body `{manager_id: int | null}`, admin only
  (`require_channel` first, so a manager asking about another team's channel gets 404, about their own 403; exec
  403). `manager_id` must be an active `manager` user, else 400 `"manager_id must be an active manager"`; null
  clears; unknown channel 404. → `{"id", "manager_id"}`.

- **Session** (`app/session.py` `router`): `GET /login` → `static/login.html` (public); `POST /session/login` (public)
  body `{email, password}` → `{"user": {id, email, name, role}}` and sets `midas_session` (`httpOnly`,
  `SameSite=Lax`, `Max-Age` 30 days (`SESSION_DAYS`), `Path=/`, `Secure` only over https); a wrong email, wrong
  password or inactive user → 401 `{"detail": "Email or password is wrong."}` (`LOGIN_FAILED`), no session; an
  unknown email spends one argon2 verify so it answers as slowly as a wrong password. `POST /session/logout` → 204,
  deletes the session row and the cookie. `GET /session/me` → `{id, email, name, role}`.

- **Team** (`app/team.py` `router`, team tracker #148): `GET /team` (the Roster) and `GET /uploads` (the uploads grid) → `static/team.html` (any signed-in user), which shows one panel by path.
  `GET /team/members` (`current_user`) → `{"members": [{id, name, manager_id, manager_name, is_active,
  created_at}], "managers": [{id, name}]}`, deactivated members included, ordered by manager name then member
  name: a manager gets their own members and `managers` = themselves; admin and exec every member and the active
  `manager` users. `POST /team/members` body `{name, manager_id?}` → 201 with the member: `name` stripped, 1–100
  characters (`NAME_MAX`, else 422); a manager adds under themselves (`manager_id` omitted or their own, another
  → 403 `forbidden`); admin and exec must give `manager_id` (400 `"manager_id is required"`), an active `manager`
  (400 `"manager_id must be an active manager"`). `PATCH /team/members/{id}` (`require_team_member`) body
  `{name?, is_active?, manager_id?}`: rename, deactivate or reactivate; an empty body 400 `"nothing to change"`;
  `manager_id` moves the member to another manager, admin only (else 403 `forbidden`), an active `manager` (else
  400 `"manager_id must be an active manager"`). Deactivating or moving a member ends their open channel assignments
  (§2 `channel_assignments`); the channels keep their manager.
  `POST /channels/{id}/assign` (`current_user`, `require_channel`; #149) body `{team_member_id, starts_on?}` →
  `{"assignment": {id, channel_id, team_member_id, starts_on, ends_on, assigned_by, created_at, member_name,
  assigned_by_name}, "changed"}`: `starts_on` defaults to today in IST (`team.ist_day`); before the open row's
  start → 400 (`"starts_on <d> is before the current assignment's start <d>"`); an unknown channel 404
  `channel_not_found` (for admin and exec too); a manager's channel must be theirs (`require_channel`) and the member
  theirs, else 404 `team_member_not_found` (also an unknown member); admin and exec assign any member to any channel;
  a deactivated member 400 `"team member is deactivated"`; the member already holding it → `changed` false, nothing
  written; else the `assign_channel` RPC, an `APIError` (a concurrent assign) → 409 `"the channel's assignment
  changed meanwhile; try again"`. `GET /team/assignments` (`current_user`) → `{"channels": [{id, name,
  manager_id, manager_name}], "assignments": [...]}`: the user's visible channels (`access.filter_channels`) by
  name, and every assignment on them, current and past, newest `starts_on` first.
  `PUT /team/members/{id}/channels` (`current_user`, `require_team_member`) body `{channel_ids}` → `{"channel_ids",
  "added", "ended"}`, the Roster's channel picker: each listed channel the member doesn't hold is assigned to them
  from today IST (or the open row's start if later) through the `assign_channel` RPC (`team._assign`), and each
  channel they hold that the user can see but isn't listed is ended today (`_end_assignments(member_id,
  channel_ids)`), left unassigned; a channel they hold that the user can't see is never ended. A listed channel the
  user can't see → 404 `channel_not_found`, nothing written; a deactivated member with any channel listed → 400
  `"team member is deactivated"`; an RPC `APIError` → 409, channels already done stay done (one transaction per
  channel, not per request).
  `PUT /channels/{id}/targets` (`current_user`, `require_channel`) body `{"days": {"<1-7>": {shorts?,
  long_form?}}}` → `{"targets"}`: a weekday or type left out is 0, each 0–500 (`TARGET_MAX`, else 422); all zero
  deletes the channel's rows (`targets` null), else the seven `channel_targets` rows are upserted with `updated_by`;
  exec → 403 `forbidden`; another team's or an unknown channel → 404 `channel_not_found`.
  `POST /channels/{id}/move` (`current_user`, `require_channel`) body `{team_member_id}` (to that member, and to
  their manager) or `{manager_id?}` with `team_member_id` null/omitted (into a tray: unheld; `manager_id` omitted =
  the channel's current manager, null = no manager) → `{"before", "after", "changed"}`, each `{team_member_id,
  manager_id}`: from today IST (or the open row's start if later) through the `move_channel` RPC; `after` equal to
  `before` → `changed` false, nothing written. Exec → 403; a manager: only their own channels (404), their own
  active members (another's 404 `team_member_not_found`, deactivated 400 `"team member is deactivated"`), their own
  tray (another manager's or none → 403); the admin anything, a tray's `manager_id` an active manager (else 400);
  an RPC `APIError` → 409. The page undoes a move by moving back to `before`.

- **Board** (`app/team_board.py` `router`): `GET /team/board` (`current_user`) → `{"today", "me": {id, role},
  "managers": [{id, name, is_active}], "members": [{id, name, manager_id, is_active}], "channels": [{id, name,
  manager_id, holder_id, since, targets, today_target, today}]}`: managers = every active manager plus any still
  owning a channel or member (admin and exec), or the user (a manager); their members, deactivated included; the
  user's visible channels with the open assignment's member and `starts_on`, the weekly targets, today's (IST)
  weekday target and the uploads live today, credited by `team_uploads._credited`. Read-only.

- **Team uploads** (`app/team_uploads.py` `router`, team tracker #151): `GET /team/uploads?from=&to=&manager_id=`
  (`current_user`) → `{"from", "to", "days", "manager_id", "managers", "channels", "rows"}`. The window is IST days
  `[from, to]` (`YYYY-MM-DD`): default the last 7 ending today IST (`DEFAULT_DAYS`); one end given → 7 days from or to
  it; backwards, longer than `MAX_DAYS` (92) or not a date → 422. `channels` = the user's visible channels
  (`access.filter_channels`), narrowed to `manager_id`'s for admin and exec only (a manager's `manager_id` is ignored
  and echoed as null), each `{id, name, manager_id, last_synced_at}` by name. Places each video on its go-live IST day
  (`team_uploads.live_at`, owner 2026-11-19: the team schedules weekend videos ahead): `scheduled_publish_at` when
  set, else nothing for a `private` video (never went live, not counted), else `public_at` (an unlisted video seen
  going public, owner 2026-11-20), else `video_published_at` (YouTube's publish time; an unlisted video counts there
  until it goes public), else `uploaded_at`. Reads `channel_uploads` for those channels with any of those four in `[from
  00:00 IST, to + 1 00:00 IST)` (one range read per column, `uploaded_at` only where `video_published_at` is NULL,
  merged by `video_id`), and their `channel_assignments`, all through `rows.rows_for_ids` (paged past the 1000-row
  cap); a future day holds what is already scheduled for it. Credits each video to the member whose assignment covered its
  channel on its go-live IST day (`starts_on <= day < ends_on`, NULL = open); an upload from before the channel's
  first assignment (earliest `starts_on`, then `id`, over all its assignments, not just the window's) to that first
  assignee (backfill, owner 2026-11-19); else Unassigned (never assigned, or a gap between assignments). `rows`: the in-scope
  managers' active members plus anyone credited or assigned in the window, by manager name then member name, then
  Unassigned (`member_id` null, name `"Unassigned"`, always present); each `{member_id, name, manager_id,
  manager_name, is_active, days: {<day>: {total, shorts, long_form}}, total, targets, channels}`, every day present
  (zeros included); a NULL `is_short` counts as long-form. `channels`: one row per channel credited to the member on
  any day of the window (`_holder`, backfill included), by name, each `{channel_id, name, days, total, targets}`, a
  day the member didn't hold it null in both, a held day's `targets` that weekday's `channel_targets` `{shorts,
  long_form}` (null when none); the member's `targets` per day = the sum over those channels (null when none).
  Unassigned's channels are the days nobody held them. `managers` = the active `manager` users for admin and exec
  (the filter), `[]` for a manager. `channel_rows` (read by the page's summary): one row per entry of `channels`, in its
  order, each `{channel_id, name, manager_id, manager_name, days, total}`, counting every upload on the channel
  whoever was credited (zeros included), so it totals the same as `rows`. Computed in Python, no SQL function. Its IST conversion (`ist_day`,
  `ist_midnight`) is its own, not the quota day.
  `GET /team/uploads/videos?day=&member_id=&manager_id=&channel_id=&by_member=` (`current_user`, #152) → `{"day", "member_id",
  "channel_id", "name", "manager_id", "videos"}`: the uploads behind one grid cell, read and credited by the grid's own code (`_scope`,
  `_credited`), so a cell's count equals its list's. `day` (IST, `YYYY-MM-DD`) required, else 422; `member_id`
  omitted = Unassigned (`name` `"Unassigned"`); `manager_id` honoured for admin and exec only, as the grid. An
  `channel_id` lists that channel's uploads that day whoever was credited, `member_id` ignored (returned null),
  `name` the channel's; with `by_member=true` (a channel row in a member's section) only those credited to
  `member_id` (omitted = Unassigned); a
  channel outside the scope (`channels` above, `manager_id` included) → 404 `channel_not_found`. An
  unknown `member_id` → 404 `team_member_not_found` for everyone; for a manager, also a member who is neither theirs
  nor ever assigned to one of their channels (the same 404). `videos`, by go-live time: `{video_id, title,
  thumbnail_url, channel_id, channel_name, uploaded_at, uploaded_at_ist (+05:30), live_at, live_at_ist, is_short (NULL kept),
  privacy_status, scheduled_publish_at, status}`; `status` = `scheduled` while `scheduled_publish_at` is set, else
  `privacy_status` (derived, not stored).

- **Pages/health:** `GET /login` (Session, above); `GET /` → `static/index.html`; `GET /channel` → `static/channel.html`; `GET /health` → `{"ok": True, "dry_run": …}`; `GET /health/jobs` (admin only) → `{"jobs": {<job_id>: {status, last_run_at, error, failed_channels, partial_errors}}}`; `GET /health/channels` (`app/channel_health.py`, admin only) → per-channel freshness and `problems`, channels with problems first; `GET /autoshorts` (`app/shorts/autoshorts.py`, any signed-in user); `/static/*`.
- **Auth/channels** (`app/auth.py`, prefix `/auth`): `GET /auth/login`, `GET /auth/callback` (both admin only; the callback stores tokens, sets `analytics_authorized` from granted scopes, clears the `token_expired` pause), `GET /auth/channels` (only the user's visible channels, `access.filter_channels`; the sidebar switcher and the channel page read it), `PATCH /auth/channels/{id}` (`require_channel`; no `manager_id` field; enabling `measurement_enabled` is 409 unless `reach.certify` passes, `app/auth.py:166-174`).
- **Sync** (`app/sync.py`): `POST /channels/{id}/sync?full=`, `POST /channels/{id}/refresh-stats`, `POST /channels/{id}/refresh-applied-stats`, `GET /channels/{id}/videos`, `GET /videos/{id}`.
- **Audits** (`app/audits.py`): `GET|POST /channels/{id}/audit-config`, `POST /channels/{id}/audit-config/elaborate`, `POST /videos/{id}/audit`, `GET /videos/{id}/audits`, `POST /audits/{id}/apply?force=`, `POST /channels/{id}/audits/apply-pending?force=` (both 409 `AGENT_CHANNEL_REFUSED`, "agent channel: a house-format apply replaces the description and its backlink block; pass force=true", on an `agent_enabled` channel unless `force=true`, before anything is sent or written; `audits._refuse_on_agent_channel`), `POST /channels/{id}/audits/reaudit-quarantined`, `POST /channels/{id}/audits/run-bulk` (both only write `pending` audits, so unguarded), `POST /audits/{id}/revert` (409 "agent channel: an audit revert …; pass force=true" on an `agent_enabled` channel unless `?force=true`; 409 `quota_insufficient` when `quota.can_afford(quota.cost(Op.VIDEOS_UPDATE))` is false, `app/audits.py:847-852`), `GET /quota-cost-preview` (admin only; the channel page's apply confirm shows no cost estimate when it is refused).
- **Measurement** (`app/measurement.py`): `GET /audits/{id}/measurement`, `GET /channels/{id}/outcomes`, `POST /measurement/evaluate` (admin only).
- **Reflection** (`app/reflection.py`): `GET /channels/{id}/reflection/history`, `POST /channels/{id}/prompt-versions/{vid}/promote`, `POST /channels/{id}/reflection/trigger`, `GET /channels/{id}/reflection/shadow-comparison`. Promote and trigger 409 `"Reflection is frozen: REFLECTION_ENABLED=false"` (`app/reflection.py:792`).
- **Playlists** (`app/playlists_router.py`): `POST /channels/{id}/playlists/evaluate`, `GET /channels/{id}/playlists/health`, `POST /channels/{id}/playlists/bootstrap` (sync + embed all), `GET /channels/{id}/playlists/status`, `POST /channels/{id}/playlists/reconcile` (409 `"Playlist reconcile writes are frozen: PLAYLIST_RECONCILE_WRITES_ENABLED=false"`, `:263-267`), `GET /channels/{id}/playlists/proposals` (every `pending` proposal, `arm_id` ones first, then `proposed_at`, `id`), `POST /channels/{id}/playlists/proposals/decide` (executes adds/removes on YouTube, not frozen; `rejected` relabels only `pending` proposals; a proposal with `arm_id` is only marked `approved`/`rejected` and sends nothing, the response gaining `queued` when any).
- **Autopilot** (`app/autopilot.py`): `POST /channels/{id}/autopilot/resume`, `GET /channels/{id}/autopilot/log`.
- **Interventions** (`app/backlinks_apply.py`): `POST /interventions/{id}/revert`, for an applied (`applied_at` set, not `cancelled`) `midas` `backlinks` or `title` row only (else 400 "Only an applied Midas title|backlinks intervention can be reverted"; 404 unknown). A `title` row → `titles_apply.revert_title(row, auto=False)`: 409 `apply_disabled` (`TITLE_APPLY_ENABLED` false), 409 `quota_insufficient`, `DRY_RUN` → `{"status": "dry_run", "title"}`, 409 `title_changed` (live title isn't `payload.title`), else `{"status": "cancelled", "title"}`. A `backlinks` row: fetches the live snippet, `backlinks.strip`s it, sends it back `part=snippet` with only `description` changed; 409 `apply_disabled` (`BACKLINK_APPLY_ENABLED` false), 409 `quota_insufficient` (51u, `quota.APPLY`); `DRY_RUN` → `{"status": "dry_run", "description"}`, no write. Sets `cancelled`, `payload.revert = {reverted_at, live_before, description}`, `videos.description`.
- **Channel SEO** (`app/channel_seo.py`): `GET /channels/{id}/seo` (`require_channel`) → `{"agent_enabled", "levers": {backlinks|title: {on, reason}}, "today": {written, cap}, "verdicts", "interventions", "videos"}`: each lever's state and first reason it can't write (`channel_seo.lever_states`, mirroring `agent_tick.backlinks_enabled`/`titles_open`), `autopilot._applies_today` against `autopilot_daily_cap`, the latest `lever_verdicts` row per (lever, `arm_scope`), every intervention of the channel newest first trimmed by `channel_seo.trim` (no `trajectory`, no candidates: title, title_before, path, targets `{video_id, title}`, error reason, `reverted_at`, delta, pre, post), and `{id: {title, thumbnail_url, is_short}}` for the videos they name. Read-only; the channel page's read.
- **SEO results** (`app/seo_results.py` `router`, #167 tickets 02–03): `GET /results` → `static/results.html` (any
  signed-in user). `GET /seo/results?channel_id=&lever=` (`current_user`) → `{"generated_at", "next_judgement",
  "first_title_verdicts", "channels": [{id, name, levers: {backlinks: cell, title: cell}}],
  "fleet": {"levers": {backlinks: cell, title: cell}}}`, read-only.
  `channels` = the user's visible channels (`access.filter_channels`) by name; a named `channel_id` goes through
  `access.check_channel`, and another team's or an unknown one (admin and exec too) → 404 `channel_not_found`; an
  unknown `lever` → 400 `"unknown lever: <x>"`; `lever` keeps only that column (`LEVERS` = backlinks, title, playlist, short_link).
  `next_judgement` = the next Monday 09:00 UTC (`JUDGEMENT_WEEKDAY`, `JUDGEMENT_HOUR`, the `lever_measurement`
  job's cron in `app/main.py`). One paged read each of `interventions` and `lever_verdicts` of the lever, narrowed by
  `access.scope_to_visible`. A channel's cell: `state` = `channel_seo.lever_states(channel)[lever]` (the channel
  page's answer); `counts` over `midas` rows: `written` (treated, `applied_at` set), `holdout`, `declined`,
  `cancelled` `{payload.error.reason or "unknown": n}` (not reverted), `reverted` `{auto, manual}`
  (`payload.revert.auto`), `judged` (the rows in the means), `insufficient_data`, `awaiting`
  (`ACTIVE_INTERVENTION_STATUSES`), `shorts_excluded` (judged rows on Shorts, `lever_verdicts._without_shorts`), and
  the team's: `team`, `team_judged` (never in a mean); `n_treated`, `n_holdout`, `treated_mean_delta`,
  `holdout_mean_delta`, `lift` (treated − holdout mean over the judged `midas` treated/holdout rows not on a Short,
  every week, current deltas); `cumulative_lift`, `windows_judged`, `verdict` from the latest `treated_vs_holdout`
  `lever_verdicts` row; `stop_rule_triggered` (any week) and `stopped_week` (the first that fired); `weeks` = every
  `treated_vs_holdout` row, oldest first. The fleet cell sums the counts, `state` `{on, reason, channels_on,
  channels}`, pools the means and `lift` over every judged row of the visible channels (= `cumulative_lift`), not an
  average of channel lifts, `weeks` pooled per judged week through `lever_verdicts.verdicts`, `windows_judged` = their
  number, no `verdict` or stop of its own (null), `stopped_channels`.
  The **playlist cell** (#171) is `playlist_test.playlist_test_summary`'s figures (`GET /channels/{id}/playlist-test`
  reads the same function): `answer` (`pending|yes|no`), `test_start`, `test_end`, `arms` (count per
  `playlist_arms.status`), `lift`/`cumulative_lift`/`windows_judged`/`verdict` of the latest `treated_vs_holdout`
  row, `stop_rule_triggered`, `stopped_week`, `weeks`. Its fleet cell sums `arms`, lists each channel's answer
  that has arms (`answers {channel_id: answer}`) and has no `answer` or lift of its own (answers are never pooled);
  `stopped_channels`. The **Short-link cell** is the team's work (`by: "team"`, no lift): `recommendations`
  (`pending|set|not_chosen|dismissed` counts from `short_link_recommendations`, narrowed on its `channel_id`, so
  a row with a NULL one is left out), `seen` (rows with `seen_at`), `team`/`team_judged` (`human` `short_link`
  interventions), `verdict` (the latest `human` `lever_verdicts` row: `week_start`, `n_treated`,
  `treated_mean_delta`, `windows_judged`; null with none); the fleet cell sums the counts. Neither has a `state`.
  The **title cell** (#170) has those fields, read from `lever_verdicts` rows of both title scopes
  (`pipeline_vs_holdout`, `agent_vs_holdout`; `SCOPES`), plus `paths: {pipeline, agent}` and `first_verdict`. A path
  holds `lever_verdicts.title_paths`' own figures (`treated, declined, cancelled, judged, insufficient, mean_delta,
  cumulative_lift, auto_reverts, stopped`, the same function `GET /channels/{id}/title-test` reads, so the two agree
  on the same rows: each path against the shared holdout, an agent decline in the agent's mean, a title put back
  after it was judged still in its path's mean) and, added, `n_treated`, `n_holdout`, `treated_mean_delta`,
  `holdout_mean_delta`, `lift` (= `cumulative_lift`), `windows_judged`, `verdict`, `stop_rule_triggered`,
  `stopped_week`, `weeks` from that path's scope. The cell's `n_*`/means/`lift` pool both paths (the `_counted`
  rows with a known path, or the holdout) against the holdout; its `verdict`, `windows_judged`, `weeks` and
  `cumulative_lift` are the lead path's (more titles written, ties the pipeline); `stop_rule_triggered` is true when
  either path's fired, `stopped_week` the earliest. `counts`: `declined` and `judged` follow the title-test summary
  (a measured decline is `judged` and still a decline; a title reverted after its judgement is in `judged` and in
  `reverted`); `cancelled` by `payload.error.reason`, `reverted` `{auto, manual}`; titles are never left out as
  Shorts. `first_verdict` = the earliest, over `midas` rows still in their window (`title_measurement._pending`), of
  `title_measurement.as_of` + `TITLE_WINDOW_DAYS` + `TRAFFIC_LAG_DAYS` (2, the steady report lag), null with none;
  `first_title_verdicts` is the earliest over the visible channels, null when `lever` leaves titles out. The fleet's
  title cell sums the counts and pools the means and each path over every visible row (the path's `stopped` = any
  channel's, `stopped_channels` their number, `verdict`/`stop_rule_triggered`/`stopped_week` null).
- **Interventions and verdicts** (`app/lever_verdicts.py`): `GET /channels/{id}/interventions?lever=&status=&limit=&offset=` → `{"interventions", "limit", "offset", "next_offset"}`, newest first, `limit` default 100, max 1000 (422 above), `next_offset` set when a page is full; unknown `lever`/`status` 400. `GET /channels/{id}/lever-verdicts` → `{"verdicts", "backlinks_stopped"}`, every row of the channel, newest week first.
- **Title test** (`app/lever_verdicts.py`): `GET /channels/{id}/title-test` (`title_test_summary(channel_id)`, which is `title_paths(rows, is_stopped)` plus the trace; the Results page reads `title_paths` too) → per path (`pipeline`|`agent`) `{treated, declined, cancelled {reason: n}, judged, insufficient, mean_delta, cumulative_lift, auto_reverts, stopped}`, `holdout {n, judged, mean_delta}`, and `trace` (tool-set stats over agent trajectories, `agent.loop.tools_called`). Read-only; reads `trajectory`, so needs `20261030000000`.
- **Playlist test** (`app/playlist_test.py` `router`): `GET /channels/{id}/playlist-test` (`playlist_test_summary(channel_id)`) → `{"test_start", "test_end", "arms", "verdicts", "answer"}`; `answer` `pending` until a `treated_vs_holdout` row with `windows_judged` ≥ `PLAYLIST_EXPERIMENT_WINDOWS`, then `no` if it triggered the stop rule, else `yes`. Read-only.
- **Short links** (`app/short_links.py` `router`; nothing reaches YouTube): `GET /channels/{id}/short-links?status=&limit=&offset=&format=` → one page of Shorts (not rows), those with a `pending` row first, then feed views, id, each with its recommendations in rank order plus YouTube/Studio URLs; unknown `status` 400, `limit` max 1000 (422 above); `format=csv` (else `json`; other 422) as `short-links-<id>.csv`, formula-leading cells prefixed `'` (`_cell`). `POST /short-links/{id}/set` (404 unknown): already `set` → `recorded: false`; else records the `human` `short_link` intervention (§2) under `_episode_key`, the Short's other `pending`/`set` rows → `not_chosen` (a `dismissed` stays), this row → `set`; → `{"recommendation", "intervention_id", "recorded"}`. `POST /short-links/{id}/dismiss` (404; 409 `"set: tick another target to change the Short's link"` on a `set` row) → `dismissed`, no intervention.
- **Ops:** `GET /dashboard` (`app/dashboard.py`): admin and exec get the cached fleet payload as before; a manager
  gets it narrowed on read (`dashboard._scoped`) to their channels: their rows, `kpis`/`health`/`pipeline` over them
  only (`_summaries`, shared with the fleet path), and the fleet-wide figures (`shorts_cut_total`,
  `shorts_uploaded_total`, `shorts_cut_today`, `jobs_running`, `audited_today`, `activity`) from `_by_channel`, the
  same figures split per channel, computed once per cached payload and only when a manager reads (`shorts_jobs`
  and `shorts_clips` read whole; activity from the newest 200 audits, `_ACTIVITY_WINDOW`). The cache stays unfiltered;
  `dashboard_summary()` and `invalidate_dashboard_cache` are unchanged; the `quota` block is the fleet's, whole for
  everyone. Channel rows gained `applied_latest`. `GET /quota` (`app/quota.py`, admin only), `GET /channels/{id}/performance`, `/performance/summary`, `/performance.csv` (`app/performance.py`).
- **Shorts** (`app/shorts/routes.py`, prefix `/shorts`): `POST /shorts/jobs` (the body's `channel_id` checked,
  404 `channel_not_found`), `GET /shorts/jobs?channel_id=` (a named channel checked, else the user's visible channels;
  channel-less NAS cut jobs show to admin and exec only), `POST /shorts/cut` (a manager may cut only a folder that is
  the `nas_folder` of one of their channels, else 404 `channel_not_found`; the jobs stay channel-less as before),
  `GET /shorts/languages` (every NAS folder, any signed-in user: the NAS layout is shared), `POST
  /shorts/jobs/clear-failed` (a named channel checked, else only the user's visible channels' failed jobs),
  `GET /shorts/jobs/{id}`, `GET /shorts/clips/{id}/file`, `POST /shorts/clips/{id}/upload`, `POST /videos/{id}/short`;
  `POST /autoshorts/jobs` (`app/shorts/autoshorts.py`; files the job under one of the user's visible channels, 503
  when there is none).

**Modules** (`app/`):

| File | Owns |
|---|---|
| `main.py` | FastAPI app, logging, job registration, per-channel fan-out, `video_sync` wrapper |
| `job_status.py` | `JobRunFailed`, `item_error_verdict`, the `/health/jobs` registry, persisted to `LOG_DIR/job_status.json` (`persist_to`) |
| `catch_up.py` | startup catch-up of missed daily jobs (`run`, `CATCH_UP`, `LOOKBACK`; §4) |
| `channel_health.py` | per-channel freshness (`check`, `run_daily`), `GET /health/channels`, the `channel_health` job (§4) |
| `config.py` | `Settings` (env) |
| `db.py` | thread-local PostgREST (`supabase-py`) client with retry; the app reaches Postgres only via PostgREST on `SUPABASE_URL` |
| `rows.py` | the 1000-row cap: `all_rows`, `all_rows_parallel`, `rows_for_ids` |
| `channel_audits.py` | `audits_for_channel`; `fetch_all` deprecated alias of `rows.all_rows` |
| `eligibility.py` | which channels each job runs for (`Job.*`, `can_audit`, `can_cut_shorts`, `has_work`); `can_run_agent` = `can_audit` and `agent_enabled` and `reach.certify` |
| `status_vocab.py` | persisted status strings and their mirrors (`tests/test_status_vocab.py`) |
| `auth.py` | OAuth + channel flag PATCH |
| `access.py` | visibility rules (team tracker #145): `current_user`, `sees_all`, `filter_channels`, `visible_channel_ids`, `can_see_channel`, `require_channel` (404 `CHANNEL_NOT_FOUND`), the object resolvers (#146: `require_video`, `require_audit`, `require_intervention`, `require_short_link`, `require_shorts_job`, `require_shorts_clip`, each 404 with its own `*_NOT_FOUND`), `check_channel` and `scope_to_visible` for list and global routes (#147), `require_team_member` (#148, 404 `TEAM_MEMBER_NOT_FOUND`), `require_role` (403 `FORBIDDEN`), `require_admin`, the `access_rule` marker the route guard reads, and `PATCH /channels/{id}/manager` (Routes) |
| `session.py` | logins (team tracker #144): the global gate (`gate`, `PUBLIC_PATHS`, `PAGES`; Routes), the `/login` page and `/session/login|logout|me`, sessions (`start_session`, `user_for_token`, `end_session`; only `hash_token`'s sha256 stored), argon2id passwords (`hash_password`, `authenticate`, rehashed on login when argon2's parameters move), and the user admin `scripts/manage_users.py` calls: `create_user`, `set_password` (also ends the user's sessions), `deactivate_user` (sets `is_active` false, ends sessions), refusing with `UserError` |
| `team.py` | the Team page, the roster (team tracker #148) and channel assignments (#149): `GET /team`, `GET /uploads`, `GET/POST /team/members`, `PATCH /team/members/{id}` (deactivating ends open assignments, `_end_assignments`), `POST /channels/{id}/assign` and `PUT /team/members/{id}/channels` (both through `_assign`, the `assign_channel` RPC), `GET /team/assignments`, the channel targets (`PUT /channels/{id}/targets`, `targets_for`, `TARGET_MAX` 500) and the Board's moves (`POST /channels/{id}/move`, the `move_channel` RPC; `PATCH /team/members/{id}` `manager_id`) (Routes); `IST` (`Asia/Kolkata`, deliberately not `quota.QUOTA_TZ`), `ist_day`; `NAME_MAX` (100), `MANAGER_REQUIRED`, `NOT_A_MANAGER`, `NOTHING_TO_CHANGE`, `MEMBER_INACTIVE`, `ASSIGN_CONFLICT` |
| `channel_seo.py` | `GET /channels/{id}/seo` (Routes), the channel page's read: lever states, today's writes, latest verdicts, trimmed interventions |
| `team_board.py` | the Board's read, `GET /team/board` (Routes) |
| `seo_results.py` | the Results page (#167): `GET /results`, `GET /seo/results` (Routes): per visible channel and lever a cell (`_channel_cell`; titles `_title_cell`, `_path_cell`, `_title_counts`, `_first_verdict`), the pooled fleet row (`_fleet_cell`, `_title_fleet`, `_pooled_weeks`), `next_judgement`, `first_title_verdicts`; `LEVERS` (backlinks, title), `SCOPES`, `TRAFFIC_LAG_DAYS`. Reuses `channel_seo.lever_states`, `lever_verdicts._without_shorts`, `_judged_week`, `verdicts`, `title_verdicts`, `title_paths`, `title_measurement.as_of`, `_pending`. Read-only |
| `team_uploads.py` | the uploads grid (team tracker #151) and its drill-down (#152): `GET /team/uploads`, `GET /team/uploads/videos` (Routes), one crediting rule for both (`_scope`, `_credited`), which also places each channel's target (`_holder`, `_weekday_target`, member rows' `channels`); `SCHEDULED` (the drill-down's status pill); `IST` (`Asia/Kolkata`, its own, not `quota.QUOTA_TZ`), `ist_day`, `ist_midnight`, `window` (defaults and the 422s), `DEFAULT_DAYS` (7), `MAX_DAYS` (92), `UNASSIGNED` |
| `sync.py` | video sync, `is_short` probe, stats refresh, routine-sync rules (`routine_sync`: a full pass when `needs_full_sync` or `uploads_need_backfill`, true while every `channel_uploads` row of the channel was first seen after `last_full_synced_at`, i.e. its upload history predates capture; a failed read answers false); token failures → `TokenExpired` (401 `token_expired`); full syncs feed the human-edit ledger. Upload capture (team tracker #150): the playlist walk carries each item's `snippet.publishedAt`; every fetched video goes to `channel_uploads` (§2) before the opted-out-Shorts and private skips (`_upload_row`, `_record_uploads`; `_stored_uploads` reads the stored rows first). A stored `channel_uploads` `is_short` is reused unless the row is still `private` or NULL (`_settled_is_short`), else re-probed inside `MAX_SHORTS_PROBES_PER_SYNC`. A `channel_uploads` read or write failure is logged and never fails the sync. `recheck_uploads` (the `upload_recheck` job, §4) re-reads unsettled uploads; `_went_public` stamps `public_at` |
| `content_type.py` | `is_episode` classifier |
| `audits.py` | `DEFAULT_PROMPT`, `_build_user_block`, strategy stamp, `audit_video`, apply, revert, bulk ops; called only from routes; `_refuse_on_agent_channel(channel, force=)` guard (Routes) |
| `audit_suggestion.py` | LLM output contract: decode, 15-hashtag cap, `rejection()`, `house_format_spec()` |
| `apply_outcome.py` | typed `ApplyError`/`ApplyOutcome`, incl. `QUOTA_INSUFFICIENT` (`quota_insufficient`) and `APPLY_DISABLED` (`apply_disabled`), both 409, refused before anything is sent |
| `backlinks_apply.py` | `apply_backlinks(intervention)` for a `planned` treated `midas` `backlinks` row with `payload.targets`. Gates in order: `apply_disabled` (`BACKLINK_APPLY_ENABLED`), `DRY_RUN` (renders onto the stored description, no call, no write), `quota_insufficient` (51u). Fetches the live snippet (1u), records a live/stored description difference via `human_edits.record_description_edits`, renders the block (`backlinks.render`), sends `part=snippet` with only `description` replaced (50u). Success → `measuring`, `applied_at`, `before_state.description`, `videos.description`; failures typed (`token_expired`, `youtube_quota_exceeded`, `failed`) and change no row (the caller cancels). Also the revert route. `_live_snippet`, `_send_snippet`, `_classified` shared with `titles_apply.py` and `playlist_test` |
| `titles_apply.py` | the title-only twin of `backlinks_apply.py`. `apply_title(intervention)` (`planned` treated `midas` `title` row with `payload.title`, `payload.title_before`): same gates (`TITLE_APPLY_ENABLED`, `DRY_RUN`, 51u), live title ≠ `title_before` → `ApplyError(FAILED, "title_changed")`, else sends only `title`; success → `measuring`, `before_state.title`, `videos.title`. `revert_title(intervention, *, auto)`: same gates, puts `before_state.title` back only if live is still `payload.title` (else 409 `title_changed`); → `cancelled`, `payload.revert {…, auto}`. Callers: agent tick (`apply_title`), revert route (`auto=False`), `lever_verdicts.auto_revert` (`auto=True`) |
| `titles.py` | the title lever's writer, checks, routing and stamps; reads only, except `strategy_version`'s `audit_strategies` row. `channel_context` → `ChannelContext` (warm long videos' reach, `median_ctr`, `ceiling` = top 1% plus any over `TITLE_MAX_IMPRESSIONS`, `top_performers` by browse + suggested views per impression). `context(video)` (title, description start, cached transcript, CTR vs median, traffic mix, top 10 search terms, top performers). `system_prompt()` (`TITLE_PROMPT`, §6), `write_candidates` (`chat_json`, `WRITER_MODEL`, `label="titles.write"`, first `TITLE_CANDIDATES`). `check(title, video)` → first failure: `length` (`TITLE_MAX` = 100), `characters` (`<`, `>`, line break), `unchanged`, `script` (`SCRIPTS[language]`; every `HEADINGS` language but `en`), `hashtags`, `url`, `emoji` (`_EMOJI_RE`); same check on both paths. `pipeline(video)` → `Written`: first passing candidate, one retry with the failures, else `title` None. `title_path(video_id)`: sha256 hash vs `TITLE_AGENT_PCT`. `strategy_inputs`/`strategy_version(path)` (§6). `path_stopped` (`lever_verdicts.stopped(…, 'title', TITLE_SCOPES[path])`), `path_closed` (stopped or no share, §7.3 item 33), `stopped` (both closed), `route` (hands to the other path if its own is closed). `would_title`, `title_answers(…, pick=)` and `preview(…, path=)` for the scripts: no decide(), no interventions, no YouTube |
| `youtube_metadata.py` | `videos.update` payload; `_NON_ISO_639_1 = {"bgc": "hi", "bho": "hi", "raj": "hi"}` (`:58-64`; `bho`/`raj` unused) |
| `youtube_client.py` | Data API wrappers + quota charging; `yt_playlist_items_page` requests `part="snippet,contentDetails"` (1u, #150; also read by the membership walk); `yt_playlist_items_insert(position=)`; `channel_credentials` (expiry from `channels.token_expiry`, NULL = expired, refreshed and saved), shared with `analytics_client` |
| `quota.py` | unit-cost table, daily ledger, `JobBudget`, `/quota` |
| `analytics_client.py` | on-demand Analytics; `analytics_creds_for_channel` = `analytics_authorized` gate + `channel_credentials` (also used by the Reporting API) |
| `reporting_client.py` / `reporting_poll.py` | Reporting API jobs (`ensure_job` per report type), CSV parsing (reach; video and playlist traffic aggregated, `TRAFFIC_SOURCE_TYPES`), reach → `video_reach_daily`, `video_metrics` backfill; latest-wins day replace (`replace_data_day`, `record_ingested`); `download_report_csv` retries a dropped connection (`DOWNLOAD_ATTEMPTS` = 3) and refreshes the token once on 401 |
| `human_edits.py` | human-edit ledger. Descriptions: `video_links`, `made_by_midas` (matches an audit's applied/reverted text, or links exactly an applied treated `midas` backlinks row's targets, `_midas_block`), `record_description_edits` (writes `human` backlinks rows with `ledger_key`); called from `sync_channel` on full syncs. Playlists: `added_by_midas` (a non-`sync` `added` assignment or an `approved` `add` proposal), `record_playlist_additions`; called from the membership walk. Both via `_record_human`; details §7.3 items 10–11 |
| `traffic_poll.py` | daily traffic-source ingestion → `video_traffic_source_daily`, `playlist_traffic_daily`; retention rule (`keeps_detail`, `collapse_unread_detail`, §2) |
| `interventions.py` | `assign_arm` (sha256 of `video_id` vs `HOLDOUT_PCT`), `active_for`, `record` (refuses a second open `midas` row with `ActiveInterventionExists`, or a `human` arm other than `n/a`; the partial unique index backs it; with `ledger_key` upserts `ignore_duplicates`, None if stored; `trajectory=` sent only when given). Callers: `human_edits`, `agent_tick`, `short_links` |
| `reach.py` | data-day windows, coverage, frontier, staleness, `certify` (`certify_covered`, `window_length`); `coverage(…, report_type=)` defaults to reach |
| `decide.py` | `decide(question_set, subject, context, intervention_id=None) -> Decision`: answers by rules (prob 1.0), asks `DECIDE_BACKEND` in shadow (`llm` via `chat_json`, validated; `jev` raises `NotConfigured`), writes one `decision_log` row (`used = 'rules'`), returns the rules answer; backend or log failures logged, never change the answer. Sets `TRIAGE` (rules: `backlinks`, then `title`, else `no_change`, §6) and `NEXT_WATCH` (`yes` iff `similarity` ≥ `join_low`). `Decision.log_id`; `link(log_id, intervention_id)`. Callers: `agent_tick.run`, `short_links._next_watch` |
| `reembed.py` | one-off B6 re-embed: `recipe_text`, `MODEL_VERSION`, `estimate_channel` (no API), `reembed_channel` (batches of 50, per-video retry), `member_similarities`, `calibrate_channel` → `channels.playlist_thresholds` (method §7.3 item 5). Run only by `scripts/reembed.py` |
| `backlinks.py` | the canonical backlink block. Pure: `render(description, targets, language)` (`HEADINGS[language]` + `<title> https://youtu.be/<id>` lines after the first line; replaces an existing block; `RenderRefused` for no heading, no/too many (`BACKLINK_MAX`)/bad targets, or over `DESCRIPTION_MAX`; drops `#`), `find`, `strip`. `HEADINGS` ("watch more songs", must stay fixed, all distinct): `"mr": "आणखी गाणी पहा:"` (SEO team), `"hi": "और गाने देखें:"`, `"bgc": "और गाणे देखो:"`, `"pa": "ਹੋਰ ਗੀਤ ਵੇਖੋ:"`, `"gu": "વધુ ગીતો જુઓ:"`, `"en": "Watch more songs:"`, `"ta": "மேலும் பாடல்களைப் பாருங்கள்:"`, `"ml": "കൂടുതൽ പാട്ടുകൾ കാണൂ:"`, `"kn": "ಇನ್ನಷ್ಟು ಹಾಡುಗಳನ್ನು ನೋಡಿ:"`, `"te": "మరిన్ని పాటలు చూడండి:"` (non-`mr` written by Claude for native review). DB: `siblings` (≥ `SIBLING_MIN_VIEWS` type-7 inbound over 28 traffic data-days, within `TRAFFIC_INGEST_CHANNELS`), `target_pool`, `candidates(video, pool=)` → `Candidates(rows, skipped_unembedded, reason, join_low)`: warm, public, non-Short targets on the source's channel (siblings only with `BACKLINK_SIBLINGS_ENABLED`), not already linked, cosine ≥ `join_low`, minus same-`title_key` and ≥ `BACKLINK_DUPLICATE_SIM` duplicates, ≤ `2 × BACKLINK_MAX` rows; reasons `no_thresholds`, `thresholds_other_model_version`, `source_not_embedded`. Called by `agent_tick` |
| `warm.py` | warm filter: `ranked_pool` (RPC when `WARM_POOL_USE_RPC`, else or on error in-app), `explore_order` (`WARM_EXPLORE_PCT`), `warm_pool` (minus Shorts, `_without_shorts`), `_holds` (mirrors `warm_pool()`'s exclusions, §2), `warm_impressions` (≥ `WARM_MIN_IMPRESSIONS`, `{}` if uncertified). Used by `agent_tick` and `backlinks.candidates` |
| `metrics_poll.py` | daily Analytics poll |
| `measurement.py` / `verdicts.py` | title verdicts, `measurement_result` shape, rollups |
| `performance.py` | per-channel performance table/CSV |
| `dashboard.py` | `/dashboard` (narrowed per manager on read: `_scoped`, `_summaries`, `_by_channel`, #147); `_aggregate_legacy` fallback/oracle for the RPC |
| `reflection.py` | weekly prompt rewrite (shadow/live/auto) + auto-revert; `derive_niche_queries`, `_sample_competitors` (frozen) |
| `transcripts.py` | transcript fetch + `video_transcripts` cache; `lang_display_name` (`_LANG_NAMES`, `:25-36`, incl. `bgc`, `bho`, `raj`); Data API captions fallback |
| `embeddings.py` / `openrouter.py` | embeddings and `chat_json`/`chat_text` via OpenRouter; `chat_tools(messages, tools, *, model=None, label=None)` (`tool_choice: "auto"`, returns the assistant message unparsed, retried once on timeout or 5xx), called only by `app/agent/loop.py` |
| `agent/loop.py` | the title agent's hand-rolled loop. `run_title_agent(video, *, channel=None)` → `AgentResult(kind, title, reason, trajectory)`: system `titles.agent_system_prompt()`, first message video id + language; per turn `chat_tools(…, model=AUDIT_MODEL, label="agent.title")`, tool errors returned as `{"error": …}`, no-tool replies get `NUDGE`. Ends: `submit_title` passing `titles.check` → `title` (one failure returned, second → `failed`, `checks_failed`); `decline`; `AGENT_MAX_TURNS` → `failed`, `turn_cap`. A `chat_tools` exception re-raised carrying the trajectory. Trajectory shape §2. `tools_called`. Writes nothing; called by `agent_tick._run_title`, `titles.preview` |
| `agent/tools.py` | the agent's tools, scoped to the run's video (`Subject`), read-only, no YouTube: `get_video`, `get_transcript`, `get_traffic_mix`, `get_search_terms` (`SEARCH_TERMS` = 25), `get_channel_top_performers(order="best"\|"worst")` (`TOP_PERFORMERS` = 10), `get_title_history` (`HISTORY` = 10), `write_candidates` (`WRITER_MODEL`, unchecked); terminal `submit_title`, `decline` (schemas only). `SCHEMAS` (§6), `TOOLS`, `call` |
| `playlists.py` | similarity engine: `join_pass` (no caller), `reconcile_channel`, `tune_thresholds`, `_llm_judge` |
| `playlists_sync.py` | playlist inventory sync, budgeted membership walk, role heuristic; feeds new memberships to the human-edit ledger |
| `playlist_discovery.py` | weekly orphan clustering → creates playlists (frozen) |
| `playlist_health.py` | playlist health scorer (recommend-only) |
| `playlists_router.py` | playlist HTTP endpoints |
| `autopilot.py` | the tick loop (§4); agent-path gates (`_agent_tick`: `apply_disabled`/`no_heading` only when neither `backlinks_enabled` nor `titles_open` holds); the agent path is its only write path, other channels get `shorts_only`. `_next_video_for_channel` kept with no caller (§7.2) |
| `agent_tick.py` | the agent tick's video work. `run(channel)`: first of `warm.warm_pool` → `_assess` (candidates from the channel's cached pool, `_pool`, `POOL_TTL_SECONDS`; triage context keys §6) → `decide(TRIAGE)` → `title` → `_run_title`; else a `midas` `backlinks` row: `no_change` or unrenderable (`_unrenderable`) → `declined` arm `n/a`; holdout → `holdout` with `payload.targets`; treated → `planned` → `apply_backlinks` → `measuring`, or `cancelled` with `payload.error` (re-raised; `dry_run` under DRY_RUN). Backlinks picks also ask `NEXT_WATCH` per candidate pair in shadow (`_next_watch`, `triage_json.next_watch`). Rows shapes §2. `backlinks_stopped` (sticky `lever_verdicts.stopped`). `backlinks_enabled(language)`, `titles_open`, `_title_enabled` (`TITLE_DAILY_CAP`, `TITLE_AGENT_DAILY_RUNS` over `_titles_today`), `title_channel` (cached with the pool). `_run_title`: holdout → `holdout`; treated → `titles.route` → pipeline or `run_title_agent` (`_agent_outcome`: decline → treated `declined`; failure → `cancelled` `turn_cap`/`checks_failed`; agent rows carry `trajectory`) → `planned` with `strategy_version` → `apply_title`; no passing candidate → `cancelled` `checks_failed`; writer raising → `cancelled` `writer_exception`, re-raised. `preview(channel_id, n)`: read-only, backlinks taken as open. §7.3 items 17, 30 |
| `lever_measurement.py` | pair measurement for `backlinks` and `human` `short_link` rows. `measure_channel(channel_id)` → counts: d0 = Pacific date of `applied_at`/`created_at`/`detected_at`; pre d0−7…d0−1, post d0+1…d0+7 (extended once to 14); waits for every involved channel's traffic frontier; `pair_views` at `SOURCE_TYPES[lever]` (`backlinks` 7, `short_link` 32), floor `LEVER_MIN_SOURCE_VIEWS` on the source's views → `judged`/`insufficient_data`; `delta` in views per week; recomputes within `RESTATEMENT_HORIZON_DAYS` (28). `data_day_start`. Result shape §2, decisions §7.3 item 19. Called by `lever_verdicts.run_weekly` |
| `title_measurement.py` | per-video title measurement. `measure_channel` over `midas` `title` rows (treated `measuring`, `holdout`, treated `declined`, recent decided ones): pre `PRE_DAYS` (14), post `TITLE_WINDOW_DAYS`; views of `SOURCE_TYPES` (3, 5, 7); `delta` = ln((post + 1) / (pre + 1)); impressions/CTR recorded only; `pre` < `TITLE_MIN_PRE_VIEWS` → `insufficient_data`, else `judged`. `ROWS` = `title interventions`. Called by `lever_verdicts.run_weekly`; §7.3 item 32 |
| `lever_verdicts.py` | the weekly verdict (arithmetic §2 `lever_verdicts`). `verdicts`, `directional`, `write_verdicts(channel_id, *, lever='backlinks')` (backfills missing earlier weeks, upserts the current one, never clears a triggered stop), `stopped(channel_id, lever, scope)`, `title_verdicts`, `title_paths` (the title-test figures over rows, pure), `TITLE_SCOPES`, `auto_revert` (judged treated titles ≤ −`TITLE_REVERT_LIFT` against the holdout, worst first, ≤ `TITLE_REVERTS_PER_DAY`, via `revert_title(auto=True)`; `title_changed` skipped, `apply_disabled`/`quota_insufficient` stop the run), `run_weekly` (the `lever_measurement` job, §4), `ON_CONFLICT`, `title_test_summary`, the interventions, lever-verdicts and title-test endpoints. `insufficient_data` rows and backlinks rows on Shorts (`_without_shorts`) enter no mean |
| `playlist_test.py` | the P3 playlist test. Draw: `survey`/`eligible` (non-`series`, ≥ `MIN_EMBEDDED_MEMBERS` (3) embedded members), `assign_arm` (hash vs `PLAYLIST_HOLDOUT_PCT`), `candidates` (warm, public, non-Short, non-episode non-members with cosine to the centroid ≥ `join_high`, by impressions, ≤ `PLAYLIST_TEST_MAX_ADDS`), `draw` (once; `AlreadyDrawn`; refused thresholds write nothing; arms + `experiment` proposals), `preview`; run only by `scripts/playlist_test.py`. Apply: `run_apply`/`apply_channel` (the `playlist_test_apply` job, §4; the test's only YouTube write), `test_dates`. Measure: `measure_channel` (weekly `playlist_starts` vs a 28-day pre, up to `PLAYLIST_EXPERIMENT_WINDOWS`, `ARMS` = `playlist arms`; writes week rows and arm columns, §2), `channel_playlist_test` endpoint. Decisions §7.3 items 21–23 |
| `short_links.py` | Short → video link recommendations, recommend-only (nothing reaches YouTube). `shorts` (feed views ≥ `SHORT_LINK_MIN_FEED_VIEWS`), `targets` (same-channel warm long videos, cosine ≥ `join_low`, ≤ `SHORT_LINK_TARGETS`; refusals as `backlinks.candidates`), `refresh` (≤ `SHORT_LINK_MAX_PER_RUN` Shorts with targets, shadow `NEXT_WATCH` per pair, one insert of `pending` rows per Short), `preview`, `run_weekly` (the `short_link_refresh` job). `router` (Routes): `channel_short_links`, `set_short_link`, `dismiss_short_link`. `seen_pairs`/`detect` (type-32 pairs → `seen_at` and `human` `short_link` interventions, `PAIRS` = `short-link pairs`, `INFERRED_TIMING` = `inferred_from_traffic`), called by `lever_verdicts.run_weekly`. Decisions §7.3 items 24–26 |
| `tracing.py` | OpenTelemetry → Phoenix spans (off by default) |
| `backup.py` / `provision.py` / `services/nas_service.py` | NAS snapshot, restore-on-empty, SMB client |
| `keyframes.py` | dead: not imported anywhere in `app/` or `scripts/` |
| `shorts/*` | Shorts cutter (NAS source), dispatcher, worker, upload. `shorts/cutter/download.py` gated off (`SHORTS_YT_DOWNLOAD_ENABLED=false`). Cut modes (`cutter/pipeline.py` `CUT_MODES`): `highlights` (4-8 picked moments, 20-45 s), `coverage` (the whole video, ≤58 s pieces), `episode` (`cutplan.episode_stanzas`: front to back in `EPISODE_MIN_SECONDS`-`EPISODE_MAX_SECONDS` = 45-50 s clips, each cut in a vocal pause, a scene change inside one preferred, else a short pause, the quietest instant, a scene change, or 47.5 s; a remainder under `EPISODE_MIN_TAIL_SECONDS` (20) dropped). `nas_source.enqueue_language_jobs` forces `episode` for a folder whose name has a word in `EPISODE_FOLDER_WORDS` (`series`), whatever the channel's `shorts_cut_mode` (`PATCH /auth/channels/{id}` accepts `highlights|coverage|episode`). A NAS job deletes its whole `SHORTS_CACHE_DIR/<job id>` when it ends and stores its clips with `local_path` NULL (`runner._run_nas_shorts_job`); `cache_cleanup.py` sweeps the rest (§4) |
| `static/*` | vanilla-JS dashboard. `midas.png` is the logo: the rail's brand (`sidebar.js` `ICONS.brand`), the login heading, and every page's tab and touch icon. `login.html` (the sign-in form, inline script, loads only `theme.css` and `midas.png`; follows `?next=` only to a same-site path; clears the `midas:swr:` localStorage cache on sign-in). `swr.js` wraps `window.fetch`: a 401 from Midas (not `/session/login`) sends the page to `/login?next=<page>`; every page loads it, `autoshorts.html` included. `sidebar.js` heads the rail with `TOP_ITEMS` (Running `/`, Uploads `/uploads`, Roster `/team`, Results `/results`) on every page, shows the signed-in user's name and role (`GET /session/me`) above the channel switcher (whose "Add channel" link, `/auth/login`, only the admin sees: `.not-admin .admin-only`, `theme.css`), with a logout button (`POST /session/logout`, clears the SWR cache, goes to `/login`). `team.html` (#148, served at `/team` as Roster and at `/uploads` as Uploads, one panel per path, no tabs): Uploads (#151): one bar of chips, the range ("Last 7 days" (default), "Last 30 days", "Next 7 days" (today onwards: what is scheduled), "Custom", which shows `From`/`To` date inputs that load on change; over 92 days refused before asking), for admin and exec a manager `data-dropdown` ("All managers" or one, sent as `manager_id`), and a count filter "All" / "Shorts" / "Long-form" (remembered in `localStorage` `midas:team:upKind`). A summary line over the grid, computed in the page from the response: the window's count, Shorts and long-form (filter "All" only), the daily average and busiest day over whole days before today, channels that posted ("n/m", the idle ones in its tooltip), and freshness from `channels[].last_synced_at`. Channel names show minus the words every visible channel shares and the generic words (`GENERIC`: Baalgeet, Balgeet, Rhymes, Nursery), full name in the tooltip (`buildLabels`, `chLabel`). The grid from `GET /team/uploads` is one table of sections (2026-11-20; no By member / By channel switch): per member a head row (name, "n channels", the manager's name when unfiltered for admin and exec, deactivated tagged) with their day counts and summed targets, then a row per channel they held (`rows[].channels`; a day someone else held it is lined, an amber dot when not synced for 6 h); Unassigned last, only when one of its channels counts something or has a target; a section folds shut from its caret (remembered in `localStorage` `midas:team:upCollapsed`). Columns per IST day headed "<Mon> <d> <Dow>" (today underlined, future days hatched as scheduled) plus Total, and an "All" footer of day totals; each day cell is one number for the filter, tinted by its share of the busiest cell of its kind (member rows, channel rows); zeros are a dot. A finished day (before today IST) is red when the count in view falls short of that row's target (`shortfall`), its strength the shortfall's share, a zero under target a red 0. Hovering a count shows a card (`#hovercard`): the row and day or range, the total, a Shorts / long-form bar and counts, "Target: got/want" per type. A non-zero cell opens the drill-down (#152): a `.modal` from `GET /team/uploads/videos` (a member's head row by `member_id`; a channel row with `channel_id` and `by_member=true`), headed by the count, its split and, on a finished day with a target, "got/target" per type; then a card grid per channel, each card a thumbnail with a Short / Long-form / "?" badge (and "Scheduled") and the title, linking to YouTube; for a member, their channels with no uploads that day named in "Nothing from …" (from `GET /team/assignments`). Roster: the Board (2026-11-20, `GET /team/board`; docs/superpowers/specs/2026-11-20-channel-targets-board-design.md): nested cards on a dot-grid canvas that pans by dragging its background and zooms (35–180%) by pinch or Ctrl/⌘ + scroll over it, around the cursor, or by the bar's − / % / + buttons (kept in `localStorage` `midas:board:zoom`); a card per manager (one hue each), dragged by its header, positions kept per user in `localStorage` `midas:board:pos:<user id>` ("Tidy up" clears them and re-flows the cards); member cards inside, holding channel chips; each manager card ends in a "Loose channels" tray; a channel with no manager (admin and exec see them) has no card: it floats on the canvas as a grey drifting chip, right of the cards when the view has room, else below them, takes no drop, and leaves by being dragged onto a member or a tray (or by its card's "Move to…"; "No manager" there is the admin's only way back). Each channel shows today's uploads against today's target as a bar and "got/want" (a tick when met; "no target today" when it has targets but none for today's weekday; a dashed "+ target" for editors when it has none, else "no target"); the bar's legend counts the channels with a target, the gold members and the alarmed loose channels, or, with no target anywhere, says to click a channel to set one; a loose channel with an unmet target today pulses red; a member who meets every target today turns gold with a star, with confetti the first time that day in the browser (`midas:board:gold:<day>`). Dragging (SortableJS 1.15.6, vendored at `static/vendor/Sortable.min.js`; drop zones glow, the dragged block lifts and tilts, a dropped block bounces) a channel onto a member or into a tray is `POST /channels/{id}/move`; the admin also drags members between managers (`PATCH /team/members/{id}` `manager_id`, confirmed first when they hold channels); each move shows a toast with Undo. A manager drags within their own block; exec gets the board read-only. Clicking a channel opens its card: today vs target, the weekly targets (seven weekdays × Shorts and long-form, "Copy Monday to every day", `PUT /channels/{id}/targets`) and a "Move to…" select (the keyboard path); clicking a member opens rename, deactivate (confirmed) or reactivate and, for the admin, a manager select. "+ Add member" at the foot of a manager's members (`POST /team/members`); "Show deactivated" (`midas:board:showOff`). `results.html` (the Results page, #167, from `GET /seo/results` through `SWR.swr`): "Next weekly judgement <day>, 09:00 UTC", a channel `data-dropdown` ("All channels" or one, sent as `channel_id`) and lever chips (Backlinks, Titles, Playlist test, Short links; each toggles its column group, never none), a one-line legend of lift and the verdict colours, then the scoreboard: a row per channel (linking to `/channel?id=`), the fleet row on top ("All channels", pooled), and per lever a column group: Written, Judged / pending (`counts.judged` / `counts.awaiting`), Lift (backlinks: views/week; titles: the log ratio as a %; tinted green `helped`, grey `no_change`, red `worse`, blank with no verdict; hover card: the arms' means and n, cumulative lift, weeks judged, held back, declined, cancelled by reason, reverts, not enough data, Shorts left out, team edits), a sparkline of `weeks` lift (inline SVG, zero line), and Verdict (a "stopped wk <date>" tag when the stop rule fired, else the off reason in grey, else the verdict pill; the fleet: "n of m on" and the stopped count; a title cell with no weekly verdict yet says "first verdicts ~<date>", from `first_verdict`). The Playlist test group (Dosed, Judged / open, Lift, Weekly lift, Answer pill or "no test drawn"; the fleet row counts yes/no/pending) and the Short links group (Pending, Set, Seen, Team effect, and "the team isn't using the card yet" while nothing is set, dismissed or ticked) follow. A title cell's hover card adds a Pipeline and an Agent row (written, judged vs held back, lift, "stopped") and a "First verdicts ~<date>" foot. `channel.html` (the channel page, rebuilt 2026-11-20 around interventions; no audit, prompt, reflection, reconcile or playlist-health UI): Autopilot = state pill and line (`Running.stateOf`, its audit-based `bad` state ignored), Start/Stop/Resume and "Get latest from YouTube", tiles (changes today / cap, titles changed, videos given backlinks, waiting on results, last change), each lever on/off with its reason and latest verdict, and "Recent changes" (the newest 30 `midas` rows, holdouts and declines behind a checkbox), all from `GET /channels/{id}/seo`, re-read every 60 s while shown. Videos = `GET /channels/{id}/videos` joined in the page to the `/seo` rows: chips All / Changed by Midas / Title changed / Backlinks added / Held back / Team edits / Untouched, a row per video with its last change and result; a row expands to every intervention on the video (title before → after, linked targets, result, "Hold to undo" → `POST /interventions/{id}/revert` on a live title or backlinks row). Playlists = the playlist test's figures (`GET /channels/{id}/playlist-test`), its pending additions only (`arm_id` set) to approve or reject, and the "Short links" card (`#sl-card`, `loadShortLinks`, "Mark set" after a `confirmDialog`, "Dismiss", "Download CSV"). Settings = one Save (`PATCH /auth/channels/{id}`: autopilot on, changes per day, language, track Shorts, NAS folder, auto-cut), "Cut Shorts now", and the levers read-only |

**Scripts:** `scripts/clean_shorts_cache.py` (`--dry-run`, `--days` default `SHORTS_CACHE_KEEP_DAYS`; runs `cache_cleanup.clean_cache`, prints each removal and the space freed), `scripts/manage_users.py` (`create --email --name --role admin|exec|manager`, `reset-password --email`,
`deactivate --email`; the password is typed twice at a `getpass` prompt, never an argument; reset and deactivate end
the user's sessions; writes `app_users`/`app_sessions` through `app/session.py`; exits 1 on a refusal),
`scripts/preview_titles.py` (`--channel`, `--n` 20, `--path pipeline|agent` default `pipeline`, `--csv [PATH]` default `logs/preview_titles_<channel>.csv`; prints `titles.preview` per title answer: arm, path, CTR vs median, candidates with checks, chosen title or failures; with `--path agent` the agent's tools, turns, submits and end; read-only, calls the writer and, for `agent`, the reasoning model), `scripts/title_bakeoff.py` (`--channel`, `--n` 20, `--models a,b,c`, `--out` default `logs/title_bakeoff_<channel>.csv`, `--seed`; each model once per video, one shuffled row per (video, model) with blank `score_1_3`, `wrong_or_broken_script`, `follows_structure`, `notes`; models hidden as `W1…Wn`, key in `<out stem>.key.csv`; no DB or YouTube writes), `scripts/short_links.py` (`--channel --preview`; prints what `refresh` would recommend; exits 1 when thresholds are refused; writes nothing), `scripts/playlist_test.py` (`--channel` and `--preview` (writes nothing) or `--draw` (no confirmation; exits 1 when refused or already drawn)), `scripts/preview_backlinks.py` (`--channel`, `--n` 20; rules answer, arm, targets, description before/after or the refusal; read-only), `scripts/reembed.py` (`--channels`, `--estimate` with `--usd-per-mtok`, `--skip-calibrate`; re-embeds then calibrates), `scripts/create_reporting_job.py` (`--report-type`, default `channel_reach_basic_a1`), `scripts/probe_reporting.py`, `scripts/probe_analytics.py`, `scripts/verify_reach_coverage.py`, `scripts/apply_migrations.py`, backfills, and the Phase A live probes in `scripts/probes/` (`probe_traffic_source_report.py` defaults to `channel_traffic_source_a3`, `:61`).

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

- **Strategy stamp** (`app/audits.py:196-278`). `strategy_version(prompt_text, prompt_source, prompt_version_id=None)`
  returns `f"{settings.STRATEGY_LABEL}-{_strategy_hash(inputs)}"`, the hash being the first 12 hex of sha256 over
  `json.dumps(inputs, sort_keys=True, separators=(",", ":"))`. `inputs` = `label`, `prompt_source`
  (`override|shorts|generated|default`; anything else raises `ValueError`), `prompt_sha256` (of the system prompt
  actually sent), `audit_model` (`settings.AUDIT_MODEL`), `decision_question_set_version` (`decide.QUESTION_SET_VERSION`, read at call time; `"2026.11-s3-v1"` `app/decide.py:39`),
  `prompt_version_id`, and no `writer_model`: `WRITER_MODEL` exists but is the title writer's, stamped by `app/titles.py`, so the audit stamp's inputs didn't change.
  `_stamp_strategy` upserts `{version, prompt_template, model: settings.AUDIT_MODEL, config: inputs, status:
  "champion", notes: "auto-registered by _stamp_strategy (derived from config)"}` with `ignore_duplicates=True`,
  once per version per process. `prompt_template` is one of `"audit_video prompt_override (caller-supplied, e.g.
  reflection shadow candidate)"`, `"audit_configs.shorts_prompt (per-channel)"`, `"audit_configs.generated_prompt
  (per-channel)"`, `"code:app/audits.py DEFAULT_PROMPT"` (`app/audits.py:210-215`).

- **Other LLM calls** (all via OpenRouter, `app/openrouter.py`; `chat_json`/`chat_text` default to
  `settings.AUDIT_MODEL`, `app/openrouter.py:93,175`):

  | Call | Model | Path | Prompt |
  |---|---|---|---|
  | Audit | `settings.AUDIT_MODEL` | `audit_video` → `chat_json(user, system=audit_prompt)` (`app/audits.py`), from the manual audit routes only | above + DB `audit_configs` |
  | Prompt elaboration | `settings.PROMPT_GEN_MODEL` | `POST /audit-config/elaborate` | `app/audits.py:107-125` (renders `house_format_spec()`) |
  | Niche queries | hardcoded `anthropic/claude-haiku-4.5` | reflection (frozen) | `app/reflection.py:264-272`, below |
  | Platform guidance | hardcoded `perplexity/sonar` via `chat_text` | reflection (frozen) | `app/reflection.py:346-352`, below |
  | Reflection candidate prompt | `settings.REFLECTION_MODEL` | reflection (frozen) | `app/reflection.py:465-507` |
  | Playlist membership judge | `JUDGE_MODEL = "anthropic/claude-haiku-4.5"` | `reconcile_channel` (frozen) and dead `join_pass` | `app/playlists.py:206-213`, below |
  | Playlist title/description proposal | `JUDGE_MODEL` | `discover_playlists` (frozen) | `app/playlist_discovery.py:137-142`, below |
  | Title writer (S3.2) | `settings.WRITER_MODEL` (= `AUDIT_MODEL`), or each `--models` entry in the bake-off | `titles.write_candidates` → `chat_json(…, system=system_prompt(), label="titles.write")`, from `titles.pipeline` (up to 2 calls a video) via `scripts/preview_titles.py`, and once per (video, model) from `scripts/title_bakeoff.py`; and from the agent tick (`agent_tick._run_title`), per treated title on the pipeline path, with a live transcript fetch (`fetch_transcript`); also from the agent's `write_candidates` tool (`app/agent/tools.py`), once per call, no retry | `TITLE_PROMPT` below, and the user block (`app/titles.py` `_user_block`) |
  | Title agent (S3.4) | `settings.AUDIT_MODEL` (the reasoning model) | `app/agent/loop.py` `run_title_agent` → `openrouter.chat_tools(messages, tools.SCHEMAS, model=AUDIT_MODEL, label="agent.title")` once per turn, at most `AGENT_MAX_TURNS` (12) a run (each retried once on a timeout or a 5xx); from the agent tick per treated title on the agent path, and from `scripts/preview_titles.py --path agent` (transcripts from the cache only) | `AGENT_PROMPT` below, the first user message, and the tools' JSON results |
  | Decide shadow answer (B5) | `settings.AUDIT_MODEL` (the `chat_json` default) | `decide()` with `DECIDE_BACKEND=llm`, from the agent tick's triage (with S3.3's title keys) and, per candidate pair, its next-watch question (`app/agent_tick.py` `run`, `_next_watch`; the preview asks the triage rules only), and, per Short-link pair, `app/short_links.py` `_next_watch` (S2.4, from `refresh`; at most `SHORT_LINK_TARGETS` × `SHORT_LINK_MAX_PER_RUN` = 150 a week per channel; `scripts/short_links.py --preview` asks none) | `app/decide.py:140-158`, below |
  | Embeddings | `EMBED_MODEL = "google/gemini-embedding-2-preview"` | `bootstrap_embeddings` (the autopilot's `embed_video` after a house-format apply went with S3.6; the manual apply routes never re-embedded) | input: title + `"\n\n"` + transcript[:6000] (`app/embeddings.py:118-120`); bootstrap passes `use_transcript=False`, so title only (`app/embeddings.py:182`). Both under `model_version = EMBED_MODEL` |
  | Embeddings, B6 recipe | `EMBED_MODEL`, stored as `model_version = "google/gemini-embedding-2-preview\|tdt-v1"` | `scripts/reembed.py` → `app/reembed.py` `reembed_channel`, one-off, run for Marathi 2026-10-07/08 | input: `app/reembed.py` `recipe_text`, title + `"\n\n"` + description + `"\n\n"` + tags joined by `", "`, the same shape for every video (empty fields stay empty blocks) |

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
  ```
  # decide llm backend (app/decide.py:154-171), label "decide.<question set name>"
  # system:
  You answer one multiple-choice question about a YouTube video for a kids' nursery-rhyme channel network. Choose exactly one of the allowed answers and give your probability for each allowed answer.
  # user:
  QUESTION: {question_set.question}
  ALLOWED ANSWERS: {', '.join(question_set.answers)}
  SUBJECT: {subject}
  CONTEXT: {json.dumps(context, sort_keys=True, default=str)}

  Return only JSON: {"answer": "<one allowed answer>", "probs": {"<allowed answer>": <probability 0..1>, ...}}

  # TRIAGE.question (app/decide.py:95-107); answers no_change, backlinks, playlist, short_link, title
  Which lever, if any, should change this video this week to route more viewers to it? `backlinks`: add a related-videos block to its description. `playlist`: add it to a playlist. `short_link`: link a Short to it. `title`: rewrite its title. `no_change`: leave it alone.

  # NEXT_WATCH.question (app/decide.py:121-129, S1.5); answers yes, no
  Would a viewer who just watched video A (the source) plausibly watch video B (the target) next? `yes` or `no`.
  ```
  The CONTEXT the agent tick sends (S1.4b, `app/agent_tick.py` `_assess`): `has_related_block`, `backlink_candidates`,
  `backlinks_stopped`, `traffic_mix_28d`, `impressions`, `ctr`, `recent_interventions`, and
  `backlinks_enabled`, `title_enabled`, `title_excluded`, `channel_median_ctr`, `is_short`. `TRIAGE`'s rules
  (`app/decide.py` `_triage_rules`, S3.3), in order: `backlinks` when `backlinks_enabled`, not `backlinks_stopped`,
  not `has_related_block` and `backlink_candidates` ≥ `BACKLINK_MIN_CANDIDATES`; `title` when `title_enabled`, not
  `is_short`, not `title_excluded`, and `ctr` < `channel_median_ctr` (both present); else `no_change`. For `NEXT_WATCH`
  (S1.5, `app/agent_tick.py` `_next_watch`), SUBJECT is `<source id>-><target id>` and CONTEXT is
  `source_video_id`, `source_title`, `target_video_id`, `target_channel_id`, `target_title`, `similarity`, `join_low`.
  The Short-link refresh (S2.4, `app/short_links.py` `_next_watch`) asks `NEXT_WATCH` with the same keys and SUBJECT
  shape, the Short as the source. The question text is unchanged; S3.3's rules change moved `QUESTION_SET_VERSION`
  from `2026.10-s1-v2` to `2026.11-s3-v1` (`app/decide.py:39`).
  The system message still says "about a YouTube video" for both sets.
  The judge and proposal prompts carry no `default_language` rule.

- **Title writer prompt** (S3.2, `app/titles.py` `TITLE_PROMPT`, the system message; `system_prompt()` fills
  `{title_max}` with `TITLE_MAX` (100) and `{candidates}` with `TITLE_CANDIDATES` (3); `{{`/`}}` are literal braces). Verbatim:

  ```
  You write the title of one YouTube video on a kids' nursery-rhyme channel.
  Only the title changes: the thumbnail, description and tags stay as they are.

  Where the title is read: on the YouTube home page, in the list of videos next
  to another video, and in search results. A parent decides in a glance whether
  to tap.

  Structure, in this order:
    <rhyme names, in the channel's script> <the channel language's word for
    kids' rhymes, in its script> | <the same rhyme names, romanised> <the
    language and that word, romanised> TMKOC <that word, in its script>
  - Everything before the "|" is in the channel's language and script; after it,
    the same words spelled out in Latin letters, then TMKOC and the word again.
  - One rhyme: just that rhyme's name. Several rhymes (a compilation): join
    their names with " & " before the "|" and " + " after it.
  - Every title ends with TMKOC and that word, whatever the current title has.
  - A story, an episode or a show (the channel's cartoon series, not rhymes)
    keeps the structure, with its name in place of the rhyme names and the
    channel language's word for an episode or a story in place of the word for
    kids' rhymes, here and after TMKOC: it never says rhymes. Keep a season or
    episode number exactly as the current title writes it.
  - Example (Hindi, a compilation of two rhymes), as the SEO team wrote it:
    आम चोरी पत्ता जोड़ा & हरे नीम की डाल हिंदी बालगीत | Aam Chori + Hare Neem Ki Dal Hindi Baalgeet TMKOC बालगीत
  - That example is over {title_max} characters. When a title is, drop in this
    order until it fits: the last word for kids' rhymes, then the romanised
    language and word. Never drop a rhyme's name or TMKOC.
  - English (channel language en) has no second half, since it would only
    repeat the first. Its structure, in place of all of the above:
      <rhyme names> | TMKOC English Nursery Rhymes
    As many of the video's rhyme names as fit, in the video's order, joined
    with ", " and " & " before the last. A story, an episode or a show: its
    name, with its season or episode number as the current title writes it,
    then " | TMKOC English Episode" or " | TMKOC English Story": never rhymes.
    Example (a compilation): Wheels on the Bus, Old MacDonald & Giddy Up Horsey | TMKOC English Nursery Rhymes
    Over {title_max} characters: drop rhyme names from the end, keeping at
    least one, and never TMKOC.

  Rules:
  - Keep the rhyme's name, in the channel's language and in its script.
  - If the current title has a series or brand name, keep it as it is written.
  - Add no hashtags: no more "#" than the current title has.
  - Add no emojis: no more than the current title has.
  - No links.
  - At most {title_max} characters.
  - Each candidate must differ from the current title.

  You are told the current title, the start of the description, the transcript
  when there is one, the channel's language, the video's click-through rate
  beside the channel's median, where its views come from, the search terms that
  bring viewers to it, and the channel's titles that get the most browse and
  suggested views per impression.

  Write {candidates} candidates, best first, each with a one-line reason.
  Return only JSON: {{"candidates": [{{"title": "...", "reason": "..."}}, ...]}}
  ```

  The user block (`_user_block`), in order: `Channel language: <code> (<name>)`, `Current title: …`,
  `Description (first 1500 characters): …`, `Click-through rate, last 28 days: <ctr%> on <n> impressions; channel
  median <ctr%>`, `Views by source, last 28 days: <name> <views>, …`, `Search terms that bring viewers (views): <term>
  (<views>), …`, `The channel's titles with the most browse and suggested views per impression:` then `- <title>
  (<views per impression>)` lines, `Transcript: …` (`not available` / `none` when empty). The retry adds a blank line,
  `Your previous candidates failed these checks; write new ones that pass:` and `- '<title>': <failure>` per failure (`- '': malformed reply: no candidates` for an empty attempt).

  Composition: `TITLE_PROMPT` = `TITLE_BRIEF` + the rest; `TITLE_BRIEF` = `TITLE_GOAL` + `TITLE_STRUCTURE` (the SEO
  team's structure, owner) + `TITLE_LIMITS` + the candidate rule. Each prompt change moves the pipeline's
  `prompt_sha256` and `strategy_version`; each title row keeps the stamp it was written under.

- **Title agent prompt** (S3.4, `app/titles.py` `AGENT_PROMPT`, the system message of `app/agent/loop.py`
  `run_title_agent`; `agent_system_prompt()` fills `{title_max}` with `TITLE_MAX` (100)). `TITLE_GOAL`, then that
  the structure is the agent's to decide, then `TITLE_LIMITS`, then the agent's part; no `TITLE_STRUCTURE`, so
  pipeline vs agent compares the SEO team's structure with the agent's own (owner). Verbatim:

  ```
  You write the title of one YouTube video on a kids' nursery-rhyme channel.
  Only the title changes: the thumbnail, description and tags stay as they are.

  Where the title is read: on the YouTube home page, in the list of videos next
  to another video, and in search results. A parent decides in a glance whether
  to tap.

  How the title should read, its structure, its words and its length within
  the limits, is yours to decide from the evidence: what this video is, where
  its views come from, and which of the channel's titles do best and worst.

  Limits:
  - Keep the rhyme's name, in the channel's language and in its script.
  - If the current title has a series or brand name, keep it as it is written.
  - Add no hashtags: no more "#" than the current title has.
  - Add no emojis: no more than the current title has.
  - No links.
  - At most {title_max} characters.
  - It must differ from the current title; to keep the current title, decline.

  You decide this video's title with tools. Find out first what the video is
  and how it is doing: where its views come from, the search terms that bring
  viewers to it, the channel's titles that do best and worst on browse and
  suggested views per impression, and what was tried on this title before.
  write_candidates asks a writer model for candidates in the SEO team's
  structure; you are not bound by it, and may submit one, change one, or write
  your own.

  End with one call:
  - submit_title(title, reasoning): the new title. Code checks it; a title that
    fails gets the failure back once, and a second failure ends the run.
  - decline(reason): leave the title as it is. You may decline: a title that
    already works is a valid outcome.
  ```

  The first user message (`_first_message`): `Video: <video id>` and `Channel language: <code>` on two lines,
  nothing else. A reply with no tool call gets `Call a tool. End with submit_title or decline.` (`NUDGE`). A
  tool's result goes back as a `tool` message, its JSON text (`ensure_ascii=False`); an error as `{"error": …}`; a
  failing `submit_title` as `{"error": "check failed: <failure>. Submit once more, or decline; a second failing
  title ends the run."}`. The tools' schemas (`app/agent/tools.py` `SCHEMAS`, all nine sent every turn), name and
  description verbatim (`{…}` filled from the module's constants):
  `get_video` "The video's current title, the start of its description, the channel's language, and its
  impressions and click-through rate over the last 28 days beside the channel's median."; `get_transcript` "The
  video's transcript, when there is one."; `get_traffic_mix` "The video's views by traffic source over the last 28
  days."; `get_search_terms` "The top 25 YouTube search terms that brought viewers to the video over the last 28
  days, with their views."; `get_channel_top_performers` (`order`: `best`|`worst`) "The channel's 10 warm long
  videos with the most (best) or fewest (worst) browse + suggested views per impression over the last 28 days, with
  their titles."; `get_title_history` "What was done to this video's title before, newest first (at most 10): past
  rewrites and their outcomes."; `write_candidates` "Ask a writer model for 3 title candidates, best first, each
  with a reason. They are not checked." (the number is `TITLE_CANDIDATES` at import); `submit_title` (`title`,
  `reasoning`, both required) "End the run with the new title. Code checks it; a failing title gets the failure
  back once."; `decline` (`reason`, required) "End the run leaving the title as it is."

- **Models in use.** Code defaults: `AUDIT_MODEL=anthropic/claude-haiku-4.5`, `PROMPT_GEN_MODEL=google/gemini-2.0-flash-001`,
  `REFLECTION_MODEL=anthropic/claude-sonnet-4-6`. Dev `.env`: `google/gemini-3.7-flash`,
  `anthropic/claude-opus-5:online`, `anthropic/claude-sonnet-5`. Office `.env`: blank (not read).

---

## 7. Delta vs the specs

Spec = `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md`. "Part 2" is the design as amended by
§0.6 (P1–P7); "Part 3" is Phase B; Parts 4–6 are Slices 1–3.

### 7.1 Spec'd but not built

**Phase B (Part 3) leftovers**
- **B1 retention:** built at ingestion (`traffic_poll.keeps_detail`, §2); rows ingested before it are folded only
  by the one-off `scripts/collapse_traffic_detail.sql`, which isn't recorded as run (`video_traffic_source_daily`
  was 4,766 MB / ≈15.0M rows on 2026-10-13, `docs/PHASE_B_FINDINGS.md`).
- **B3 scope:** the membership walk runs only inside `playlist_reconcile`, i.e. for the allowlisted channels
  (`app/config.py:151-161`); B3a sees an old video's edit only on a full sync, every 3 days (`app/sync.py:520`).
- **B4:** the old audit picker (no caller) is still newest-first with no impressions filter
  (`supabase/migrations/20260904000100_next_audit_candidate_exclude_episodes.sql:37`) and excludes in-window
  audits rather than active interventions (`:35-36`).
- **B6:** the playlist engine and its RPCs still use `EMBED_MODEL` and the global thresholds (§7.3 items 4–5).
- **The A8 registry's persistence** is a JSON file under `LOG_DIR` (`app/job_status.py` `persist_to`), not a DB table.

**Slice 1 (Part 2 §1–§2, §3.4, §6.1)**
- Code checks for links (§2.4): not built. Partially present: `DESCRIPTION_MAX = 5000`, the 15-hashtag cap and
  `rejection()` (`app/audit_suggestion.py`).
- Fleet-sibling targets (P2) are built but switched off (`BACKLINK_SIBLINGS_ENABLED`, §7.3 item 35).
- The findings write-up of the first verdict and the stop-rule outcome (S1.8, #70): the owner's.

**Slice 2 (Part 2 §4; Part 5)**
- Jev fit check replacing `playlists._llm_judge`: not built, deferred by Part 5 E12.
- Per-channel auto-apply flip for playlist adds: not built (`PLAYLIST_HITL` is one global setting,
  `app/config.py:115`).

**Slice 3 (Part 2 §3; Part 6)**
- Agent tools Part 2 §3.2 lists that Part 6 leaves out: `get_related_top_performers`, `get_playlists`,
  `get_niche_reference`, `get_channel_playbook`, and `submit_change` (Slice 3's terminal tool is `submit_title`):
  none exist. The online per-family writer bake-off (§3.3) is not built (Part 6 F9: offline only).
- Title objective (P5): the pipeline writes the SEO team's search-shaped structure and the test counts search
  views too (§7.3 item 34); the old house format, still reachable from the manual audit routes (guarded on agent
  channels), optimises for search ("keyword-rich sentences", "high-value search phrases",
  `app/audit_suggestion.py:74-76`).
- Niche reference (§3.6): no `app/niche_reference.py`, no `niche_reference_refresh` job, no `channels.niche_reference_*`
  columns. `derive_niche_queries` and `_sample_competitors` still live in the frozen `app/reflection.py:239-339`.

**Slice 4 (Part 2 §5)**: no `channels.playbook_json`, no distiller, no weekly rebuild; `reflection.py` not retired.

**Slice 5 (Part 2 §6)**: no per-channel quota shares in `JobBudget`.

### 7.2 Built but not spec'd

| Item | Where | Note |
|---|---|---|
| Title measurement loop (21-day CTR verdicts, `awaiting_window` stamping on apply) | `app/measurement.py`, `app/verdicts.py`, migration `20260702183233` | Kept only indirectly ("Title … CTR vs a comparable window … Built", Part 2 §1.2). Its windows are not the spec's weekly cadence (7.3) |
| Prompt reflection loop (weekly `generated_prompt` rewrite, `prompt_versions` shadow/live/auto, shadow audits, auto-revert on cohort median) | `app/reflection.py`, `prompt_versions` | **Frozen** (`REFLECTION_ENABLED`). Spec scraps it as the memory (Part 2 §0.5 item 3) and retires it in Slice 4 (§5) |
| Similarity playlist engine: daily add/remove, `tune_thresholds`, `join_pass` | `app/playlists.py` | Add/remove and tuning **frozen**; `join_pass` has no caller (`app/autopilot.py`) |
| Weekly orphan-cluster playlist **creation** | `app/playlist_discovery.py` | **Frozen** (`PLAYLIST_DISCOVERY_ENABLED`). Spec: "New-playlist creation … stay human-confirmed" (Part 2 §4) |
| Competitor sampling via `search.list` (100u each) and Perplexity guidance | `app/reflection.py:301-352` | Frozen with reflection. Spec moves the competitor half to Slice 3's niche reference |
| `video_traffic_source_playlist` table + tier-2 poller | `20260618133036_…`, `app/metrics_poll.py:85,228` | Disabled (`TIER2_TRAFFIC_SOURCE_SUPPORTED = False`); never populated. Superseded by `playlist_traffic_daily` (B1b), which is populated; the old table and poller are still in the code |
| Playlist health scorer (tier-1 percentile bands) | `app/playlist_health.py` (its plan, `docs/PHASE_1B_PLAN.md`, is in git history) | Kept by Part 2 §0.5 ("inventory, health …") but no stage uses it |
| `video_sync` daily job | `app/main.py:243-267,365-376` | Added 2026-10-01 after the A0 pause stopped sync (`docs/PHASE_A_FINDINGS.md` "Phase A conclusion" §3.6). Not in any Part, though B3 depends on sync |
| Shorts cutter (NAS source, worker queue, autopilot Shorts, upload) | `app/shorts/*`, 7 migrations | Separate product line; the spec only says Shorts uploads continue (Part 2 §6.1). Uploads are not charged to the quota ledger (`app/shorts/youtube_upload.py` has no `can_afford`) |
| Logins and the global gate: `app_users`, `app_sessions`, `/login`, `/session/*`, `scripts/manage_users.py` | `app/session.py`, `20261118000000_app_users_sessions.sql`, `app/static/login.html` | Team tracker (`docs/TEAM_UPLOAD_TRACKING.md`, #142/#144), not in the spec. Closes the open LAN port: every route but `/login`, `/session/login`, `/static/theme.css`, `/static/midas.png`, `/health` needs a session. Per-role channel scoping (`app/access.py`, `channels.manager_id`, #145): the channel-id routes and `/auth/channels`; object-id routes through per-object resolvers (#146); list and global routes filtered, operational routes admin-only (#147). Each manager's roster: `team_members`, `app/team.py`, the Team page (#148). Channel assignments: `channel_assignments`, `assign_channel()`, `POST /channels/{id}/assign`, `GET /team/assignments` (#149). Upload capture: `channel_uploads`, written by `sync_channel` (#150). The uploads grid: `GET /team/uploads`, `app/team_uploads.py`, the Team page's Uploads tab (#151). The drill-down: `GET /team/uploads/videos`, a grid cell's video list (#152) |
| Self-hosted Postgres + PostgREST, nightly NAS snapshot, restore-on-empty | `app/backup.py`, `app/provision.py`, `docker-compose.yml`, `docs/SELF_HOSTED_DB.md` | Infra; the spec references it only in Part 3's schema discipline |
| OTel/Phoenix tracing | `app/tracing.py`, `docs/OBSERVABILITY.md` | Spec reuses it for the agent (Part 2 §3.1) |
| Egress RPCs with in-app parity fallbacks | migrations `202607*`, `app/dashboard.py`, `app/autopilot.py:116-123` | Supabase free-tier era |
| Transcript cache + captions-API fallback (250u per video) | `app/transcripts.py`, `video_transcripts` | Quota exposure unspecified |
| Episode exclusion | `app/content_type.py`, migrations `20260904*` | Matches Part 2 §2.1 "not an episode" |
| `/dashboard`, `/performance*`, `/autoshorts` UIs | `app/dashboard.py`, `app/performance.py`, `app/static/*` | |
| The Results page: `GET /seo/results`, `/results` | `app/seo_results.py`, `app/static/results.html` | #167 (the handover's findings record, replacing the Slice 1–3 docs #70, #94, #122), not in the spec. Reads `interventions`, `lever_verdicts`, `playlist_arms` and `short_link_recommendations` only; backlinks, titles, playlist test and Short links columns |
| Dead code: `app/keyframes.py`, `video_keyframes`, `audits.keyframes_extracted`, `videos.thumbnail_optimized_at`/`playlists_optimized_at`, statuses `approved`/`rejected`, `outcome_decision='redo_queued'`, `redo_of_audit_id`, `MAX_REDO`, `AUTO_REVERT_ON_REGRESSION`, `PLAYLIST_MEASUREMENT_WINDOW_DAYS`, `playlists.strategy_version` | various | Pre-spec reservations nothing writes or reads |
| The old audit picker: `autopilot._next_video_for_channel`, the `next_audit_candidate()` SQL function (`20260904000100`), `AUTOPILOT_PICKER_USE_RPC`; `PausedReason.UNSAFE_MODEL` | `app/autopilot.py`, `supabase/migrations/20260727160000_next_audit_candidate_rpc.sql` (replaced by `20260730010000`, `20260904000100`), `app/config.py`, `app/status_vocab.py` | No caller: the tick's house-format branch is gone; kept with its tests (`tests/test_autopilot_picker_rpc.py`, the live parity guards, the `next_audit_candidate()` drift check in `tests/test_status_vocab.py`), since dropping the SQL function needs a migration. `unsafe_model` is a persisted pause reason (not renamed or removed); nothing sets it now |

### 7.3 Built differently from the spec

Unless noted, each item's details are this build's own choices; the spec is silent on them.

1. **Strategy stamp timing (Part 1 A6, Part 2 §8).** Spec: derive at startup from the `DEFAULT_PROMPT` hash and the
   per-channel prompt-version id. Built: per audit, hashing the prompt text sent and its source
   (`app/audits.py:218-243`), so shorts/override/generated audits stamp differently. Pre-A6 audits carry
   `2026.07-baseline-v1`.
2. **Measurement cadence (Part 2 §1.1, §1.7).** Spec: weekly windows, extended once to 14 days. Built: symmetric
   21-day pre/post windows (`MEASUREMENT_WINDOW_DAYS`, `app/reach.py:60-82`) plus `ROLLOVER_SLOP_DAYS=1`, judged
   on CTR only.
3. **Dormancy (Part 2 §2.1).** Spec: keep dormant videos out at selection. Built: found only after the window
   (`REASON_DORMANT`, `app/measurement.py:280`); the old newest-first picker has no caller, and the tick picks only
   through the warm filter. A7 (2026-10-06): 4,254 applies landed on dormant videos.
4. **Embedding input (Part 3 B6).** Spec: one recipe (title + description + tags) for every video. Built: B6's recipe
   under its own `model_version` (`app/reembed.py`), but production still writes and reads two recipes under
   `EMBED_MODEL`, so that value doesn't identify the input. B6 embeds **every** video of the named channels (Shorts,
   private, episodes). No length cap. Token estimate = UTF-8 bytes / 3; price passed in (`--usd-per-mtok`).
5. **Playlist thresholds (Part 2 §4, B6).** Spec: per channel. Built: the engine reads process-global values; the
   frozen `tune_thresholds` overwrites the global from one channel (`app/playlists.py:518`) and filters on a
   `channel_id` column `playlist_assignments` lacks (`app/playlists.py:470-474`), so would fail if unfrozen.
   Per-channel values on `channels.playlist_thresholds`, read only by `backlinks.candidates` (`join_low`). Method
   (`app/reembed.py` `calibrate_channel`): `join_high` = p50, `join_low` = p5 of each member's cosine to the centroid
   of its playlist's *other* members; `leave` = p10 of each member's cosine to the centroid of *all* members. Needs 30
   similarities and 3 embedded members per playlist. `leave`'s order against `join_high` isn't guaranteed. p50 lets a
   non-member as close as the median member join without the judge: a starting value for owner review.
6. **Discovery provenance.** Created playlists are stored `origin='inherited'` (`app/playlist_discovery.py:200-205`);
   B3b identifies them via `playlist_assignments` `decision_source='discovery'` (`app/human_edits.py`
   `added_by_midas`).
7. **Traffic ingestion details (Part 2 §7, Part 3 B1).** Both traffic tables have an `id bigserial` (`app/rows.py`
   pages by `id`). The shared ledger has `report_type`, so traffic reports aren't reach coverage
   (`app/reach.py:122-130`). When a day's original and restated reports are both new, only the newest by parsed
   `createTime` is ingested (`app/traffic_poll.py:89`). The two feeds are isolated: one crashing fails the channel's
   run but not the other (`app/traffic_poll.py:155`).
8. **Apply cost.** `quota.APPLY` = 51u (`app/quota.py:67`) but apply no longer fetches stats: gates overestimate by
   1u. Spec Part 1 A10 says note it only.
9. **`interventions` DDL (Part 2 §7, Part 3 B2).** Spec lists columns only. Built: `not null` on `video_id`,
   `channel_id`, `lever`, `origin`, `arm`, `status`; `video_id → videos on delete cascade`; a partial unique index
   enforcing §1.6 (`supabase/migrations/20261006020000_interventions.sql`). Vocab checked in Python
   (`app/interventions.py` `_require`), not SQL `check`s.
10. **Human-edit ledger details (Part 2 §1.4, Part 3 B3; B3a).** `ledger_key` (unique, not in Part 2 §7) prevents
   duplicates. "Our videos" = any in `videos`, any channel (`app/human_edits.py` `our_videos`), plus the same sync's
   fetch; links to channels with no synced videos aren't recorded; self-links ignored. A removed link makes no row:
   it is noted in a same-edit addition's `removed_targets` and as `payload.removed_detected_at` on the earlier row.
   "Midas made the change" = description equals (whitespace collapsed) an applied audit's `suggested_description` or
   a reverted one's `description_before`; a match skips the whole change; a body-overridden apply isn't recognised.
   Only full syncs re-read old videos; a team edit then a Midas rewrite within one interval reads as Midas's.
11. **Human-edit ledger, playlist memberships (Part 3 B3, change 2; B3b).** "New" = no `playlist_assignments` row of
   any action for the pair (`app/playlists_sync.py:297-307`); no removal detection, so re-adds are never new. A
   playlist's first walk (`membership_walked_at` NULL) is a baseline that records nothing. Only the channel's own
   videos count; a membership of a not-yet-synced video is recorded on a later walk even if old (a false `human`
   row). A ledger error still seeds `sync` rows, losing that page. "Midas added it" = any non-`sync` `added`
   assignment or approved `add` proposal, human-approved ones included. Detection waits for an item-count change or
   `PLAYLIST_FULL_WALK_DAYS` (30) rotation, within `PLAYLIST_SYNC_QUOTA_BUDGET`.
12. **Warm filter (Part 2 §2.1, Part 3 B4).** Spec adds it *to* `next_audit_candidate`; built as a separate
   `warm_pool()` returning the whole pool. Window = latest `WARM_WINDOW_DAYS` distinct ingested reach `data_date`s
   (zero-row days count; gaps reach further back). Uncertified reach → empty pool. NULL `privacy_status` = public;
   `is_episode is not true`. Only *Midas* interventions in `ACTIVE_INTERVENTION_STATUSES` exclude (human rows never
   close). Explore share in Python (`explore_order`): each pick with probability `WARM_EXPLORE_PCT` is uniform over
   all but the best. `WARM_POOL_USE_RPC` (default false) isn't in the spec; parity tested offline
   (`tests/test_warm_pool_parity.py`). Slice 1 exclusions (`midas` rows only): cooldown `created_at > now() -
   p_cooldown_days days`, every lever; "for the experiment's duration" is *forever*: any `midas` `backlinks` row of
   arm `treated` or `holdout` bars the video permanently (a later experiment needs a boundary column). Shorts (not in
   the spec): `warm.warm_pool` drops `is_short` true after either path, since a Short's description links aren't
   clickable.
13. **`decide()` and `decision_log` (Part 3 B5).** Spec gives no question sets. Built: `QuestionSet` (name, question,
   answers, rules function) and `TRIAGE` (`app/decide.py`). One `QUESTION_SET_VERSION` covers every set and feeds the
   audit stamp, so any rules change moves every audit's `strategy_version`. `TRIAGE` offers five options but its
   rules choose only `backlinks`, `title` (item 30) or `no_change`. A backend answer needs a probability for every
   option (sum unchecked), else it's a failure; failures still log a row (NULL `jev_answer`/`jev_probs`); a failed
   log write never raises. `intervention_id` is `on delete set null`.
14. **Canonical backlink block (Part 2 §3.4, Part 4 S1.2).** Part 2 says "fixed marker lines"; built as Part 4: the
   exact heading plus the `<title> https://youtu.be/<id>` lines under it (`app/backlinks.py`). A blank line follows
   the block when text follows, so `strip` doesn't absorb a human link line. Over `BACKLINK_MAX` targets is refused;
   `#` removed from titles. A block-shaped line a human adds directly under the block reads as part of it. The 5,000
   limit is in characters.
15. **Siblings and candidates (Part 2 §2.3, Part 4 S1.1).** Window = latest 28 distinct ingested
   `channel_traffic_source_a3` data-days (`SIBLING_WINDOW_DAYS`). "Warm" = `warm.warm_impressions` only, so a target
   may be in an active intervention or an episode. NULL `is_short` eligible. Raw cosine vs the source channel's
   `join_low`, also for siblings; ranked by similarity, impressions, id. `skipped_unembedded` counts an unembedded
   source as 1. Similarity in-app over every eligible target's `vector(3072)`; no RPC (`app/backlinks.py`). Siblings
   off by default (item 35).
16. **Description-only apply, revert, ledger (Part 2 §2.5, Part 4 S1.3).** `apply_backlinks` sets success to
   `measuring` itself; the caller cancels failures. The revert also refuses while `BACKLINK_APPLY_ENABLED` is false,
   gated at 51u (it fetches the snippet). DRY_RUN calls no YouTube (renders onto the stored description; the revert
   records nothing). Only the fetched `snippet` is sent back, read-only fields as returned. A live description
   differing from the stored one goes to the ledger first. "Exactly the targets" (finding 4) = links to our videos
   equal the targets of a `treated` `midas` `backlinks` row with `applied_at`, not `cancelled`. Rendering precedes any
   YouTube call. The revert strips every canonical block (`app/backlinks_apply.py`).
17. **Tick routing, triage, holdout (Part 2 §2.1, §2.2, §1.3, §6.1, Part 4 S1.4; S1.4b).** The tick branches on
   `agent_enabled` after the Shorts action (`app/autopilot.py` `tick`); failing `can_run_agent` does nothing
   (`agent_ineligible`), no fallback; `can_run_agent` includes `can_audit`, so `autopilot_enabled = t` too. Gates
   (resync, cap, quota) precede triage, so an unaffordable tick records nothing. A `declined` row (lever `backlinks`,
   arm `n/a`) and a treated row that never reaches YouTube (`cancelled`, `payload.error.reason`, e.g. `dry_run`) hold
   the video only for the cooldown. The agent doesn't run while the kill switch is off or the language has no
   heading. `backlinks_stopped` is a triage context key, so it is logged. Context windows: 28 days (`CONTEXT_DAYS`)
   for recent interventions and traffic mix; the warm window for impressions/CTR. `has_related_block` (D5) = a link
   to any of our videos but itself. The preview asks `TRIAGE.rules` directly (no backend, no log).
18. **Next-watch in shadow (Part 2 §2.3, Part 4 S1.5).** Asked for every pair `candidates` returns (up to
   `2 × BACKLINK_MAX`). `candidates` already drops pairs below `join_low`, so the rules answer is always `yes`: the
   log measures agreement only on accepted pairs. Stored on `triage_json.next_watch`; the backend's answer only on the
   log row. Part 2 §2.4's shadow checks aren't built (D7). Cost: up to 6 sequential backend calls per `backlinks`
   video inside the tick (`app/agent_tick.py` `_next_watch`).
19. **Pair measurement (Part 2 §1.2, §1.3, §1.7, Part 4 S1.6; S1.6a).** Complete when every involved channel's
   frontier ≥ d0+7; a missing day counts as zero and is listed in `missing_days`; a never-ingested target channel
   leaves the row `awaiting_window` indefinitely. The extension lengthens only the post window, so `delta` = post ×
   7/14 − pre (views/week). Floor = the source's views over every traffic source in the post window, not
   `view_count`. `RESTATEMENT_HORIZON_DAYS = 28` after the post window: decided rows recomputed each run; `judged_at`
   kept unless the outcome changes; a recompute that can't decide keeps the old verdict. `cancelled` treated rows
   aren't measured; human rows are, even if later removed. d0 = the Pacific date of the timestamp; windows exclude
   d0. `status` holds the outcome, `measurement_status` the progress (§7.4) (`app/lever_measurement.py`).
20. **Weekly verdict and stop rule (Part 2 §1.3–§1.5, P1, Part 4 S1.6; S1.6b).** "Judged that week" =
   `judged_at` in the Monday–Sunday UTC week; a missed run shifts rows to the next week, which isn't an extra window.
   `cumulative_lift` is pooled (treated mean − holdout mean over all rows judged to date, current `delta`s). Band:
   `helped` at ≥ `BACKLINK_MIN_LIFT`, `worse` at ≤ −it; no verdict without a judged treated and holdout row. Past
   weeks never rewritten; a triggered stop is never cleared and keeps the lever off even if the lift recovers (owner
   restart = delete the row). Human rows: `n_treated` and mean delta only, never stop. Job runs every channel.
   `missing_days` doesn't exclude a row. Backlinks rows on Shorts enter no mean, either arm (`_without_shorts`; the
   arm hash keeps it fair) (`app/lever_verdicts.py`).
21. **The playlist test's draw (Part 2 §4, P3, Part 5 S2.1).** Members via `reembed._members` (latest action per
   pair). `eligible_members` counts embedded members; centroid = their vector sum, raw cosine. Candidates on the
   playlist's channel; NULL `privacy_status`/`is_short`/`is_episode` eligible. A refused threshold refuses the whole
   draw, so the once-only draw isn't spent. A second draw raises `AlreadyDrawn`. Not atomic: a draw dying midway
   leaves a partial draw a rerun refuses; recovery is deleting the channel's `playlist_arms` rows and proposals by
   hand (`app/playlist_test.py`).
22. **The playlist test's apply (Part 2 §2.5, Part 5 S2.2).** Only `failed` uses an attempt
   (`apply_error.attempts`). Position = count of the arm's higher-ranked adds already in the playlist. After a 400
   naming the position or sort order, that playlist's adds go appended, in rank, across runs; the extra call can
   exceed the n × 50u budget by 50u. An arm settles `dosed`/`no_dose` once no approved add is unsent or retryable,
   whatever is pending; a proposal approved after settling is never sent; nothing approved stays open while any is
   pending. Kill switch off → nothing settles. A budget stop or quotaExceeded ends the run (channel `degraded`); a
   token error fails only that channel. DRY_RUN checks no budget, settles nothing (`app/playlist_test.py`).
23. **The playlist test's measurement and verdict (Part 2 §1.2, §1.3, §1.5, P3, Part 5 S2.3).** Weeks stop at
   `PLAYLIST_EXPERIMENT_WINDOWS`. Every week's row and arm numbers are recomputed each run until done (unlike
   backlinks); afterwards nothing is re-read. A vanished playlist leaves every week's means and ends
   `insufficient_data`. `no_dose` arms keep their status. An errored arm holds back the channel's verdicts and end. No
   verdict for a week lacking a dosed treated or a holdout arm, so such a test stays `pending`. `pre_weekly` = pre sum
   × 7 / 28. Answer: `no` if the window-4 row triggered the stop rule, `yes` if not, else `pending`; nothing reads
   `lever_verdicts.stopped(channel, 'playlist')`. A failed `playlist_arms` read skips the playlist half
   (`app/playlist_test.py`).
24. **Short-link recommendations (Part 2 §2.3, P4, Part 5 S2.4).** The per-run cap counts Shorts that get rows; a
   Short with no vector or no target uses no slot and is retried. Refused thresholds refuse the channel's run
   (`degraded`, `refused: <reason>`), noticed only when there are new Shorts. Each Short's rows go in one insert after
   its pair decisions, so it is written whole or not at all; the log row's `intervention_id` stays NULL. A Short needs
   `is_short` true; a NULL target is eligible; no episode filter. No `analytics_authorized` check; `channel_id`
   nullable (`app/short_links.py`).
25. **The Short-links page and the tick (Part 2 §1.4, §2.5, P4, Part 5 S2.5).** Pages count Shorts (grouped in-app),
   those with a `pending` row first, then by feed views, then id; `status` filters rows within a Short. The tick
   writes the ledger, the Short's other rows, then this row's `set`, so a partial tick is redone whole. Changing the
   target leaves the old pair's intervention `applied`; nothing records when a link came off. A dismissed sibling
   stays `dismissed`; `pending`/`set` siblings become `not_chosen`. Dismissing a `set` row is 409. Setting an earlier
   target back records a new period under `short_link:<short>:<A>:2` (`_episode_key`). The card confirms before
   recording (no undo route) and sits on the Playlists tab (`app/static/channel.html`).
26. **Short links seen in the traffic, their measurement and verdicts (Part 2 §1.2, §1.4, Part 5 S2.6).** Window = the
   target channel's latest 28 ingested data-days (`short_links.FEED_WINDOW_DAYS`); zero-view or blank-detail rows
   never count. `detected_at`/`seen_at` = first day with views as Pacific midnight; only a NULL `seen_at` is written.
   Intervention `channel_id` = the Short's. Once inferred, never re-inferred. Bias: d0 is the first day with views, so
   a link set before detection first ran reads delta near zero, biasing `short_link` verdicts against older team
   links (spec's d0 rule, kept). Floor stays the Short's views, every type; only `pair_views` takes `source_type`. Only
   `human` rows measured; detection only on `TRAFFIC_INGEST_CHANNELS`, isolated from backlinks (`app/short_links.py`).
27. **The title write and its revert (Part 2 §2.5, Part 6 S3.1, F1).** `title_changed` on apply is
   `ApplyError(FAILED, "title_changed")`; on revert `HTTPException(409, "title_changed")`. Both compare the live title
   exactly, after a 1u fetch. Each lever reads only its own kill switch. `payload.title_before` may be empty but must
   be present. No human-edit ledger for titles: a stored title differing from live is overwritten on success. Fetch
   and send shared with `backlinks_apply.py` (`app/titles_apply.py`).
28. **The title writer, its checks, the preview and the bake-off (Part 2 §2.4, §3.3, Part 6 S3.2, F9, F12).** The
   preview walks `warm.warm_pool` until `n` videos pass `TRIAGE.rules`, so it varies and inherits the pick's
   exclusions; the bake-off samples by impressions without them (`pick=False`). Transcripts from the cache only
   (`titles._transcript`), since a live fetch may cost 250u outside the quota gate. Median CTR over warm long videos
   with impressions; ceiling's 1% of warm long videos. Top performers = browse + suggested views (28 traffic days) ÷
   warm-window impressions. Search terms are the video's. Checks: all-whitespace = empty; a language not in `SCRIPTS`
   (other than `en`) fails; URL = `https?://`, `www.`, `youtu.be/`, `youtube.com/`; `<`, `>`, line breaks fail
   (`invalidTitle`). A malformed reply is a failed attempt, retried. Stamp: the spec's five inputs; `prompt_sha256`
   of the rendered `system_prompt()`, so `TITLE_CANDIDATES` moves it. The bake-off hides each model behind one
   shuffled code (`W1…Wn`), one call each (`app/titles.py`, `scripts/title_bakeoff.py`).
29. **The old title path's retirement (Part 6 S3.6, F13).** A non-agent channel records `shorts_only` and is touched
   so the round-robin moves on. Kept: `_next_video_for_channel` (no caller; mirrors the `next_audit_candidate()` SQL
   function, droppable only by migration), `_applies_today`'s audit count, `eligibility.can_audit`,
   `PausedReason.UNSAFE_MODEL`. The guard is in `apply_audit_internal` (`force`, default false) before any write, so a
   refusal records nothing; apply-pending checks once, then per audit. `run-bulk`/`reaudit-quarantined` never apply,
   so are unguarded. NULL `agent_enabled` = non-agent. Dashboard apply buttons send no `force`, so show the 409 on an
   agent channel (`app/audits.py`).
30. **Triage and routing for titles (Part 2 §2.1, §2.2, §1.3, Part 6 S3.3, F2–F5, F12).** The backlinks rule requires
   `backlinks_enabled`. Title keys are read only while `title_enabled`; NULL `is_short` isn't a Short; a NULL CTR or
   median never answers `title`. The title context is cached with the pool (`_pools`). The agent-run limit applies by
   routed path, whatever the arm; turned-away videos are declined until the cooldown. No passing candidate → treated
   `cancelled`, no `planned` step, counting toward `autopilot_daily_cap` and `TITLE_DAILY_CAP`. A raising writer →
   `cancelled`, `writer_exception`, re-raised. `_agent_tick`'s "neither lever can run" uses `titles_open`, not the
   daily limits, so a capped channel still ticks and declines. Each preview takes its own lever as open
   (`titles_on=True` ignores `TITLE_APPLY_ENABLED`, `TITLE_CHANNELS` and limits) (`app/agent_tick.py`).
31. **The agent loop, its tools and the trajectory (Part 2 §3.1, §3.2, Part 6 S3.4, F5, F11, F14).** Tools see only
   the run's video (`Subject`); the model passes only schema arguments, keeping runs comparable (§3.5 (a)). The
   agent's stamp hashes `AGENT_PROMPT` and adds `agent_model` (`AUDIT_MODEL`); only `planned` rows are stamped. A turn
   = one `chat_tools` call; a reply without a tool call gets `NUDGE` and uses its turn; a terminal call ends the run.
   First failing `submit_title` gets the failure back, the second ends `failed`, `checks_failed`. `chat_tools`
   retries once immediately on timeout or ≥ 500, then raises → `cancelled`, `writer_exception`, with the trajectory
   so far. Trajectory texts cut to 2,000 characters; the model gets results whole. `get_title_history` merges the
   newest 10 of each table; `worst` performers count no views as 0; `write_candidates` is unchecked. A decline is
   treated `declined` without `applied_at`, left out of the daily cap (F14) (`app/agent/loop.py`,
   `app/agent/tools.py`).
32. **Title measurement, verdicts, auto-revert (Part 2 §1.2, §1.3, §1.5, §1.7, Part 6 S3.5, F6–F8, F14).** Own module
   (`app/title_measurement.py`). d0 = Pacific date of `applied_at`, else `created_at`. Declines are measured like
   holdouts. Completeness reads only the video's channel frontier. No extension: under the floor →
   `insufficient_data`. Impressions/CTR recorded, judge nothing. A judged title put back stays in its path's mean
   (intention-to-treat). The harm guard is an extra stop condition; stops are sticky. Auto-revert compares with the
   holdout mean of the row's judged week, else all holdouts judged so far; worst first; the limit counts reverts done;
   the kill switch or a short ledger stops the channel's reverts for the run. The job's title half runs only on
   channels with a `midas` `title` row, isolated. Once per experiment: a `midas` `title` holdout row, or treated row
   unless `cancelled` without `applied_at` (declines included, F14), holds its video at any age (`warm._holds`,
   `warm_pool()`); a row cancelled before its write holds only for the cooldown.
33. **A path with no share is closed (Part 6 F5, F7).** `titles.path_closed`: stop rule fired or no share
   (`TITLE_AGENT_PCT` 0 for the agent, 1 for the pipeline). `stopped` = both closed; `route` hands over only when its
   path is closed and the other isn't (`app/titles.py`). Otherwise at `TITLE_AGENT_PCT=0` a pipeline stop would send
   every title to the unreviewed agent, which, with no verdicts, would never stop (F7).
34. **Search counts for titles; the pipeline writes the SEO team's structure (Part 6 F6, finding 3, P5; owner,
   2026-10-31).** Spec: measure on browse (3) + suggested (7) and aim away from search. Built: the pipeline writes the
   SEO team's bilingual, search-shaped structure (`titles.TITLE_STRUCTURE`); the agent its own within `TITLE_LIMITS`;
   the test counts search too (`title_measurement.SOURCE_TYPES = (3, 5, 7)`), as does `TITLE_MIN_PRE_VIEWS`. Top
   performers are still ranked on browse + suggested (`titles.BROWSE_SUGGESTED`). The bake-off is rerun before
   `WRITER_MODEL` is chosen. Keeping a series name (e.g. TMKOC) is a limit on both paths.
35. **Backlinks stay on the source's own channel (Part 2 §2.3, P2; owner, 2026-11-16).** Spec: targets on the source's
   channel or a sibling. Each channel is one language, so siblings meant cross-language links; dropped.
   `BACKLINK_SIBLINGS_ENABLED` (default false) makes `backlinks.target_pool` read no siblings; `siblings` stays.
   `default_language` can't substitute (Hindi, Bhojpuri, Rajasthani, 3D Animated all `hi`). Existing sibling blocks
   stay. A target ≥ `BACKLINK_DUPLICATE_SIM` (0.98) like the source or a kept target is left out as a re-upload
   (observed 0.985–0.993; closest different videos 0.972), since `title_key` catches only equal titles
   (`backlinks.candidates`).

### 7.4 Contradictions within the spec

- **`agent_enabled`.** Part 2 §7 says `bool default false`, B2 `bool not null default false` (built as B2). Part 2
  §7 ("Data model (Phase B)") also lists Slice 3's `niche_reference_*` columns.
- **Backlink block markers.** Part 2 §3.4: "fixed marker lines"; Part 4 S1.2: the exact heading line plus the
  `youtu.be` lines. Built as Part 4 (7.3 item 14).
- **Playbook storage.** Part 2 §5 puts it in `channels.playbook_json`; Part 2 §7 doesn't list it.
- **Warm window.** §8 says 28 "ingested data-days"; A7's query used 30 calendar days. Built on ingested days (7.3
  item 12).
- **Intervention status vs measurement status.** B2's lifecycle statuses mix in measurement outcomes. As built,
  `status` carries lifecycle and outcome (`judged`, `insufficient_data`); `measurement_status` only progress,
  `awaiting_window|extended|done` (`app/status_vocab.py`; 7.3 item 19).
- **Midas edits in B3.** B3 doesn't say whether human-triggered applies through Midas are `human` or `midas`. As
  built, any apply, revert or approved proposal counts as Midas's (`app/human_edits.py` `made_by_midas`,
  `added_by_midas`).
- **"Active intervention".** Part 2 §1.6 limits *Midas* interventions to one per video; §2.1 and B4 say any
  origin. As built, Midas only (`app/interventions.py` `active_for`, the partial unique index), since human rows
  never close (7.3 item 12).
- **Which statuses are active.** Neither Part says. As built: `planned|applied|measuring|holdout`, not `declined`
  (`app/status_vocab.py`).
- **`WARM_MIN_IMPRESSIONS`** says "Revisit after Phase A live numbers" (§8); it wasn't revisited.
- **`decision_log` columns.** Part 2 §7 names them `jev_answer`/`jev_probs` though the default backend is `llm`,
  and stores no backend or question-set name. As built, `jev_answer` holds whichever backend answered; the question
  set is told apart by `subject`'s shape (video id vs `<source>-><target>`) and by
  `short_link_recommendations.decision_log_id` (7.3 items 13, 18).
- **Document framing.** "This file has two parts" while it has three; "Ground truth used: `STATE.md` @ `bddd373`"
  predates Phase A.

---

## 8. Operational reality

The live DB is unreachable from here. Every figure is quoted from a doc, with its date.

- **Live, 2026-11-16** (`docs/PLAN_TO_2026-11-27.md`): 12 titles written on the first day (Hindi, Marathi,
  Gujarati 4 each); backlink blocks on every newly enabled channel (Haryanvi 7, Malayalam 6, Rajasthani 6, Tamil
  5); no errors, no pauses; Data API ≈6.2k units by 13:00 UTC (the 3,000u collection reserve stops writes near 7k).
  NAS snapshot `midas.0.sql`, 3,766,099,174 bytes, 13:49 UTC.
- **Quota budget** (`docs/PLAN_TO_2026-11-27.md`): 10,000 units/day for the fleet; a title or backlink write ≈ 51u
  (`quota.APPLY`), so ≈ 130 writes/day fleet-wide after syncs and polls.
- **Marathi thresholds** (B6, 2026-10-08, `docs/PHASE_B_FINDINGS.md`): `join_high 0.9014`, `join_low 0.8454`,
  `leave 0.8703` (5,176 sims, 82 playlists).
- **Traffic mix** (A1.1, Marathi, data date 2026-09-29, 52,319 report rows, 259,868 views): 14 Playlists 118,342
  (45.5%) · 24 Shorts feed 49,292 (19.0%) · 7 Suggested 48,862 (18.8%) · 3 Browse 17,652 (6.8%) · 8 Other 12,851
  (4.9%) · 4 Channels 7,432 (2.9%) · 5 Search 2,911 (1.1%) · 0 Direct 1,368 · 9 External 668 · 20 Endscreen 254 ·
  18 Playlist pages 148 · 27 Sound 33 · 32 Related video 27 · 26 Hashtag 20 · 17 Notifications 8. Type 14 split:
  `RD…` Mixes 117,929 · our `PL…` playlists **50** · other 363.
- **Routing levers before Midas** (A1.1/A1.3, 2026-09-29): 1,804 description-link pairs on Marathi → 4
  attributable views (type 7); Short → video (type 32) 27 views from 12 Shorts. Type-7 suggested views from any of
  our channels: 11,113 of 48,862 (22.7%); Mixes seeded from our videos: 7,024 of 117,929 (6.0%).
- **Sensor shape** (A1.1): `channel_traffic_source_a3` has 15 columns, `playlist_traffic_source_a2` 16; source
  types are numeric codes; steady lag 2 days; the playlist report restates some data dates; ≈52k raw rows per
  Marathi channel-day. On-demand detail for PLAYLIST and SHORTS returns 400; RELATED_VIDEO and YT_SEARCH detail
  work (A1.2). Search terms are available, with low-volume suppression in the report (233 of 319 type-5 rows
  empty) (A3).
- **Short → video link field** (A2, 2026-10-01): not readable or writable via the Data API.
- **The old title autopilot** (A7, 2026-10-06, before it was retired): 822 judged applies, win 7.8% · regression
  12.9% · neutral 79.3%; 4,254 applies landed on dormant videos (Gujarati 91% of its last-90-day applies).
- **Blank:** verdicts (none yet); Shorts upload volume and its Data API cost (not charged to the ledger, §7.2);
  playlist proposal queue size beyond ">1,000 pending".

**SQL to refresh** (on the office machine: `docker compose exec db psql -U midas midas`; `count(1)`, because the
office copy-paste path drops `*`):

```sql
-- channels and their switches
select id, name, default_language, agent_enabled, autopilot_enabled, autopilot_daily_cap, autopilot_paused_reason,
       autopilot_shorts_enabled, measurement_enabled, reach_warmup
from channels order by name;

-- data frontiers per channel and report type (reach, video traffic, playlist traffic)
select channel_id, report_type, max(data_date) frontier, count(distinct data_date) days_ingested
from reporting_reports_ingested group by 1,2 order by 1,2;

-- daily Data API burn, last 30 days
select date_trunc('day', occurred_at) d, sum(units) units, count(1) filter (where not success) failures
from quota_log where units > 0 and occurred_at > now() - interval '30 days' group by 1 order by 1;

-- interventions per channel, lever, origin, arm, status and measurement progress
select channel_id, lever, origin, arm, status, measurement_status, count(1)
from interventions group by 1,2,3,4,5,6 order by 1,2,3,4,5,6;

-- title rows by path and outcome (holdout rows have no path); errors and auto-reverts
select channel_id, coalesce(payload->>'path', 'holdout') path, status, payload->'error'->>'reason' error,
       count(1), round(avg((measurement_result->>'delta')::numeric), 3) mean_delta,
       count(1) filter (where (payload->'revert'->>'auto')::boolean) auto_reverts
from interventions where origin = 'midas' and lever = 'title' group by 1,2,3,4 order by 1,2,3,4;

-- weekly verdicts, every lever
select channel_id, lever, arm_scope, week_start, n_treated, n_holdout, lift, cumulative_lift, windows_judged,
       verdict, stop_rule_triggered
from lever_verdicts order by channel_id, lever, arm_scope, week_start;

-- playlist test arms
select channel_id, arm, status, measurement_status, count(1) from playlist_arms group by 1,2,3,4 order by 1,2,3,4;

-- Short-link recommendations
select channel_id, status, count(1), count(seen_at) seen from short_link_recommendations group by 1,2 order by 1,2;

-- shadow agreement per question set (a NULL jev_answer is a backend failure)
select case when d.subject not like '%->%' then 'triage'
            when exists (select 1 from short_link_recommendations s where s.decision_log_id = d.id)
              then 'next_watch: short links'
            when d.intervention_id is not null then 'next_watch: backlinks'
            else 'next_watch: unlinked' end question_set,
       count(1) rows_,
       count(1) filter (where d.jev_answer is null) backend_failures,
       count(1) filter (where d.jev_answer = d.rules_answer) agree,
       round(count(1) filter (where d.jev_answer = d.rules_answer)::numeric
             / nullif(count(1) filter (where d.jev_answer is not null), 0), 3) agreement
from decision_log d group by 1 order by 1;
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
