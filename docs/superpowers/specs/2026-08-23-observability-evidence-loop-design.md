# Observability and the evidence loop

Date: 2026-08-23
Status: approved, not started
Supersedes nothing. Precedes a later phase on tool-using audits and LangGraph
orchestration, which this document deliberately does not design.

## Why this exists

Midas is not an agent and does not need to become one to get better. It is a
deterministic pipeline (`autopilot.tick()`) making eight one-shot LLM calls, with
a genuine outcome-measurement loop behind it. The loop is the valuable part and
it is the part that was broken.

An investigation on 2026-08-23, reading `migration_export/` (exported
2026-08-08), established the following. Every number below is fleet-wide.

| Fact | Value |
|---|---|
| audit rows | 2865 |
| applied to YouTube | 2618 |
| `not_applicable` | 2681 |
| — of those, no `measurement_result` at all | 2300 |
| — evaluated, then rejected as dormant | 381 (all with **0** pre-window impressions) |
| `neutral` | 147 |
| `win` | 21 |
| `regression` | 3 |
| prompt versions | 6 — 1 retired, 5 `shadow`, **0 live** |

Three conclusions followed.

**The sensor works; the loop is severed by configuration.** The 2300 rows with
no `measurement_result` are overwhelmingly May–June, before measurement existed;
they are history, not failure. In July the sweep evaluated 552 audits and
returned 171 verdicts — a 31% yield, which is healthy. The real defect is that
`audits.py:528` only stamps `awaiting_window` when the channel has
`measurement_enabled`, and:

- `UCc4Tv_DEGDEKrKAt-vyVNmw` — the **only** channel with autopilot on — has
  `measurement_enabled = False`. All 57 of its August applies fell to the
  `not_applicable` default with no result. It has produced **zero** verdicts ever.
- `UC8KjoL0Z9mTHKqB6gFutkJw` — which produced **all 171** verdicts — has
  autopilot **off**.

The channel doing the work is invisible. The channel being measured is not
working. Nothing downstream can produce evidence until that is true.

**The reflection trigger would have fired on a false premise, and the six
existing candidates already did.** Two separate problems, initially conflated
here and corrected 2026-08-23 after reading `prompt_versions.performance_snapshot`:

*The six existing candidates are velocity-era artifacts.* Every one carries
`median_velocity_lift` and no `median_ctr_delta_pct`, with lifts of −98% to
−99.5% and win rates of 0.0–1.6% over `count` values of 502–1979. Those counts
are *all applied audits*, not measured verdicts — the old velocity report ran on
view counts, which every audit has, so its gate was far weaker than
`_MIN_DATA_POINTS`. That is how a channel with zero CTR verdicts accumulated five
candidates. The most recent is 2026-07-27; as of the 2026-08-08 export, **no
CTR-era reflection had ever been recorded.** These five `shadow` rows were
generated from a metric known to be broken and none should be promoted.

*The CTR-era rule was primed to repeat the mistake.* `verdicts.win_rate` counts
neutral in its denominator — correctly, since neutral is a measured outcome — so
`UC8KjoL0Z9mTHKqB6gFutkJw`'s 171 verdicts give 21/171 = 12.3%. The old rule
(`win_rate < 50 -> reflect`) would therefore have fired on the next eligible
Monday and every one after, with a prompt asking the model to *"diagnose why the
current prompt underperforms"* — presupposing underperformance that a
neutral-dominant distribution does not show. `reflection.py:154` warns about
exactly this history: the metric was fixed, the threshold was never recalibrated
to what the fixed metric returns. The fix in `7fd628c` is therefore preventive
rather than curative, and no less necessary for it.

`_weekly_reflection` runs for **every** channel with no eligibility filter. Under
CTR gating that now no-ops safely on the twelve channels below
`_MIN_DATA_POINTS`, but it is worth knowing the fan-out is unfiltered.

**A calibrated LLM judge is not buildable yet.** Three regressions means at most
three win-vs-regression pairs — statistically empty. This is a consequence of
the severed loop, not of anything intrinsic: once measurement is on for the
autopilot channel, 57 applies/month at 31% yield accrues roughly 18 verdicts a
month.

The original brief asked for four things: observability, LangGraph, tool usage,
and context management. The finding reorders them. The instrument that was
missing is not LLM tracing — it is the one that says whether an audit did
anything.

## Already done (2026-08-23, outside this spec)

Committed separately as a bounded fix, because it was stopping waste every week:

- `_should_reflect` now fires on evidence of **harm** — regressions outnumbering
  wins, a median CTR delta below −2%, or a lever below −5% — never on an absence
  of wins. `_WIN_RATE_THRESHOLD` and `_REGRESSION_THRESHOLD` are gone; both were
  unreachable for a neutral-dominant channel.
- `_build_perf_report` now carries `distribution` (win/neutral/regression counts
  from `verdicts.distribution`), because a win rate alone cannot distinguish
  "mostly neutral" from "mostly regression".
- The reflection prompt no longer presupposes underperformance, states that
  neutral is the ordinary outcome of a metadata rewrite, and makes "no change
  warranted" a first-class answer.
- `_run_reflection` returns `(version_id, reason)`, so a model declining a
  rewrite (`no_change_warranted`) stops being logged as `reflection_llm_failed`.

## Scope

Four pieces, in dependency order.

### 1. Reconnect the loop

Set `measurement_enabled = true` on `UCc4Tv_DEGDEKrKAt-vyVNmw`.

One field. It gates everything else in this document — no instrumentation or
scorer produces useful signal while the autopilot channel's outcomes are
discarded. It is a production write, so it is executed by the user, not by an
agent:

```sql
UPDATE channels SET measurement_enabled = true
WHERE id = 'UCc4Tv_DEGDEKrKAt-vyVNmw';
```

Per `CLAUDE.md`, verify the change landed, then refresh the NAS snapshot rather
than waiting for the nightly run.

Only newly-applied audits enter the pipeline; `audits.py:528` stamps at apply
time and there is no backfill. The 57 August applies stay unmeasured — their
windows have closed and their reach coverage was never collected. That is
accepted, not fixed.

**Verification:** within 24h of the next autopilot apply, that channel should
have audits in `awaiting_window`. Within roughly 3 weeks (`window_for` plus
`ROLLOVER_SLOP_DAYS` plus report lag) the first verdicts should appear.

**Same trip: retire the five velocity-era candidates.** They were generated
from the broken view-velocity metric (lifts of −98% to −99.5%) and sit in
`shadow`, indistinguishable in the UI from a candidate a real CTR reflection
would produce. Anyone promoting one would be adopting a prompt written to fix a
problem that did not exist. Retire rather than delete, so the history stays
readable:

```sql
UPDATE prompt_versions SET status = 'retired', retired_at = now()
WHERE status = 'shadow'
  AND performance_snapshot ? 'median_velocity_lift';
```

The `?` operator tests for a JSON key, which is what dates these rows — the
velocity report emitted `median_velocity_lift`, the CTR report emits
`median_ctr_delta_pct`. Verify the row count matches the five expected before
committing the transaction; a higher count means a CTR-era candidate has since
been written and the predicate needs narrowing by date.

### 2. Feed the loop measurable work

Resolved 2026-08-23. `_next_video_for_channel` walks the catalogue
newest-first with no regard for whether a video gets any traffic, and the
consequence shows up in the 381 dormant verdicts:

- **184** videos were published *during or after* their own pre-change window.
  Autopilot edits videos shortly after upload, so no "before" period exists.
  Structurally unmeasurable — not a bug in measurement.
- **197** were published well before and genuinely had zero impressions.

Their median *post*-change impressions was **45**, against a
`MIN_IMPRESSIONS` floor of 500. These videos fail at both ends: no before, and
not enough after either. Roughly 7 in 10 audits therefore cost an LLM call and
YouTube quota while being incapable of producing evidence.

The decision is **not** to stop auditing them. Good metadata on a video nobody
finds is plausibly the highest-upside edit available; it simply cannot be
proven by a before/after comparison. Instead, **ring-fence a share of each
channel's daily cap for videos that are measurable**, so the learning loop is
fed every day regardless of what the newest-first walk happens to surface.

Design constraints:

- **"Measurable" is not a new rule.** The picker must ask the same question
  `measurement` asks — impressions over the trailing window at or above
  `settings.MIN_IMPRESSIONS`. Inventing a second threshold would let the picker
  and the measurer disagree about which videos count, which is the class of
  drift `app/verdicts.py`'s guard tests exist to prevent.
- **The picker exists twice.** `next_audit_candidate` (Postgres RPC, the fast
  path) and the in-app fallback in `_next_video_for_channel`. Both must change
  together; `tests/test_autopilot_picker_parity_live.py` asserts they agree,
  and that test is the contract.
- **New split, new setting.** A per-channel reserved share (default: 3 of a
  10-video cap) rather than a hardcoded ratio, so it can be tuned per channel
  without a deploy.
- Requires a migration. Per `CLAUDE.md`, refresh the NAS snapshot after it
  lands and is verified.

Expected effect: measurable audits per month rise from roughly 18 to roughly
the reserved share, since nearly every reserved-slot audit produces a verdict.
That is what shortens the wait on the deferred LLM judge below.

### 3. Phoenix and instrumentation

**Service.** `phoenix` in the existing `docker-compose.yml`, using the `db`
service already running, with `PHOENIX_SQL_DATABASE_URL` pointed at a **separate
`phoenix` database**. Ports 6006 (UI + OTLP HTTP) and 4317 (OTLP gRPC), pinned
to an explicit image version.

The separate database is deliberate. `app/backup.py` runs `pg_dump` against a
single DSN, not `pg_dumpall`, so traces are excluded from the NAS snapshot by
construction. Trace data is telemetry; losing it is not a disaster-recovery
event, and it must not bloat the snapshot that `CLAUDE.md` is built around.
Retention is capped so trace growth cannot compete with operational data for
disk on the office machine.

**One new module: `app/tracing.py`.** The only file in the codebase that imports
OpenTelemetry. It exposes a span context manager and a decorator; nothing else
knows OTel exists. Two consequences: repointing at a hosted backend later is one
env var, and `OTEL_ENABLED=false` makes every call site a no-op.

**Fail-open is a hard requirement.** Autopilot runs unattended on a machine
nobody is sitting at. If Phoenix is down or slow, spans are dropped and the
audit still applies. A telemetry outage must never become a revenue outage. Span
emission is wrapped so no exception can escape into a caller.

**Instrumentation is manual, not auto.** Midas calls OpenRouter through raw
`httpx`, which no auto-instrumentor sees. Switching to the OpenAI SDK to gain
auto-instrumentation would change the LLM client for the entire application to
save roughly thirty lines; not worth the risk.

*LLM spans* — both functions in `app/openrouter.py`. Attributes, chosen for what
is currently invisible:

| Attribute | Why |
|---|---|
| `llm.json_repair_fired` | `chat_json` silently rescues malformed JSON. Its own docstring concedes a parse "got rescued by luck." The rate is unknown. |
| `llm.json_sliced` | `_extract_json_object` having to slice means the model narrated around its JSON — a quality signal currently discarded. |
| `llm.model_requested` / `llm.model_served` | OpenRouter can reroute. The response's `model` field says what actually ran; nothing reads it today. |
| `llm.tokens.*`, `llm.cost` | Nothing counts either. "What does one audit cost" is unanswerable. |
| `llm.latency_ms` | The two-timeouts-then-fail logic in `tick()` fights a problem it cannot measure. |
| `llm.call_site` | Eight call sites are indistinguishable in the logs. |

*Operation spans* — root spans wrapping `audit_video()`, `reflect()`,
`eval_measurements()`, and `tick()`. Without these, LLM spans are anonymous;
with them, every call sits under why it happened.

*Evidence-loop spans* — the reason this phase widened beyond `openrouter.py`. A
configuration gap silently ate 57 applies for a month and took an NDJSON
forensic dig to find. Specifically:

- the apply path records `measurement_enabled` as a span attribute, so an
  applied-but-unmeasurable audit is a visible, alertable fact within a day;
- `plan_measurement`'s outcome per audit, so the dormant/coverage/hold split is
  a chart rather than a hypothesis;
- `_should_reflect`'s decision and reason, so a stuck trigger is obvious at a
  glance instead of after three months.

### 4. Tier 1 deterministic scorers

An eval suite run against a **frozen, stratified** sample of videos. Frozen is
load-bearing: comparing two prompt versions on different videos is not a
comparison.

No LLM involved. Fully reproducible. Two groups:

**Safety** — reuse `AuditSuggestion.rejection()` directly, so the eval and the
production apply-time check cannot drift.

**House format**, currently enforced only as prose in three separate prompts and
measured nowhere:

- hashtag count **pre-cap** equals 15. This is the highest-value scorer in the
  set: `cap_description_hashtags` silently fixes overflow at construction, so a
  prompt that regressed to 22 hashtags persists a row *identical* to a good one.
  The fix erases the evidence. Measuring pre-cap is the only way to see it.
- exactly 3 hashtags on the first line
- all five description blocks present and in order
- regional script genuinely present — a codepoint-range check, not a heuristic
- title matches `[regional] | [english] | [theme] Nursery 3D Rhymes`
- tags total characters within a target band; under 200 is wasted budget, not a
  pass
- JSON arrived intact — neither `json_repair` nor the brace-slice fired

Runner: `scripts/eval_prompt.py <prompt_version_id>`, emitting results to Phoenix
as an experiment and a summary to stdout. The deterministic scorers additionally
get a pytest wrapper over a small fixture set, so format regressions fail CI
without needing Phoenix or network access.

## Explicitly out of scope

Deferred with re-entry criteria, so the decision is revisited on evidence rather
than forgotten:

- **LLM-as-judge scorer.** Blocked on labels. Revisit when there are at least 30
  `regression` verdicts fleet-wide — dependent on step 2 — at the unreserved rate that is 6–9 months, and
  materially sooner with a reserved share. Design as pairwise with position-swapping and abstention, and
  calibrate against known win/regression pairs before trusting it. Pre-register
  thresholds — ≥70% agreement, ≥80% swap-consistency — *before* seeing a result.
  If calibration fails, the judge gets no authority. Failing is an acceptable
  outcome.
- **An eval gate on prompt promotion.** Blocked on the judge. Gating on Tier 1
  alone would only assert the candidate is well-formed, which the apply path
  already enforces. Gating on an uncalibrated judge would replace one
  unvalidated heuristic with another — the thing this whole effort exists to
  stop.
- **Tool-using audits.** The audit model currently receives a hand-assembled
  context block and cannot ask for more. Giving it tools is the only change in
  the original brief that can plausibly move audit quality, and it is unsafe to
  attempt before steps 3 and 4 can detect a regression.
- **LangGraph.** `autopilot.tick()` should **not** become a graph: 613 lines of
  readable, testable, single-video-per-beat Python would gain indirection and
  nothing else. LangGraph's defensible homes in Midas are the tool-using audit
  loop above, and `reflection.py`'s six-step cycle, which is genuinely stateful
  and would benefit from durable resumption. Both wait on the phases above.

## Error handling

- Tracing failures are swallowed inside `app/tracing.py`. No span emission path
  may raise into a caller.
- Phoenix unreachable is a logged warning once per process, not per span.
- The eval runner is a script, not a scheduled job, for this phase. It has no
  production write path and cannot affect autopilot.
- Step 1 is a manual, reversible single-field update.

## Testing

- `app/tracing.py`: unit tests that a raising exporter is invisible to callers,
  and that `OTEL_ENABLED=false` emits nothing.
- Span attributes: assert `json_repair_fired` is true for a known-malformed
  payload and false for clean JSON — pinning the signal that is currently
  invisible.
- Apply path: assert the span records `measurement_enabled`, so the class of bug
  that motivated this document cannot recur silently.
- Tier 1 scorers: table-driven tests per rule, including a description with 22
  hashtags that must score as a failure **despite** `cap_description_hashtags`
  normalising it.
- Picker split (step 2): `test_autopilot_picker_parity_live.py` must still pass
  — it is the contract between the RPC and the in-app fallback, and a change
  that only lands in one of them is the failure mode it exists to catch. Plus
  offline tests that a reserved slot prefers a measurable video, and that the
  reserved share degrades to the normal walk when no measurable candidate
  exists rather than idling the channel.
- Existing guard tests in `tests/test_verdicts.py` continue to enforce that no
  module computes its own win rate, median, or lever taxonomy.
- Live-integration tests remain `@pytest.mark.live` and skip without creds.

## Open questions

1. ~~**Why did all 381 evaluated audits have exactly 0 pre-window
   impressions?**~~ **Resolved 2026-08-23.** Not a coverage gap: the dormant
   branch in `measurement.py` is only reached *after* `missing_days` comes back
   empty, so the reach data was present and genuinely read zero. The cause is
   video selection — 184 of the 381 were published during or after their own
   pre-change window (autopilot edits shortly after upload, so no "before"
   exists), and the other 197 are old videos with real zero traffic. Their
   median post-change impressions was 45 against a 500 floor, so they fail on
   both sides. Addressed by step 2.

2. ~~**Why does `UCr5-YUqBiW7PUmeAtxUWuRg` own 5 of 6 prompt versions with zero
   verdicts?**~~ **Resolved 2026-08-23.** No second path into reflection. All
   six versions predate the CTR report — their `performance_snapshot` carries
   `median_velocity_lift` — and the velocity-era `_build_perf_report` gated on
   all applied audits (502–1979) rather than measured verdicts, so
   `_MIN_DATA_POINTS` was trivially satisfied. See the revised finding above.

3. **Trace retention.** What window, and does the office machine have the disk
   for it at current audit volume? Needs a measured span-size estimate, not a
   guess.
