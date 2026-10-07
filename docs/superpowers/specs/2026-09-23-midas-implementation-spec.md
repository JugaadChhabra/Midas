# Midas — implementation spec: the discoverability agent

Date: 2026-09-23
Status: Part 1 done (exit gate passed 2026-10-06) · **Part 3 (Phase B) ready to build** (code merged or in PR; deploy and exit gate pending) · Part 4 (Slice 1) drafted 2026-10-07, owner decisions D1–D8 accepted 2026-10-07; ready to build once Phase B's exit gate passes · Part 2 approved design, amended 2026-10-06 from Phase A findings (§0.6)
Supersedes:
- `2026-09-22-discoverability-agent-spec.md`
- The separate 2026-09-23 discoverability and Phase A specs (merged here)
- As design sources: `CONTINUOUS_IMPROVEMENT_LOOP.md`, `PLAYLIST_OPTIMIZATION.md`, `plan.md` (see Part 2 §0.5)

All of the superseded docs above, plus `2026-08-26-tool-using-audit-agent-design.md` and the
`PHASE_2_TRACK2`/`TRACK4` drafts, were **deleted on 2026-10-06** once the `STATE.md` §9 rewrite
landed (Phase A exit gate). They're in git history, e.g. `git show 8981ec2:docs/plan.md`.

Diagram: `docs/midas-seo-agent-v2.excalidraw`. Step numbers (1–8) in Part 2 refer to it.
Ground truth used: `STATE.md` @ `bddd373`.

---

## How to use this document (read first)

This file has four parts, and they are used differently.

- **Part 1 is Phase A, now done.** It is kept as the record of what Phase A did; evidence is in `docs/PHASE_A_FINDINGS.md`.
- **Part 2 is the design.** It describes the whole target system and the order its stages arrive, amended by Phase A's findings (§0.6). **Do not implement anything from Part 2 directly.** That holds even where Part 2 describes code in detail.
- **Part 3 is the build task: Phase B.** It is the only part to implement now, in its run order.
- **Part 4 is Slice 1, drafted.** Its owner decisions (D1–D8) were accepted on 2026-10-07. It becomes "ready to build" when Phase B's exit gate passes.

**After Phase A's exit gate**, the Phase B build section is written into this file as a new Part, using Phase A's findings. Each later slice follows the same pattern. Part 2 is updated if a finding changes the design. At any time, exactly one Part is marked "ready to build."

---

## Part 1 — Phase A: gates (done 2026-10-06)

> **Done.** Exit gate passed 2026-10-06. Rollout channel #1: Marathi `UCr5-YUqBiW7PUmeAtxUWuRg`. Evidence, per-task
> records and the conclusion are in `docs/PHASE_A_FINDINGS.md`. Part 1 is kept as the record of what was asked.

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

### 0.6 Amendments from Phase A (decided 2026-10-06)

Phase A found every routing lever **measurable (outcome (a))**, but carrying **≈0 traffic today** on Marathi:
<0.05% of views between them. The traffic is algorithmic: Mixes 45%, Shorts feed 19%, Suggested 19%, Browse 7%,
Search 1.1%. At least 23% of suggested views come from our own other channels, and judged title verdicts were 64
wins vs 106 regressions. Evidence: `docs/PHASE_A_FINDINGS.md` ("Phase A conclusion" and A1–A7). The owner accepted these
amendments; the sections they touch are edited in place and marked **(P#)**.

| # | Amendment | Changes |
|---|---|---|
| P1 | Slice 1 (backlinks) runs as a **time-boxed experiment with a stop rule**: if treated pairs' attributable views don't beat holdout after `BACKLINK_EXPERIMENT_WINDOWS` weekly windows, stop the lever | §1.2, §6, §8 |
| P2 | Backlink (and Short-link) **candidates may come from any of our channels**, restricted to channels that already exchange suggested traffic with the source channel | §2.3, §2.4 |
| P3 | **Slice 2's playlist work shrinks to one test:** can a curated `PL…` playlist earn `playlist_starts` at all? The rest of §4 is deferred until it can | §4, §6 |
| P4 | **Short → video links are recommend-only, permanently.** The Data API can't read or set them (A2) | §2.5, §6 |
| P5 | When the title lever returns (Slice 3), its **objective is browse/suggested click-through, not search keywords**, and the house format is unproven. **Reverting the 106 regressions was considered and deferred** (owner, 2026-10-06) | §3.3, §11.5 |
| P6 | **Traffic-source ingestion is specified:** `channel_traffic_source_a3` + `playlist_traffic_source_a2`, numeric codes, newest report wins for restated days, 2-day lag, aggregate out `country_code` / `subscribed_status` / `live_or_on_demand` before storage | §7, Part 3 |
| P7 | **Set `default_language` on the six channels without one** (Hindi, Bhojpuri, Malayalam, Tamil, Rajasthani, Telugu), with API-code mappings for the codes YouTube doesn't take | Part 3 |

### 1. Measurement and learning loop

#### 1.1 Cadence

- The work rate is unchanged: autopilot `tick()`.
- Measurement and the playbook rebuild run **weekly**.
- **Reporting lag.** CTR and reach CSVs arrive 1–6 days late (`app/config.py:193-194`). A "7-day window" therefore yields its verdict around day 9–13. Plan for that; don't hide it.

#### 1.2 Signal per lever

| Lever | Primary indicator | Source | Status |
|---|---|---|---|
| Description backlinks | Views arriving at the target with `traffic_source_detail` = the source video (type 7 Suggested) | `video_traffic_source_daily` | **(a), confirmed by A1.** Today ≈0: 1,804 links → 4 views/day |
| Playlist placement | Views with type 14/18 detail = our `PL…` id; `playlist_starts` per playlist × video × day | `video_traffic_source_daily`, `playlist_traffic_daily` (P6) | **(a), confirmed by A1.** On-demand playlist detail returns 400, so the Reporting API is the sensor |
| Short → video link | Long video's views with type 32 (Related video) detail = the Short | `video_traffic_source_daily` | **(a), confirmed by A1.** Not automatable (A2) |
| Title | CTR vs a comparable window | `video_reach_daily` | Built |

**Phase A result: (a) for every routing lever.** A link's views are attributable per pair, but the
algorithm's own suggestions of B next to A land in the same type-7 rows, so a pair's views count only as the
treated arm's change minus the holdout arm's (§1.3), never raw. **(P1)** Because today's pair-level traffic is
≈0, Slice 1 is an experiment: if treated pairs' attributable views don't beat holdout after
`BACKLINK_EXPERIMENT_WINDOWS` weekly windows, the backlink lever stops and the result is recorded as a finding.

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

**(Slice 1, 2026-10-07)** For backlinks the floor is on the **source** video, not on the pair: `LEVER_MIN_SOURCE_VIEWS` total views in the post window. Nobody can click a link on a video nobody watched, and pair views near zero are the expected result, not a reason to discard a row (Part 4 S1.6).

---

### 2. Pipeline (diagram steps 1–5)

#### 2.1 Step 1: pick a video (code, no AI)

The warm filter is added to `next_audit_candidate` (SQL) and to its in-app parity fallback.

- **Eligible:** public, not an episode (`is_episode`), on a channel with `agent_enabled`, certified reach (`reach.certify`), and **impressions ≥ `WARM_MIN_IMPRESSIONS` over the trailing `WARM_WINDOW_DAYS` of ingested data-days**.
- **Excluded:** videos with an active intervention (§1.6). This replaces the current awaiting/measuring exclusion.
- **Also excluded (Slice 1, 2026-10-07),** in the SQL and its in-app parity fallback (Part 4 S1.4):
  - videos with any Midas intervention created within `TRIAGE_COOLDOWN_DAYS`. A `declined` (`no_change`) row isn't active, so without the cooldown the same top video would be offered again on the next tick;
  - for an experiment's duration, videos that already have an intervention for that lever, of either arm. Each video is in the experiment once.
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
| Backlinks | Candidates = top performers above the floor **on the source's channel or a sibling channel (P2)**, filtered by tag/title overlap (embeddings after re-embed, §4). A sibling is one of our channels that already sends suggested traffic to the source channel, measured over the trailing 28 days of the source channel's own `video_traffic_source_daily` rows (at least `SIBLING_MIN_VIEWS`). **(Slice 1, 2026-10-07)** A sibling counts only if it is itself in `TRAFFIC_INGEST_CHANNELS`: a link A→B is measured from B's channel's report, so a target on an un-ingested channel can't be measured. `TRAFFIC_INGEST_CHANNELS` is widened to Marathi's siblings before Slice 1 launches, so their pre-windows exist (Part 4 D1). Jev answers "would a viewer of A plausibly watch B next?" per pair. Keep top `BACKLINK_MAX`. | Agent gathers context and chooses |
| Playlist | Candidates from playlist inventory. Jev fit judgment replaces `playlists._llm_judge`. Written to `playlist_proposals`. | Agent |
| Short link | Jev picks the best long video for each Short. Queued for the team. | Agent |
| Title | Existing `audit_video` path, only when triage says `title` | Agent with writer model (§3.3) |

#### 2.4 Step 4: checks (code first, then Jev)

- **Code (hard rules):**
  - Every link target is a public video on the source's channel or one of its sibling channels (P2, §2.3), and not the video itself.
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
- **Rollout.** **(Slice 1, 2026-10-07)** Jev checks are not in Slice 1 (Part 4 D7): the backlink block is rendered by code from our own titles, so language and appropriateness are fixed, and relevance is the shadow next-watch question (Part 4 S1.5). Where Jev checks do run, they start in shadow alongside the code checks, and start *blocking* once their false-positive rate on human-reviewed samples is acceptable (§9).

#### 2.5 Step 5: apply

- **Backlinks.** **(Slice 1, 2026-10-07)** Not `build_update_payload`, which always sends category, language and `status` fields and takes title and tags from the caller. The write fetches the live snippet with `videos.list` (1u), renders the canonical block (§3.4) onto the live description, and sends `videos.update` with `part=snippet` only, sending the fetched snippet back with only `description` replaced. Charged through the existing ledger gate (`quota.APPLY`, 51u) (Part 4 S1.3).
- **Playlist.** Recommend-only (Slice 2). Confirmed proposals apply via `yt_playlist_items_insert` (50u).
- **Short link.** Recommend-only to the team, **permanently (P4)**: Phase A2 found no readable or writable API field. The team sets it in Studio. It enters the §1.4 human ledger when the team applies it, and it's measured through type 32.
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

**Objective (P5).** The title lever optimises browse/suggested click-through, not search keywords: search was 1.1% of Marathi's views, and viewers search Hindi phrasings of Marathi rhymes (A3). The house format is unproven: the old rewrites scored 64 wins vs 106 regressions (A7). The 106 regressions stay applied for now (owner, 2026-10-06).

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

- **(P3) One test first.** Our `PL…` playlists got 50 of 259,868 Marathi views (A1.1), and YouTube's Mixes 45%. Slice 2's playlist work is one measured test: curate a small number of playlists on the rollout channel and see whether they earn `playlist_starts` at all. The rest of this section waits until they do.
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
| **Phase B: plumbing** | See **Part 3**. Traffic-source ingestion (P6). `interventions` table. Holdout assignment. Human-edit ledger. Warm filter. Re-embed. `decision_log` for Jev shadow. `app/decide.py`. Missing `default_language` (P7). | One channel shows a week of traffic-source data and at least one detected human edit |
| **Slice 1: backlinks + no change** | Tick routing (§6.1) **before** autopilot is re-enabled. Rules triage, pipeline step 3, code checks, canonical block, apply, weekly measurement with holdout. Fleet candidates (P2). Jev triage/targets/checks in shadow. **Time-boxed (P1).** | First weekly verdicts written, treated vs holdout. **Stop rule (P1):** no lift over holdout after `BACKLINK_EXPERIMENT_WINDOWS` windows → the lever stops |
| **Slice 2: playlists + Short links** | **One playlist test (P3).** Short links recommend-only to the team, permanently (P4). Jev goes live where shadow beat rules. | The playlist test answered (do curated playlists earn starts?); Short links flowing through the human ledger |
| **Slice 3: agent challenger + titles** | Hand-rolled loop, tools, `decline`, writer bake-off, niche reference (§3.6). Title lever enabled, **aimed at browse/suggested CTR (P5)**. | §3.5 adoption decision per lever, including whether the niche reference is kept |
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
- **`video_traffic_source_daily`** (P6; shape from Phase A1.1)
  - `video_id, channel_id, date, source_type smallint, source_detail text not null default '', views, engaged_views, watch_time_minutes, report_id, ingested_at`
  - Unique `(video_id, date, source_type, source_detail)`. Source: `channel_traffic_source_a3`, summed over `country_code`, `subscribed_status` and `live_or_on_demand` before storage.
  - `source_type` stores YouTube's numeric code; names come from a code table in code (A1.1 has it).
- **`playlist_traffic_daily`** (P6)
  - `playlist_id, video_id, channel_id, date, source_type smallint, source_detail text not null default '', views, playlist_starts, watch_time_minutes, report_id, ingested_at`
  - Unique `(playlist_id, video_id, date, source_type, source_detail)`. Source: `playlist_traffic_source_a2`, aggregated the same way.
  - **Restatements:** YouTube re-issues some data dates. The newest report for a (job, data date) replaces that date's rows; it is never added to them.
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
| `BACKLINK_EXPERIMENT_WINDOWS` | 3 | P1 stop rule: weekly windows before the lever stops if treated ≤ holdout |
| `TRAFFIC_INGEST_CHANNELS` | the rollout channel | P6 / Part 3 B1: channels whose traffic-source reports are ingested |
| `SIBLING_MIN_VIEWS` | 100 | P2: trailing-28-day suggested views between two of our channels, in either direction, for them to count as siblings |
| `BACKLINK_MIN_LIFT` | 1.0 | Slice 1, 2026-10-07: attributable views per treated video per week that cumulative lift must reach to beat holdout (Part 4 D6) |
| `BACKLINK_APPLY_ENABLED` | false | Slice 1, 2026-10-07: kill switch for backlink writes to YouTube |
| `TRIAGE_COOLDOWN_DAYS` | 7 | Slice 1, 2026-10-07: §2.1 pick exclusion after any Midas intervention |
| `LEVER_MIN_SOURCE_VIEWS` | 100 | Slice 1, 2026-10-07: §1.7 floor, on the source's post-window views |
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

1. ~~Phase A probe outcomes (A1–A3).~~ **Answered 2026-10-06:** (a) for all three levers; Short links not automatable; search terms available (§0.6).
2. The Jev check false-positive rate acceptable before checks block (§2.4). Measure on a human-reviewed sample in Slice 1.
3. ~~Which channel is rollout #1.~~ **Marathi `UCr5-YUqBiW7PUmeAtxUWuRg`** (owner, 2026-10-06). Haryanvi has no reach data.
4. Whether human-run channels stay fully human during Slices 1–2 (recommended, so they serve as the benchmark) or get recommend-only suggestions.
5. Is the house format itself right? **First evidence (A7): 64 wins vs 106 regressions under the old rewrites.** Treated as unproven (P5); Slice 3's verdicts decide.
6. ~~Does the SEO team run the Midas channel during the pause?~~ Not needed: the owner had already turned title autopilot off around 2026-09-23, and no handover was arranged.

---

## Part 3 — Phase B: plumbing (ready to build)

**Purpose.** Build the sensors and the record-keeping that Slice 1 needs, on one channel first, **without
changing anything on YouTube.** Phase B adds no levers and no applies. Its only YouTube calls are reads,
plus creating Reporting API jobs (a subscription, not a change to the channel).

**Rollout channel:** Marathi `UCr5-YUqBiW7PUmeAtxUWuRg` (Part 1 conclusion). Everything new is enabled for
it first. Widening to other channels is a config change, not new code.

**Inputs.** Phase A findings (`docs/PHASE_A_FINDINGS.md`) and Part 2 as amended in §0.6. Where this Part
and Part 2 disagree, this Part wins for Phase B, and Part 2 is corrected in the same change.

**Schema discipline.** Phase B adds tables. Every migration follows the repo rules:
- Apply the migration on the office machine.
- Reload PostgREST's schema cache with `docker compose restart postgrest rest`, or app writes fail with PGRST204.
- After verifying the migration, refresh the NAS snapshot (`CLAUDE.md`).

All three steps are listed in B9.

### Run order

1. **B1: traffic-source ingestion first.** The exit gate needs a week of its data, so it should start
   collecting as early as possible.
2. **B2, B3:** interventions with holdout, then the human-edit ledger, which writes interventions.
3. **B4, B5, B6:** the warm filter, `decide()` with `decision_log`, and the scoped re-embed. These are independent of each other.
4. **B7, B8:** missing languages (P7) and the `refresh-stats` 401 fix.
5. **B9:** deploy and verify. **B10:** docs. Then the exit gate.

### B1 — Traffic-source ingestion (P6)

**Problem.** The traffic-source reports exist (Phase A1.1), but nothing stores them. Slice 1's measurement,
P2's sibling channels, and the human-edit ledger's measurements all read from them.

**Change.**
1. **Jobs.** For each channel in `TRAFFIC_INGEST_CHANNELS` (default: the rollout channel), ensure Reporting API
   jobs exist for `channel_traffic_source_a3` and `playlist_traffic_source_a2`. Reuse the
   `ensure_reach_job` pattern in `app/reporting_client.py`, generalised to a report type. Marathi's two jobs
   already exist (created 2026-09-29) and must be found, not duplicated.
2. **Ingest.** A daily job `traffic_poll` at 06:30 UTC (after `reporting_poll`, which it doesn't depend on)
   that downloads every report not yet ingested and writes `video_traffic_source_daily` and
   `playlist_traffic_daily` (Part 2 §7):
   - Sum over `country_code`, `subscribed_status` and `live_or_on_demand` before writing.
   - Store `source_type` as the numeric code. Keep a code→name table in code, copied from the A1.1 table,
     with its source URL.
   - **Restatements:** when a newer report arrives for a (job, data date) that's already ingested, replace
     that date's rows for the channel. Never add to them. Record which report a row came from. The reach
     ingester already does latest-wins per data date (`app/reporting_poll.py` `_ingest_report`); reuse it,
     don't re-implement it. `ensure_reach_job` handles only the reach type today, so generalise it, keeping
     the reach behaviour.
   - Record each ingested report in the existing `reporting_reports_ingested` ledger.
3. **Health.** Same failure semantics as `reporting_poll`: a channel crash fails the run; per-report errors
   are judged by `job_status.item_error_verdict`.
4. **Size.** Log rows written per channel per day. A1.1 saw about 52k raw rows a day for Marathi before
   aggregation. Record the aggregated count in the findings doc after the first week, and decide retention
   then. No retention policy in Phase B.

**Tests.**
- Aggregation sums across the dropped dimensions.
- A restated date replaces rather than adds.
- An already-ingested report is skipped.
- Codes map to names.
- An existing job is found, not recreated.
- A malformed report fails only that report.

**Acceptance.** Tests green. On the office machine, Marathi has `video_traffic_source_daily` rows for every
data date from the backfill to the frontier minus 2 days, and `/health/jobs` shows `traffic_poll` `success`.

### B2 — `interventions` table and holdout assignment

**Change.**
1. Migration for `interventions` exactly as Part 2 §7, plus `channels.agent_enabled bool not null default false`
   (Part 2 §7). The column is added now so B4 and Slice 1 have it. Nothing sets it true in Phase B. New status values go into `app/status_vocab.py` and its
   guard test: `declined`, `holdout`, `insufficient_data`, plus the intervention lifecycle statuses
   (`planned`, `applied`, `measuring`, `judged`, `cancelled`).
2. `app/interventions.py` with:
   - `assign_arm(video_id, lever) -> 'treated' | 'holdout'`: a stable hash of (video_id, lever) against
     `HOLDOUT_PCT`.
   - `record(...)`.
   - `active_for(video_id)`, which enforces §1.6: at most one active Midas intervention per video.
3. Nothing in Phase B creates `midas` interventions. They start in Slice 1. B3 creates `human` ones.

**Tests.**
- The arm is stable across processes and calls.
- The holdout share is about `HOLDOUT_PCT` over 10k ids.
- Different levers give independent arms.
- A second active intervention on a video is rejected.
- The status vocab guard test covers every new value.

**Acceptance.** Tests green; the migration is applied on the office machine.

### B3 — Human-edit ledger (Part 2 §1.4)

**Problem.** The SEO team edits other channels by hand, and that's our benchmark. Nothing records what they change.

**Change.**
1. **Description links.**
   - When sync rewrites a video's description, diff the links to our videos before and after, using the
     same extraction as Phase A1.3 but tightened to real 11-character IDs.
   - For each link that wasn't there before, record an intervention: `origin='human'`, `lever='backlinks'`,
     `arm='n/a'`, `detected_at = now`, with the source and target in `payload`.
   - Skip any change Midas made itself. In Phase B that's every apply; from Slice 1, it's every
     intervention with `origin='midas'`.
2. **Playlist memberships.** When the playlist membership walk sees a video newly added to one of our playlists
   that Midas didn't add, record `lever='playlist'` the same way.
   - Tell "Midas added it" from `playlist_assignments` and executed `playlist_proposals`, **not** from
     `playlists.origin`: discovery-created playlists are stored as `origin='inherited'`
     (`app/playlist_discovery.py`), so `origin` can't separate Midas playlists from human ones.
   - The walk runs only inside `playlist_reconcile`, for `PLAYLIST_RECONCILE_CHANNELS`. Marathi is in the
     default allowlist. Membership detection for other channels needs them added there.
3. **Short links** can't be read (A2), so the ledger can't see them. The team logs them by hand, for example in
   a sheet. That process is out of scope for code.
4. **Detection timing.** Edits to old videos are seen only by a full sync, which runs every 3 days
   (`FULL_SYNC_INTERVAL`). Record `detected_at`, not when the edit happened, and say so in the row.

**Tests.**
- An added link creates one intervention.
- An unchanged description creates none.
- A removed link is recorded in the payload but creates no intervention.
- A Midas apply creates none.
- A new playlist membership is recorded.
- Detection is idempotent: a rerun doesn't duplicate.

**Acceptance.** Tests green. After deploy, at least one human intervention exists on any channel. That's an
exit-gate item: the SEO team edits continuously, so a week is enough.

### B4 — Warm filter (Part 2 §2.1)

**Change.**
- A function and SQL pair that return a channel's eligible pool: public, not an episode, certified reach,
  impressions ≥ `WARM_MIN_IMPRESSIONS` over the trailing `WARM_WINDOW_DAYS` ingested data days, and no active
  intervention (B2). Ordered by impressions, with a `WARM_EXPLORE_PCT` random share from the rest of the pool.
- Add it next to `next_audit_candidate`, with a parity test between SQL and Python, as the existing RPCs do.
  **Don't wire it into the tick.** That's Slice 1's tick routing.

**Tests.** It excludes dormant, episode, private and in-intervention videos; the explore share is about right;
SQL and Python agree.

**Acceptance.** Tests green. On the office machine, Marathi's pool size is recorded in the findings doc. Expect it
near A7's 566, but not equal: A7 used 30 *calendar* days, while the filter uses `WARM_WINDOW_DAYS` *ingested*
data days, and it also excludes episodes and in-intervention videos. `agent_enabled` isn't part of B4's filter;
Slice 1's tick routing checks it.

### B5 — `app/decide.py` and `decision_log`

**Change.**
- `decide(question_set, subject, context) -> Decision`: a typed answer plus probabilities.
- Two backends behind `DECIDE_BACKEND`:
  - `llm`, the default, via `openrouter.chat_json`.
  - `jev`: a stub that raises `NotConfigured` until access exists.
- Shadow mode: log both the rules answer and the backend's answer to `decision_log` (Part 2 §7), use only the
  rules answer, and stamp the `question_set_version`. It feeds the A6 strategy stamp's
  `DECISION_QUESTION_SET_VERSION`, replacing the placeholder.

**Tests.** Both backends return the same typed shape; shadow decisions are logged and never used; the jev stub
fails closed to the rules answer; the question-set version appears in both the log row and the strategy stamp.

**Acceptance.** Tests green; the migration is applied.

### B6 — Re-embed, scoped (Part 2 §4)

**Change.**
- Embed one consistent input (title + description + tags, the same recipe for every video) under a new
  `model_version`, for the rollout channel and its P2 sibling channels. Siblings come from B1's data; until a
  week exists, the rollout channel alone.
- `video_embeddings` already has `model_version`, so no schema change is needed. **Use a new version value.** The
  existing value covers two different input recipes (title + transcript in one path, title only in another),
  so it can't identify an input and must not be reused.
- Recalibrate `PLAYLIST_JOIN_HIGH` / `PLAYLIST_JOIN_LOW` / `PLAYLIST_LEAVE` **per channel** on the new
  distribution, and store the result, not in process-global settings.
- Budget: estimate the OpenRouter cost before running, and record it. Run as a resumable one-off, not a
  scheduled job.

**Tests.** The input recipe is identical for every video; a rerun skips videos already embedded under the new
`model_version`; calibration is per channel.

**Acceptance.** Every warm Marathi video has a new-version embedding, and the calibration values are recorded.

### B7 — Missing `default_language` (P7)

**Change.**
- Owner sets, via `PATCH /auth/channels/{id}` or SQL: Hindi `hi`, Bhojpuri `bho`, Malayalam `ml`, Tamil `ta`,
  Rajasthani `raj`, Telugu `te`. Confirm each with the owner first, because Bhojpuri and Rajasthani audiences
  might prefer `hi`.
- In code: add `bho` and `raj` to `lang_display_name`, and to `_NON_ISO_639_1` in `app/youtube_metadata.py`
  (→ `hi`), following the `bgc` precedent and its comment.

**Tests.** Display names; the payload emits `hi` for `bho` and `raj`.

**Acceptance.** All 13 channels have a `default_language`, recorded in the findings doc.

### B8 — `refresh-stats` 401 fix

**Problem.** Two linked bugs, both seen on the Hindi channel on 2026-10-06:
- A token failing *during* the stats call returns 500, because only `youtube_for_channel` is wrapped.
- `video_sync`'s `routine_sync` catches `TokenExpiredError`, but `sync_channel` and `refresh_stats` are HTTP
  route functions that turn it into `HTTPException(401)` (`app/sync.py`). So an expired token **fails** the
  `video_sync` run instead of being skipped. The 2026-10-01 tests mocked `TokenExpiredError` directly, which
  hid this.

**Change.** Map a token failure anywhere in the call to `HTTPException(401, "token_expired")`, and make the
routine sync treat it as the expected skip.

**Tests.** A token failure mid-call returns 401. Using the **real** `sync_channel`/`refresh_stats` with a fake
YouTube client that raises the token error, the routine sync skips that channel and doesn't fail the run.

### B9 — Deploy and verify

**Steps (office machine).**
1. Apply the migrations.
2. Run `docker compose restart postgrest rest`.
3. Restart the app.
4. Check `/health/jobs` lists `traffic_poll`.
5. After its first run, record rows per day for Marathi.
6. Refresh the NAS snapshot once the migrations are verified.

### B10 — Docs

Update `STATE.md` for every task above. Record the findings-doc entries named in each acceptance line. Mark
Part 3 done, and write the Slice 1 Part from what Phase B found.

### Phase B exit gate

- Marathi has at least **7 consecutive data days** in `video_traffic_source_daily`, ingested by `traffic_poll`
  rather than by hand, and `/health/jobs` shows it `success`.
- At least **one human intervention** detected by B3 on any channel, with its row checked by hand against the
  video's description.
- B1–B8 are merged, tests green, and deployed; the migrations are applied; PostgREST is reloaded; the NAS snapshot is refreshed.
- `assign_arm` is stable, and `decide()` logs shadow decisions.
- The warm pool and the B1 storage size are recorded in the findings doc.

### Not doing in Phase B

- No applies, no tick routing, and no re-enabling of title autopilot. Those are Slice 1.
- No `midas` interventions.
- No Jev calls; the jev backend stays a stub.
- No retention policy for the traffic tables. Decide it from the first week's size.
- No widening beyond `TRAFFIC_INGEST_CHANNELS`, except as a deliberate config change.
- No reverting of the 106 regressions (P5: deferred).

### Review protocol

As Part 1: an independent clean-context review per task against this Part, and a phase review at the end listing
what was spec'd but not built and what was built but not spec'd, with a check of `STATE.md` §1, §3 and §4.

---

## Part 4 — Slice 1: backlinks + no change (drafted 2026-10-07; ready to build once Phase B's exit gate passes)

**Purpose.** Midas changes YouTube again, on one channel, with one lever, as a measured experiment. Each tick
picks a warm video and decides, by rules, whether it gets a code-rendered block of links to related videos
("backlinks") or nothing. A stable fifth of the videos chosen for the lever are held out unchanged. A weekly job
compares the two arms' attributable views. **P1 time box:** if the treated arm doesn't beat holdout after
`BACKLINK_EXPERIMENT_WINDOWS` weekly windows, the lever stops and the result is written up as a finding.

**Rollout channel:** Marathi `UCr5-YUqBiW7PUmeAtxUWuRg`, the only channel with `agent_enabled = true` in Slice 1.

**Inputs.** Phase B as built: `video_traffic_source_daily` (B1), `interventions` and `assign_arm` (B2), the
human-edit ledger (B3), `app/warm.py` (B4), `decide()` and `decision_log` (B5), the new-recipe embeddings and
`channels.playlist_thresholds` (B6). The Phase B findings (warm pool, B1 rows/day, the first human interventions)
are filled in at B10. Where this Part and Part 2 disagree, this Part wins, and Part 2 is corrected in the same
change. The corrections are listed under "Changes to Part 2" and were applied on 2026-10-07.

**Owner decisions.** Items marked **(D#)** point to the "Owner decisions" table at the end. The owner accepted
every recommendation on 2026-10-07.

### What Phase B found that shapes this Part

1. **A pair's views are only visible in the target's channel's report.** A link A→B shows up as rows with
   `video_id = B, source_type = 7, source_detail = A`. Those rows come from B's channel's
   `channel_traffic_source_a3`. A Hindi target linked from a Marathi video is therefore measurable only if Hindi
   is in `TRAFFIC_INGEST_CHANNELS`. P2's cross-channel candidates mean nothing until the sibling channels are
   ingested, and their pre-window needs a week of data before launch. **(D1)**
2. **A declined video isn't held.** `no_change` is recorded as a `declined` intervention, which is not an active
   status (`status_vocab.ACTIVE_INTERVENTION_STATUSES`). The B4 warm pool would offer the same top video again on
   the next tick. The pick needs a cooldown (S1.4).
3. **`build_update_payload` isn't description-only.** It always sends `categoryId` (Education), the language
   fields and `status.selfDeclaredMadeForKids`, and takes title and tags from the caller (`app/youtube_metadata.py`).
   A `videos.update` replaces the whole `snippet`, so anything omitted is deleted. Backlinks need their own write
   path (S1.3).
4. **`made_by_midas` knows only audits.** B3a's ledger would record Midas's own block as a human edit unless the
   check learns about `midas` backlink interventions (`app/human_edits.py`, which says so in its docstring).

### Run order

1. **S1.1, S1.2, S1.3** in parallel: candidates, the renderer, and the description-only write path.
2. **S1.4:** tick routing, triage and holdout, wiring the three together behind `BACKLINK_APPLY_ENABLED`.
3. **S1.5, S1.6:** the shadow next-watch question, and weekly measurement with the stop rule.
4. **S1.7:** deploy, preview, then enable writes (owner). **S1.8:** docs.

### S1.1 — Siblings and backlink candidates (Part 2 §2.3, P2)

**Change.** A new module, `app/backlinks.py`, with:
- `siblings(channel_id)`: our other channels whose videos sent the channel's videos at least `SIBLING_MIN_VIEWS`
  suggested (type 7) views over its trailing 28 ingested data days, read from the channel's own
  `video_traffic_source_daily` rows. A channel counts only if it is itself in `TRAFFIC_INGEST_CHANNELS`
  (finding 1). Ordered by views.
- `candidates(video)`: link targets for a source video, ranked. A target must be:
  - on the source's channel or a sibling;
  - public, not a Short, not the source itself, and not already linked from the source's description
    (`human_edits.video_links`);
  - warm on its own channel (≥ `WARM_MIN_IMPRESSIONS` over `WARM_WINDOW_DAYS` ingested data days, B4's measure);
  - similar to the source: cosine similarity on the B6 `model_version` ≥ the source channel's calibrated `join_low`
    (`channels.playlist_thresholds`). A target or source without a new-version embedding is skipped and counted.
  
  Rank by similarity, ties broken by impressions. Return at most `2 × BACKLINK_MAX` rows, each with
  `{video_id, channel_id, title, similarity, impressions}`. The caller keeps the top `BACKLINK_MAX`.
- Until a sibling channel has new-version embeddings (S1.7 step 2), its videos simply don't appear. No fallback to
  title overlap: two recipes in one comparison is the B6 mistake again.

**Tests.** Sibling threshold and the ingested-channels rule; each exclusion above; ranking; the skip count for
missing embeddings; reads paged through `app/rows.py`.

### S1.2 — Canonical backlink block (Part 2 §3.4)

**Change.** Pure functions in `app/backlinks.py`, with no I/O:
- `render(description, targets, language) -> str`. The block is a heading line followed by one line per target,
  `<target title> https://youtu.be/<id>`. The heading comes from a per-language table in code. Marathi's text is
  supplied by the SEO team **(D3)**, and a language missing from the table makes `render` refuse rather than fall
  back to English.
- **Placement (D2):** directly after the description's first line, so the links are above "Show more".
- `find(description)` and `strip(description)`: locate and remove the block by its exact heading line and the
  `youtu.be` lines under it.
- **Idempotent:** rendering onto a description that already has a block replaces it and never duplicates it.
- **Safe:** at most `BACKLINK_MAX` targets. If the result would exceed 5,000 characters, `render` refuses. The
  result passes `cap_description_hashtags` unchanged (the block adds no hashtags).

**Tests.** Idempotence; placement; the cap; the language table (including a missing language refusing); 5,000
characters; `strip(render(d)) == d`; a block that survives a re-render with different targets.

### S1.3 — Description-only apply, revert, and the ledger (Part 2 §2.5)

**Change.**
- `apply_backlinks(intervention)`:
  1. Fetch the live snippet with `videos.list` (1u). Use it, not the stored description: the team may have
     edited since the last sync.
  2. Render the block onto the live description.
  3. Send `videos.update` with `part=snippet` only, sending the fetched snippet back with only `description`
     replaced. Title, tags, category, language and `status` stay as YouTube had them.
  4. Store the live description in `before_state`, and the rendered description and targets in `payload`.
  5. Write the new description to `videos.description` so the next sync sees no diff.
  
  The write is charged through the existing ledger gate (`quota.APPLY`, 51u). Typed outcomes follow
  `app/apply_outcome.py`, and `DRY_RUN` is honoured.
- **Revert:** `POST /interventions/{id}/revert` removes the block with `strip` from the live description, using
  the same quota gate (409 when unaffordable) as `POST /audits/{id}/revert`. Status becomes `cancelled`, with the
  revert recorded in `payload`.
- **Ledger:** `human_edits.made_by_midas` also returns true when the description's links to our videos are exactly
  a `midas` backlinks intervention's targets (finding 4).

**Tests.**
- A fake YouTube client records the update body: only `description` differs from the fetched snippet, `parts` is
  `snippet`, and no `status` is sent.
- Live description vs stale stored description.
- Quota-gate refusal.
- A revert restores the original text.
- A sync after an apply records no human intervention.
- A human link added next to a Midas block still records one.

### S1.4 — Tick routing, triage and holdout (Part 2 §2.1, §2.2, §1.3, §6.1)

**Change.**
- **Routing.** In `autopilot.tick`, a channel with `agent_enabled` takes the agent path. That path calls
  `audit_video` **never**: the title lever is disabled until Slice 3. With `agent_enabled = false` the tick is
  byte-for-byte today's behaviour. A new predicate, `eligibility.can_run_agent(ch)`, is true when:
  - `can_audit(ch)` holds (enabled, not paused, language set);
  - `agent_enabled` is set;
  - the channel's reach is certified.
- **Pick.** The B4 warm pool, minus two further exclusions. Both go into the SQL and the Python twin, with the
  parity test extended:
  - any Midas intervention on the video created within `TRIAGE_COOLDOWN_DAYS` (finding 2);
  - for the experiment's duration, any video that already has a `backlinks` intervention of either arm. Each video
    is in the experiment once.
- **Triage.** `decide(TRIAGE, …)` with the context below. The rules answer is used, and the backend's answer is
  logged in shadow:
  - `has_related_block`: the description already links to one of our videos **(D5)**;
  - `backlink_candidates`: the count from S1.1;
  - the 28-day traffic mix by source type;
  - impressions and CTR;
  - the video's recent interventions.
  
  `decide()` returns the decision's log id, so the intervention's `triage_json` and `decision_log` link both ways.
  The stop rule (S1.6) makes triage answer `no_change` for backlinks once the lever has stopped.
- **Record.**
  - `no_change` → a `declined` intervention with the rationale.
  - `backlinks` → `assign_arm(video, 'backlinks')`.
    - **Holdout:** a `holdout` intervention whose `payload` carries the targets it *would* have got. That makes
      it measurable on the same pairs.
    - **Treated:** a `planned` intervention, then S1.3's apply. Success makes it `measuring` with `applied_at`;
      failure makes it `cancelled`, with the error in `payload`.
- **Cap.** The daily cap counts applied Midas interventions as well as applied audits (`_applies_today`).
  Holdout and declined rows don't count. Marathi's cap for the experiment is 40/day **(D4)**.
- **Kill switch.** `BACKLINK_APPLY_ENABLED` (default false). While false, treated rows stop at `planned` →
  `cancelled` with reason `apply_disabled`, and nothing is written to YouTube.
- **Preview.** `scripts/preview_backlinks.py --channel <id> --n 20` runs pick → triage → candidates → render
  read-only. It records nothing and prints each before/after description with its arm. The owner reads its output
  before writes are enabled (S1.7).

**Tests.**
- With `agent_enabled` on, a tick never calls `audit_video`; with it off, the tick is unchanged (Part 2 §9).
- The cooldown and the once-per-experiment rule, in SQL and Python, with the parity test.
- A holdout row records targets and never calls YouTube.
- Declined rows don't count toward the cap.
- A second active Midas intervention is impossible (B2's index).
- The kill switch writes nothing to YouTube.
- Triage is deterministic for a given context.

### S1.5 — Next-watch in shadow (Part 2 §2.3)

**Change.** A second question set in `app/decide.py`, `NEXT_WATCH`: "Would a viewer of A plausibly watch B
next?", answered yes/no. It's asked for each pair S1.1 returns. The rules answer is "yes, if similarity ≥ the
channel's `join_low`", the backend answers in shadow, and the result is stored on the intervention. Bump
`QUESTION_SET_VERSION`.

Part 2 §2.4's shadow **checks** (language, kid-appropriate, links relevant) are dropped from Slice 1 **(D7)**. The
block is rendered by code from our own titles, so language and appropriateness are already fixed, and relevance
is this question.

**Tests.** One log row per pair; the rules answer is used; the version bump reaches the strategy stamp.

### S1.6 — Weekly measurement and the stop rule (Part 2 §1.2, §1.3, §1.7, P1)

**Change.**
- **Pair views.** For an intervention with source A and targets B₁…Bₙ, its indicator over a window is the sum of
  `views` in `video_traffic_source_daily` where `video_id ∈ {Bᵢ}`, `source_type = 7` and `source_detail = A`.
- **Windows.** The as-of date d₀ is the `applied_at` date (treated) or the `created_at` date (holdout).
  - Pre window: d₀−7 … d₀−1. Post window: d₀+1 … d₀+7.
  - A window is complete when every target's channel has ingested data through d₀+7.
  - If the **source** had fewer than `LEVER_MIN_SOURCE_VIEWS` total views in the post window, extend the window
    once to 14 days. If it still falls short, mark the row `insufficient_data`. The floor is on the source
    because nobody can click a link on a video nobody watched; pair views near zero are the expected result,
    not a reason to discard a row.
  - Otherwise the row becomes `judged`, with `{pre, post, delta, source_views, window}` in `measurement_result`.
- **Weekly verdict.** A new table, `lever_verdicts`:

  ```
  channel_id, lever, week_start, n_treated, n_holdout,
  treated_mean_delta, holdout_mean_delta, lift, cumulative_lift, windows_judged,
  verdict, computed_at
  ```

  - `lift` = treated mean delta − holdout mean delta, over the rows judged that week.
  - `verdict` is directional (`helped|no_change|worse`, §1.5) against `BACKLINK_MIN_LIFT` **(D6)**.
  - A week with no judged holdout row writes no verdict.
- **Stop rule.** Once `windows_judged ≥ BACKLINK_EXPERIMENT_WINDOWS` and `cumulative_lift < BACKLINK_MIN_LIFT`,
  the lever is stopped for the channel (`stop_rule_triggered` on the row). Triage reads it (S1.4). Blocks already
  applied stay in place **(D8)**.
- **Human benchmark (§1.4).** `human` backlinks interventions on channels in `TRAFFIC_INGEST_CHANNELS` get the same
  pair measurement, with `detected_at` as d₀. They are reported in their own row, `lever = 'backlinks'`,
  `arm = 'n/a'`, and never mixed into the treated/holdout lift.
- **Job.** `lever_measurement`, weekly on Monday at 09:00 UTC (after `traffic_poll`), with `traffic_poll`'s failure
  semantics. Two read endpoints:
  - `GET /channels/{id}/interventions?lever=&status=` (paged);
  - `GET /channels/{id}/lever-verdicts`.

**Tests.**
- Pair views select the right source type and detail.
- Pre and post windows are as above.
- The completeness rule waits for a lagging target channel.
- The 14-day extension happens once, and then `insufficient_data`.
- The verdict arithmetic.
- The stop rule triggers exactly at the window count, and stopped triage returns `no_change`.
- Human rows never enter the lift.
- Restated traffic days are reread on the next run, because a judged row is recomputed while its window is within
  the restatement horizon.

### S1.7 — Deploy, preview, go live (owner, office machine)

1. **Before launch, during Phase B's exit-gate week:** widen `TRAFFIC_INGEST_CHANNELS` to Marathi's
   siblings **(D1)**, so their pre-windows exist by launch.
2. After deploying S1.1–S1.6, apply the migrations, run `docker compose restart postgrest rest`, and restart the
   app.
3. Run `scripts/reembed.py --estimate` for the sibling channels, record the cost, then do the real run.
4. Set `agent_enabled = true` and `autopilot_enabled = true` on Marathi, leaving `BACKLINK_APPLY_ENABLED` unset
   (false). Run `scripts/preview_backlinks.py` for 20 videos. **The owner and the SEO team read the rendered
   descriptions.**
5. Set `BACKLINK_APPLY_ENABLED=true` in the office `.env` and restart. Watch the first 10 applies by hand in
   Studio: the block, the title, the tags and the category are all unchanged apart from the block.
6. Refresh the NAS snapshot after each migration step is verified.

### S1.8 — Docs

- `STATE.md` updated for every task.
- The findings doc records:
  - the preview review;
  - the first weekly verdict;
  - at window `BACKLINK_EXPERIMENT_WINDOWS`, the stop-rule outcome, with the numbers, as a finding either way.
- Mark Part 4 done and write the Slice 2 Part.

### Config (new)

| Setting | Start | Notes |
|---|---|---|
| `BACKLINK_MAX` | 3 | Part 2 §8 |
| `BACKLINK_MIN_CANDIDATES` | 2 | Exists (B5) |
| `BACKLINK_EXPERIMENT_WINDOWS` | 3 | P1 |
| `BACKLINK_MIN_LIFT` | 1.0 | Attributable views per treated video per week. **(D6)** |
| `BACKLINK_APPLY_ENABLED` | false | Kill switch for YouTube writes |
| `SIBLING_MIN_VIEWS` | 100 | Part 2 §8, inbound only (finding 1) |
| `TRIAGE_COOLDOWN_DAYS` | 7 | Finding 2 |
| `LEVER_MIN_SOURCE_VIEWS` | 100 | §1.7 floor, on the source's post-window views |

### Exit gate

- The first weekly verdict is written for Marathi, treated vs holdout, with both arms non-empty.
- Every applied block was checked by hand on the first 10. No title, tag, category or language field changed.
- No human intervention was recorded for a Midas edit.
- `/health/jobs` shows `lever_measurement` `success`.
- At window `BACKLINK_EXPERIMENT_WINDOWS`, the stop rule's outcome is recorded in the findings doc, and Slice 2 is
  written either way.

### Not doing in Slice 1

- No titles, no playlists and no Short links. `audit_video` never runs on an agent channel.
- No channel other than Marathi gets `agent_enabled`.
- No Jev calls. The shadow backend is `llm` until access exists.
- No model-written text in the block.
- No automatic revert of applied blocks when the lever stops **(D8)**.
- No playbook. The weekly verdict table is its future input.

### Changes to Part 2 (applied 2026-10-07)

- **§2.1.** The pick also excludes recently triaged videos and, during an experiment, videos already in it.
- **§2.3.** A sibling counts only if its own traffic is ingested.
- **§2.4.** Jev checks are not in Slice 1 (D7).
- **§8.** `BACKLINK_MIN_LIFT`, `BACKLINK_APPLY_ENABLED`, `TRIAGE_COOLDOWN_DAYS` and `LEVER_MIN_SOURCE_VIEWS` added.
- **§1.7.** The window-extension floor is on the source's views.
- **§2.5.** The backlink write is a fresh `videos.list` plus a snippet-only `videos.update`, not
  `build_update_payload`.

### Owner decisions (decided 2026-10-07: all recommendations accepted)

| # | Question | Decision and why |
|---|---|---|
| D1 | Widen `TRAFFIC_INGEST_CHANNELS` to Marathi's siblings (A1.1: Hindi, English, Bhojpuri, Gujarati) before launch? | **Yes, during Phase B's exit-gate week.** Without it, cross-channel links are unmeasurable (finding 1) and there's no pre-window at launch. English also becomes the human benchmark (§1.4). Cost: storage, sized against B1's measured rows/day |
| D2 | Where the block goes | **After the first line, above "Show more".** A link nobody sees tests nothing. The alternative was the end of the description, where the team's existing links may already be |
| D3 | The heading text in Marathi | **The SEO team writes it.** Not guessed by code or a model |
| D4 | Marathi's daily cap during the experiment | **40/day** (≈2,040u at 51u, against ≤1.4k/day current burn and a 10k ceiling). At the default 10/day, the warm pool would take over three weeks, and the first windows would be thin |
| D5 | Videos that already link to our videos | **Skip them** (`no_change`). The team already pulled this lever there, and adding to it muddies the pair measure |
| D6 | What "beats holdout" means | **Cumulative lift ≥ 1 attributable view per treated video per week.** Any positive lift would pass on noise at today's ≈0 pair traffic. Below 1 view/video/week, a few hundred linked videos earn fewer views a week than Marathi gets in minutes, which isn't worth the spam risk |
| D7 | Drop Jev shadow checks from Slice 1 | **Yes.** The block is code-rendered from our own titles; relevance is covered by S1.5 |
| D8 | When the lever stops, revert the blocks? | **No, leave them.** They're harmless links, and reverting costs 51u each. The revert endpoint exists for any one that needs to go |

### Review protocol

As Parts 1 and 3: an independent clean-context review per task against this Part, and a slice review at the end
listing spec'd-but-not-built and built-but-not-spec'd, with a check of `STATE.md` §1–§4 and §7.
