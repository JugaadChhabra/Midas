# Final fix wave — whole-branch review

Baseline before this wave: 1570 passed, 0 failed, but the suite's stderr ended
in a `RuntimeError: still down` traceback. After: **1577 passed, 0 failed,
stderr 0 bytes.**

Commands run at the end:

    venv/bin/python -m pytest -q            # 1577 passed, 1 warning in 16.36s; stderr 0 bytes
    venv/bin/python -m pytest tests/test_tracing.py tests/test_openrouter_tracing.py \
        tests/test_evidence_loop_tracing.py tests/test_autopilot_tick_helpers.py \
        tests/test_measurement_composition.py tests/test_measurement_judge.py \
        tests/test_verdicts.py -q          # 423 passed
    venv/bin/python -m py_compile scripts/reconnect_evidence_loop.py   # clean

No Docker container was started, stopped or restarted.

---

## Item 1 — unbounded flush in the shutdown path — DONE

`app/tracing.py`: added `FLUSH_TIMEOUT_MS = 2000` with a comment naming the
actual reason (`force_flush` defaults to 30_000 ms, the OTLP/HTTP exporter
retries with backoff inside that window, and the `midas` service declares no
`stop_grace_period` so Docker's default 10 s wins — SIGKILL mid-flush). `flush()`
now calls `_provider.force_flush(FLUSH_TIMEOUT_MS)`.

`app/main.py`: `scheduler.shutdown(wait=False)` now runs **before**
`tracing.flush()`, with a comment explaining why that ordering is the safe one
(`wait=False` does not wait on the batch processor anyway, so nothing is lost,
and a flush against a dead Phoenix can no longer sit between the process and a
clean scheduler stop).

Test: `tests/test_tracing.py::test_flush_cannot_block_past_the_container_grace_period`
— installs a provider whose `force_flush` records the timeout it was handed, and
asserts a bounded value (`not None`, `0 < t <= 5000`) was supplied. It fails on
the old code, where the argument was absent.

## Item 2 — the suite's red ending — DONE

`app/tracing.py::_reset_for_tests` now builds `TracerProvider(shutdown_on_exit=False)`,
with a comment recording both reasons: OTel registers its own atexit `shutdown`,
so the deliberately-exploding exporter raised at interpreter exit and ended an
all-green run in a traceback nobody could distinguish from a real failure; and
the function is called 40+ times a run, each call previously leaking a provider
plus a fresh hook.

Verification: full suite stderr redirected to a file — **0 bytes**, versus a
`RuntimeError: still down` traceback before.

## Item 3 — three causes conflated into one counter — DONE

`app/verdicts.py`: added `REASON = "reason_code"` next to `RATIONALE` (that module
owns the `measurement_result` key vocabulary and has guard tests for it), plus a
`Verdict.reason_code` property. No existing key or value changed.

`app/measurement.py`: four stable tags — `REASON_NO_TIMESTAMP`,
`REASON_COVERAGE_LOST`, `REASON_DORMANT`, `REASON_VIDEO_GONE` — written into the
result dict alongside the existing `rationale` at their four branches
(`plan_measurement`'s missing-timestamp and coverage-lost branches,
`judge_reach`'s dormant branch, and `eval_measurements`' vanished-video branch).
The tag is an additive key; no persisted value, status string, control flow or
log line changed.

`_count_reason(reasons, result)` tallies from that key, never from the prose.
`_eval_audit` gained an optional `reasons` out-parameter (default `None`, so
every existing caller and test is unaffected) and counts on both the FINALIZE and
the MEASURE path — the MEASURE path matters most, since `judge_reach`'s dormant
verdict was 381 of 381 in the motivating investigation. `eval_measurements`
threads one dict through the loop, counts the vanished-video branch into the same
tally, and emits `measurement.reason.{code}` on the span beside the existing
`measurement.count.{status}`.

Tests, all in `tests/test_measurement_composition.py`:
- `test_the_three_not_applicable_causes_are_counted_separately` — drives all
  three causes through `_eval_audit`, asserts the tally has one of each, and
  asserts all three persisted the *same* terminal status (the premise: status
  alone answers nothing).
- `test_the_cause_is_structural_not_the_rationale_prose` — rewrites the
  rationale and shows the count is unaffected.
- `test_the_sweep_puts_each_cause_on_the_span_separately` — end-to-end through
  `eval_measurements`: two causes, both `not_applicable`, separately visible as
  `measurement.reason.*` while `measurement.count.not_applicable` reads 2.

## Item 4 — two spans sharing one name — DONE

Distinct labels at the three sites that run under no operation span:
- `app/playlists.py` → `label="playlist_membership_judge"`
- `app/playlist_discovery.py` → `label="playlist_proposal"`
- `app/audits.py` (prompt elaboration) → `label="elaborate_audit_prompt"`

The first two both passed `JUDGE_MODEL` and therefore shared one `_span_name`
result; each carries a comment saying so. Covered by the existing
`test_label_names_the_span` behaviour in `tests/test_openrouter_tracing.py`; no
new test, since the labels are call-site data, not logic.

## Item 5 — malformed `usage` fails the audit — DONE

`app/openrouter.py::_record_usage`: `data.get("usage") or {}` replaced with an
`isinstance(usage, dict)` check, commented with why `or {}` was insufficient
(wrong-typed, not absent) and why `Recorder.set`'s internal try cannot help
(arguments are evaluated first).

Test: `tests/test_openrouter_tracing.py::test_malformed_usage_block_does_not_break_the_call`,
parametrized over a list, a string and an int. Fails on the old code with
`AttributeError`.

## Item 6 — a successful write penalising a channel — DONE

`app/autopilot.py::_apply_audit_and_handle`: the success return is now
`status = result.get("status") if isinstance(result, dict) else None` then
`return status or AuditStatus.APPLIED`. `isinstance` rather than `(result or {})`
because a non-dict truthy return would still raise on `.get`. Comment names the
consequence being prevented: an `AttributeError` inside the success `try` lands
in `except Exception`, calls `_record_failure`, and three of those pause the
channel — for a video that was in fact rewritten. No control flow or side effect
changed; every existing autopilot test still passes.

## Item 7 — a test that could not fail — DONE

`test_configure_is_idempotent` replaced by
`test_configure_does_not_build_a_second_provider`. It runs the **enabled** path
(`OTEL_ENABLED=True`) with the OTLP exporter monkeypatched to a collectorless
double (no socket, no live Phoenix, no retry loop) and `TracerProvider`
subclassed to count constructions and to skip the atexit hook. It asserts one
provider was built across two `configure()` calls, and that both the tracer and
the provider are identical objects afterwards. It also asserts both are non-None
first, so the test cannot pass vacuously if the enabled path silently failed
open. `tests/` is outside the guard test's scan (`app/**` only), so importing
opentelemetry there does not violate the seam.

## Item 8 — docs and a misleading comment — DONE

(a) `docker-compose.yml`: the three-line "trace retention" comment above
`PHOENIX_ENABLE_PROMETHEUS` is gone. In its place: why Prometheus is off
(nothing scrapes it; a second port on a loopback-only box), and an explicit
statement that there is **no** retention cap, pointing at
`docs/OBSERVABILITY.md` §Retention.

(b) `docs/OBSERVABILITY.md`: added the `createdb phoenix` step under "Turning it
on", with the reason it is not optional (Phoenix creates tables but not its
database, `POSTGRES_DB=midas` never made it, and `restart: unless-stopped` turns
the omission into a silent crash-loop) and the exact command for the office
machine, which has no git checkout.

(c) `docs/OBSERVABILITY.md`: new "Every `tick.outcome`" section enumerating all
**17** values, derived from `app/autopilot.py` and `app/apply_outcome.py`, not
from the plan's stale 12 — 11 literals in `tick()` plus `applied`, `dry_run`,
`apply_exception` and `ApplyOutcome`'s four members (`token_expired` occurs on
both legs, hence 17 distinct rather than 18). Grouped by leg, with a note that a
tick which raises sets no outcome at all. Also documented the new
`measurement.reason.{cause}` counters from Item 3.

(d) `docs/superpowers/plans/2026-08-23-phoenix-observability.md`: Self-Review now
records a third deliberate departure — the spec's OTLP gRPC port 4317 is not
published, because the app exports over HTTP and nothing in the stack speaks
gRPC, so it would be surface with no consumer on a loopback-only box.

## Item 9 — the retirement script's preview — DONE

`scripts/reconnect_evidence_loop.py`:
- The CTR-era query now carries `performance_snapshot IS NOT NULL`, and a third
  query lists shadow rows with a NULL snapshot under their own heading. On a NULL
  snapshot the jsonb `?` operator yields NULL, so such a row satisfied neither
  predicate and appeared in no list while the preview read as exhaustive. The
  comment states that and states that leaving them in shadow is the safe
  direction.
- The abort message now covers both directions: HIGHER means a new candidate was
  written since the script was drafted; LOWER means something already touched
  these rows (partial run, manual edit, wrong database) and finishing the job
  would complete work whose first half nobody has inspected.

**The retirement predicate itself is untouched** — a NULL snapshot still does not
get retired, deliberately.

Verified with `py_compile`; not executed, because it writes to the production
database and CLAUDE.md reserves production DB mutations for the user.

---

## Nothing skipped

All nine items are implemented.

## Concerns

- **Item 3 adds a key to `measurement_result` going forward.** Rows already
  persisted have no `reason_code`, so the `measurement.reason.*` counters
  describe only audits evaluated after this deploy. Historical rows still need
  the export-reading approach; `_count_reason` ignores a missing tag rather than
  bucketing it as unknown.
- **Item 3's `reasons` out-parameter** is the one piece of shape I am least happy
  with — `_eval_audit` returns a status, and the cause had to reach the sweep
  some other way without changing that return type (several tests assert on it).
  An out-parameter was the smallest change; a `(status, reason)` tuple would be
  cleaner and is a candidate for a later pass.
- **No test covers Item 1's ordering change in `app/main.py`.** The lifespan hook
  is not currently exercised by any test, and standing one up for two statements
  seemed disproportionate. The bounded-timeout half — the part that is a genuine
  logic invariant — is tested.
- Per CLAUDE.md, nothing here touches the database, so no NAS snapshot is due.
