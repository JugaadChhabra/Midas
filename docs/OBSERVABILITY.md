# Observability

Phoenix, self-hosted, in the same compose stack as everything else.

## What is traced

Two layers. LLM spans in `app/openrouter.py` carry the model requested *and
the model served* (OpenRouter can reroute), tokens, cost, and whether
`json_repair` or the brace-slice had to rescue the response. Operation spans
wrap `tick`, `audit_video`, `apply_audit`, `reflect`, `should_reflect`, and
`eval_measurements`, so an LLM span always has a parent explaining why it ran.

`eval_measurements` emits `measurement.count.{status}` and, beside it,
`measurement.reason.{cause}` — `dormant`, `coverage_lost`, `no_timestamp`,
`video_gone`. Four branches share the `not_applicable` status, and the split
between them is the difference between a fact about the audience and one about
our own ingestion. The cause is a `reason_code` key in `measurement_result`,
not something parsed out of the human-readable `rationale` beside it.

`app/tracing.py` is the only module that imports OpenTelemetry, enforced by a
test. Everything else uses `span()` and `Recorder.set()`.

## Every `tick.outcome`

One autopilot tick sets exactly one of these on its `tick` span, and returns.
Derived from `app/autopilot.py` (`tick`, `_agent_tick`) and `app/agent_tick.py`
(`run`). Since S3.6 (spec Part 6, F13) the house-format title path is gone from
the tick, and with it `audit_paused`, `title_autopilot_disabled`, `no_video` of
the audit picker, `unsafe_model`, `audit_timeout`, `audit_failed`, `quarantined`,
`applied` and `apply_exception` of the audit apply. Build dashboards off this
list, not off the plan's.

Gates before any work happens:

| value | meaning |
| --- | --- |
| `quota_dormant` | YouTube quota exhausted; the fleet is waiting for reset |
| `no_channel` | nothing eligible to pick |
| `shorts_only` | channel with `agent_enabled` off: the Shorts action is all the tick does |
| `agent_ineligible` | agent channel whose agent path is closed (`eligibility.can_run_agent`) |
| `apply_disabled` | `BACKLINK_APPLY_ENABLED=false`; the agent does nothing |
| `no_heading` | the channel's language has no heading in `backlinks.HEADINGS` |
| `stale_sync` | resync was needed and did not succeed |
| `daily_cap` | channel already at `autopilot_daily_cap` applies today |
| `quota_insufficient` | the ledger says the write can't be afforded; a skip, nothing paused |

Agent leg (the return of `agent_tick.run`, or `_react_to_apply_error` on an `ApplyError`):

| value | meaning |
| --- | --- |
| `no_video` | the warm pool has nothing to pick |
| `active_intervention` | the pick already has an active Midas intervention |
| `declined` | triage said `no_change` (or the block can't be rendered) |
| `holdout` | held out; would-be targets recorded, no YouTube call |
| `measuring` | the backlinks write happened |
| `dry_run` | `DRY_RUN=true`; rendered, nothing written, row cancelled |
| `youtube_quota_exceeded` | quota hit at apply; fleet goes dormant |
| `token_expired` | OAuth token expired/revoked; channel paused |
| `failed` | classified apply failure; counts toward `_record_failure` |
| `agent_failed` | unclassified raise; counts toward `_record_failure` |

A tick that raises outright sets no outcome and carries ERROR on the span
instead — absence of `tick.outcome` is itself the signal.

## Turning it on

`OTEL_ENABLED=true` in `.env`, then restart the app. Default is off: the
instrumentation is inert until you opt in.

The `phoenix` database must exist before the container starts. Phoenix creates
its own tables but **not** its own database, and `POSTGRES_DB=midas` never made
it — with `restart: unless-stopped`, a missing database is a silent crash-loop
rather than an error anyone sees. Once, on the office machine:

    docker compose exec -T db createdb -U midas phoenix

UI: http://localhost:6006 (loopback only, like every other service here).

## Where the data lives

A `phoenix` database in the existing Postgres cluster — deliberately NOT the
`midas` database. `app/backup.py` dumps a single DSN, so traces stay out of the
NAS snapshot by construction. That is the intent: trace data is telemetry, and
losing it is not a disaster-recovery event. **A restore will come back with no
trace history, and that is correct.**

## Retention

Phoenix does not prune by default, and this disk is shared with the
operational database. Before raising any retention window, measure real span
volume:

    docker compose exec -T db psql -U midas -d phoenix -c "\l+ phoenix"

Estimate from a week of real traffic rather than guessing. If it grows faster
than expected, the cheap lever is dropping `input.value` / `output.value` from
the LLM spans — they are by far the largest attributes.

## When Phoenix is down

Nothing happens. Every path in `app/tracing.py` fails open; a dead collector
costs a background retry and nothing else. Autopilot runs unattended, so this
is a hard requirement, not a nicety — `tests/test_tracing.py` pins it.
