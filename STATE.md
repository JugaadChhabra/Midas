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

**Generated:** 2026-10-26 (Slice 2 S2.2 #88: `decide_proposals` only queues a proposal with `arm_id`, the daily `playlist_test_apply` job (11:00 UTC, `app/playlist_test.py` `run_apply`, `apply_channel`), `playlist_test.test_dates`, `yt_playlist_items_insert(position=)`, `PLAYLIST_APPLY_ENABLED`, `PLAYLIST_TEST_DAILY_UNITS`, `PLAYLIST_TEST_MAX_ATTEMPTS`; no migration). Earlier: 2026-10-26 (Slice 2 S2.1 #87: `playlist_arms` and four `playlist_proposals` columns in migration `20261027000000` (not applied), `app/playlist_test.py` (`eligible`, `survey`, `assign_arm`, `candidates`, `draw`, `preview`), `scripts/playlist_test.py`, `PLAYLIST_HOLDOUT_PCT`, `PLAYLIST_TEST_MAX_ADDS`, `status_vocab.PlaylistArm`/`PlaylistArmStatus`/`PlaylistArmMeasurement`/`PlaylistProposalSource`, `experiment` → "Playlist test" in `channel.html` `DECIDED_BY`). Earlier: 2026-10-26 (Slice 2 specified: spec Part 5, owner decisions E1–E13, tickets #87–#94; no code yet). Earlier: 2026-10-26 (fleet readiness #84/#85 deployed 2026-10-26; same day at the office: `reach_warmup = t` on Haryanvi, Rajasthani, 3D Animated, Kannada, Telugu, `TRAFFIC_INGEST_CHANNELS` = all 13 in the office `.env`, Hindi re-consented; Kannada and Telugu have no uploads on YouTube, owner). Earlier: 2026-10-25 (fleet readiness: backlink headings for every channel language in `backlinks.HEADINGS`, `YT_QUOTA_COLLECTION_RESERVE` on the autopilot apply gate, `app/channel_health.py` (`GET /health/channels`, the daily `channel_health` job), `video_sync` `degraded` on token skips; owner decisions 2026-10-25 in `docs/PLAN_TO_2026-11-27.md`). Earlier: 2026-10-25 (Slice 1 deployed and live on Marathi 2026-10-24: `BACKLINK_APPLY_ENABLED=true` in the office `.env`, Marathi `agent_enabled = autopilot_enabled = t`, `autopilot_daily_cap = 40`; Marathi re-consented 2026-10-24, Hindi, Bhojpuri, Punjabi tokens dead since 2026-10-16. Forward plan: `docs/PLAN_TO_2026-11-27.md`). Earlier: 2026-10-23 (#55: `client_max_body_size 16m` in `deploy/postgrest-proxy.conf`). Earlier: 2026-10-23 (Marathi backlink heading `आणखी गाणी पहा:` in `backlinks.HEADINGS`). Earlier: 2026-10-23 (Slice 1 review fixes: a treated `backlinks` row that never reached YouTube no longer uses up its video, the agent does nothing while `BACKLINK_APPLY_ENABLED` is off or the language has no heading, unsent treated attempts count toward the cap, `TITLE_AUTOPILOT_ENABLED`, `render`'s byte limit). Earlier: 2026-10-23 (Slice 1 S1.6b #68: `lever_verdicts` in migration `20261023010000` (not applied), `app/lever_verdicts.py` (`write_verdicts`, `run_weekly`, `GET /channels/{id}/interventions`, `GET /channels/{id}/lever-verdicts`), the weekly `lever_measurement` job (Mon 09:00 UTC), `agent_tick.backlinks_stopped` reading the stop rule, `BACKLINK_EXPERIMENT_WINDOWS`, `BACKLINK_MIN_LIFT`, `status_vocab.LeverVerdictScope`/`LeverVerdict`). Earlier: 2026-10-23 (Slice 1 S1.6a #67: `app/lever_measurement.py` `measure_channel`, pair measurement per backlinks intervention, not scheduled; `LEVER_MIN_SOURCE_VIEWS`; `status_vocab.InterventionMeasurement` for `interventions.measurement_status`). Earlier: 2026-10-23 (Slice 1 S1.5 #66: `decide.NEXT_WATCH`, asked in shadow per candidate pair by `app/agent_tick.py` `_next_watch` and stored as `triage_json.next_watch`, `backlinks.Candidates.join_low`, `QUESTION_SET_VERSION = "2026.10-s1-v2"`). Earlier: 2026-10-23 (Slice 1 S1.4b #65: the agent tick, `app/agent_tick.py` (`run`, `preview`, `backlinks_stopped`), `autopilot._agent_tick` behind `channels.agent_enabled`, `eligibility.can_run_agent`, `_applies_today` counting applied Midas interventions, `decide()` returning `log_id` and `decide.link`, the TRIAGE stop-rule input and `QUESTION_SET_VERSION = "2026.10-s1-v1"`, `scripts/preview_backlinks.py`). Earlier: 2026-10-23 (Slice 1 S1.3 #64: `app/backlinks_apply.py` `apply_backlinks` and `POST /interventions/{id}/revert`, `BACKLINK_APPLY_ENABLED`, `ApplyOutcome.QUOTA_INSUFFICIENT`/`APPLY_DISABLED`, `human_edits.made_by_midas` knows applied Midas blocks). Earlier: 2026-10-23 (Slice 1 S1.4a #63: `warm_pool()` replaced by `20261023000000`, cooldown and once-per-experiment exclusions in it and `app/warm.py`, `TRIAGE_COOLDOWN_DAYS`). Earlier: 2026-10-23 (Slice 1 S1.1 #62: `app/backlinks.py` `siblings`/`candidates`, `SIBLING_MIN_VIEWS`, `warm.warm_impressions`, `reach.coverage(report_type=)`). Earlier: 2026-10-23 (Slice 1 S1.2 #61: `app/backlinks.py`, `BACKLINK_MAX`). Earlier: 2026-10-13 (B10: Phase B deployed 2026-10-07/08 and its exit gate passed 2026-10-13, `docs/PHASE_B_FINDINGS.md`; #56, 2026-10-08: `youtube_client.channel_credentials`). Earlier: 2026-10-06 (full regeneration from §9; updated for B1a #30: `traffic_poll`, `video_traffic_source_daily`; B1b #31: `playlist_traffic_daily`; B8 #39: token failures skip in `video_sync`; B2 #32: `interventions`, `assign_arm`, `HOLDOUT_PCT`, `channels.agent_enabled`; B3a #33: `app/human_edits.py`, `interventions.ledger_key`; B3b #34: playlist-membership ledger in the walk; B4 #35: `app/warm.py`, `warm_pool()`, `WARM_*`; B5 #36: `app/decide.py`, `decision_log`, `DECIDE_BACKEND`, `BACKLINK_MIN_CANDIDATES`, the stamp's question-set version; B6 #37: `app/reembed.py`, `scripts/reembed.py`, `channels.playlist_thresholds`; B7 #38, 2026-10-07: `bho`/`raj` in `_LANG_NAMES` and `_NON_ISO_639_1`) · **Commit:** on top of `9828d73` · **Branch:** `slice-2/88-slice-2-s2-2-queued-budgeted-playlist-ap`
(Older design docs are deleted in the same change and live only in git history; nothing below cites them.
`scripts/overnight_tickets.sh` is dev tooling, never deployed.)

**The spec**, cited below as **spec**: `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md`. Its
status line: Part 1 (Phase A) done, exit gate passed 2026-10-06; Part 3 (Phase B) done, exit gate passed 2026-10-13;
Part 4 (Slice 1) built and live on Marathi; **Part 5 (Slice 2) "ready to build"** (2026-10-26); Part 2
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
migration `20261006040000`; picked from by Slice 1's agent tick since S1.4b, not deployed) and B5 (#36: `app/decide.py`, `decision_log` in migration
`20261006050000`; called since Slice 1 S1.4b by `app/agent_tick.py`, not deployed) and B6 (#37: `app/reembed.py`, run by `scripts/reembed.py`,
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
| **Phase A** | Gates | **done** (exit gate passed 2026-10-06, spec status line) | A4: `app/config.py:115-117,34`, `app/main.py:323-364`, `tests/test_frozen_writers.py`. A5: `app/transcripts.py:25-31`, `app/youtube_metadata.py:58-59` (the `bgc` entries). A6: `app/audits.py:199-286`, `tests/test_strategy_version.py`. A8: `app/job_status.py`, `app/main.py:77-103,562-565`, `tests/test_main_fanout.py`. A10: `app/autopilot.py:501-514,631,699`, `app/audits.py:830-837`, `tests/test_revert_quota_gate.py`. Probes: `scripts/probes/*.py`. Record: `docs/PHASE_A_FINDINGS.md` | Every lever outcome (a) (findings "Phase A conclusion" §1). A5's `default_language = 'bgc'` was already set on Haryanvi (findings "Next session" item 5); the optional i18n probe was not run (A5 table blank). The findings "Exit gate" checklist ticks A11 with this §9-based regeneration (2026-10-06). |
| **Phase B** | Plumbing (spec Part 3, B1–B10) | **done** (exit gate passed 2026-10-13; deployed 2026-10-07/08; `docs/PHASE_B_FINDINGS.md`) | B1a/B1b: `app/traffic_poll.py`, `app/reporting_client.py` (`ensure_job`, `parse_traffic_csv`, `parse_playlist_traffic_csv`, `TRAFFIC_SOURCE_TYPES`), `app/reporting_poll.py` (`replace_data_day`, `record_ingested`), `supabase/migrations/20261006000000_video_traffic_source_daily.sql`, `supabase/migrations/20261006010000_playlist_traffic_daily.sql`, `tests/test_traffic_poll.py`, `tests/test_reporting_ingest.py`. B8: `app/sync.py:41-70` (`TokenExpired`, `_token_failure_as_401`), `tests/test_sync_token_expiry.py`. B2: `app/interventions.py` (`assign_arm`, `active_for`, `record`), `app/status_vocab.py:143-220` (`Intervention*`, `ACTIVE_INTERVENTION_STATUSES`), `supabase/migrations/20261006020000_interventions.sql`, `HOLDOUT_PCT` (`app/config.py:234`), `tests/test_interventions.py`. B3a: `app/human_edits.py` (`video_links`, `made_by_midas`, `record_description_edits`), `app/sync.py:143-153,262-265,288-297` (`_record_human_edits`), `interventions.record(ledger_key=…)`, `supabase/migrations/20261006030000_interventions_ledger_key.sql`, `tests/test_human_edits.py`. B3b: `app/human_edits.py` (`added_by_midas`, `record_playlist_additions`), `app/playlists_sync.py:297-328,359-368` (`_record_human_memberships`), `tests/test_human_edits_playlists.py`. B4: `app/warm.py` (`ranked_pool`, `explore_order`, `warm_pool`), `supabase/migrations/20261006040000_warm_pool_rpc.sql` (`warm_pool()`), `WARM_*` (`app/config.py:235-247`), `app/reach.py` (`certify_covered`, `window_length`), `tests/test_warm.py`, `tests/test_warm_pool_parity.py`, `tests/test_warm_pool_parity_live.py`. B5: `app/decide.py` (`decide`, `Decision`, `QuestionSet`, `TRIAGE`, `QUESTION_SET_VERSION`, `NotConfigured`), `supabase/migrations/20261006050000_decision_log.sql`, `DecisionUsed` (`app/status_vocab.py:223-233`), `DECIDE_BACKEND`, `BACKLINK_MIN_CANDIDATES` (`app/config.py:248-255`), `tests/test_decide.py`. B6: `app/reembed.py` (`recipe_text`, `MODEL_VERSION`, `estimate_channel`, `reembed_channel`, `calibrate_channel`), `scripts/reembed.py`, `supabase/migrations/20261006060000_channels_playlist_thresholds.sql`, `model_version` keyword on `app/embeddings.py` `pooled_embeddings`/`embedded_video_ids`, `tests/test_reembed.py`. B7 (code half): `bho`/`raj` in `_LANG_NAMES` (`app/transcripts.py:25-36`) and `_NON_ISO_639_1` (`app/youtube_metadata.py:58-64`), `tests/test_language_codes.py`, `tests/test_youtube_metadata.py` | In Phase B nothing called `decide()`, so `decision_log` got no rows; Slice 1's agent tick (S1.4b, `app/agent_tick.py`) is its first caller, not deployed; only the B3 human ledger writes `interventions` (`human` rows: backlinks on full syncs, playlist memberships on the membership walk); the warm filter is picked from only by S1.4b's agent tick (`app/agent_tick.py`; `tests/test_warm.py` guards that; S1.1's candidates use its `warm_impressions`); the B6 recipe's vectors and `channels.playlist_thresholds` are written only by the one-off `scripts/reembed.py` (run for Marathi 2026-10-07/08) and read in production only by S1.1's `backlinks.candidates`, called by S1.4b's agent tick on `agent_enabled` channels; the `bho`/`raj` entries are unused, since the owner chose plain `hi` for Bhojpuri and Rajasthani (2026-10-06, `app/youtube_metadata.py:60-61`) and they exist so those channels can switch later without a code change. Partial footholds listed in §7.1. |
| **Slice 1** | Backlinks + no change | **live on Marathi since 2026-10-24** (deployed per `docs/agents/s1-7-office-steps.md`; first treated applies 07:38 UTC, interventions 187–195; exit gate pending: first weekly verdict, #70) | S1.1: `app/backlinks.py` (`siblings`, `candidates`, `Candidates`), `SIBLING_MIN_VIEWS` (`app/config.py:264`), `app/warm.py` `warm_impressions`, `tests/test_backlink_candidates.py`. S1.2: `app/backlinks.py` (`render`, `find`, `strip`, `HEADINGS`), `BACKLINK_MAX` (`app/config.py:259`), `tests/test_backlinks.py`. S1.4a: `supabase/migrations/20261023000000_warm_pool_agent_exclusions.sql` (`warm_pool()`), `app/warm.py` `_holds`, `TRIAGE_COOLDOWN_DAYS` (`app/config.py:269`), `tests/test_warm.py`, `tests/test_warm_pool_parity.py`. S1.3: `app/backlinks_apply.py` (`apply_backlinks`, `revert_intervention` = `POST /interventions/{id}/revert`), `BACKLINK_APPLY_ENABLED` (`app/config.py:273`), `ApplyOutcome.QUOTA_INSUFFICIENT`/`APPLY_DISABLED` (`app/apply_outcome.py`), `app/human_edits.py` `_midas_block`, `tests/test_backlinks_apply.py`. S1.4b: `app/agent_tick.py` (`run`, `preview`, `backlinks_stopped`), `app/autopilot.py` (`_agent_tick`, the `agent_enabled` branch in `tick`, `_applies_today`, `_react_to_apply_error`), `app/eligibility.py` `can_run_agent`, `app/decide.py` (`Decision.log_id`, `link`, `backlinks_stopped` in the TRIAGE rules), `scripts/preview_backlinks.py`, `tests/test_agent_tick.py`. S1.5: `app/decide.py` (`NEXT_WATCH`, `_next_watch_rules`), `app/agent_tick.py` `_next_watch`, `backlinks.Candidates.join_low`, `tests/test_decide.py`, `tests/test_agent_tick.py`. S1.6a: `app/lever_measurement.py` (`measure_channel`, `pair_views`, `windows`, `as_of`), `LEVER_MIN_SOURCE_VIEWS` (`app/config.py:278`), `InterventionMeasurement` (`app/status_vocab.py:223-244`), `tests/test_lever_measurement.py`. S1.6b: `supabase/migrations/20261023010000_lever_verdicts.sql`, `app/lever_verdicts.py` (`verdicts`, `write_verdicts`, `run_weekly`, the two read endpoints), the `lever_measurement` job (`app/main.py` `_register_jobs`), `app/agent_tick.py` `backlinks_stopped`, `BACKLINK_EXPERIMENT_WINDOWS`, `BACKLINK_MIN_LIFT` (`app/config.py:283,287`), `LeverVerdictScope`, `LeverVerdict` (`app/status_vocab.py:247-271`), `tests/test_lever_verdicts.py`, `tests/test_agent_tick.py` | Tick routing is built (S1.4b) but no channel has `agent_enabled = t` (set by the owner for Marathi at S1.7, with `autopilot_enabled = t` and `autopilot_daily_cap = 40`, D4), and none of Slice 1 is deployed; `20261023000000` and `20261023010000` are not applied. The candidate finder (S1.1) finds only Marathi targets until the siblings are re-embedded (S1.7). The block renderer's heading table is empty (S1.2), so every render refuses until the SEO team's Marathi heading is added (D3, S1.7): a treated row is `cancelled` with `failed: render refused`. Every treated row is `cancelled` with `apply_disabled` while `BACKLINK_APPLY_ENABLED` is false (the default). Pair measurement (S1.6a) and the weekly verdicts and stop rule (S1.6b) run in the weekly `lever_measurement` job (Monday 09:00 UTC, `app/lever_verdicts.py` `run_weekly`); until there are judged treated and holdout rows it writes no verdict, so the lever can't stop (`agent_tick.backlinks_stopped` reads `lever_verdicts`). The next-watch question (S1.5) is asked in shadow for every candidate pair of a video triaged to `backlinks`; its rules answer is always `yes` there, since `candidates` keeps only pairs ≥ `join_low`, so what it records is the backend's agreement. Title autopilot is off on every channel (header), which is the spec's precondition (spec Part 2 §6.1). |
| **Slice 2** | Playlist test (P3) + Short links (P4) | **in build** (spec Part 5, ready to build 2026-10-26; tickets #87–#92 code, #93 deploy, #94 docs): S2.1 (#87) and S2.2 (#88) built, not deployed; S2.3–S2.6 not started | S2.1: `supabase/migrations/20261027000000_playlist_arms.sql`, `app/playlist_test.py` (`survey`, `eligible`, `assign_arm`, `candidates`, `draw`, `preview`, `AlreadyDrawn`), `scripts/playlist_test.py`, `PLAYLIST_HOLDOUT_PCT`, `PLAYLIST_TEST_MAX_ADDS` (`app/config.py`), `PlaylistArm`, `PlaylistArmStatus`, `PlaylistArmMeasurement`, `PlaylistProposalSource` (`app/status_vocab.py`), `DECIDED_BY.experiment` (`app/static/channel.html`), `tests/test_playlist_test.py`, `tests/test_status_vocab.py`. S2.2: `app/playlists_router.py` `decide_proposals` (the `arm_id` branch), `app/playlist_test.py` (`run_apply`, `apply_channel`, `test_dates`, `POSITION_REFUSED`), the `playlist_test_apply` job (`app/main.py` `_register_jobs`), `app/youtube_client.py` `yt_playlist_items_insert(position=)`, `PLAYLIST_APPLY_ENABLED`, `PLAYLIST_TEST_DAILY_UNITS`, `PLAYLIST_TEST_MAX_ATTEMPTS` (`app/config.py`), `tests/test_playlist_test_apply.py`. Pre-spec engine frozen: `app/playlists.py`, `app/playlist_discovery.py` | The draw is built but nothing runs it: the owner runs `scripts/playlist_test.py --preview`, then `--draw`, at S2.7, after `20261027000000` is applied. Approving a test proposal (`arm_id` set) in the dashboard card only marks it `approved` (S2.2, `app/playlists_router.py` `decide_proposals`); the daily `playlist_test_apply` job sends it, and does nothing while `PLAYLIST_APPLY_ENABLED` is false (the default). The card's toast still says "Executed 0 change(s) on YouTube." for them; the response carries `queued`. Recommend-only proposal machinery exists (`playlist_proposals`, `app/playlists_router.py:271-297`). The add/remove and creation paths are frozen by default (§4). |
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
(`20261006020000`, B2; applied 2026-10-07; read by `autopilot.tick` and `eligibility.can_run_agent` since S1.4b, set on no channel).

---

## 2. Schema — as applied

**Migrations** (`supabase/migrations/`, in order; bootstrap `supabase/bootstrap/000_roles.sql`,
`010_storage_shim.sql` run first). The latest is `20261027000000` (S2.1, #87), not applied; `20261023010000` (S1.6b, #68) and `20261023000000` (S1.4a, #63) are not applied either. `20261006060000` (B6, #37), `20261006050000` (B5, #36), `20261006040000` (B4, #35), `20261006030000` (B3a, #33), `20261006020000` (B2, #32),
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
  of that set (`tests/test_status_vocab.py`). Two writers: the B3 human ledger (`app/human_edits.py`, two
  `human` row kinds) and, since S1.4b, the agent tick (`app/agent_tick.py`, `midas` `backlinks` rows: `declined`
  arm `n/a` with `payload.rationale`; `holdout` with `payload.targets`; `planned` → `measuring` or `cancelled`
  with `payload.error = {reason, detail}`; each with `triage_json`, §5). Since S1.6a, `app/lever_measurement.py`
  `measure_channel` updates `backlinks` rows' `status`, `measurement_status` and `measurement_result` (below; run
  weekly by the `lever_measurement` job since S1.6b). **B3a:** one
  row per link to one of our videos that the team added to a description, `origin='human'`, `lever='backlinks'`,
  `arm='n/a'`, `status='applied'`, `applied_at` NULL, `detected_at` = when the sync saw it, and `payload`
  `{source_video_id, target_video_id, added_targets, removed_targets, timing}` (plus `removed_detected_at` once a
  later sync sees the link gone). `ledger_key` = `backlinks:<source>:<target>:<first 16 hex of sha256 of the new
  description, whitespace collapsed>`. **B3b:** one row per membership of one of the channel's videos in one of its
  playlists that the membership walk sees for the first time, in a playlist it has walked before, and that Midas
  didn't add: `lever='playlist'`, same `origin`/`arm`/`status`/`applied_at`/`detected_at` as B3a, `payload`
  `{playlist_id, video_id, playlist_item_id, timing}`, `ledger_key` = `playlist:<playlist_id>:<video_id>:<playlist_item_id>`.
  `ledger_key` is NULL on any other row.
  **Measurement (S1.6a).** `status` is the lifecycle and carries the outcome: `measuring` (treated), `holdout`
  and `applied` (human) → `judged` or `insufficient_data`. `measurement_status` only says how far the measurement
  got (`InterventionMeasurement`, `app/status_vocab.py:223-244`): `awaiting_window|extended|done`, NULL until the
  first run; every other row and lever leaves it NULL. `measurement_result` on a decided row:
  `{pre, post, delta, source_views, missing_days, window: {d0, pre: [start, end], post: [start, end], post_days,
  extended}, judged_at, computed_at}` (§5 `lever_measurement.py`).
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
- **`video_embeddings`**: `video_id, chunk_index, model_version text not null, embedding vector(3072), unique (video_id, chunk_index, model_version)` (`20260518000000_playlists.sql:10-12`). Production writes use `model_version = EMBED_MODEL` (`app/embeddings.py:133`), from two input recipes (§6). B6's one-off re-embed writes a second value, `app/reembed.py` `MODEL_VERSION` = `"google/gemini-embedding-2-preview|tdt-v1"` (`EMBED_MODEL` + `"|"` + `RECIPE`, `app/reembed.py:33-34`), one recipe for every video (§6); every production reader filters on `EMBED_MODEL`, and every caller of the `p_model_version` RPCs passes it, except `app/backlinks.py` `candidates` (S1.1), which reads only `MODEL_VERSION` and is called by the agent tick (`app/agent_tick.py`).
- **Other tables:** `audit_configs` (`raw_insights, generated_prompt, shorts_prompt, niche_queries jsonb, reflection_mode default 'shadow'`), `prompt_versions`, `threshold_history`, `playlist_assignments`, `playlist_proposals` (§2 `playlist_arms` for its S2.1 columns), `video_keyframes`, `video_transcripts`, `quota_log`, `shorts_jobs`, `shorts_clips`. SQL functions: `dashboard_summary()`, `playlist_video_sims()`, `discover_orphan_clusters()`, `next_audit_candidate()`, `warm_pool()` (B4, replaced by S1.4a, below).

- **`warm_pool()`** (`20261023000000`, S1.4a #63, replacing B4's `20261006040000`), verbatim without its header
  comment. Its in-app twin is `app/warm.py` `_ranked_pool_inapp`; the agent tick picks through `warm.warm_pool` (§5). On top of B4's
  active-Midas exclusion it skips a video with any `midas` row created within `p_cooldown_days`
  (`TRIAGE_COOLDOWN_DAYS`), whatever its lever or status, or any `midas` `backlinks` row of arm `treated` or
  `holdout`, at any age. The four-argument B4 function is dropped, not overloaded:
  ```sql
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
          )
      )
    order by rc.impressions desc, v.id;
  $$;

  revoke execute on function warm_pool(text, bigint, int, int, int) from public;
  grant  execute on function warm_pool(text, bigint, int, int, int) to service_role;
  ```

- **`decision_log`** (`20261006050000`, B5), verbatim without its header comment. Written only by
  `app/decide.py` `decide()`, called by the agent tick (`app/agent_tick.py` `run`), which then sets `intervention_id`
  through `decide.link` (§5). `subject` is the video id for `TRIAGE` rows and `<source id>-><target id>` for
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
  `used` vocab (`app/status_vocab.py:274-284`, `DecisionUsed`): `rules|jev`; always `rules` in shadow. `jev_answer`
  / `jev_probs` hold the configured backend's answer (`llm` by default), NULL when the backend failed.

- **`lever_verdicts`** (`20261023010000`, S1.6b #68), verbatim without its header comment. Written only by
  `app/lever_verdicts.py` `write_verdicts`, from the weekly `lever_measurement` job; read by
  `lever_verdicts.stopped` (the stop rule, through `agent_tick.backlinks_stopped`) and `GET /channels/{id}/lever-verdicts`:
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
  Vocab (`app/status_vocab.py:247-271`): `arm_scope` `treated_vs_holdout|human` (`LeverVerdictScope`), `verdict`
  `helped|no_change|worse` (`LeverVerdict`), NULL on `human` rows; `tests/test_status_vocab.py` checks the
  migration's column comments against them. `week_start` is the Monday (UTC) of the week the rows were judged
  in (`measurement_result.judged_at`). A `treated_vs_holdout` row: `n_treated`/`n_holdout` and the two means over
  the `midas` rows judged that week, `lift` = treated mean delta − holdout mean delta, `cumulative_lift` the same
  over every row judged up to that week, `windows_judged` = the channel's `treated_vs_holdout` weeks so far
  (this one included), `verdict` = `helped` at `lift` ≥ `BACKLINK_MIN_LIFT`, `worse` at ≤ −it, else
  `no_change`, `stop_rule_triggered` = `windows_judged` ≥ `BACKLINK_EXPERIMENT_WINDOWS` and `cumulative_lift` <
  `BACKLINK_MIN_LIFT`. A `human` row: `n_treated` and `treated_mean_delta` of the `human` rows judged that week;
  `n_holdout` 0, `holdout_mean_delta`, `lift`, `cumulative_lift` and `verdict` NULL, never stopped. The DDL adds
  `id` and the unique key to the ticket's column list; types and `not null`s are this build's.

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
  `status`/`decided_at`. Nothing writes `measurement_*` yet (S2.3):
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

Of the spec's Phase B tables `video_traffic_source_daily`, `playlist_traffic_daily`, `interventions` and `decision_log` exist (plus `channels.agent_enabled`, and B6's `channels.playlist_thresholds`, which the spec doesn't name); the rest, and the Slice tables and columns, are listed in §7.1.

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
| `STRATEGY_LABEL` | `:302` `os.getenv("STRATEGY_LABEL") or "2026.07-baseline"` | prefix of a derived `strategy_version` (A6, Part 2 §8) | derived per audit, not at startup (§7.3) |
| `MIN_IMPRESSIONS` | `:185` `int(os.getenv("MIN_IMPRESSIONS") or "500")` | `WARM_MIN_IMPRESSIONS` starts "Same as `MIN_IMPRESSIONS`" (Part 2 §8) | no (a separate setting, same default) |
| `MEASUREMENT_WINDOW_DAYS` | `:184` `or "21"` | measurement runs weekly (Part 2 §1.1); 14-day extension (§1.7) | **differs** (21-day window) |
| `PLAYLIST_JOIN_HIGH` / `_LOW` / `PLAYLIST_LEAVE` | `:120-122` `or "0.72"` / `"0.55"` / `"0.60"`, process-global | per channel, recalibrated (Part 2 §4, Part 3 B6) | **differs** in use: B6 calibrates per channel into `channels.playlist_thresholds` (`app/reembed.py` `calibrate_channel`, never writing `settings`), but the engine still reads these globals |
| `TRAFFIC_INGEST_CHANNELS` | `:226-230` `{c.strip() for c in (os.getenv("TRAFFIC_INGEST_CHANNELS") or "UCr5-YUqBiW7PUmeAtxUWuRg").split(",") if c.strip()}` | the rollout channel (Part 2 §8) | no |
| `HOLDOUT_PCT` | `:234` `float(os.getenv("HOLDOUT_PCT") or "0.20")` | 0.20, per lever, stable hash (Part 2 §8) | no. Read only by `app/interventions.py` `assign_arm` |
| `WARM_MIN_IMPRESSIONS` | `:239` `int(os.getenv("WARM_MIN_IMPRESSIONS") or "500")` | 500 (Part 2 §8) | no. Read only by `app/warm.py` |
| `WARM_WINDOW_DAYS` | `:240` `int(os.getenv("WARM_WINDOW_DAYS")     or "28")` | 28 "Ingested data-days" (Part 2 §8) | no: the latest 28 reach data-days in the ledger (`app/warm.py`) |
| `WARM_EXPLORE_PCT` | `:241` `float(os.getenv("WARM_EXPLORE_PCT")   or "0.10")` | 0.10 "Picks from the non-top warm pool" (Part 2 §8) | no. Read only by `app/warm.py` `warm_pool` |
| `DECIDE_BACKEND` | `:252` `os.getenv("DECIDE_BACKEND") or "llm"` | `llm`; `jev` once access is set up (Part 2 §8) | no. Read only by `app/decide.py`; `jev` is a stub raising `NotConfigured`, an unknown value is a backend failure (rules answer stands) |
| `BACKLINK_MIN_CANDIDATES` | `:255` `int(os.getenv("BACKLINK_MIN_CANDIDATES") or "2")` | 2 (Part 2 §8) | no. Read only by `app/decide.py` `TRIAGE` rules |
| `BACKLINK_MAX` | `:259` `int(os.getenv("BACKLINK_MAX") or "3")` | 3 (Part 4 Config, Part 2 §8) | no. Read only by `app/backlinks.py` `render`, at call time, which refuses more targets rather than trimming |
| `AUDIT_MODEL` | `:29` `os.getenv("AUDIT_MODEL") or "anthropic/claude-haiku-4.5"`; dev `.env`: `google/gemini-3.7-flash` | reasoning model (Part 2 §3.1) | — |
| `SIBLING_MIN_VIEWS` | `:264` `int(os.getenv("SIBLING_MIN_VIEWS") or "100")` | 100, inbound only (Part 4 Config, Part 2 §8) | no. Read only by `app/backlinks.py` `siblings`, over the source channel's latest 28 ingested traffic data-days (`SIBLING_WINDOW_DAYS`, a module constant) |
| `TRIAGE_COOLDOWN_DAYS` | `:269` `int(os.getenv("TRIAGE_COOLDOWN_DAYS") or "7")` | 7 (Part 4 Config, finding 2; Part 2 §2.1, §8) | no. Read only by `app/warm.py` (in-app cooldown, and `p_cooldown_days` of the `warm_pool()` RPC) |
| `BACKLINK_APPLY_ENABLED` | `:273` `os.getenv("BACKLINK_APPLY_ENABLED", "false").lower() == "true"` | false, the kill switch for YouTube writes (Part 4 Config) | **yes, stricter**: while false the agent tick does nothing at all (`app/autopilot.py` `_agent_tick` returns `apply_disabled` before any pick, triage or record), where the spec has treated rows cancelled with `apply_disabled`. `app/backlinks_apply.py` still refuses on its own (`apply_backlinks`, `POST /interventions/{id}/revert`, 409) |
| `TITLE_AUTOPILOT_ENABLED` | `os.getenv("TITLE_AUTOPILOT_ENABLED", "false").lower() == "true"` | not in the spec (Slice 1 review, 2026-10-23): the title lever stays off until Slice 3 (Part 2 §6) | read only by `app/autopilot.py` `tick`: while false a channel that reaches the title path (`agent_enabled` off, `can_audit` on) returns `title_autopilot_disabled` and never calls `audit_video`. Manual audit routes are unaffected |
| `LEVER_MIN_SOURCE_VIEWS` | `:278` `int(os.getenv("LEVER_MIN_SOURCE_VIEWS") or "100")` | 100, §1.7 floor on the source's post-window views (Part 4 Config, Part 2 §1.7, §8) | no. Read only by `app/lever_measurement.py` `evaluate`: under it the post window is extended once to 14 days, then `insufficient_data` |
| `BACKLINK_EXPERIMENT_WINDOWS` | `:283` `int(os.getenv("BACKLINK_EXPERIMENT_WINDOWS") or "3")` | 3, the P1 time box (Part 4 Config, Part 2 §8) | no. Read only by `app/lever_verdicts.py` `verdicts`: the stop rule needs `windows_judged` ≥ it |
| `BACKLINK_MIN_LIFT` | `:287` `float(os.getenv("BACKLINK_MIN_LIFT") or "1.0")` | 1.0 attributable views per treated video per week (Part 4 Config, D6, Part 2 §8) | no. Read only by `app/lever_verdicts.py`: the verdict band (`directional`, ±it) and the stop rule's bar on `cumulative_lift` |
| `PLAYLIST_HOLDOUT_PCT` | `:303` `float(os.getenv("PLAYLIST_HOLDOUT_PCT") or "0.5")` | 0.5, per playlist, stable hash (Part 5 Config, E4) | no. Read only by `app/playlist_test.py` `assign_arm` |
| `PLAYLIST_TEST_MAX_ADDS` | `:306` `int(os.getenv("PLAYLIST_TEST_MAX_ADDS") or "5")` | 5, per treated playlist (Part 5 Config, E5) | no. Read only by `app/playlist_test.py` (`candidates`, `draw`, `preview`) |
| `PLAYLIST_APPLY_ENABLED` | `:310` `os.getenv("PLAYLIST_APPLY_ENABLED", "false").lower() == "true"` | false, the kill switch for the test's YouTube writes (Part 5 Config) | no. Read only by `app/playlist_test.py` `run_apply`: while false the job logs `"playlist_test_apply skipped: PLAYLIST_APPLY_ENABLED=false"` and does nothing |
| `PLAYLIST_TEST_DAILY_UNITS` | `:313` `int(os.getenv("PLAYLIST_TEST_DAILY_UNITS") or "2000")` | 2000, `JobBudget` for `playlist_test_apply` (Part 5 Config, E5) | no. Read only by `app/playlist_test.py` `run_apply` |
| `PLAYLIST_TEST_MAX_ATTEMPTS` | `:316` `int(os.getenv("PLAYLIST_TEST_MAX_ATTEMPTS") or "3")` | 3, runs a failing add is retried (Part 5 Config) | no. Read only by `app/playlist_test.py` (`_sendable`); only a `failed` error uses up an attempt (§7.3 item 22) |
| `PLAYLIST_EXPERIMENT_WINDOWS` (4), `PLAYLIST_MIN_LIFT` (1.0), `SHORT_LINK_*` | **absent** | Part 5 Config start values (S2.2–S2.6) | **absent** |
| `PLAYBOOK_MIN_VIDEOS_PER_PATTERN` (5), `AGENT_MAX_TURNS` (12), `WRITER_MODEL` (= `AUDIT_MODEL`), `NICHE_REFERENCE_REFRESH_DAYS` (90), `NICHE_REFERENCE_QUOTA_BUDGET` (500) | **absent** | Part 2 §8 start values | **absent** |

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
AUTOPILOT_PICKER_USE_RPC "false"        # dev .env true
AUTOPILOT_PAUSE_COOLDOWN_MINUTES "60"
SHORTS_MAX_CONCURRENT_JOBS "2"  SHORTS_DISPATCH_INTERVAL_SECONDS "5"  SHORTS_YT_DOWNLOAD_ENABLED "false"
SHORTS_MAX_SOURCE_SECONDS "300"  SHORTS_CACHE_DIR "./shorts_cache"  LOG_DIR "logs"  LOG_LEVEL "INFO"
YOUTUBE_PROXY_URL ""  WEBSHARE_PROXY_USERNAME ""  WEBSHARE_PROXY_PASSWORD ""
PLAYLIST_HITL "true"  PLAYLIST_MUTATION_CAP "20"
PLAYLIST_SIMS_USE_RPC "false"           # dev .env true
PLAYLIST_DISCOVERY_USE_RPC "false"      # dev .env true
WARM_POOL_USE_RPC "false"               # (:247) B4; not in the spec: the RPC/in-app switch, as for the picker
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
`decide.QUESTION_SET_VERSION="2026.10-s1-v2"` (`app/decide.py:39`); `agent_tick.CONTEXT_DAYS=28` (`app/agent_tick.py`); `lever_measurement.WEEK=7`, `EXTENDED_DAYS=14`, `RESTATEMENT_HORIZON_DAYS=28` (`app/lever_measurement.py`); `playlist_test.MIN_EMBEDDED_MEMBERS=3` (`app/playlist_test.py`); `reembed.RECIPE="tdt-v1"`, `BATCH_SIZE=50`,
`_BYTES_PER_TOKEN=3`, `JOIN_HIGH_PCTL=50`, `LEAVE_PCTL=10`, `JOIN_LOW_PCTL=5`, `MIN_MEMBER_SIMS=30` (`app/reembed.py:33-51`); `quota.APPLY=(VIDEOS_LIST, VIDEOS_UPDATE)`
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
| `autopilot` | interval `AUTOPILOT_TICK_SECONDS` (`app/main.py:298`) | `app/autopilot.py:562` `tick`: quota-dormancy gate → pick channel (`Job.AUTOPILOT` = `can_audit or can_cut_shorts`) → Shorts action → **`agent_enabled` → the agent path** (`_agent_tick`: `can_run_agent` gate, else `agent_ineligible` → `BACKLINK_APPLY_ENABLED` off → `apply_disabled`, nothing else runs → no heading for the channel's `default_language` in `backlinks.HEADINGS` → `no_heading` → `_resync_if_stale` → daily cap → ledger quota gate → `agent_tick.run`: warm pick → triage → record → treated apply; never `audit_video`) → `can_audit` gate → `TITLE_AUTOPILOT_ENABLED` gate (default off: `title_autopilot_disabled`) → `_resync_if_stale` → daily cap → pick video → ledger quota gate → unsafe-model gate → `audit_video` → validate → ledger quota gate → apply → re-embed | registered. With `autopilot_enabled = f` everywhere it runs only the Shorts action, and no channel has `agent_enabled`. `_can_afford_apply` (`app/autopilot.py:501-514`) logs `quota_insufficient` and skips without pausing. The daily cap (`autopilot_daily_cap`, default 10) counts applied audits, `midas` interventions with `applied_at` today, and today's `midas` treated rows that never reached YouTube (`applied_at` NULL: DRY_RUN, a refused render, a YouTube error), so a systematic failure is bounded too (`_applies_today`, `app/autopilot.py:81`), on both paths; holdout and declined rows don't count. Agent-path apply errors get the audit path's reaction (`_react_to_apply_error`: quotaExceeded → fleet dormancy, token expiry → pause, `failed` → failure count; `apply_disabled`, `quota_insufficient` → none); anything unclassified is `agent_failed` and a failure count |
| `shorts_dispatch` | interval `SHORTS_DISPATCH_INTERVAL_SECONDS` (5 s) (`:306`) | `app/shorts/dispatcher.py:dispatch_tick` | registered |
| `playlist_reconcile` | cron 02:00 server-local (`:314`) | `main._daily_reconcile` (`:131`) → `sync_playlists` (shared `JobBudget("playlist_sync", PLAYLIST_SYNC_QUOTA_BUDGET, reserve=YT_QUOTA_APPLY_RESERVE)`) + `reconcile_channel` | registered; channels = `PLAYLIST_RECONCILE_CHANNELS` allowlist (`app/eligibility.py:186-195`). **Add/remove frozen** by `PLAYLIST_RECONCILE_WRITES_ENABLED`; inventory sync and the budgeted membership walk still run. **Human-edit ledger (B3b):** for a playlist walked before (`membership_walked_at` not NULL at plan time), each page's memberships the walk has no `playlist_assignments` row for go to `human_edits.record_playlist_additions` before the walk seeds its `sync` rows (`app/playlists_sync.py:297-328`); a playlist's first walk is the baseline and records none. A ledger error is logged as `"sync_playlists <id>: human-edit ledger failed; walk continues: <err>"` and never fails the walk (`_record_human_memberships`, `app/playlists_sync.py:361-370`). The manual `POST /channels/{id}/playlists/bootstrap` runs the same walk (`app/playlists_router.py:192`) |
| `playlist_discovery` | cron Sun 03:00 local (`:327`) | `main._weekly_discovery` → `app/playlist_discovery.py:152` `discover_playlists` | **frozen** (`PLAYLIST_DISCOVERY_ENABLED`). When on: every channel; **creates playlists** (≤2/run), skipped under `DRY_RUN` |
| `reflection` | cron Mon 04:00 local (`:340`) | `app/reflection.py:702` `reflect` | **frozen** (`REFLECTION_ENABLED`). When on: every channel |
| `playlist_tuning` | cron Mon 03:30 local (`:353`) | `app/playlists.py:463` `tune_thresholds` | **frozen** (`PLAYLIST_TUNING_ENABLED`). When on: writes `settings.PLAYLIST_JOIN_HIGH` process-globally (`app/playlists.py:518`) |
| `video_sync` | cron 04:00 UTC (`:365`) | `main._daily_video_sync` (`:243`) → `app/sync.py:546` `routine_sync` per channel | registered, every channel. Read-only: `"fresh"` if synced within 6 h, else a full pass if the last full sync is >3 days old, else incremental + `refresh_stats`. An expired or revoked token is an expected skip, logged `"video_sync <id>: OAuth token expired; skipping until re-consent"`; since fleet readiness the run then returns `{"partial_errors": {<id>: "token_expired: re-consent needed"}}`, so it records `degraded` rather than `success`; any other error, including a YouTube 401 that isn't a token failure, fails the channel. The skip works because `sync_channel`, `refresh_stats` and `refresh_applied_stats` are wrapped by `_token_failure_as_401` (`app/sync.py:54`), which turns a `TokenExpiredError` from anywhere in the call (at `youtube_for_channel`, or mid-call from the `yt_*` helpers' `invalid_grant` check, `app/youtube_client.py:63-66`) into `TokenExpired` (`app/sync.py:41`): an `HTTPException(401, "token_expired")` that is also a `TokenExpiredError`. Before B8 these raised a plain `HTTPException(401)`, which failed the run (2026-10-06, Hindi, §8). The autopilot resync catches the same type (`app/autopilot.py:398`). **Human-edit ledger (B3a):** a full pass also reads the stored descriptions and, before the videos upsert, hands every re-read (id, stored, fetched) description to `human_edits.record_description_edits` (`app/sync.py:262-265,288-297`). A ledger error is logged as `"sync <id>: human-edit ledger failed; sync continues: <err>"` and never fails the sync; a per-video error is logged `"human_edits <channel>: ledger failed for <video>: <err>"` and the other videos still run. Incremental passes re-fetch no known video, so they record nothing |
| `metrics_poll` | cron 05:00 UTC (`:378`) | `app/metrics_poll.py:poll_metrics` | registered; `analytics_authorized` channels; videos only if in a measurement window (`METRICS_POLL_MEASURED_ONLY`) |
| `reporting_poll` | cron 06:00 UTC (`:399`) | `app/reporting_poll.py:poll_reporting` | registered; `analytics_authorized AND (measurement_enabled OR reach_warmup)` (`app/eligibility.py:154-168`). Ingests only `channel_reach_basic_a1` |
| `traffic_poll` | cron 06:30 UTC (`:418`) | `app/traffic_poll.py:173` `poll_traffic` | registered; `analytics_authorized` channels in `TRAFFIC_INGEST_CHANNELS` (`app/eligibility.py:170-178`). Two feeds per channel (`_FEEDS`, `app/traffic_poll.py:74`): **video** ensures the `channel_traffic_source_a3` job (`midas-traffic-source`, Marathi `3647f5d8…`) → `video_traffic_source_daily`; **playlist** ensures the `playlist_traffic_source_a2` job (`midas-playlist-traffic-source`, Marathi `381cf084…`) → `playlist_traffic_daily`. Both Marathi jobs are found, not created. Each feed ingests each data-day's newest not-yet-ingested report, a restatement replacing the day (`app/traffic_poll.py:89` `_newest_per_day`, `app/reporting_poll.py:104` `replace_data_day`), and ledgers it with its own `report_type`. Logs `"traffic_poll <id> data-day <d>: <n> rows written to <table> (report <r>)"` (`app/traffic_poll.py:118`). Feeds are isolated (`_poll_channel`, `app/traffic_poll.py:155`): a feed crash is recorded as `"<feed>: <Type>: <msg>"` and fails the channel, but the other feed still runs; per-report errors are judged per feed (categories `video reports`, `playlist reports`). Independent of `reporting_poll` |
| `playlist_health_score` | cron 07:00 UTC (`:432`) | `main._daily_playlist_health_score` (`:220`) → `app/playlist_health.py:score_channel` | registered; `playlist_health_enabled` channels (Punjabi only, §1) |
| `measurement_eval` | cron 08:00 UTC (`:451`) | `main._daily_measurement_eval` → `app/measurement.py:evaluate_with_failures` | registered |
| `lever_measurement` | cron Mon 09:00 UTC (`app/main.py` `_register_jobs`) | `app/lever_verdicts.py` `run_weekly` | registered (S1.6b). Every channel (`Job.EVERY`): `lever_measurement.measure_channel` (S1.6a), then `write_verdicts` for the current week. `traffic_poll`'s failure model: a channel that raises fails the run once every channel has run (`JobRunFailed("lever_measurement", …)`); per-row errors go through `job_status.item_error_verdict` under the category `interventions` (all errored → the channel fails as `"ItemsFailed: interventions: all <n> failed"` and gets no verdicts that run, some → `degraded`). DB only, nothing reaches YouTube |
| `channel_health` | cron 10:00 UTC (`app/main.py` `_register_jobs`) | `app/channel_health.py` `run_daily` | registered (fleet readiness, not in the spec). Read-only: `check()` over every channel, and `JobRunFailed("channel_health", {<id>: "<problems>"})` when any channel has one: `last_synced_at` older than `SYNC_STALE_HOURS` (30) or NULL, a reach frontier (`Job.REACH` channels) more than `REACH_STALE_DAYS` (7) behind or none, a `channel_traffic_source_a3` frontier (`Job.TRAFFIC` channels) more than `TRAFFIC_STALE_DAYS` (4) behind or none, or a non-NULL `autopilot_paused_reason`. A channel with no row in `videos` is listed with `no_videos: true` and no problems (Kannada and Telugu, no uploads on 2026-10-26). Exists because the 2026-10-16 sign-in outage left every job `success` for a week |
| `playlist_test_apply` | cron 11:00 UTC (`app/main.py` `_register_jobs`) | `app/playlist_test.py` `run_apply` | registered (S2.2), always; does nothing while `PLAYLIST_APPLY_ENABLED` is false (default). Otherwise, per channel with a treated `playlist_arms` row `planned` or `applying` (`apply_channel`), a playlist at a time in arm id order: its approved, unsent adds with attempts left go together only if n × 50u fits both `JobBudget("playlist_test_apply", PLAYLIST_TEST_DAILY_UNITS)` and `quota.can_afford(…, reserve=YT_QUOTA_COLLECTION_RESERVE)`, else the job stops for the day. Each add is `yt_playlist_items_insert` at position = the number of the arm's adds ahead of it in rank (`proposal_ids` order) already in the playlist; a 400 naming the position or sort order is retried once appended, and from then on (this run and later ones, read off `apply_error.reason = 'position_refused'`) that playlist's adds go appended. Success → the proposal's `applied_at`, `playlist_item_id`, and a `playlist_assignments` `added` row with `decision_source = 'experiment'` (`playlists._record_assignment`). Errors classified as `backlinks_apply._classified`: `failed` uses up an attempt (at most `PLAYLIST_TEST_MAX_ATTEMPTS`); `youtube_quota_exceeded` stops the job and makes the channel `degraded` (`"youtube_quota_exceeded: stopped for the day"`), never counted as an errored add; `token_expired` stops the channel and fails it. Arm status settles after each arm (§2 `playlist_arms`). `DRY_RUN` logs `"[DRY_RUN] playlist_test_apply <id>: would add […] to the top of <playlist>"` and writes nothing. `traffic_poll`'s failure model: a channel that raises fails the run once every channel has run (`JobRunFailed("playlist_test_apply", …)`); per-add errors through `job_status.item_error_verdict` under `playlist adds` |
| `nightly_db_backup` | cron `BACKUP_HOUR` local (`:466`) | `app/backup.py:run_nightly_backup` | registered; no-op if `BACKUP_ENABLED=false` |
| `pot_provider_refresh` | interval 2 h (`:482`) | `main._refresh_pot_provider` | only if env `BGUTIL_POT_HTTP_BASE_URL` is set; absent on the office machine (`docs/PHASE_A_FINDINGS.md` A0 step 12) |

Startup side effects: `provision.ensure_database_populated()` (restore from NAS if the DB is empty,
`app/main.py:499`), `shorts.runner.reap_stuck_jobs()` (`:505-509`), `tracing.configure()`.

Spec'd jobs not registered: `niche_reference_refresh` (Part 2 §3.6) and playbook rebuild (Part 2 §1.1, §5).

---

## 5. Surface area

**Routes** (`app/main.py:528-541` mounts every router):

- **Pages/health:** `GET /` → `static/index.html`; `GET /channel` → `static/channel.html`; `GET /health` → `{"ok": True, "dry_run": …}`; `GET /health/jobs` → `{"jobs": {<job_id>: {status, last_run_at, error, failed_channels, partial_errors}}}`; `GET /health/channels` (`app/channel_health.py`) → `{"checked_at", "with_problems", "channels": [{id, name, last_synced_at, reach_days_behind, traffic_days_behind, autopilot_paused_reason, no_videos, problems}]}`, channels with problems first, read from the DB; `GET /autoshorts` (`app/shorts/autoshorts.py:85`); `/static/*`.
- **Auth/channels** (`app/auth.py`, prefix `/auth`): `GET /auth/login`, `GET /auth/callback` (stores tokens, sets `analytics_authorized` from granted scopes, clears the `token_expired` pause), `GET /auth/channels`, `PATCH /auth/channels/{id}` (enabling `measurement_enabled` returns 409 unless `reach.certify` passes, `app/auth.py:166-174`).
- **Sync** (`app/sync.py`): `POST /channels/{id}/sync?full=`, `POST /channels/{id}/refresh-stats`, `POST /channels/{id}/refresh-applied-stats`, `GET /channels/{id}/videos`, `GET /videos/{id}`.
- **Audits** (`app/audits.py`): `GET|POST /channels/{id}/audit-config`, `POST /channels/{id}/audit-config/elaborate`, `POST /videos/{id}/audit`, `GET /videos/{id}/audits`, `POST /audits/{id}/apply`, `POST /channels/{id}/audits/apply-pending`, `POST /channels/{id}/audits/reaudit-quarantined`, `POST /channels/{id}/audits/run-bulk`, `POST /audits/{id}/revert` (409 `"quota_insufficient: revert needs <n> units, <m> remaining today"` when `quota.can_afford(quota.cost(Op.VIDEOS_UPDATE))` is false, `app/audits.py:830-837`), `GET /quota-cost-preview`.
- **Measurement** (`app/measurement.py`): `GET /audits/{id}/measurement`, `GET /channels/{id}/outcomes`, `POST /measurement/evaluate`.
- **Reflection** (`app/reflection.py`): `GET /channels/{id}/reflection/history`, `POST /channels/{id}/prompt-versions/{vid}/promote`, `POST /channels/{id}/reflection/trigger`, `GET /channels/{id}/reflection/shadow-comparison`. Promote and trigger return 409 `"Reflection is frozen: REFLECTION_ENABLED=false"` while frozen (`_require_reflection_enabled`, `app/reflection.py:792`).
- **Playlists** (`app/playlists_router.py`): `POST /channels/{id}/playlists/evaluate`, `GET /channels/{id}/playlists/health`, `POST /channels/{id}/playlists/bootstrap` (sync + embed all), `GET /channels/{id}/playlists/status`, `POST /channels/{id}/playlists/reconcile` (409 `"Playlist reconcile writes are frozen: PLAYLIST_RECONCILE_WRITES_ENABLED=false"`, `:263-267`), `GET /channels/{id}/playlists/proposals`, `POST /channels/{id}/playlists/proposals/decide` (executes adds/removes on YouTube; not frozen; since S2.2 a proposal with `arm_id` set is only marked `approved`/`rejected` with `decided_at` and sends nothing, and the response gains `queued` (their count) only when there were any).
- **Autopilot** (`app/autopilot.py`): `POST /channels/{id}/autopilot/resume`, `GET /channels/{id}/autopilot/log`.
- **Interventions** (`app/backlinks_apply.py`): `POST /interventions/{id}/revert`, for an applied (`applied_at` set, not `cancelled`) `midas` `backlinks` intervention only (else 400; 404 unknown). Fetches the live snippet, `backlinks.strip`s it and sends it back `part=snippet` with only `description` changed (no update if no block is left); 409 `"apply_disabled"` while `BACKLINK_APPLY_ENABLED` is false, 409 `"quota_insufficient: revert needs <n> units, <m> remaining today"` when `quota.can_afford(quota.cost_of(*quota.APPLY))` (51u) is false; under `DRY_RUN` it returns `{"status": "dry_run", "description": <stored, stripped>}` and writes nothing. Sets `status = 'cancelled'`, `payload.revert = {reverted_at, live_before, description}`, and `videos.description`.
- **Interventions and verdicts** (`app/lever_verdicts.py`, S1.6b): `GET /channels/{id}/interventions?lever=&status=&limit=&offset=` → `{"interventions": [...], "limit", "offset", "next_offset"}`, newest first (`created_at` desc, then `id` desc), one page of `limit` rows (default 100, at most 1000 = `rows.PAGE_SIZE`; 422 above), `next_offset` set whenever a page comes back full (so an exactly full last page points at one more, empty page); an unknown `lever` or `status` (not in `status_vocab`) is 400. `GET /channels/{id}/lever-verdicts` → `{"verdicts": [...], "backlinks_stopped": bool}`, every `lever_verdicts` row of the channel (`all_rows`), newest week first.
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
| `audits.py` | `DEFAULT_PROMPT`, `_build_user_block`, strategy stamp, `audit_video`, apply, revert, bulk ops |
| `audit_suggestion.py` | LLM output contract: decode, 15-hashtag cap, `rejection()`, `house_format_spec()` |
| `apply_outcome.py` | typed `ApplyError`/`ApplyOutcome`; S1.3 adds `QUOTA_INSUFFICIENT` (`quota_insufficient`) and `APPLY_DISABLED` (`apply_disabled`), both 409, the backlinks write's refusals before anything is sent |
| `backlinks_apply.py` | Slice 1 S1.3: `apply_backlinks(intervention)` for a `planned`, `treated`, `midas` `backlinks` row with `payload.targets` (else `ValueError`). Refuses `apply_disabled` while `BACKLINK_APPLY_ENABLED` is false; under `DRY_RUN` renders onto the stored description and returns `{"status": "dry_run", "description"}` with no YouTube call and no write; then the ledger gate (`quota_insufficient` unless `quota.APPLY`, 51u, is affordable). Fetches the live snippet (`yt_videos_list_full`, 1u), renders the block onto the live description (`backlinks.render`, the channel's `default_language`), and sends `videos.update` `part=snippet` with the fetched snippet, only `description` replaced (`yt_videos_update`, 50u). A live description that differs from the stored one goes to `human_edits.record_description_edits` first, so a team edit since the last sync is still recorded. Success: the row becomes `measuring` with `applied_at`, `before_state = {description: <live>}`, `payload.description` = the rendered text; `videos.description` = the rendered text. YouTube failures are typed (`token_expired`, `youtube_quota_exceeded`, `failed`; a refused render or a video gone is `failed`) and change no row: recording the failure is the caller's (`app/agent_tick.py`, S1.4b, records it `cancelled`). Also the revert route (§5 Routes). Called by `agent_tick.run` for a treated row |
| `youtube_metadata.py` | `videos.update` payload; `_NON_ISO_639_1 = {"bgc": "hi", "bho": "hi", "raj": "hi"}` (`:58-64`; `bho`/`raj` unused for now, B7) |
| `youtube_client.py` | Data API wrappers + quota charging; `yt_playlist_items_insert` takes an optional `position` (S2.2), sent as `snippet.position` only when given; `channel_credentials` (#56): a channel's stored creds with `expiry` from `channels.token_expiry` (NULL = expired), refreshed and saved when expired, shared with `analytics_client` |
| `quota.py` | unit-cost table, daily ledger, `JobBudget`, `/quota` |
| `analytics_client.py` | on-demand Analytics (views/retention, playlist session metrics); `analytics_creds_for_channel` = the `analytics_authorized` gate + `youtube_client.channel_credentials` (also used by the Reporting API) |
| `reporting_client.py` / `reporting_poll.py` | Reporting API jobs (`ensure_job` per report type; `ensure_reach_job`, `ensure_traffic_job`, `ensure_playlist_traffic_job`), CSV parsing (reach; video and playlist traffic with aggregation, `_aggregate_traffic_csv`, and the `TRAFFIC_SOURCE_TYPES` code→name table), reach ingestion → `video_reach_daily`, `video_metrics` backfill; the shared latest-wins day replace (`replace_data_day`, `superseded_reports`, `record_ingested`); `download_report_csv` retries a dropped connection (`_DOWNLOAD_TRANSIENT`, `DOWNLOAD_ATTEMPTS` = 3, pauses 1 s then 2 s; #57) and refreshes the token once on a 401 |
| `human_edits.py` | B3a human-edit ledger, description links: `video_links` (11-character ids from `watch?v=`, `youtu.be/`, `shorts/`, `embed/`, `live/`, `v/` URLs), `made_by_midas` (the description equals an applied audit's `suggested_description` or a reverted one's `description_before`, whitespace collapsed; or, S1.3 `_midas_block`, its links to our videos, other than itself, are exactly the targets of a `treated` `midas` `backlinks` intervention with `applied_at` set, not `cancelled`), `record_description_edits` (diff, keep targets in `videos` on any channel, write `human` backlinks rows with a `ledger_key`, stamp removals on the earlier row). Called only from `sync_channel` on a full sync. B3b, playlist memberships: `added_by_midas` (a `playlist_assignments` `added` row whose `decision_source` isn't `sync`, i.e. `embedding`, `llm_confirmed` or `discovery`, or an `approved` `add` `playlist_proposals` row; never `playlists.origin`), `record_playlist_additions` (write `human` playlist rows with a `ledger_key`). Called only from the membership walk (`app/playlists_sync.py`). Both write through `_record_human` |
| `traffic_poll.py` | B1 daily traffic-source ingestion → `video_traffic_source_daily`, `playlist_traffic_daily`; the video feed's retention rule (`keeps_detail`, `collapse_unread_detail`, reading every id in `videos` once per run) |
| `interventions.py` | B2: `assign_arm` (sha256 of `video_id`, lever vs `HOLDOUT_PCT`), `active_for` (the video's open `midas` intervention), `record` (refuses a second open `midas` one with `ActiveInterventionExists`, and a `human` one with an arm other than `n/a`; a concurrent second insert is refused by the partial unique index as a PostgREST unique-violation error, not `ActiveInterventionExists`). With `ledger_key` it upserts `on_conflict="ledger_key", ignore_duplicates=True` and returns None for a key already stored. Callers: `app/human_edits.py` (`human` rows), `app/agent_tick.py` (`midas` rows, S1.4b) |
| `reach.py` | data-day windows, coverage, frontier, staleness, `certify` (`certify_covered` over a coverage set already read; `window_length` for SQL callers). `coverage(channel_id, report_type=…)` defaults to reach; S1.1's sibling window passes `channel_traffic_source_a3` |
| `decide.py` | B5: `decide(question_set, subject, context, intervention_id=None) -> Decision` (`question_set`, `answer`, `probs`). Answers with the question set's rules (probability 1.0), asks the `DECIDE_BACKEND` backend in shadow (`llm` via `openrouter.chat_json`, validated against the allowed answers and probabilities in [0, 1]; `jev` raises `NotConfigured`), writes one `decision_log` row with `used = 'rules'` and `QUESTION_SET_VERSION`, and returns the rules answer. A backend failure is logged `"decide <set> <subject>: <backend> backend failed; rules answer stands: …"` and logged as a row with NULL `jev_answer`; a failed log write is logged and doesn't change the answer. Two question sets: `TRIAGE` (answers `no_change|backlinks|playlist|short_link|title`, Part 2 §2.2; the rules choose only `backlinks` or `no_change`) and, since S1.5, `NEXT_WATCH` (answers `yes|no`; the rules answer `yes` when the context's `similarity` ≥ its `join_low`, else `no`, including when either is missing). Every answer needs a probability; the rules answer is 1.0 on itself, 0.0 elsewhere. S1.4b: the rules also answer `no_change` when the context's `backlinks_stopped` is true; the returned `Decision` carries the `decision_log` row's id as `log_id` (None if the write failed; not part of equality), and `link(log_id, intervention_id)` sets that row's `intervention_id` (failures logged, never raised). Caller: `app/agent_tick.py` `run` (both sets) |
| `reembed.py` | B6, one-off: `recipe_text` (title, description, tags as `f"{title}\n\n{description}\n\n{', '.join(tags)}"`, title and description stripped; no transcript, no branch), `MODEL_VERSION`, `estimate_channel` (video count, videos still to embed, tokens ≈ UTF-8 bytes / 3, cost at a price passed in; reads the DB, calls no API), `reembed_channel` (every video of the channel in `videos` without a `MODEL_VERSION` vector, in batches of 50 upserted on `video_id,chunk_index,model_version`; a failed batch, or one answered with the wrong number of vectors, is retried one video at a time; a video that still fails is logged and counted, and a rerun retries it), `member_similarities` (`MemberSims`), `calibrate_channel` (thresholds from current playlist members' similarity, stored on `channels.playlist_thresholds`). Run only by `scripts/reembed.py` |
| `backlinks.py` | Slice 1 S1.2, pure (no I/O): the canonical backlink block. `render(description, targets, language)` puts `HEADINGS[language]` then one `<title> https://youtu.be/<id>` line per target (dicts with `video_id`, `title`) directly after the description's first line (D2), then a blank line if text follows; any block already there is stripped first, so a re-render replaces it. Raises `RenderRefused` (a `ValueError`) for a language not in `HEADINGS` (no English fallback), no targets, more than `BACKLINK_MAX`, a duplicate or malformed target id, an empty title, a heading with `#`, or a result over `DESCRIPTION_MAX` characters. `#` is dropped from titles and whitespace collapsed, so the block adds no hashtag. `find` → `Block(language, video_ids, start, end)`: an exact heading line followed by at least one line matching `<title> https://youtu.be/<11-char id>` and nothing else; `strip` removes every such block and the blank line after it. `HEADINGS` (all "watch more songs"): `"mr": "आणखी गाणी पहा:"` (owner, 2026-10-23: D3 left it to the SEO team, who had no preference) and, written by Claude for a native reader to skim before each channel goes live (owner, 2026-10-25), `"hi": "और गाने देखें:"`, `"bgc": "और गाणे देखो:"`, `"pa": "ਹੋਰ ਗੀਤ ਵੇਖੋ:"`, `"gu": "વધુ ગીતો જુઓ:"`, `"en": "Watch more songs:"`, `"ta": "மேலும் பாடல்களைப் பாருங்கள்:"`, `"ml": "കൂടുതൽ പാട്ടുകൾ കാണൂ:"`, `"kn": "ಇನ್ನಷ್ಟು ಹಾಡುಗಳನ್ನು ನೋಡಿ:"`, `"te": "మరిన్ని పాటలు చూడండి:"`; one per channel `default_language` (Bhojpuri, Rajasthani, 3D Animated share `hi`), all distinct (`find` reads the language off the heading). It must stay fixed: `find`/`strip` match it exactly. **S1.1, reads the DB:** `siblings(channel_id)` → `[{channel_id, views}]`, most views first: the channels whose videos sent this channel's videos ≥ `SIBLING_MIN_VIEWS` type-7 views over its latest `SIBLING_WINDOW_DAYS` (28) ingested `channel_traffic_source_a3` data-days (`reach.coverage(report_type=)`), read from its own `video_traffic_source_daily`, mapped to channels through `videos`, excluding itself and any channel not in `TRAFFIC_INGEST_CHANNELS`. `candidates(video, *, sibling_ids=None)` → `Candidates(rows, skipped_unembedded, reason, join_low)` (`join_low`, S1.5: the threshold applied, None when the thresholds were missing or another model version's): targets on the source's channel or a sibling, warm on their own channel (`warm.warm_impressions`), public (or NULL), not a Short (`is_short` true), not the source, not in `human_edits.video_links(source description)`, with a `reembed.MODEL_VERSION` vector, and cosine ≥ the source channel's `playlist_thresholds.join_low`; ranked by similarity, then impressions, then id; at most `2 × BACKLINK_MAX` rows `{video_id, channel_id, title, similarity, impressions}`. Reasons: `no_thresholds`, `thresholds_other_model_version`, `source_not_embedded`. `candidates` and `render` are called by `app/agent_tick.py` (S1.4b; `siblings` through `candidates`) |
| `warm.py` | B4 warm filter: `ranked_pool` (`{id, impressions}`, most impressions first, id tie-break; `warm_pool()` RPC paged through `all_rows` when `WARM_POOL_USE_RPC`, else in-app, and in-app if the RPC errors), `explore_order` (each pick is the best left or, with probability `WARM_EXPLORE_PCT`, a random one from the rest, flagged `explore`; injectable `random.Random`), `warm_pool` (both); `_holds` (S1.4a: a `midas` row holds its video if active, created within `TRIAGE_COOLDOWN_DAYS` whatever its status, or a `backlinks` row of arm `treated`/`holdout` at any age; the in-app pool reads every `midas` row of its warm videos through `rows_for_ids`); `warm_impressions` (the warmth measure alone, `{video_id: impressions}` ≥ `WARM_MIN_IMPRESSIONS`, `{}` if reach isn't certified; the in-app pool is built on it). `app/agent_tick.py` picks from `warm_pool` (S1.4b), and `app/backlinks.py` `candidates` reads `warm_impressions` (S1.1) |
| `metrics_poll.py` | daily Analytics poll |
| `measurement.py` / `verdicts.py` | title verdicts, `measurement_result` shape, rollups |
| `performance.py` | per-channel performance table/CSV |
| `dashboard.py` | `/dashboard`; `_aggregate_legacy` kept as fallback/oracle for the RPC |
| `reflection.py` | weekly per-channel prompt rewrite (shadow/live/auto) + auto-revert; `derive_niche_queries`, `_sample_competitors` (frozen) |
| `transcripts.py` | transcript fetch + `video_transcripts` cache; `lang_display_name` (`_LANG_NAMES`, `:25-36`, incl. `bgc` Haryanvi, `bho` Bhojpuri, `raj` Rajasthani); Data API captions fallback |
| `embeddings.py` / `openrouter.py` | embeddings and `chat_json`/`chat_text` via OpenRouter |
| `playlists.py` | similarity engine: `join_pass` (call commented out, `app/autopilot.py:438-439`), `reconcile_channel`, `tune_thresholds`, `_llm_judge` |
| `playlists_sync.py` | playlist inventory sync, budgeted membership walk, role heuristic; hands memberships new since a playlist's previous walk to the human-edit ledger (`_record_human_memberships`) |
| `playlist_discovery.py` | weekly orphan clustering → creates playlists (frozen) |
| `playlist_health.py` | playlist health scorer (recommend-only) |
| `playlists_router.py` | playlist HTTP endpoints |
| `autopilot.py` | the tick loop; the agent path's gates (`_agent_tick`, S1.4b) |
| `agent_tick.py` | Slice 1 S1.4b, the agent tick's video work. `run(channel)`: the first of `warm.warm_pool` (with the explore share) → `_assess` (S1.1 `backlinks.candidates` and the triage context: `has_related_block` = the description links to one of our videos other than itself, `human_edits.video_links` ∩ `human_edits.our_videos`, D5; `backlink_candidates` = the candidate count; `backlinks_stopped`; `traffic_mix_28d` = views by source-type name over the channel's latest 28 ingested `channel_traffic_source_a3` data-days; `impressions`, `ctr` = `reach.weighted_ctr` over the latest `WARM_WINDOW_DAYS` reach data-days; `recent_interventions` = the video's rows of any origin created in the last 28 days) → `decide(TRIAGE, video_id, context)` → `interventions.record` (lever `backlinks`, origin `midas`): `no_change` → `declined`, arm `n/a`, `payload.rationale`; `backlinks` → `assign_arm`: holdout → `holdout` with `payload.targets` (top `BACKLINK_MAX` candidates), no YouTube call; treated → `planned` with `payload.targets`, then `backlinks_apply.apply_backlinks` (success → `measuring`; an ApplyError or other exception → `cancelled` with `payload.error = {reason, detail}`, re-raised for the tick; DRY_RUN → `cancelled` with reason `dry_run` and the rendered `payload.description`). `triage_json` = `{decision_log_id, question_set_version, answer, probs, context, explore, candidates_reason, skipped_unembedded}`, and `decide.link` points the log row back. S1.5: a video triaged to `backlinks` (either arm), before it is recorded, gets `_next_watch`: `decide(NEXT_WATCH, "<source>-><target>", context)` for every row `candidates` returned (up to `2 × BACKLINK_MAX`, not only the targets kept), context `{source_video_id, source_title, target_video_id, target_channel_id, target_title, similarity, join_low}`; the results go on `triage_json.next_watch` as `[{target_video_id, similarity, decision_log_id, answer, probs}]` (the rules answer; the backend's is on the log row), and `decide.link` points each pair's row at the intervention too. A declined row has no `next_watch` key. A pick that already has an active Midas intervention returns `active_intervention` (`ActiveInterventionExists`). `backlinks_stopped(channel_id)` (S1.6b): `lever_verdicts.stopped(channel_id)`, true once any `treated_vs_holdout` `lever_verdicts` row of the channel for `backlinks` has `stop_rule_triggered`; it stays true, since past weeks' rows aren't rewritten and a same-week rerun keeps a set flag. `preview(channel_id, n)`: the same up to the render for the pool's first `n`, asking `TRIAGE.rules` directly; writes nothing, calls no backend and no YouTube |
| `lever_measurement.py` | Slice 1 S1.6a, pair measurement per `backlinks` intervention (Part 4 S1.6, Part 2 §1.2, §1.3, §1.7). `measure_channel(channel_id, *, today=None)` → counts `{attempted, errored, judged, insufficient_data, awaiting_window, extended, changed}` (`attempted`/`errored` for `job_status.item_error_verdict`; a row that raises is logged and left as it was). Reads the channel's (the source's) `backlinks` rows through `all_rows`: treated (`midas`, arm `treated`, `measuring`, `applied_at` set), holdout (`midas`, `holdout`) and human (`human`, `applied`, only when the channel is in `TRAFFIC_INGEST_CHANNELS`), plus `judged`/`insufficient_data` ones whose post window ended within `RESTATEMENT_HORIZON_DAYS` (28), which are recomputed so a restated traffic day is re-read. `as_of`: d0 = the Pacific (YouTube data-day) date of `applied_at` (treated), `created_at` (holdout) or `detected_at` (human). `windows(d0, post_days)`: pre d0−7 … d0−1, post d0+1 … d0+7 (or +14). Targets: a Midas row's `payload.targets[].video_id` (channel from the payload), a human row's `payload.target_video_id` (channel from `videos`, `rows_for_ids`). Complete when every target's channel and the source's own have a `channel_traffic_source_a3` ledger frontier (`reach.coverage`, `reach.frontier`) ≥ the post window's last day; else `measurement_status = awaiting_window` (or `extended`). `pair_views` = Σ `views` in `video_traffic_source_daily` with `video_id` in the targets, `source_type = 7`, `source_detail` = the source (`rows_for_ids`); `source_views` = the source's own views, every type (`all_rows`). Source under `LEVER_MIN_SOURCE_VIEWS` at 7 days → wait for 14; still under → `insufficient_data`; else `judged`. `delta` = post − pre, in views per week (a 14-day post is scaled by 7/14); `missing_days` lists the windows' data-days some channel the row reads has no ingested report for (counted as zero, flagged). Writes only when something changed; `judged_at` is when the row got its current outcome (kept across recomputes that don't change it), `computed_at` is the last change; a decided row that can't be decided again yet keeps its verdict. Called by `app/lever_verdicts.py` `run_weekly` (the `lever_measurement` job) |
| `lever_verdicts.py` | Slice 1 S1.6b, the weekly verdict (Part 4 S1.6, Part 2 §1.3–§1.5, P1, D6, D8). `verdicts(rows, week, windows_before)` (the arithmetic, §2 `lever_verdicts`), `write_verdicts(channel_id, *, today=None)` (reads the channel's `judged` `backlinks` rows and its verdict weeks through `all_rows`; writes, oldest first, every earlier week with judged rows and no verdict row yet, then the current week, upserting on `channel_id,lever,arm_scope,week_start`; deletes the current week's row of a scope that has none now, unless it triggered the stop rule), `stopped(channel_id)` (any triggered `treated_vs_holdout` row; a bounded `limit(1)` read), `run_weekly(*, today=None)` (the job, §4), and the two read endpoints (§5 Routes). `insufficient_data` rows never enter a mean (§1.7) |
| `playlist_test.py` | Slice 2 S2.1, the playlist test's draw (Part 5 S2.1, Part 2 §4, P3, E1, E4–E6); #88/#89 extend it. `survey(channel_id)` → `Survey(eligible, skipped)`: the channel's `playlists` rows (`all_rows`), eligible when `role` isn't `series` and at least `MIN_EMBEDDED_MEMBERS` (3) current members have a `reembed.MODEL_VERSION` vector; current members are `reembed._members` (the latest `playlist_assignments` action per pair is `added`, as `playlists._current_members`, read for the whole channel through `rows_for_ids`); skipped rows carry `reason` `series` or `too_few_embedded_members`. `eligible(channel_id)` → `[{playlist_id, title, eligible_members}]`. `assign_arm(playlist_id)`: sha256 of the playlist id, first 8 bytes as a point in [0, 1), `holdout` below `PLAYLIST_HOLDOUT_PCT`, else `treated` (`interventions.assign_arm` untouched). `candidates(channel_id, playlist_id)` → `Candidates(rows, skipped_unembedded, reason, join_high)`: videos of the channel warm by `warm.warm_impressions`, public (or NULL), `is_short` not true, `is_episode` not true, not a current member, with a `MODEL_VERSION` vector whose raw cosine to the members' centroid (the sum of their vectors, which cosine reads as the mean) is ≥ the channel's `playlist_thresholds.join_high`; ranked by impressions, then similarity, then id; at most `PLAYLIST_TEST_MAX_ADDS` rows `{video_id, title, similarity, impressions}`. Refused with `reason` `no_thresholds` or `thresholds_other_model_version` (`backlinks._thresholds` and its constants); a playlist `survey` wouldn't make eligible gets no rows. `draw(channel_id)`: raises `AlreadyDrawn` if the channel has any `playlist_arms` row; writes nothing and returns `refused` when the thresholds are refused; else per eligible playlist inserts its arm (treated with candidates `planned`, treated without `no_dose`, holdout `holdout`), then a treated arm's pending `experiment` `add` proposals with `arm_id`, then their ids onto `proposal_ids`; returns `{channel_id, refused, playlists, arms: {treated, holdout, no_dose}, proposals, skipped}`. `preview(channel_id)`: the same plan, writing nothing, plus `already_drawn` and `plan` (per eligible playlist its arm, status, `eligible_members` and the videos it would get; none for a holdout arm). Run only by `scripts/playlist_test.py`; nothing in the draw reaches YouTube. **S2.2:** `run_apply()` (the `playlist_test_apply` job, §4) and `apply_channel(channel_id, budget)` → `{attempted, errored, sent, stopped}` (`stopped`: `budget`, `youtube_quota_exceeded` or None), the test's only YouTube write; `test_dates(channel_id)` → `(test_start, test_end)`, the Pacific dates (`lever_measurement._day`) of the earliest `first_applied_at` and latest `last_applied_at` over the channel's treated arms, None while any treated arm is `planned` or `applying`, when none has a `first_applied_at`, or when the channel has none (read by #89). `test_dates.__test__ = False`, since pytest collects `app/playlist_test.py` by its name |
| `tracing.py` | OpenTelemetry → Phoenix spans (off by default) |
| `backup.py` / `provision.py` / `services/nas_service.py` | NAS snapshot, restore-on-empty, SMB client |
| `keyframes.py` | dead: not imported anywhere in `app/` or `scripts/` |
| `shorts/*` | Shorts cutter (NAS source), dispatcher, worker, upload. `shorts/cutter/download.py` gated off (`SHORTS_YT_DOWNLOAD_ENABLED=false`) |
| `static/*` | vanilla-JS dashboard. `channel.html`'s proposals card labels `decision_source` through `DECIDED_BY`, which has `experiment: 'Playlist test'` since S2.1 (the playlist test's proposals show up there unchanged otherwise) |

**Scripts:** `scripts/playlist_test.py` (S2.1: `--channel` and one of `--preview` (prints per eligible playlist its arm, status and the videos it would get, the skipped playlists and the counts; writes nothing) or `--draw` (`playlist_test.draw`, no confirmation; exits 1 when refused or already drawn)), `scripts/preview_backlinks.py` (S1.4b: `--channel`, `--n` default 20; prints each video's rules answer, arm, targets, context and description before/after, or the render refusal; read-only), `scripts/reembed.py` (B6: `--channels` comma list, `--estimate` with `--usd-per-mtok`, `--skip-calibrate`;
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

- **Strategy stamp** (`app/audits.py:196-281`). `strategy_version(prompt_text, prompt_source, prompt_version_id=None)`
  returns `f"{settings.STRATEGY_LABEL}-{_strategy_hash(inputs)}"`, the hash being the first 12 hex of sha256 over
  `json.dumps(inputs, sort_keys=True, separators=(",", ":"))`. `inputs` = `label`, `prompt_source`
  (`override|shorts|generated|default`; anything else raises `ValueError`), `prompt_sha256` (of the system prompt
  actually sent), `audit_model` (`settings.AUDIT_MODEL`), `decision_question_set_version` (`decide.QUESTION_SET_VERSION`, read at call time; `"2026.10-s1-v2"` since S1.5, `app/decide.py:39`),
  `prompt_version_id`, plus `writer_model` only if a `WRITER_MODEL` setting exists (it doesn't).
  `_stamp_strategy` upserts `{version, prompt_template, model: settings.AUDIT_MODEL, config: inputs, status:
  "champion", notes: "auto-registered by _stamp_strategy (derived from config)"}` with `ignore_duplicates=True`,
  once per version per process. `prompt_template` is one of `"audit_video prompt_override (caller-supplied, e.g.
  reflection shadow candidate)"`, `"audit_configs.shorts_prompt (per-channel)"`, `"audit_configs.generated_prompt
  (per-channel)"`, `"code:app/audits.py DEFAULT_PROMPT"` (`app/audits.py:210-215`).

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
  | Decide shadow answer (B5) | `settings.AUDIT_MODEL` (the `chat_json` default) | `decide()` with `DECIDE_BACKEND=llm`, from the agent tick's triage and, per candidate pair, its next-watch question (`app/agent_tick.py` `run`, `_next_watch`; the preview asks the triage rules only) | `app/decide.py:140-158`, below |
  | Embeddings | `EMBED_MODEL = "google/gemini-embedding-2-preview"` | `embed_video` after apply; `bootstrap_embeddings` | input: title + `"\n\n"` + transcript[:6000] (`app/embeddings.py:118-120`); bootstrap passes `use_transcript=False`, so title only (`app/embeddings.py:182`). Both under `model_version = EMBED_MODEL` |
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
  # decide llm backend (app/decide.py:140-158), label "decide.<question set name>"
  # system:
  You answer one multiple-choice question about a YouTube video for a kids' nursery-rhyme channel network. Choose exactly one of the allowed answers and give your probability for each allowed answer.
  # user:
  QUESTION: {question_set.question}
  ALLOWED ANSWERS: {', '.join(question_set.answers)}
  SUBJECT: {subject}
  CONTEXT: {json.dumps(context, sort_keys=True, default=str)}

  Return only JSON: {"answer": "<one allowed answer>", "probs": {"<allowed answer>": <probability 0..1>, ...}}

  # TRIAGE.question (app/decide.py:83-95); answers no_change, backlinks, playlist, short_link, title
  Which lever, if any, should change this video this week to route more viewers to it? `backlinks`: add a related-videos block to its description. `playlist`: add it to a playlist. `short_link`: link a Short to it. `title`: rewrite its title. `no_change`: leave it alone.

  # NEXT_WATCH.question (app/decide.py:107-115, S1.5); answers yes, no
  Would a viewer who just watched video A (the source) plausibly watch video B (the target) next? `yes` or `no`.
  ```
  The CONTEXT the agent tick sends (S1.4b, `app/agent_tick.py` `_assess`): `has_related_block`, `backlink_candidates`,
  `backlinks_stopped`, `traffic_mix_28d`, `impressions`, `ctr`, `recent_interventions`. For `NEXT_WATCH`
  (S1.5, `app/agent_tick.py` `_next_watch`), SUBJECT is `<source id>-><target id>` and CONTEXT is
  `source_video_id`, `source_title`, `target_video_id`, `target_channel_id`, `target_title`, `similarity`, `join_low`.
  The system message still says "about a YouTube video" for both sets.
  The judge and proposal prompts carry no `default_language` rule.

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
  (`app/config.py:145-155`; Marathi is in the default). B3a sees an old video's edit only on a full sync, every
  3 days (`app/sync.py:520`). As of 2026-10-13 every `human` row is a playlist membership (110); none is a backlink.
- **B4** is wired into the agent tick only (S1.4b, `app/agent_tick.py`): the audit path's picker is still newest-first with no impressions filter
  (`supabase/migrations/20260904000100_next_audit_candidate_exclude_episodes.sql:37`
  `order by v.published_at desc, v.id`) and excludes in-window audits rather than active interventions (`:35-36`).
- **B5:** `decide()` is called by S1.4b's triage, which isn't deployed, so `decision_log` is still empty.
- **B6:** run for Marathi only; the siblings wait for the office to deploy #55 (`deploy/postgrest-proxy.conf`
  `client_max_body_size 16m`, merged 2026-10-23; every batch got 413 on Marathi under nginx's 1 MB default).
  The playlist engine and its RPCs still use `EMBED_MODEL` and the global thresholds (§7.3 items 4–5); the only
  reader of the new vectors and the stored thresholds is S1.1's `backlinks.candidates`, called by the agent tick.
- **B7:** done; `bho`/`raj` stay unused while Bhojpuri and Rajasthani use plain `hi` (owner, 2026-10-06).
- **B2's persistence of the A8 registry** ("Persisting it is Phase B work", Part 1 A8): not built; registry is
  in-memory (`app/job_status.py`).

**Slice 1 (Part 2 §1–§2, §3.4, §6.1)**
- Tick routing on `agent_enabled` (§6.1, Part 4 S1.4): built (S1.4b, `app/autopilot.py` `_agent_tick`,
  `app/agent_tick.py`, `eligibility.can_run_agent`), not deployed, and no channel has `agent_enabled`.
- The pick's cooldown and once-per-experiment exclusions (§2.1, Part 4 S1.4 "Pick"): built (S1.4a, `warm_pool()` in
  `20261023000000`, `app/warm.py`), not applied; called by the agent tick (S1.4b).
- Rules triage, `no_change` as a `declined` intervention, holdout with would-be targets, the cap and the kill
  switch (§2.2, §1.3, Part 4 S1.4): built (S1.4b, `app/agent_tick.py`), not deployed. The P1 stop rule's input
  reads `lever_verdicts` since S1.6b (`agent_tick.backlinks_stopped`).
- Backlink candidates and fleet siblings (P2, Part 4 S1.1): built (`app/backlinks.py` `siblings`, `candidates`),
  called by the agent tick (S1.4b). Sibling targets appear only once the sibling channels have `MODEL_VERSION` vectors (S1.7 step 2;
  B6 ran for Marathi only). The next-watch question in shadow (§2.3, Part 4 S1.5): built (`decide.NEXT_WATCH`,
  asked by `app/agent_tick.py` `_next_watch`), not deployed.
- Code checks for links (§2.4): not built. Partially present: `DESCRIPTION_MAX = 5000`, the 15-hashtag cap and
  `rejection()` (`app/audit_suggestion.py`).
- Canonical backlink block (§3.4, Part 4 S1.2): built (`app/backlinks.py`), called by the agent tick and `apply_backlinks`, with
  Marathi's heading `आणखी गाणी पहा:` (owner, 2026-10-23, D3), and since fleet readiness a heading for every channel language (§5 `backlinks.py`), not yet skimmed by native readers.
- Description-only apply (§2.5, Part 4 S1.3): built (`app/backlinks_apply.py`), with its revert and the ledger
  change; called by the agent tick (S1.4b) for treated rows, and refusing while `BACKLINK_APPLY_ENABLED` is false.
- Weekly measurement and the stop rule (Part 4 S1.6, P1): built (S1.6a `app/lever_measurement.py`, S1.6b
  `app/lever_verdicts.py`, the `lever_measurement` job, `lever_verdicts` in `20261023010000`), not deployed and
  not applied. The findings-doc write-ups of the first verdict and the stop-rule outcome are S1.8 (owner).
- `reach_warmup` on human-run channels (§1.4): set 2026-10-26 on the 5 channels without reach (Haryanvi, Rajasthani, 3D Animated, Kannada, Telugu; `docs/PLAN_TO_2026-11-27.md`). The other 8 ingest reach through `measurement_enabled`.

**Slice 2 (Part 2 §4; Part 5, ready to build 2026-10-26; S2.1, S2.2 built)**
- The P3 curated-playlist test (Part 5 S2.1–S2.3): the arms, candidates, draw and preview (S2.1, `app/playlist_test.py`, `playlist_arms` in `20261027000000`) and the queued, budgeted apply behind `PLAYLIST_APPLY_ENABLED` with `test_dates` (S2.2, `app/playlist_test.py` `run_apply`, the `playlist_test_apply` job) are built, not deployed, not applied, not run. The measurement, verdict and `GET /channels/{id}/playlist-test` (S2.3): not built. Jev fit check replacing `playlists._llm_judge`: not built, deferred by Part 5 E12.
- Short → video links recommend-only to the team (P4, Part 5 S2.4–S2.6): no code path.
- Per-channel auto-apply flip for playlist adds: not built (`PLAYLIST_HITL` is one global setting,
  `app/config.py:109`).

**Slice 3 (Part 2 §3)**
- `app/agent/loop.py`, `openrouter.chat_tools`, `AGENT_MAX_TURNS`, tools (`get_traffic_mix`, `get_search_terms`,
  `get_niche_reference`, `get_channel_playbook`, `submit_change`, `decline`): none exist.
- `WRITER_MODEL` and the writer bake-off (§3.3): not built (the stamp reads it via `getattr`, `app/audits.py:242`).
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
   (`app/audits.py:218-245`), so shorts/override/generated audits stamp differently. Audits before A6 still carry
   `2026.07-baseline-v1`.
2. **Measurement cadence (Part 2 §1.1, §1.7).** Spec: weekly windows, extended once to 14 days. Built: symmetric
   21-day pre/post windows (`MEASUREMENT_WINDOW_DAYS`, `app/reach.py:60-82`) plus `ROLLOVER_SLOP_DAYS=1`, judged
   on CTR only.
3. **Dormancy (Part 2 §2.1).** Spec: keep dormant videos out at selection. Built: dormancy is found only after the
   window (`REASON_DORMANT`, `app/measurement.py:280`); the picker is newest-first (7.1 B4: the warm filter exists
   but the tick doesn't use it). A7 (2026-10-06):
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
   (`app/human_edits.py` `our_videos`), since sibling channels link into each other (P2), plus the videos fetched
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
13. **`decide()` and `decision_log` (Part 3 B5).** The spec gives `decide(question_set, subject, context)` and no
   question sets. Built: a `QuestionSet` (name, question, allowed answers, rules function) and one set, `TRIAGE`
   (Part 2 §2.2's rules: `backlinks` with no related block and at least `BACKLINK_MIN_CANDIDATES` candidates, else
   `no_change`; context keys `has_related_block`, `backlink_candidates`), so `BACKLINK_MIN_CANDIDATES` is added in
   Phase B rather than Slice 1. One `QUESTION_SET_VERSION` covers every set in `app/decide.py` and replaces the A6
   placeholder (`DECISION_QUESTION_SET_VERSION` is gone from `app/audits.py`), so after deploy every audit source stamps a new
   `strategy_version` (and `_stamp_strategy` upserts a new `audit_strategies` row) though no prompt changed.
   `TRIAGE` offers §2.2's five options; its rules choose only `backlinks` or `no_change` (the Slice 1 baseline), so a
   backend's other choices are logged but can't agree with the rules. A backend answer must give a probability
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
   `_apply_audit_and_handle`). A `declined` row is lever `backlinks`, arm `n/a` (Slice 1's only lever), so it
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
  question set is not stored: since S1.5 adds `NEXT_WATCH`, it is told apart only by `subject`'s shape (a video id
  for `TRIAGE`, `<source>-><target>` for `NEXT_WATCH`) and by `triage_json` on the linked intervention (7.3 items 13, 18).
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
