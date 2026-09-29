# Midas — implementation spec: the discoverability agent

Date: 2026-09-23
Status: Part 1 ready to build · Part 2 approved design, not started
Supersedes:
- `2026-09-22-discoverability-agent-spec.md`
- The separate 2026-09-23 discoverability and Phase A specs (merged here)
- As design sources: `CONTINUOUS_IMPROVEMENT_LOOP.md`, `PLAYLIST_OPTIMIZATION.md`, `plan.md` (see Part 2 §0.5)

Diagram: `docs/midas-seo-agent-v2.excalidraw`. Step numbers (1–8) in Part 2 refer to it.
Ground truth used: `STATE.md` @ `bddd373`.

---

## How to use this document (read first)

This file has two parts, and they are used differently.

- **Part 1 is the build task.** It is the only part to implement now: Phase A, in the run order given.
- **Part 2 is the design.** It describes the whole target system and the order its stages arrive. Read it for context: *why* each Phase A task exists, and what later work depends on it. **Do not implement anything from Part 2.** That includes Phase B and Slices 1–5, and it holds even where Part 2 describes code in detail.

**After Phase A's exit gate**, the Phase B build section is written into this file as a new Part, using Phase A's findings. Each later slice follows the same pattern. Part 2 is updated if a finding changes the design. At any time, exactly one Part is marked "ready to build."

---

## Part 1 — Phase A: gates (ready to build)

**Purpose.** Answer the questions everything else depends on, and stop changes we can't measure, *before* building anything new. Phase A adds no new levers and makes no new writes to YouTube.

**Deliverable.** The A0 operational change; code changes A4–A6 and A8–A10; doc changes A11; plus `docs/PHASE_A_FINDINGS.md` with the A0 record and answers to A1–A3 and A7. Each answer includes raw evidence: request, response excerpt, date, and channel.

**Probe discipline.** This is the same discipline as Phase 0's CTR probe (`docs/PHASE_0_GAPS.md`). One real call per question before any abstraction is written. If a probe fails, record the exact error and the variants tried. Probes are scripts under `scripts/probes/`, marked `live`, and never run by the test suite.

### Run order

The tasks are numbered A0–A11 for reference. Build them in this order:

1. **A0: the pause.** Minutes of work; stops further rewrites immediately.
2. **Start A1's report job on day one.** A new Reporting API job can take a day or more to produce its first report. Create it before anything else and let it generate while the code work happens.
3. **A8: failure visibility**, so everything deployed after it is observable.
4. **A4, A10, A6, A5**: the remaining code changes.
5. **Deploy, then A9.** Confirm health scores refresh and `/health/jobs` shows every job.
6. **A1–A3: the probes**, once the first report is ready. Then **A7**, the live numbers.
7. **A11: doc cleanup** last, so the banners and regeneration prompt reflect what Phase A actually found.

---

### A0 — Pause Midas title autopilot (do this first)

Part 2 §6.1 explains why. This is an operational change, not code.

**Steps.**
1. **Check Shorts independence before flipping anything.** Read `app/autopilot.py:tick` and `app/eligibility.py` (`can_audit`, `can_cut_shorts`). Record whether the Shorts action still runs for a channel with `autopilot_enabled = false` and `autopilot_shorts_enabled = true`.
   - If it does, Shorts uploads keep running. That's intended: they don't edit existing videos.
   - If it doesn't, record that, and ask the owner whether Shorts should pause too. Don't add code to separate them in Phase A.
2. **Set `autopilot_enabled = false`** on the Midas channel via `PATCH /auth/channels/{id}`. Do **not** use the pause mechanism (`autopilot_paused_reason`): it has a cooldown (`AUTOPILOT_PAUSE_COOLDOWN_MINUTES`) and can resume on its own.
3. **Leave `measurement_enabled` on,** so already-applied audits finish their windows and get verdicts.
4. **Record in the findings doc:**
   - Pause timestamp and channel ID.
   - The Shorts answer from step 1.
   - The list of videos with `measurement_status in ('awaiting_window','measuring')` at pause time, with the date each window closes. Slice 1 excludes these until then (Part 2 §1.6).
5. **If the SEO team takes over the channel during the pause** (Part 2 §11.6), record the handover date and set up their log (video, what changed, date).

**Acceptance.** For 24 hours after the change, the autopilot log (`GET /channels/{id}/autopilot/log`) shows no new audits or applies on that channel. The findings entry is complete.

**Do not re-enable autopilot on this channel** until Slice 1's tick routing is merged (Part 2 §6.1).

### A1 — Traffic-source probe (the critical one)

**Question.** Can we get per-video, per-day views by traffic source, and ideally by *referring video*?

**Steps.**

1. **Reporting API.**
   - Create or confirm a job for `channel_traffic_source_a2` on the probe channel (`UCr5-YUqBiW7PUmeAtxUWuRg`), reusing `app/reporting_client.py`.
   - Wait for the first report, download it, and record:
     - The exact column names.
     - The distinct values of the traffic-source type column.
     - Whether a traffic-source detail column exists, and what it contains for `RELATED_VIDEO`, `PLAYLIST`, `SHORTS` (or the equivalent names), and `YT_SEARCH`.
     - The observed lag (data date vs availability).
2. **On-demand Analytics**, for comparison. Try `dimensions=insightTrafficSourceType` with `filters=video==<id>` on a warm video. Then try `insightTrafficSourceDetail` filtered to one source type at a time. Gap 6 recorded a 400 on one query shape, so record which of these variants succeed and which return 400.
3. **Description-link attribution.** Pick a video the SEO team linked from another video's description at least two weeks ago. Check whether views arriving from that description show up, and under which source type and detail.

**Answer in findings, as one of:**
- **(a)** Views attributable to the referring video.
- **(b)** Target-level totals by source type only.
- **(c)** Nothing usable.

Give the same answer separately for playlist traffic and Short → video traffic. These outcomes map directly onto Part 2 §1.2.

**Acceptance.** The findings doc has the report columns, sample rows (IDs are fine; no personal data exists here), the chosen outcome per lever, and the lag.

### A2 — Short → video link field

**Question.** Does the Data API expose, or allow setting, a Short's related-video link?

**Steps.**
1. Ask the team for one Short with a related video set in Studio.
2. `videos.list` on it with every readable part (`snippet,contentDetails,status,topicDetails,recordingDetails,localizations,player`). Search the raw JSON for the linked video's ID.
3. Check the current `videos.update` reference for any writable field matching it.
4. **Do not attempt a write.**

**Answer:** readable yes/no, writable yes/no, with the raw evidence.

### A3 — Search terms

**Question.** Can we read the search queries that led viewers to a given video?

**Steps.** Probe `insightTrafficSourceDetail` restricted to the YouTube-search source type, on a warm video, both on-demand and via whatever the A1 report provides. Record availability, granularity, and any minimum-volume suppression.

**Answer:** available yes/no, and the shape. This decides whether `get_search_terms` (Part 2 §3.2) is built.

### A4 — Freeze unmeasured writers

Add these settings to `app/config.py`, **each defaulting to `false`**:

| Setting | Controls | Current registration |
|---|---|---|
| `PLAYLIST_DISCOVERY_ENABLED` | `playlist_discovery` job (creates playlists) | `app/main.py` lifespan, Sun 03:00 |
| `PLAYLIST_RECONCILE_WRITES_ENABLED` | the add/remove half of `playlist_reconcile`; `sync_playlists` keeps running | `app/main.py`, 02:00 |
| `PLAYLIST_TUNING_ENABLED` | `playlist_tuning` job (mutates global `PLAYLIST_JOIN_HIGH`) | Mon 03:30 |
| `REFLECTION_ENABLED` | `reflection` job (prompt rewrites, `search.list`, Perplexity) | Mon 04:00 |

**Rules.**
- When a flag is off, the job is **not registered**, and startup logs one line naming the flag. The exception is reconcile, which still registers for sync; skip its write step and log that it was skipped.
- `POST /channels/{id}/playlists/reconcile` and `POST /channels/{id}/reflection/trigger` return 409 with the flag name when their flag is off. `.../playlists/proposals/decide` stays available: those are human decisions.
- Also freeze **live or auto prompt promotion**: while `REFLECTION_ENABLED` is false, `POST .../prompt-versions/{vid}/promote` returns 409. Currently live prompts keep running unchanged.

**Tests.**
- Each job is absent from the scheduler when its flag is off, and present when it's on.
- Reconcile with writes off calls sync but never `yt_playlist_items_insert` or `yt_playlist_items_delete`. Assert with the existing fakes.
- The endpoints return 409.

**Acceptance.** Tests green. A one-line entry in `STATE.md` §4 per frozen job.

### A5 — Haryanvi channel `default_language`

Channel `UCc4Tv_DEGDEKrKAt-vyVNmw` has `default_language = NULL`, and `eligibility.can_audit` gates it out. Before setting a value:

1. **Check what the code does with the value.**
   - `lang_display_name` must render it sensibly (e.g. "Haryanvi").
   - `youtube_metadata.py` must send a language code YouTube accepts on `videos.update`. `bgc` (ISO 639-3) may not be in YouTube's accepted list.
2. **Probe once.** Confirm the accepted code, or the fallback YouTube would store, with an `i18nLanguages.list` call. That call is read-only, 1u.
3. **If `bgc` isn't accepted,** keep `default_language = 'bgc'` for prompts and add a mapping in `youtube_metadata.py` from content language to the API language code, e.g. `bgc → hi`. Document the choice.

**Tests.** `lang_display_name('bgc')`. The payload builder emits the mapped code.
**Acceptance.** The value is set on the channel (office DB, recorded in findings). Tests green.

### A6 — Honest strategy stamp

**Problem.** Today `STRATEGY_VERSION` is a static env string (`2026.07-baseline-v1`), and its `audit_strategies` row was inserted once with `ignore_duplicates=True` (`app/audits.py:218`) and `model = anthropic/claude-haiku-4.5`. Model swaps in `.env` are invisible.

**Change.**
1. Derive `strategy_version` at startup as `<STRATEGY_LABEL>-<short hash>`. The hash covers:
   - The prompt source identity: `DEFAULT_PROMPT` text hash, and the per-channel prompt-version ID at audit time.
   - `AUDIT_MODEL`.
   - `WRITER_MODEL`, when it exists.
   - The decision question-set version, once `decide()` exists. Include a placeholder constant now.
2. Upsert an `audit_strategies` row per distinct version, with the real `model` and a `config` JSON of the hashed inputs.
3. Keep the existing seed row for history.

**Tests.** Changing `AUDIT_MODEL` in settings yields a different version and a new row. The same inputs yield the same version. Audits are stamped with the derived version.

**Acceptance.** Tests green. The office deployment's first audit after deploy shows the model actually in use.

### A7 — Live numbers

Run the SQL block at the end of `STATE.md` §8 on the office machine, and paste the results into the findings doc.

Add two queries needed to pick rollout channel #1 (Part 2 §11.3):

```sql
-- warm pool size per channel (28 ingested days, ≥500 impressions)
select channel_id, count(*) warm_videos
from (select channel_id, video_id, sum(impressions) imp
      from video_reach_daily where date > current_date - 30 group by 1,2) t
where imp >= 500 group by 1 order by 2 desc;

-- how many applied audits in the last 90 days landed on dormant videos
select v.channel_id, count(*) filter (where a.measurement_result->>'reason_code' = 'dormant') dormant, count(*) total
from audits a join videos v on v.id = a.video_id
where a.applied_at > now() - interval '90 days' group by 1;
```

The `reason_code` value for dormancy must be confirmed against `app/measurement.py` before running. Adjust the literal if it differs.

### A8 — Make per-channel job failures visible

**Problem.** `_run_per_channel` in `app/main.py` catches each channel's exception so one channel can't stop the others. APScheduler then logs the job as "executed successfully." This is how `playlist_health_score` raised `NameError` daily from 2026-08-06 to 2026-09-23 unnoticed (STATE §8). Every job added in Phase B would inherit the same blind spot.

**Change.**
1. Keep isolating channels: one channel failing must not skip the rest.
2. Collect per-channel exceptions during the run. Log each at `ERROR` with the job ID, channel ID, and traceback.
3. After all channels have run, if any failed, **raise** a summary exception naming the failed channels. APScheduler then records the run as failed.
4. Register an APScheduler `EVENT_JOB_ERROR` listener that logs failed jobs distinctly and updates an in-process registry: last run time, last status, and failed channels with their error message, per job.
5. Expose the registry at `GET /health/jobs`. It's in-memory, so a restart clears it. Persisting it is Phase B work, alongside the other new tables.

**Tests.**
- Two channels where one raises: the other still runs, the job ends failed, and the registry lists the failing channel.
- All channels succeed: the job ends successful.
- The endpoint returns the registry shape.

**Acceptance.** Tests green. After deploy, `GET /health/jobs` on the office machine shows every registered job with a status after its first run.

### A9 — Deploy and verify the health-scorer fix

The `METRIC_ROW_PAGE` fix is merged (`bddd373`), but the office machine's stored `health_*` values stay stale until it's deployed and the 07:00 UTC job runs.

**Steps.** Deploy, which is also required for A4–A10. After the next 07:00 UTC run, re-run the playlist-health freshness query from STATE §8 and record the new `max(health_computed_at)` per channel in the findings doc.

**Acceptance.** Every `playlist_health_enabled` channel shows `health_computed_at` from after the deploy, and `GET /health/jobs` (A8) shows the job succeeded.

### A10 — Close the quota gaps

**Problems (STATE §8, §7.1).**
- Autopilot applies without checking quota first. It only learns it's out when YouTube returns `quotaExceeded`.
- Manual revert (`revert_audit`) doesn't check `quota.can_afford` before writing.

**Change.**
1. **Autopilot.** Before any YouTube write in a tick, call `quota.can_afford` with the write's cost. If it can't afford it, skip the tick and log `quota_insufficient`. Don't pause the channel: the next tick after the Pacific reset proceeds normally.
2. **Revert.** Check `quota.can_afford` before writing. If it can't afford it, return 409 with the remaining units.
3. **Keep the existing fleet-wide dormancy on a real `quotaExceeded`.** The Data API quota is shared across all channels in the project, so fleet-wide is correct. Make the log line state that explicitly, so it isn't mistaken for a single-channel problem.
4. **Out of scope:** fixing the 1-unit apply overestimate (`quota.APPLY` = 51u vs actual 50u). It errs on the safe side; note it in STATE only.

**Tests.**
- A tick with insufficient quota makes no YouTube call and pauses nothing.
- A revert with insufficient quota returns 409 and makes no call.
- The `quotaExceeded` handling is unchanged.

**Acceptance.** Tests green.

### A11 — Mark the old specs superseded

Without this, every `STATE.md` regeneration reports dozens of "missing" items that were deliberately dropped.

**Changes (docs only).**
1. **Add a banner** to the top of `docs/CONTINUOUS_IMPROVEMENT_LOOP.md`, `docs/PLAYLIST_OPTIMIZATION.md`, and `docs/plan.md`. It states they're superseded by `docs/superpowers/specs/2026-09-23-midas-implementation-spec.md` and kept for history, and names which parts were carried forward, following Part 2 §0.5 "Kept".
2. **Mark the old discoverability spec.** Mark `docs/superpowers/specs/2026-09-22-discoverability-agent-spec.md` as superseded in its status line and commit it, since it's currently untracked. If the separate `2026-09-23-discoverability-agent-spec.md` or `2026-09-23-phase-a-gates-spec.md` were committed earlier, delete them: this file replaces both.
3. **Commit the diagram** as `docs/midas-seo-agent-v2.excalidraw`.
4. **Rewrite the regeneration prompt** in `STATE.md` §9 so §7 is computed against this implementation spec (Part 2, and the phase parts added to it over time), not the three old docs. Old-spec items appear only if Part 2 says they're carried forward.

**Acceptance.** The banners are present. The next regeneration's §7 lists no items from the old specs that Part 2 §0.5 records as scrapped.

---

### Phase A exit gate

Phase B starts only when all of these hold:

- `docs/PHASE_A_FINDINGS.md` answers A1–A3 with raw evidence and records an outcome — (a), (b), or (c) — per routing lever.
- A0 is done and recorded: no Midas applies on the channel for 24 hours after the change.
- A4–A6 and A8–A10 are merged, tests green, deployed to the office machine, and the frozen jobs are confirmed absent from the running scheduler's log.
- A9 shows fresh health scores, and `GET /health/jobs` reports every job's status.
- A11's doc changes are merged.
- A7 numbers are in the findings doc, and rollout channel #1 is chosen with the reason recorded.
- **If A1 returns (c) for every routing lever, stop and revisit Part 2 before Phase B.** The plan's measurement design depends on it.

### Not doing in Phase A

- No new tables. `interventions`, `video_traffic_source_daily`, and `decision_log` are Phase B.
- No Jev integration or API access work beyond reading the docs.
- No re-embedding.
- No changes to `audit_video`, the house format, or the picker.
- No new writes to YouTube of any kind. A5's probe is read-only. A0 stops writes; it doesn't add any.
- No re-enabling of autopilot on the Midas channel. That waits for Slice 1's tick routing.
- No persistence for the A8 job registry (Phase B).

### Review protocol

- Per task (A0–A11): an independent review sub-agent with a clean context checks the work against this spec before the next task starts. Fix before proceeding.
- Phase review at the end: an explicit list of **spec'd but not built** and **built but not spec'd** items, and a check that `STATE.md` §1, §3, and §4 reflect the change.

---

## Part 2 — Design (context only; do not build)

### 0. Why

#### 0.1 What we learned (carried forward, one correction)

1. **The team reports seeing SEO impact in about a week.** *Correction:* this is self-reported and unmeasured. The team also says it isn't confident which of its practices work. We treat the one-week clock as a **hypothesis to test** (§1.4), not a design fact.
2. **Metadata rewrite alone is too thin to justify an agent.** Unchanged.
3. **The team's levers are routing levers, not writing levers:**
   - **Description backlinks**: links to other channel videos in a video's description.
   - **Playlist placement**: adding videos to relevant playlists.
   - **Short → long video links**: linking each uploaded Short to a related long video. *Missing from the 2026-09-22 spec.*

#### 0.2 Why the current system loses (from STATE.md)

- **It never says "leave it alone."** `DEFAULT_PROMPT` says "rewrite it to a FIXED house format", the schema has no no-op, and autopilot applies any valid rewrite.
- **It edits videos nobody sees.** `next_audit_candidate` orders by `published_at desc` with no impressions filter. 381 of 381 `not_applicable` verdicts on the measure path were dormant videos (`app/measurement.py`).
- **Its sensor can't see routing.** Loop 0 measures CTR. Links and playlists change *where views come from*, not how often a thumbnail is clicked. The traffic-source sensor is disabled (`TIER2_TRAFFIC_SOURCE_SUPPORTED = False`, STATE Gap 6).
- **Its one routing lever is switched off.** `join_pass` is commented out (`app/autopilot.py:453-455`).

#### 0.3 The reframe

The job is **"improve this video's discoverability using the channel's own catalog"**, across four levers: backlinks, playlist placement, Short links, and titles. *No change* is always a valid outcome. Every change is measured against unchanged videos. The system learns per channel which levers work.

---

### 0.5 Scrapped, resolved, frozen, kept

#### Settled scraps (unchanged from 2026-09-22)

1. Metadata-first sequencing. Levers ship in order of expected impact, routing first.
2. The 3-week learning clock as the gate on getting smarter.
3. Whole-prompt reflection rewriting as the memory (`app/reflection.py`).
4. Fleet autonomy as the organizing principle.
5. The blind single-call rewrite.

#### Resolved dissents (decided 2026-09-23)

6. **LangGraph: out.** Use a hand-rolled loop (§3.1).
   - **Why.** The loop is "call model → run requested tools → append results → repeat until a terminal tool or the turn cap." That's about 10 lines on top of `app/openrouter.py`. None of LangGraph's distinguishing features are needed: checkpointing (runs are seconds long and retried by the next tick), mid-run human interrupts (review happens after, via `playlist_proposals` and quarantine), branching (the lever branch now lives upstream in triage, step 2), streaming, or multi-agent handoff.
   - **What it would have cost.** A second model interface (every model swap, including the writer comparison, Sarvam's own API, and Jev, would need a LangChain adapter). An extra instrumentor inside the OpenTelemetry isolation guard. Framework message types between the test fakes and the assertions. Pinned-version churn.
   - **Reversibility.** Tools are plain Python functions, so moving to LangGraph later is cheap. Moving off it later would not be.
   - **Revisit if** traces show runs needing mid-run branching that triage can't handle, durable pause/resume for approval, or multiple cooperating agents.

7. **`search_competitors`: out of v1.**
   - **Why.** It serves none of the routing levers, which all draw on the channel's own catalog. It costs 100u per call (two applies) against a budget that has already starved applies (2026-08-03/04). It lets the model decide when to spend. It returns ranking, not measured clicks. Its results change daily, so runs can't be reproduced.
   - **Replacement.** A scheduled, cached **niche reference** (built in Slice 3, §3.6), exposed as a free read tool, and the channel's **own search terms** if Phase A shows they're available. Both are deterministic and budgeted.
   - **Revisit if** traces show the agent repeatedly lacking information those two don't provide, *and* the title lever is producing measured wins.

#### Frozen from Phase A onward (new)

8. Unmeasured writers are frozen on every channel. Their changes would contaminate every measurement in §1.
   - `playlist_discovery`: weekly playlist creation.
   - `playlist_reconcile`: adds and removals. Inventory sync stays on, because the health scorer needs it.
   - `playlist_tuning`: mutates the process-global `PLAYLIST_JOIN_HIGH` from one channel.
   - `reflection`: prompt rewriting, its `search.list` spend, and its Perplexity input.

   They stay in the codebase behind flags until the relevant slice replaces or retires them.

#### Caveats against this spec's own bets

9. **Backlinks may not be learnable.** This depends on the Phase A traffic-source probe. §1.2 defines what happens under each probe result.
10. **Titles may not deserve their turns.** The title lever ships last and has to earn its place against the routing levers on measured results.
11. **The agent itself has to earn its place.** Routing levers start as fixed pipelines (§6, Slices 1–2). The LLM agent enters in Slice 3 as a challenger. If its tool choices don't vary per video and its verdicts don't beat the pipeline, it isn't adopted.

#### Kept

- The sensor layer: `metrics_poll`, `reporting_poll`, `reach.py`, `video_reach_daily`.
- The apply path: `apply_audit_internal` → `yt_videos_update`.
- The `AuditSuggestion` decoder and validation.
- Quota: `JobBudget`, apply reserve.
- `status_vocab` (with its guard test) and Certification (`reach.certify`).
- The playlist write functions in `youtube_client.py` and the inventory, health, and proposal machinery.

---

### 1. Measurement and learning loop

#### 1.1 Cadence

- The work rate is unchanged: autopilot `tick()`.
- Measurement and the playbook rebuild run **weekly**.
- **Reporting lag.** CTR and reach CSVs arrive 1–6 days late (`app/config.py:193-194`). A "7-day window" therefore yields its verdict around day 9–13. Plan for that; don't hide it.

#### 1.2 Signal per lever

| Lever | Primary indicator | Source | Status |
|---|---|---|---|
| Description backlinks | Views arriving at linked videos *from* the source video's description | Traffic source + detail (see note below) | **Depends on Phase A probe** |
| Playlist placement | Video's views from `PLAYLIST` traffic; joined playlist's `playlistStarts`, `viewsPerPlaylistStart` | Traffic source; `playlist_metrics` | Traffic source depends on probe; playlist metrics built |
| Short → video link | Long video's views arriving from the Short | Traffic source + detail | Depends on probe |
| Title | CTR vs a comparable window | `video_reach_daily` | Built |

**What the backlink indicator becomes, by probe outcome:**
- **(a)** Views can be attributed to the referring video. The indicator is used as defined, and it's attributable per link.
- **(b)** Only target-level totals by source type are available. Use the lift in targets' views from the relevant source type. This is a weaker, pooled signal: commit only on channel-level patterns, never per link.
- **(c)** Nothing usable. Backlinks become a lever we **do but can't learn from**. They keep a fixed conservative policy and are excluded from the playbook. This is a conscious decision, recorded in the Phase A findings.

#### 1.3 Control group (new)

The 2026-09-22 spec compared each video only with its own past, which a weekly window makes vulnerable to trends and seasonality.

- After triage (step 2) assigns a lever, `HOLDOUT_PCT` of those videos are assigned to the **holdout** arm by a stable hash of `video_id` and lever.
- Holdout videos are recorded as interventions with `arm = 'holdout'` and are **not applied**.
- The verdict for a lever is the treated arm's change minus the holdout arm's change over the same window.
- Holding out *after* triage keeps the arms comparable, because both contain videos the system chose for that lever.
- The quota saved on holdout videos is small and worth it.

#### 1.4 The SEO team's edits (new)

- On sync, detect changes Midas didn't make: new links in descriptions, new playlist memberships, and Short links if readable (Phase A2). Record each as an intervention with `origin = 'human'`.
- Measure them with the same indicators. There's no holdout for human edits, so compare against the same channel's unchanged videos in the same week.
- Turn on `reach_warmup` for human-run channels so their reach and traffic data are ingested.
- **Purposes:**
  - Test the one-week-impact hypothesis (§0.1).
  - Learn which of the team's habits work.
  - Provide an external benchmark: the system has to beat human edits measured the same way.

#### 1.5 Commitment rule

- A lever's verdict is directional (helped / no change / worse). It is not a significance test.
- The playbook commits a pattern only when its direction is consistent across at least `PLAYBOOK_MIN_VIDEOS_PER_PATTERN` videos and the treated arm beats holdout.
- **One video is an anecdote.**

#### 1.6 One change at a time

- Each video has at most one active Midas intervention per measurement window, of any lever.
- Title rewrites under the house format replace the whole description. The renderer must re-append any existing backlink block (§3.4), and a title change on a video with an active backlink intervention waits until that window closes.

#### 1.7 Low-traffic videos

The warm filter (§2.1) keeps most of them out. If a warm video still doesn't reach its indicator floor within the window, extend that video's window once, to 14 days. If it still doesn't, mark it `insufficient_data` and exclude it from the week's learning. Never silently drop it.

---

### 2. Pipeline (diagram steps 1–5)

#### 2.1 Step 1: pick a video (code, no AI)

The warm filter is added to `next_audit_candidate` (SQL) and to its in-app parity fallback.

- **Eligible:** public, not an episode (`is_episode`), on a channel with `agent_enabled`, certified reach (`reach.certify`), and **impressions ≥ `WARM_MIN_IMPRESSIONS` over the trailing `WARM_WINDOW_DAYS` of ingested data-days**.
- **Excluded:** videos with an active intervention (§1.6). This replaces the current awaiting/measuring exclusion.
- **Order:** most impressions first. This is exploitation. A small random share (`WARM_EXPLORE_PCT`) of picks comes from the rest of the warm pool, so the long tail isn't starved.
- The "CTR below channel band" condition applies **only to the title lever**, inside triage. Any warm video can benefit from routing.

#### 2.2 Step 2: triage (Jev)

- **Output:** exactly one of `no_change`, `backlinks`, `playlist`, `short_link`, `title`, plus a probability per option.
- **Input state:** current description (does it already have a related block?), playlist memberships, whether the video has a Short pointing to it, traffic mix, CTR vs channel band, recent interventions and verdicts, and the playbook once one exists.
- **`no_change`** is recorded as a `declined` intervention with the triage rationale. It spends zero quota and zero agent turns.
- **Rollout.**
  - Slice 1 starts with a **rules baseline**: backlinks if no related block and at least `BACKLINK_MIN_CANDIDATES` candidates exist; otherwise `no_change`. Jev runs in **shadow**: its choice is logged next to the rules' choice.
  - Jev's triage goes live only if its choices, applied, beat the rules baseline on measured verdicts.

#### 2.3 Step 3: prepare the change

| Lever | Slice 1–2 (pipeline) | Slice 3+ (agent challenger, §3) |
|---|---|---|
| Backlinks | Candidates = channel top performers above the floor, filtered by tag/title overlap (embeddings after re-embed, §4). Jev answers "would a viewer of A plausibly watch B next?" per pair. Keep top `BACKLINK_MAX`. | Agent gathers context and chooses |
| Playlist | Candidates from playlist inventory. Jev fit judgment replaces `playlists._llm_judge`. Written to `playlist_proposals`. | Agent |
| Short link | Jev picks the best long video for each Short. Queued for the team. | Agent |
| Title | Existing `audit_video` path, only when triage says `title` | Agent with writer model (§3.3) |

#### 2.4 Step 4: checks (code first, then Jev)

- **Code (hard rules):**
  - Every link target is a public video on the same channel and not the video itself.
  - At most `BACKLINK_MAX` links.
  - Description ≤ 5,000 chars.
  - 15-hashtag cap still holds.
  - Language code is present.
  - Title changes pass `AuditSuggestion.rejection()`.
- **Jev (judgment), as parallel yes/no questions:**
  - Does the output target the channel's `default_language` audience?
  - Is it kid-appropriate?
  - Are the links relevant to this video?
  - For titles: is it faithful to the transcript?
- **On failure:** one retry of step 3 with the failure reasons, then quarantine.
- **Rollout.** Jev checks run in shadow alongside the code checks in Slice 1. They start *blocking* once their false-positive rate on human-reviewed samples is acceptable (§9).

#### 2.5 Step 5: apply

- **Backlinks.** `videos.update` changing only the description: the current description plus the canonical block (§3.4). The payload builder (`youtube_metadata.py`) must send the current title and category unchanged. Charged through the existing quota gate (50u).
- **Playlist.** Recommend-only (Slice 2). Confirmed proposals apply via `yt_playlist_items_insert` (50u).
- **Short link.** Recommend-only to the team, unless Phase A2 finds an API field. It enters the §1.4 human ledger when the team applies it.
- **Title.** The existing apply path, unchanged.

---

### 3. The agent (Slice 3): `app/agent/`

#### 3.1 Loop

- `app/agent/loop.py`: hand-rolled. Call `openrouter.chat_tools` (new, next to `chat_json`) with the lever's toolset.
- Execute requested tools. Return errors to the model as text rather than raising.
- Stop on a terminal tool or after `AGENT_MAX_TURNS` (start 12, tune from traces).
- Persist the full trajectory on the intervention row.
- Tracing uses the existing `app/tracing.py` spans. No new instrumentor.
- Model: `AUDIT_MODEL` for reasoning. The writer model is separate (§3.3).

#### 3.2 Tools

Each tool is pure, hard-capped, returns compact results, and returns errors rather than raising.

- `get_video`, `get_transcript`, `get_audit_history`. As 2026-09-22 §3.1.
- `get_channel_top_performers(order="best"|"worst")`, filtered on `MIN_IMPRESSIONS`.
- `get_related_top_performers(video_id)`. Candidates as in §2.3, with the Jev next-watch score attached.
- `get_playlists(channel_id)`, from `playlists._serialize_playlists`.
- `get_traffic_mix(video_id)`. **New.** Where this video's views come from, once Phase B ingests it.
- `get_search_terms(video_id)`. **New, conditional on Phase A3.**
- `get_niche_reference(channel_id)`. **New, free.** Returns the cached niche summary, a few example titles, and its build date (§3.6). Returns empty, with a reason, if the channel has no reference yet.
- `get_channel_playbook(channel_id)`. Returns empty below the floor.
- **Terminal tools:**
  - `submit_change(lever, payload, reasoning)`, validated per lever by §2.4.
  - `decline(reason)`, valid and costing zero quota.

  `decline` moves forward from Slice 4 to exist from Slice 3 day one. In Slices 1–2 its equivalent is triage's `no_change`.

#### 3.3 Writer model (title lever only)

`write_candidates(lever, context)` is a tool backed by a configurable `WRITER_MODEL`. It is distinct from the reasoning model. The bake-off happens in Slice 3:
- Offline first, candidates from 3–4 model families on the same context.
- Then online: the K title candidates come from different families, stamped per candidate, so verdicts show which family wins per language.

#### 3.4 Canonical backlink block

- Rendered by code, never written by a model.
- Delimited by fixed marker lines so it can be found, replaced, and measured.
- The heading is in the channel's `default_language`.
- Contains up to `BACKLINK_MAX` watch URLs to real target videos.
- Rendering is idempotent: re-rendering replaces the block, never duplicates it.
- The house-format title path re-appends the block after its rewrite (§1.6).

#### 3.5 Adoption test

In Slice 3 the agent runs as a challenger against the Slice 1–2 pipeline, on the same channel, split by hash. It's adopted for a lever only if both hold:
- **(a)** Traces show tool choice genuinely varies per video.
- **(b)** Its verdicts beat the pipeline's.

Otherwise that lever stays a pipeline. This is the §3.4 falsifiability test of the 2026-09-22 spec, turned into a gate.

#### 3.6 Niche reference (Slice 3)

The replacement for `search_competitors`. Only the agent's title work reads it, so it is built with the agent, not earlier.

- **Module.** `app/niche_reference.py`. Move `derive_niche_queries` and `_sample_competitors` out of `app/reflection.py` into it rather than rewriting them, so nothing depends on the frozen reflection module.
- **Queries.** Seed from the channel's own search terms if Phase A3 found them readable (measured). Otherwise use `audit_configs.niche_queries` (LLM-derived, already stored).
- **Job.** `niche_reference_refresh`, per channel with `agent_enabled`, every `NICHE_REFERENCE_REFRESH_DAYS`. Runs under its own `JobBudget` of `NICHE_REFERENCE_QUOTA_BUDGET` units and never draws on the apply reserve. For each query: `search.list` (100u), then `videos.list` (1u per 50) for the top results' titles and view counts.
- **Summary.** One `chat_json` call summarizes common title patterns. It obeys the `default_language` rule and states plainly that this is **what ranks, not what gets clicked**.
- **Storage.** The summary, build date, queries used, and raw results are all kept (§7), so any agent run can be traced back to exactly what it saw.
- **Earns its place.** Trajectories record whether the agent called the tool. The §3.5 adoption test compares runs that used it with runs that didn't. If it's never called or makes no difference, stop the job. That same evidence decides whether `search_competitors` ever returns (§0.5 item 7).

---

### 4. Playlist placement

As 2026-09-22 §4, with these changes:

- **Recommend-only first.** Proposals go to `playlist_proposals`, with the Jev fit check replacing `_llm_judge`.
- **Frozen writers (§0.5 item 8) stay frozen** until Slice 2 ships the measured replacement.
- **Re-embedding is a Phase B task,** not a Slice 2 pre-req.
  - Embed one consistent input for every video under a new `model_version`.
  - Recalibrate `PLAYLIST_JOIN_HIGH` / `PLAYLIST_JOIN_LOW` / `PLAYLIST_LEAVE` on the new distribution, per channel rather than process-global.
  - Until done, embeddings are not used for any candidate generation.
- Auto-apply of adds is flipped per channel only after sustained trustworthy verdicts. New-playlist creation and deletes stay human-confirmed.

---

### 5. Playbook (step 8)

As 2026-09-22 §5:
- A per-lever structure in `channels.playbook_json`, rebuilt weekly past a floor and exposed as the `get_channel_playbook` tool.
- It respects `default_language` and is stated as correlational.

**Additions:**
- **Inputs:** treated-vs-holdout verdicts (§1.3) and measured human edits (§1.4), weighted equally.
- **Commitment:** the §1.5 rule.
- **Once it exists,** the playbook also feeds triage (step 2), not just the agent.
- **Retirement:** `reflection.py` is retired when the playbook ships. Its shadow and champion/challenger scaffolding may be reused for the §3.5 test.

---

### 6. Build order

| Stage | Contents | Exit gate |
|---|---|---|
| **Phase A: gates** | Pause Midas title autopilot. Probes (traffic source, Short link field, search terms). Freeze unmeasured writers. Haryanvi `default_language`. Honest strategy stamp. Live numbers. Fix silent job failures, deploy the health-scorer fix, close quota gaps. Mark old specs superseded. See Part 1. | Findings doc answers every probe question with raw evidence; go/no-go recorded per lever |
| **Phase B: plumbing** | Traffic-source ingestion. `interventions` table. Holdout assignment. Human-edit ledger. Warm filter. Re-embed. `decision_log` for Jev shadow. `app/decide.py`. | One channel shows a week of traffic-source data and at least one detected human edit |
| **Slice 1: backlinks + no change** | Tick routing (§6.1) **before** autopilot is re-enabled. Rules triage, pipeline step 3, code checks, canonical block, apply, weekly measurement with holdout. Jev triage/targets/checks in shadow. | First weekly verdicts written, treated vs holdout |
| **Slice 2: playlists + Short links** | Recommend-only proposals and team queue. Jev goes live where shadow beat rules. | Proposals confirmed and measured; Short links flowing through the human ledger |
| **Slice 3: agent challenger + titles** | Hand-rolled loop, tools, `decline`, writer bake-off, niche reference (§3.6). Title lever enabled. | §3.5 adoption decision per lever, including whether the niche reference is kept |
| **Slice 4: playbook** | Weekly per-lever distillation; retire `reflection.py`. | Playbook changes triage or agent choices measurably vs no-playbook |
| **Slice 5: fleet** | Per-channel quota shares via `JobBudget`; per-channel auto-apply flips; widen beyond the rollout channel. | Second channel live without regressions |

Every stage ships to one channel first, gets about a week of watching, then widens.

#### 6.1 Autopilot during the build

- **Human SEO on the other channels never stops.** It's the benchmark, and from Phase B it is logged (§1.4).
- **Midas title autopilot on its channel is paused from Phase A** (Part 1, task A0), by setting `channels.autopilot_enabled = false`. Not the pause mechanism: `autopilot_paused_reason` has a cooldown and can resume on its own. `measurement_enabled` stays on so already-applied audits finish their windows. Shorts uploads continue if their flag is independent of `autopilot_enabled` (Part 1 A0 checks this).
- **Why pause.** Continuing would keep making forced rewrites on mostly dormant videos, lock warm videos in 21-day windows just before Slice 1 needs them, and muddy the before-period of the first backlink measurements.
- **Resume = Slice 1, and it needs code first.** Re-enabling `autopilot_enabled` restarts the old `audit_video` path unless the tick is changed. So Slice 1 must ship this before the flag flips back on: when a channel has `agent_enabled`, every tick goes through the warm filter and triage (§2.1–2.2). The title lever is disabled until Slice 3, so `audit_video` cannot run on that channel before then.
- **Optional handover.** During the pause, the SEO team may run the Midas channel. They keep a simple log (video, what changed, date) because the Phase B edit detection isn't built yet and can only reconstruct approximate dates afterwards. They hand the channel back when Slice 1 starts, so the two never edit the same videos.

---

### 7. Data model (Phase B)

- **`interventions`**
  - `id bigserial pk, video_id → videos, channel_id → channels`
  - `lever text` (`backlinks|playlist|short_link|title`)
  - `origin text` (`midas|human`), `arm text` (`treated|holdout|n/a`)
  - `status text`, `payload jsonb`, `before_state jsonb`
  - `audit_id → audits` (title lever only), `strategy_version → audit_strategies`
  - `triage_json jsonb` (rules choice, Jev choice and probabilities)
  - `applied_at`, `detected_at` (human), `measurement_status`, `measurement_result jsonb`, `created_at`
  - `audits` stays intact. Title interventions reference it.
- **`video_traffic_source_daily`**
  - `video_id, channel_id, date, source_type, source_detail (nullable), views, est_minutes_watched`
  - Columns are **provisional until Phase A1**, which defines the real report shape.
- **`decision_log`**
  - `id, decided_at, question_set_version, subject (video/pair/candidate), rules_answer, jev_answer, jev_probs jsonb, used text (rules|jev), intervention_id`
- **`channels`**
  - `agent_enabled bool default false`
- **Niche reference (Slice 3)**, on `channels`:
  - `niche_reference_json jsonb` (summary + example titles), `niche_reference_built_at timestamptz`, `niche_reference_inputs jsonb` (queries used + raw results)
- **Status vocab**
  - New values (`declined`, `holdout`, `insufficient_data`, intervention statuses) go into `app/status_vocab.py`, its mirror, and the guard test.

### 8. Config (new, starting values, tune from data)

| Setting | Start | Notes |
|---|---|---|
| `WARM_MIN_IMPRESSIONS` | 500 | Same as `MIN_IMPRESSIONS`. Revisit after Phase A live numbers |
| `WARM_WINDOW_DAYS` | 28 | Ingested data-days |
| `WARM_EXPLORE_PCT` | 0.10 | Picks from the non-top warm pool |
| `HOLDOUT_PCT` | 0.20 | Per lever, stable hash |
| `BACKLINK_MAX` | 3 | Start conservative (spam/ToS risk) |
| `BACKLINK_MIN_CANDIDATES` | 2 | Below this, triage says `no_change` for backlinks |
| `PLAYBOOK_MIN_VIDEOS_PER_PATTERN` | 5 | §1.5 |
| `AGENT_MAX_TURNS` | 12 | Slice 3; tune from traces |
| `WRITER_MODEL` | = `AUDIT_MODEL` | Slice 3 bake-off replaces it |
| `DECIDE_BACKEND` | `llm` | `jev` once access is set up; `llm` is the fallback |
| `NICHE_REFERENCE_REFRESH_DAYS` | 90 | Slice 3 |
| `NICHE_REFERENCE_QUOTA_BUDGET` | 500 | Per refresh; about five searches |

`strategy_version` is derived, not a static env string. It covers prompt source, `AUDIT_MODEL`, `WRITER_MODEL`, and the decision question-set version (Phase A6).

### 9. Testing

As 2026-09-22 §7, adapted:

- **Loop.** Fake `openrouter.chat_tools`: turn cap → quarantine, tool error → readable, invalid submit → rejection, `decline` → zero quota.
- **Pipeline.** Warm filter excludes dormant and in-window videos. Holdout assignment is stable and never applies. Rules triage is deterministic.
- **Renderer.** Idempotent, capped, valid URLs, language heading, survives a title rewrite.
- **Decide.** `decide()` with the `llm` backend and a fake Jev backend return the same typed shape. Shadow decisions are logged, never used, while shadow is on.
- **Human ledger.** Sync-diff detects an added description link and a new playlist membership; ignores Midas's own changes.
- **Tick routing.** With `agent_enabled` on, a tick never calls `audit_video` while the title lever is disabled; with it off, behaviour is unchanged.
- **Niche reference.** Refresh stops at its budget, never touches the apply reserve, stores its inputs, and the tool returns empty with a reason when nothing is built.
- **Offline and tracing guards** stay green. Live probes are marked `live`.

### 10. Risks

1. **Backlink measurability.** §1.2 outcomes (a)/(b)/(c). Decided in Phase A, not assumed.
2. **Spam / ToS.** Caps, relevance checks, recommend-only playlists, one change per video per window.
3. **Weekly signals mislead.** Holdout plus distributional commitment.
4. **Jev is early-access.** It sits behind `decide()` with an LLM fallback. Nothing blocks on Jev availability. Its outputs aren't trusted until shadow results and the backtest justify them.
5. **Freezing reduces activity.** The frozen jobs made changes that may have been helping, unmeasured. Accept a dip in activity in exchange for measurements that mean something.

### 11. Open questions

1. Phase A probe outcomes (A1–A3). Everything in §1.2 branches on them.
2. The Jev check false-positive rate acceptable before checks block (§2.4). Measure on a human-reviewed sample in Slice 1.
3. Which channel is rollout #1. Candidates are the Haryanvi channel (after A5) or the Marathi probe channel. Pick the one with certified reach and the most warm videos, per the Phase A live numbers.
4. Whether human-run channels stay fully human during Slices 1–2 (recommended, so they serve as the benchmark) or get recommend-only suggestions.
5. Is the house format itself right? Out of scope here. The title lever's verdicts in Slice 3 are the first evidence.
6. Does the SEO team run the Midas channel during the pause (§6.1)? Optional; decide before Phase A starts.
