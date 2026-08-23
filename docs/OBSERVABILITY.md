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
Seventeen values, derived from `app/autopilot.py` — the apply leg is not a
single `applied`, it is whatever `_apply_audit_and_handle` decided, which is
`ApplyOutcome`'s four members plus `applied`, `dry_run` and `apply_exception`.
Build dashboards off this list, not off the plan's (which predates the apply
leg expanding).

Gates before any work happens:

| value | meaning |
| --- | --- |
| `quota_dormant` | YouTube quota exhausted; the fleet is waiting for reset |
| `no_channel` | nothing eligible to pick |
| `audit_paused` | channel picked (possibly for shorts), audit path closed |
| `stale_sync` | resync was needed and did not succeed |
| `daily_cap` | channel already at `autopilot_daily_cap` applies today |
| `no_video` | no remaining unaudited video on that channel |
| `unsafe_model` | `AUDIT_MODEL` failed the safety gate; channel paused |

Audit leg:

| value | meaning |
| --- | --- |
| `token_expired` | OAuth token expired/revoked (also raised by the apply leg) |
| `audit_timeout` | OpenRouter read timeout; no failure charged to the channel |
| `audit_failed` | audit raised; counts toward `_record_failure` |
| `quarantined` | audit produced, `validate_audit` rejected it |

Apply leg (the return of `_apply_audit_and_handle`):

| value | meaning |
| --- | --- |
| `applied` | the YouTube write happened |
| `dry_run` | `DRY_RUN=true`; payload built, nothing written |
| `blocked_test_and_compare` | an active Test & Compare experiment on YouTube |
| `youtube_quota_exceeded` | quota hit at apply; fleet goes dormant |
| `failed` | classified apply failure; counts toward `_record_failure` |
| `apply_exception` | unclassified raise; counts toward `_record_failure` |

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
