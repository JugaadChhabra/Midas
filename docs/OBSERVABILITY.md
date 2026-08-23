# Observability

Phoenix, self-hosted, in the same compose stack as everything else.

## What is traced

Two layers. LLM spans in `app/openrouter.py` carry the model requested *and
the model served* (OpenRouter can reroute), tokens, cost, and whether
`json_repair` or the brace-slice had to rescue the response. Operation spans
wrap `tick`, `audit_video`, `apply_audit`, `reflect`, `should_reflect`, and
`eval_measurements`, so an LLM span always has a parent explaining why it ran.

`app/tracing.py` is the only module that imports OpenTelemetry, enforced by a
test. Everything else uses `span()` and `Recorder.set()`.

## Turning it on

`OTEL_ENABLED=true` in `.env`, then restart the app. Default is off: the
instrumentation is inert until you opt in.

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
