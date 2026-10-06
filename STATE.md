# Midas — STATE

> **What this file is.** A ground-truth snapshot of what exists **in this repo**, for
> priming an architecture conversation that cannot read the code.
>
> **Rules for whoever regenerates this:**
> 1. Every claim must be verifiable by reading a file in this repo. Cite the path.
> 2. If something is planned but not built, it goes in §7 (Delta) — never in §2–§6.
> 3. Do not summarise the specs. `CONTINUOUS_IMPROVEMENT_LOOP.md`, `PLAYLIST_OPTIMIZATION.md`
>    and `plan.md` hold intent; this file holds reality. The gap between them is §7.
> 4. Verbatim over paraphrase for config values, metric names, and prompt text.
>
> **Regenerate with:** Claude Code, prompt in §9.

**Generated:** 2026-10-06 (header updated for the Phase A conclusion; §4, §5 updated for the daily `video_sync` job, sync decoupled from autopilot; header + §1 1B updated for A9 + A0 24 h passing on the office machine; header + §3 + §7.1 updated for the office restart: Phase A image live, freeze confirmed, A1 report jobs created; §4, §5, §8 updated for per-item poll errors (fail when a whole category fails, `degraded` when partial) and job ids on `_daily_reconcile`'s inner ERROR lines; §7.1 updated for #24 restart-day kit: A1 traffic-source probe scripts written, not run; §4, §8 updated for #23 A8 finish: metrics_poll/reporting_poll/measurement_eval fail the run, job id on the fan-out ERROR line; §1, §3, §6, §7.3 updated for #22 prompt-text strategy stamp, `app/audits.py` line cites re-pointed; header, §7.3, §7.4 updated for A11 superseded-spec banners; §1, §5 updated for A5 `bgc` code path; §1, §3, §6, §7.3 updated for A6 derived strategy stamp; §4, §5, §7.1, §7.3, §8 for A10 quota gate; §1, §3, §4, §5, §7.1 for A4 writer freeze; §4, §5, §8 for A8 on 2026-09-28) · **Commit:** the Phase A conclusion commit on top of `49c3e96` (a commit can't cite its own SHA) · **Branch:** `main`
(working tree clean. `scripts/overnight_tickets.sh` is the unattended ticket runner, driven by a playbook: dev tooling, never deployed. The shipped shorts plans in `docs/superpowers/plans/` and the two `docs/agentic-workflow-*.excalidraw` diagrams were deleted, and on 2026-09-29 so were the finished one-off scripts (`export_supabase`, `import_to_local`, `backfill_is_episode`, `reconnect_evidence_loop`), the draft `PHASE_2_TRACK3_PLAYLIST_BUILD.md`, and the never-started `2026-08-24-format-scorers-design.md`. The two standalone shorts-cutter design docs moved to the shorts-cutter repo (`docs/design-history/`). All of it is in git history.)

**Office deployment (2026-09-29, from `docs/PHASE_A_FINDINGS.md` A0/A1.1).** The office
machine has run the Phase A image since 2026-09-29 11:54 UTC. The four A4 writers are
confirmed frozen from the startup log. All 13 channels have `autopilot_enabled = f`
(title autopilot off since ≈2026-09-23, owner). 11 have `autopilot_shorts_enabled = t`,
so the autopilot tick still runs, for Shorts only. The office `.env` sets
`AUTOPILOT_TICK_SECONDS` to 30. There were 1,910 audits in a measurement window on
2026-09-29 (Marathi 1,198, Gujarati 706, Punjabi 6). Two Reporting API jobs exist on
`UCr5-YUqBiW7PUmeAtxUWuRg`: `channel_traffic_source_a3` and
`playlist_traffic_source_a2`. `channel_traffic_source_a2` is retired: `jobs.create`
returned 404. **A9 passed on 2026-10-01:** all 8 registered jobs `success`, and Punjabi (the only
`playlist_health_enabled` channel) was scored 2026-10-01 07:00 UTC (39 playlists). **The A0 24 h check
passed too:** the last apply fleet-wide was 2026-09-24 04:00 UTC. A1.1 and A2 have been inspected
(`docs/PHASE_A_FINDINGS.md`). Video sync had stopped with the title pause (the last Marathi sync was
2026-09-24); the `video_sync` job (§4) fixes that, live since the 2026-10-01 restart. **Phase A evidence is
complete (2026-10-06):** rollout channel #1 is Marathi; all three routing levers are measurable (outcome (a)), but
today they carry ≈0 traffic; judged title verdicts are 64 wins vs 106 regressions. Conclusion and proposed Part 2
changes: `docs/PHASE_A_FINDINGS.md` "Phase A conclusion".

**Data caveat for this generation.** The live database runs on the office machine,
bound to `127.0.0.1:55432` there (`docker-compose.yml:18-22`), so it can't be reached from the
machine that generated this file. The rules say leave a field blank when a live count
isn't available, so every live count below is blank. Where the repo itself records a dated
measurement (in code comments, docs, or the dev-machine `logs/` that end 2026-08-13), it
is quoted and labelled with its date and source. §8 ends with the SQL to fill the blanks.

Spec abbreviations: **CIL** = `docs/CONTINUOUS_IMPROVEMENT_LOOP.md`, **PO** =
`docs/PLAYLIST_OPTIMIZATION.md`, **plan** = `docs/plan.md`. All three now open with a banner marking them
superseded by `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md` and listing the parts it keeps.

---

## 1. Phase status

| Phase | Theme | Status | Evidence (paths) | Notes |
|---|---|---|---|---|
| 0 | Sensor foundation | **built** (CTR via a different API than spec) | `app/analytics_client.py`, `app/metrics_poll.py`, `app/reporting_client.py`, `app/reporting_poll.py`, `app/reach.py`, migrations `20260610122433_analytics_authorized.sql`, `20260610134419_metrics_tables.sql`, `20260702174235_phase05_reporting_reach.sql` | CTR does not exist on the on-demand Analytics API. It comes from Reporting API CSVs (`channel_reach_basic_a1`) into `video_reach_daily` (`docs/PHASE_0_GAPS.md` Gap 1). The video sensor polls only in-measurement videos by default (`METRICS_POLL_MEASURED_ONLY=true`). |
| 1A | Metadata control loop | **partial**: sense and judge built; the act half is inert | `app/measurement.py`, `app/verdicts.py`, `app/audits.py:789` (`revert_audit`), migration `20260702183233_phase1a_loop1_measurement.sql` | Verdicts are written. There is no redo path and no auto-revert: `MAX_REDO` and `AUTO_REVERT_ON_REGRESSION` are declared in `app/config.py` but never read. `OutcomeDecision.REDO_QUEUED` is "Reserved … nothing writes it yet" (`app/status_vocab.py:96-98`). `docs/PHASE_2_TRACK2_LOOP1_REDO.md` is still **DRAFT**. |
| 1B | Playlist inventory + health | **built** (scorer was crashing 2026-08-06 → 2026-09-23; fixed) | `app/playlists_sync.py`, `app/playlist_health.py`, `app/playlists_router.py:521,552`, migrations `20260618115221_…`, `20260618133036_…` | From `b355f40` (rows refactor) until this commit, `score_channel` raised `NameError: name 'METRIC_ROW_PAGE' is not defined` (seen in `logs/midas.log*`). It now reads through `rows.rows_for_ids`, covered by `tests/test_playlist_health.py`. The office deploy (2026-09-29) refreshed them: `health_computed_at` 2026-10-01 07:00 UTC on the one `playlist_health_enabled` channel (`docs/PHASE_A_FINDINGS.md` A9). Tier-2 (playlist traffic source) is disabled: `TIER2_TRAFFIC_SOURCE_SUPPORTED = False` (`app/metrics_poll.py`, Gap 6 REOPENED). |
| 2A | Competitor research | **not started** (as spec'd) | none | Something nearby exists. `app/reflection.py` has `derive_niche_queries` and `_sample_competitors`, which call `search.list` × 2 and feed the *prompt reflection* loop, not playlists. No `playlist_competitor_reference_json`. |
| 2B | Playlist construction | **not started** (as spec'd); a pre-spec similarity builder runs instead | `app/playlist_discovery.py` (weekly, **creates** playlists via `playlists.insert`), `app/playlists.py` (daily reconcile add/remove); both frozen by default behind A4 flags (§4) | No `playlist_interventions` table, no LLM re-rank for session continuation, no ordering or entry-point logic. `join_pass` is commented out in autopilot (`app/autopilot.py:453-455`: "Playlist allocation skipped — workflow under review"). |
| 2C | Playlist self-eval | **not started** | none | Nothing measures playlists the optimizer created. |
| 3A | Metadata playbook | **not started** | none | There is no `app/playbook.py` and no `playbook_json`. The only memory-like mechanism is `prompt_versions` reflection (§7.2). |
| 3B | Playlist playbook | **not started** | none | |
| 4 | Meta loops | **partial** (stamping only) | `audit_strategies` table + seed row (`20260702183233_…`), `app/audits.py:196-286,428-442` | Every audit is stamped with a derived `strategy_version(prompt_text, prompt_source, prompt_version_id)` = `<STRATEGY_LABEL>-<12-hex sha256>` (§3), hashing the sha256 of the system prompt actually sent plus its source (`override|shorts|generated|default`), and each distinct version gets its own `audit_strategies` row naming that source. There is no `app/eval.py`, no challenger routing, and no `/strategies` endpoints. Per-channel prompt champion/challenger exists in `app/reflection.py`; that is a different design (§7.3). |

**Channels live.** Per-channel flags are DB columns (`channels.*`). Live values are blank
because the DB was unreachable (see caveat). The repo does record:

| Channel | `analytics_authorized` | Measurement | Playlist optimizer | Thumbnails | Since |
|---|---|---|---|---|---|
| `UCr5-YUqBiW7PUmeAtxUWuRg` (Marathi) | (blank) | (blank) | n/a: no such flag | n/a: no such flag | Phase 0 probe channel 2026-06-10 (`20260610134419_metrics_tables.sql` header). In the default reconcile allowlist (`app/config.py:134-139`). |
| `UC8KjoL0Z9mTHKqB6gFutkJw` (Punjabi) | (blank) | (blank) | n/a | n/a | Reach CSV probe 2026-07-02 (`20260702174235_…` header). Gap 6 bisect (`docs/PHASE_0_GAPS.md`). Reconcile allowlist. |
| `UCOVKJdzghm2gOnuaGeJTonA` (Gujarati) | (blank) | (blank) | n/a | n/a | Reconcile allowlist only. |
| `UCc4Tv_DEGDEKrKAt-vyVNmw` (Haryanvi) | (blank) | (blank) | n/a | n/a | Reconcile allowlist. `app/audits.py:390-395` records that 57 English-only audits shipped to "a Haryanvi audience" when `default_language` was missing. The code path for `bgc` exists: `lang_display_name("bgc")` → `"Haryanvi"` (`app/transcripts.py:31` `_LANG_NAMES`), and `youtube_language_code` sends it to YouTube as `hi` (`app/youtube_metadata.py:58-71` `_NON_ISO_639_1 = {"bgc": "hi"}`). `scripts/probes/probe_i18n_languages.py` (live, not run by the suite) checks `bgc`/`hi` against `i18nLanguages.list`. |

Flags that actually exist on `channels`: `analytics_authorized`, `measurement_enabled`,
`reach_warmup`, `playlist_health_enabled`, `autopilot_enabled`, `autopilot_shorts_enabled`,
`sync_shorts`. None of `playlist_optimizer_enabled`, `playbook_enabled`, or any thumbnail flag
exists (see §2).

Recorded fact (`app/audits.py:311-321`): *"on 2026-08-23 the only channel with autopilot on
was the one channel with that flag [measurement_enabled] off — 57 applies in a month, every
one landing on the `not_applicable` default."*

---

## 2. Schema — as applied

**Migrations applied** (`supabase/migrations/`, in order; bootstrap `supabase/bootstrap/000_roles.sql`, `010_storage_shim.sql` run first):

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
```

These are the migration files. The rows in the live DB's migration ledger weren't checked (DB unreachable).

**Tables that exist** (the columns are the union across the migrations above):

- **`channels`**: `id text pk, name, handle, refresh_token text not null, access_token, token_expiry timestamptz, last_synced_at, created_at, default_language text, autopilot_enabled bool default false, autopilot_paused_reason text, autopilot_last_tick_at, autopilot_daily_cap int default 10, analytics_authorized bool default false, last_full_synced_at, playlist_health_enabled bool default false, measurement_enabled bool default false, autopilot_shorts_enabled bool not null default false, autopilot_shorts_daily_cap int default 1, autopilot_shorts_upload_cap int default 2, shorts_cut_mode text default 'highlights', shorts_camera_motion text default 'calm', sync_shorts bool (nullable), nas_folder text, autopilot_paused_at timestamptz, reach_warmup bool default false`.
  - Of the spec'd columns, only **`analytics_authorized`** exists. `playbook_json`, `playbook_built_at`, `playbook_outcome_count`, `playlist_playbook_json`, `playlist_playbook_built_at`, `playlist_competitor_reference_json`, `playlist_competitor_built_at`, and `playlist_optimizer_enabled` do **not**. The `*_enabled` flags that do exist are listed in §1.
- **`videos`**: `id text pk, channel_id → channels on delete cascade, title, description, tags text[], thumbnail_url, category_id, view_count, like_count, comment_count bigint, published_at, last_fetched_at, privacy_status text, thumbnail_optimized_at, playlists_optimized_at timestamptz, duration_seconds int, is_short bool, is_episode bool (nullable; NULL = not episode)`.
- **`audits`**: `id bigserial pk, video_id → videos on delete cascade, status text default 'pending', suggested_title, suggested_description, suggested_tags text[], thumbnail_feedback, issues_found jsonb, ai_reasoning, applied_at, created_at, title_before, description_before, tags_before text[], view_count_at_apply, like_count_at_apply, comment_count_at_apply bigint, transcript_available bool, transcript_lang, keyframes_extracted int, prompt_version_id → prompt_versions, measurement_status text default 'not_applicable', measurement_started_at, measurement_result jsonb, outcome_decision text default 'none', redo_of_audit_id → audits, strategy_version → audit_strategies`.
  - **All five spec'd Loop-1 columns exist**: `measurement_status`, `measurement_result`, `outcome_decision`, `redo_of_audit_id`, `strategy_version`. `redo_of_audit_id` is never written by code.
  - Status vocab (`app/status_vocab.py`): `pending|applied|failed|quarantined|blocked_test_and_compare|shadow_pending|reverted|approved|rejected`. No code writes `approved` or `rejected`.
  - Partial index `audits_measurement_inflight_idx` on `('awaiting_window','measuring')`. Also `audits_video_created_idx (video_id, created_at desc)`.
- **`video_metrics`** (`20260610134419`):
  ```sql
  id bigserial pk, video_id text not null → videos on delete cascade, channel_id text not null → channels,
  window_start date not null, window_end date not null,
  impressions bigint, ctr float,               -- backfilled by reporting_poll, or written as is_pre_change baseline by measurement
  views bigint, est_minutes_watched bigint, avg_view_duration_sec integer, avg_view_pct float,
  is_pre_change boolean default false, fetched_at timestamptz default now(),
  unique (video_id, window_start, window_end)
  ```
- **`video_reach_daily`** (not in spec; this is the real CTR source): `video_id text not null (no FK), channel_id → channels, date date, impressions bigint not null, ctr double precision not null (fraction 0..1), report_id text, fetched_at, unique(video_id, date)`.
- **`reporting_reports_ingested`** (not in spec): `report_id text pk, job_id, channel_id, data_date date, row_count int, ingested_at`.
- **`playlists`**: `id text pk, channel_id → channels on delete cascade, title text not null, description default '', synced_at, role text, origin text not null default 'inherited', item_count int, last_synced_at, created_by_optimizer_at, strategy_version text, health_score float, health_recommendation text (revive|remove|keep|insufficient_data), health_computed_at, health_rationale_json jsonb, membership_walked_at timestamptz`.
  - Roles actually assigned: `series | funnel | inherited` (`app/playlists_sync.py:50-63`). `topic_cluster` is "deliberately left to a follow-up". `playlist_discovery` inserts rows **without** setting `origin='optimizer_created'` or `created_by_optimizer_at` (`app/playlist_discovery.py:200-205`), so every discovery-created playlist lands as `origin='inherited'`.
- **`playlist_metrics`**:
  ```sql
  id bigserial pk, playlist_id text not null (no FK), channel_id → channels, window_start date, window_end date,
  playlist_starts bigint, views_per_playlist_start float, avg_time_in_playlist_sec integer,   -- spec: avg_time_in_playlist_min FLOAT
  playlist_views bigint, playlist_est_minutes_watched bigint, is_pre_change boolean default false,
  fetched_at, unique (playlist_id, window_start, window_end)
  ```
- **`video_traffic_source_playlist`**: `video_id → videos, playlist_id text (no FK), channel_id, window_start, window_end, views bigint, unique(video_id, playlist_id, window_start, window_end)`. Nothing populates it (tier-2 disabled).
- **`audit_strategies`**: `version text pk, prompt_template text not null, model text not null, config jsonb, status text default 'challenger', notes, created_at`. Seed row: `('2026.07-baseline-v1', 'code:app/audits.py DEFAULT_PROMPT + audit_configs.generated_prompt (per-channel)', 'anthropic/claude-haiku-4.5', 'champion', …)`.
- **Other tables (not in the three specs):** `audit_configs` (`raw_insights, generated_prompt, shorts_prompt, niche_queries jsonb, reflection_mode default 'shadow'`), `prompt_versions`, `threshold_history`, `video_embeddings` (`vector(3072)`), `playlist_assignments`, `playlist_proposals`, `video_keyframes`, `video_transcripts`, `quota_log`, `shorts_jobs`, `shorts_clips`. SQL functions: `dashboard_summary()`, `playlist_video_sims()`, `discover_orphan_clusters()`, `next_audit_candidate()`.

**Spec'd tables and columns that do NOT exist:**
- `playlist_interventions` (the whole table)
- `channels.playbook_json`, `playbook_built_at`, `playbook_outcome_count`
- `channels.playlist_playbook_json`, `playlist_playbook_built_at`
- `channels.playlist_competitor_reference_json`, `playlist_competitor_built_at`
- `channels.playlist_optimizer_enabled`
- `video_metrics.avg_view_duration_sec FLOAT` (stored as `integer`); `playlist_metrics.avg_time_in_playlist_min FLOAT` (renamed to `_sec integer`)

---

## 3. Config — verbatim

Defaults from `app/config.py`. Values in the local `.env` (dev machine) are noted where they
override. The office machine's `.env` is hand-carried and was not read.

| Setting | Actual value (`app/config.py`) | Spec value | Differs? |
|---|---|---|---|
| `SCOPES` | `youtube`, `youtube.readonly`, `yt-analytics.readonly` | `youtube` + add `yt-analytics.readonly` | adds `youtube.readonly` |
| `MEASUREMENT_ENABLED` | not an env setting; per-channel `channels.measurement_enabled` (default false) | per-channel | no |
| `MEASUREMENT_WINDOW_DAYS` | `int(os.getenv("MEASUREMENT_WINDOW_DAYS") or "21")` | 21 | no |
| `MIN_IMPRESSIONS` | `or "500"` | 500 | no |
| `CTR_WIN_THRESHOLD` | `float(… or "0.10")` | +0.10 | no |
| `CTR_REGRESSION_THRESHOLD` | `float(… or "-0.10")` | -0.10 | no |
| `MAX_REDO` | `or "2"` | 2 | value same, **never read** |
| `AUTO_REVERT_ON_REGRESSION` | `os.getenv(…, "false")` | false | value same, **never read** |
| `PLAYBOOK_ENABLED` / `MIN_OUTCOMES_FOR_PLAYBOOK` / `PLAYBOOK_REFRESH_DELTA` / `PLAYBOOK_MAX_EXEMPLARS` | absent | per-channel / 15 / 10 / 10 | **absent** |
| `CHALLENGER_TRAFFIC_PCT` / `MIN_OUTCOMES_FOR_PROMOTION` / `PROMOTION_MARGIN` / `EVAL_HELDOUT_SIZE` | absent | 0.20 / 30 / +0.05 / 50 | **absent** |
| `PLAYLIST_OPTIMIZER_ENABLED` | absent | per-channel | **absent** |
| `PLAYLIST_MEASUREMENT_WINDOW_DAYS` | `or "35"` | 35 | value same, **never read** (only `app/config.py:166`); health uses `PLAYLIST_HEALTH_AGG_WEEKS` |
| `MIN_PLAYLIST_STARTS` | `or "50"` | 50 | no |
| `COMPETITOR_REFRESH_DAYS` / `COMPETITOR_DISCOVERY_QUOTA_BUDGET` / `COMPETITOR_MIN_SUBSCRIBER_MULTIPLE` | absent | 90 / 2000 / 3 | **absent** |
| `MAX_NEW_PLAYLISTS_PER_WINDOW` | absent; hardcoded `MAX_NEW_PLAYLISTS = 2` per weekly run (`app/playlist_discovery.py:20`) | 3 per window | **differs** |
| `PLAYLIST_AUTO_DELETE` | absent (no delete path exists) | false | absent |
| `PLAYLIST_CHALLENGER_PCT` | absent | 0.20 | **absent** |
| `PLAYLIST_DISCOVERY_ENABLED` | `os.getenv("PLAYLIST_DISCOVERY_ENABLED", "false").lower() == "true"` | false (`docs/superpowers/specs/2026-09-23-midas-implementation-spec.md` A4) | no |
| `PLAYLIST_RECONCILE_WRITES_ENABLED` | `os.getenv("PLAYLIST_RECONCILE_WRITES_ENABLED", "false").lower() == "true"` | false (`docs/superpowers/specs/2026-09-23-midas-implementation-spec.md` A4) | no |
| `PLAYLIST_TUNING_ENABLED` | `os.getenv("PLAYLIST_TUNING_ENABLED", "false").lower() == "true"` | false (`docs/superpowers/specs/2026-09-23-midas-implementation-spec.md` A4) | no |
| `REFLECTION_ENABLED` | `os.getenv("REFLECTION_ENABLED", "false").lower() == "true"` | false (`docs/superpowers/specs/2026-09-23-midas-implementation-spec.md` A4) | no |
| `AUDIT_MODEL` | `os.getenv("AUDIT_MODEL") or "anthropic/claude-haiku-4.5"`; **local .env: `google/gemini-3.7-flash`** | (not spec'd) | — |

**Settings in code with no spec home** (verbatim defaults):
```
PROMPT_GEN_MODEL = "google/gemini-2.0-flash-001"      # local .env: anthropic/claude-opus-5:online
REFLECTION_MODEL = "anthropic/claude-sonnet-4-6"      # local .env: anthropic/claude-sonnet-5
OTEL_ENABLED=false  OTEL_ENDPOINT="http://phoenix:6006/v1/traces"  OTEL_SERVICE_NAME="midas"
DRY_RUN = false (default!)   YT_DAILY_QUOTA=10000  YT_QUOTA_SAFETY_BUFFER=300  YT_QUOTA_APPLY_RESERVE=1500
AUTOPILOT_TICK_SECONDS=120 (local .env 100; office .env 30, observed 2026-09-29)  AUTOPILOT_PICKER_USE_RPC=false (local .env true)
AUTOPILOT_PAUSE_COOLDOWN_MINUTES=60
SHORTS_MAX_CONCURRENT_JOBS=2  SHORTS_DISPATCH_INTERVAL_SECONDS=5  SHORTS_YT_DOWNLOAD_ENABLED=false
SHORTS_MAX_SOURCE_SECONDS=300  SHORTS_CACHE_DIR  LOG_DIR  LOG_LEVEL
YOUTUBE_PROXY_URL  WEBSHARE_PROXY_USERNAME/PASSWORD
PLAYLIST_HITL=true  PLAYLIST_JOIN_HIGH=0.72  PLAYLIST_JOIN_LOW=0.55  PLAYLIST_LEAVE=0.60  PLAYLIST_MUTATION_CAP=20
PLAYLIST_SIMS_USE_RPC=false (local .env true)  PLAYLIST_DISCOVERY_USE_RPC=false (local .env true)
PLAYLIST_RECONCILE_CHANNELS = the four channel ids in §1 ("*" = all)
PLAYLIST_SYNC_QUOTA_BUDGET=2000  PLAYLIST_FULL_WALK_DAYS=30
PLAYLIST_HEALTH_AGG_WEEKS=4  PLAYLIST_HEALTH_REMOVE_PCTL=5  PLAYLIST_HEALTH_REVIVE_PCTL=20
DASHBOARD_USE_RPC=true  MEASUREMENT_COVERAGE_GRACE_DAYS=14  REACH_STALE_AFTER_DAYS=7
REPORTING_MEASURED_CHANNELS_ONLY=true  METRICS_POLL_MEASURED_ONLY=true
STRATEGY_LABEL = os.getenv("STRATEGY_LABEL") or "2026.07-baseline"   # prefix of the derived stamp <STRATEGY_LABEL>-<12 hex> over prompt sha256 + source (app/audits.py strategy_version, §6)
TRANSCRIPT_MAX_CHARS=8000  KEYFRAME_MAX_FRAMES=4  KEYFRAMES_LOCAL_DIR  KEYFRAME_FFMPEG_TIMEOUT=30
NAS_* (MODE=smb, AUTH_PROTOCOL=ntlm, SOURCE/DESTINATION roots, LOCAL_ROOT)
DATABASE_URL  BACKUP_ENABLED=true  BACKUP_HOUR=0  BACKUP_WORK_DIR  BACKUP_SLOTS=1 (local .env 2; CLAUDE.md says 2)
BACKUP_PG_DUMP="pg_dump"  RESTORE_ON_EMPTY=true  RESTORE_PSQL="psql"
```
Hardcoded constants that act like config: `reflection._MIN_DATA_POINTS=10`, `_NEGATIVE_MEDIAN_PCT=-2.0`,
`_NEGATIVE_LEVER_PCT=-5.0`, `_REFLECT_COOLDOWN_DAYS=7` (`app/reflection.py:47-52`), auto-revert
`>10pp` and `21 days` (`app/reflection.py:649,659`), `playlist_discovery.MIN_CLUSTER_SIZE=4`,
`CLUSTER_SIM_THRESHOLD=0.75`, `reach.ROLLOVER_SLOP_DAYS=1`, `analytics_client.ANALYTICS_DATA_LAG_DAYS=2`,
`metrics_poll.WINDOW_DAYS=7`.

**Settings spec'd but absent from `config.py`:** `PLAYBOOK_ENABLED`, `MIN_OUTCOMES_FOR_PLAYBOOK`,
`PLAYBOOK_REFRESH_DELTA`, `PLAYBOOK_MAX_EXEMPLARS`, `CHALLENGER_TRAFFIC_PCT`,
`MIN_OUTCOMES_FOR_PROMOTION`, `PROMOTION_MARGIN`, `EVAL_HELDOUT_SIZE`,
`PLAYLIST_OPTIMIZER_ENABLED`, `COMPETITOR_REFRESH_DAYS`, `COMPETITOR_DISCOVERY_QUOTA_BUDGET`,
`COMPETITOR_MIN_SUBSCRIBER_MULTIPLE`, `MAX_NEW_PLAYLISTS_PER_WINDOW`, `PLAYLIST_AUTO_DELETE`,
`PLAYLIST_CHALLENGER_PCT`.

---

## 4. Scheduled jobs

All registered in `app/main.py` `_register_jobs()`, called from `lifespan()` (`BackgroundScheduler`, `max_instances=1, coalesce=True`).

**Failure semantics.** Per-channel jobs (`playlist_reconcile`, `playlist_discovery`,
`playlist_tuning`, `reflection`, `playlist_health_score`) fan out through
`main._run_per_channel` (and so does `video_sync`). Channels stay isolated: each channel's exception is logged at ERROR
with traceback as `"<label> (job <job_id>) failed for <id>: <err>"` (`job_id` is the APScheduler id,
passed by each wrapper as `job_id=`, default `"-"`) and the loop continues. Once every channel
has run, any failure raises one `job_status.JobRunFailed` naming the failed channels, so
APScheduler records the run as failed (`app/main.py`, `app/job_status.py`). The three jobs outside
the fan-out raise the same exception. `poll_metrics` and `poll_reporting` collect each channel that
raised anything other than the expected skips (`AnalyticsNotAuthorizedError`, `TokenExpiredError`)
as `{channel_id: "<Type>: <message>"}` and raise `JobRunFailed("metrics_poll" | "reporting_poll", …)`
after the last channel; "no channels" returns normally. Per-item errors *inside* a channel's poll
are judged by `job_status.item_error_verdict` (`app/job_status.py:50`) per category, as
`{category: (errored, attempted)}`: videos, playlists and tier-2 for `metrics_poll`
(`_item_verdict`, `app/metrics_poll.py:351`); new reports for `reporting_poll`. If **every**
attempted item in a category errored, the channel fails the run as
`"ItemsFailed: <category>: all <n> failed"`. If only some did, the channel is recorded as partial
and the poll returns `{"partial_errors": {channel_id: "<category>: <e>/<n> failed; …"}}`
(`app/metrics_poll.py:421`, `app/reporting_poll.py:331`), which the registry turns into a
`degraded` run. Nothing attempted is neither. Both are called only by the scheduler. `measurement_eval` registers
`main._daily_measurement_eval`, which calls `measurement.evaluate_with_failures()` and raises
`JobRunFailed("measurement_eval", failed)` when any audit errored, keyed by channel id with the
audits in the message (`"audit <id>: <Type>: <message>; …"`; `unknown_channel` when the video row is
gone). `eval_measurements()` (what `POST /measurement/evaluate` returns) still returns only the summary,
whose `errors` is counted from the same per-channel record (`app/measurement.py:376-494`). In
`_daily_reconcile` a channel fails if either `sync_playlists` or `reconcile_channel` raised;
reconcile still runs after a failed sync. Its inner ERROR lines also carry the id:
`"Daily playlist sync (job playlist_reconcile) failed for <id>: <err>"` and
`"Daily reconcile (job playlist_reconcile) failed for <id>: <err>"`. After all `add_job` calls, `job_status.registry.watch(scheduler)`
registers every job as `never_run` and listens for `EVENT_JOB_EXECUTED | EVENT_JOB_ERROR`. It
records per job id `status` (`never_run|success|degraded|failed`), `last_run_at` (the event's
`scheduled_run_time`), `error`, `failed_channels` (`{channel_id: "<Type>: <message>"}`, taken
from the `JobRunFailed`), and `partial_errors` (taken from a successful run's return value when it
is a dict carrying `partial_errors`; non-empty → `degraded`). It logs failures as
`"JOB FAILED <job_id> at <time>: <error>"` and degraded runs as `"JOB DEGRADED <job_id> at <time>: …"`. The
registry is in-memory: a restart clears it. It is served at `GET /health/jobs` (§5).

**Freeze flags (A4).** Jobs are added by `main._register_jobs(sched)`, called from `lifespan()`.
Three writers register only when their flag is true; when it is false startup logs one line,
`"<job_id> not registered: <FLAG>=false"`, and the job never runs. `playlist_reconcile` always
registers; with its flag false `_daily_reconcile` runs `sync_playlists` and skips
`reconcile_channel` (so no `playlistItems.insert/delete` and no new proposals), logging
`"Daily reconcile <id>: add/remove skipped (PLAYLIST_RECONCILE_WRITES_ENABLED=false)"` per channel
(startup also logs `"playlist_reconcile registered for sync only: add/remove skipped
(PLAYLIST_RECONCILE_WRITES_ENABLED=false)"`). All four
flags default to false (§3), so on a default `.env` these writers are frozen.

| Job id | Trigger | Entry point | Status |
|---|---|---|---|
| `autopilot` | interval `AUTOPILOT_TICK_SECONDS` | `app/autopilot.py:tick`: at most one video per tick: quota-dormancy gate → pick channel → shorts action → ledger quota gate → audit → validate → ledger quota gate → apply → re-embed | registered; per-channel gated by `eligibility.can_audit` / `can_cut_shorts`. The ledger gate (`_can_afford_apply`: `quota.can_afford(quota.cost_of(*quota.APPLY))`) runs before the audit and again right before the write; on a no it logs `quota_insufficient`, sets `tick.outcome` to `"quota_insufficient"`, and skips the tick without pausing the channel or setting fleet dormancy |
| `shorts_dispatch` | interval 5s | `app/shorts/dispatcher.py:dispatch_tick` | registered |
| `playlist_reconcile` | cron 02:00 server-local | `main._daily_reconcile` → `sync_playlists` (budgeted) + `reconcile_channel` | registered; channel allowlist `PLAYLIST_RECONCILE_CHANNELS`. **Writes to YouTube** (`playlistItems.insert/delete`) or queues proposals when `PLAYLIST_HITL=true`. **Add/remove step frozen by `PLAYLIST_RECONCILE_WRITES_ENABLED`** (sync still runs) |
| `playlist_discovery` | cron Sun 03:00 local | `main._weekly_discovery` → `app/playlist_discovery.py:discover_playlists` | **frozen by `PLAYLIST_DISCOVERY_ENABLED`** (not registered when false). When on: **all channels** (`Job.EVERY`). **Creates playlists on YouTube** (≤2/run), skipped under DRY_RUN |
| `playlist_tuning` | cron Mon 03:30 local | `app/playlists.py:tune_thresholds` | **frozen by `PLAYLIST_TUNING_ENABLED`** (not registered when false). When on: all channels. Mutates `settings.PLAYLIST_JOIN_HIGH` **in-process, globally** from one channel's churn |
| `reflection` | cron Mon 04:00 local | `app/reflection.py:reflect` | **frozen by `REFLECTION_ENABLED`** (not registered when false). When on: all channels |
| `video_sync` | cron 04:00 UTC | `main._daily_video_sync` → `app/sync.py:routine_sync` per channel | registered, **all channels** (`Job.EVERY`), whatever autopilot is doing. Read-only against YouTube: skips a channel synced within `sync.SYNC_STALE_AFTER` (6 h), otherwise a full pass if `sync.needs_full_sync` (`FULL_SYNC_INTERVAL` = 3 days), else incremental + `refresh_stats`. An expired token is logged and skipped, not a failure. Added 2026-10-01: until then sync ran only inside autopilot's title-audit path (`_resync_if_stale`, after `can_audit`), so the ≈09-23 title pause stopped sync on every channel (last Marathi sync 2026-09-24 03:55 UTC, `docs/PHASE_A_FINDINGS.md` A1.1) |
| `metrics_poll` | cron 05:00 UTC | `app/metrics_poll.py:poll_metrics` | registered; `analytics_authorized` channels; videos only if in-measurement |
| `reporting_poll` | cron 06:00 UTC | `app/reporting_poll.py:poll_reporting` | registered; `analytics_authorized AND (measurement_enabled OR reach_warmup)` |
| `playlist_health_score` | cron 07:00 UTC | `main._daily_playlist_health_score` → `score_channel` | registered; `playlist_health_enabled` channels (NameError crash fixed in this commit; §1 1B) |
| `measurement_eval` | cron 08:00 UTC | `main._daily_measurement_eval` → `app/measurement.py:evaluate_with_failures` | registered; fails the run if any audit errored |
| `nightly_db_backup` | cron `BACKUP_HOUR` local | `app/backup.py:run_nightly_backup` | registered; no-op if `BACKUP_ENABLED=false` |
| `pot_provider_refresh` | interval 2h | `main._refresh_pot_provider` | **gated**: only if env `BGUTIL_POT_HTTP_BASE_URL` set |

Startup side effects: `provision.ensure_database_populated()` (restore from NAS if DB empty),
`shorts.runner.reap_stuck_jobs()`.

Not registered (spec'd): competitor refresh, playlist measurement eval, playbook rebuild (weekly), strategy eval.

---

## 5. Surface area

**Routes** (`app/main.py` mounts every router below):

- **Pages/health:** `GET /` → `static/index.html`; `GET /channel` → `static/channel.html`; `GET /health`; `GET /health/jobs` → `{"jobs": {<job_id>: {status, last_run_at, error, failed_channels, partial_errors}}}` from the in-process registry (`app/job_status.py`, §4); `GET /autoshorts` (`shorts/autoshorts.py`); `/static/*`.
- **Auth/channels** (`app/auth.py`, prefix `/auth` for login/callback): `GET /auth/login` starts OAuth. `GET /auth/callback` stores tokens, sets `analytics_authorized` from granted scopes, clears the `token_expired` pause. `GET /auth/channels` lists channels with flags. `PATCH /auth/channels/{id}` sets flags; enabling `measurement_enabled` returns 409 unless `reach.certify` passes.
- **Sync** (`app/sync.py`): `POST /channels/{id}/sync?full=`, `POST /channels/{id}/refresh-stats`, `POST /channels/{id}/refresh-applied-stats`, `GET /channels/{id}/videos`, `GET /videos/{id}`.
- **Audits** (`app/audits.py`): `GET|POST /channels/{id}/audit-config`, `POST /channels/{id}/audit-config/elaborate` (LLM builds prompt from notes), `POST /videos/{id}/audit`, `GET /videos/{id}/audits`, `POST /audits/{id}/apply`, `POST /channels/{id}/audits/apply-pending`, `POST /channels/{id}/audits/reaudit-quarantined`, `POST /channels/{id}/audits/run-bulk`, `POST /audits/{id}/revert` (409 `"quota_insufficient: revert needs 50 units, <n> remaining today"` when `quota.can_afford(quota.cost(Op.VIDEOS_UPDATE))` is false; no YouTube call), `GET /quota-cost-preview`.
- **Measurement** (`app/measurement.py`): `GET /audits/{id}/measurement`, `GET /channels/{id}/outcomes` (counts + `pending_review` regressions + 25 recent), `POST /measurement/evaluate` (manual run).
- **Reflection** (`app/reflection.py`): `GET /channels/{id}/reflection/history`, `POST /channels/{id}/prompt-versions/{vid}/promote`, `POST /channels/{id}/reflection/trigger`, `GET /channels/{id}/reflection/shadow-comparison`. Promote and trigger return 409 `"Reflection is frozen: REFLECTION_ENABLED=false"` while the flag is false (`_require_reflection_enabled`).
- **Playlists** (`app/playlists_router.py`): `POST /channels/{id}/playlists/evaluate` (runs the scorer), `GET /channels/{id}/playlists/health`, `POST /channels/{id}/playlists/bootstrap` (sync + embed all), `GET /channels/{id}/playlists/status`, `POST /channels/{id}/playlists/reconcile` (409 `"Playlist reconcile writes are frozen: PLAYLIST_RECONCILE_WRITES_ENABLED=false"` while that flag is false), `GET /channels/{id}/playlists/proposals`, `POST /channels/{id}/playlists/proposals/decide` (executes adds/removes on YouTube; not frozen, these are human decisions).
- **Autopilot** (`app/autopilot.py`): `POST /channels/{id}/autopilot/resume`, `GET /channels/{id}/autopilot/log`.
- **Ops** : `GET /dashboard` (`app/dashboard.py`, 30s cache, RPC-first), `GET /quota` (`app/quota.py`), `GET /channels/{id}/performance`, `/performance/summary`, `/performance.csv` (`app/performance.py`).
- **Shorts** (`app/shorts/routes.py`, prefix `/shorts`): `POST|GET /shorts/jobs`, `POST /shorts/cut`, `GET /shorts/languages`, `POST /shorts/jobs/clear-failed`, `GET /shorts/jobs/{id}`, `GET /shorts/clips/{id}/file`, `POST /shorts/clips/{id}/upload`, `POST /videos/{id}/short`, `POST /autoshorts/jobs`.

**Modules** (`app/`):

| File | Owns |
|---|---|
| `main.py` | FastAPI app, logging, scheduler registration, per-channel job fan-out |
| `job_status.py` | `JobRunFailed` + in-memory job-status registry (APScheduler listener) behind `/health/jobs` |
| `config.py` | `Settings` (env) |
| `db.py` | thread-local PostgREST (`supabase-py`) client with retry. The app talks to Postgres **only** via PostgREST on `SUPABASE_URL` |
| `rows.py` | the 1000-row cap: `all_rows`, `all_rows_parallel`, `rows_for_ids` |
| `channel_audits.py` | `audits_for_channel` join-scoped query. `fetch_all` is a **deprecated alias** of `rows.all_rows` |
| `eligibility.py` | which channels each job runs for (`Job.*`, `can_audit`, …) |
| `status_vocab.py` | persisted status strings (do not rename) |
| `auth.py` | OAuth + channel flag PATCH |
| `sync.py` | channel/video sync, `is_short` probe (`/shorts/` URL), stats refresh, and the routine-sync rules (`is_stale`, `needs_full_sync`, `routine_sync`) shared by the `video_sync` job and autopilot's `_resync_if_stale` |
| `content_type.py` | `is_episode` classifier (title/tag pattern) |
| `audits.py` | `DEFAULT_PROMPT`, `_build_user_block`, `audit_video`, apply, revert, bulk ops |
| `audit_suggestion.py` | LLM output contract: decode, 15-hashtag cap, validation, `house_format_spec()` |
| `apply_outcome.py` | typed `ApplyError`/`ApplyOutcome` |
| `youtube_metadata.py` | `videos.update` payload (category, language code, madeForKids). Content language → YouTube code via `_NON_ISO_639_1 = {"bgc": "hi"}` (`app/youtube_metadata.py:58-60`); unmapped codes pass through |
| `youtube_client.py` | Data API wrappers + quota charging |
| `quota.py` | unit-cost table, daily ledger, `JobBudget`, `/quota` |
| `analytics_client.py` | on-demand Analytics (views/retention, playlist session metrics) |
| `reporting_client.py` / `reporting_poll.py` | Reporting API job + CSV ingestion → `video_reach_daily`, `video_metrics` backfill |
| `reach.py` | data-day windows, coverage, frontier, staleness, `certify` |
| `metrics_poll.py` | Loop 0 daily poll |
| `measurement.py` / `verdicts.py` | Loop 1 verdicts; the `measurement_result` shape and rollups |
| `performance.py` | per-channel performance table/CSV (view deltas descriptive; verdicts from Loop 1) |
| `dashboard.py` | `/dashboard`. `_aggregate_legacy` is kept as fallback/oracle (duplicate of the SQL RPC by design) |
| `reflection.py` | weekly per-channel prompt rewrite (shadow/live/auto) + auto-revert |
| `transcripts.py` | transcript fetch + `video_transcripts` cache. Falls back to Data API captions (`captions.list` 50u + `captions.download` 200u) when IP-blocked |
| `embeddings.py` / `openrouter.py` | embeddings (`google/gemini-embedding-2-preview`) and `chat_json`/`chat_text` via OpenRouter |
| `playlists.py` | similarity assignment engine: `join_pass` (**unused**, call commented out), `reconcile_channel`, `tune_thresholds` |
| `playlists_sync.py` | playlist inventory sync, budgeted membership walk, role heuristic |
| `playlist_discovery.py` | weekly orphan clustering → **creates** playlists |
| `playlist_health.py` | Phase 1B scorer (recommend-only; tier-1 score) |
| `playlists_router.py` | playlist HTTP endpoints |
| `autopilot.py` | the tick loop |
| `tracing.py` | OpenTelemetry → Phoenix spans (off by default) |
| `backup.py` / `provision.py` / `services/nas_service.py` | NAS snapshot, restore-on-empty, SMB client |
| `keyframes.py` | **dead**: not imported anywhere ("reserved for thumbnail generation (Block D)", `app/audits.py:23-25`) |
| `shorts/*` | shorts cutter (NAS source), dispatcher, worker, upload. `shorts/cutter/download.py` is gated off (`SHORTS_YT_DOWNLOAD_ENABLED=false`) |
| `static/*` | vanilla-JS dashboard (`index.html`, `channel.html`, `autoshorts.html`, `theme.css`, …) |

---

## 6. Prompts and LLM calls

- **Audit prompt**: `app/audits.py:44` `DEFAULT_PROMPT`. It is used when the channel has no
  `audit_configs.generated_prompt`. Precedence is `prompt_override` > `shorts_prompt` (if is_short) >
  `generated_prompt` > `DEFAULT_PROMPT` (`app/audits.py:368-375`). **The per-channel
  `generated_prompt` (DB, possibly rewritten by reflection) is what actually runs on any channel that has one.
  Its current text lives in the DB, not the repo.** Verbatim `DEFAULT_PROMPT`:

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

  `house_format_spec()` (`app/audit_suggestion.py:49`), rendered with `TITLE_MAX=100`,
  `HASHTAG_LIMIT=15`, `TAGS_TOTAL_CHARS_MAX=500`, `TAGS_MAX=30`:

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
      "title":       { "current_problems": "...", "suggested": "your rewrite in the required title format", "why_better": "1-2 sentences" },
      "description": { "current_problems": "...", "suggested": "the FULL multi-line description following all 5 blocks above", "why_better": "..." },
      "tags":        { "current_problems": "...", "suggested": ["tag1","tag2",...], "why_better": "..." }
    },
    "issues":   [ { "field":"title|description|tags", "severity":"high|medium|low", "problem":"...", "fix":"..." } ],
    "reasoning": "short overall summary"
  }
  ```
  (The `current_problems` strings are elided above; they are the full sentences in the source.)

- **`_build_user_block()`**, verbatim (`app/audits.py:144-193`):

  ```python
  def _build_user_block(video, transcript, transcript_lang, channel_language) -> str:
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
          lines += ["", f"VIDEO TRANSCRIPT (detected language: {transcript_lang_name} — content signal only):", transcript]
      else:
          lines += ["", "VIDEO TRANSCRIPT: not available — base content judgment on metadata only."]
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
  - The `default_language` rule is injected as the **first block of the user message**. `DEFAULT_PROMPT`'s LANGUAGE section restates it in the system prompt. A missing `default_language` makes `audit_video` refuse with 400 instead of defaulting (`app/audits.py:390-402`), and `eligibility.can_audit` gates such channels out of autopilot.
  - Transcript language is labelled "content signal only" in both prompts. It is also persisted to `audits.transcript_lang` and used nowhere else in output selection. **Confirmed.**
  - The per-channel `generated_prompt` or a reflection candidate replaces the *system* prompt, but `_build_user_block` still carries the language rule, so the rule survives prompt rewrites.
  - The user block never includes CTR, impressions, or traffic-source data. It includes lifetime `view_count` and `like_count`.

- **Known SEO-prompt issues:**
  - *Hashtag cap*: **fixed and enforced in code.** `AuditSuggestion._make` calls `cap_description_hashtags` (`app/audit_suggestion.py:147`) on every construction path, including apply-time overrides (`from_fields`, `app/audits.py:507-516`). It keeps the first 15 (`HASHTAG_LIMIT = 15`, line 40), and its regex is Indic-safe (`#[^\s#]+`). The prompt asks for **exactly** 15, but code only enforces ≤15. `rejection()` does not check for too few.
  - *Search vs browse/suggested*: **not fixed.** The house format optimises for search: "keyword-rich sentences" (`audit_suggestion.py:74`), "high-value search phrases" (`:76`), a tag list maximised to ~500 chars (`:82`). Reflection's guidance query asks "what drives search discovery and click-through rate" (`app/reflection.py:349`). No prompt mentions browse, suggested, or packaging-for-CTR.
  - *No "no change recommended" option*: **not fixed for audits.** `DEFAULT_PROMPT` says "rewrite it to a FIXED house format", and the JSON schema has no no-op field. Every audit produces a rewrite, and autopilot applies any valid one. (Reflection *does* have a no-change output: an empty `candidate_prompt`, `app/reflection.py:497-520`.)
  - *Tag weighting*: **not addressed.** The only instruction is "A list mixing broad and specific tags … Maximize coverage up to ~500 characters". There is no ordering or weighting guidance. Validation checks only count ≤30 and total chars ≤500 (`rejection()`).

- **Other LLM calls** (all via OpenRouter, `app/openrouter.py`):

  | Call | Model | Path | Prompt location |
  |---|---|---|---|
  | Audit | `settings.AUDIT_MODEL` (chat_json default) | `audit_video` → `chat_json(user, system=audit_prompt)` | `app/audits.py:44,144` + DB `audit_configs` |
  | Prompt elaboration | `settings.PROMPT_GEN_MODEL` | `POST /audit-config/elaborate` | `app/audits.py:107-125` |
  | Niche queries | hardcoded `anthropic/claude-haiku-4.5` | reflection | `app/reflection.py:264-272` |
  | Platform guidance | hardcoded `perplexity/sonar` (`chat_text`, no JSON mode) | reflection | `app/reflection.py:346-352` |
  | Reflection candidate prompt | `settings.REFLECTION_MODEL` | reflection | `app/reflection.py:465-507` |
  | Playlist membership judge | hardcoded `JUDGE_MODEL = "anthropic/claude-haiku-4.5"` | reconcile (and dead `join_pass`) | `app/playlists.py:188-224` |
  | Playlist title/description proposal | hardcoded `anthropic/claude-haiku-4.5` | weekly discovery | `app/playlist_discovery.py:124-149` |
  | Embeddings | `EMBED_MODEL = "google/gemini-embedding-2-preview"` | embed on apply, bootstrap | `app/openrouter.py:7` |
  | Playbook distillation, thumbnail generation or validation, session re-ranking, competitor fit filter | **do not exist** | — | — |

  Playlist proposals ignore `default_language`: the proposal prompt (`playlist_discovery.py:136-141`) carries no language rule.

- **Models in use vs defaults.** Code defaults are `AUDIT_MODEL=anthropic/claude-haiku-4.5`, `PROMPT_GEN_MODEL=google/gemini-2.0-flash-001`, `REFLECTION_MODEL=anthropic/claude-sonnet-4-6`. The dev-machine `.env` sets `google/gemini-3.7-flash`, `anthropic/claude-opus-5:online`, and `anthropic/claude-sonnet-5`. **The office machine's `.env` was not read.** The strategy stamp now records the model actually in use. `app/audits.py` `strategy_version(prompt_text, prompt_source, prompt_version_id=None) -> (version, inputs)` returns `f"{settings.STRATEGY_LABEL}-{_strategy_hash(inputs)}"`, where `_strategy_hash` is the first 12 hex chars of sha256 over `json.dumps(inputs, sort_keys=True, separators=(",", ":"))` and `inputs` = `label`, `prompt_source` (one of `PROMPT_SOURCE_OVERRIDE = "override"`, `PROMPT_SOURCE_SHORTS = "shorts"`, `PROMPT_SOURCE_GENERATED = "generated"`, `PROMPT_SOURCE_DEFAULT = "default"`; anything else raises `ValueError`), `prompt_sha256` (sha256 of the system prompt text actually passed to `chat_json`; the text itself is never stored), `audit_model` (`settings.AUDIT_MODEL`), `decision_question_set_version` (placeholder `DECISION_QUESTION_SET_VERSION = "none"`), `prompt_version_id` (the audit's own), plus `writer_model` only if a `WRITER_MODEL` setting exists (it doesn't yet). `audit_video` picks `(audit_prompt, prompt_source)` in its precedence order (§6 above) and calls `_stamp_strategy(audit_prompt, prompt_source, prompt_version_id)` right before the insert: it upserts `{version, prompt_template, model: settings.AUDIT_MODEL, config: inputs, status: "champion", notes}`, where `prompt_template` names the source (`_PROMPT_SOURCE_TEMPLATES`: `"audit_video prompt_override (caller-supplied, e.g. reflection shadow candidate)"`, `"audit_configs.shorts_prompt (per-channel)"`, `"audit_configs.generated_prompt (per-channel)"`, `"code:app/audits.py DEFAULT_PROMPT"`), with `ignore_duplicates=True`, once per version per process (`_strategy_rows_ensured`). So an `AUDIT_MODEL` swap yields a new version and a new row. The `2026.07-baseline-v1` seed row (model `anthropic/claude-haiku-4.5`) is left in place for history; nothing stamps it any more. A change to the prompt text, its source, or the model gives a new version and a new row (§7.3 #6).

---

## 7. Delta vs the specs

### 7.1 Spec'd but not built

**Phase 0**
- CIL §0.2 `videoThumbnailImpressions*` via `reports.query`: impossible on the live API (Gap 1). Replaced by the Reporting API (see 7.3).
- CIL §0.4 "for each video currently under measurement": built. The v0 "every public video" wide net is now off by default.
- PO §Sensor traffic-source=PLAYLIST member breakdown: the code is built but disabled (`TIER2_TRAFFIC_SOURCE_SUPPORTED=False`). The table exists but stays empty. The Reporting-API replacement probe is in progress (Gap 6). `channel_traffic_source_a2` is retired (404 on 2026-09-29). Jobs for `channel_traffic_source_a3` and `playlist_traffic_source_a2` were created on the probe channel on 2026-09-29 with `scripts/create_reporting_job.py --report-type <id>`, and no report has been inspected yet; `scripts/probes/probe_traffic_source_report.py` / `scripts/probes/probe_traffic_source_analytics.py` read it; commands and answer slots are in `docs/PHASE_A_FINDINGS.md`.
- Phase 0 exit gate ("≥1 week trustworthy CTR on one channel"): `PHASE_0_GAPS.md` Gap 1 still reads "CLOSING … exit gate pending". The live gate state is unverified here.

**Phase 1A**
- CIL §1.5 auto-revert on regression: not built. `AUTO_REVERT_ON_REGRESSION` is never read. Manual revert exists (`app/audits.py` `revert_audit`).
- CIL §1.6 redo: not built. There is no `POST /audits/{id}/redo`, no failure-context injection, and nothing reads `MAX_REDO`. Nothing writes `redo_of_audit_id` or `outcome_decision='redo_queued'`. `docs/PHASE_2_TRACK2_LOOP1_REDO.md` is still **DRAFT**.
- CIL §1.7 "include `redo_queued` audits as work items": not built. The "exclude awaiting_window/measuring" half is built, in both the SQL and in-app pickers.
- CIL §1.4 v2 two-proportion z-test: not built (v1 relative threshold only).
- CIL §1.2 warm-video targeting: see 7.3. Dormancy is detected only *after* the window, not at selection.
- CIL §1.7 "per-channel flag … one channel first": the flag exists. Whether rollout followed that cadence can't be verified from the repo.

**Phase 1B**
- The health scorer raised `NameError` from 2026-08-06 until this commit, so recommendations on the live DB haven't been refreshed since then. Fixed now; takes effect after deploy.
- The score uses tier-1 only (`avg_time_in_playlist_sec × views_per_playlist_start`). Tier-2 "playlist-source views to members" is not collected.
- The `topic_cluster` role is not classified.
- Nothing reads `PLAYLIST_MEASUREMENT_WINDOW_DAYS`. Health aggregates `PLAYLIST_HEALTH_AGG_WEEKS=4` (28 days), not 35.

**Phase 2A: competitor research.** Nothing is built: no niche characterisation for playlists, no `search.list`→`channels.list` subscriber filter, no LLM fit/language filter, no harvesting of competitors' `playlists.list`, no distillation, no `playlist_competitor_reference_json`, no `COMPETITOR_*` config, no scheduled job, no sub-budget, no endpoints.

**Phase 2B: construction + intervention lifecycle.** Not built: no `playlist_interventions` table, no intervention stamping or pre-change baselines, no LLM session-continuation re-rank, no ordering or entry-point logic, no `default_language`-ruled playlist metadata, no `PLAYLIST_OPTIMIZER_ENABLED` flag, no `MAX_NEW_PLAYLISTS_PER_WINDOW`. Also missing: `POST /channels/{id}/playlists/build`, `/playlist-competitor-reference`, `/playlist-playbook`, `/playlist-interventions/{id}/measurement`, and `/playlist-interventions/{id}/confirm-delete`. (A similarity-only builder runs anyway; see 7.2.)

**Phase 2C: playlist self-eval.** Nothing is built.

**Phase 3A: metadata playbook.** No `app/playbook.py`, no `playbook_*` columns, no distiller prompt, no lazy rebuild, no cold-start floor, no "WHAT WORKS ON THIS CHANNEL" block in `_build_user_block`, no exemplars, no endpoints, no `PLAYBOOK_*` config.

**Phase 3B: playlist playbook.** Nothing is built.

**Phase 4: meta loops.**
- `audit_strategies` exists and audits are stamped. Nothing else is built: no challenger routing by id hash, no offline eval harness (`app/eval.py`), no different-family judge, no backtest, no promotion rule, no `/strategies*` endpoints, no `CHALLENGER_*`/`PROMOTION_*`/`EVAL_*` config.
- Playlists: `playlists.strategy_version` exists but is never written.

**Cross-cutting (plan §Cross-cutting)**
- "`default_language` survives everything": holds for audits and reflection (via `_build_user_block` + `house_format_spec`). **Violated** for playlist proposal titles and descriptions (`playlist_discovery._propose_playlist`) and the membership judge.
- "auto-delete default off": vacuously true, because no delete path exists. But `reconcile_channel` **removes** videos from playlists (LLM-confirmed, not human) when `PLAYLIST_HITL=false` and `PLAYLIST_RECONCILE_WRITES_ENABLED=true` (default false, §4).

### 7.2 Built but not spec'd

| Item | Where | Deliberate or drift |
|---|---|---|
| Reporting API reach pipeline (`video_reach_daily`, `reporting_reports_ingested`, `reach.py`, `certify`, `reach_warmup`) | `app/reporting_*.py`, `app/reach.py`, migrations `20260702174235`, `20260730000000` | **Deliberate**: the spec is stale. Recorded in `PHASE_0_GAPS.md` Gap 1 and `PHASE_2_TRACK1_METADATA_UNLOCK.md` (SHIPPED). |
| Per-channel prompt reflection loop: weekly LLM rewrite of `generated_prompt`, `prompt_versions` shadow/live/auto, shadow audits on 10 recent videos, auto-revert on cohort median | `app/reflection.py`, `prompt_versions` | **Pre-dates the specs** (migration 20260519). It has since been rewired to read Loop 1 verdicts. It occupies the design space of both Loop 2 (memory) and Loop 3 (strategy A/B) without being either. The specs don't mention it. `PHASE_2_TRACK4_MEMORY_META.md` (DRAFT) acknowledges it. |
| Similarity playlist engine: daily reconcile add/remove, `playlist_proposals` HITL queue, weekly `tune_thresholds`, weekly orphan-cluster **playlist creation** | `app/playlists.py`, `app/playlist_discovery.py` | Pre-dates the specs. PO says it should be "demoted to candidate generation" but it **still acts on YouTube** unmeasured. Drift. |
| Competitor sampling via `search.list` (200u per reflection) | `app/reflection.py:301-339` | Not in CIL. Uncapped by any competitor sub-budget. |
| Perplexity "platform guidance" web search injected into prompt rewrites | `app/reflection.py:344-355` | Not spec'd. Unmeasured external input into the prompt. |
| House-format contract as code (`AuditSuggestion`, quarantine on invalid) | `app/audit_suggestion.py` | Deliberate hardening. |
| Episode exclusion (`is_episode`) | `app/content_type.py`, migrations 20260904* | Deliberate (the SEO flow is for rhymes only). |
| Transcript cache + captions-API fallback (250u per video when IP-blocked) | `app/transcripts.py`, `video_transcripts` | Deliberate. The quota exposure isn't spec'd. |
| Shorts cutter (NAS source, parallel worker queue, autopilot shorts, upload) | `app/shorts/*`, 7 migrations | A separate product line with no home in the three docs. Specs live in `docs/superpowers/`. |
| Self-hosted Postgres + PostgREST, nightly NAS snapshot, restore-on-empty | `app/backup.py`, `app/provision.py`, `docker-compose.yml`, `docs/SELF_HOSTED_DB.md` | Deliberate infra (plan.md is silent). |
| Egress RPCs (`dashboard_summary`, `next_audit_candidate`, `playlist_video_sims`, `discover_orphan_clusters`) with in-app parity fallbacks | migrations 202607*, `app/dashboard.py`, `app/autopilot.py` | Deliberate (Supabase free-tier era). The duplicate Python paths are kept as oracles. |
| OTel/Phoenix tracing | `app/tracing.py`, `docs/OBSERVABILITY.md` | Deliberate. |
| Quota `JobBudget` + apply reserve | `app/quota.py`, `YT_QUOTA_APPLY_RESERVE` | Deliberate (reconcile starved applies on 2026-08-03/04, per migration `20260812000000` header). |
| Dead code: `app/keyframes.py`; `audits.keyframes_extracted`, `video_keyframes`, `videos.thumbnail_optimized_at`/`playlists_optimized_at`, `shorts_jobs.wayinvideo_project_id`; statuses `approved`/`rejected`; `playlists.join_pass` | various | Drift / reserved. |

### 7.3 Built differently from spec

1. **CTR source.** Spec: the Analytics API `reports.query`. Built: Reporting API daily CSVs aggregated over arbitrary windows (`reach.aggregate`, impression-weighted CTR). **The code is correct; the spec is stale.**
2. **Measurement windows.** Spec: a post window of `MEASUREMENT_WINDOW_DAYS` vs "N days before". Built: symmetric pre/post windows from `reach.window_for(applied)`. Each side excludes the apply day ±`ROLLOVER_SLOP_DAYS=1` (because of the LA-vs-UTC day rollover). **Code is correct.**
3. **Coverage failure → `not_applicable`, not `neutral`.** Spec §1.3 says insufficient data → neutral. Built: *post*-window impressions under the floor → `neutral` (matches spec), but lost reach coverage → `not_applicable` with `reason_code='coverage_lost'`, and the grace period runs in *ingested* time (`measurement.py:204-243`). **Code is correct.** It is a deliberate change, documented in the `measurement.py` docstring.
4. **Where dormancy is enforced.** Spec §1.2: at apply ("If the video had ~no impressions pre-change → not_applicable"), keeping dormant videos out of the loop. Built: the apply path stamps `awaiting_window` unconditionally on measurement-enabled channels. Dormancy is only discovered by `measurement_eval` **after** the post window closes. The picker selects **newest-published first** with no impressions filter (`next_audit_candidate`, `20260904000100…sql`: `order by v.published_at desc`). So dormant videos are audited and applied (and each spends ~50 Data API units), then block re-audit for ≥3 weeks. **Neither side is fully right.** The spec's intent (target warm videos) is unmet. This is the targeting problem.
5. **Loop 2 / Loop 3.** Spec: a per-channel playbook injected into the user block (data), plus fleet-level `audit_strategies` champion/challenger (machinery). Built: `reflection.py` rewrites the per-channel **system prompt** (so it mutates the strategy, not data). Candidates are tested by shadow audits that are never applied or measured. Promotion is manual or `auto` mode, not measured win-rate. Auto-revert compares cohort median CTR deltas per `prompt_version_id`. **The spec is the intended target.** `docs/superpowers/specs/2026-09-22-discoverability-agent-spec.md` (status line now "superseded by `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md`") proposed yet another direction, itself now superseded by that 09-23 spec; see 7.4.
6. **Strategy attribution.** Spec: stamp every audit with the strategy (prompt template + model + logic). Built (A6): a derived stamp, `<STRATEGY_LABEL>-<short hash>` over the sha256 of the system prompt text actually sent and its source (`override|shorts|generated|default`), the audit's `prompt_version_id` when present, `AUDIT_MODEL`, `WRITER_MODEL` if present, and a placeholder decision question-set version (`app/audits.py` `strategy_version`, §6). Each distinct version gets an `audit_strategies` row with the real `model` and `config` = the hashed inputs. The spec says "derive at startup", and names "`DEFAULT_PROMPT` text hash" as the prompt identity; built instead: the prompt is only known at audit time, so the stamp is derived per audit, and it hashes whichever prompt ran (#22), so shorts, override and unversioned `generated_prompt` audits no longer stamp the same as a `DEFAULT_PROMPT` audit. Every other input is fixed for the process. Audits stamped before A6 still carry `2026.07-baseline-v1`.
7. **Playlist construction.** Spec: embeddings for recall → LLM session re-rank → ordering → language-ruled metadata, measured as interventions. Built: centroid cosine ≥0.72 add, Haiku-confirmed removal <0.60, orphan clusters ≥4 at 0.75 → new playlist with a Haiku title. No ordering, no measurement, no provenance stamp (`origin` stays `inherited`). **The spec is correct.**
8. **Playlist health cadence and window.** Spec: `PLAYLIST_MEASUREMENT_WINDOW_DAYS=35` gate. Built: a 4-week aggregate plus per-channel percentile bands (remove ≤5th, revive ≤20th), a design from `PHASE_1B_PLAN.md`. Deliberate; the plan doc is the record.
9. **Apply cost.** `quota.APPLY = (VIDEOS_LIST, VIDEOS_UPDATE)` = 51u (`app/quota.py`), but `apply_audit_internal` no longer fetches stats (`app/audits.py:537-543`). The preview, `apply-pending` and autopilot (`_can_afford_apply`) gates overestimate by 1u per apply. Minor drift; left as-is (errs on the safe side).
10. **Metric storage units.** `avg_time_in_playlist_sec integer` (spec: `_min FLOAT`) and `avg_view_duration_sec integer` (spec: FLOAT). The live API returns integer seconds (Gap 3). **Code is correct.**

### 7.4 Contradictions between the specs

- **Build-order independence.** plan says 1A and 1B are "independent" and "build whichever channel is re-consented first". CIL and PO agree. The code followed this.
- **Playlist measurement window.** PO uses 35 days + `MIN_PLAYLIST_STARTS` for *interventions*. plan §1B reuses `MIN_PLAYLIST_STARTS` for *inventory health* but gives no window. The code resolved this with its own 4-week window (`PHASE_1B_PLAN.md`).
- **`MAX_NEW_PLAYLISTS_PER_WINDOW`.** PO sets it to 3 per channel with an undefined "window". The code uses a hardcoded 2 per weekly run, from the pre-spec discovery engine rather than either doc.
- **The competitor reference and the prompt loop.** PO's competitor research is a *playlist* input (requirement 2). CIL has no competitor input to audits at all. The code's only competitor research feeds the *metadata prompt* (reflection), which contradicts both specs' separation of measured from inferred inputs.
- **CIL §1.4 vs §1.3 on insufficient data.** §1.3 says "insufficient impressions even after the window → neutral". §1.4's table implies all non-win/non-regression is neutral. Neither covers lost ingestion. The code split this into post-floor→neutral and coverage-lost→not_applicable.
- **The newer direction supersedes all three docs on scope and clock.** All three, and the 09-22 spec below, are now superseded by `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md` (their banners and status line say so). `docs/superpowers/specs/2026-09-22-discoverability-agent-spec.md` (status line: "superseded by `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md` (2026-09-23); kept for history") replaces the 21-day/months-to-playbook clock with a weekly leading-indicator loop. It scopes an agent across three levers: metadata, description backlinks, and playlist placement via `playlistItems.insert`, behind a new `channels.agent_enabled`. It also moves playlists from "second action type measured at 5 weeks" to a per-video placement lever. **None of it is built** (no `agent_enabled` column, no LangGraph dependency in `requirements*.txt`). It conflicts with plan's phase ordering (Phases 3–4 would be superseded, not sequenced). The code today follows plan/CIL/PO through Phase 1. The 09-22 spec's §0.5 records two dissents it left unresolved: revert LangGraph → hand-rolled loop, and cut the paid `search_competitors` tool from v1 (that doc keeps both, per an explicit user override). The 09-23 spec resolves both the other way under "Resolved dissents (decided 2026-09-23)": item 6 "**LangGraph: out.**" and item 7 "**`search_competitors`: out of v1.**" (Part 2 §0.5).

---

## 8. Operational reality

The live DB was unreachable (see caveat), so live counts are blank. Figures below come from the repo and are labelled with their source.

- **Outcome volume**
  - Live win / neutral / regression / awaiting_window / measuring / not_applicable counts: blank. Run the SQL below.
  - Recorded 2026-08-23 (`app/reflection.py:32-34`): *"171 verdicts … 147 neutral / 21 win / 3 regression, a win rate of 12.3%."*
  - Recorded in `app/measurement.py:162-165,359-361`: an investigation found *"381 dormant, of which 184 published inside their own pre-window"*, and dormant was *"381 of 381"* of the `not_applicable` verdicts on the measure path. This is the targeting ratio (7.3 #4).
  - Recorded 2026-08-23 (`app/audits.py:315-319`): 57 applies in a month on the one autopilot channel. None were measured, because `measurement_enabled` was off there.
  - Dev-machine logs (`logs/midas.log.2`, 2026-07-14 → 07-28): `measurement_eval: {'evaluated': 557, 'errors': 0, 'awaiting_window': 557}`, unchanged across that span.
  - Reflection: *"five candidate prompts, none promoted"* from 2026-05 onward (`app/reflection.py:35-37`).
- **Sensor health**
  - **CTR arrives only via Reporting API CSVs**, 1–6 days late (`app/config.py:193-194`, 2026-07-02 probe).
  - The metric-name probe **failed** as spec'd: `videoThumbnailImpressions*` return 400 on `reports.query` (Gap 1). Retention and playlist metrics pass. Types are integer seconds (Gap 3).
  - The **`isCurated` probe returned 400**: the deprecation is final, and the filter is not used (Gap 2).
  - Tier-2 playlist traffic-source returns **400 "The query is not supported."** (Gap 6, 2026-07-02).
  - Current reach frontier and staleness per channel: blank. `measurement_eval` logs `reach_stalled_channels` when a channel is more than `REACH_STALE_AFTER_DAYS=7` behind.
  - Open: Gap 10 (~12.5% transient DNS failures on first poll) and Gap 5 (no FK on `playlist_metrics.playlist_id`).
- **Quota**
  - Typical daily Data API burn: blank.
  - Recorded: the playlist reconcile alone consumed *"8.5k-9.2k of the 10k/day"* on 2026-08-03/04 and starved applies (`20260812000000_playlist_membership_walked_at.sql` header). It is now capped at `PLAYLIST_SYNC_QUOTA_BUDGET=2000` with a 1500u apply reserve.
  - Earlier: *"~8k units/day fleet-wide"* for the reconcile (`app/config.py:128-131`).
  - Autopilot checks the quota ledger before the audit and before the apply (`_can_afford_apply`, `app/autopilot.py`); a no skips the tick with `quota_insufficient` and pauses nothing. A real YouTube `quotaExceeded` still makes the whole fleet dormant until the Pacific reset (the Data API quota is project-wide), logged as `"YouTube quotaExceeded: the Data API quota is project-wide, so autopilot is dormant fleet-wide (every channel, not just %s) until %s"`. A ledger skip at the second gate (after the audit) leaves that audit `pending`, which the picker excludes (`AUDIT_PICKER_SKIP_STATUSES`, `app/status_vocab.py`); it waits for `apply-pending`, as a quotaExceeded apply already did (`app/audits.py`).
  - Shorts uploads (`videos.insert` via `upload_short`, `app/shorts/youtube_upload.py`) are not reached from the autopilot tick: `_run_shorts_action` only inserts `shorts_jobs` rows, and the upload runs in the worker subprocess that `shorts_dispatch` spawns (`app/shorts/dispatcher.py`, `app/shorts/runner.py`). They have no `quota.can_afford` gate and no `Op` in `quota.UNIT_COST`, so they are not charged to the ledger.
- **Failures**
  - `playlist_health_score` raised `NameError: name 'METRIC_ROW_PAGE' is not defined` daily from `b355f40` (2026-08-06) until this commit (`logs/midas.log*`). APScheduler logged it as "executed successfully" because `_run_per_channel` caught per-channel exceptions and returned normally. That silent-failure pattern applied to every `_run_per_channel` job until A8: it now raises `JobRunFailed` after the fan-out, and `GET /health/jobs` shows each job's last status and failed channels (§4). `metrics_poll`, `reporting_poll` and `measurement_eval` now end failed too: a channel that crashes either poll, or any audit that errors in the measurement pass, raises `JobRunFailed` after the pass (§4), so `/health/jobs` lists the failing channels (and, for measurement, the audit ids). Per-item errors inside a channel's poll (`videos_err`, `tier2_err`, `playlists_err`, `reports_err`) now count too: a category where every item errored fails the channel, and some-but-not-all marks the run `degraded` with the counts (§4). A trickle of per-item errors is expected (deleted or privacy-flipped videos, Gap 10's transient DNS), which is why a partial error degrades the run rather than failing it.
  - `join_pass` is disabled, so applied videos are no longer placed into playlists (`app/autopilot.py:455`).
  - Quarantine count: blank (the `/dashboard` `quarantined_count` has it live).
  - `threshold_history` tuning writes one channel's FPR into the **process-global** `settings.PLAYLIST_JOIN_HIGH` (`app/playlists.py:tune_thresholds`), so the last channel tuned sets the threshold for all of them until restart.
- **Surprises vs spec assumptions**
  1. Neutral dominates (86% of verdicts on 2026-08-23), so a win-rate trigger or a "win-rate > champion" promotion rule is structurally uninformative.
  2. Dormant videos are the bulk of `not_applicable`, and the picker keeps choosing them (newest-first, no warmth filter).
  3. The team reports seeing SEO impact in about a week (`2026-09-22-discoverability-agent-spec.md` §0). That contradicts CIL's "~3 weeks per outcome, playbook in months" clock.
  4. On-demand Analytics exposes no CTR at all. The whole CTR pipeline rests on an erratic, out-of-order bulk CSV feed.

**SQL to fill the blanks** (run on the office machine against `midas`, e.g. `docker compose exec db psql -U midas midas`):

```sql
-- channels live
select id, name, default_language, analytics_authorized, measurement_enabled, reach_warmup,
       playlist_health_enabled, autopilot_enabled, autopilot_paused_reason, autopilot_shorts_enabled
from channels order by name;

-- outcome volume + dormancy ratio
select measurement_status, measurement_result->>'reason_code' as reason, count(*)
from audits where status in ('applied','reverted') group by 1,2 order by 1,2;

-- per-channel outcomes
select v.channel_id, a.measurement_status, count(*)
from audits a join videos v on v.id=a.video_id
where a.measurement_status <> 'not_applicable' group by 1,2 order by 1,2;

-- reach frontier per channel
select channel_id, max(data_date) frontier, count(*) days_covered
from reporting_reports_ingested group by 1;

-- daily Data API burn, last 30 days
select date_trunc('day', occurred_at) d, sum(units) units, count(*) filter (where not success) failures
from quota_log where units > 0 and occurred_at > now() - interval '30 days' group by 1 order by 1;

-- quarantine + prompt versions
select status, count(*) from audits group by 1;
select channel_id, status, count(*) from prompt_versions group by 1,2;

-- playlist health freshness (stale until the fixed scorer deploys and runs)
select channel_id, max(health_computed_at), count(*) filter (where health_recommendation is not null)
from playlists group by 1;
```

---

## 9. Regeneration prompt

Run in Claude Code at the repo root:

> Read this repo and rewrite `STATE.md` in place, keeping its exact section structure.
> Rules: every claim must be verifiable from a file in this repo, cited by path; if you
> can't verify it, leave the field blank rather than inferring it. Do not summarise the
> spec docs — read `CONTINUOUS_IMPROVEMENT_LOOP.md`, `PLAYLIST_OPTIMIZATION.md` and
> `plan.md` only to compute §7. For §7 be exhaustive and uncharitable: list every
> spec'd-but-not-built item including partial implementations, every built-but-not-spec'd
> item, and every substantive divergence. Paste config values, prompt text and DDL
> verbatim rather than describing them. For §8, query the database for the actual counts.
