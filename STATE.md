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

**Generated:** 2026-10-30 (Slice 3 built: #115–#120 on the stacked `slice-3/*` branches, not merged or deployed; final-review fixes: `titles.path_closed` (`a1c3d3c`: a path with no share, `TITLE_AGENT_PCT` 0 for the agent or 1 for the pipeline, counts as closed, so a pipeline stop closes the lever instead of handing titles to the agent), stale citations and sentences corrected; no migration). Earlier: 2026-10-30 (Slice 3 S3.5 #120: the weekly `lever_measurement` job measures `midas` `title` rows (`app/title_measurement.py` `measure_channel`: treated `measuring`, `holdout`, agent `declined`; pre d0−14 … d0−1, post d0+1 … d0+`TITLE_WINDOW_DAYS`, Pacific d0; browse (3) + suggested (7) views, `delta` = ln((post + 1) / (pre + 1)); pre under `TITLE_MIN_PRE_VIEWS` → `insufficient_data`; impressions and CTR recorded), writes `lever = 'title'` verdicts per path (`lever_verdicts.title_verdicts`, `arm_scope` `pipeline_vs_holdout`/`agent_vs_holdout`, the holdout shared, agent declines in the agent mean, stop at `TITLE_EXPERIMENT_WINDOWS` below `TITLE_MIN_LIFT` or at `TITLE_HARM_WINDOWS` at ≤ −`TITLE_HARM_LIFT`), puts back losing titles (`lever_verdicts.auto_revert`, `TITLE_REVERT_LIFT`, `TITLE_REVERTS_PER_DAY`, errors under `title reverts`); `titles.path_stopped` reads the triggered rows (`lever_verdicts.stopped(…, scope=)`); `GET /channels/{id}/title-test`; `TITLE_WINDOW_DAYS`, `TITLE_MIN_PRE_VIEWS`, `TITLE_MIN_LIFT`, `TITLE_EXPERIMENT_WINDOWS`, `TITLE_HARM_WINDOWS`, `TITLE_HARM_LIFT`, `TITLE_REVERT_LIFT`, `TITLE_REVERTS_PER_DAY`; migration `20261030010000` (a column comment only, not applied); a video is in the title experiment once: `warm_pool()` replaced by migration `20261030020000` (not applied) and `warm._holds` keep out any video with a `midas` `title` holdout row, or treated row unless `cancelled` before reaching YouTube, at any age). Earlier: 2026-10-30 (Slice 3 S3.4 #119: the agent path's treated titles are written by a hand-rolled tool-using agent, `app/agent/loop.py` `run_title_agent` → `AgentResult(kind, title, reason, trajectory)` (`title` → `planned` → `apply_title` as the pipeline; `decline` → `declined`, arm `treated`, `payload {path, title_before, rationale}`; `failed` → `cancelled`, `turn_cap` or `checks_failed`); `app/agent/tools.py` (`get_video`, `get_transcript`, `get_traffic_mix`, `get_search_terms`, `get_channel_top_performers`, `get_title_history`, `write_candidates`, terminal `submit_title`/`decline`); `openrouter.chat_tools`; `AGENT_MAX_TURNS`; `titles.AGENT_PROMPT`/`TITLE_BRIEF`, the agent's stamp hashing its own prompt and `agent_model`; `interventions.trajectory` in migration `20261030000000` (not applied), written through `interventions.record(trajectory=)` on every agent row; `scripts/preview_titles.py --path agent` runs the agent). Earlier: 2026-10-30 (Slice 3 S3.3 #118: the tick titles videos on `TITLE_CHANNELS` channels: `decide.TRIAGE`'s rules answer `title` after backlinks (`backlinks_enabled`, `title_enabled`, `title_excluded`, `channel_median_ctr`, `is_short` in the context), `QUESTION_SET_VERSION = "2026.11-s3-v1"`; `agent_tick._run_title` (holdout `{title_before}`; treated → `titles.route` → `titles.pipeline` on both paths → `planned` with `strategy_version` → `titles_apply.apply_title`, or `cancelled` `checks_failed`/`writer_exception`); `agent_tick.backlinks_enabled`, `titles_open`, `title_channel` (the title `ChannelContext` kept in `_pools` with the target pool), `_titles_today`; `titles.path_stopped` (always False until #120), `stopped`, `route`; `_agent_tick` returns `apply_disabled`/`no_heading` only when neither lever can run; `TITLE_CHANNELS`, `TITLE_DAILY_CAP`, `TITLE_AGENT_DAILY_RUNS`, `TITLE_EXCLUDE_VIDEOS`; `scripts/preview_titles.py` asks `TRIAGE.rules`; no migration). Earlier: 2026-10-30 (Slice 3 S3.6 #117: the autopilot tick's house-format title path deleted (`can_audit` → `TITLE_AUTOPILOT_ENABLED` → `audit_video` → validate → apply), with `TITLE_AUTOPILOT_DISABLED`, `_apply_audit_and_handle`, `APPLY_UNCLASSIFIED`, `_is_unsafe_model`/`UNSAFE_MODELS` and `_video_timeout_counts`; `TITLE_AUTOPILOT_ENABLED` removed from `app/config.py`; a channel with `agent_enabled` off gets the Shorts action only (`tick.outcome` `shorts_only`); the manual house-format applies (`POST /audits/{id}/apply`, `POST /channels/{id}/audits/apply-pending`) answer 409 `"agent channel: a house-format apply replaces the description and its backlink block; pass force=true"` on an `agent_enabled` channel unless `?force=true` (`audits._refuse_on_agent_channel`); no migration). Earlier: 2026-10-30 (Slice 3 S3.2 #116: `app/titles.py` (`channel_context`, `context`, `TITLE_PROMPT`, `write_candidates`, `check`/`SCRIPTS`, `pipeline`, `title_path`, `strategy_version`, `title_answers`, `preview`), `scripts/preview_titles.py`, `scripts/title_bakeoff.py`, `WRITER_MODEL` (= `AUDIT_MODEL`), `TITLE_CANDIDATES`, `TITLE_MAX_IMPRESSIONS`, `TITLE_AGENT_PCT`; the audit stamp no longer reads `WRITER_MODEL`; nothing in the tick calls the writer yet; no migration). Earlier: 2026-10-30 (Slice 3 S3.1 #115: `app/titles_apply.py` (`apply_title`, `revert_title`), the title-only snippet write and its revert, `POST /interventions/{id}/revert` dispatching applied `midas` `title` rows to `revert_title`, `TITLE_APPLY_ENABLED` (default false), `backlinks_apply._live_snippet`/`_send_snippet` split out of `_write_description`; nothing calls `apply_title` yet; no migration). Earlier: 2026-10-30 (spec Part 6, Slice 3, written and accepted (F1–F14): titles only, browse + suggested views vs holdout, pipeline vs agent; no code yet). Earlier: 2026-10-29 (office: Midas moved to a new office machine, restored from the NAS snapshot; backlinks switched on for English (14:04 UTC), Hindi and Bhojpuri (14:13 UTC), Gujarati (18:12 UTC) (`agent_enabled = autopilot_enabled = t`, `autopilot_daily_cap = 10`); Marathi's warm long-video pool is used up (the `warm_pool()` RPC returns 226 Shorts and no long video). Earlier: 2026-10-29 (backlink targets with the source's title, or a better target's, are left out (`backlinks.title_key`: hashtags, punctuation, case, spacing dropped), since the #s1-9 Hindi preview linked a video to three re-uploads of itself; a video triaged to `backlinks` whose block can't be rendered on the stored description (e.g. over 5,000 characters) is recorded `declined` with `triage_json.render_refused` before the arm is drawn (`agent_tick._unrenderable`), and the preview shows it as `no_change`; no migration). Earlier: 2026-10-29 (`backlinks.target_pool` (`Pool`: a source channel's `join_low`, eligible targets, their B6 vectors and warm impressions) and `candidates(video, pool=)`; the agent tick keeps each channel's pool for `agent_tick.POOL_TTL_SECONDS` (3600) in `_pool`, vectors as shared `array('d')`, since reading it per pick took minutes per video on channels with many siblings (the #s1-9 English preview: about an hour for 20 videos); no migration). Earlier: 2026-10-26 (STATE refresh: Slice 1 shown as live on Marathi everywhere, the #94 list of Slice 2 mismatches fixed (`interventions` writers, `decision_log` callers, `DecisionUsed` line, `added_by_midas` sources, `write_verdicts(lever=)`), `app/config.py` and `app/main.py` line citations updated). Earlier: 2026-10-26 (Slice 2 deployed at the office, #93 steps A1–E2: both Slice 2 migrations applied, image of 2026-10-26 04:46 UTC (#105, #106) running, Marathi's playlist test drawn (37 treated `planned`, 2 `no_dose`, 40 holdout; 151 adds approved, 14 rejected), `PLAYLIST_APPLY_ENABLED=true` in the office `.env`, Short-link recommendations written for 100 Marathi Shorts; Marathi `sync_shorts` was already on, 4,878 Shorts in `videos`, all with B6 vectors). Earlier: 2026-10-26 (`GET /channels/{id}/playlists/proposals` returns every pending proposal, paged past the 1,000-row cap, the playlist test's (`arm_id` set) first: the #93 D3 review found the test's 165 hidden behind the frozen engine's backlog; no migration). Earlier: 2026-10-26 (backlinks verdicts leave out rows whose video is a Short: `lever_verdicts._without_shorts`, called by `write_verdicts` for `lever = 'backlinks'` only; the A1 preflight of #93 found 44 treated, 11 holdout backlinks rows on Marathi Shorts from before #103; no migration). Earlier: 2026-10-26 (`warm.warm_pool`, the agent's pick, leaves out Shorts (`is_short` true; NULL stays in) on both the RPC and in-app paths, `_without_shorts`; `ranked_pool` and the `warm_pool()` SQL function unchanged; no migration). Earlier: 2026-10-26 (Slice 2 follow-ups from the final review: `decide_proposals` rejects only `pending` proposals; a Short's target set back after another records a new period under `short_link:<short>:<target>:<n>` (`app/short_links.py` `_episode_key`); the Short-links CSV escapes titles that start with `= + - @`). Earlier: 2026-10-26 (Slice 2 S2.6 #92: `app/short_links.py` `seen_pairs`/`detect` (type-32 pairs → `seen_at` and `human` `short_link` interventions, `timing: "inferred_from_traffic"`), called by the `lever_measurement` job before measuring on `TRAFFIC_INGEST_CHANNELS` channels under `short-link pairs`; `app/lever_measurement.py` measuring `short_link` rows on type 32 (`SOURCE_TYPES`, `source`, `pair_views(source_type=)`); `write_verdicts(lever=)` and `lever = 'short_link'` `human` verdict rows; `SHORT_LINK_SEEN_MIN_VIEWS`; the §8 shadow-agreement query; no migration). Earlier: 2026-10-26 (Slice 2 S2.5 #91: `app/short_links.py` `router` (`GET /channels/{id}/short-links`, `?format=csv`, `POST /short-links/{id}/set`, `POST /short-links/{id}/dismiss`), human `short_link` interventions with `ledger_key = short_link:<short>:<target>`, the "Short links" card on `app/static/channel.html`'s Playlists tab; no migration). Earlier: 2026-10-26 (Slice 2 S2.4 #90: `short_link_recommendations` in migration `20261027010000` (not applied), `app/short_links.py` (`shorts`, `targets`, `refresh`, `preview`, `run_weekly`), the weekly `short_link_refresh` job (Mon 10:30 UTC), `scripts/short_links.py`, `SHORT_LINK_CHANNELS`, `SHORT_LINK_TARGETS`, `SHORT_LINK_MIN_FEED_VIEWS`, `SHORT_LINK_MAX_PER_RUN`, `status_vocab.ShortLinkStatus`). Earlier: 2026-10-26 (Slice 2 S2.3 #89: `app/playlist_test.py` `measure_channel` (pre, post weeks, per-arm `measurement_result`, `lever = 'playlist'` rows in `lever_verdicts`), `GET /channels/{id}/playlist-test`, the `lever_measurement` job's `playlist arms` category, `lever_verdicts.verdicts`/`directional` taking the lever's thresholds, `PLAYLIST_EXPERIMENT_WINDOWS`, `PLAYLIST_MIN_LIFT`; no migration). Earlier: 2026-10-26 (Slice 2 S2.2 #88: `decide_proposals` only queues a proposal with `arm_id`, the daily `playlist_test_apply` job (11:00 UTC, `app/playlist_test.py` `run_apply`, `apply_channel`), `playlist_test.test_dates`, `yt_playlist_items_insert(position=)`, `PLAYLIST_APPLY_ENABLED`, `PLAYLIST_TEST_DAILY_UNITS`, `PLAYLIST_TEST_MAX_ATTEMPTS`; no migration). Earlier: 2026-10-26 (Slice 2 S2.1 #87: `playlist_arms` and four `playlist_proposals` columns in migration `20261027000000` (not applied), `app/playlist_test.py` (`eligible`, `survey`, `assign_arm`, `candidates`, `draw`, `preview`), `scripts/playlist_test.py`, `PLAYLIST_HOLDOUT_PCT`, `PLAYLIST_TEST_MAX_ADDS`, `status_vocab.PlaylistArm`/`PlaylistArmStatus`/`PlaylistArmMeasurement`/`PlaylistProposalSource`, `experiment` → "Playlist test" in `channel.html` `DECIDED_BY`). Earlier: 2026-10-26 (Slice 2 specified: spec Part 5, owner decisions E1–E13, tickets #87–#94; no code yet). Earlier: 2026-10-26 (fleet readiness #84/#85 deployed 2026-10-26; same day at the office: `reach_warmup = t` on Haryanvi, Rajasthani, 3D Animated, Kannada, Telugu, `TRAFFIC_INGEST_CHANNELS` = all 13 in the office `.env`, Hindi re-consented; Kannada and Telugu have no uploads on YouTube, owner). Earlier: 2026-10-25 (fleet readiness: backlink headings for every channel language in `backlinks.HEADINGS`, `YT_QUOTA_COLLECTION_RESERVE` on the autopilot apply gate, `app/channel_health.py` (`GET /health/channels`, the daily `channel_health` job), `video_sync` `degraded` on token skips; owner decisions 2026-10-25 in `docs/PLAN_TO_2026-11-27.md`). Earlier: 2026-10-25 (Slice 1 deployed and live on Marathi 2026-10-24: `BACKLINK_APPLY_ENABLED=true` in the office `.env`, Marathi `agent_enabled = autopilot_enabled = t`, `autopilot_daily_cap = 40`; Marathi re-consented 2026-10-24, Hindi, Bhojpuri, Punjabi tokens dead since 2026-10-16. Forward plan: `docs/PLAN_TO_2026-11-27.md`). Earlier: 2026-10-23 (#55: `client_max_body_size 16m` in `deploy/postgrest-proxy.conf`). Earlier: 2026-10-23 (Marathi backlink heading `आणखी गाणी पहा:` in `backlinks.HEADINGS`). Earlier: 2026-10-23 (Slice 1 review fixes: a treated `backlinks` row that never reached YouTube no longer uses up its video, the agent does nothing while `BACKLINK_APPLY_ENABLED` is off or the language has no heading, unsent treated attempts count toward the cap, `TITLE_AUTOPILOT_ENABLED`, `render`'s byte limit). Earlier: 2026-10-23 (Slice 1 S1.6b #68: `lever_verdicts` in migration `20261023010000` (not applied), `app/lever_verdicts.py` (`write_verdicts`, `run_weekly`, `GET /channels/{id}/interventions`, `GET /channels/{id}/lever-verdicts`), the weekly `lever_measurement` job (Mon 09:00 UTC), `agent_tick.backlinks_stopped` reading the stop rule, `BACKLINK_EXPERIMENT_WINDOWS`, `BACKLINK_MIN_LIFT`, `status_vocab.LeverVerdictScope`/`LeverVerdict`). Earlier: 2026-10-23 (Slice 1 S1.6a #67: `app/lever_measurement.py` `measure_channel`, pair measurement per backlinks intervention, not scheduled; `LEVER_MIN_SOURCE_VIEWS`; `status_vocab.InterventionMeasurement` for `interventions.measurement_status`). Earlier: 2026-10-23 (Slice 1 S1.5 #66: `decide.NEXT_WATCH`, asked in shadow per candidate pair by `app/agent_tick.py` `_next_watch` and stored as `triage_json.next_watch`, `backlinks.Candidates.join_low`, `QUESTION_SET_VERSION = "2026.10-s1-v2"`). Earlier: 2026-10-23 (Slice 1 S1.4b #65: the agent tick, `app/agent_tick.py` (`run`, `preview`, `backlinks_stopped`), `autopilot._agent_tick` behind `channels.agent_enabled`, `eligibility.can_run_agent`, `_applies_today` counting applied Midas interventions, `decide()` returning `log_id` and `decide.link`, the TRIAGE stop-rule input and `QUESTION_SET_VERSION = "2026.10-s1-v1"`, `scripts/preview_backlinks.py`). Earlier: 2026-10-23 (Slice 1 S1.3 #64: `app/backlinks_apply.py` `apply_backlinks` and `POST /interventions/{id}/revert`, `BACKLINK_APPLY_ENABLED`, `ApplyOutcome.QUOTA_INSUFFICIENT`/`APPLY_DISABLED`, `human_edits.made_by_midas` knows applied Midas blocks). Earlier: 2026-10-23 (Slice 1 S1.4a #63: `warm_pool()` replaced by `20261023000000`, cooldown and once-per-experiment exclusions in it and `app/warm.py`, `TRIAGE_COOLDOWN_DAYS`). Earlier: 2026-10-23 (Slice 1 S1.1 #62: `app/backlinks.py` `siblings`/`candidates`, `SIBLING_MIN_VIEWS`, `warm.warm_impressions`, `reach.coverage(report_type=)`). Earlier: 2026-10-23 (Slice 1 S1.2 #61: `app/backlinks.py`, `BACKLINK_MAX`). Earlier: 2026-10-13 (B10: Phase B deployed 2026-10-07/08 and its exit gate passed 2026-10-13, `docs/PHASE_B_FINDINGS.md`; #56, 2026-10-08: `youtube_client.channel_credentials`). Earlier: 2026-10-06 (full regeneration from §9; updated for B1a #30: `traffic_poll`, `video_traffic_source_daily`; B1b #31: `playlist_traffic_daily`; B8 #39: token failures skip in `video_sync`; B2 #32: `interventions`, `assign_arm`, `HOLDOUT_PCT`, `channels.agent_enabled`; B3a #33: `app/human_edits.py`, `interventions.ledger_key`; B3b #34: playlist-membership ledger in the walk; B4 #35: `app/warm.py`, `warm_pool()`, `WARM_*`; B5 #36: `app/decide.py`, `decision_log`, `DECIDE_BACKEND`, `BACKLINK_MIN_CANDIDATES`, the stamp's question-set version; B6 #37: `app/reembed.py`, `scripts/reembed.py`, `channels.playlist_thresholds`; B7 #38, 2026-10-07: `bho`/`raj` in `_LANG_NAMES` and `_NON_ISO_639_1`) · **Commit:** on top of `8c36352` · **Branch:** `slice-3/120-slice-3-s3-5-title-measurement-verdicts`
(Older design docs are deleted in the same change and live only in git history; nothing below cites them.
`scripts/overnight_tickets.sh` is dev tooling, never deployed.)

**The spec**, cited below as **spec**: `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md`. Its
status line: Part 1 (Phase A) done, exit gate passed 2026-10-06; Part 3 (Phase B) done, exit gate passed 2026-10-13;
Part 4 (Slice 1) built and live on Marathi; Part 5 (Slice 2) built and deployed on Marathi (2026-10-26); **Part 6 (Slice 3) "ready to build"** (2026-10-30, owner decisions F1–F14); Part 2
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
membership walk in `app/playlists_sync.py`; no migration) and B4 (#35: `app/warm.py`, the `warm_pool()` function in
migration `20261006040000`; picked from by Slice 1's agent tick since S1.4b, live on Marathi since 2026-10-24) and B5 (#36: `app/decide.py`, `decision_log` in migration
`20261006050000`; called since Slice 1 S1.4b by `app/agent_tick.py`, live on Marathi since 2026-10-24) and B6 (#37: `app/reembed.py`, run by `scripts/reembed.py`,
`channels.playlist_thresholds` in migration `20261006060000`; not run yet) and B7's code half (#38: `bho`/`raj` →
`hi`, `app/transcripts.py`, `app/youtube_metadata.py`; no channel uses them yet). **All of it is deployed** (B9a #40
2026-10-07: B1 + B8; B9b #41 2026-10-07/08: the other five migrations, the languages, the Marathi re-embed), and #56
(stored token expiry) since 2026-10-08. Live figures from the deploy are in `docs/PHASE_B_FINDINGS.md`.

**Data caveat for this generation.** The live database runs on the office machine, bound to
`127.0.0.1:55432` there (`docker-compose.yml:21-22`), so it can't be reached from the machine that generated
this file. Live figures below are quoted from `docs/PHASE_A_FINDINGS.md` and `docs/PHASE_B_FINDINGS.md`, each labelled with its date and
section; anything not recorded there is blank. §8 ends with the SQL to refresh them.

---

## 1. Phase status

Stages are the spec's build order (spec Part 2 §6).

| Stage | Theme | Status | Evidence (paths) | Notes |
|---|---|---|---|---|
| **Phase A** | Gates | **done** (exit gate passed 2026-10-06, spec status line) | A4: `app/config.py:121-123,34`, `app/main.py:335-377`, `tests/test_frozen_writers.py`. A5: `app/transcripts.py:25-31`, `app/youtube_metadata.py:58-59` (the `bgc` entries). A6: `app/audits.py:196-278`, `tests/test_strategy_version.py`. A8: `app/job_status.py`, `app/main.py:82-108,634-637`, `tests/test_main_fanout.py`. A10: `app/autopilot.py:450-466,515`, `app/audits.py:847-852`, `tests/test_revert_quota_gate.py`. Probes: `scripts/probes/*.py`. Record: `docs/PHASE_A_FINDINGS.md` | Every lever outcome (a) (findings "Phase A conclusion" §1). A5's `default_language = 'bgc'` was already set on Haryanvi (findings "Next session" item 5); the optional i18n probe was not run (A5 table blank). The findings "Exit gate" checklist ticks A11 with this §9-based regeneration (2026-10-06). |
| **Phase B** | Plumbing (spec Part 3, B1–B10) | **done** (exit gate passed 2026-10-13; deployed 2026-10-07/08; `docs/PHASE_B_FINDINGS.md`) | B1a/B1b: `app/traffic_poll.py`, `app/reporting_client.py` (`ensure_job`, `parse_traffic_csv`, `parse_playlist_traffic_csv`, `TRAFFIC_SOURCE_TYPES`), `app/reporting_poll.py` (`replace_data_day`, `record_ingested`), `supabase/migrations/20261006000000_video_traffic_source_daily.sql`, `supabase/migrations/20261006010000_playlist_traffic_daily.sql`, `tests/test_traffic_poll.py`, `tests/test_reporting_ingest.py`. B8: `app/sync.py:41-70` (`TokenExpired`, `_token_failure_as_401`), `tests/test_sync_token_expiry.py`. B2: `app/interventions.py` (`assign_arm`, `active_for`, `record`), `app/status_vocab.py:143-220` (`Intervention*`, `ACTIVE_INTERVENTION_STATUSES`), `supabase/migrations/20261006020000_interventions.sql`, `HOLDOUT_PCT` (`app/config.py:240`), `tests/test_interventions.py`. B3a: `app/human_edits.py` (`video_links`, `made_by_midas`, `record_description_edits`), `app/sync.py:143-153,262-265,288-297` (`_record_human_edits`), `interventions.record(ledger_key=…)`, `supabase/migrations/20261006030000_interventions_ledger_key.sql`, `tests/test_human_edits.py`. B3b: `app/human_edits.py` (`added_by_midas`, `record_playlist_additions`), `app/playlists_sync.py:297-328,359-368` (`_record_human_memberships`), `tests/test_human_edits_playlists.py`. B4: `app/warm.py` (`ranked_pool`, `explore_order`, `warm_pool`), `supabase/migrations/20261006040000_warm_pool_rpc.sql` (`warm_pool()`), `WARM_*` (`app/config.py:241-253`), `app/reach.py` (`certify_covered`, `window_length`), `tests/test_warm.py`, `tests/test_warm_pool_parity.py`, `tests/test_warm_pool_parity_live.py`. B5: `app/decide.py` (`decide`, `Decision`, `QuestionSet`, `TRIAGE`, `QUESTION_SET_VERSION`, `NotConfigured`), `supabase/migrations/20261006050000_decision_log.sql`, `DecisionUsed` (`app/status_vocab.py:370-377`), `DECIDE_BACKEND`, `BACKLINK_MIN_CANDIDATES` (`app/config.py:254-261`), `tests/test_decide.py`. B6: `app/reembed.py` (`recipe_text`, `MODEL_VERSION`, `estimate_channel`, `reembed_channel`, `calibrate_channel`), `scripts/reembed.py`, `supabase/migrations/20261006060000_channels_playlist_thresholds.sql`, `model_version` keyword on `app/embeddings.py` `pooled_embeddings`/`embedded_video_ids`, `tests/test_reembed.py`. B7 (code half): `bho`/`raj` in `_LANG_NAMES` (`app/transcripts.py:25-36`) and `_NON_ISO_639_1` (`app/youtube_metadata.py:58-64`), `tests/test_language_codes.py`, `tests/test_youtube_metadata.py` | In Phase B nothing called `decide()`, so `decision_log` got no rows; Slice 1's agent tick (S1.4b, `app/agent_tick.py`) is its first caller, live on Marathi since 2026-10-24; only the B3 human ledger writes `interventions` (`human` rows: backlinks on full syncs, playlist memberships on the membership walk); the warm filter is picked from only by S1.4b's agent tick (`app/agent_tick.py`; `tests/test_warm.py` guards that; S1.1's candidates use its `warm_impressions`); the B6 recipe's vectors and `channels.playlist_thresholds` are written only by the one-off `scripts/reembed.py` (run for Marathi 2026-10-07/08) and read in production only by S1.1's `backlinks.candidates`, called by S1.4b's agent tick on `agent_enabled` channels; the `bho`/`raj` entries are unused, since the owner chose plain `hi` for Bhojpuri and Rajasthani (2026-10-06, `app/youtube_metadata.py:60-61`) and they exist so those channels can switch later without a code change. Partial footholds listed in §7.1. |
| **Slice 1** | Backlinks + no change | **live on Marathi since 2026-10-24, and on English, Hindi, Bhojpuri and Gujarati since 2026-10-29** (deployed per `docs/agents/s1-7-office-steps.md`; first treated applies 07:38 UTC, interventions 187–195; exit gate pending: first weekly verdict, #70) | S1.1: `app/backlinks.py` (`siblings`, `candidates`, `Candidates`), `SIBLING_MIN_VIEWS` (`app/config.py:270`), `app/warm.py` `warm_impressions`, `tests/test_backlink_candidates.py`. S1.2: `app/backlinks.py` (`render`, `find`, `strip`, `HEADINGS`), `BACKLINK_MAX` (`app/config.py:265`), `tests/test_backlinks.py`. S1.4a: `supabase/migrations/20261023000000_warm_pool_agent_exclusions.sql` (`warm_pool()`), `app/warm.py` `_holds`, `TRIAGE_COOLDOWN_DAYS` (`app/config.py:275`), `tests/test_warm.py`, `tests/test_warm_pool_parity.py`. S1.3: `app/backlinks_apply.py` (`apply_backlinks`, `revert_intervention` = `POST /interventions/{id}/revert`), `BACKLINK_APPLY_ENABLED` (`app/config.py:279`), `ApplyOutcome.QUOTA_INSUFFICIENT`/`APPLY_DISABLED` (`app/apply_outcome.py`), `app/human_edits.py` `_midas_block`, `tests/test_backlinks_apply.py`. S1.4b: `app/agent_tick.py` (`run`, `preview`, `backlinks_stopped`), `app/autopilot.py` (`_agent_tick`, the `agent_enabled` branch in `tick`, `_applies_today`, `_react_to_apply_error`), `app/eligibility.py` `can_run_agent`, `app/decide.py` (`Decision.log_id`, `link`, `backlinks_stopped` in the TRIAGE rules), `scripts/preview_backlinks.py`, `tests/test_agent_tick.py`. S1.5: `app/decide.py` (`NEXT_WATCH`, `_next_watch_rules`), `app/agent_tick.py` `_next_watch`, `backlinks.Candidates.join_low`, `tests/test_decide.py`, `tests/test_agent_tick.py`. S1.6a: `app/lever_measurement.py` (`measure_channel`, `pair_views`, `windows`, `as_of`), `LEVER_MIN_SOURCE_VIEWS` (`app/config.py:341`), `InterventionMeasurement` (`app/status_vocab.py:223-244`), `tests/test_lever_measurement.py`. S1.6b: `supabase/migrations/20261023010000_lever_verdicts.sql`, `app/lever_verdicts.py` (`verdicts`, `write_verdicts`, `run_weekly`, the two read endpoints), the `lever_measurement` job (`app/main.py` `_register_jobs`), `app/agent_tick.py` `backlinks_stopped`, `BACKLINK_EXPERIMENT_WINDOWS`, `BACKLINK_MIN_LIFT` (`app/config.py:346,350`), `LeverVerdictScope`, `LeverVerdict` (`app/status_vocab.py:245-277`), `tests/test_lever_verdicts.py`, `tests/test_agent_tick.py` | Live on Marathi (`agent_enabled = autopilot_enabled = t`, `autopilot_daily_cap = 40`, D4) and, since 2026-10-29, English (14:04 UTC), Hindi and Bhojpuri (14:13 UTC) and Gujarati (18:12 UTC), `autopilot_daily_cap = 10` each; their headings (`en`, `hi`, `gu`) approved by native readers (owner, 2026-10-29). Marathi's warm long videos are used up (2026-10-29: the pool is 226 Shorts, 0 long videos; 93 long videos treated or held out), `BACKLINK_APPLY_ENABLED=true` in the office `.env`; `20261023000000` and `20261023010000` applied (both in `schema_migrations`, #93 A1, 2026-10-26). `backlinks.HEADINGS` has a heading for every channel language (Marathi's `आणखी गाणी पहा:` from the SEO team, the rest written by Claude and awaiting a native reader). While `BACKLINK_APPLY_ENABLED` is false or the language has no heading the agent does nothing (§3). Until the 2026-10-26 image (#103) the pick took Shorts: #93 A1 found 44 treated (`measuring`), 11 holdout, 51 declined and 1 cancelled `midas` backlinks rows on Marathi Shorts; the blocks stay (owner, not reverted) and since #105 those rows enter no verdict (`lever_verdicts._without_shorts`). Sibling targets appear only once the sibling channels have B6 vectors (B6 ran for Marathi only). The weekly `lever_measurement` job (Monday 09:00 UTC) writes the first verdict once treated and holdout rows are judged (expected 2026-11-02 or 11-09); the stop rule needs 3 windows. The next-watch question is asked in shadow per candidate pair; its rules answer is always `yes` there, since `candidates` keeps only pairs ≥ `join_low`. The tick has no house-format title path since S3.6 (#117: the branch is deleted, `app/autopilot.py` `tick`), the spec's precondition (spec Part 2 §6.1); since S3.3 (#118) triage may answer `title` after backlinks, on `TITLE_CHANNELS` channels while `TITLE_APPLY_ENABLED` is on (`TITLE_CHANNELS` defaults to Marathi, `app/config.py:299-303`; the switch defaults false, `app/config.py:283`, so no title is written by default). |
| **Slice 2** | Playlist test (P3) + Short links (P4) | **deployed on Marathi 2026-10-26** (spec Part 5; #93 runbook `docs/agents/s2-7-office-steps.md`, steps A1–E2 done: migrations applied, draw done (37 treated `planned` with 151 approved adds and 14 rejected, 2 `no_dose`, 40 holdout), `PLAYLIST_APPLY_ENABLED=true`, first adds at the 11:00 UTC run that day; 241 `pending` Short-link recommendations over 100 Shorts; D5 daily checks and F1 pending; #94 docs open) | S2.1: `supabase/migrations/20261027000000_playlist_arms.sql`, `app/playlist_test.py` (`survey`, `eligible`, `assign_arm`, `candidates`, `draw`, `preview`, `AlreadyDrawn`), `scripts/playlist_test.py`, `PLAYLIST_HOLDOUT_PCT`, `PLAYLIST_TEST_MAX_ADDS` (`app/config.py`), `PlaylistArm`, `PlaylistArmStatus`, `PlaylistArmMeasurement`, `PlaylistProposalSource` (`app/status_vocab.py`), `DECIDED_BY.experiment` (`app/static/channel.html`), `tests/test_playlist_test.py`, `tests/test_status_vocab.py`. S2.2: `app/playlists_router.py` `decide_proposals` (the `arm_id` branch), `app/playlist_test.py` (`run_apply`, `apply_channel`, `test_dates`, `POSITION_REFUSED`), the `playlist_test_apply` job (`app/main.py` `_register_jobs`), `app/youtube_client.py` `yt_playlist_items_insert(position=)`, `PLAYLIST_APPLY_ENABLED`, `PLAYLIST_TEST_DAILY_UNITS`, `PLAYLIST_TEST_MAX_ATTEMPTS` (`app/config.py`), `tests/test_playlist_test_apply.py`. S2.3: `app/playlist_test.py` (`measure_channel`, `windows`, `daily_starts`, `channel_playlist_test` = `GET /channels/{id}/playlist-test`, `ARMS`), `app/lever_verdicts.py` (`run_weekly`'s `playlist arms` category, `verdicts`/`directional` taking `min_lift`/`windows`, `ON_CONFLICT`), `PLAYLIST_EXPERIMENT_WINDOWS`, `PLAYLIST_MIN_LIFT` (`app/config.py`), `tests/test_playlist_test_measurement.py`. S2.4: `supabase/migrations/20261027010000_short_link_recommendations.sql`, `app/short_links.py` (`shorts`, `targets`, `refresh`, `preview`, `run_weekly`), the `short_link_refresh` job (`app/main.py` `_register_jobs`), `scripts/short_links.py`, `SHORT_LINK_CHANNELS`, `SHORT_LINK_TARGETS`, `SHORT_LINK_MIN_FEED_VIEWS`, `SHORT_LINK_MAX_PER_RUN` (`app/config.py`), `ShortLinkStatus` (`app/status_vocab.py`), `tests/test_short_links.py`. S2.5: `app/short_links.py` (`router`: `channel_short_links`, `set_short_link`, `dismiss_short_link`), the "Short links" card (`#sl-card`, `loadShortLinks`, `app/static/channel.html`), `tests/test_short_links_page.py`. S2.6: `app/short_links.py` (`seen_pairs`, `detect`, `PAIRS`), `app/lever_measurement.py` (`SOURCE_TYPES`, `source`, `targets`, `pair_views(source_type=)`), `app/lever_verdicts.py` (`write_verdicts(lever=)`, `run_weekly`'s detection), `SHORT_LINK_SEEN_MIN_VIEWS` (`app/config.py`), `tests/test_short_links_seen.py`, `tests/test_lever_measurement.py`, `tests/test_lever_verdicts.py`. Pre-spec engine frozen: `app/playlists.py`, `app/playlist_discovery.py` | Marathi was drawn 2026-10-26 04:10 UTC (`scripts/playlist_test.py --draw`); the 165 proposals were decided by SQL at 04:40 UTC (151 `approved`, 14 `rejected`), since the dashboard card then listed only the oldest 1,000 pending proposals (fixed by #106). The candidates concentrate on a handful of high-impression videos (one is proposed for about 25 playlists): Marathi's `join_high` (0.9014) is below most videos' cosine to a playlist's centroid (0.90–0.93), so it barely filters and the ranking is by impressions. Over 1,000 frozen-engine proposals are still `pending` on the card, and approving one writes to YouTube at once. Approving a test proposal (`arm_id` set) in the dashboard card only marks it `approved` (S2.2, `app/playlists_router.py` `decide_proposals`); the daily `playlist_test_apply` job sends it, and does nothing while `PLAYLIST_APPLY_ENABLED` is false (the default). The card's toast still says "Executed 0 change(s) on YouTube." for them; the response carries `queued`. The weekly `lever_measurement` job measures a drawn channel's test once it is dosed (`test_dates`) and writes `lever = 'playlist'` verdicts (S2.3); nothing reads them to stop anything. The weekly `short_link_refresh` job (S2.4) writes `pending` Short-link recommendations for Marathi once `20261027010000` is applied and Marathi's Shorts are in `videos` with B6 vectors (S2.7 step 2); the team sees them on the "Short links" card (Playlists tab, S2.5) and ticks a target it set in Studio, which writes a `human` `short_link` intervention; nothing reaches YouTube. The weekly `lever_measurement` job (S2.6) records the links it sees in type-32 traffic as `human` `short_link` interventions too, measures them on type 32 and writes `lever = 'short_link'` `human` verdict rows; it needs `20261027010000` applied once a Short-link pair shows up. Recommend-only proposal machinery exists (`playlist_proposals`, `app/playlists_router.py:271-297`). The add/remove and creation paths are frozen by default (§4). |
| **Slice 3** | Agent challenger + titles | **built, not merged or deployed** (spec Part 6, owner decisions F1–F14, 2026-10-30): S3.1 built (#115), S3.2 built (#116), S3.3 built (#118), S3.4 built (#119), S3.5 built (#120), S3.6 built (#117), on the stacked `slice-3/*` branches; S3.7 (deploy) and S3.8 (docs) are the owner's | S3.1: `app/titles_apply.py` (`apply_title`, `revert_title`), `app/backlinks_apply.py` (`revert_intervention`'s `title` dispatch, `_live_snippet`, `_send_snippet`), `TITLE_APPLY_ENABLED` (`app/config.py`), `tests/test_titles_apply.py`. S3.2: `app/titles.py`, `scripts/preview_titles.py`, `scripts/title_bakeoff.py`, `WRITER_MODEL`, `TITLE_CANDIDATES`, `TITLE_MAX_IMPRESSIONS`, `TITLE_AGENT_PCT` (`app/config.py`), `tests/test_titles.py`. S3.6: `app/autopilot.py` `tick` (the house-format branch deleted, `SHORTS_ONLY`), the title-autopilot setting gone from `app/config.py`, `app/audits.py` (`AGENT_CHANNEL_REFUSED`, `_refuse_on_agent_channel`, `apply_audit_internal(force=)`, `force` on `POST /audits/{id}/apply` and `/apply-pending`), `tests/test_audits_agent_guard.py`, `tests/test_agent_tick.py` `test_with_agent_enabled_off_the_tick_does_the_shorts_action_only`, `tests/test_autopilot_shorts_tick.py`, `tests/test_autopilot_tick_helpers.py`. S3.3: `app/decide.py` (`_triage_rules`, `QUESTION_SET_VERSION`), `app/agent_tick.py` (`_run_title`, `backlinks_enabled`, `titles_open`, `_title_enabled`, `_titles_today`, `title_channel`, `_assess`'s title keys), `app/titles.py` (`path_stopped`, `stopped`, `route`, `would_title` and `title_answers` on `TRIAGE.rules`), `app/autopilot.py` `_agent_tick`, `TITLE_CHANNELS`, `TITLE_DAILY_CAP`, `TITLE_AGENT_DAILY_RUNS`, `TITLE_EXCLUDE_VIDEOS` (`app/config.py`), `tests/test_agent_tick_titles.py`, `tests/test_decide.py`, `tests/test_titles.py`. S3.4: `app/openrouter.py` `chat_tools`, `app/agent/loop.py` (`run_title_agent`, `AgentResult`, `tools_called`), `app/agent/tools.py` (the tools, `SCHEMAS`, `call`), `app/titles.py` (`TITLE_BRIEF`, `AGENT_PROMPT`, `agent_system_prompt`, the agent stamp, `preview`'s agent run), `app/agent_tick.py` (`_run_title`'s agent path, `_agent_outcome`), `app/interventions.py` `record(trajectory=)`, `supabase/migrations/20261030000000_interventions_trajectory.sql`, `AGENT_MAX_TURNS` (`app/config.py`), `scripts/preview_titles.py`, `tests/test_agent_loop.py`, `tests/test_openrouter_tools.py`, `tests/test_agent_tick_titles.py`, `tests/test_titles.py`. S3.5: `app/title_measurement.py`, `app/lever_verdicts.py` (`title_verdicts`, `TITLE_SCOPES`, `_title_judged`, `write_verdicts(lever='title')`, `stopped(…, scope=)`, `auto_revert`, `REVERTS`, `run_weekly`'s title half, `channel_title_test` = `GET /channels/{id}/title-test`), `app/titles.py` (`path_stopped`, `path_closed`), `supabase/migrations/20261030020000_warm_pool_title_holds.sql` (`warm_pool()`), `app/warm.py` `_holds`, `LeverVerdictScope.PIPELINE_VS_HOLDOUT`/`AGENT_VS_HOLDOUT` (`app/status_vocab.py`), `supabase/migrations/20261030010000_lever_verdicts_title_scopes.sql`, the eight S3.5 settings (`app/config.py`), `tests/test_title_measurement.py`, `tests/test_title_verdicts.py`, `tests/test_status_vocab.py`, `tests/test_warm.py`, `tests/test_warm_pool_parity.py` | The tick titles videos (S3.3) only while `TITLE_APPLY_ENABLED` is true (default false) and the channel is in `TITLE_CHANNELS` (default Marathi): triage answers `title` after backlinks; a treated video is written by the pipeline or, on the agent path (`TITLE_AGENT_PCT`, 0.5), by the agent (S3.4), which may decline; every agent row stores its run in `interventions.trajectory` (migration `20261030000000`, not applied: until it is, every agent-path row write fails, while pipeline, holdout and backlinks rows don't send the column). While the switch is off no title row is written and the write and its revert send nothing. The weekly `lever_measurement` job measures title rows, writes a verdict per path against the shared holdout, stops a path by its stop rule or harm guard (`titles.path_stopped`); a stopped path, or one with no share (`TITLE_AGENT_PCT` 0 or 1), is closed (`titles.path_closed`), a closed path's videos go to the other path if it is open, and both closed close the lever and puts back losing titles (S3.5, `revert_title(auto=True)`, nothing sent while `TITLE_APPLY_ENABLED` is off); no title verdict exists yet. `20261030010000` (a column comment) and `20261030020000` (`warm_pool()` with the title hold) are not applied either (§2). No `app/niche_reference.py`. The old title path is gone from the tick (S3.6): no tick path calls `audit_video`, and a channel with `agent_enabled` off does only the Shorts action. `audit_video` stays for the manual audit routes, whose house-format applies refuse on an agent channel unless `?force=true` (§5). |
| **Slice 4** | Playbook | **not started** | none | No `channels.playbook_json`. `app/reflection.py` (the thing Slice 4 retires) is frozen by `REFLECTION_ENABLED=false` (§4). |
| **Slice 5** | Fleet | **not started** | none | `JobBudget` exists (`app/quota.py:232`) but has no per-channel shares. |

**What runs today (pre-spec machinery, all built before the spec).** The sensor layer
(`app/metrics_poll.py`, `app/reporting_poll.py`, `app/reach.py`, `video_reach_daily`), Loop 1 title
measurement (`app/measurement.py`, `app/verdicts.py`; 21-day CTR windows), playlist inventory and health
scoring (`app/playlists_sync.py`, `app/playlist_health.py`), daily video sync (`app/main.py:248-275`), the Shorts
cutter (`app/shorts/*`), and the NAS backup (`app/backup.py`). The spec keeps the sensor layer, the apply path,
`AuditSuggestion`, quota, `status_vocab`, `reach.certify`, and the playlist write, inventory, health and proposal
machinery (spec Part 2 §0.5 "Kept").

**Channels live** (A7 query 1, `docs/PHASE_A_FINDINGS.md`, 2026-10-06). All 13: `analytics_authorized = t`,
`autopilot_enabled = f`, `reach_warmup = f` on that date. Since then: Marathi `autopilot_enabled = agent_enabled = t` (2026-10-24, Slice 1), `reach_warmup = t` on Haryanvi, Rajasthani, 3D Animated, Kannada and Telugu (2026-10-26); Marathi `sync_shorts = t` (#93 A1, 2026-10-26). Warm pool and reach frontier are from the same A7 run.

| Channel | id | `default_language` | `measurement_enabled` | `playlist_health_enabled` | `autopilot_shorts_enabled` | Warm videos (≥500 imp, 30 d) | Reach frontier |
|---|---|---|---|---|---|---|---|
| Marathi (**rollout #1**) | `UCr5-YUqBiW7PUmeAtxUWuRg` | `mr` | t | f | t | 566 | 2026-10-04 (221 days) |
| Punjabi | `UC8KjoL0Z9mTHKqB6gFutkJw` | `pa` | t | **t** (only one) | t | 342 | 2026-10-04 (213) |
| Gujarati | `UCOVKJdzghm2gOnuaGeJTonA` | `gu` | t | f | t | 603 | 2026-10-04 (147) |
| English | `UCMpj6iUMCMhB0k4L5EcxJwQ` | `en` | t | f | t | 1,008 | 2026-10-04 (148) |
| Hindi | `UCR9qQMyP86aSt-1VgaMg7UA` | `hi` (set 2026-10-07) | t | f | t | 1,120 | 2026-09-26 (213; token expired, last synced 2026-09-24) |
| Bhojpuri | `UC8oC7Yiz0WkH3PKb3GW42XA` | `hi` (set 2026-10-07) | t | f | t | 471 | 2026-10-04 (183) |
| Tamil | `UCWb0eKKkX1NE1r_Tu6oKhdQ` | `ta` (set 2026-10-07) | t | f | t | 290 | 2026-10-04 (143) |
| Malayalam | `UCX8BttGE4UAFdm1RRIULOPQ` | `ml` (set 2026-10-07) | t | f | t | 70 | 2026-10-04 (143) |
| Haryanvi | `UCc4Tv_DEGDEKrKAt-vyVNmw` | `bgc` | f | f | t | no reach data | none |
| Rajasthani | `UCFO6AQ_KBQDEaQiTi-dBEWQ` | `hi` (set 2026-10-07) | f | f | t | no reach data | none |
| 3D Animated Series | `UCqtU4xCSjsSvE53Iy6NUKSg` | `hi` | f | f | t | no reach data | none |
| Kannada | `UCo4_mZK5aAF7ugv4cTfZlEg` | `kn` | f | f | f | no reach data | none (0 videos) |
| Telugu | `UCxK1-ftYdFvU4IuUW3POxRA` | `te` (set 2026-10-07) | f | f | f | no reach data | none (0 videos) |

Every channel has a `default_language` since B9b step 7 (2026-10-07; `docs/PHASE_B_FINDINGS.md`), so
`eligibility.can_audit` (`app/eligibility.py:66-84`) no longer gates any channel out on language. Harmless while
`autopilot_enabled = f` everywhere.

Flags that exist on `channels`: `analytics_authorized`, `measurement_enabled`, `reach_warmup`,
`playlist_health_enabled`, `autopilot_enabled`, `autopilot_shorts_enabled`, `sync_shorts`, and `agent_enabled`
(`20261006020000`, B2; applied 2026-10-07; read by `autopilot.tick` and `eligibility.can_run_agent` since S1.4b, set on Marathi since 2026-10-24).

---

## 2. Schema — as applied

**Migrations** (`supabase/migrations/`, in order; bootstrap `supabase/bootstrap/000_roles.sql`,
`010_storage_shim.sql` run first). The latest is `20261030020000` (S3.5, #120: `warm_pool()` replaced with the title hold), not applied, after `20261030010000` (S3.5, a column comment only), not applied, after `20261030000000` (S3.4, #119), not applied. `20261027010000` (S2.4, #90) and `20261027000000` (S2.1, #87) were applied at the office 2026-10-26 (#93 B1). `20261023010000` (S1.6b, #68) and `20261023000000` (S1.4a, #63) were applied for Slice 1's deploy (A1 of #93 lists both in `schema_migrations`). `20261006060000` (B6, #37), `20261006050000` (B5, #36), `20261006040000` (B4, #35), `20261006030000` (B3a, #33), `20261006020000` (B2, #32),
`20261006010000` (B1b, #31) and `20261006000000` (B1a, #30) are applied on the office machine: the B1 pair on
2026-10-07 (B9a), the other five on 2026-10-07 (B9b) (`docs/PHASE_B_FINDINGS.md`).

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
```

These are the files. The live DB's migration ledger was not checked (unreachable).

**Tables** (columns are the union across the migrations):

- **`channels`**: `id text pk, name, handle, refresh_token text not null, access_token, token_expiry timestamptz, last_synced_at, created_at, default_language text, autopilot_enabled bool default false, autopilot_paused_reason text, autopilot_last_tick_at, autopilot_daily_cap int default 10, analytics_authorized bool default false, last_full_synced_at, playlist_health_enabled bool default false, measurement_enabled bool default false, autopilot_shorts_enabled bool not null default false, autopilot_shorts_daily_cap int not null default 1, autopilot_shorts_upload_cap int not null default 2, shorts_cut_mode text not null default 'highlights', shorts_camera_motion text not null default 'calm', sync_shorts bool (nullable), nas_folder text, autopilot_paused_at timestamptz, reach_warmup bool default false, agent_enabled boolean not null default false, playlist_thresholds jsonb`.
  `playlist_thresholds` (`20261006060000`, B6), verbatim: `alter table channels add column if not exists playlist_thresholds jsonb;`. NULL until `app/reembed.py` `calibrate_channel` writes `{model_version, join_high, join_low, leave, member_sims, playlists, method, computed_at}`. Read only by `app/backlinks.py` `candidates` (S1.1: the source channel's `join_low`, refused unless `model_version` is `reembed.MODEL_VERSION`), called by the agent tick (`app/agent_tick.py`).
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
  **Retention** (owner, 2026-10-13): `source_detail` is kept only where `app/traffic_poll.py` `keeps_detail` says so (type 7 from a video in `videos`, any channel; type 14 `PL…` or `RD<one of our video ids>`; every other type) and the rest is folded into the blank-detail row for (video, day, type) by `collapse_unread_detail`, so per-type totals are exact. Rows ingested before it are folded by the one-off `scripts/collapse_traffic_detail.sql` (not yet run at the office).
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
  of that set (`tests/test_status_vocab.py`). Row inserts come from four writers: the B3 human ledger (`app/human_edits.py`, two
  `human` row kinds) and, since S1.4b, the agent tick (`app/agent_tick.py`, `midas` `backlinks` rows: `declined`
  arm `n/a` with `payload.rationale`; `holdout` with `payload.targets`; `planned` → `measuring` or `cancelled`
  with `payload.error = {reason, detail}`; each with `triage_json`, §5), the Short-link tick since S2.5
  (`app/short_links.py` `set_short_link`, below), and the Short-link detection since S2.6 (`app/short_links.py` `detect`). Since S3.1
  `app/titles_apply.py` updates a `midas` `title` row on its apply (`measuring`, `applied_at`, `before_state =
  {title}`) and revert (`cancelled`, `payload.revert = {reverted_at, live_before, title, auto}`). Since S3.3 the agent
  tick writes `midas` `title` rows (`app/agent_tick.py` `_run_title`): `holdout` with `payload {title_before}`;
  treated `planned` with `payload {title_before, title, candidates, reason, path}` and `strategy_version` (the title
  stamp, §6), then `measuring` or `cancelled` with `payload.error = {reason, detail}` as backlinks; or, with no
  `planned` step, treated `cancelled` with `payload {title_before, path, title: null, candidates, reason: null,
  error}`, `error.reason` `checks_failed` (no candidate passed the checks), or `payload {title_before, path, error}`,
  `error.reason` `writer_exception` (the writer raised). Since S3.4 an agent-path run writes the same `planned` row
  (`candidates` = its submitted titles with their checks), or treated `declined` with `payload {title_before, path:
  "agent", rationale}` (no `strategy_version`, no YouTube call), or treated `cancelled` with `error.reason`
  `turn_cap` or `checks_failed`; each with `trajectory` (below), `writer_exception` too when the model call raised. Updates: since S1.6a, `app/lever_measurement.py`
  `measure_channel` updates `backlinks` rows' `status`, `measurement_status` and `measurement_result` (below; run
  weekly by the `lever_measurement` job since S1.6b); since S3.5 `app/title_measurement.py` `measure_channel` does the same for
  `midas` `title` rows, and `lever_verdicts.auto_revert` reverts judged ones through `titles_apply.revert_title(auto=True)`. **B3a:** one
  row per link to one of our videos that the team added to a description, `origin='human'`, `lever='backlinks'`,
  `arm='n/a'`, `status='applied'`, `applied_at` NULL, `detected_at` = when the sync saw it, and `payload`
  `{source_video_id, target_video_id, added_targets, removed_targets, timing}` (plus `removed_detected_at` once a
  later sync sees the link gone). `ledger_key` = `backlinks:<source>:<target>:<first 16 hex of sha256 of the new
  description, whitespace collapsed>`. **B3b:** one row per membership of one of the channel's videos in one of its
  playlists that the membership walk sees for the first time, in a playlist it has walked before, and that Midas
  didn't add: `lever='playlist'`, same `origin`/`arm`/`status`/`applied_at`/`detected_at` as B3a, `payload`
  `{playlist_id, video_id, playlist_item_id, timing}`, `ledger_key` = `playlist:<playlist_id>:<video_id>:<playlist_item_id>`.
  **S2.5:** one row per (Short, target) pair the team ticks as set in Studio (`POST /short-links/{id}/set`):
  `lever='short_link'`, `origin='human'`, `arm='n/a'`, `status='applied'`, `video_id` = the target, `applied_at`
  NULL, `detected_at` = the tick, `payload` `{short_id, target_video_id, recommendation_id, timing: "ticked"}`,
  `ledger_key` = `short_link:<short_id>:<target_video_id>`. **S2.6:** one row per (Short, target) pair the
  `lever_measurement` job sees in type-32 traffic with no row yet (`app/short_links.py` `detect`): the same columns,
  `channel_id` = the Short's, `detected_at` = Pacific midnight of the first data-day with views in the window,
  `payload` `{short_id, target_video_id, recommended, timing: "inferred_from_traffic"}` (`recommended` = a
  `short_link_recommendations` row exists for the pair), the same `ledger_key`, so a later tick links it.
  `ledger_key` is NULL on any other row.
  Added by `20261030000000` (S3.4, #119; not applied), verbatim without its header comment:
  ```sql
  alter table interventions add column if not exists trajectory jsonb;
  ```
  Written only by the agent tick, through `interventions.record(trajectory=)`, on every agent-path `title` row
  (`planned`, `declined`, `cancelled`), whatever its end: `{model, writer_model, max_turns, turns, end: {kind,
  reason, detail}, submits: [{title, check, reasoning}], messages: [{role, content, tool_calls: [{id, name,
  arguments}], tool_call_id, name}]}`, every text cut to 2,000 characters (`app/agent/loop.py`
  `TRAJECTORY_CHARS`). `record` sends the column only when given, so no other row needs the migration. NULL on
  every other row.
  **Measurement (S1.6a).** `status` is the lifecycle and carries the outcome: `measuring` (treated), `holdout`
  and `applied` (human) → `judged` or `insufficient_data`. `measurement_status` only says how far the measurement
  got (`InterventionMeasurement`, `app/status_vocab.py:223-244`): `awaiting_window|extended|done`, NULL until the
  first run; every other row and lever leaves it NULL. Since S2.6 `measure_channel` also measures `human`
  `short_link` rows the same way (source `payload.short_id`, target `video_id`, type 32), with the same
  `measurement_status` and `measurement_result`. `measurement_result` on a decided row:
  `{pre, post, delta, source_views, missing_days, window: {d0, pre: [start, end], post: [start, end], post_days,
  extended}, judged_at, computed_at}` (§5 `lever_measurement.py`).
  **Title rows (S3.5).** `app/title_measurement.py` `measure_channel` (the `lever_measurement` job) measures
  `midas` `title` rows: treated `measuring` (`applied_at` set), `holdout`, and treated `declined` (an agent
  decline) → `judged` or `insufficient_data`, `measurement_status` `awaiting_window` → `done` (never `extended`);
  `cancelled` and `planned` rows aren't measured. A judged treated row later put back keeps its numbers as
  `cancelled` (`payload.revert`). `measurement_result` on a decided title row: `{pre, post, delta, impressions:
  {pre, post}, ctr: {pre, post}, missing_days, window: {d0, pre: [start, end], post: [start, end]}, judged_at,
  computed_at}` (`pre`/`post` browse + suggested views, `delta` the log ratio; §5 `title_measurement.py`).
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
- **`audit_strategies`**: `version text pk, prompt_template text not null, model text not null, config jsonb, status text default 'challenger', notes, created_at`. Seed row `('2026.07-baseline-v1', 'code:app/audits.py DEFAULT_PROMPT + audit_configs.generated_prompt (per-channel)', 'anthropic/claude-haiku-4.5', 'champion', …)`; derived rows are upserted per audit (§6), and since S3.2 per title strategy by `app/titles.py` `strategy_version` (`prompt_template = 'code:app/titles.py TITLE_PROMPT'`, `model = WRITER_MODEL`), written since S3.3 by the agent tick's treated titles.
- **`video_embeddings`**: `video_id, chunk_index, model_version text not null, embedding vector(3072), unique (video_id, chunk_index, model_version)` (`20260518000000_playlists.sql:10-12`). Production writes use `model_version = EMBED_MODEL` (`app/embeddings.py:133`), from two input recipes (§6). B6's one-off re-embed writes a second value, `app/reembed.py` `MODEL_VERSION` = `"google/gemini-embedding-2-preview|tdt-v1"` (`EMBED_MODEL` + `"|"` + `RECIPE`, `app/reembed.py:33-34`), one recipe for every video (§6); every production reader filters on `EMBED_MODEL`, and every caller of the `p_model_version` RPCs passes it, except `app/backlinks.py` `candidates` (S1.1), which reads only `MODEL_VERSION` and is called by the agent tick (`app/agent_tick.py`).
- **Other tables:** `audit_configs` (`raw_insights, generated_prompt, shorts_prompt, niche_queries jsonb, reflection_mode default 'shadow'`), `prompt_versions`, `threshold_history`, `playlist_assignments`, `playlist_proposals` (§2 `playlist_arms` for its S2.1 columns), `video_keyframes`, `video_transcripts`, `quota_log`, `shorts_jobs`, `shorts_clips`. SQL functions: `dashboard_summary()`, `playlist_video_sims()`, `discover_orphan_clusters()`, `next_audit_candidate()`, `warm_pool()` (B4, replaced by S1.4a, below).

- **`warm_pool()`** (`20261023000000`, S1.4a #63, replacing B4's `20261006040000`; replaced again by
  `20261030020000`, S3.5 #120, not applied, which adds the `title` clause shown below), verbatim without its header
  comment, as of `20261030020000`. Its in-app twin is `app/warm.py` `_ranked_pool_inapp`; the agent tick picks through `warm.warm_pool` (§5). On top of B4's
  active-Midas exclusion it skips a video with any `midas` row created within `p_cooldown_days`
  (`TRIAGE_COOLDOWN_DAYS`), whatever its lever or status, or any `midas` `backlinks` row of arm `holdout`, or
  `treated` with `applied_at` set, at any age; since S3.5 also any `midas` `title` row of arm `holdout`, or `treated`
  with `applied_at` set or a status other than `cancelled` (a decline, measured or not), at any age. The
  four-argument B4 function is dropped, not overloaded (S1.4a; `20261030020000` keeps the five-argument signature,
  `create or replace`):
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

- **`decision_log`** (`20261006050000`, B5), verbatim without its header comment. Written only by
  `app/decide.py` `decide()`, called by the agent tick (`app/agent_tick.py` `run`), which then sets `intervention_id`
  through `decide.link` (§5), and since S2.4 by the Short-link refresh (`app/short_links.py` `_next_watch`, through
  `refresh`), whose rows `short_link_recommendations.decision_log_id` points at. `subject` is the video id for `TRIAGE` rows and `<source id>-><target id>` for
  `NEXT_WATCH` rows (S1.5):
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
  `used` vocab (`app/status_vocab.py:370-377`, `DecisionUsed`): `rules|jev`; always `rules` in shadow. `jev_answer`
  / `jev_probs` hold the configured backend's answer (`llm` by default), NULL when the backend failed.

- **`lever_verdicts`** (`20261023010000`, S1.6b #68), verbatim without its header comment. Written by
  `app/lever_verdicts.py` `write_verdicts` (`lever = 'backlinks'`, since S2.6 `'short_link'`, since S3.5 `'title'`) and, since S2.3, `app/playlist_test.py`
  `measure_channel` (`lever = 'playlist'`, below), both from the weekly `lever_measurement` job; read by
  `lever_verdicts.stopped` (the stop rule, through `agent_tick.backlinks_stopped` and, since S3.5, `titles.path_stopped`), `GET /channels/{id}/lever-verdicts`
  and `GET /channels/{id}/playlist-test`. The `lever` column's comment still says `-- backlinks`:
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
  Vocab (`app/status_vocab.py`): `arm_scope` `treated_vs_holdout|human|pipeline_vs_holdout|agent_vs_holdout`
  (`LeverVerdictScope`; the last two since S3.5), `verdict` `helped|no_change|worse` (`LeverVerdict`), NULL on
  `human` rows; `tests/test_status_vocab.py` checks the migration's column comments against them (the two title
  scopes against `20261030010000`, which records the four, verbatim without its header comment:
  `comment on column lever_verdicts.arm_scope is 'treated_vs_holdout|human|pipeline_vs_holdout|agent_vs_holdout';`). `week_start` is the Monday (UTC) of the week the rows were judged
  in (`measurement_result.judged_at`). A `treated_vs_holdout` row: `n_treated`/`n_holdout` and the two means over
  the `midas` rows judged that week, `lift` = treated mean delta − holdout mean delta, `cumulative_lift` the same
  over every row judged up to that week, `windows_judged` = the channel's `treated_vs_holdout` weeks so far
  (this one included), `verdict` = `helped` at `lift` ≥ `BACKLINK_MIN_LIFT`, `worse` at ≤ −it, else
  `no_change`, `stop_rule_triggered` = `windows_judged` ≥ `BACKLINK_EXPERIMENT_WINDOWS` and `cumulative_lift` <
  `BACKLINK_MIN_LIFT`. A `human` row: `n_treated` and `treated_mean_delta` of the `human` rows judged that week;
  `n_holdout` 0, `holdout_mean_delta`, `lift`, `cumulative_lift` and `verdict` NULL, never stopped. A backlinks row whose video has `is_short` true enters neither scope (`_without_shorts`, since 2026-10-26: the pick took Shorts before #103); it is still measured. The DDL adds
  `id` and the unique key to the ticket's column list; types and `not null`s are this build's.
  **A `playlist` row (S2.3)**, always `treated_vs_holdout`: one per complete post week k of the channel's playlist
  test, `week_start` = that week's first day (`test_end` + 1 + 7(k − 1), not a Monday), `n_treated`/`n_holdout` =
  the dosed treated and holdout arms whose playlist is still in `playlists` (`no_dose` arms never count), the two
  mean `delta`s of week k, `lift` = their difference, `cumulative_lift` = treated mean − holdout mean over every
  arm's weeks 1 … k pooled, `windows_judged` = k, `verdict` = `directional(lift, PLAYLIST_MIN_LIFT)`,
  `stop_rule_triggered` = k ≥ `PLAYLIST_EXPERIMENT_WINDOWS` and `cumulative_lift` < `PLAYLIST_MIN_LIFT` (the answer
  "no"). Upserted on the same unique key, every week rewritten in place each run until the test is done.
  **A `short_link` row (S2.6)**, always `human`: as backlinks' `human` row, over the `human` `short_link` rows
  judged that week (`write_verdicts(lever='short_link')`): `n_treated`, `treated_mean_delta`, `windows_judged`;
  no lift, no verdict, never stopped.
  **A `title` row (S3.5)**, `arm_scope` `pipeline_vs_holdout` or `agent_vs_holdout`
  (`write_verdicts(lever='title')`, `lever_verdicts.title_verdicts`): a path's rows against the one holdout, with
  backlinks' `treated_vs_holdout` arithmetic over the `midas` `title` rows judged that week (`payload.path` picks
  the path; an agent decline, arm `treated` without `applied_at`, is in the agent's mean, F14; a judged row put
  back since, `cancelled` with `pre` ≥ `TITLE_MIN_PRE_VIEWS`, stays in), `windows_judged` = that scope's weeks so
  far, `verdict` = `directional(lift, TITLE_MIN_LIFT)`, `stop_rule_triggered` = (`windows_judged` ≥
  `TITLE_EXPERIMENT_WINDOWS` and `cumulative_lift` < `TITLE_MIN_LIFT`) or (`windows_judged` ≥ `TITLE_HARM_WINDOWS`
  and `cumulative_lift` ≤ −`TITLE_HARM_LIFT`). Read by `titles.path_stopped` (`lever_verdicts.stopped(channel,
  'title', scope)`) and `GET /channels/{id}/title-test`.

- **`playlist_arms`** (`20261027000000`, S2.1 #87), verbatim without its header comment, with the four columns it
  adds to `playlist_proposals` (`20260519000000`: `id, video_id → videos, playlist_id → playlists, video_title,
  playlist_title, action, similarity, decision_source, status default 'pending', proposed_at, decided_at`). Written
  only by `app/playlist_test.py` `draw`, once per channel: one row per eligible playlist, and for a `planned` treated
  arm its candidates as `playlist_proposals` rows `{video_id, playlist_id, video_title, playlist_title, action:
  'add', similarity, decision_source: 'experiment', status: 'pending', arm_id}`, whose ids go on `proposal_ids` in
  candidate rank. `eligible_members` = the playlist's current members with a `reembed.MODEL_VERSION` vector at the
  draw. Since S2.2 `app/playlist_test.py` `apply_channel` (the `playlist_test_apply` job) moves a treated arm
  `planned` → `applying` → `dosed`/`no_dose` and writes `first_applied_at`/`last_applied_at`, and writes the
  proposals' `applied_at`, `playlist_item_id` and `apply_error` (`{reason, detail, attempts}` on a failure,
  `{reason: 'position_refused', detail}` on an add YouTube took only appended); `decide_proposals` writes their
  `status`/`decided_at`. Since S2.3 `app/playlist_test.py` `measure_channel` (the weekly `lever_measurement` job)
  writes every arm's `measurement_status` (`awaiting_window` → `measuring` → `done`) and `measurement_result`
  `{pre_weekly, weeks: [{k, start, end, starts, delta}], missing_days, added_video_views: [{k, views}],
  computed_at}`, and at the last window moves `dosed`/`holdout` arms to `judged`, or `insufficient_data` when the
  playlist is gone from `playlists` (`no_dose` stays):
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
  Vocab (`app/status_vocab.py`): `arm` `treated|holdout` (`PlaylistArm`); `status`
  `planned|applying|dosed|no_dose|holdout|judged|insufficient_data` (`PlaylistArmStatus`; the draw writes only
  `planned`, `no_dose` and `holdout`); `measurement_status` `awaiting_window|measuring|done`
  (`PlaylistArmMeasurement`); `playlist_proposals.decision_source` `experiment` (`PlaylistProposalSource`, the only
  value listed there; the older ones are literals in the frozen engine). `tests/test_status_vocab.py` checks the
  migration's column comments against them, and `DECIDED_BY` in `app/static/channel.html` for `experiment`.

- **`short_link_recommendations`** (`20261027010000`, S2.4 #90), verbatim without its header comment. Written only by
  `app/short_links.py` `refresh` (the weekly `short_link_refresh` job): per Short from `shorts` with no row yet, its
  `targets` as `pending` rows (`rank` 1 … `SHORT_LINK_TARGETS`, in one insert, after asking each pair
  `decide(NEXT_WATCH, "<short>-><target>", …)`), `similarity` the raw B6 cosine, `impressions` the target's warm
  impressions, `feed_views` the Short's type-24 views at the refresh, `decision_log_id` the pair's log row (the log
  row's `intervention_id` stays NULL). Since S2.5 `app/short_links.py` `set_short_link` and `dismiss_short_link`
  write `status` (`set`, `not_chosen`, `dismissed`), `decided_at` and, on a `set` row, `intervention_id` (§5
  Routes). Since S2.6 `app/short_links.py` `detect` writes `seen_at` (Pacific midnight of the first data-day the
  pair had type-32 views in the window) when it is NULL. `channel_id` is nullable, as the spec's column list has it:
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
  Vocab (`app/status_vocab.py`, `ShortLinkStatus`): `pending|set|not_chosen|dismissed`; `refresh` writes only
  `pending`, the S2.5 routes the other three. `tests/test_status_vocab.py` checks the migration's column comment and default against it.

Of the spec's Phase B tables `video_traffic_source_daily`, `playlist_traffic_daily`, `interventions` and `decision_log` exist (plus `channels.agent_enabled`, and B6's `channels.playlist_thresholds`, which the spec doesn't name); the rest, and the Slice tables and columns, are listed in §7.1.

---

## 3. Config — verbatim

Defaults from `app/config.py`. "Dev `.env`" is the generating machine's local `.env` (not in git). The office
`.env` is hand-carried and was not read; the only office value on record is `AUTOPILOT_TICK_SECONDS=30`
(`docs/PHASE_A_FINDINGS.md` restart-day step 2).

**Settings the spec names** (spec Part 1 A4/A6, Part 2 §8):

| Setting | Code (`app/config.py`) | Spec | Differs? |
|---|---|---|---|
| `PLAYLIST_DISCOVERY_ENABLED` | `:121` `os.getenv("PLAYLIST_DISCOVERY_ENABLED", "false").lower() == "true"` | default false (Part 1 A4) | no |
| `PLAYLIST_RECONCILE_WRITES_ENABLED` | `:122` same form, `"false"` | default false (A4) | no |
| `PLAYLIST_TUNING_ENABLED` | `:123` same form, `"false"` | default false (A4) | no |
| `REFLECTION_ENABLED` | `:34` same form, `"false"` | default false (A4) | no |
| `STRATEGY_LABEL` | `:411` `os.getenv("STRATEGY_LABEL") or "2026.07-baseline"` | prefix of a derived `strategy_version` (A6, Part 2 §8) | derived per audit, not at startup (§7.3) |
| `MIN_IMPRESSIONS` | `:191` `int(os.getenv("MIN_IMPRESSIONS") or "500")` | `WARM_MIN_IMPRESSIONS` starts "Same as `MIN_IMPRESSIONS`" (Part 2 §8) | no (a separate setting, same default) |
| `MEASUREMENT_WINDOW_DAYS` | `:190` `or "21"` | measurement runs weekly (Part 2 §1.1); 14-day extension (§1.7) | **differs** (21-day window) |
| `PLAYLIST_JOIN_HIGH` / `_LOW` / `PLAYLIST_LEAVE` | `:126-128` `or "0.72"` / `"0.55"` / `"0.60"`, process-global | per channel, recalibrated (Part 2 §4, Part 3 B6) | **differs** in use: B6 calibrates per channel into `channels.playlist_thresholds` (`app/reembed.py` `calibrate_channel`, never writing `settings`), but the engine still reads these globals |
| `TRAFFIC_INGEST_CHANNELS` | `:232-236` `{c.strip() for c in (os.getenv("TRAFFIC_INGEST_CHANNELS") or "UCr5-YUqBiW7PUmeAtxUWuRg").split(",") if c.strip()}` | the rollout channel (Part 2 §8) | no |
| `HOLDOUT_PCT` | `:240` `float(os.getenv("HOLDOUT_PCT") or "0.20")` | 0.20, per lever, stable hash (Part 2 §8) | no. Read only by `app/interventions.py` `assign_arm` |
| `WARM_MIN_IMPRESSIONS` | `:245` `int(os.getenv("WARM_MIN_IMPRESSIONS") or "500")` | 500 (Part 2 §8) | no. Read only by `app/warm.py` |
| `WARM_WINDOW_DAYS` | `:246` `int(os.getenv("WARM_WINDOW_DAYS")     or "28")` | 28 "Ingested data-days" (Part 2 §8) | no: the latest 28 reach data-days in the ledger (`app/warm.py`) |
| `WARM_EXPLORE_PCT` | `:247` `float(os.getenv("WARM_EXPLORE_PCT")   or "0.10")` | 0.10 "Picks from the non-top warm pool" (Part 2 §8) | no. Read only by `app/warm.py` `warm_pool` |
| `DECIDE_BACKEND` | `:258` `os.getenv("DECIDE_BACKEND") or "llm"` | `llm`; `jev` once access is set up (Part 2 §8) | no. Read only by `app/decide.py`; `jev` is a stub raising `NotConfigured`, an unknown value is a backend failure (rules answer stands) |
| `BACKLINK_MIN_CANDIDATES` | `:261` `int(os.getenv("BACKLINK_MIN_CANDIDATES") or "2")` | 2 (Part 2 §8) | no. Read only by `app/decide.py` `TRIAGE` rules |
| `BACKLINK_MAX` | `:265` `int(os.getenv("BACKLINK_MAX") or "3")` | 3 (Part 4 Config, Part 2 §8) | no. Read only by `app/backlinks.py` `render`, at call time, which refuses more targets rather than trimming |
| `AUDIT_MODEL` | `:29` `os.getenv("AUDIT_MODEL") or "anthropic/claude-haiku-4.5"`; dev `.env`: `google/gemini-3.7-flash` | reasoning model (Part 2 §3.1) | — |
| `SIBLING_MIN_VIEWS` | `:270` `int(os.getenv("SIBLING_MIN_VIEWS") or "100")` | 100, inbound only (Part 4 Config, Part 2 §8) | no. Read only by `app/backlinks.py` `siblings`, over the source channel's latest 28 ingested traffic data-days (`SIBLING_WINDOW_DAYS`, a module constant) |
| `TRIAGE_COOLDOWN_DAYS` | `:275` `int(os.getenv("TRIAGE_COOLDOWN_DAYS") or "7")` | 7 (Part 4 Config, finding 2; Part 2 §2.1, §8) | no. Read only by `app/warm.py` (in-app cooldown, and `p_cooldown_days` of the `warm_pool()` RPC) |
| `BACKLINK_APPLY_ENABLED` | `:279` `os.getenv("BACKLINK_APPLY_ENABLED", "false").lower() == "true"` | false, the kill switch for YouTube writes (Part 4 Config) | **yes, stricter**: while false (and, since S3.3, the title lever is closed on the channel, `agent_tick.titles_open`) the agent tick does nothing at all (`app/autopilot.py` `_agent_tick` returns `apply_disabled` before any pick, triage or record), where the spec has treated rows cancelled with `apply_disabled`. With titles open it still ticks, and triage's `backlinks_enabled` (this switch and a heading for the language, `agent_tick.backlinks_enabled`) keeps backlinks out. `app/backlinks_apply.py` still refuses on its own (`apply_backlinks`, `POST /interventions/{id}/revert`, 409) |
| `TITLE_APPLY_ENABLED` | `os.getenv("TITLE_APPLY_ENABLED", "false").lower() == "true"` | false, the kill switch for title writes (Part 6 Config, F1); "while false no title row is written" | read only by `app/titles_apply.py` (`apply_title`, `revert_title`): while false both refuse `apply_disabled` (409) and send nothing. Since S3.3 also by `app/agent_tick.py` `titles_open`: while false triage never answers `title`, so no title row is written |
| `LEVER_MIN_SOURCE_VIEWS` | `:341` `int(os.getenv("LEVER_MIN_SOURCE_VIEWS") or "100")` | 100, §1.7 floor on the source's post-window views (Part 4 Config, Part 2 §1.7, §8) | no. Read only by `app/lever_measurement.py` `evaluate`: under it the post window is extended once to 14 days, then `insufficient_data` |
| `BACKLINK_EXPERIMENT_WINDOWS` | `:346` `int(os.getenv("BACKLINK_EXPERIMENT_WINDOWS") or "3")` | 3, the P1 time box (Part 4 Config, Part 2 §8) | no. Read only by `app/lever_verdicts.py` `write_verdicts`, passed to `verdicts`: the stop rule needs `windows_judged` ≥ it |
| `BACKLINK_MIN_LIFT` | `:350` `float(os.getenv("BACKLINK_MIN_LIFT") or "1.0")` | 1.0 attributable views per treated video per week (Part 4 Config, D6, Part 2 §8) | no. Read only by `app/lever_verdicts.py` `write_verdicts`, which passes it to `verdicts`/`directional`: the verdict band (±it) and the stop rule's bar on `cumulative_lift` |
| `PLAYLIST_HOLDOUT_PCT` | `:354` `float(os.getenv("PLAYLIST_HOLDOUT_PCT") or "0.5")` | 0.5, per playlist, stable hash (Part 5 Config, E4) | no. Read only by `app/playlist_test.py` `assign_arm` |
| `PLAYLIST_TEST_MAX_ADDS` | `:357` `int(os.getenv("PLAYLIST_TEST_MAX_ADDS") or "5")` | 5, per treated playlist (Part 5 Config, E5) | no. Read only by `app/playlist_test.py` (`candidates`, `draw`, `preview`) |
| `PLAYLIST_APPLY_ENABLED` | `:361` `os.getenv("PLAYLIST_APPLY_ENABLED", "false").lower() == "true"` | false, the kill switch for the test's YouTube writes (Part 5 Config) | no. Read only by `app/playlist_test.py` `run_apply`: while false the job logs `"playlist_test_apply skipped: PLAYLIST_APPLY_ENABLED=false"` and does nothing |
| `PLAYLIST_TEST_DAILY_UNITS` | `:364` `int(os.getenv("PLAYLIST_TEST_DAILY_UNITS") or "2000")` | 2000, `JobBudget` for `playlist_test_apply` (Part 5 Config, E5) | no. Read only by `app/playlist_test.py` `run_apply` |
| `PLAYLIST_TEST_MAX_ATTEMPTS` | `:367` `int(os.getenv("PLAYLIST_TEST_MAX_ATTEMPTS") or "3")` | 3, runs a failing add is retried (Part 5 Config) | no. Read only by `app/playlist_test.py` (`_sendable`); only a `failed` error uses up an attempt (§7.3 item 22) |
| `PLAYLIST_EXPERIMENT_WINDOWS` | `:370` `int(os.getenv("PLAYLIST_EXPERIMENT_WINDOWS") or "4")` | 4, weekly windows before the answer (Part 5 Config, E8) | no. Read only by `app/playlist_test.py` (`measure_channel`, `_answer`): the post weeks measured, and the window of the stop rule and the answer |
| `PLAYLIST_MIN_LIFT` | `:374` `float(os.getenv("PLAYLIST_MIN_LIFT") or "1.0")` | 1.0 starts per playlist per week (Part 5 Config, E8) | no. Read only by `app/playlist_test.py` `measure_channel`: the verdict band (`lever_verdicts.directional`, ±it) and the stop rule's bar on `cumulative_lift` |
| `SHORT_LINK_CHANNELS` | `:379-383` `{c.strip() for c in (os.getenv("SHORT_LINK_CHANNELS") or "UCr5-YUqBiW7PUmeAtxUWuRg").split(",") if c.strip()}` | Marathi, comma list (Part 5 Config, E13) | no. Read only by `app/short_links.py` `run_weekly`, intersected with `TRAFFIC_INGEST_CHANNELS` |
| `SHORT_LINK_TARGETS` | `:385` `int(os.getenv("SHORT_LINK_TARGETS") or "3")` | 3 (Part 5 Config, E10) | no. Read only by `app/short_links.py` `targets` |
| `SHORT_LINK_MIN_FEED_VIEWS` | `:389` `int(os.getenv("SHORT_LINK_MIN_FEED_VIEWS") or "1")` | 1 type-24 view over 28 ingested data-days (Part 5 Config, E9) | no. Read only by `app/short_links.py` `shorts` |
| `SHORT_LINK_MAX_PER_RUN` | `:392` `int(os.getenv("SHORT_LINK_MAX_PER_RUN") or "50")` | 50 Shorts per weekly run (Part 5 Config) | no. Read only by `app/short_links.py` `_plan`: Shorts written per run; Shorts skipped without a vector or a target don't count (§7.3 item 24) |
| `SHORT_LINK_SEEN_MIN_VIEWS` | `:396` `int(os.getenv("SHORT_LINK_SEEN_MIN_VIEWS") or "1")` | 1 type-32 view for a pair to count as set (Part 5 Config, S2.6) | no. Read only by `app/short_links.py` `seen_pairs`, over the target channel's latest 28 ingested traffic data-days |
| `WRITER_MODEL` | `os.getenv("WRITER_MODEL") or AUDIT_MODEL` | = `AUDIT_MODEL`, set from the bake-off (Part 6 Config, F9) | no. Read by `app/titles.py` (`write_candidates`' default model, the title stamp's `writer_model`) and `app/agent/loop.py` (the trajectory's `writer_model`); no longer by the audit stamp (§6) |
| `TITLE_CANDIDATES` | `int(os.getenv("TITLE_CANDIDATES") or "3")` | 3 candidates per writer call (Part 6 Config) | no. Read by `app/titles.py` (`system_prompt`, `_candidates` keeps at most this many) and `app/agent/tools.py` (the `write_candidates` tool's description) |
| `TITLE_MAX_IMPRESSIONS` | `int(os.getenv("TITLE_MAX_IMPRESSIONS") or "5000000")` | 5000000, plus the top 1% (Part 6 Config, F2) | no. Read by `app/titles.py` `_ceiling` (`channel_context.ceiling`), read through the cached `agent_tick.title_channel` by triage's `title_excluded` since S3.3 |
| `TITLE_AGENT_PCT` | `float(os.getenv("TITLE_AGENT_PCT") or "0.5")` | 0.5, 0 = pipeline only (Part 6 Config, F5) | no. Read by `app/titles.py` `title_path`, routed by `titles.route` (S3.3; a closed path hands its videos to the other if that one is open) and, since `a1c3d3c`, by `titles._share` (`path_closed`: 0 closes the agent path, 1 the pipeline) for the tick and the preview |
| `TITLE_CHANNELS` | `{c.strip() for c in (os.getenv("TITLE_CHANNELS") or "UCr5-YUqBiW7PUmeAtxUWuRg").split(",") if c.strip()}` | Marathi, comma list (Part 6 Config, F3) | no. Read only by `app/agent_tick.py` `titles_open` |
| `TITLE_DAILY_CAP` | `int(os.getenv("TITLE_DAILY_CAP") or "10")` | 10 treated title rows per channel per day, inside `autopilot_daily_cap` (Part 6 Config, F4) | no. Read only by `app/agent_tick.py` `_title_enabled`, over `_titles_today` (UTC day, arm `treated`, status not `declined`) |
| `TITLE_AGENT_DAILY_RUNS` | `int(os.getenv("TITLE_AGENT_DAILY_RUNS") or "20")` | 20 agent runs per channel per day, declines included (Part 6 Config, F14) | no. Read only by `app/agent_tick.py` `_title_enabled`, for a video on the agent path: `title` rows with `payload.path = 'agent'` today, any status |
| `TITLE_EXCLUDE_VIDEOS` | `{v.strip() for v in (os.getenv("TITLE_EXCLUDE_VIDEOS") or "").split(",") if v.strip()}` | empty, comma list (Part 6 Config, F12) | no. Read by `app/agent_tick.py` `_assess` (`title_excluded`) and `app/titles.py` `would_title` |
| `AGENT_MAX_TURNS` | `int(os.getenv("AGENT_MAX_TURNS") or "12")` | 12 (Part 6 Config, Part 2 §8) | no. Read only by `app/agent/loop.py` `run_title_agent`: the `chat_tools` calls a run gets before it ends `failed`, `turn_cap` |
| `TITLE_WINDOW_DAYS` | `int(os.getenv("TITLE_WINDOW_DAYS") or "14")` | 14, post window; pre is 14 (Part 6 Config, F6) | no. Read only by `app/title_measurement.py` (`windows`, the decided-row read); the pre is the module's `PRE_DAYS` (14) |
| `TITLE_MIN_PRE_VIEWS` | `int(os.getenv("TITLE_MIN_PRE_VIEWS") or "100")` | 100 browse + suggested views in the pre window, else `insufficient_data` (Part 6 Config, F6) | no. Read by `app/title_measurement.py` `evaluate` and `app/lever_verdicts.py` (`_title_judged`, `_counted`: a `cancelled` row with `pre` at it or over was judged, then put back) |
| `TITLE_MIN_LIFT` | `float(os.getenv("TITLE_MIN_LIFT") or "0.05")` | 0.05, log-ratio verdict band and stop bar (Part 6 Config, F7) | no. Read only by `app/lever_verdicts.py` `title_verdicts` |
| `TITLE_EXPERIMENT_WINDOWS` | `int(os.getenv("TITLE_EXPERIMENT_WINDOWS") or "4")` | 4 (Part 6 Config, F7) | no. Read only by `app/lever_verdicts.py` `title_verdicts` |
| `TITLE_HARM_WINDOWS` | `int(os.getenv("TITLE_HARM_WINDOWS") or "2")` | 2 (Part 6 Config, F7) | no. Read only by `app/lever_verdicts.py` `title_verdicts` |
| `TITLE_HARM_LIFT` | `float(os.getenv("TITLE_HARM_LIFT") or "0.10")` | 0.10 (Part 6 Config, F7) | no. Read only by `app/lever_verdicts.py` `title_verdicts`: cumulative lift ≤ −it stops a path early |
| `TITLE_REVERT_LIFT` | `float(os.getenv("TITLE_REVERT_LIFT") or "0.30")` | 0.30 (Part 6 Config, F8) | no. Read only by `app/lever_verdicts.py` `auto_revert` |
| `TITLE_REVERTS_PER_DAY` | `int(os.getenv("TITLE_REVERTS_PER_DAY") or "10")` | 10 per channel per run (Part 6 Config, F8) | no. Read only by `app/lever_verdicts.py` `auto_revert`: reverts done (a skipped title doesn't count) |
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
AUTOPILOT_PICKER_USE_RPC "false"        # dev .env true; read only by autopilot._next_video_for_channel, which nothing calls since S3.6
AUTOPILOT_PAUSE_COOLDOWN_MINUTES "60"
SHORTS_MAX_CONCURRENT_JOBS "2"  SHORTS_DISPATCH_INTERVAL_SECONDS "5"  SHORTS_YT_DOWNLOAD_ENABLED "false"
SHORTS_MAX_SOURCE_SECONDS "300"  SHORTS_CACHE_DIR "./shorts_cache"  LOG_DIR "logs"  LOG_LEVEL "INFO"
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
`decide.QUESTION_SET_VERSION="2026.11-s3-v1"` (`app/decide.py:39`); `agent_tick.CONTEXT_DAYS=28`, `agent_tick.POOL_TTL_SECONDS=3600` (`app/agent_tick.py`); `lever_measurement.WEEK=7`, `EXTENDED_DAYS=14`, `RESTATEMENT_HORIZON_DAYS=28` (`app/lever_measurement.py`); `playlist_test.MIN_EMBEDDED_MEMBERS=3` (`app/playlist_test.py`); `short_links.FEED_WINDOW_DAYS=28` (`app/short_links.py`); `title_measurement.PRE_DAYS=14`, `SOURCE_TYPES=(3, 7)` (`app/title_measurement.py:58,60`); `agent.loop.TRAJECTORY_CHARS=2000` (`app/agent/loop.py:47`); `agent.tools.SEARCH_TERMS=25`, `TOP_PERFORMERS=10`, `HISTORY=10` (`app/agent/tools.py:31-34`); `titles.DESCRIPTION_CHARS=1500`, `SEARCH_TERMS=10`, `TOP_PERFORMERS=5` (`app/titles.py:58-61`); `reembed.RECIPE="tdt-v1"`, `BATCH_SIZE=50`,
`_BYTES_PER_TOKEN=3`, `JOIN_HIGH_PCTL=50`, `LEAVE_PCTL=10`, `JOIN_LOW_PCTL=5`, `MIN_MEMBER_SIMS=30` (`app/reembed.py:33-51`); `quota.APPLY=(VIDEOS_LIST, VIDEOS_UPDATE)`
= 51u (`app/quota.py:50-67`); `openrouter.EMBED_MODEL="google/gemini-embedding-2-preview"` (`app/openrouter.py:7`).

---

## 4. Scheduled jobs

All registered in `app/main.py:304` `_register_jobs()`, called from `lifespan()` (`app/main.py:560-571`),
`BackgroundScheduler`, each `max_instances=1, coalesce=True`.

**Failure semantics.** `_run_per_channel` (`app/main.py:82-108`) runs every channel, logs each failure at ERROR
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
(`app/main.py:282-291`). `job_status.registry.watch(scheduler)` (`app/main.py:571`) registers every job as
`never_run` and records `status` (`never_run|success|degraded|failed`), `last_run_at`, `error`,
`failed_channels`, `partial_errors`, logging `"JOB FAILED <job_id> at <time>: <error>"` /
`"JOB DEGRADED <job_id> at <time>: …"` (`app/job_status.py:96,103`). In memory only; a restart clears it. Served
at `GET /health/jobs` (`app/main.py:634-637`).

**Freeze flags (A4).** With its flag false a writer is not registered and startup logs
`"<job_id> not registered: <FLAG>=false"`. `playlist_reconcile` always registers; with
`PLAYLIST_RECONCILE_WRITES_ENABLED=false` it runs `sync_playlists` and skips `reconcile_channel`, logging
`"Daily reconcile <id>: add/remove skipped (PLAYLIST_RECONCILE_WRITES_ENABLED=false)"` per channel
(`app/main.py:170-174`) and `"playlist_reconcile registered for sync only: add/remove skipped
(PLAYLIST_RECONCILE_WRITES_ENABLED=false)"` at startup (`app/main.py:335-337`). All four flags default false (§3);
the office startup log confirmed the freeze 2026-09-29 (`docs/PHASE_A_FINDINGS.md` A0).

| Job id | Trigger | Entry point | Status |
|---|---|---|---|
| `autopilot` | interval `AUTOPILOT_TICK_SECONDS` (`app/main.py:314`) | `app/autopilot.py:533` `tick`: quota-dormancy gate → pick channel (`Job.AUTOPILOT` = `can_audit or can_cut_shorts`) → Shorts action → **`agent_enabled` → the agent path** (`_agent_tick`: `can_run_agent` gate, else `agent_ineligible` → neither lever can run (backlinks: `BACKLINK_APPLY_ENABLED` and a heading for the channel's `default_language` in `backlinks.HEADINGS`, `agent_tick.backlinks_enabled`; titles, S3.3: the channel in `TITLE_CHANNELS`, `TITLE_APPLY_ENABLED`, the lever not stopped, `agent_tick.titles_open`) → `apply_disabled` while `BACKLINK_APPLY_ENABLED` is off, else `no_heading`, nothing else runs → `_resync_if_stale` → daily cap → ledger quota gate → `agent_tick.run`: warm pick → triage (backlinks, then `title`, S3.3) → record → treated apply (`apply_backlinks` or, for a title, the path's writer (the pipeline, or since S3.4 the agent, which may decline: no apply) then `apply_title`); never `audit_video`) → every other channel: nothing after the Shorts action (`shorts_only`, the channel touched so the round-robin moves on; the house-format branch, `can_audit` → `audit_video` → validate → apply, and its setting were deleted by S3.6, F13) | registered. On the agent channels (`agent_enabled = autopilot_enabled = t`) it runs the agent path; on every other channel only the Shorts action, whatever `autopilot_enabled` says. `_can_afford_apply` (`app/autopilot.py:450-466`) logs `quota_insufficient` and skips without pausing. The daily cap (`autopilot_daily_cap`, default 10) counts applied audits, `midas` interventions with `applied_at` today, and today's `midas` treated rows that never reached YouTube (`applied_at` NULL: DRY_RUN, a refused render, a YouTube error; for titles since S3.3 also `checks_failed` and `writer_exception`, and since S3.4 an agent run's `turn_cap`; an agent decline, treated `declined`, doesn't count: `_applies_today`'s unsent count leaves out `declined`, F14), so a systematic failure is bounded too (`_applies_today`, `app/autopilot.py`; applied audits count only through the manual routes since S3.6); holdout and declined rows don't count. Titles count toward it like backlinks (S3.3), and also have their own `TITLE_DAILY_CAP`/`TITLE_AGENT_DAILY_RUNS` (§3), which turn triage away from `title` rather than stop the tick. Agent-path apply errors get `_react_to_apply_error` ( quotaExceeded → fleet dormancy, token expiry → pause, `failed` → failure count; `apply_disabled`, `quota_insufficient` → none); anything unclassified (including a title writer that raises) is `agent_failed` and a failure count |
| `shorts_dispatch` | interval `SHORTS_DISPATCH_INTERVAL_SECONDS` (5 s) (`:322`) | `app/shorts/dispatcher.py:dispatch_tick` | registered |
| `playlist_reconcile` | cron 02:00 server-local (`:331`) | `main._daily_reconcile` (`:136`) → `sync_playlists` (shared `JobBudget("playlist_sync", PLAYLIST_SYNC_QUOTA_BUDGET, reserve=YT_QUOTA_APPLY_RESERVE)`) + `reconcile_channel` | registered; channels = `PLAYLIST_RECONCILE_CHANNELS` allowlist (`app/eligibility.py:186-195`). **Add/remove frozen** by `PLAYLIST_RECONCILE_WRITES_ENABLED`; inventory sync and the budgeted membership walk still run. **Human-edit ledger (B3b):** for a playlist walked before (`membership_walked_at` not NULL at plan time), each page's memberships the walk has no `playlist_assignments` row for go to `human_edits.record_playlist_additions` before the walk seeds its `sync` rows (`app/playlists_sync.py:297-328`); a playlist's first walk is the baseline and records none. A ledger error is logged as `"sync_playlists <id>: human-edit ledger failed; walk continues: <err>"` and never fails the walk (`_record_human_memberships`, `app/playlists_sync.py:361-370`). The manual `POST /channels/{id}/playlists/bootstrap` runs the same walk (`app/playlists_router.py:192`) |
| `playlist_discovery` | cron Sun 03:00 local (`:345`) | `main._weekly_discovery` → `app/playlist_discovery.py:152` `discover_playlists` | **frozen** (`PLAYLIST_DISCOVERY_ENABLED`). When on: every channel; **creates playlists** (≤2/run), skipped under `DRY_RUN` |
| `reflection` | cron Mon 04:00 local (`:358`) | `app/reflection.py:702` `reflect` | **frozen** (`REFLECTION_ENABLED`). When on: every channel |
| `playlist_tuning` | cron Mon 03:30 local (`:371`) | `app/playlists.py:463` `tune_thresholds` | **frozen** (`PLAYLIST_TUNING_ENABLED`). When on: writes `settings.PLAYLIST_JOIN_HIGH` process-globally (`app/playlists.py:518`) |
| `video_sync` | cron 04:00 UTC (`:386`) | `main._daily_video_sync` (`:248`) → `app/sync.py:546` `routine_sync` per channel | registered, every channel. Read-only: `"fresh"` if synced within 6 h, else a full pass if the last full sync is >3 days old, else incremental + `refresh_stats`. An expired or revoked token is an expected skip, logged `"video_sync <id>: OAuth token expired; skipping until re-consent"`; since fleet readiness the run then returns `{"partial_errors": {<id>: "token_expired: re-consent needed"}}`, so it records `degraded` rather than `success`; any other error, including a YouTube 401 that isn't a token failure, fails the channel. The skip works because `sync_channel`, `refresh_stats` and `refresh_applied_stats` are wrapped by `_token_failure_as_401` (`app/sync.py:54`), which turns a `TokenExpiredError` from anywhere in the call (at `youtube_for_channel`, or mid-call from the `yt_*` helpers' `invalid_grant` check, `app/youtube_client.py:63-66`) into `TokenExpired` (`app/sync.py:41`): an `HTTPException(401, "token_expired")` that is also a `TokenExpiredError`. Before B8 these raised a plain `HTTPException(401)`, which failed the run (2026-10-06, Hindi, §8). The autopilot resync catches the same type (`app/autopilot.py:413`). **Human-edit ledger (B3a):** a full pass also reads the stored descriptions and, before the videos upsert, hands every re-read (id, stored, fetched) description to `human_edits.record_description_edits` (`app/sync.py:262-265,288-297`). A ledger error is logged as `"sync <id>: human-edit ledger failed; sync continues: <err>"` and never fails the sync; a per-video error is logged `"human_edits <channel>: ledger failed for <video>: <err>"` and the other videos still run. Incremental passes re-fetch no known video, so they record nothing |
| `metrics_poll` | cron 05:00 UTC (`:407`) | `app/metrics_poll.py:poll_metrics` | registered; `analytics_authorized` channels; videos only if in a measurement window (`METRICS_POLL_MEASURED_ONLY`) |
| `reporting_poll` | cron 06:00 UTC (`:426`) | `app/reporting_poll.py:poll_reporting` | registered; `analytics_authorized AND (measurement_enabled OR reach_warmup)` (`app/eligibility.py:154-168`). Ingests only `channel_reach_basic_a1` |
| `traffic_poll` | cron 06:30 UTC (`:440`) | `app/traffic_poll.py:173` `poll_traffic` | registered; `analytics_authorized` channels in `TRAFFIC_INGEST_CHANNELS` (`app/eligibility.py:170-178`). Two feeds per channel (`_FEEDS`, `app/traffic_poll.py:74`): **video** ensures the `channel_traffic_source_a3` job (`midas-traffic-source`, Marathi `3647f5d8…`) → `video_traffic_source_daily`; **playlist** ensures the `playlist_traffic_source_a2` job (`midas-playlist-traffic-source`, Marathi `381cf084…`) → `playlist_traffic_daily`. Both Marathi jobs are found, not created. Each feed ingests each data-day's newest not-yet-ingested report, a restatement replacing the day (`app/traffic_poll.py:89` `_newest_per_day`, `app/reporting_poll.py:104` `replace_data_day`), and ledgers it with its own `report_type`. Logs `"traffic_poll <id> data-day <d>: <n> rows written to <table> (report <r>)"` (`app/traffic_poll.py:118`). Feeds are isolated (`_poll_channel`, `app/traffic_poll.py:155`): a feed crash is recorded as `"<feed>: <Type>: <msg>"` and fails the channel, but the other feed still runs; per-report errors are judged per feed (categories `video reports`, `playlist reports`). Independent of `reporting_poll` |
| `playlist_health_score` | cron 07:00 UTC (`:459`) | `main._daily_playlist_health_score` (`:225`) → `app/playlist_health.py:score_channel` | registered; `playlist_health_enabled` channels (Punjabi only, §1) |
| `measurement_eval` | cron 08:00 UTC (`:474`) | `main._daily_measurement_eval` → `app/measurement.py:evaluate_with_failures` | registered |
| `lever_measurement` | cron Mon 09:00 UTC (`app/main.py` `_register_jobs`) | `app/lever_verdicts.py` `run_weekly` | registered (S1.6b). Every channel (`Job.EVERY`): `lever_measurement.measure_channel` (S1.6a), then `write_verdicts` for the current week. `traffic_poll`'s failure model: a channel that raises fails the run once every channel has run (`JobRunFailed("lever_measurement", …)`); per-row errors go through `job_status.item_error_verdict` under the category `interventions` (all errored → the channel fails as `"ItemsFailed: interventions: all <n> failed"` and gets no verdicts that run, some → `degraded`). **S2.3:** then, for a channel with any `playlist_arms` row (read once per run), `playlist_test.measure_channel`, under its own category `playlist arms` (`"ItemsFailed: playlist arms: all <n> failed"`, `"playlist arms: <e>/<n> failed"`) and its own `try`: a crash or failure in either half doesn't stop the other on the same channel, and both halves' messages are joined with `; `. A failed `playlist_arms` read (the table is missing until `20261027000000` is applied) is logged `"lever_measurement: playlist_arms unreadable; playlist test skipped: <err>"` and skips only the playlist half that run. **S2.6:** on a channel in `TRAFFIC_INGEST_CHANNELS`, first `short_links.detect` (the Short links seen in its type-32 traffic, §5), under its own category `short-link pairs` (`"ItemsFailed: short-link pairs: all <n> failed"`, `"short-link pairs: <e>/<n> failed"`) and its own `try`, so the measurement still runs; the measurement then covers `short_link` rows too (same `interventions` category), and after backlinks' verdicts `write_verdicts(lever='short_link')`. A channel with a type-32 pair fails the detection reading `short_link_recommendations` until `20261027010000` is applied. **S3.5:** on a channel with any `midas` `title` row (`_has_titles`, a `limit(1)` read), after backlinks and before the playlist test, in its own `try`: `title_measurement.measure_channel` under the category `title interventions` (`"ItemsFailed: title interventions: all <n> failed"` and no title verdicts that run), then `write_verdicts(lever='title')`, then `auto_revert` under `title reverts` (`"ItemsFailed: title reverts: all <n> failed"`, `"title reverts: <e>/<n> failed"`); a crash in the title half is logged `"lever_measurement <id>: titles crashed: …"` and fails the channel without stopping its other halves. Nothing reaches YouTube except the auto-revert's title writes (`titles_apply.revert_title(auto=True)`, behind `TITLE_APPLY_ENABLED` and `DRY_RUN`) |
| `channel_health` | cron 10:00 UTC (`app/main.py` `_register_jobs`) | `app/channel_health.py` `run_daily` | registered (fleet readiness, not in the spec). Read-only: `check()` over every channel, and `JobRunFailed("channel_health", {<id>: "<problems>"})` when any channel has one: `last_synced_at` older than `SYNC_STALE_HOURS` (30) or NULL, a reach frontier (`Job.REACH` channels) more than `REACH_STALE_DAYS` (7) behind or none, a `channel_traffic_source_a3` frontier (`Job.TRAFFIC` channels) more than `TRAFFIC_STALE_DAYS` (4) behind or none, or a non-NULL `autopilot_paused_reason`. A channel with no row in `videos` is listed with `no_videos: true` and no problems (Kannada and Telugu, no uploads on 2026-10-26). Exists because the 2026-10-16 sign-in outage left every job `success` for a week |
| `playlist_test_apply` | cron 11:00 UTC (`app/main.py` `_register_jobs`) | `app/playlist_test.py` `run_apply` | registered (S2.2), always; does nothing while `PLAYLIST_APPLY_ENABLED` is false (default). Otherwise, per channel with a treated `playlist_arms` row `planned` or `applying` (`apply_channel`), a playlist at a time in arm id order: its approved, unsent adds with attempts left go together only if n × 50u fits both `JobBudget("playlist_test_apply", PLAYLIST_TEST_DAILY_UNITS)` and `quota.can_afford(…, reserve=YT_QUOTA_COLLECTION_RESERVE)`, else the job stops for the day. Each add is `yt_playlist_items_insert` at position = the number of the arm's adds ahead of it in rank (`proposal_ids` order) already in the playlist; a 400 naming the position or sort order is retried once appended, and from then on (this run and later ones, read off `apply_error.reason = 'position_refused'`) that playlist's adds go appended. Success → the proposal's `applied_at`, `playlist_item_id`, and a `playlist_assignments` `added` row with `decision_source = 'experiment'` (`playlists._record_assignment`). Errors classified as `backlinks_apply._classified`: `failed` uses up an attempt (at most `PLAYLIST_TEST_MAX_ATTEMPTS`); `youtube_quota_exceeded` stops the job and makes the channel `degraded` (`"youtube_quota_exceeded: stopped for the day"`), never counted as an errored add; `token_expired` stops the channel and fails it. Arm status settles after each arm (§2 `playlist_arms`). `DRY_RUN` logs `"[DRY_RUN] playlist_test_apply <id>: would add […] to the top of <playlist>"` and writes nothing. `traffic_poll`'s failure model: a channel that raises fails the run once every channel has run (`JobRunFailed("playlist_test_apply", …)`); per-add errors through `job_status.item_error_verdict` under `playlist adds` |
| `short_link_refresh` | cron Mon 10:30 UTC (`app/main.py` `_register_jobs`) | `app/short_links.py` `run_weekly` | registered (S2.4), always. `refresh` for every channel in `SHORT_LINK_CHANNELS` ∩ `TRAFFIC_INGEST_CHANNELS` (none: logs `"short_link_refresh: no channels (SHORT_LINK_CHANNELS ∩ TRAFFIC_INGEST_CHANNELS); nothing to do"`). `traffic_poll`'s failure model: a channel that raises fails the run once every channel has run (`JobRunFailed("short_link_refresh", …)`); per-Short write errors through `job_status.item_error_verdict` under `shorts` (`"ItemsFailed: shorts: all <n> failed"`, `"shorts: <e>/<n> failed"`). A channel whose thresholds are refused writes nothing and is `degraded` (`"refused: no_thresholds"` or `"refused: thresholds_other_model_version"`). DB and OpenRouter (the shadow next-watch) only; nothing reaches YouTube. Until `20261027010000` is applied, a channel with listed Shorts fails reading the table |
| `nightly_db_backup` | cron `BACKUP_HOUR` local (`:541`) | `app/backup.py:run_nightly_backup` | registered; no-op if `BACKUP_ENABLED=false` |
| `pot_provider_refresh` | interval 2 h (`:553`) | `main._refresh_pot_provider` | only if env `BGUTIL_POT_HTTP_BASE_URL` is set; absent on the office machine (`docs/PHASE_A_FINDINGS.md` A0 step 12) |

Startup side effects: `provision.ensure_database_populated()` (restore from NAS if the DB is empty,
`app/main.py:566`), `shorts.runner.reap_stuck_jobs()` (`:572-575`), `tracing.configure()`.

Spec'd jobs not registered: `niche_reference_refresh` (Part 2 §3.6) and playbook rebuild (Part 2 §1.1, §5).

---

## 5. Surface area

**Routes** (`app/main.py:596-613` mounts every router):

- **Pages/health:** `GET /` → `static/index.html`; `GET /channel` → `static/channel.html`; `GET /health` → `{"ok": True, "dry_run": …}`; `GET /health/jobs` → `{"jobs": {<job_id>: {status, last_run_at, error, failed_channels, partial_errors}}}`; `GET /health/channels` (`app/channel_health.py`) → `{"checked_at", "with_problems", "channels": [{id, name, last_synced_at, reach_days_behind, traffic_days_behind, autopilot_paused_reason, no_videos, problems}]}`, channels with problems first, read from the DB; `GET /autoshorts` (`app/shorts/autoshorts.py:85`); `/static/*`.
- **Auth/channels** (`app/auth.py`, prefix `/auth`): `GET /auth/login`, `GET /auth/callback` (stores tokens, sets `analytics_authorized` from granted scopes, clears the `token_expired` pause), `GET /auth/channels`, `PATCH /auth/channels/{id}` (enabling `measurement_enabled` returns 409 unless `reach.certify` passes, `app/auth.py:166-174`).
- **Sync** (`app/sync.py`): `POST /channels/{id}/sync?full=`, `POST /channels/{id}/refresh-stats`, `POST /channels/{id}/refresh-applied-stats`, `GET /channels/{id}/videos`, `GET /videos/{id}`.
- **Audits** (`app/audits.py`): `GET|POST /channels/{id}/audit-config`, `POST /channels/{id}/audit-config/elaborate`, `POST /videos/{id}/audit`, `GET /videos/{id}/audits`, `POST /audits/{id}/apply?force=`, `POST /channels/{id}/audits/apply-pending?force=` (since S3.6 both answer 409 `"agent channel: a house-format apply replaces the description and its backlink block; pass force=true"` on a channel with `agent_enabled` unless `force=true`, before anything is sent or written: the single apply inside `apply_audit_internal`, after it reads the channel; apply-pending once, reading the channel before any apply, then passing `force` on to each `apply_audit_internal`; `audits._refuse_on_agent_channel`, `AGENT_CHANNEL_REFUSED`; a non-agent channel answers as before), `POST /channels/{id}/audits/reaudit-quarantined`, `POST /channels/{id}/audits/run-bulk` (it and `reaudit-quarantined` only call `audit_video`, which writes a `pending` audit and nothing to YouTube, so neither is guarded), `POST /audits/{id}/revert` (409 `"agent channel: an audit revert replaces the description and its backlink block; pass force=true"` on an `agent_enabled` channel unless `?force=true`, `_refuse_on_agent_channel`, since it restates the whole snippet from the before-state (owner, 2026-10-30, Slice 3 final review); 409 `"quota_insufficient: revert needs <n> units, <m> remaining today"` when `quota.can_afford(quota.cost(Op.VIDEOS_UPDATE))` is false, `app/audits.py:847-852`), `GET /quota-cost-preview`.
- **Measurement** (`app/measurement.py`): `GET /audits/{id}/measurement`, `GET /channels/{id}/outcomes`, `POST /measurement/evaluate`.
- **Reflection** (`app/reflection.py`): `GET /channels/{id}/reflection/history`, `POST /channels/{id}/prompt-versions/{vid}/promote`, `POST /channels/{id}/reflection/trigger`, `GET /channels/{id}/reflection/shadow-comparison`. Promote and trigger return 409 `"Reflection is frozen: REFLECTION_ENABLED=false"` while frozen (`_require_reflection_enabled`, `app/reflection.py:792`).
- **Playlists** (`app/playlists_router.py`): `POST /channels/{id}/playlists/evaluate`, `GET /channels/{id}/playlists/health`, `POST /channels/{id}/playlists/bootstrap` (sync + embed all), `GET /channels/{id}/playlists/status`, `POST /channels/{id}/playlists/reconcile` (409 `"Playlist reconcile writes are frozen: PLAYLIST_RECONCILE_WRITES_ENABLED=false"`, `:263-267`), `GET /channels/{id}/playlists/proposals` (every `pending` proposal of the channel's playlists, through `all_rows`/`rows_for_ids`, those with `arm_id` first, then by `proposed_at`, then `id`; since 2026-10-26), `POST /channels/{id}/playlists/proposals/decide` (executes adds/removes on YouTube; not frozen; `rejected` relabels only `pending` proposals and returns their count, since the Slice 2 follow-ups; since S2.2 a proposal with `arm_id` set is only marked `approved`/`rejected` with `decided_at` and sends nothing, and the response gains `queued` (their count) only when there were any).
- **Autopilot** (`app/autopilot.py`): `POST /channels/{id}/autopilot/resume`, `GET /channels/{id}/autopilot/log`.
- **Interventions** (`app/backlinks_apply.py`): `POST /interventions/{id}/revert`, for an applied (`applied_at` set, not `cancelled`) `midas` `backlinks` or (since S3.1) `title` intervention only (else 400: `"Only an applied Midas title intervention can be reverted"` for a `title` row `revert_title` refuses (`ValueError`), `"Only an applied Midas backlinks intervention can be reverted"` for any other; 404 unknown). A `title` row goes to `titles_apply.revert_title(row, auto=False)` (§5 Modules `titles_apply.py`): 409 `"apply_disabled"` while `TITLE_APPLY_ENABLED` is false, 409 `"quota_insufficient: revert needs <n> units, <m> remaining today"`, under `DRY_RUN` `{"status": "dry_run", "title": <before_state.title>}`, 409 `"title_changed"` when the live title isn't `payload.title`, else `{"status": "cancelled", "title"}`. For a `backlinks` row: Fetches the live snippet, `backlinks.strip`s it and sends it back `part=snippet` with only `description` changed (no update if no block is left); 409 `"apply_disabled"` while `BACKLINK_APPLY_ENABLED` is false, 409 `"quota_insufficient: revert needs <n> units, <m> remaining today"` when `quota.can_afford(quota.cost_of(*quota.APPLY))` (51u) is false; under `DRY_RUN` it returns `{"status": "dry_run", "description": <stored, stripped>}` and writes nothing. Sets `status = 'cancelled'`, `payload.revert = {reverted_at, live_before, description}`, and `videos.description`.
- **Interventions and verdicts** (`app/lever_verdicts.py`, S1.6b): `GET /channels/{id}/interventions?lever=&status=&limit=&offset=` → `{"interventions": [...], "limit", "offset", "next_offset"}`, newest first (`created_at` desc, then `id` desc), one page of `limit` rows (default 100, at most 1000 = `rows.PAGE_SIZE`; 422 above), `next_offset` set whenever a page comes back full (so an exactly full last page points at one more, empty page); an unknown `lever` or `status` (not in `status_vocab`) is 400. `GET /channels/{id}/lever-verdicts` → `{"verdicts": [...], "backlinks_stopped": bool}`, every `lever_verdicts` row of the channel (`all_rows`), newest week first, `playlist` rows included.
- **Title test** (`app/lever_verdicts.py`, S3.5): `GET /channels/{id}/title-test` → `{"paths": {"pipeline"|"agent": {treated (arm `treated` with `applied_at`), declined (arm `treated`, no `applied_at`, not `cancelled`/`planned`), cancelled ({reason: n}: `payload.error.reason`, `reverted` for a title put back, `unknown` with neither, `app/lever_verdicts.py:629-630`), judged (rows in the path's mean), insufficient, mean_delta, cumulative_lift (path mean − holdout mean over every judged row), auto_reverts (`payload.revert.auto`), stopped}}, "holdout": {n, judged, mean_delta}, "trace": {runs, most_common, share_differing, share_calling: {tool: share}}}`: the channel's `midas` `title` rows through `all_rows` (with `trajectory`, so the read needs `20261030000000` applied); `trace` over the agent-path rows with a trajectory, the tools each called (`agent.loop.tools_called`) as a set: the most common set, the share of runs with another, the share calling each tool. Read-only, nothing judged.
- **Playlist test** (`app/playlist_test.py` `router`, S2.3): `GET /channels/{id}/playlist-test` → `{"test_start", "test_end", "arms": [...], "verdicts": [...], "answer"}`: `test_dates` as ISO dates (None until dosed), every `playlist_arms` row of the channel, its `lever = 'playlist'` `lever_verdicts` rows oldest week first, and `answer` `pending` until a `treated_vs_holdout` row with `windows_judged` ≥ `PLAYLIST_EXPERIMENT_WINDOWS`, then `no` if it triggered the stop rule, else `yes`. Read-only.
- **Short links** (`app/short_links.py` `router`, S2.5). Nothing here reaches YouTube. `GET /channels/{id}/short-links?status=&limit=&offset=&format=` → `{"shorts": [{short_id, title, youtube_url, studio_url, feed_views, recommendations: [{id, rank, target_video_id, title, youtube_url, similarity, impressions, feed_views, status, decided_at, intervention_id}]}], "limit", "offset", "next_offset"}`: one page of the channel's Shorts (not rows), those with a `pending` row first, then by feed views, then id, each with its rows in rank order; `youtube_url` is `https://www.youtube.com/shorts/<id>` (Short) or `https://www.youtube.com/watch?v=<id>` (target), `studio_url` `https://studio.youtube.com/video/<id>/edit`; titles from `videos`. `status` keeps only the rows in it and the Shorts that have one; unknown `status` 400; `limit` default 100, at most 1000 (422 above), `next_offset` as `GET /channels/{id}/interventions`. `format=csv` (`json` default; anything else 422) returns the same page as `short-links-<id>.csv`, one line per recommendation, titles starting with `=`, `+`, `-`, `@`, tab or CR prefixed with `'` (`_cell`, so a spreadsheet doesn't run them) (`short_id, short_title, short_url, studio_url, feed_views, recommendation_id, rank, target_video_id, target_title, target_url, similarity, impressions, status, decided_at`). `POST /short-links/{id}/set` (404 unknown): a row already `set` → no write, `recorded: false`; else `interventions.record` (the human row, §2 `interventions` S2.5) under `_episode_key` (the pair key, or `<pair key>:<n>` when another target of the Short was ticked after the pair's latest row), or, for a key already stored, that row's id; then the Short's other `pending`/`set` rows → `not_chosen` with `decided_at` (a `dismissed` one stays), then this row → `set` with `decided_at` and `intervention_id`; → `{"recommendation", "intervention_id", "recorded"}`. `POST /short-links/{id}/dismiss` (404 unknown; 409 `"set: tick another target to change the Short's link"` on a `set` row): → `dismissed` with `decided_at`, no intervention; an already `dismissed` row is returned unchanged; → `{"recommendation"}`.
- **Ops:** `GET /dashboard` (`app/dashboard.py:94`), `GET /quota` (`app/quota.py:295`), `GET /channels/{id}/performance`, `/performance/summary`, `/performance.csv` (`app/performance.py`).
- **Shorts** (`app/shorts/routes.py`, prefix `/shorts`): `POST|GET /shorts/jobs`, `POST /shorts/cut`, `GET /shorts/languages`, `POST /shorts/jobs/clear-failed`, `GET /shorts/jobs/{id}`, `GET /shorts/clips/{id}/file`, `POST /shorts/clips/{id}/upload`, `POST /videos/{id}/short`; `POST /autoshorts/jobs` (`app/shorts/autoshorts.py:49`).

**Modules** (`app/`):

| File | Owns |
|---|---|
| `main.py` | FastAPI app, logging, job registration, per-channel fan-out, `video_sync` wrapper |
| `job_status.py` | `JobRunFailed`, `item_error_verdict`, in-memory registry behind `/health/jobs` |
| `channel_health.py` | fleet readiness: per-channel freshness from the DB (`check`, `channel_status`, `run_daily`), `GET /health/channels`, the `channel_health` job (§4) |
| `config.py` | `Settings` (env) |
| `db.py` | thread-local PostgREST (`supabase-py`) client with retry. The app talks to Postgres only via PostgREST on `SUPABASE_URL` |
| `rows.py` | the 1000-row cap: `all_rows`, `all_rows_parallel`, `rows_for_ids` |
| `channel_audits.py` | `audits_for_channel`; `fetch_all` is a deprecated alias of `rows.all_rows` |
| `eligibility.py` | which channels each job runs for (`Job.*`, `can_audit`, `can_cut_shorts`, `has_work`); `can_run_agent` (S1.4b: `can_audit` and `agent_enabled` and `reach.certify`, the last read last) |
| `status_vocab.py` | persisted status strings and their mirrors (guarded by `tests/test_status_vocab.py`) |
| `auth.py` | OAuth + channel flag PATCH |
| `sync.py` | video sync, `is_short` probe, stats refresh, routine-sync rules (`is_stale`, `needs_full_sync`, `routine_sync`); token failures in its routes → `TokenExpired` (401 `token_expired`); full syncs feed the human-edit ledger (`_record_human_edits`) |
| `content_type.py` | `is_episode` classifier |
| `audits.py` | `DEFAULT_PROMPT`, `_build_user_block`, strategy stamp, `audit_video`, apply, revert, bulk ops; since S3.6 no autopilot caller (only the routes call `audit_video` and `apply_audit_internal`), and `_refuse_on_agent_channel(channel, force=)`, the 409 guard of the house-format applies on an `agent_enabled` channel (§5 Routes) |
| `audit_suggestion.py` | LLM output contract: decode, 15-hashtag cap, `rejection()`, `house_format_spec()` |
| `apply_outcome.py` | typed `ApplyError`/`ApplyOutcome`; S1.3 adds `QUOTA_INSUFFICIENT` (`quota_insufficient`) and `APPLY_DISABLED` (`apply_disabled`), both 409, the backlinks write's refusals before anything is sent |
| `backlinks_apply.py` | Slice 1 S1.3: `apply_backlinks(intervention)` for a `planned`, `treated`, `midas` `backlinks` row with `payload.targets` (else `ValueError`). Refuses `apply_disabled` while `BACKLINK_APPLY_ENABLED` is false; under `DRY_RUN` renders onto the stored description and returns `{"status": "dry_run", "description"}` with no YouTube call and no write; then the ledger gate (`quota_insufficient` unless `quota.APPLY`, 51u, is affordable). Fetches the live snippet (`yt_videos_list_full`, 1u), renders the block onto the live description (`backlinks.render`, the channel's `default_language`), and sends `videos.update` `part=snippet` with the fetched snippet, only `description` replaced (`yt_videos_update`, 50u). A live description that differs from the stored one goes to `human_edits.record_description_edits` first, so a team edit since the last sync is still recorded. Success: the row becomes `measuring` with `applied_at`, `before_state = {description: <live>}`, `payload.description` = the rendered text; `videos.description` = the rendered text. YouTube failures are typed (`token_expired`, `youtube_quota_exceeded`, `failed`; a refused render or a video gone is `failed`) and change no row: recording the failure is the caller's (`app/agent_tick.py`, S1.4b, records it `cancelled`). Also the revert route (§5 Routes). Called by `agent_tick.run` for a treated row. `_live_snippet` (the 1u fetch, `failed` for a video gone) and `_send_snippet` (the `part=snippet` send) are shared with `titles_apply.py` (S3.1) |
| `titles_apply.py` | Slice 3 S3.1, the title-only write and its revert (Part 6 S3.1, F1), the twin of `backlinks_apply.py` for `snippet.title`. `apply_title(intervention)` for a `planned`, `treated`, `midas` `title` row with `payload.title` and `payload.title_before` (else `ValueError`): refuses `apply_disabled` while `TITLE_APPLY_ENABLED` is false; under `DRY_RUN` returns `{"status": "dry_run", "title"}` with no YouTube call and no write; then the ledger gate (`quota_insufficient` unless `quota.APPLY`, 51u, is affordable: `"title apply needs <n> units"`); fetches the live snippet (`backlinks_apply._live_snippet`, 1u); a live title other than `payload.title_before` refuses `ApplyError(FAILED, "title_changed")` and sends nothing; else sends `videos.update` `part=snippet` with the fetched snippet, only `title` replaced (`_send_snippet`, 50u). Success: `measuring`, `applied_at`, `before_state = {title: <live>}`; `videos.title` = the new title; returns `{"status": "measuring", "title"}`. YouTube failures typed by `backlinks_apply._classified`; a failure changes no row. `revert_title(intervention, *, auto)` for an applied (not `cancelled`) `midas` `title` row with `before_state.title` (else `ValueError`): the same gates (kill switch, `DRY_RUN`, 51u), then the same write putting `before_state.title` back, only if the live title is still `payload.title` (else `HTTPException(409, "title_changed")`, nothing sent); `cancelled`, `payload.revert = {reverted_at, live_before, title, auto}`, `videos.title`. `apply_title` is called by the agent tick (`app/agent_tick.py:525`, S3.3); `revert_title` by `POST /interventions/{id}/revert` (`auto=False`, `app/backlinks_apply.py:204`) and `lever_verdicts.auto_revert` (`auto=True`, `app/lever_verdicts.py:378`, S3.5) |
| `titles.py` | Slice 3 S3.2, the title lever's writer and its checks (Part 6 S3.2, Part 2 §2.4, §3.3, P5, F9, F12); S3.3 adds the routing (below), S3.4 the agent's prompt and its preview, S3.5 extends it. Reads only, except `strategy_version` (its `audit_strategies` row). `channel_context(channel_id)` → `ChannelContext(channel_id, language, reach, median_ctr, ceiling, top_performers)`: the warm long videos (`warm.warm_impressions` minus `is_short` true, `rows_for_ids`), each one's (impressions, CTR) over the latest `WARM_WINDOW_DAYS` reach data-days (`reach.weighted_ctr`), their median CTR, the ceiling (`ceil(0.01 × n)` most-impressed plus any over `TITLE_MAX_IMPRESSIONS`), and the `TOP_PERFORMERS` (5, plus one spare) with the most browse (3) + suggested (7) views over the latest 28 ingested `channel_traffic_source_a3` data-days per warm-window impression, among those with a title in `videos`. `context(video, *, channel=None)` → `{video_id, title, description (first 1,500 characters), transcript (the `video_transcripts` cache only, `_transcript`), default_language, impressions, ctr (agent_tick._reach), channel_median_ctr, traffic_mix_28d (agent_tick._traffic_mix), search_terms (the video's top 10 type-5 source_detail by views over the 28 traffic data-days, blank detail left out), top_performers (the video itself left out)}`. `system_prompt()` = `TITLE_PROMPT` with `TITLE_MAX` and `TITLE_CANDIDATES` filled in (§6). `write_candidates(ctx, *, model=None, failures=None)` → `chat_json(<user block>, model=model or WRITER_MODEL, system=system_prompt(), label="titles.write")`, the reply's first `TITLE_CANDIDATES` `{title, reason}`, titles stripped (a malformed reply → `[]`); `failures` (`{title, failure}`) add a block telling the model which candidates failed which check. `check(title, video)` → the first failure or None: `length` (empty after stripping, or over `TITLE_MAX` = 100), `characters` (`<`, `>` or a line break, which YouTube refuses in a title), `unchanged` (equal to the current title after whitespace collapse and casefold), `script` (not `en`: no character of `SCRIPTS[language]`, or no script known for the language), `hashtags` (more `#` than the current title), `url` (`https?://`, `www.`, `youtu.be/`, `youtube.com/`). `SCRIPTS`: `mr`/`hi`/`bgc` Devanagari U+0900–U+097F, `gu` Gujarati U+0A80–U+0AFF, `pa` Gurmukhi U+0A00–U+0A7F, `ta` Tamil U+0B80–U+0BFF, `ml` Malayalam U+0D00–U+0D7F, `kn` Kannada U+0C80–U+0CFF, `te` Telugu U+0C00–U+0C7F (every `backlinks.HEADINGS` language but `en`). `pipeline(video, *, channel=None, model=None)` → `Written(title, reason, candidates, failures)`: the first candidate passing `check`, else one retry with the failures, else `title`/`reason` None and `failures` = `attempt <n>: '<title>': <failure>` per candidate, or `attempt <n>: malformed reply: no candidates` (`MALFORMED`) per empty attempt; `candidates` carries every candidate with its `check` and `attempt`. `title_path(video_id)`: sha256 of `video_id + "\|title-path"`, first 8 bytes as a point in [0, 1), `agent` below `TITLE_AGENT_PCT`, else `pipeline` (`PATHS`). `strategy_inputs(path)` → (`<STRATEGY_LABEL>-<audits._strategy_hash(inputs)>`, `{lever: "title", path, prompt_sha256 (of system_prompt(), or since S3.4 of agent_system_prompt() on the agent path), writer_model, decision_question_set_version}`, plus `agent_model` (`AUDIT_MODEL`) on the agent path since S3.4), pure; `strategy_version(path)` upserts its `audit_strategies` row once per process (`status 'champion'`, `ignore_duplicates`, as `audits._stamp_strategy`; since S3.4 the agent path's row has `prompt_template` `code:app/titles.py AGENT_PROMPT` and `model` `AUDIT_MODEL`). **S3.3:** `path_stopped(channel_id, path)`: whether a path's stop rule has fired, since S3.5 `lever_verdicts.stopped(channel_id, 'title', TITLE_SCOPES[path])`; `path_closed(channel_id, path)` (`a1c3d3c`): `path_stopped`, or the path has no share (`_share`: `TITLE_AGENT_PCT` for the agent, 1 − it for the pipeline, ≤ 0), so a path nobody switched on, which never gets verdicts, can't keep the lever open; `stopped(channel_id)`: both paths closed; `route(channel_id, video_id)`: `title_path`, handed to the other path when that one is closed and the other isn't, else unchanged (the tick's and the preview's path). `would_title(video_id, channel)`: `decide.TRIAGE.rules` on the video's title keys alone (`backlinks_enabled` false, `title_enabled` true, `title_excluded` = the ceiling or `TITLE_EXCLUDE_VIDEOS`, its CTR and the median). `title_answers(channel_id, n, *, pick=True)`: the channel context (`agent_tick.title_channel`, the cached one) and the first `n` videos `TRIAGE.rules` sends to titles: with `pick`, in `warm.warm_pool` pick order, each on the tick's full context (`agent_tick._assess(…, titles_on=True)`: backlinks as the tick sees it, so backlinks still wins, and the title lever taken as open whatever `TITLE_APPLY_ENABLED`, `TITLE_CHANNELS` and the daily limits say); with `pick=False` every warm long video by impressions through `would_title` (the pick's exclusions ignored; the bake-off's sample). `preview(channel_id, n, *, path)`: per title answer `{video_id, title, answer, impressions, ctr, channel_median_ctr, arm (interventions.assign_arm(…, 'title')), path (treated only, `route`), written (the pipeline's Written, treated on the pipeline path), agent (since S3.4, the agent's `AgentResult`, treated on the agent path, `run_title_agent(…)`), note ("on the <path> path"), error}`; no decide(), no interventions, no YouTube |
| `youtube_metadata.py` | `videos.update` payload; `_NON_ISO_639_1 = {"bgc": "hi", "bho": "hi", "raj": "hi"}` (`:58-64`; `bho`/`raj` unused for now, B7) |
| `youtube_client.py` | Data API wrappers + quota charging; `yt_playlist_items_insert` takes an optional `position` (S2.2), sent as `snippet.position` only when given; `channel_credentials` (#56): a channel's stored creds with `expiry` from `channels.token_expiry` (NULL = expired), refreshed and saved when expired, shared with `analytics_client` |
| `quota.py` | unit-cost table, daily ledger, `JobBudget`, `/quota` |
| `analytics_client.py` | on-demand Analytics (views/retention, playlist session metrics); `analytics_creds_for_channel` = the `analytics_authorized` gate + `youtube_client.channel_credentials` (also used by the Reporting API) |
| `reporting_client.py` / `reporting_poll.py` | Reporting API jobs (`ensure_job` per report type; `ensure_reach_job`, `ensure_traffic_job`, `ensure_playlist_traffic_job`), CSV parsing (reach; video and playlist traffic with aggregation, `_aggregate_traffic_csv`, and the `TRAFFIC_SOURCE_TYPES` code→name table), reach ingestion → `video_reach_daily`, `video_metrics` backfill; the shared latest-wins day replace (`replace_data_day`, `superseded_reports`, `record_ingested`); `download_report_csv` retries a dropped connection (`_DOWNLOAD_TRANSIENT`, `DOWNLOAD_ATTEMPTS` = 3, pauses 1 s then 2 s; #57) and refreshes the token once on a 401 |
| `human_edits.py` | B3a human-edit ledger, description links: `video_links` (11-character ids from `watch?v=`, `youtu.be/`, `shorts/`, `embed/`, `live/`, `v/` URLs), `made_by_midas` (the description equals an applied audit's `suggested_description` or a reverted one's `description_before`, whitespace collapsed; or, S1.3 `_midas_block`, its links to our videos, other than itself, are exactly the targets of a `treated` `midas` `backlinks` intervention with `applied_at` set, not `cancelled`), `record_description_edits` (diff, keep targets in `videos` on any channel, write `human` backlinks rows with a `ledger_key`, stamp removals on the earlier row). Called only from `sync_channel` on a full sync. B3b, playlist memberships: `added_by_midas` (a `playlist_assignments` `added` row whose `decision_source` isn't `sync`, i.e. `embedding`, `llm_confirmed`, `discovery` or, since S2.2, `experiment`, or an `approved` `add` `playlist_proposals` row; never `playlists.origin`), `record_playlist_additions` (write `human` playlist rows with a `ledger_key`). Called only from the membership walk (`app/playlists_sync.py`). Both write through `_record_human` |
| `traffic_poll.py` | B1 daily traffic-source ingestion → `video_traffic_source_daily`, `playlist_traffic_daily`; the video feed's retention rule (`keeps_detail`, `collapse_unread_detail`, reading every id in `videos` once per run) |
| `interventions.py` | B2: `assign_arm` (sha256 of `video_id`, lever vs `HOLDOUT_PCT`), `active_for` (the video's open `midas` intervention), `record` (refuses a second open `midas` one with `ActiveInterventionExists`, and a `human` one with an arm other than `n/a`; a concurrent second insert is refused by the partial unique index as a PostgREST unique-violation error, not `ActiveInterventionExists`). With `ledger_key` it upserts `on_conflict="ledger_key", ignore_duplicates=True` and returns None for a key already stored. Callers: `app/human_edits.py` (`human` rows), `app/agent_tick.py` (`midas` rows, S1.4b), `app/short_links.py` `set_short_link` and `detect` (`human` `short_link` rows, S2.5, S2.6). Since S3.4 `trajectory=` (the agent tick's agent rows) is sent only when given, so no other caller needs `20261030000000` |
| `reach.py` | data-day windows, coverage, frontier, staleness, `certify` (`certify_covered` over a coverage set already read; `window_length` for SQL callers). `coverage(channel_id, report_type=…)` defaults to reach; S1.1's sibling window passes `channel_traffic_source_a3` |
| `decide.py` | B5: `decide(question_set, subject, context, intervention_id=None) -> Decision` (`question_set`, `answer`, `probs`). Answers with the question set's rules (probability 1.0), asks the `DECIDE_BACKEND` backend in shadow (`llm` via `openrouter.chat_json`, validated against the allowed answers and probabilities in [0, 1]; `jev` raises `NotConfigured`), writes one `decision_log` row with `used = 'rules'` and `QUESTION_SET_VERSION`, and returns the rules answer. A backend failure is logged `"decide <set> <subject>: <backend> backend failed; rules answer stands: …"` and logged as a row with NULL `jev_answer`; a failed log write is logged and doesn't change the answer. Two question sets: `TRIAGE` (answers `no_change|backlinks|playlist|short_link|title`, Part 2 §2.2; since S3.3 the rules choose `backlinks`, then `title`, else `no_change`, §6) and, since S1.5, `NEXT_WATCH` (answers `yes|no`; the rules answer `yes` when the context's `similarity` ≥ its `join_low`, else `no`, including when either is missing). Every answer needs a probability; the rules answer is 1.0 on itself, 0.0 elsewhere. S1.4b: the rules also refuse `backlinks` when the context's `backlinks_stopped` is true (and, since S3.3, unless `backlinks_enabled`); the returned `Decision` carries the `decision_log` row's id as `log_id` (None if the write failed; not part of equality), and `link(log_id, intervention_id)` sets that row's `intervention_id` (failures logged, never raised). Callers: `app/agent_tick.py` `run` (both sets), `app/short_links.py` `_next_watch` (`NEXT_WATCH`, S2.4) |
| `reembed.py` | B6, one-off: `recipe_text` (title, description, tags as `f"{title}\n\n{description}\n\n{', '.join(tags)}"`, title and description stripped; no transcript, no branch), `MODEL_VERSION`, `estimate_channel` (video count, videos still to embed, tokens ≈ UTF-8 bytes / 3, cost at a price passed in; reads the DB, calls no API), `reembed_channel` (every video of the channel in `videos` without a `MODEL_VERSION` vector, in batches of 50 upserted on `video_id,chunk_index,model_version`; a failed batch, or one answered with the wrong number of vectors, is retried one video at a time; a video that still fails is logged and counted, and a rerun retries it), `member_similarities` (`MemberSims`), `calibrate_channel` (thresholds from current playlist members' similarity, stored on `channels.playlist_thresholds`). Run only by `scripts/reembed.py` |
| `backlinks.py` | Slice 1 S1.2, pure (no I/O): the canonical backlink block. `render(description, targets, language)` puts `HEADINGS[language]` then one `<title> https://youtu.be/<id>` line per target (dicts with `video_id`, `title`) directly after the description's first line (D2), then a blank line if text follows; any block already there is stripped first, so a re-render replaces it. Raises `RenderRefused` (a `ValueError`) for a language not in `HEADINGS` (no English fallback), no targets, more than `BACKLINK_MAX`, a duplicate or malformed target id, an empty title, a heading with `#`, or a result over `DESCRIPTION_MAX` characters. `#` is dropped from titles and whitespace collapsed, so the block adds no hashtag. `find` → `Block(language, video_ids, start, end)`: an exact heading line followed by at least one line matching `<title> https://youtu.be/<11-char id>` and nothing else; `strip` removes every such block and the blank line after it. `HEADINGS` (all "watch more songs"): `"mr": "आणखी गाणी पहा:"` (owner, 2026-10-23: D3 left it to the SEO team, who had no preference) and, written by Claude for a native reader to skim before each channel goes live (owner, 2026-10-25), `"hi": "और गाने देखें:"`, `"bgc": "और गाणे देखो:"`, `"pa": "ਹੋਰ ਗੀਤ ਵੇਖੋ:"`, `"gu": "વધુ ગીતો જુઓ:"`, `"en": "Watch more songs:"`, `"ta": "மேலும் பாடல்களைப் பாருங்கள்:"`, `"ml": "കൂടുതൽ പാട്ടുകൾ കാണൂ:"`, `"kn": "ಇನ್ನಷ್ಟು ಹಾಡುಗಳನ್ನು ನೋಡಿ:"`, `"te": "మరిన్ని పాటలు చూడండి:"`; one per channel `default_language` (Bhojpuri, Rajasthani, 3D Animated share `hi`), all distinct (`find` reads the language off the heading). It must stay fixed: `find`/`strip` match it exactly. **S1.1, reads the DB:** `siblings(channel_id)` → `[{channel_id, views}]`, most views first: the channels whose videos sent this channel's videos ≥ `SIBLING_MIN_VIEWS` type-7 views over its latest `SIBLING_WINDOW_DAYS` (28) ingested `channel_traffic_source_a3` data-days (`reach.coverage(report_type=)`), read from its own `video_traffic_source_daily`, mapped to channels through `videos`, excluding itself and any channel not in `TRAFFIC_INGEST_CHANNELS`. `target_pool(channel_id, *, sibling_ids=None, known_vectors=None)` → `(Pool, None)` or `(None, reason)` (since 2026-10-29: the thresholds, the eligible targets below, their `MODEL_VERSION` vectors, skipping ids already in `known_vectors`, and warm impressions; most of the cost). `candidates(video, *, sibling_ids=None, pool=None)` (reads a pool when none is passed) → `Candidates(rows, skipped_unembedded, reason, join_low)` (`join_low`, S1.5: the threshold applied, None when the thresholds were missing or another model version's): targets on the source's channel or a sibling, warm on their own channel (`warm.warm_impressions`), public (or NULL), not a Short (`is_short` true), not the source, not in `human_edits.video_links(source description)`, with a `reembed.MODEL_VERSION` vector, and cosine ≥ the source channel's `playlist_thresholds.join_low`; ranked by similarity, then impressions, then id, leaving out a target whose `title_key` is the source's or a better-ranked target's (since 2026-10-29); at most `2 × BACKLINK_MAX` rows `{video_id, channel_id, title, similarity, impressions}`. Reasons: `no_thresholds`, `thresholds_other_model_version`, `source_not_embedded`. `candidates` and `render` are called by `app/agent_tick.py` (S1.4b; `siblings` through `candidates`) |
| `warm.py` | B4 warm filter: `ranked_pool` (`{id, impressions}`, most impressions first, id tie-break; `warm_pool()` RPC paged through `all_rows` when `WARM_POOL_USE_RPC`, else in-app, and in-app if the RPC errors), `explore_order` (each pick is the best left or, with probability `WARM_EXPLORE_PCT`, a random one from the rest, flagged `explore`; injectable `random.Random`), `warm_pool` (both, over the ranking minus Shorts: `_without_shorts` reads `videos.is_short` for the pool through `rows_for_ids` and drops `true`, keeping NULL, on either path, since a Short's description links aren't clickable); `_holds` (S1.4a: a `midas` row holds its video if active, created within `TRIAGE_COOLDOWN_DAYS` whatever its status, or a `backlinks` row of arm `treated`/`holdout` at any age, or, since S3.5, a `title` row of arm `holdout`, or `treated` unless `cancelled` without `applied_at`, at any age; the in-app pool reads every `midas` row of its warm videos through `rows_for_ids`); `warm_impressions` (the warmth measure alone, `{video_id: impressions}` ≥ `WARM_MIN_IMPRESSIONS`, `{}` if reach isn't certified; the in-app pool is built on it). `app/agent_tick.py` picks from `warm_pool` (S1.4b), and `app/backlinks.py` `candidates` reads `warm_impressions` (S1.1) |
| `metrics_poll.py` | daily Analytics poll |
| `measurement.py` / `verdicts.py` | title verdicts, `measurement_result` shape, rollups |
| `performance.py` | per-channel performance table/CSV |
| `dashboard.py` | `/dashboard`; `_aggregate_legacy` kept as fallback/oracle for the RPC |
| `reflection.py` | weekly per-channel prompt rewrite (shadow/live/auto) + auto-revert; `derive_niche_queries`, `_sample_competitors` (frozen) |
| `transcripts.py` | transcript fetch + `video_transcripts` cache; `lang_display_name` (`_LANG_NAMES`, `:25-36`, incl. `bgc` Haryanvi, `bho` Bhojpuri, `raj` Rajasthani); Data API captions fallback |
| `embeddings.py` / `openrouter.py` | embeddings and `chat_json`/`chat_text` via OpenRouter; since S3.4 `chat_tools(messages, tools, *, model=None, label=None)`: OpenAI-format `tools` with `tool_choice: "auto"`, the assistant message returned as sent (`content`, `tool_calls`; nothing parsed), the same headers and LLM span as `chat_json` (plus `llm.message_count`, `llm.tool_count`, `llm.tool_calls`), retried once on an `httpx.TimeoutException` or a 5xx, a 4xx or a second failure raised. Called only by `app/agent/loop.py` |
| `agent/loop.py` | Slice 3 S3.4, the title agent's hand-rolled loop (Part 6 S3.4, Part 2 §3.1, F5, F11, F14). `run_title_agent(video, *, channel=None)` → `AgentResult(kind, title, reason, trajectory)`: system `titles.agent_system_prompt()`, first user message the video id and the channel's `default_language` only; per turn `chat_tools(messages, tools.SCHEMAS, model=AUDIT_MODEL, label="agent.title")`, each tool call run (`tools.call`; arguments that aren't a JSON object, an unknown tool or a raising tool come back as `{"error": …}` text), a reply with no tool call answered with `NUDGE`. Ends: `submit_title` passing `titles.check` (on the stripped title, against the video with the channel's language) → `title`, `reason` its reasoning; a failing one gets the failure back once, a second → `failed`, `checks_failed`; `decline` → `decline`, `reason` its reason; `AGENT_MAX_TURNS` turns with neither → `failed`, `turn_cap`. A `chat_tools` exception is re-raised with the trajectory so far as its `trajectory` attribute (`end.reason` `exception`). The trajectory: §2 `interventions`. `tools_called(trajectory)`: the tool names in order. Writes nothing; called by `agent_tick._run_title` and `titles.preview` |
| `agent/tools.py` | Slice 3 S3.4, the agent's tools (Part 6 S3.4, Part 2 §3.2), each about the run's video only (`Subject(video, channel)`, passed by the loop; the model passes only the schema's arguments), read-only, no YouTube: `get_video` (`{video_id, title, description (first 1,500), default_language, impressions_28d, ctr_28d, channel_median_ctr}`, from the channel context's reach or `agent_tick._reach`), `get_transcript` (`titles._transcript`, cut to `TRANSCRIPT_MAX_CHARS`; `{available: false}` when none), `get_traffic_mix` (`agent_tick._traffic_mix`), `get_search_terms` (`titles._search_terms`, top `SEARCH_TERMS` = 25), `get_channel_top_performers(order="best"\|"worst")` (`titles._top_performers(…, worst=)`, `TOP_PERFORMERS` = 10 of the channel context's warm long videos, the video left out; `worst` counts no browse or suggested views as 0), `get_title_history` (the video's `audits` `{created_at, title_before, title (suggested_title), status, measurement_status}` and `title` interventions `{created_at, origin, status, title (payload.title), delta (measurement_result.delta)}`, each read newest first with `limit(10)`, merged, newest first, at most `HISTORY` = 10), `write_candidates` (`titles.write_candidates(titles.context(video, channel=))`, `WRITER_MODEL`, unchecked); terminal `submit_title(title, reasoning)` and `decline(reason)`, schemas only (the loop runs them). `SCHEMAS` (the nine, §6), `TOOLS`, `call` |
| `playlists.py` | similarity engine: `join_pass` (no caller since S3.6), `reconcile_channel`, `tune_thresholds`, `_llm_judge` |
| `playlists_sync.py` | playlist inventory sync, budgeted membership walk, role heuristic; hands memberships new since a playlist's previous walk to the human-edit ledger (`_record_human_memberships`) |
| `playlist_discovery.py` | weekly orphan clustering → creates playlists (frozen) |
| `playlist_health.py` | playlist health scorer (recommend-only) |
| `playlists_router.py` | playlist HTTP endpoints |
| `autopilot.py` | the tick loop; the agent path's gates (`_agent_tick`, S1.4b; since S3.3 it returns `apply_disabled`/`no_heading` only when neither `agent_tick.backlinks_enabled` nor `agent_tick.titles_open` holds). Since S3.6 the agent path is its only write path: a channel with `agent_enabled` off gets the Shorts action and `shorts_only`. `_next_video_for_channel` (the audit picker, in-app or the `next_audit_candidate()` RPC) is kept with no caller (§7.2) |
| `agent_tick.py` | Slice 1 S1.4b, the agent tick's video work. `run(channel)`: the first of `warm.warm_pool` (with the explore share) → `_assess(video, language)` (S1.1 `backlinks.candidates` on the channel's pool, `_pool`: `backlinks.target_pool` read at most once per `POOL_TTL_SECONDS` per channel, kept in process with its vectors as `array('d')` shared across channels' pools, so a target that turns private or cold within the hour can still be picked; and the triage context: `has_related_block` = the description links to one of our videos other than itself, `human_edits.video_links` ∩ `human_edits.our_videos`, D5; `backlink_candidates` = the candidate count; `backlinks_stopped`; `traffic_mix_28d` = views by source-type name over the channel's latest 28 ingested `channel_traffic_source_a3` data-days; `impressions`, `ctr` = `reach.weighted_ctr` over the latest `WARM_WINDOW_DAYS` reach data-days; `recent_interventions` = the video's rows of any origin created in the last 28 days; since S3.3 `backlinks_enabled` = `backlinks_enabled(language)`, `title_enabled` = `_title_enabled`, `title_excluded` = in `TITLE_EXCLUDE_VIDEOS` or the channel's ceiling, `channel_median_ctr`, `is_short` = `videos.is_short`; the ceiling and median from `title_channel`, read only while `title_enabled`) → `decide(TRIAGE, video_id, context)` → `title` → `_run_title` (below); else `interventions.record` (lever `backlinks`, origin `midas`): `no_change` → `declined`, arm `n/a`, `payload.rationale`; `backlinks` → if `backlinks.render` refuses on the stored description (`_unrenderable`, since 2026-10-29), `declined`, arm `n/a`, `payload.rationale` "the block can't be rendered: …", `triage_json.render_refused`; else `assign_arm`: holdout → `holdout` with `payload.targets` (top `BACKLINK_MAX` candidates), no YouTube call; treated → `planned` with `payload.targets`, then `backlinks_apply.apply_backlinks` (success → `measuring`; an ApplyError or other exception → `cancelled` with `payload.error = {reason, detail}`, re-raised for the tick; DRY_RUN → `cancelled` with reason `dry_run` and the rendered `payload.description`). `triage_json` = `{decision_log_id, question_set_version, answer, probs, context, explore, candidates_reason, skipped_unembedded}`, and `decide.link` points the log row back. S1.5: a video triaged to `backlinks` (either arm), before it is recorded, gets `_next_watch`: `decide(NEXT_WATCH, "<source>-><target>", context)` for every row `candidates` returned (up to `2 × BACKLINK_MAX`, not only the targets kept), context `{source_video_id, source_title, target_video_id, target_channel_id, target_title, similarity, join_low}`; the results go on `triage_json.next_watch` as `[{target_video_id, similarity, decision_log_id, answer, probs}]` (the rules answer; the backend's is on the log row), and `decide.link` points each pair's row at the intervention too. A declined row has no `next_watch` key. A pick that already has an active Midas intervention returns `active_intervention` (`ActiveInterventionExists`). `backlinks_stopped(channel_id)` (S1.6b): `lever_verdicts.stopped(channel_id)`, true once any `treated_vs_holdout` `lever_verdicts` row of the channel for `backlinks` has `stop_rule_triggered`; it stays true, since past weeks' rows aren't rewritten and a same-week rerun keeps a set flag. `preview(channel_id, n)`: the same up to the render for the pool's first `n`, asking `TRIAGE.rules` directly with backlinks taken as open (`backlinks_on=True`, so it shows targets before the switch is on and a missing heading as the render's refusal); a `title` answer shows its arm only (`scripts/preview_titles.py` shows the writer); writes nothing, calls no backend and no YouTube. **S3.3 (titles):** `backlinks_enabled(language)` = `BACKLINK_APPLY_ENABLED` and the language in `backlinks.HEADINGS`; `titles_open(channel_id)` = in `TITLE_CHANNELS`, `TITLE_APPLY_ENABLED`, not `titles.stopped`; `_titles_today(channel_id)` → (today's `midas` `title` rows of arm `treated` not `declined`, today's with `payload.path = 'agent'`), one bounded query, UTC day; `_title_enabled(channel_id, video_id)` = `titles_open`, the first below `TITLE_DAILY_CAP`, and for a video `titles.route`s to `agent` the second below `TITLE_AGENT_DAILY_RUNS`; `title_channel(channel_id)` = `titles.channel_context`, kept as the fourth field of the channel's `_pools` entry, read once per pool refresh (`POOL_TTL_SECONDS`) and only when asked. `_run_title(video, triage, decision)`: `assign_arm(video, 'title')`: holdout → `holdout`, `payload {title_before}`, no writer call; treated → `titles.route` → the path's writer (`titles.pipeline(video, channel=title_channel(…))`, or since S3.4 on the agent path `agent_loop.run_title_agent(video, channel=title_channel(…))`, mapped by `_agent_outcome`: a title → the same `planned` row with `candidates` = its submits, a decline → treated `declined` with `payload {title_before, path, rationale}` and no YouTube call, a failure → treated `cancelled` with `payload.error.reason` `turn_cap` or `checks_failed`; every agent row with `trajectory`, through `interventions.record`) → `planned` with `payload {title_before, title, candidates, reason, path}` and `strategy_version = titles.strategy_version(path)` → `titles_apply.apply_title` (`measuring`; an ApplyError or other exception → `cancelled` with `payload.error`, re-raised; DRY_RUN → `cancelled`, reason `dry_run`); no passing candidate → `cancelled`, reason `checks_failed` (`CHECKS_FAILED`), detail the failures; the writer raising → `cancelled`, reason `writer_exception` (`WRITER_EXCEPTION`), re-raised for the tick; `decide.link` points the triage row at it |
| `lever_measurement.py` | Slice 1 S1.6a, pair measurement per `backlinks` intervention (Part 4 S1.6, Part 2 §1.2, §1.3, §1.7); since S2.6 also `short_link` (below). `measure_channel(channel_id, *, today=None)` → counts `{attempted, errored, judged, insufficient_data, awaiting_window, extended, changed}` (`attempted`/`errored` for `job_status.item_error_verdict`; a row that raises is logged and left as it was). Reads the channel's (the source's) `backlinks` rows through `all_rows`: treated (`midas`, arm `treated`, `measuring`, `applied_at` set), holdout (`midas`, `holdout`) and human (`human`, `applied`, only when the channel is in `TRAFFIC_INGEST_CHANNELS`), plus `judged`/`insufficient_data` ones whose post window ended within `RESTATEMENT_HORIZON_DAYS` (28), which are recomputed so a restated traffic day is re-read. `as_of`: d0 = the Pacific (YouTube data-day) date of `applied_at` (treated), `created_at` (holdout) or `detected_at` (human). `windows(d0, post_days)`: pre d0−7 … d0−1, post d0+1 … d0+7 (or +14). Targets: a Midas row's `payload.targets[].video_id` (channel from the payload), a human row's `payload.target_video_id` (channel from `videos`, `rows_for_ids`). Complete when every target's channel and the source's own have a `channel_traffic_source_a3` ledger frontier (`reach.coverage`, `reach.frontier`) ≥ the post window's last day; else `measurement_status = awaiting_window` (or `extended`). `pair_views` = Σ `views` in `video_traffic_source_daily` with `video_id` in the targets, `source_type = 7`, `source_detail` = the source (`rows_for_ids`); `source_views` = the source's own views, every type (`all_rows`). Source under `LEVER_MIN_SOURCE_VIEWS` at 7 days → wait for 14; still under → `insufficient_data`; else `judged`. `delta` = post − pre, in views per week (a 14-day post is scaled by 7/14); `missing_days` lists the windows' data-days some channel the row reads has no ingested report for (counted as zero, flagged). Writes only when something changed; `judged_at` is when the row got its current outcome (kept across recomputes that don't change it), `computed_at` is the last change; a decided row that can't be decided again yet keeps its verdict. **S2.6:** the row read takes `lever in (backlinks, short_link)`; a `short_link` row is measured only as `human` (`applied`, `TRAFFIC_INGEST_CHANNELS`), with `source(row)` = `payload.short_id`, `targets(row)` = [`video_id`], d0 = `detected_at`'s Pacific date, the pair views at `SOURCE_TYPES[lever]` (`backlinks` 7, `short_link` 32; `pair_views(…, source_type=7)`) and the floor on the Short's own views, every type (`source_views`, unchanged); everything else as human backlinks. `data_day_start(day)`: Pacific midnight of a data-day, which `as_of` reads back as that day (`short_links.detect`'s timestamps). Called by `app/lever_verdicts.py` `run_weekly` (the `lever_measurement` job) |
| `title_measurement.py` | Slice 3 S3.5, title measurement per video (Part 6 S3.5, Part 2 §1.2, §1.7, F6, F14). `measure_channel(channel_id, *, today=None)` → counts `{attempted, errored, judged, insufficient_data, awaiting_window, changed}`, over the channel's `midas` `title` rows (`all_rows`): treated `measuring` with `applied_at`, `holdout`, treated `declined`, and `judged`/`insufficient_data` ones still within `lever_measurement.RESTATEMENT_HORIZON_DAYS` of their post window. `as_of`: the Pacific date of `applied_at`, else `created_at`. `windows(d0)`: pre d0−`PRE_DAYS` (14) … d0−1, post d0+1 … d0+`TITLE_WINDOW_DAYS`. Complete when the channel's `channel_traffic_source_a3` frontier reaches the post's last day (`reach.coverage`, `reach.frontier`, read once per channel). `views`: Σ `views` of `SOURCE_TYPES` (3, 7) in `video_traffic_source_daily` for the video (`all_rows`); `delta` = ln((post + 1) / (pre + 1)); `missing_days` = `reach.missing_days`; impressions and CTR per window from `reach.aggregate` (`video_reach_daily`), recorded only. `pre` < `TITLE_MIN_PRE_VIEWS` → `insufficient_data`, else `judged`. Writes through `lever_measurement._update` (`judged_at` kept across recomputes). `ROWS` = `title interventions`, its job category. Called by `lever_verdicts.run_weekly` |
| `lever_verdicts.py` | Slice 1 S1.6b, the weekly verdict (Part 4 S1.6, Part 2 §1.3–§1.5, P1, D6, D8). **S3.5:** `title_verdicts` (the per-path rows, §2 `lever_verdicts`), `write_verdicts(lever='title')` (reads `_title_judged`: judged `midas` `title` rows and those put back after judging), `stopped(channel_id, lever, scope)` (default `treated_vs_holdout`), `TITLE_SCOPES` (`payload.path` → scope), `auto_revert(channel_id)` → `{attempted, errored, reverted, skipped}` (a judged treated row with `applied_at` whose `delta` − the holdout mean Δ of its judged week, else the cumulative holdout mean, is ≤ −`TITLE_REVERT_LIFT`, worst first, at most `TITLE_REVERTS_PER_DAY` reverted, through `titles_apply.revert_title(auto=True)`; `title_changed` skipped and the next tried; `apply_disabled`/`quota_insufficient` skip and stop the run; any other error counted), the job's title half (§4) and `GET /channels/{id}/title-test` (§5 Routes). `verdicts(rows, week, windows_before, *, min_lift, windows)` (the arithmetic, §2 `lever_verdicts`; `write_verdicts` passes `BACKLINK_MIN_LIFT`, `BACKLINK_EXPERIMENT_WINDOWS`), `directional(lift, min_lift)`, `write_verdicts(channel_id, *, today=None, lever='backlinks')` (reads the channel's `judged` rows of that lever and its verdict weeks through `all_rows`; writes, oldest first, every earlier week with judged rows and no verdict row yet, then the current week, upserting on `channel_id,lever,arm_scope,week_start`; deletes the current week's row of a scope that has none now, unless it triggered the stop rule), `stopped(channel_id)` (any triggered `treated_vs_holdout` row; a bounded `limit(1)` read), `run_weekly(*, today=None)` (the job, §4; since S2.3 also `playlist_test.measure_channel` for drawn channels; since S2.6 `short_links.detect` first and `write_verdicts(lever='short_link')` last on `TRAFFIC_INGEST_CHANNELS` channels; `write_verdicts` takes `lever`, default `backlinks`), `ON_CONFLICT` (the table's unique key, shared with `playlist_test`), and the two read endpoints (§5 Routes). `insufficient_data` rows never enter a mean (§1.7); nor, for `backlinks`, do rows whose video is a Short (`_without_shorts`, `is_short` true, NULL stays in), read through `rows_for_ids` |
| `playlist_test.py` | Slice 2 S2.1, the playlist test's draw (Part 5 S2.1, Part 2 §4, P3, E1, E4–E6); #88/#89 extend it. `survey(channel_id)` → `Survey(eligible, skipped)`: the channel's `playlists` rows (`all_rows`), eligible when `role` isn't `series` and at least `MIN_EMBEDDED_MEMBERS` (3) current members have a `reembed.MODEL_VERSION` vector; current members are `reembed._members` (the latest `playlist_assignments` action per pair is `added`, as `playlists._current_members`, read for the whole channel through `rows_for_ids`); skipped rows carry `reason` `series` or `too_few_embedded_members`. `eligible(channel_id)` → `[{playlist_id, title, eligible_members}]`. `assign_arm(playlist_id)`: sha256 of the playlist id, first 8 bytes as a point in [0, 1), `holdout` below `PLAYLIST_HOLDOUT_PCT`, else `treated` (`interventions.assign_arm` untouched). `candidates(channel_id, playlist_id)` → `Candidates(rows, skipped_unembedded, reason, join_high)`: videos of the channel warm by `warm.warm_impressions`, public (or NULL), `is_short` not true, `is_episode` not true, not a current member, with a `MODEL_VERSION` vector whose raw cosine to the members' centroid (the sum of their vectors, which cosine reads as the mean) is ≥ the channel's `playlist_thresholds.join_high`; ranked by impressions, then similarity, then id; at most `PLAYLIST_TEST_MAX_ADDS` rows `{video_id, title, similarity, impressions}`. Refused with `reason` `no_thresholds` or `thresholds_other_model_version` (`backlinks._thresholds` and its constants); a playlist `survey` wouldn't make eligible gets no rows. `draw(channel_id)`: raises `AlreadyDrawn` if the channel has any `playlist_arms` row; writes nothing and returns `refused` when the thresholds are refused; else per eligible playlist inserts its arm (treated with candidates `planned`, treated without `no_dose`, holdout `holdout`), then a treated arm's pending `experiment` `add` proposals with `arm_id`, then their ids onto `proposal_ids`; returns `{channel_id, refused, playlists, arms: {treated, holdout, no_dose}, proposals, skipped}`. `preview(channel_id)`: the same plan, writing nothing, plus `already_drawn` and `plan` (per eligible playlist its arm, status, `eligible_members` and the videos it would get; none for a holdout arm). Run only by `scripts/playlist_test.py`; nothing in the draw reaches YouTube. **S2.2:** `run_apply()` (the `playlist_test_apply` job, §4) and `apply_channel(channel_id, budget)` → `{attempted, errored, sent, stopped}` (`stopped`: `budget`, `youtube_quota_exceeded` or None), the test's only YouTube write; `test_dates(channel_id)` → `(test_start, test_end)`, the Pacific dates (`lever_measurement._day`) of the earliest `first_applied_at` and latest `last_applied_at` over the channel's treated arms, None while any treated arm is `planned` or `applying`, when none has a `first_applied_at`, or when the channel has none (read by #89). `test_dates.__test__ = False`, since pytest collects `app/playlist_test.py` by its name. **S2.3:** `measure_channel(channel_id)` → `{attempted, errored, weeks, changed}` (`attempted`/`errored` per arm, for `job_status.item_error_verdict` under `ARMS` = `playlist arms`): nothing until `test_dates` and once every arm's `measurement_status` is `done`; else `windows(test_start, test_end, PLAYLIST_EXPERIMENT_WINDOWS)` (pre = `PRE_DAYS` (28) data-days ending `test_start` − 1; week k = `test_end` + 1 + 7(k − 1) … `test_end` + 7k), keeping the weeks whose last day the channel's `playlist_traffic_source_a2` ledger frontier (`reach.coverage(report_type=)`, `reach.frontier`) has reached. The indicator, `daily_starts`: Σ `playlist_starts` in `playlist_traffic_daily` per `playlist_id` and day, every video and source type (`rows_for_ids` on the channel's arm playlist ids and the span). Per arm: `pre_weekly` = pre sum × 7 / 28, each week's `starts` and `delta` = starts − `pre_weekly`, `missing_days` = `reach.missing_days` over pre and the weeks (zero, listed), `added_video_views` = per week the arm's landed adds' (`playlist_proposals.applied_at`) `video_traffic_source_daily` views with `source_type` 14 and `source_detail` = its playlist (`[]` for an arm with none). Then the week rows (§2 `lever_verdicts`), unless an arm errored, and the arms' columns, written only when changed. At window `PLAYLIST_EXPERIMENT_WINDOWS` with no arm errored, every arm is `done` and the `dosed`/`holdout` ones `judged` (`insufficient_data` when its playlist is no longer in `playlists`). `channel_playlist_test` is the read endpoint (§5 Routes) |
| `short_links.py` | Slice 2 S2.4, Short → video link recommendations (Part 5 S2.4, Part 2 §2.3, P4, E9, E10); #91/#92 extend it. Recommend-only: nothing here reaches YouTube. `shorts(channel_id)` → `[{id, channel_id, title, feed_views}]`, most views first, ties by id: the channel's videos with `is_short` true, public (or NULL), with ≥ `SHORT_LINK_MIN_FEED_VIEWS` type-24 views in `video_traffic_source_daily` over its latest `FEED_WINDOW_DAYS` (28) ingested `channel_traffic_source_a3` data-days (`reach.coverage(report_type=)`, as `backlinks.siblings`). `targets(short, *, pool=None)` → `Targets(rows, skipped_unembedded, reason, join_low)` (`backlinks.Candidates`' shape): long videos (`is_short` not true) on the Short's own channel only (Part 5 finding 6), public (or NULL), warm (`warm.warm_impressions`), not the Short, with a `reembed.MODEL_VERSION` vector whose cosine to the Short's is ≥ the channel's `playlist_thresholds.join_low`; ranked by similarity, then impressions, then id; at most `SHORT_LINK_TARGETS` rows `{video_id, channel_id, title, similarity, impressions}`. Refused as `backlinks.candidates` (`backlinks._thresholds` and its reasons `no_thresholds`, `thresholds_other_model_version`); a Short without a vector → `source_not_embedded`, `skipped_unembedded` 1; else `skipped_unembedded` counts the eligible targets without a vector. `pool` (`_pool`: the thresholds, the eligible targets and their vectors) is read once per channel by `refresh`. `refresh(channel_id)`: `_plan` (the listed Shorts with no `short_link_recommendations` row of any status, in `shorts` order, until `SHORT_LINK_MAX_PER_RUN` have targets; a Short without a vector or a target is counted and tried again next run), then per Short, per pair, `decide(NEXT_WATCH, "<short>-><target>", context)` with `agent_tick._next_watch`'s context (the Short as source), and its `pending` rows with each pair's `log_id` as `decision_log_id` in one insert; returns `{channel_id, refused, shorts, already, skipped_unembedded, no_targets, targets_unembedded, attempted, errored, recommended, rows}` (a Short whose write raises is logged, counted in `errored`, and the others run). `preview(channel_id)`: `_plan`, writing nothing and asking no backend. `run_weekly()`: the `short_link_refresh` job (§4). **S2.5:** `router`, the page's endpoints and the tick (§5 Routes): `channel_short_links` (`_page`, `_csv`), `set_short_link` (the human ledger through `interventions.record`, `_ledger_key`), `dismiss_short_link`. **S2.6:** `seen_pairs(channel_id)` → `[{short_id, short_channel_id, target_video_id, views, first_day}]`: type-32 rows of `video_traffic_source_daily` on the channel (`video_id` = the target, in `videos`; `source_detail` = a Short in `videos` with `is_short` true; B1 keeps type-32 detail, `app/traffic_poll.py` `keeps_detail`) summed over its latest `FEED_WINDOW_DAYS` (28) ingested `channel_traffic_source_a3` data-days, ≥ `SHORT_LINK_SEEN_MIN_VIEWS`; `detect(channel_id)` → `{pairs, attempted, errored, seen, inferred}`: per pair `seen_at` on a matching recommendation still without one, and an `interventions.record` (§2 `interventions` S2.6) unless the pair's `ledger_key` is stored; a pair that raises is logged and counted (`PAIRS` = `short-link pairs`; `INFERRED_TIMING` = `inferred_from_traffic`). Called by `app/lever_verdicts.py` `run_weekly` |
| `tracing.py` | OpenTelemetry → Phoenix spans (off by default) |
| `backup.py` / `provision.py` / `services/nas_service.py` | NAS snapshot, restore-on-empty, SMB client |
| `keyframes.py` | dead: not imported anywhere in `app/` or `scripts/` |
| `shorts/*` | Shorts cutter (NAS source), dispatcher, worker, upload. `shorts/cutter/download.py` gated off (`SHORTS_YT_DOWNLOAD_ENABLED=false`) |
| `static/*` | vanilla-JS dashboard. `channel.html`'s proposals card labels `decision_source` through `DECIDED_BY`, which has `experiment: 'Playlist test'` since S2.1 (the playlist test's proposals show up there unchanged otherwise). Since S2.5 the Playlists tab has a "Short links" card (`#sl-card`, `loadShortLinks`, `renderShortLinks`, `decideShortLink`), loaded with the tab: `GET /channels/{id}/short-links?limit=1000` (from the SWR cache, as the other cards), per Short its title (YouTube link), feed views and an "Open in Studio" link, per target its rank, title, similarity, impressions and status pill, "Set in Studio" (`POST /short-links/{id}/set`, after a `confirmDialog`) on a target not `set` and "Dismiss" (`POST /short-links/{id}/dismiss`) on a `pending` one, and a "Download CSV" link (`?format=csv&limit=1000`) |

**Scripts:** `scripts/preview_titles.py` (S3.2: `--channel`, `--n` default 20, `--path pipeline|agent` default `pipeline`, `--csv [PATH]` default `logs/preview_titles_<channel>.csv`; prints `titles.preview` per title answer (since S3.3, the videos `TRIAGE.rules` sends to titles with the lever taken as open, §5 `titles.py`): arm, path, CTR beside the median, impressions, each candidate with its check, the chosen title or the failures; since S3.4 with `--path agent` the agent's run instead: the tools called and its turns, each submitted title with its check, and the title or `decline`/`failed` with its reason, the CSV gaining `agent_end`, `tools`, `turns`; CSV cells starting `= + - @`, tab or CR prefixed with `'` (`short_links._cell`); read-only, calls the writer model and, with `--path agent`, the reasoning model), `scripts/title_bakeoff.py` (S3.2, F9: `--channel`, `--n` default 20, `--models a,b,c`, `--out` default `logs/title_bakeoff_<channel>.csv`, `--seed`; `titles.title_answers(…, pick=False)`'s videos through `titles.write_candidates` once per model, no retry; one shuffled row per (video, model): `row, code, video_id, current_title, candidate` (the top candidate passing `check`, else blank), `checks` (`pass`, or each failure), blank `score_1_3` and `wrong_or_broken_script`; the model is a code `W1…Wn` assigned in shuffled order, mapped in `<out stem>.key.csv` (`code, model`); cells escaped as the preview's; writes nothing to the DB, calls no YouTube), `scripts/short_links.py` (S2.4: `--channel` and `--preview` (required); prints per Short `refresh` would recommend its feed views and targets (rank, similarity, impressions), then the counts; exits 1 when the thresholds are refused; writes nothing, asks no backend), `scripts/playlist_test.py` (S2.1: `--channel` and one of `--preview` (prints per eligible playlist its arm, status and the videos it would get, the skipped playlists and the counts; writes nothing) or `--draw` (`playlist_test.draw`, no confirmation; exits 1 when refused or already drawn)), `scripts/preview_backlinks.py` (S1.4b: `--channel`, `--n` default 20; prints each video's rules answer, arm, targets, context and description before/after, or the render refusal; read-only), `scripts/reembed.py` (B6: `--channels` comma list, `--estimate` with `--usd-per-mtok`, `--skip-calibrate`;
the real run re-embeds then calibrates each channel), `scripts/create_reporting_job.py` (`--report-type`, default `channel_reach_basic_a1`),
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

- **Strategy stamp** (`app/audits.py:196-278`). `strategy_version(prompt_text, prompt_source, prompt_version_id=None)`
  returns `f"{settings.STRATEGY_LABEL}-{_strategy_hash(inputs)}"`, the hash being the first 12 hex of sha256 over
  `json.dumps(inputs, sort_keys=True, separators=(",", ":"))`. `inputs` = `label`, `prompt_source`
  (`override|shorts|generated|default`; anything else raises `ValueError`), `prompt_sha256` (of the system prompt
  actually sent), `audit_model` (`settings.AUDIT_MODEL`), `decision_question_set_version` (`decide.QUESTION_SET_VERSION`, read at call time; `"2026.11-s3-v1"` since S3.3, `app/decide.py:39`),
  `prompt_version_id`, and no `writer_model`: since S3.2 `WRITER_MODEL` exists but is the title writer's, stamped by `app/titles.py`, so the audit stamp's inputs didn't change.
  `_stamp_strategy` upserts `{version, prompt_template, model: settings.AUDIT_MODEL, config: inputs, status:
  "champion", notes: "auto-registered by _stamp_strategy (derived from config)"}` with `ignore_duplicates=True`,
  once per version per process. `prompt_template` is one of `"audit_video prompt_override (caller-supplied, e.g.
  reflection shadow candidate)"`, `"audit_configs.shorts_prompt (per-channel)"`, `"audit_configs.generated_prompt
  (per-channel)"`, `"code:app/audits.py DEFAULT_PROMPT"` (`app/audits.py:210-215`).

- **Other LLM calls** (all via OpenRouter, `app/openrouter.py`; `chat_json`/`chat_text` default to
  `settings.AUDIT_MODEL`, `app/openrouter.py:93,175`):

  | Call | Model | Path | Prompt |
  |---|---|---|---|
  | Audit | `settings.AUDIT_MODEL` | `audit_video` → `chat_json(user, system=audit_prompt)` (`app/audits.py`), from the manual audit routes only since S3.6 | above + DB `audit_configs` |
  | Prompt elaboration | `settings.PROMPT_GEN_MODEL` | `POST /audit-config/elaborate` | `app/audits.py:107-125` (renders `house_format_spec()`) |
  | Niche queries | hardcoded `anthropic/claude-haiku-4.5` | reflection (frozen) | `app/reflection.py:264-272`, below |
  | Platform guidance | hardcoded `perplexity/sonar` via `chat_text` | reflection (frozen) | `app/reflection.py:346-352`, below |
  | Reflection candidate prompt | `settings.REFLECTION_MODEL` | reflection (frozen) | `app/reflection.py:465-507` |
  | Playlist membership judge | `JUDGE_MODEL = "anthropic/claude-haiku-4.5"` | `reconcile_channel` (frozen) and dead `join_pass` | `app/playlists.py:206-213`, below |
  | Playlist title/description proposal | `JUDGE_MODEL` | `discover_playlists` (frozen) | `app/playlist_discovery.py:137-142`, below |
  | Title writer (S3.2) | `settings.WRITER_MODEL` (= `AUDIT_MODEL`), or each `--models` entry in the bake-off | `titles.write_candidates` → `chat_json(…, system=system_prompt(), label="titles.write")`, from `titles.pipeline` (up to 2 calls a video) via `scripts/preview_titles.py`, and once per (video, model) from `scripts/title_bakeoff.py`; and since S3.3 from the agent tick (`agent_tick._run_title`), per treated title on the pipeline path (on either path until S3.4), with a live transcript fetch (`fetch_transcript`); since S3.4 also from the agent's `write_candidates` tool (`app/agent/tools.py`), once per call, no retry | `TITLE_PROMPT` below, and the user block (`app/titles.py` `_user_block`) |
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
  `backlinks_stopped`, `traffic_mix_28d`, `impressions`, `ctr`, `recent_interventions`, and since S3.3
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

  Where the title is read: on the YouTube home page, and in the list of videos
  next to another video, beside the thumbnail. A parent scrolling past decides
  in a glance whether to tap. It is not read in a list of search results, so
  write for that glance, not for search keywords.

  Rules:
  - Keep the rhyme's name, in the channel's language and in its script.
  - If the current title has a series name, keep it.
  - Use plain words a parent recognises, not a list of keywords.
  - Add no hashtags: no more "#" than the current title has.
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

  Since S3.4 the part through the rules is `TITLE_BRIEF`, and `TITLE_PROMPT` is `TITLE_BRIEF` plus the rest (the
  rendered text, and so the pipeline's stamp, unchanged).

- **Title agent prompt** (S3.4, `app/titles.py` `AGENT_PROMPT`, the system message of `app/agent/loop.py`
  `run_title_agent`; `agent_system_prompt()` fills `{title_max}` with `TITLE_MAX` (100)). `TITLE_BRIEF`, then the
  agent's part. Verbatim:

  ```
  You write the title of one YouTube video on a kids' nursery-rhyme channel.
  Only the title changes: the thumbnail, description and tags stay as they are.

  Where the title is read: on the YouTube home page, and in the list of videos
  next to another video, beside the thumbnail. A parent scrolling past decides
  in a glance whether to tap. It is not read in a list of search results, so
  write for that glance, not for search keywords.

  Rules:
  - Keep the rhyme's name, in the channel's language and in its script.
  - If the current title has a series name, keep it.
  - Use plain words a parent recognises, not a list of keywords.
  - Add no hashtags: no more "#" than the current title has.
  - No links.
  - At most {title_max} characters.
  - Each candidate must differ from the current title.

  You decide this video's title with tools. Find out first what the video is
  and how it is doing: where its views come from, the search terms that bring
  viewers to it, the channel's titles that do best and worst on browse and
  suggested views per impression, and what was tried on this title before.
  write_candidates asks a writer model for candidates; you may submit one,
  change one, or write your own.

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
§0.6 (P1–P7); "Part 3" is Phase B (done 2026-10-13); "Part 4" is Slice 1, the Part marked ready to build.

### 7.1 Spec'd but not built

**Phase B (Part 3)**: done; the acceptances are recorded in `docs/PHASE_B_FINDINGS.md`. What remains:
- **B1 retention.** Decided 2026-10-13 (owner), built at ingestion (`traffic_poll.keeps_detail`, §2). Not deployed,
  and the existing rows aren't folded yet (`scripts/collapse_traffic_detail.sql`): `video_traffic_source_daily` was
  4,766 MB / ≈15.0M rows on 2026-10-13.
- **B3 scope.** The membership walk runs only inside `playlist_reconcile`, i.e. for the allowlisted channels
  (`app/config.py:151-161`; Marathi is in the default). B3a sees an old video's edit only on a full sync, every
  3 days (`app/sync.py:520`). As of 2026-10-13 every `human` row is a playlist membership (110); none is a backlink.
- **B4** is wired into the agent tick only (S1.4b, `app/agent_tick.py`): the old audit picker, uncalled since S3.6, is still newest-first with no impressions filter
  (`supabase/migrations/20260904000100_next_audit_candidate_exclude_episodes.sql:37`
  `order by v.published_at desc, v.id`) and excludes in-window audits rather than active interventions (`:35-36`).
- **B5:** `decide()` is called by S1.4b's triage (live on Marathi since 2026-10-24) and by the Short-link refresh (S2.4, since 2026-10-26), so `decision_log` has rows.
- **B6:** run for Marathi only; the siblings wait for the office to deploy #55 (`deploy/postgrest-proxy.conf`
  `client_max_body_size 16m`, merged 2026-10-23; every batch got 413 on Marathi under nginx's 1 MB default).
  The playlist engine and its RPCs still use `EMBED_MODEL` and the global thresholds (§7.3 items 4–5); the only
  reader of the new vectors and the stored thresholds is S1.1's `backlinks.candidates`, called by the agent tick.
- **B7:** done; `bho`/`raj` stay unused while Bhojpuri and Rajasthani use plain `hi` (owner, 2026-10-06).
- **B2's persistence of the A8 registry** ("Persisting it is Phase B work", Part 1 A8): not built; registry is
  in-memory (`app/job_status.py`).

**Slice 1 (Part 2 §1–§2, §3.4, §6.1)**
- Tick routing on `agent_enabled` (§6.1, Part 4 S1.4): built (S1.4b, `app/autopilot.py` `_agent_tick`,
  `app/agent_tick.py`, `eligibility.can_run_agent`), live on Marathi since 2026-10-24.
- The pick's cooldown and once-per-experiment exclusions (§2.1, Part 4 S1.4 "Pick"): built (S1.4a, `warm_pool()` in
  `20261023000000`, `app/warm.py`), applied; called by the agent tick (S1.4b).
- Rules triage, `no_change` as a `declined` intervention, holdout with would-be targets, the cap and the kill
  switch (§2.2, §1.3, Part 4 S1.4): built (S1.4b, `app/agent_tick.py`), live on Marathi. The P1 stop rule's input
  reads `lever_verdicts` since S1.6b (`agent_tick.backlinks_stopped`).
- Backlink candidates and fleet siblings (P2, Part 4 S1.1): built (`app/backlinks.py` `siblings`, `candidates`),
  called by the agent tick (S1.4b). Sibling targets appear only once the sibling channels have `MODEL_VERSION` vectors (S1.7 step 2;
  B6 ran for Marathi only). The next-watch question in shadow (§2.3, Part 4 S1.5): built (`decide.NEXT_WATCH`,
  asked by `app/agent_tick.py` `_next_watch`), live on Marathi.
- Code checks for links (§2.4): not built. Partially present: `DESCRIPTION_MAX = 5000`, the 15-hashtag cap and
  `rejection()` (`app/audit_suggestion.py`).
- Canonical backlink block (§3.4, Part 4 S1.2): built (`app/backlinks.py`), called by the agent tick and `apply_backlinks`, with
  Marathi's heading `आणखी गाणी पहा:` (owner, 2026-10-23, D3), and since fleet readiness a heading for every channel language (§5 `backlinks.py`), not yet skimmed by native readers.
- Description-only apply (§2.5, Part 4 S1.3): built (`app/backlinks_apply.py`), with its revert and the ledger
  change; called by the agent tick (S1.4b) for treated rows, and refusing while `BACKLINK_APPLY_ENABLED` is false.
- Weekly measurement and the stop rule (Part 4 S1.6, P1): built (S1.6a `app/lever_measurement.py`, S1.6b
  `app/lever_verdicts.py`, the `lever_measurement` job, `lever_verdicts` in `20261023010000`), deployed and
  applied; no verdict yet. The findings-doc write-ups of the first verdict and the stop-rule outcome are S1.8 (owner).
- `reach_warmup` on human-run channels (§1.4): set 2026-10-26 on the 5 channels without reach (Haryanvi, Rajasthani, 3D Animated, Kannada, Telugu; `docs/PLAN_TO_2026-11-27.md`). The other 8 ingest reach through `measurement_enabled`.

**Slice 2 (Part 2 §4; Part 5; S2.1–S2.6 built, deployed on Marathi 2026-10-26)**
- The P3 curated-playlist test (Part 5 S2.1–S2.3): the arms, candidates, draw and preview (S2.1, `app/playlist_test.py`, `playlist_arms` in `20261027000000`) and the queued, budgeted apply behind `PLAYLIST_APPLY_ENABLED` with `test_dates` (S2.2, `app/playlist_test.py` `run_apply`, the `playlist_test_apply` job) are built and deployed 2026-10-26; Marathi is drawn and dosing from that day. The measurement, weekly verdict and `GET /channels/{id}/playlist-test` (S2.3, `app/playlist_test.py` `measure_channel`, run by the `lever_measurement` job) are deployed; they measure once Marathi's dosing ends (`test_dates`). Jev fit check replacing `playlists._llm_judge`: not built, deferred by Part 5 E12.
- Short → video links recommend-only to the team (P4, Part 5 S2.4–S2.6): the recommendations, their shadow next-watch and the weekly `short_link_refresh` job (S2.4, `app/short_links.py`, `short_link_recommendations` in `20261027010000`) are deployed 2026-10-26: 241 `pending` rows over 100 Marathi Shorts (two hand refreshes), every Marathi Short embedded. The page, the tick and the ledger (S2.5) and the traffic detection, type-32 measurement and `short_link` human verdicts (S2.6) are deployed the same day.
- Per-channel auto-apply flip for playlist adds: not built (`PLAYLIST_HITL` is one global setting,
  `app/config.py:115`).

**Slice 3 (Part 2 §3; Part 6)**
- The title-only write and its revert (Part 6 S3.1, F1): built (`app/titles_apply.py`), called by the tick since S3.3.
- The pipeline's writer, its checks, the title stamp, the preview and the offline bake-off (Part 6 S3.2, F9, F12):
  built (`app/titles.py`, `scripts/preview_titles.py`, `scripts/title_bakeoff.py`), called by the tick since S3.3.
- Triage and routing for titles (Part 6 S3.3, F2–F5, F12): built (#118; `app/decide.py`, `app/agent_tick.py`
  `_run_title`, `app/titles.py` `route`, `app/autopilot.py` `_agent_tick`). `titles.path_stopped` reads the title verdicts since S3.5.
- Title measurement, verdicts per path, the stop rule and harm guard, auto-revert and the title-test endpoint
  (Part 6 S3.5, F6–F8, F14): built (#120; `app/title_measurement.py`, `app/lever_verdicts.py`), run by the weekly
  `lever_measurement` job; no title row measured yet. "The video never re-enters the title experiment" is built in
  the pick (`warm._holds`, `warm_pool()` in `20261030020000`, not applied: until it is, the RPC path, used only when
  `WARM_POOL_USE_RPC` is true, still lets a title video back after the cooldown; the in-app path doesn't).
- The agent loop, its tools and the trajectory (Part 6 S3.4, Part 2 §3.1, §3.2): built (#119; `app/agent/loop.py`,
  `app/agent/tools.py`, `openrouter.chat_tools`, `AGENT_MAX_TURNS`, `interventions.trajectory` in `20261030000000`,
  not applied), run by the tick for the agent path's treated titles and by `scripts/preview_titles.py --path agent`.
- The old title path's retirement (Part 6 S3.6, F13): built (#117). The tick's house-format branch and
  `TITLE_AUTOPILOT_ENABLED` are gone (`app/autopilot.py` `tick`); the manual applies refuse on an agent channel
  unless `?force=true` (`app/audits.py` `_refuse_on_agent_channel`).
- Agent tools Part 2 §3.2 lists that Part 6 leaves out: `get_related_top_performers`, `get_playlists`,
  `get_niche_reference`, `get_channel_playbook`, and `submit_change` (Slice 3's terminal tool is `submit_title`):
  none exist. The online per-family writer bake-off (§3.3) is not built (Part 6 F9: offline only).
- Title objective aimed at browse/suggested views (P5): the writer's prompt (`TITLE_PROMPT`, S3.2) aims at them, and
  the tick writes titles through it since S3.3 (while `TITLE_APPLY_ENABLED` is on); the weekly job measures them on those views since S3.5;
  the old house format, still reachable from the manual audit routes (guarded on agent channels since S3.6),
  optimises for search ("keyword-rich sentences", "high-value search phrases", `app/audit_suggestion.py:74-76`).
- Niche reference (§3.6): no `app/niche_reference.py`, no `niche_reference_refresh` job, no `channels.niche_reference_*`
  columns. `derive_niche_queries` and `_sample_competitors` still live in the frozen `app/reflection.py:239-339`.

**Slice 4 (Part 2 §5)**: no `channels.playbook_json`, no distiller, no weekly rebuild; `reflection.py` not retired.

**Slice 5 (Part 2 §6)**: no per-channel quota shares in `JobBudget`.

### 7.2 Built but not spec'd

| Item | Where | Note |
|---|---|---|
| Title measurement loop (21-day CTR verdicts, `awaiting_window` stamping on apply) | `app/measurement.py`, `app/verdicts.py`, migration `20260702183233` | Kept only indirectly ("Title … CTR vs a comparable window … Built", Part 2 §1.2). Its windows are not the spec's weekly cadence (7.3) |
| Prompt reflection loop (weekly `generated_prompt` rewrite, `prompt_versions` shadow/live/auto, shadow audits, auto-revert on cohort median) | `app/reflection.py`, `prompt_versions` | **Frozen** (`REFLECTION_ENABLED`). Spec scraps it as the memory (Part 2 §0.5 item 3) and retires it in Slice 4 (§5) |
| Similarity playlist engine: daily add/remove, `tune_thresholds`, `join_pass` | `app/playlists.py` | Add/remove and tuning **frozen**; `join_pass` has no caller since S3.6 (`app/autopilot.py`) |
| Weekly orphan-cluster playlist **creation** | `app/playlist_discovery.py` | **Frozen** (`PLAYLIST_DISCOVERY_ENABLED`). Spec: "New-playlist creation … stay human-confirmed" (Part 2 §4) |
| Competitor sampling via `search.list` (100u each) and Perplexity guidance | `app/reflection.py:301-352` | Frozen with reflection. Spec moves the competitor half to Slice 3's niche reference |
| `video_traffic_source_playlist` table + tier-2 poller | `20260618133036_…`, `app/metrics_poll.py:85,228` | Disabled (`TIER2_TRAFFIC_SOURCE_SUPPORTED = False`); never populated. Superseded by `playlist_traffic_daily` (B1b), which is populated; the old table and poller are still in the code |
| Playlist health scorer (tier-1 percentile bands) | `app/playlist_health.py`, `docs/PHASE_1B_PLAN.md` | Kept by Part 2 §0.5 ("inventory, health …") but no stage uses it |
| `video_sync` daily job | `app/main.py:243-267,365-376` | Added 2026-10-01 after the A0 pause stopped sync (`docs/PHASE_A_FINDINGS.md` "Phase A conclusion" §3.6). Not in any Part, though B3 depends on sync |
| Shorts cutter (NAS source, worker queue, autopilot Shorts, upload) | `app/shorts/*`, 7 migrations | Separate product line; the spec only says Shorts uploads continue (Part 2 §6.1). Uploads are not charged to the quota ledger (`app/shorts/youtube_upload.py` has no `can_afford`) |
| Self-hosted Postgres + PostgREST, nightly NAS snapshot, restore-on-empty | `app/backup.py`, `app/provision.py`, `docker-compose.yml`, `docs/SELF_HOSTED_DB.md` | Infra; the spec references it only in Part 3's schema discipline |
| OTel/Phoenix tracing | `app/tracing.py`, `docs/OBSERVABILITY.md` | Spec reuses it for the agent (Part 2 §3.1) |
| Egress RPCs with in-app parity fallbacks | migrations `202607*`, `app/dashboard.py`, `app/autopilot.py:116-123` | Supabase free-tier era |
| Transcript cache + captions-API fallback (250u per video) | `app/transcripts.py`, `video_transcripts` | Quota exposure unspecified |
| Episode exclusion | `app/content_type.py`, migrations `20260904*` | Matches Part 2 §2.1 "not an episode" |
| `/dashboard`, `/performance*`, `/autoshorts` UIs | `app/dashboard.py`, `app/performance.py`, `app/static/*` | |
| Dead code: `app/keyframes.py`, `video_keyframes`, `audits.keyframes_extracted`, `videos.thumbnail_optimized_at`/`playlists_optimized_at`, statuses `approved`/`rejected`, `outcome_decision='redo_queued'`, `redo_of_audit_id`, `MAX_REDO`, `AUTO_REVERT_ON_REGRESSION`, `PLAYLIST_MEASUREMENT_WINDOW_DAYS`, `playlists.strategy_version` | various | Pre-spec reservations nothing writes or reads |
| The old audit picker: `autopilot._next_video_for_channel`, the `next_audit_candidate()` SQL function (`20260904000100`), `AUTOPILOT_PICKER_USE_RPC`; `PausedReason.UNSAFE_MODEL` | `app/autopilot.py`, `supabase/migrations/20260727160000_next_audit_candidate_rpc.sql` (replaced by `20260730010000`, `20260904000100`), `app/config.py`, `app/status_vocab.py` | No caller since S3.6 deleted the tick's house-format branch; kept with its tests (`tests/test_autopilot_picker_rpc.py`, the live parity guards, the `next_audit_candidate()` drift check in `tests/test_status_vocab.py`), since dropping the SQL function needs a migration. `unsafe_model` is a persisted pause reason (not renamed or removed); nothing sets it now |

### 7.3 Built differently from the spec

1. **Strategy stamp timing (Part 1 A6, Part 2 §8).** Spec: derive at startup from the `DEFAULT_PROMPT` hash and the
   per-channel prompt-version id. Built: derived per audit, hashing the prompt text actually sent and its source
   (`app/audits.py:218-243`), so shorts/override/generated audits stamp differently. Audits before A6 still carry
   `2026.07-baseline-v1`.
2. **Measurement cadence (Part 2 §1.1, §1.7).** Spec: weekly windows, extended once to 14 days. Built: symmetric
   21-day pre/post windows (`MEASUREMENT_WINDOW_DAYS`, `app/reach.py:60-82`) plus `ROLLOVER_SLOP_DAYS=1`, judged
   on CTR only.
3. **Dormancy (Part 2 §2.1).** Spec: keep dormant videos out at selection. Built: dormancy is found only after the
   window (`REASON_DORMANT`, `app/measurement.py:280`); the old audit picker is newest-first (7.1 B4), but since
   S3.6 nothing calls it: the tick picks only through the warm filter (the agent path). A7 (2026-10-06):
   4,254 applies landed on dormant videos.
4. **Embedding input (Part 3 B6).** Spec: one recipe (title + description + tags) for every video. Built: B6's
   recipe under its own `model_version` (`app/reembed.py`, §6), but production still writes and reads two recipes
   under `EMBED_MODEL` (§6), so that value does not identify the input. B6 embeds **every** video of the named
   channels (Shorts, private and episodes included), not only the warm ones the acceptance names: one recipe, and
   the warm pool changes daily. The recipe has no length cap (title ≤100, description ≤5000, tags ≤500 chars,
   `app/audit_suggestion.py`). The token estimate is UTF-8 bytes / 3, not a tokenizer, and the price is passed
   in (`--usd-per-mtok`), not stored.
5. **Playlist thresholds (Part 2 §4, B6).** Spec: per channel. Built: the engine still reads the process-global
   values, and `tune_thresholds` overwrites the global from one channel (`app/playlists.py:518`), frozen. B6 stores
   per-channel values on `channels.playlist_thresholds` that only S1.1's `backlinks.candidates` reads (`join_low`). The spec gives no method; built
   (`app/reembed.py` `calibrate_channel`), on `MODEL_VERSION` vectors: `join_high` = p50 and `join_low` = p5 of each
   current member's cosine to the centroid of its playlist's *other* members (how a candidate outside the playlist is
   scored), and `leave` = p10 of each member's cosine to the centroid of *all* members, itself included (how
   reconcile compares a member with `PLAYLIST_LEAVE`: `app/playlists.py` `_sims_matrix`, and the
   `playlist_video_sims` RPC). Nothing is stored below 30 similarities. `join_low` ≤ `join_high` always; `leave`
   comes from the other distribution, so its order against `join_high` isn't guaranteed. p50 lets a non-member
   as close as the median member join without the judge: a starting value for the owner to review before
   anything reads it. Members are the latest `playlist_assignments` action per
   (playlist, video) being `added`, as `playlists._current_members`, over the playlists whose `playlists.channel_id`
   is the channel (`playlist_assignments` has no `channel_id`, `20260518000000_playlists.sql:25-35`; the same join
   as the `playlist_video_sims` RPC); a playlist needs 3 embedded members. The frozen `tune_thresholds` filters
   `playlist_assignments` on `channel_id` (`app/playlists.py:470-474`), a column the table lacks, so it would fail
   if unfrozen; B6 doesn't touch it. Stored as a
   `channels` jsonb column rather than `threshold_history`, which `tune_thresholds` owns.
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
8. **Apply cost.** `quota.APPLY` = 51u (`app/quota.py:67`) but apply no longer fetches stats (`app/audits.py:546-556`):
   the gates overestimate by 1u. Spec Part 1 A10 says note it only.
9. **`interventions` DDL (Part 2 §7, Part 3 B2).** The spec lists columns only. Built with `not null` on
   `video_id`, `channel_id`, `lever`, `origin`, `arm` and `status`, `video_id → videos on delete cascade` (as
   `audits`), `created_at default now()`, and a partial unique index that makes §1.6 hold in the database as well
   as in `record` (`supabase/migrations/20261006020000_interventions.sql`). Vocabularies are checked in Python
   (`app/interventions.py` `_require`), not by SQL `check` constraints, as for `audits.status`.
10. **Human-edit ledger details (Part 2 §1.4, Part 3 B3; B3a).** `interventions` gained `ledger_key text` with a
   unique index (`20261006030000`), which Part 2 §7 doesn't list, so a rerun or a racing sync can't duplicate a row.
   "Links to our videos" means any video in `videos`, on any channel, not only the source's channel
   (`app/human_edits.py` `our_videos`), since sibling channels link into each other (P2), plus the videos fetched
   in the same sync (`also_ours`: the ledger runs before the upsert). A target on a channel with no synced videos
   (Kannada, Telugu, §1) is not ours to the ledger, and that link is not recorded. A link from a video to
   itself is ignored. A removed link creates no row: it is listed in `removed_targets` of any addition seen in the
   same edit, and stamped as `payload.removed_detected_at` on the link's earlier ledger row; a removal of a link
   older than the ledger is not stored anywhere. "Midas made the change" is the new description equalling (with
   whitespace collapsed) an applied audit's `suggested_description` or a reverted audit's `description_before`
   (`made_by_midas`); on a match the whole description change is skipped, additions and removals alike. An apply
   whose description was overridden in the request body isn't recognised, because the applied text isn't stored on
   the audit (`app/audits.py:515-522`). Only full syncs re-read old videos, so incremental syncs record nothing, and a
   video the team edits and Midas then rewrites within one full-sync interval is seen only as Midas's.
   **Deploy order:** apply `20261006030000` with `20261006020000`, before the app restarts on this code, and restart
   PostgREST. Without it every ledger write fails (no `ledger_key` column); the sync still succeeds and logs the
   error per video, but no human edit is recorded until the migration lands, and edits synced meanwhile are lost.
11. **Human-edit ledger, playlist memberships (Part 3 B3, change 2; B3b).** "Newly added" is "the walk has no
   `playlist_assignments` row of any action for the (video, playlist) pair", which is what the walk already used
   to decide what to seed (`app/playlists_sync.py:297-307`); the walk has no removal detection, so a video the
   team removes and re-adds, or that Midas once removed, is never seen as new. Baseline rule (the spec has none): a
   playlist with `membership_walked_at` NULL at plan time, including one new to the DB, is walked as a baseline and
   records nothing, so a human add made before a playlist's first walk is never recorded. Playlists the walk has
   already stamped (`20260812000000`) are not re-baselined after deploy: their existing memberships already have
   `sync` rows. Only the channel's own videos count (the walk's `known_videos`), and a membership of a video not yet
   in `videos` is skipped; when that video is synced later the next walk of the playlist records it, even if the
   add predates the previous walk (a false `human` row; `videos` has no first-seen time to rule it out). Marathi
   was fully synced 2026-10-06 (header), so its exposure at deploy is videos uploaded since. A ledger error doesn't
   stop the walk seeding its `sync` rows, so the memberships of that page are never detected (as B3a's lost edits).
   The manual `/playlists/bootstrap` walk detects for whichever channel it is run on, allowlisted or not. "Midas added it" counts every non-`sync` `added` assignment and every approved
   `add` proposal, including those a person approved through `/playlists/proposals/decide`. Detection timing:
   `detected_at` is the walk that saw it, which re-reads a playlist only when its item count changes or every
   `PLAYLIST_FULL_WALK_DAYS` (30), within `PLAYLIST_SYNC_QUOTA_BUDGET`; an equal-count swap waits for rotation. The
   payload's `timing` says so. A walk cut short by the budget mid-playlist has already recorded the pages it read
   (the ledger runs per page).
12. **Warm filter (Part 2 §2.1, Part 3 B4).** Part 2 §2.1 adds the filter *to* `next_audit_candidate`; built as
   a separate function, `warm_pool()` (`20261006040000`), with `next_audit_candidate` unchanged, since B4 says not to
   wire it into the tick. It returns the whole pool, not one pick. "Ingested data-days" = the latest
   `WARM_WINDOW_DAYS` distinct `data_date`s with a reach report in `reporting_reports_ingested` (`reach.coverage`'s
   days), so a day ingested with no rows counts and an ingestion gap reaches further back. "Certified reach" =
   `reach.certify` for the channel, at query time; an uncertified channel's pool is empty. In SQL that is
   `count(distinct day) = MEASUREMENT_WINDOW_DAYS` over the days ending at the frontier, passed in as
   `p_measurement_window_days` (`reach.window_length`). "Public" counts a NULL `privacy_status` as public, and "not an
   episode" is `is_episode is not true`, both as `next_audit_candidate`. Only *Midas* interventions in
   `ACTIVE_INTERVENTION_STATUSES` exclude (as `interventions.active_for`): human rows are written `applied` and
   never closed (B3), so counting them would bar every video the team ever edited. A video in `video_reach_daily`
   but not in `videos` isn't in the pool. The explore share is applied in Python over the ranking
   (`explore_order`), not in SQL: each successive pick is exploration with probability `WARM_EXPLORE_PCT`, drawn
   uniformly from all but the best remaining video. Settings are function parameters (SQL can't read `settings`).
   The `WARM_POOL_USE_RPC` switch (default false) isn't in the spec; it follows `AUTOPILOT_PICKER_USE_RPC`.
   Parity is tested offline on a throwaway local Postgres (`tests/test_warm_pool_parity.py`), not only live.
   **S1.4a (#63).** The two Slice 1 exclusions are in the same function, replaced by `20261023000000`, and its twin;
   only `midas` rows count. "Created within `TRIAGE_COOLDOWN_DAYS`" = `created_at > now() - p_cooldown_days days`
   (Python: `> now(UTC) - TRIAGE_COOLDOWN_DAYS`); a NULL `created_at` is outside it. "For the experiment's duration"
   is built as *forever*: no experiment id or end exists yet, so a video with any `midas` `backlinks` row of arm
   `treated` or `holdout` never re-enters the pool; a later experiment would need a boundary column. The cooldown
   applies to every lever, not only backlinks. The signature gained `p_cooldown_days`, so the four-argument function
   is dropped (PostgREST can't pick between overloads); its only caller, `app/warm.py` `_rpc_params`, passes it.
   **Shorts (2026-10-26, not in the spec).** The pick (`warm.warm_pool`) drops videos with `is_short` true, after
   either path, not in the SQL function or `ranked_pool`, so the parity tests still compare like with like and no
   migration is needed. Part 2 §2.1 excludes Shorts only as link targets (§2.4); the pick needs it too once a
   channel's Shorts are synced (Part 5 S2.7 turns `sync_shorts` on for Marathi), or a backlink block lands on a
   Short, where description links aren't clickable.
13. **`decide()` and `decision_log` (Part 3 B5).** The spec gives `decide(question_set, subject, context)` and no
   question sets. Built: a `QuestionSet` (name, question, allowed answers, rules function) and one set, `TRIAGE`
   (Part 2 §2.2's rules: `backlinks` with no related block and at least `BACKLINK_MIN_CANDIDATES` candidates, else
   `no_change`; context keys `has_related_block`, `backlink_candidates`), so `BACKLINK_MIN_CANDIDATES` is added in
   Phase B rather than Slice 1. One `QUESTION_SET_VERSION` covers every set in `app/decide.py` and replaces the A6
   placeholder (`DECISION_QUESTION_SET_VERSION` is gone from `app/audits.py`), so after deploy every audit source stamps a new
   `strategy_version` (and `_stamp_strategy` upserts a new `audit_strategies` row) though no prompt changed.
   `TRIAGE` offers §2.2's five options; its rules chose only `backlinks` or `no_change` (the Slice 1 baseline; `title`
   too since S3.3, item 30), so a backend's other choices are logged but can't agree with the rules. A backend answer must give a probability
   for every option (§2.2), not necessarily summing to 1; anything else is a backend failure. `decide()` takes an optional
   `intervention_id` for the log row. A failing backend still writes a row (NULL `jev_answer`/`jev_probs`), so the log
   counts failures too; a failed `decision_log` write is logged, never raised. `intervention_id` is
   `on delete set null` (an intervention cascades away with its video). Column types and `not null`s aren't in the
   spec (Part 2 §7 lists names only).
14. **Canonical backlink block (Part 2 §3.4, Part 4 S1.2).** Part 2 says "fixed marker lines"; built as Part 4
   says, with no marker but the heading: a block is the exact heading line plus the `<title> https://youtu.be/<id>`
   lines directly under it (`app/backlinks.py`). Not in the spec: a blank line after the block when text follows, so
   that a human's own link line in that shape, sitting under the first line before the render, isn't absorbed into the
   block by `strip`; more than `BACKLINK_MAX` targets is refused, not trimmed (S1.1's caller keeps the top
   `BACKLINK_MAX`); `#` is removed from target titles, so the block never adds a hashtag; an empty description
   becomes the block alone. A line in the block's shape that a human adds directly under the block is read as part
   of it (`tests/test_backlinks.py`); S1.3 can tell by comparing `find`'s ids with the intervention's targets. The 5,000 limit is checked in characters (`len`, as `rejection()`, `app/audit_suggestion.py`), not UTF-8 bytes.
15. **Siblings and candidates (Part 2 §2.3, Part 4 S1.1).** "Trailing 28 ingested data days" = the latest 28
   distinct `data_date`s with a `channel_traffic_source_a3` report for the channel in `reporting_reports_ingested`
   (`reach.coverage(report_type=)`, B4's notion), a module constant `SIBLING_WINDOW_DAYS`, not a setting. "Ours" for
   a referring video = in `videos`; the referring channel is that row's `channel_id`. "Warm on its own channel" is
   B4's impressions measure only (`warm.warm_impressions`): unlike the pick pool, a target may be in an active Midas
   intervention or an episode, since treated and held-out videos stay active for their window while the pick takes
   up to 40 a day (spec Part 4 D4), and the ticket lists no episode exclusion. A sibling whose reach isn't certified
   (`reach.certify`) has no warm videos, so it adds no targets and nothing to the skip count, as in B4. A NULL
   `is_short` is eligible (not yet probed), as NULL privacy is. The raw cosine is compared with `join_low` and
   ranked (ties by impressions, then id); it is not rounded. The source channel's `join_low` applies to sibling targets too
   (Part 4: "the source channel's calibrated `join_low`"). `candidates` returns a `Candidates` tuple with
   `skipped_unembedded` (source or otherwise eligible targets without a `MODEL_VERSION` vector) and a `reason`; a
   source without one counts 1. It takes optional `sibling_ids` so a caller can compute `siblings` once. All
   similarity is in-app: one call reads the `vector(3072)` (`20260518000000_playlists.sql:10-12`) of every eligible
   warm target on the source channel and its siblings; no RPC twin yet.
16. **Description-only apply, revert, ledger (Part 2 §2.5, Part 4 S1.3).** Not in the spec: on success
   `apply_backlinks` itself sets the row to `measuring` with `applied_at` (S1.4's success state), but leaves a
   failure's row untouched for S1.4 to cancel. The revert is gated like the apply: `BACKLINK_APPLY_ENABLED` false
   refuses it too ("every write path", ticket #64), so removing a block after the kill switch is off needs the
   switch on again. Its quota gate is `quota.APPLY` (51u), not `POST /audits/{id}/revert`'s 50u, since it also
   fetches the live snippet. DRY_RUN calls no YouTube at all (as the audit apply), so a dry run renders onto the
   stored description, not the live one, and under DRY_RUN the revert records nothing (the audit revert marks
   the audit reverted). The fetch is `yt_videos_list_full` (1u, all four parts) and only its `snippet` is sent
   back, read-only fields (`publishedAt`, `channelId`, `thumbnails`, `localized` …) included, as YouTube returned
   them. The apply hands a live description that differs from the stored one to the ledger before overwriting
   `videos.description`, or a team edit made since the last full sync would never be seen. "Exactly the targets"
   (finding 4) = the description's links to our videos, other than the video itself, equal the targets of a
   `treated` `midas` `backlinks` row with `applied_at` set and status not `cancelled` (a reverted block is gone, so
   the same links added later are the team's); a holdout row's would-have-got targets never count. The apply renders
   onto the stored description before any YouTube call, so a refusal (no heading, too many targets) spends nothing.
   The revert strips every canonical block (`backlinks.strip`), not only the intervention's targets. Links to videos that aren't ours are ignored, as the ledger ignores them.
17. **Tick routing, triage, holdout (Part 2 §2.1, §2.2, §1.3, §6.1, Part 4 S1.4; S1.4b).** The tick branches on
   `agent_enabled` alone, right after the Shorts action (`app/autopilot.py` `tick`): an agent channel whose
   `can_run_agent` is false does nothing (`agent_ineligible`) rather than falling back to the audit path. Because
   `can_run_agent` includes `can_audit`, an agent channel also needs `autopilot_enabled = t`. The agent path keeps
   the audit path's gates in the same order (resync, cap, ledger quota gate, before triage, so a tick that can't
   afford the write records nothing) and its error reactions (`_react_to_apply_error`, factored out of
   `_apply_audit_and_handle`, which S3.6 deleted with the audit path). A `declined` row is lever `backlinks`, arm `n/a` (Slice 1's only lever), so it
   holds its video only for the cooldown. Every treated row that doesn't reach YouTube is `cancelled` with
   `payload.error.reason` (`apply_disabled`, `quota_insufficient`, `failed`, …; `dry_run` under DRY_RUN, which
   the spec doesn't mention): a treated row that never reached YouTube (`applied_at` NULL) holds its video only for the cooldown, not for
   the experiment (review fix, 2026-10-23: `warm_pool()` and `warm._holds`), and the agent doesn't run at all while
   the kill switch is off or the language has no heading, so no pick is spent before writes can happen. The stop rule enters triage as a context key, `backlinks_stopped`, read by the TRIAGE rules, so it is
   logged with the decision; that rules change bumps `QUESTION_SET_VERSION` to `2026.10-s1-v1` and with it every
   audit's `strategy_version`. "Recent interventions" and the traffic mix span 28 days (`CONTEXT_DAYS`), the
   mix over ingested traffic data-days and keyed by source-type name; impressions and CTR over the warm window.
   `has_related_block` (D5) counts a link to any of our videos on any channel, not to itself. `decide()` logs
   before the row exists, so `decision_log.intervention_id` is set afterwards by `decide.link`. The preview asks
   `TRIAGE.rules` directly (no backend call, no log row), and previews the pool's first `n` in order (no
   cooldown between them).
18. **Next-watch in shadow (Part 2 §2.3, Part 4 S1.5; #66).** Asked for every pair `candidates` returns (up to
   `2 × BACKLINK_MAX`), not only the `BACKLINK_MAX` targets kept, as the spec says "each pair S1.1 returns". Since
   `candidates` drops every pair below `join_low`, the rules answer is `yes` for every pair asked, so the log
   measures only how often the backend agrees with pairs the rule already accepted, never pairs it rejected.
   The results are stored on `triage_json.next_watch` (not `payload`: `payload` is the lever's change, which
   the apply and the ledger read), with the rules answer and probabilities and each pair's `decision_log_id`;
   the backend's answer is only on the log row, as for triage. The pairs are asked before the intervention is
   recorded, so a pick refused as `active_intervention` leaves its pair rows unlinked (as its triage row). The
   question set is new, so `QUESTION_SET_VERSION` goes to `2026.10-s1-v2` and, as with B5 and S1.4b, every audit's
   `strategy_version` changes after deploy though no audit prompt did (`tests/test_decide.py`
   `test_the_s1_5_bump_reaches_the_strategy_stamp`). The preview (`scripts/preview_backlinks.py`) doesn't ask it.
   Part 2 §2.4's shadow checks are not built (D7). Cost: each pair is one sequential backend call inside the tick,
   so a video triaged to `backlinks` makes up to `2 × BACKLINK_MAX` (6) `decide.next_watch` calls besides triage's.
   Item 13's single `TRIAGE` set now has this second set beside it.
19. **Pair measurement (Part 2 §1.2, §1.3, §1.7, Part 4 S1.6; S1.6a, #67).** Not in the spec, decided here:
   *Completeness* reads "ingested data through d0+7" as each channel's ledger frontier ≥ that day (as
   `reach.frontier`), so a missing day inside the window (a gap, or a channel whose ingestion began inside the
   pre window, D1) counts as zero views rather than holding the row forever, and is listed in
   `measurement_result.missing_days` for S1.6b to exclude or report; and the source's own channel must be complete too, since the floor reads the source's views from its
   channel's report (usually a target's channel already). A target whose channel isn't ingested (or a human row's
   target missing from `videos`) never completes, or errors, and waits. *The extension* lengthens only the post
   window (the ticket: "extend the post window"); the pre stays 7 days, so `delta` is put in views per week
   (post × 7/14 − pre) to stay comparable with unextended rows and with D6's per-week unit; `pre` and `post` are
   the raw sums. `insufficient_data` rows carry the same numbers. *The floor* is the source's views over every
   traffic source in the post window (`video_traffic_source_daily`), not Analytics `view_count`. *Restatements*:
   the spec's "restatement horizon" has no value; built as `RESTATEMENT_HORIZON_DAYS = 28` after the post window
   ends (four weekly runs), a module constant, and every decided row inside it is recomputed on each run.
   `judged_at` is when the row got its current outcome (the week it was "judged" for S1.6b), kept across
   recomputes that don't change the outcome and restamped when one does; `computed_at` moves.
   A recompute that can't decide yet (a restated source day falls under the floor and the 14-day window isn't in)
   keeps the old verdict rather than reopening the row. *Which rows*: a `cancelled` treated row (refused, failed,
   DRY_RUN or reverted) isn't measured; a human row is measured even if `payload.removed_detected_at` says the
   link was later removed. d0 is the Pacific date of the timestamp, because traffic data-days are YouTube's
   (as reach's, `app/reach.py` `ROLLOVER_SLOP_DAYS`): a block applied at 02:00 UTC went live on the previous
   data-day, which as a UTC date would have been in the pre window. No further slop: the ticket's windows already
   exclude d0. A target whose channel is never ingested leaves its row `awaiting_window` indefinitely (not
   counted as an error). *Status split* (§7.4): `status` holds the outcome, `measurement_status`
   the progress (§2). Human rows go `applied` → `judged`/`insufficient_data`; nothing else reads a human row's
   status (the warm pool and `active_for` count `midas` rows only).
20. **Weekly verdict and stop rule (Part 2 §1.3–§1.5, P1, Part 4 S1.6; S1.6b, #68).** Not in the spec, decided
   here: *"Judged that week"* = `measurement_result.judged_at` in the Monday-to-Sunday (UTC) week, so a missed
   Monday run (the office machine is often off) puts that week's rows into the next run's week and costs no row,
   and a missed week isn't a window. A run that measured but died before its verdicts leaves judged rows in a
   week with no verdict row: the next run writes that week first, so they still get their weekly lift. *`cumulative_lift`* is pooled: the treated mean minus the holdout mean over
   every row judged up to that week (with each row's current, possibly restated, `delta`), not a mean of the
   weekly lifts, so a thin week weighs what its rows weigh. *The verdict band* is symmetric: `helped` at lift ≥
   `BACKLINK_MIN_LIFT`, `worse` at ≤ −it. *No verdict* also when the week has no judged treated row (the lift is
   undefined), as when it has no judged holdout row (the ticket). *Reruns*: past weeks' rows are never rewritten
   (a restatement reaches the verdicts through the cumulative lift); a same-week rerun replaces that week's row,
   and deletes it if the week no longer has a verdict, but never clears or deletes a triggered stop. *The stop is sticky*: `backlinks_stopped` is any triggered
   row, so the lever stays off even if a later week's cumulative lift recovers (P1's time box: the result is
   written up, not re-litigated by the job); an owner restart means deleting the row. *Human rows* get
   `n_treated` and their mean delta only: no lift, no verdict (§1.4: no comparison group), and never stop the lever.
   *Channels*: the job runs every channel (`Job.EVERY`), since Midas rows can outlive `agent_enabled` and human
   rows are measured on `TRAFFIC_INGEST_CHANNELS` (measure_channel's own rule). *The interventions page*:
   `limit`/`offset` (no paging convention existed), capped at PostgREST's 1000. *`missing_days`* (S1.6a's flag)
   doesn't exclude a row from the means: the spec gives no rule, a gap is rare once a channel's ingestion is
   steady, and the row still says so for anyone reading it through the interventions endpoint.
   *Shorts* (2026-10-26, not in the spec): a backlinks row whose video is a Short enters no mean, in either arm
   or the human row (`_without_shorts`). Before #103 the pick took Shorts, and on 2026-10-26 Marathi had 44
   treated and 11 holdout rows on Shorts, where description links aren't clickable; the arm is a hash of the
   video id, so dropping them from both arms keeps the comparison fair. The 44 blocks stay on YouTube (owner,
   2026-10-26: not reverted) and the rows are still measured.
21. **The playlist test's draw (Part 2 §4, P3, Part 5 S2.1; #87).** Not in the spec, decided here: *Members*
   are read with `reembed._members` (the channel's playlists' `playlist_assignments` through `rows_for_ids`, the
   latest action per pair by `decided_at` then `id`), the same rule as `playlists._current_members` and the reader
   `calibrate_channel` used for `join_high`, in one channel-wide read rather than one per playlist.
   *`eligible_members`* stores the members with a `MODEL_VERSION` vector (the ones the centroid is built from), not
   every member. *The centroid* is the sum of the members' vectors (cosine ignores scale, so it is the mean's
   cosine), as `reembed.member_similarities`; the cosine is compared raw. *Candidates* must be on the playlist's
   channel by `videos.channel_id`, and a NULL `privacy_status`, `is_short` or `is_episode` is eligible (not yet
   known), as `warm_pool()` and `backlinks.candidates`. A current member without a vector is still a member and
   never proposed. *A refused threshold refuses the whole draw* (nothing written, `refused` = the reason) rather
   than writing every treated arm `no_dose`, since that would spend the once-only draw on a configuration
   problem. *A second draw* raises `AlreadyDrawn` (the script prints it and exits 1). *Holdout arms* get no
   candidates computed, so the preview shows none for them. *The write is not atomic*: PostgREST takes one
   statement at a time, so each arm is inserted, then its proposals, then its `proposal_ids`; a draw that dies
   midway leaves a partial draw that a rerun refuses, and recovering means deleting the channel's `playlist_arms`
   rows and their proposals by hand. *Vocab*: `PlaylistProposalSource` lists only `experiment`; the frozen
   engine's `embedding`/`llm_confirmed`/`discovery` stay literals. The migration adds no index beyond the unique
   key (the table holds one row per playlist).
22. **The playlist test's apply (Part 2 §2.5, Part 5 S2.2; #88).** Not in the spec, decided here: *Attempts* are
   counted in `apply_error.attempts`; only a `failed` error uses one up, since `youtube_quota_exceeded` and
   `token_expired` aren't the add's fault (they still write `apply_error`). *Positions*: an add's position is the
   number of the arm's adds ahead of it in rank already in the playlist, so a retry next run lands at its rank, not
   at the top. *A refused position* is "a 400 whose text names the position or the sort order"; after one, every
   later add to that playlist goes appended, in that run and later ones (the refusal is read back off
   `apply_error`), still in rank: the playlist isn't sorted manually, and each refusal costs 50u. The playlist's
   budget check is n × 50u, so the one refusal's extra call is over it by 50u. *Pending proposals*: as the spec
   says, an arm is `dosed`/`no_dose` once no approved add is unsent or retryable, whatever is still pending, so an
   undecided proposal never holds `test_dates` back; a proposal approved after its arm settled is never sent (E3 is
   one review sitting). An arm with nothing approved stays open while any proposal is pending.
   *The job's channels* are those with a treated arm `planned` or `applying`, so an all-rejected `planned` arm
   becomes `no_dose` on the next enabled run; while the kill switch is off no arm settles. *`stopped`*: a budget
   stop and YouTube's quotaExceeded end the run for every later channel; a token error raises out of the channel
   (it fails the run, as a token failure fails `traffic_poll`) and the next channel runs. A quotaExceeded is not an
   errored add (it is a stop): its channel is `degraded`, not failed. *DRY_RUN* checks no budget and settles
   no arm. *The approve response* gains `queued` only when non-zero, so a batch with no test proposals answers as
   before; the dashboard card is unchanged. *`_record_assignment`* is called from `app/playlists` (where the
   router imports it from), and writes `model_version = EMBED_MODEL` as every assignment does.
23. **The playlist test's measurement and verdict (Part 2 §1.2, §1.3, §1.5, P3, Part 5 S2.3; #89).** Not in the
   spec, decided here: *Weeks measured* stop at `PLAYLIST_EXPERIMENT_WINDOWS`; a later week isn't measured or
   given a row. *Rewrites*: unlike backlinks' weeks (never rewritten after their week), every complete week's
   row and every arm's numbers are recomputed each run until the test is done, so a restated playlist report day
   (the report restates, `docs/PHASE_A_FINDINGS.md` A1.1) reaches them; once every arm is `done` the test is
   never measured again, so a restatement after the last window is not read. *A vanished playlist* (gone from
   `playlists`, the inventory sync's view) leaves every week's means, not only the last, since a gone playlist
   reads as zero starts; its arm is still measured, and becomes `insufficient_data` at the last window. *`no_dose`
   arms* keep their status at the end (the spec says "arms become `judged`"; a `no_dose` arm never entered a
   mean, and `judged` would hide why), and are `done` like the rest. *An errored arm* (any) holds back the whole
   channel's verdicts and the arms' end, since a missing arm would change the means and, at the last window,
   decide the answer without it; the next run retries. *No verdict* for a week without a dosed treated arm or a
   holdout arm (as backlinks), so a test without both never gets an answer and stays `pending` (its arms still
   end `done`). *`added_video_views`* is `[{k, views}]`, `[]` for an arm with no landed add, and counts only adds
   with `applied_at`. *`pre_weekly`* is the pre's sum × 7 / 28, so an ingestion gap inside it lowers it (listed in
   `missing_days`, as S1.6a). *The answer* reads the stored rows: `no` when the window-4 row triggered the stop
   rule, `yes` when it didn't, `pending` otherwise; `lever_verdicts.stopped(channel, 'playlist')` gives the same
   `no` and nothing reads it. *The job* finds the drawn channels with one `playlist_arms` read per run, and joins
   a channel's backlinks and playlist messages with `; ` when both report; a crash in either half skips only that
   half, and a failed `playlist_arms` read skips the playlist half for the run (logged at ERROR, not a job failure: the
   next run recomputes every week, and the table is missing until the owner applies `20261027000000`). The backlinks half now runs its verdicts in an `else` rather than `continue`, so the playlist half still
   runs after a backlinks failure; backlinks' own behaviour is unchanged. *The endpoint* lives on a small router in `app/playlist_test.py`, mounted in `app/main.py`.
24. **Short-link recommendations (Part 2 §2.3, P4, Part 5 S2.4; #90).** Not in the spec, decided here: *The per-run
   cap* counts Shorts that get rows (the ones that cost shadow calls, which the cap bounds); a Short skipped for no
   vector or no target above `join_low` uses no slot, writes nothing and is tried again next run, so a Short embedded
   later, or a target that warms up, still gets its rows. *Refused thresholds* (missing, or another model version's)
   refuse the whole channel's run: nothing written, the job's channel `degraded` with `refused: <reason>`, not
   failed, since it's a configuration step (S2.7) and not an outage. *The skip count*: `targets` counts the Short
   (1, `source_not_embedded`) as `backlinks.candidates` counts its source, else the eligible targets with no
   vector; `refresh` reports Shorts skipped (`skipped_unembedded`) and the channel's unembedded warm long videos
   (`targets_unembedded`) apart. *The write order*: each pair's decision first, then the Short's rows with their log ids in
   one insert, so a Short is written whole or not at all and one that raises is tried again next run (its log rows
   stay, unlinked); `decide` never raises on a backend failure, and a failed log write leaves `decision_log_id` NULL.
   *Refusals* are noticed only when there are new Shorts to recommend: a channel whose listed Shorts all have rows
   reads no thresholds. The log row's `intervention_id` stays NULL (`decide.link`
   unchanged). *Feed views* sum every type-24 row of the Short (any `source_detail`) on the window's days; a row on
   a day with no ingested report doesn't count. *Targets* need no episode filter (none in the spec, as
   `backlinks.candidates`) and a Short with `is_short` NULL is not listed (only `is_short` true is a Short), while a
   target with `is_short` NULL is eligible. *The job's channels* are the setting intersection only: no
   `analytics_authorized` check, since it reads the DB alone. *`channel_id`* is nullable, as the spec's column list
   gives it. The migration adds no index beyond the unique key (`refresh` reads a channel's `short_id`s once a run).

25. **The Short-links page and the tick (Part 2 §1.4, §2.5, P4, Part 5 S2.5; #91).** Not in the spec, decided here:
   *The page is of Shorts*, not rows, so a Short's targets never split across pages: `limit`/`offset` count Shorts,
   grouped in-app over every row of the channel (`all_rows`; at most `SHORT_LINK_MAX_PER_RUN` × `SHORT_LINK_TARGETS`
   new rows a week), not one bounded DB page as `GET /channels/{id}/interventions`. "Pending first" = Shorts with any
   `pending` row, then the rest, each by feed views (the largest of its rows'), then id. *`status`* filters rows: a
   Short is listed with only its rows in that status. *The CSV* is the same page (the card links `limit=1000`), one
   line per recommendation; `format` other than `json`/`csv` is 422 (FastAPI's validation), not 400. *The tick*
   writes the ledger first, then the Short's other rows, then this row's `set` last, so a tick that dies partway is
   redone whole by the next one; a pair whose key is already stored (a retry, or S2.6's inferred row once it exists)
   gets that row's id rather than a second row. A tick of a row already `set` writes nothing. *Changing the target*
   leaves the old pair's intervention `applied`, unchanged: the link was on the Short for a while, and S2.6 measures
   per pair. *A dismissed sibling* stays `dismissed` when another target is set (the spec says "the Short's other
   rows become `not_chosen`"; a dismissal is the stronger statement); only `pending` and `set` siblings become
   `not_chosen`, with `decided_at`. *Dismissing a `set` row* is refused (409): the ledger says the link is on the
   Short; the team changes it by setting another target. A `not_chosen` or `dismissed` row can still be set.
   *Setting an earlier target back* (A, then B, then A) records a third row, under `short_link:<short>:<A>:2`
   (`_episode_key`: the pair's rows are `key`, `key:2`, …; a new one when another target of the Short has a larger
   intervention id than the pair's latest), so the second period of A is measured from its own tick. A pair seen
   only by S2.6 and then ticked, with no other target ticked since, is still linked, not a new period. S2.6's
   detection checks the plain pair key, so it never adds a row for a pair the team has ticked. Nothing records when
   a changed-away link came off the Short (no `removed_detected_at`, unlike B3a). *The intervention's
   `channel_id`* is the recommendation's, or the Short's in `videos` when it is NULL (`refresh` always writes it).
   *The card's tick* asks for confirmation ("I set it") before it records, since there is no undo route. *The card* lives on the
   Playlists tab, after the playlist proposals, since the channel page has no Shorts tab and the spec allows no other
   page change; it reads one page of up to 1000 Shorts.
26. **Short links seen in the traffic, their measurement and verdicts (Part 2 §1.2, §1.4, Part 5 S2.6; #92).** Not
   in the spec, decided here: *The window* is the target channel's latest 28 ingested `channel_traffic_source_a3`
   data-days (`short_links.FEED_WINDOW_DAYS`, as the feed views), since the type-32 rows are in the target's report.
   *"A Short in `videos`"* is any channel's; the target must be in `videos` too (the intervention's FK). Rows with no
   `source_detail` or with zero views never count, and a pair's first day is its first day with views > 0.
   *`detected_at` and `seen_at`* are the first data-day as Pacific midnight (`2026-10-01T00:00:00-07:00`), so
   `lever_measurement.as_of` reads it back as that day; a pair seen again later keeps its first `seen_at`, and only
   a NULL one is written. *`seen_at` is written whatever the recommendation's status* (a dismissed row the team set
   anyway is still seen). *The intervention's `channel_id`* is the Short's (as a tick's: the recommendation's is the
   Short's channel), so the pair is measured with the Short's channel's rows. *The payload* has no
   `recommendation_id` (the ticket lists `recommended` only). *Once inferred, never re-inferred*: the key is per pair,
   so a link the team removed and set again isn't seen twice (as item 25). *A pre-window with no type-32 views*:
   d0 is the first day with views, so an inferred row's pre is usually zero and its delta is the post's views per
   week, for a link first seen inside the window. A link set before detection first ran is dated at the window's
   first day with views, so its pre falls on days that already carried its views and its delta reads near zero, a
   bias against the team's older links in the `short_link` verdicts; the spec's d0 rule, kept. *A tick after
   detection* links the inferred row (S2.5's `_ledger_id`), which keeps `timing: "inferred_from_traffic"`. *The floor* is `source_views` (the Short's own views, every source type), unchanged:
   "the pair-view and source-floor helpers take the source type" is read as the source (video) for the floor,
   since the floor is on every view of the Short; only `pair_views` takes a `source_type` (default 7, so backlinks'
   calls are unchanged). *Only `human` `short_link` rows* are measured (P4: Midas sets none); a `midas` one would be
   skipped. *The job*: detection runs only on `TRAFFIC_INGEST_CHANNELS` channels (the report it reads), before the
   measurement, in its own `try` and category, so a detection failure never blocks backlinks; `short_link` rows share
   the measurement's `interventions` category, and `write_verdicts(lever='short_link')` runs only on those channels,
   after backlinks' (a channel off the list has no measured human rows). The recommendations are read only when there
   is a pair, so a channel with no type-32 pair runs before `20261027010000` is applied.
27. **The title write and its revert (Part 2 §2.5, Part 6 S3.1, F1; #115).** Not in the spec, decided here:
   *`title_changed`* on the apply is `ApplyError(FAILED, "title_changed")` (Part 6: "refuses as `failed`, reason
   `title_changed`"), so a caller records `payload.error = {reason: "failed", detail: "title_changed"}` and the
   tick's error reaction counts it as a failure; on the revert it is a plain `HTTPException(409, "title_changed")`,
   not an `ApplyOutcome` (no new vocab), which `revert_title`'s callers (S3.5) catch by status. Both compare the live
   title exactly, after one 1u fetch, so a refusal still costs that 1u. *The revert route* sends every `title` row to `revert_title`, whose
   `ValueError` (not applied, cancelled, human, no `before_state.title`) is its own 400; every other row gets the
   backlinks checks and messages as before, and a title row never reads
   `BACKLINK_APPLY_ENABLED` (nor a backlinks row `TITLE_APPLY_ENABLED`). *The revert's order* is the backlinks
   revert's: shape check, kill switch, DRY_RUN, ledger gate, fetch; under DRY_RUN it reads nothing from the DB and
   returns `before_state.title`. *The titles compared are exact*, not whitespace-normalised: nothing in the spec says YouTube rewrites a title
   it accepts, and a looser match could overwrite a team's edit. *`payload.title_before`* may be an empty string (a video with no title is still
   compared), but must be present. *No human-edit ledger* for titles: nothing records a team's title edit, so a
   stored title that differs from the live one is simply overwritten on success. The fetch and send are shared
   with `backlinks_apply.py` (`_live_snippet`, `_send_snippet`, a no-behaviour-change split of
   `_write_description`), and the revert route imports `titles_apply` inside the function, since `titles_apply`
   imports those helpers. The daily cap needed no change: `autopilot._applies_today` already counts applied `midas`
   interventions of any lever (`tests/test_titles_apply.py`
   `test_an_applied_title_counts_toward_the_daily_cap`).

28. **The title writer, its checks, the preview and the bake-off (Part 2 §2.4, §3.3, Part 6 S3.2, F9, F12; #116).**
   Not in the spec, decided here: *The preview's title answer* was a local rule (`titles.would_title`) until S3.3's
   TRIAGE rule existed; since S3.3 it is `TRIAGE.rules` (item 30). It needs the ceiling and the path split, so
   `TITLE_MAX_IMPRESSIONS` and `TITLE_AGENT_PCT` (Part 6 Config) arrive with S3.2, and `title_path` is the hash
   alone: S3.3 adds the hand-over when a path is stopped (`titles.route`). "The pool's first `n` title answers" walks `warm.warm_pool` (with its explore
   share, as `agent_tick.preview`) until `n` videos pass, so the order can differ between runs, and it inherits the pick's exclusions: on a channel whose warm long videos are all in a backlinks experiment (Marathi, 2026-10-29) it lists none. The bake-off samples without them (`pick=False`, by impressions), since it judges the writer, not the pick. *Transcripts* come
   from the `video_transcripts` cache only (`titles._transcript`), in the tick as in the preview and the bake-off,
   since a live fetch may call the captions API (250u) outside the apply's quota gate (owner, 2026-10-30, Slice 3
   final review; the `cache_only` switch is gone); a video with none is written for without one. *Median CTR* is
   over the warm long videos with a CTR (impressions > 0), and the ceiling's 1% is of the warm long videos; the
   `tests/test_verdicts.py` median guard (meant for CTR deltas) exempts `app/titles.py` for this one median.
   *Top performers* are ranked by browse + suggested views over the 28 ingested traffic data-days divided by
   impressions over the warm window (two ledgers, each the latest of its own report), a video without a row in
   `videos` dropped, and the video itself left out of its own context. *Search terms* are the video's, not the
   channel's (Part 6: "its top 10 search terms"). *The checks* compare length on the raw title but call an
   all-whitespace title empty; a language not in `SCRIPTS` (other than `en`) fails the script check rather than
   passing unchecked; a URL is `https?://`, `www.`, `youtu.be/` or `youtube.com/`; `<`, `>` and line breaks fail (YouTube's `invalidTitle`), so a refusal costs no 50u apply; candidates are stripped of surrounding whitespace before the checks. *A malformed reply* counts as a
   failed attempt and still gets the retry; a model returning more than `TITLE_CANDIDATES` is cut to that many.
   An exception from the model (network, HTTP) propagates out of `pipeline`; the preview and the bake-off catch it per
   video and print it. *The stamp*: the inputs are the five the spec lists (no `label`, unlike the audit stamp, whose
   label is only the version's prefix here too); `prompt_sha256` hashes `system_prompt()` as rendered, so
   `TITLE_CANDIDATES` moves it; both paths hashed `TITLE_PROMPT` until S3.4 gave the agent its own prompt (item 31). The audit
   stamp's old `getattr(settings, "WRITER_MODEL")` hook is gone, so adding the setting changed no audit's stamp.
   *The CSVs* escape formula-leading cells with `short_links._cell`. *Top performers* read every type-3/7 row of the channel's warm long videos for 28 days (paged through `rows_for_ids`), once per preview or bake-off run; S3.3 caches it with the pool. *The bake-off* hides each model behind one code (`W1…Wn`, assigned in shuffled order) rather than a code per row,
   so the SEO team's scores can be totalled per code; it asks each model once (no retry), the "top pick only" of F9.

29. **The old title path's retirement (Part 6 S3.6, F13; #117).** Not in the spec, decided here: *A channel with
   `agent_enabled` off* records `tick.outcome` `shorts_only` and is touched (`autopilot_last_tick_at`), as the
   deleted `title_autopilot_disabled` branch was, so the round-robin moves on; `Job.AUTOPILOT` (`can_audit or
   can_cut_shorts`) is unchanged, so such a channel with `autopilot_enabled` on is still picked and does only the
   Shorts action (and nothing if it has none). *Helpers*: deleted with the branch, as nothing else calls them,
   `_apply_audit_and_handle`, `APPLY_UNCLASSIFIED`, `_is_unsafe_model`/`UNSAFE_MODELS`, `_video_timeout_counts`, and
   the after-apply `embed_video` (the manual routes never re-embedded); their tests went with them, and the
   reaction tests now drive `_react_to_apply_error` and the A10 quota-gate tests the agent path. Kept:
   `_next_video_for_channel` (no caller; it mirrors the `next_audit_candidate()` SQL function, which only a
   migration can drop, and its parity tests guard that pair, §7.2), `_applies_today`'s applied-audit count (the
   manual routes still apply audits, and those writes still spend the channel's day), `eligibility.can_audit`
   (`can_run_agent` uses it), `PausedReason.UNSAFE_MODEL` (persisted vocab). *The guard* lives inside
   `apply_audit_internal` (keyword `force`, default false), after it reads the channel and before the `DRY_RUN`
   branch or any write, so a refused apply records nothing, not even the before-state a dry run stores; the
   single-apply route passes its `force` query param; apply-pending reads `channels.agent_enabled` once and refuses
   before any quota check or apply, then passes `force` on, so a channel that turns agent mid-run has its remaining
   applies refused per audit (`failed` rows in the response). The read is `maybe_single`, so an unknown channel id answers as before (nothing pending), not 500. *`run-bulk` and `reaudit-quarantined`* never apply
   (they only call `audit_video`, which writes a `pending` audit), so "when it applies" never holds and they are
   unchanged. *A NULL or missing `agent_enabled`* is a non-agent channel. *`force`* is a FastAPI `bool` query
   parameter (`?force=true`; `1`, `yes`, `on` also parse as true). The dashboard's apply buttons
   (`app/static/channel.html`) send no `force`, so on an agent channel they show the 409.

30. **Triage and routing for titles (Part 2 §2.1, §2.2, §1.3, Part 6 S3.3, F2–F5, F12; #118).** Not in the spec,
   decided here: *`backlinks_enabled` is required* by the backlinks rule (a context without it never answers
   `backlinks`); the tick always sets it. *The title keys* are read only while `title_enabled` holds: on a channel
   whose title lever is closed the context carries `channel_median_ctr` None and `title_excluded` only from
   `TITLE_EXCLUDE_VIDEOS`, so a backlinks-only channel reads no title context. *`is_short`* is `videos.is_short` as
   stored; NULL (not probed) is not a Short, as the warm pool. *A NULL CTR* (no impressions) or no median never
   answers `title`. *The title channel context* (`titles.channel_context`, with its top performers, so the writer's
   context reuses it) is kept as a fourth field of the target pool's `_pools` entry and dropped with it, read
   lazily: the TTL and the test fixture that clears `_pools` cover both. *`title_enabled`'s agent-run limit* applies
   by the video's routed path, whatever its arm, as the spec words it; a video it turns away is declined (lever
   `backlinks`, arm `n/a`, as every `no_change`), back after the cooldown. *Counting today*: one query on the
   channel's `midas` `title` rows created since UTC midnight (`_titles_today`), no paging, since the limits bound a
   day's rows far under 1,000. *No passing candidate* is recorded `cancelled` with no `planned` step (the spec's
   "`None` → `cancelled`"); it is a treated row with `applied_at` NULL, so it counts toward `autopilot_daily_cap`
   (`_applies_today`'s unsent attempts) and toward `TITLE_DAILY_CAP`, like a failed apply. *A writer that raises*
   (OpenRouter down) is not in the spec: recorded `cancelled`, reason `writer_exception`, then re-raised, so the
   tick counts a failure (`agent_failed`) and the video takes the cooldown rather than being picked again next
   tick. *The rationale* of a `no_change` row names backlinks' reason first (now also "backlinks can't run on this
   channel"), then, when the title lever was open for the video, `; title: <why>`; on a backlinks-only channel it
   reads as before. *Both paths* wrote with the pipeline until S3.4 (item 31 swapped the agent in), but `payload.path` and the stamp
   (`titles.strategy_version(path)`) record the routed path, so S3.4 only swaps the writer. *`path_stopped`* was a
   stub here; S3.5 (#120) reads the stop rule into it, and `route` hands off by `path_closed` (item 33). *The gates*: `_agent_tick`'s
   "neither lever can run" uses `titles_open` (channel, switch, not stopped), not the daily limits, so a channel at
   its title cap with backlinks off still ticks and declines; its outcome is `apply_disabled` when
   `BACKLINK_APPLY_ENABLED` is off, else `no_heading`. *The previews*: each takes its own lever as open
   (`_assess(backlinks_on=True)` for `scripts/preview_backlinks.py`, `titles_on=True` for `scripts/preview_titles.py`,
   which ignores `TITLE_APPLY_ENABLED`, `TITLE_CHANNELS` and the daily limits) and sees the other as the tick
   does, so the title preview lists what the SEO team signs off on before the switch is on. The backlinks
   preview shows a `title` answer with its arm only. *The bake-off* (`pick=False`) asks `TRIAGE.rules` on the title
   keys alone (`would_title`), backlinks left out. *The transcript*: from the cache only, as everywhere in titles
   (item 28).

31. **The agent loop, its tools and the trajectory (Part 2 §3.1, §3.2, Part 6 S3.4, F5, F11, F14; #119).** Not in the
   spec, decided here: *The tools are about the run's video only*: the loop passes each tool the `Subject` (the
   video and its channel's title context), and the model passes only the schema's arguments (none, or
   `order`), so a run can't wander to another video or channel and the traces stay comparable (§3.5 (a)). *The
   agent's prompt* lives in `app/titles.py` beside the writer's (`AGENT_PROMPT`, `TITLE_BRIEF` shared, the rendered
   writer prompt unchanged), since `app/agent` imports `titles`. *The agent's stamp* hashes its own prompt (Part 6
   S3.2's note: "until S3.4 gives the agent its own prompt") and adds `agent_model` (`AUDIT_MODEL`) to the five
   inputs, as the reasoning model shapes the agent's titles as much as the writer does; its `audit_strategies` row
   says `code:app/titles.py AGENT_PROMPT` and `model` = `AUDIT_MODEL` (the pipeline's: `WRITER_MODEL`). Only a `planned` row is stamped, as the
   pipeline's: a decline carries no `strategy_version`. *A turn* is one `chat_tools` call; a reply with no tool
   call is told to call one (`NUDGE`) and uses up its turn. Several tool calls in one reply run in order, and a
   terminal call ends the run there (later calls in the reply aren't run). *An invalid submit*: the first failing
   `submit_title` gets `{"error": "check failed: …"}` back, the second ends `failed`, `checks_failed`, whatever came
   between; a `title` that isn't a string counts as a failing submit; the check runs on the stripped title, against
   the video with the channel's `default_language`. *A decline* needs no reason (an empty one is stored).
   *`chat_tools` raising* (OpenRouter down after its retry) isn't in the spec: the loop re-raises with the trajectory
   so far on the exception, and the tick records it as the pipeline's `writer_exception` (`cancelled`, with that
   trajectory) and re-raises, so the video takes the cooldown and the tick counts a failure. *The planned row's
   `candidates`* are the run's submitted titles with their checks and reasoning (the pipeline's are the writer's
   candidates); the writer tool's candidates are in the trajectory. *The trajectory* also carries `writer_model`,
   `max_turns`, `end {kind, reason, detail}` and `submits`; every text (message content, tool-call arguments, tool
   result) is cut to 2,000 characters there, while the model is sent each result whole (a transcript is up to
   `TRANSCRIPT_MAX_CHARS`); results are JSON with `ensure_ascii=False`, so Indic text isn't six times longer.
   *The column is sent only when given* (`interventions.record(trajectory=)`), so pipeline, holdout and backlinks
   rows work before `20261030000000` is applied; an agent-path row doesn't: its insert fails, no row is written,
   the tick counts `agent_failed` and picks the same video next tick, until three failures pause the channel
   (`autopilot._record_failure`). Apply the migration before the agent path can run (`TITLE_APPLY_ENABLED` with
   `TITLE_AGENT_PCT` > 0). *`chat_tools`' retry* is immediate (no pause): a timeout is `httpx.TimeoutException`, a
   5xx a status ≥ 500; a 4xx or a body without `choices` isn't retried. *`get_title_history`* reads each table
   newest first with `limit(10)` (bounded, under the 1,000-row page) and merges; audits of any status, and `title`
   interventions of either origin. *`get_channel_top_performers`* is the channel context's warm long videos (≥
   `WARM_MIN_IMPRESSIONS`, Part 2 §3.2's `MIN_IMPRESSIONS` filter) without the video itself; `worst` counts a
   video with no browse or suggested views as 0, `best` still lists only videos with some (S3.2's context unchanged).
   *`write_candidates`* is one writer call, no retry, its candidates unchecked (the agent's submit is checked).
   *`get_video`'s reach* is the channel context's (the warm window), `agent_tick._reach` for a video outside it.
   *The preview* runs the agent only for treated videos on the agent path (Part 6 S3.2: "for treated ones on the
   path asked"), with transcripts from the cache: with `HOLDOUT_PCT` 0.2 and `TITLE_AGENT_PCT` 0.5 about 40% of
   `--n`, so F12's 20 agent runs need about `--n 50`. *Arguments* may come as a JSON string or, from some
   providers, an object; anything else is an error back to the model. *The daily cap*: an agent decline is treated
   `declined` with no `applied_at`, so `autopilot._applies_today`'s unsent-attempts count now leaves out
   `declined` (F14: declines don't count toward the cap); nothing else writes a treated `declined` row.

32. **Title measurement, verdicts, auto-revert (Part 2 §1.2, §1.3, §1.5, §1.7, Part 6 S3.5, F6–F8, F14; #120).** Not
   in the spec, decided here: *Its own module* (`app/title_measurement.py`), not the pair code: a title is per video,
   and backlinks' and Short links' rows are read and measured exactly as before (`lever_measurement._rows` reads
   only their levers). *d0* is the Pacific date of `applied_at`, else `created_at` (holdout, decline). *A measured
   decline* goes `declined` → `judged`/`insufficient_data` like a holdout; it stays a decline by arm `treated`
   with no `applied_at`. *Completeness* reads only the video's own channel's frontier (the views are its own). *No
   extension*: under the floor is `insufficient_data` at once, with its numbers. *Impressions and CTR* are
   `reach.aggregate` over the two windows, uncertified (a day without a reach row reads as zero), and judge nothing.
   *A judged title put back* stays in its path's mean (`cancelled` with `pre` ≥ `TITLE_MIN_PRE_VIEWS`, which only a
   judged row has): leaving the losers out would raise the path's lift after each revert (intention-to-treat, as
   the declines); the revert changes its status only (`revert_title`), and a cancelled row isn't re-measured, so
   its numbers stay. *The harm guard* is an extra condition on `stop_rule_triggered` for title rows only; both
   rules and the stop are sticky as backlinks' (a triggered row is never cleared). *Auto-revert's holdout mean*:
   the holdout rows judged in the row's judged week, else every holdout row judged so far (not only up to that
   week, so a row isn't stuck when its week and the ones before had none). Worst gap first; the limit counts reverts
   done (a dry run counts), so a skipped human-edited title doesn't use one; the kill switch or a short ledger
   stops the channel's reverts for the run (every later one would refuse the same way); a YouTube error is counted
   and the next row still runs. *The job's title half* runs only on a channel with a `midas` `title` row (one
   `limit(1)` read), so a channel without titles reads nothing more; it has its own `try` and two categories
   (`title interventions`, `title reverts`) and never stops backlinks', Short links' or the playlist test's.
   *The vocab*: the applied `20261023010000`'s `arm_scope` comment can't change (`scripts/apply_migrations.py`
   refuses an applied file whose content changed), so `20261030010000` records the four scopes as a `comment on
   column`, which `tests/test_status_vocab.py` reads; `arm_scope` has no check constraint, so the app needs nothing
   applied. *The endpoint* lives on `lever_verdicts`' router; "treated" counts rows that reached YouTube, "judged"
   the rows in the path's mean; its read includes `trajectory`, so it fails until `20261030000000` is applied.
   *Once per experiment for titles* (Part 6 S3.5 "the video never re-enters the title experiment", Part 2 §2.1): a
   `midas` `title` holdout row, or treated row unless `cancelled` without `applied_at`, holds its video at any age
   (`warm._holds`, `warm_pool()` in `20261030020000`). A decline holds it too, though no title went up: it is in the
   agent's mean over its own 14-day post window (F14), which a re-pick would muddy, and a measured decline is
   `judged`/`insufficient_data` with no `applied_at`, so the rule reads "not cancelled" rather than a status list.
   A treated row cancelled before its write (checks_failed, turn_cap, writer_exception, a refused apply) holds only
   for the cooldown, as backlinks' unsent rows. `tests/test_warm.py`'s helper defaulted to `lever="title"` as "a
   lever with no hold"; it now defaults to `playlist`, and the parity world's `declined_old` is a backlinks
   `no_change` (arm `n/a`), what such a row is in practice.
33. **A path with no share is closed (Part 6 F5, F7; `a1c3d3c`, final review).** Not in the spec, decided here:
   `titles.path_closed` counts a path as closed when its stop rule has fired (`path_stopped`) or it has no share
   (`TITLE_AGENT_PCT` 0 for the agent, 1 for the pipeline). `stopped` = both closed; `route` hands a video to the
   other path only when its own is closed and the other isn't (`app/titles.py`). Before it, with
   `TITLE_AGENT_PCT=0` (F5: the agent preview not signed off) a pipeline stop sent every treated title to the
   unreviewed agent, and since the agent path then had no verdicts it never stopped, so the lever never closed
   (F7). `tests/test_title_verdicts.py`
   `test_a_path_with_no_share_is_closed_so_a_pipeline_stop_closes_the_lever`.

### 7.4 Contradictions within the spec

- **`agent_enabled` and Part 2 §7.** Part 3 B2 adds `channels.agent_enabled` (built, `20261006020000`), but
  Part 2 §7 says `bool default false` where B2 says `bool not null default false` (built as B2 says), and B4's
  warm filter omits it while §2.1's eligibility requires it (B4 defers it to Slice 1's tick routing). Part 2 §7,
  headed "Data model (Phase B)", also lists the Slice 3 `niche_reference_*` columns.
- **Backlink block markers.** Part 2 §3.4 delimits the block by "fixed marker lines"; Part 4 S1.2 finds it "by its
  exact heading line and the `youtu.be` lines under it". Part 4 wins (its Inputs); built as Part 4 (7.3 item 14).
- **Re-embed scope.** Resolved 2026-10-13: Part 2 §4 now says the rollout channel and its siblings first (B10).
- **Sibling detection vs ingestion scope.** Resolved 2026-10-07: Part 2 §2.3 and §8 now say inbound only, from the
  source channel's own report, and a sibling must itself be in `TRAFFIC_INGEST_CHANNELS` (Part 4 finding 1). Built
  so (S1.1, `app/backlinks.py` `siblings`).
- **Playbook storage.** Part 2 §5 puts it in `channels.playbook_json`; Part 2 §7 (data model) doesn't list it.
- **Warm window definition.** §8 `WARM_WINDOW_DAYS` = 28 "ingested data-days", and A7's query is labelled
  "28 ingested days", but the query uses `date > current_date - 30` (calendar days). B4's acceptance compares
  against that query's 566. As built, the filter uses ingested days (7.3 item 12).
- **Intervention status vs measurement status.** Part 2 §7 gives `interventions` both `status` and
  `measurement_status`; B2's lifecycle statuses (`planned`, `applied`, `measuring`, `judged`, `cancelled`) put
  measurement state into `status` too, reusing strings already in `AuditStatus` and `MeasurementStatus`. B2 also
  lists `insufficient_data`, which §1.7 describes as a measurement outcome, and `holdout`, which is also an `arm`
  value. As built, all eight are `InterventionStatus` values (`app/status_vocab.py:184-210`). Resolved by S1.6a:
  `status` carries the lifecycle and the outcome (`judged`, `insufficient_data`); `measurement_status` holds only
  the measurement's progress, `awaiting_window|extended|done` (`InterventionMeasurement`,
  `app/status_vocab.py:223-244`), so the two never disagree about an outcome (§2, 7.3 item 19).
- **What counts as a Midas edit in B3.** B3 skips "every apply" in Phase B, yet Phase B allows no applies. The
  manual paths that still write to YouTube (`POST /audits/{id}/apply`, `/apply-pending`,
  `/playlists/proposals/decide`) are human-triggered through Midas: B3 doesn't say whether they are `human` or
  `midas`. As built (B3a), a description written by any apply or revert counts as Midas's, however it was
  triggered (`app/human_edits.py` `made_by_midas`); likewise (B3b) a membership from an approved proposal counts
  as Midas's, as B3 change 2 says (`app/human_edits.py` `added_by_midas`).
- **"Active intervention" exclusion.** Part 2 §1.6 limits *Midas* interventions to one per video; §2.1 and B4
  exclude videos with "an active intervention" of any origin, which would let human edits block Midas picks.
  Part 3 B2's test says "a second active intervention", no origin. As built (B2), §1.6's reading: `active_for`
  and the partial unique index count `origin = 'midas'` only (`app/interventions.py`,
  `20261006020000_interventions.sql`). B4 (built) counts Midas ones only, for the same reason and because human
  rows never close (7.3 item 12).
- **Which statuses are "active".** Neither Part says. As built: `planned`, `applied`, `measuring` and
  `holdout` (a held-out video is the control arm for its window); `declined` is not, so a `no_change` triage
  doesn't hold a video for a window, and the picker could pick it again next tick (Slice 1's concern)
  (`app/status_vocab.py:217-220`).
- **`get_search_terms`.** A3 answered yes (Part 2 §11.1), but §6's Slice 3 row doesn't list the tool and §7 has
  no storage for terms.
- **`WARM_MIN_IMPRESSIONS`** says "Revisit after Phase A live numbers" (§8); Phase A is done and it wasn't revisited.
- **`decision_log` columns vs backends.** Part 2 §7 names the backend column `jev_answer`/`jev_probs`, while B5's
  default backend is `llm`; and it has no column for the backend's name or the question set's name. As built
  (exact DDL), `jev_answer` holds whichever backend answered; the backend is `DECIDE_BACKEND` at the time and the
  question set is not stored: since S1.5 adds `NEXT_WATCH`, it is told apart by `subject`'s shape (a video id
  for `TRIAGE`, `<source>-><target>` for `NEXT_WATCH`), by `triage_json` on the linked intervention, and, since S2.4, by
  `short_link_recommendations.decision_log_id`, which §8's agreement query uses (7.3 items 13, 18).
- **B5 vs the Phase B exit gate.** Part 3's exit gate wants "`decide()` logs shadow decisions", but B5 adds no
  caller and "Not doing in Phase B" excludes tick routing, so `decision_log` stays empty in Phase B. As built, the
  gate can be met only by `tests/test_decide.py`.
- **Document framing.** "This file has two parts" (How to use) while it has three; "Ground truth used:
  `STATE.md` @ `bddd373`" predates Phase A.

---

## 8. Operational reality

The live DB is unreachable from here. Every figure is from `docs/PHASE_A_FINDINGS.md` or
`docs/PHASE_B_FINDINGS.md`, labelled.

- **Phase B, 2026-10-13** (`docs/PHASE_B_FINDINGS.md`): every registered job `success`. Warm pool (B4, Marathi)
  531, floor 500, top 7,303,586. `video_traffic_source_daily` 4,766 MB / ≈14,969,306 rows; `playlist_traffic_daily`
  12 MB / ≈30,460 rows. Traffic frontiers: Marathi 2026-10-11 (43 data-days both feeds, no gaps from 08-30);
  Hindi, Bhojpuri, English, Gujarati 2026-10-10/11 (35–36). `human` interventions 110, all `playlist`.
  Marathi thresholds (B6, 2026-10-08): `join_high 0.9014`, `join_low 0.8454`, `leave 0.8703` (5,176 sims, 82
  playlists). Office disk: C 94.3 GB free, D 59.2 GB free.
- **2026-10-08 auth incident** (findings doc, "Fix #56"): stored `token_expiry` was July on 12 of 13 channels;
  `video_sync` failed for 6 channels with `HttpError 401 Invalid Credentials` until #56.

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

-- B9b: Marathi's warm pool (B4; S1.4a's five-argument form, which needs 20261023000000 applied; before it, drop
-- the last argument). Arguments: WARM_MIN_IMPRESSIONS, WARM_WINDOW_DAYS, MEASUREMENT_WINDOW_DAYS,
-- TRIAGE_COOLDOWN_DAYS. 0 rows also when reach isn't certified.
select count(1) warm_videos, min(impressions) floor_, max(impressions) top
from warm_pool('UCr5-YUqBiW7PUmeAtxUWuRg', 500, 28, 21, 7);

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

-- B9b (B6; after scripts/reembed.py ran): warm Marathi videos without a B6-recipe vector (want 0), and the
-- stored calibration
select count(1) missing
from warm_pool('UCr5-YUqBiW7PUmeAtxUWuRg', 500, 28, 21, 7) w
where not exists (select 1 from video_embeddings e where e.video_id = w.id and e.chunk_index = 'pooled'
                  and e.model_version = 'google/gemini-embedding-2-preview|tdt-v1');
select id, playlist_thresholds from channels where playlist_thresholds is not null;

-- S1.6a: backlinks interventions by origin, arm, status and measurement progress
select origin, arm, status, measurement_status, count(1)
from interventions where lever = 'backlinks' group by 1,2,3,4 order by 1,2,3,4;

-- S1.6b: weekly verdicts per channel (after 20261023010000 is applied), newest first
select channel_id, arm_scope, week_start, n_treated, n_holdout, lift, cumulative_lift, windows_judged, verdict,
       stop_rule_triggered
from lever_verdicts order by channel_id, week_start desc, arm_scope;

-- S2.1: the playlist test's arms per channel (after 20261027000000 is applied), and its proposals by status
select channel_id, arm, status, count(1), sum(coalesce(array_length(proposal_ids, 1), 0)) proposals
from playlist_arms group by 1,2,3 order by 1,2,3;
select a.channel_id, p.status, count(1)
from playlist_proposals p join playlist_arms a on a.id = p.arm_id group by 1,2 order by 1,2;

-- S2.2: the test's adds sent and failing, per channel and arm status, with each arm's dose dates
select a.channel_id, a.status, count(1) filter (where p.applied_at is not null) sent,
       count(1) filter (where p.applied_at is null and p.apply_error is not null) failing,
       min(a.first_applied_at) first_applied, max(a.last_applied_at) last_applied
from playlist_arms a join playlist_proposals p on p.arm_id = a.id
where a.arm = 'treated' group by 1,2 order by 1,2;

-- S2.3: the playlist test's arms by measurement progress, and its weekly verdicts
select channel_id, arm, status, measurement_status, count(1),
       max(jsonb_array_length(measurement_result->'weeks')) weeks
from playlist_arms group by 1,2,3,4 order by 1,2,3,4;
select channel_id, week_start, windows_judged, n_treated, n_holdout, lift, cumulative_lift, verdict,
       stop_rule_triggered
from lever_verdicts where lever = 'playlist' order by channel_id, week_start;

-- S2.4: Short-link recommendations per channel and status (after 20261027010000 is applied), and how many have
-- their shadow next-watch logged
select channel_id, status, count(1), count(distinct short_id) shorts, count(decision_log_id) logged
from short_link_recommendations group by 1,2 order by 1,2;

-- S2.5/S2.6: Short links the team ticked as set and those seen in the traffic (timing ticked |
-- inferred_from_traffic), per channel, with how many were recommended and how far their measurement got
select channel_id, payload->>'timing' timing, status, measurement_status, count(1),
       count(1) filter (where (payload->>'recommended')::boolean) recommended, max(detected_at) latest
from interventions where lever = 'short_link' group by 1,2,3,4 order by 1,2,3,4;

-- S2.6: recommendations seen in the traffic, per channel and status
select channel_id, status, count(1), count(seen_at) seen
from short_link_recommendations group by 1,2 order by 1,2;

-- S2.6: the weekly short_link human verdict rows
select channel_id, week_start, n_treated, treated_mean_delta, windows_judged
from lever_verdicts where lever = 'short_link' order by channel_id, week_start;

-- S3.3: title rows per channel, arm, status and path (the agent tick, #118), today's against TITLE_DAILY_CAP
select channel_id, arm, status, payload->>'path' path, payload->'error'->>'reason' error, count(1),
       count(1) filter (where created_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc') today
from interventions where origin = 'midas' and lever = 'title' group by 1,2,3,4,5 order by 1,2,3,4,5;

-- S3.4: agent runs per channel by how they ended (after 20261030000000 is applied), with their turns
select channel_id, status, trajectory->'end'->>'kind' ended, trajectory->'end'->>'reason' reason, count(1),
       round(avg((trajectory->>'turns')::int), 1) avg_turns
from interventions where origin = 'midas' and lever = 'title' and payload->>'path' = 'agent'
group by 1,2,3,4 order by 1,2,3,4;

-- S3.5: title rows per channel and path by measurement outcome, with the mean delta and the auto-reverts
-- (holdout rows have no path: 'holdout'); a decline is arm treated with no applied_at
select channel_id, coalesce(payload->>'path', 'holdout') path, arm, status, measurement_status,
       count(1), round(avg((measurement_result->>'delta')::numeric), 3) mean_delta,
       count(1) filter (where applied_at is null and arm = 'treated') declines,
       count(1) filter (where (payload->'revert'->>'auto')::boolean) auto_reverts
from interventions where origin = 'midas' and lever = 'title' group by 1,2,3,4,5 order by 1,2,3,4,5;

-- S3.5: the title verdicts per path, oldest week first
select channel_id, arm_scope, week_start, n_treated, n_holdout, lift, cumulative_lift, windows_judged, verdict,
       stop_rule_triggered
from lever_verdicts where lever = 'title' order by channel_id, arm_scope, week_start;

-- S2.6 (E12): shadow agreement per question set, read-only. TRIAGE rows have a video id as subject, NEXT_WATCH
-- rows <source>-><target>; the Short-link NEXT_WATCH rows are those a recommendation's decision_log_id points at,
-- the backlinks ones those decide.link pointed at an intervention, and the rest (a write that failed) unlinked.
-- A backend failure is a NULL jev_answer; agreement is over the rows the backend answered.
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
