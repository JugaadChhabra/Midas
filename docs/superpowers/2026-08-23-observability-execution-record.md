# Observability build — execution record

What was decided while building step 3 of
`specs/2026-08-23-observability-evidence-loop-design.md`, and what is still to
run. The spec says what to build and the plan says how; this says what actually
happened, which of the two documents was wrong where, and what a future reader
should not re-litigate.

Merged to `main` 2026-08-23 as 14 commits ending at `82f5fc8`. 1577 tests pass.

## Status of the spec's four steps

| Step | State |
|---|---|
| 1. Reconnect the loop | **Not run.** Needs the office machine. `scripts/reconnect_evidence_loop.py` is written and previews by default. |
| 2. Feed the loop measurable work | **Not built.** Needs a migration, so it needs the office machine too. |
| 3. Phoenix and instrumentation | **Built and merged.** Inert until `OTEL_ENABLED=true`. |
| 4. Tier 1 deterministic scorers | **Not built.** No blocker — needs no database and no office machine. The natural next piece of work. |

## What to run on the office machine, in order

1. `python scripts/reconnect_evidence_loop.py` to preview, then `--apply`.
   Enables `measurement_enabled` on the autopilot channel and retires the five
   velocity-era prompt candidates, in one transaction. It aborts rather than
   guessing if the candidate count has drifted from 5.
2. Verify it landed, **then** refresh the NAS snapshot — that order, per
   `CLAUDE.md`: publishing replaces today's slot, so snapshotting an unverified
   change overwrites a known-good copy.
3. Build and apply step 2's picker migration. Snapshot again after verifying.
4. Hand-carry `docker-compose.yml` and the `.env` additions to the office
   machine (it has no git checkout), and run
   `docker compose exec -T db createdb -U midas phoenix` on that cluster —
   Phoenix creates its own tables but not its own database, and a missing
   database plus `restart: unless-stopped` is a silent crash-loop.
5. Only then set `OTEL_ENABLED=true`, as a separate change from the deploy, so
   a Phoenix misconfiguration cannot be blamed on the app restart that
   accompanied it.

## Decisions taken during the build

Recorded because the reasoning is not recoverable from the diff, and because
several of them overrode the plan.

**Deliver the dormant/coverage split rather than defer it.** The first
implementation counted only the terminal `measurement_status`, but four
different branches all terminate as `not_applicable`. That conflated exactly
the distinction the spec named — and it is the distinction whose absence forced
the database export that produced "381 dormant, of which 184 were published
inside their own pre-window". Now tagged structurally via `verdicts.REASON`
(never by matching the human-readable `rationale`, which is written to be
reworded) and emitted as `measurement.reason.{cause}`.

**`tick.outcome` reports the outcome actually taken, not the literal
`"applied"`.** `_apply_audit_and_handle` absorbs `ApplyError` for four cases —
including one that pauses the channel and one that sets the whole fleet dormant
— and then returns normally, so all four were reporting as successful applies.
It was also internally inconsistent: a token expiry during the *audit* reported
`token_expired` while the identical failure during *apply* reported `applied`.
Fixed by having the function return its real outcome. This touched the revenue
path, deliberately: an attribute that says "applied" when the channel was just
paused is worse than no attribute.

**`APPLY_UNCLASSIFIED` is kept distinct from `ApplyOutcome.FAILED`.** `failed`
means YouTube rejected the write; the bare `except` means something that was
never typed at the boundary broke. They send you to different places.

**Flush is bounded and runs after the scheduler stops.** `force_flush` defaults
to 30s with exporter backoff inside it, while the `midas` service has no
`stop_grace_period` so Docker's default is 10s. With Phoenix down, shutdown
blocked past the grace period, the container was SIGKILLed, and the scheduler
never stopped cleanly — a telemetry outage changing how the app shuts down,
which is the one thing the spec forbids. Now `FLUSH_TIMEOUT_MS = 2000`, called
after `scheduler.shutdown(wait=False)`.

**`llm.call_site` and `llm.latency_ms` were dropped from the spec's attribute
table.** The parent operation span supplies the call site, and where one
operation makes several LLM calls the `label=` keyword disambiguates them. Span
duration already *is* the latency; a hand-computed copy would be a second
driftable definition.

**OTLP gRPC port 4317 is not published.** The spec mentions it; the app speaks
OTLP/HTTP only, so the port would be surface with no consumer.

**`CLAUDE.md` was not committed.** The plan listed it as a file to modify, which
was a plan defect: `.gitignore` carries an explicit `/CLAUDE.md` rule and the
file has never been tracked. The edit is on disk (agents read it from disk) and
the durable form of the same fact is in `docs/OBSERVABILITY.md`.

**`docs/agents/*.md` were committed unintentionally.** Three untracked files
swept in from a dirty working tree. They were kept rather than reverted because
`CLAUDE.md` references all three by path, so removing them would leave dangling
references — but they were not chosen, and `git rm --cached docs/agents/*.md`
reverses it.

## Known weaknesses, consciously carried

A whole-branch review triaged these as safe to merge. They are recorded so they
are not rediscovered as surprises.

- **No test covers `main.py`'s shutdown ordering.** The bounded timeout is
  tested; the ordering is held only by a comment naming why it must stay. The
  weakest spot in the instrumentation. The lifespan hook has no test harness
  today.
- **`reason_code` is forward-looking only.** Rows evaluated before this deploy
  carry no cause tag, so historical `not_applicable` analysis still needs the
  database export.
- **The `reasons` out-parameter on `_eval_audit`** is inelegant; a
  `(status, reason)` tuple return would be cleaner but would churn several
  existing assertions for no behavioural gain.
- **Trace retention is uncapped.** `docs/OBSERVABILITY.md` is honest about this.
  It cannot be sized without real traffic — spec open question 3. The `phoenix`
  database shares a disk with the operational Postgres whose NAS snapshot is the
  entire DR story, so this is worth returning to once there is a week of data.
- **`tick.outcome` draws from three vocabularies** (`AuditStatus`,
  `ApplyOutcome`, and tick's own gate strings) plus two literals. No collisions
  — verified — and deliberately not unified, because those are persisted status
  strings. All 17 values are enumerated in `docs/OBSERVABILITY.md`.

## What this deliberately did not touch

The original brief asked for four things: observability, LangGraph orchestration,
tool usage, and harness/context management. The investigation reordered them —
the instrument that was missing was not LLM tracing but the one that says
whether an audit did anything. The remaining three are recorded with re-entry
criteria in the spec's "Explicitly out of scope" section. In particular:
`autopilot.tick()` should **not** become a LangGraph graph; its defensible homes
are the tool-using audit loop and `reflection.py`'s stateful cycle, and both
wait on evidence this instrumentation is meant to produce.
