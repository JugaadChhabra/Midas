# Phoenix Observability Implementation Plan

> **Executed and merged to `main` on 2026-08-23.** Delivered `app/tracing.py`, LLM spans in `app/openrouter.py`, evidence-loop spans across audits/reflection/measurement/autopilot, and a self-hosted Phoenix service in `docker-compose.yml`; inert until `OTEL_ENABLED=true`. The execution record — including where the build deviated from this plan — is `docs/superpowers/2026-08-23-observability-execution-record.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every LLM call and every evidence-loop decision in Midas visible in a self-hosted Phoenix instance, without making the app depend on Phoenix being up.

**Architecture:** One new module, `app/tracing.py`, is the only file in the repo that imports OpenTelemetry. It exposes a `span()` context manager yielding a `Recorder`; callers set attributes through the `Recorder` and never touch an OTel type. Every path through the module is fail-open — a broken exporter, a missing collector, or `OTEL_ENABLED=false` all degrade to a no-op that still yields a working `Recorder`. Instrumentation lands in two layers: LLM spans inside `app/openrouter.py`, and operation spans wrapping the audit / reflection / measurement / autopilot entry points so an LLM span always has a parent explaining why it happened. Phoenix itself is stood up **last**, because tasks 1–3 are verified against an in-memory span exporter and need no container.

**Tech Stack:** Python 3.13, `opentelemetry-sdk==1.44.0`, `opentelemetry-exporter-otlp-proto-http==1.44.0`, OpenInference semantic conventions (attribute strings only, no dependency), Arize Phoenix (Docker), existing self-hosted Postgres 16.

**Spec:** `docs/superpowers/specs/2026-08-23-observability-evidence-loop-design.md` (step 3)

## Global Constraints

- **Fail-open is absolute.** No code path in `app/tracing.py` may raise into a caller. Autopilot runs unattended; a telemetry fault must never become a revenue fault.
- **`app/tracing.py` is the only file that may import `opentelemetry`.** Enforced by a guard test, in the style of the existing guards in `tests/test_verdicts.py`.
- **No OTel types in signatures outside `app/tracing.py`.** Callers see `span()` and `Recorder.set()` only.
- **Attribute names follow OpenInference exactly**, as verified against `https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md`: `openinference.span.kind`, `llm.model_name`, `llm.token_count.prompt`, `llm.token_count.completion`, `llm.token_count.total`, `llm.cost.total`, `input.value`, `output.value`. Phoenix's UI keys off these; inventing names produces spans that render as untyped.
- **`OTEL_ENABLED` defaults to `false`.** Tracing is opt-in per environment, so merging this changes nothing until the env var is set.
- **Pins are exact**, matching the curated style of `requirements.txt`, with a comment explaining why each is there.
- **Postgres major version is 16.** Phoenix requires ≥14, so this is satisfied; do not upgrade the `db` service.
- **The office machine has no git checkout.** It runs `.env` + `docker-compose.yml` + `.bat`, hand-carried. Any compose change must be called out as a file the user physically copies over. Avoid new bind mounts: a missing bind-mount source silently becomes a directory.

---

### Task 1: The tracing seam

**Files:**
- Create: `app/tracing.py`
- Create: `tests/test_tracing.py`
- Modify: `requirements.txt`
- Modify: `app/config.py:28-33` (add the two settings near `OPENROUTER_API_KEY`)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `tracing.configure() -> None` — idempotent; safe to call more than once; never raises.
  - `tracing.span(name: str, kind: str = CHAIN, **attributes) -> ContextManager[Recorder]`
  - `tracing.Recorder.set(**attributes) -> None`
  - Constants: `CHAIN`, `LLM`, `SPAN_KIND`, `MODEL_NAME`, `INPUT_VALUE`, `OUTPUT_VALUE`, `TOKEN_PROMPT`, `TOKEN_COMPLETION`, `TOKEN_TOTAL`, `COST_TOTAL`
  - `tracing._reset_for_tests(exporter=None) -> None` — installs an in-memory exporter; used only by tests.

- **Step 1: Add the dependencies**

In `requirements.txt`, append:

```
# OpenTelemetry, for app/tracing.py only — no other module may import it
# (tests/test_tracing.py enforces that). Traces go to a self-hosted Phoenix over
# OTLP/HTTP. Both pins move together: the SDK and the exporter share a version
# lockstep and a mismatched pair fails at import, not at export time.
opentelemetry-sdk==1.44.0
opentelemetry-exporter-otlp-proto-http==1.44.0
```

Install:

```bash
venv/bin/pip install opentelemetry-sdk==1.44.0 opentelemetry-exporter-otlp-proto-http==1.44.0
```

- **Step 2: Add the settings**

In `app/config.py`, inside `class Settings`, immediately after the `REFLECTION_MODEL` line:

```python
    # Tracing. Defaults to OFF so merging the instrumentation changes nothing
    # until an environment opts in. OTEL_ENDPOINT is the Phoenix collector's
    # OTLP/HTTP traces path; inside docker-compose that host is the service name.
    OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() == "true"
    OTEL_ENDPOINT = os.getenv("OTEL_ENDPOINT", "http://phoenix:6006/v1/traces")
    OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "midas")
```

- **Step 3: Write the failing tests**

Create `tests/test_tracing.py`:

```python
"""The tracing seam must be invisible when it breaks.

Autopilot runs unattended on the office machine. Every test here exists to
pin one half of that promise: spans carry what we asked them to carry, and
nothing tracing does can reach a caller as an exception.
"""
import pathlib

import pytest

from app import tracing


@pytest.fixture(autouse=True)
def _isolated_tracer():
    """Fresh in-memory exporter per test; tracing left off afterwards."""
    exporter = tracing._reset_for_tests()
    yield exporter
    tracing._reset_for_tests(disable=True)


def _finished(exporter):
    return exporter.get_finished_spans()


def test_span_records_name_and_attributes(_isolated_tracer):
    with tracing.span("audit_video", video_id="abc123") as rec:
        rec.set(**{tracing.MODEL_NAME: "anthropic/claude-haiku-4.5"})

    spans = _finished(_isolated_tracer)
    assert len(spans) == 1
    assert spans[0].name == "audit_video"
    assert spans[0].attributes["video_id"] == "abc123"
    assert spans[0].attributes[tracing.MODEL_NAME] == "anthropic/claude-haiku-4.5"


def test_span_defaults_to_chain_kind(_isolated_tracer):
    with tracing.span("reflect"):
        pass
    assert _finished(_isolated_tracer)[0].attributes[tracing.SPAN_KIND] == tracing.CHAIN


def test_llm_kind_is_recorded_when_asked(_isolated_tracer):
    with tracing.span("chat_json", kind=tracing.LLM):
        pass
    assert _finished(_isolated_tracer)[0].attributes[tracing.SPAN_KIND] == tracing.LLM


def test_nested_spans_are_parented(_isolated_tracer):
    with tracing.span("audit_video"):
        with tracing.span("chat_json", kind=tracing.LLM):
            pass

    spans = {s.name: s for s in _finished(_isolated_tracer)}
    child, parent = spans["chat_json"], spans["audit_video"]
    assert child.parent is not None
    assert child.parent.span_id == parent.context.span_id


def test_an_exception_in_the_block_is_recorded_and_reraised(_isolated_tracer):
    """Tracing must not swallow the caller's error — only its own."""
    with pytest.raises(ValueError, match="boom"):
        with tracing.span("audit_video"):
            raise ValueError("boom")

    span = _finished(_isolated_tracer)[0]
    assert span.status.status_code.name == "ERROR"


def test_disabled_tracing_yields_a_working_recorder():
    """OTEL_ENABLED=false must not make call sites conditional."""
    tracing._reset_for_tests(disable=True)
    with tracing.span("audit_video", video_id="x") as rec:
        rec.set(foo="bar")          # must not raise
    # Nothing to assert about spans — the point is that nothing blew up.


def test_a_raising_exporter_is_invisible_to_the_caller(monkeypatch):
    """A dead Phoenix must not fail an audit."""
    class Exploding:
        def export(self, spans):
            raise RuntimeError("phoenix is down")

        def shutdown(self):
            raise RuntimeError("still down")

        def force_flush(self, timeout_millis=None):
            raise RuntimeError("very down")

    tracing._reset_for_tests(exporter=Exploding())
    with tracing.span("audit_video") as rec:
        rec.set(k="v")
    # Force the export path to run inside the test rather than at interpreter
    # exit, so a raise would surface here if it were going to surface at all.
    tracing.flush()


def test_set_with_a_none_value_is_dropped_not_crashed(_isolated_tracer):
    """OTel rejects None attribute values; callers pass Optionals constantly."""
    with tracing.span("audit_video") as rec:
        rec.set(present="yes", absent=None)

    attrs = _finished(_isolated_tracer)[0].attributes
    assert attrs["present"] == "yes"
    assert "absent" not in attrs


def test_configure_is_idempotent():
    tracing.configure()
    tracing.configure()        # must not raise or double-register


APP = pathlib.Path(__file__).resolve().parents[1] / "app"


@pytest.mark.parametrize(
    "path",
    [p for p in sorted(APP.rglob("*.py")) if p.name != "tracing.py"],
    ids=lambda p: p.name,
)
def test_only_tracing_imports_opentelemetry(path):
    """The seam is the point. One module owns OTel; everything else asks it.

    Without this, an OTel type leaks into a signature somewhere and swapping
    the backend stops being a one-env-var change.
    """
    assert "opentelemetry" not in path.read_text(), (
        f"{path.name} imports opentelemetry directly — go through app.tracing, "
        "so the backend stays swappable and OTEL_ENABLED=false stays total"
    )
```

- **Step 4: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_tracing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tracing'`

- **Step 5: Write `app/tracing.py`**

```python
"""The one place Midas talks to OpenTelemetry.

Everything else in the app asks this module for a span and sets attributes on
it. Nothing else imports opentelemetry — `tests/test_tracing.py` enforces that
— which buys two things: the backend behind `OTEL_ENDPOINT` is swappable
without touching a call site, and `OTEL_ENABLED=false` is total rather than
best-effort.

FAIL-OPEN IS THE WHOLE DESIGN. Autopilot runs unattended on the office machine.
If Phoenix is down, unreachable, or misconfigured, every function here degrades
to a no-op that still yields a working `Recorder`, so call sites never need a
conditional and a telemetry outage can never become a revenue outage. The only
exception deliberately allowed through is the caller's own — a `with` block that
raises records ERROR on the span and re-raises, because swallowing that would
hide real failures.

Attribute names follow the OpenInference semantic conventions, which is what
Phoenix's UI keys off:
https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md
Invented names still export, they just render as an untyped span.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import settings

log = logging.getLogger("midas.tracing")

# ── OpenInference attribute names ─────────────────────────────────────────
#
# Strings, not a dependency. There is a package that defines these, but it
# pulls a tree of instrumentors this app has no use for — it calls OpenRouter
# through raw httpx, which no auto-instrumentor sees.

SPAN_KIND = "openinference.span.kind"
#: A step in the app's own logic — an audit, a reflection cycle, a tick.
CHAIN = "CHAIN"
#: A model call.
LLM = "LLM"

MODEL_NAME = "llm.model_name"
INPUT_VALUE = "input.value"
OUTPUT_VALUE = "output.value"
TOKEN_PROMPT = "llm.token_count.prompt"
TOKEN_COMPLETION = "llm.token_count.completion"
TOKEN_TOTAL = "llm.token_count.total"
COST_TOTAL = "llm.cost.total"

#: Set once by `configure()`. None means tracing is off or setup failed — both
#: are handled identically on purpose, so a broken exporter behaves like a
#: disabled one rather than like a bug.
_tracer = None
_provider = None
_configured = False


class Recorder:
    """What a traced block writes attributes to.

    Wraps a span so callers never hold an OTel type. The no-op form (`_span is
    None`) exists so `with span(...) as rec: rec.set(...)` is valid whether or
    not tracing is on — the alternative is an `if rec:` at every call site,
    which is how instrumentation rots.
    """

    __slots__ = ("_span",)

    def __init__(self, span: Any = None) -> None:
        self._span = span

    def set(self, **attributes: Any) -> None:
        """Attach attributes. Silently drops Nones; never raises.

        Nones are dropped rather than stringified because OTel rejects them and
        because the callers here are full of Optionals — a transcript that
        wasn't found, a cost the provider didn't report. "Absent" is better
        expressed by the attribute's absence than by the string "None".
        """
        if self._span is None:
            return
        try:
            for key, value in attributes.items():
                if value is None:
                    continue
                self._span.set_attribute(key, value)
        except Exception:  # pragma: no cover - defensive
            log.debug("dropping span attributes", exc_info=True)


_NOOP = Recorder()


def configure() -> None:
    """Set up the exporter. Idempotent, and never raises.

    Called once from the app's startup hook. A failure here logs and leaves
    tracing off, which is indistinguishable at every call site from
    OTEL_ENABLED=false.
    """
    global _tracer, _provider, _configured
    if _configured:
        return
    _configured = True

    if not settings.OTEL_ENABLED:
        log.info("tracing disabled (OTEL_ENABLED is not true)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        _provider = TracerProvider(
            resource=Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
        )
        # Batched, not simple: an audit already waits on a 120s model call and
        # must not also wait on the collector. Batching is also what makes a
        # dead Phoenix cost nothing but a background retry.
        _provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT))
        )
        trace.set_tracer_provider(_provider)
        _tracer = trace.get_tracer("midas")
        log.info("tracing enabled, exporting to %s", settings.OTEL_ENDPOINT)
    except Exception:
        _tracer = None
        _provider = None
        log.warning(
            "tracing setup failed; continuing without it", exc_info=True
        )


@contextmanager
def span(name: str, kind: str = CHAIN, **attributes: Any) -> Iterator[Recorder]:
    """Trace a block of work. Yields a `Recorder` whether or not tracing is on.

    The caller's own exceptions propagate — they are recorded as ERROR on the
    span first. Exceptions originating in tracing itself never propagate.
    """
    if _tracer is None:
        yield _NOOP
        return

    try:
        cm = _tracer.start_as_current_span(name)
        otel_span = cm.__enter__()
    except Exception:
        log.debug("could not start span %s", name, exc_info=True)
        yield _NOOP
        return

    recorder = Recorder(otel_span)
    recorder.set(**{SPAN_KIND: kind}, **attributes)
    try:
        yield recorder
    except BaseException as exc:
        # The caller's failure is real signal — record it, then let it fly.
        try:
            from opentelemetry.trace import Status, StatusCode

            otel_span.set_status(Status(StatusCode.ERROR, str(exc)))
            otel_span.record_exception(exc)
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            cm.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:  # pragma: no cover - defensive
            pass
        raise
    else:
        try:
            cm.__exit__(None, None, None)
        except Exception:  # pragma: no cover - defensive
            log.debug("could not close span %s", name, exc_info=True)


def flush() -> None:
    """Best-effort flush of pending spans. Never raises.

    For process shutdown and for tests that need the export path to run before
    assertions rather than at interpreter exit.
    """
    if _provider is None:
        return
    try:
        _provider.force_flush()
    except Exception:
        log.debug("span flush failed", exc_info=True)


def _reset_for_tests(exporter: Any = None, disable: bool = False) -> Any:
    """Install an in-memory (or supplied) exporter. Tests only.

    Returns the exporter so a test can read finished spans off it. With
    `disable=True`, tears tracing down entirely to exercise the no-op paths.
    """
    global _tracer, _provider, _configured
    _configured = True

    if disable:
        _tracer = None
        _provider = None
        return None

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = exporter if exporter is not None else InMemorySpanExporter()
    _provider = TracerProvider()
    # Simple, not batched: tests assert on spans immediately after the block.
    _provider.add_span_processor(SimpleSpanProcessor(exporter))
    # `trace.set_tracer_provider` refuses to overwrite, so hold the tracer
    # directly instead of going through the global.
    _tracer = _provider.get_tracer("midas-test")
    return exporter
```

- **Step 6: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_tracing.py -v`
Expected: PASS, all tests including the per-file `test_only_tracing_imports_opentelemetry` parametrisation.

- **Step 7: Confirm nothing else broke**

Run: `venv/bin/python -m pytest -q`
Expected: the 7 pre-existing `*_live.py` failures only (they need a reachable Postgres). Everything else passes.

- **Step 8: Commit**

```bash
git add app/tracing.py tests/test_tracing.py requirements.txt app/config.py
git commit -m "feat(tracing): one seam for OpenTelemetry, fail-open by design

app/tracing.py is the only module that imports opentelemetry, enforced by a
guard test in the style of tests/test_verdicts.py. Callers get span() and
Recorder.set() and never hold an OTel type, so the backend behind
OTEL_ENDPOINT stays swappable and OTEL_ENABLED=false stays total.

Every path fails open. A dead collector, a failed setup, or tracing switched
off all degrade to a no-op that still yields a working Recorder — call sites
need no conditional. Autopilot runs unattended; a telemetry fault must not
become a revenue fault. The caller's own exceptions are the one thing that
does propagate, recorded as ERROR first, because swallowing those would hide
real failures.

Defaults to off, so this changes no behaviour until an environment opts in."
```

---

### Task 2: LLM spans in the OpenRouter client

**Files:**
- Modify: `app/openrouter.py` (both `chat_json` and `chat_text`)
- Create: `tests/test_openrouter_tracing.py`

**Interfaces:**
- Consumes: `tracing.span`, `tracing.Recorder.set`, and the constants from Task 1.
- Produces: `chat_json(prompt, model=None, system=None, image_urls=None, label=None)` and `chat_text(prompt, model=None, system=None, label=None)` — the new trailing `label` keyword names the span. Existing positional and keyword callers are unaffected.

Why `label` rather than a `call_site` parameter: the parent operation span from Task 3 already says *what* was running, but `reflect()` makes three different LLM calls inside one operation span, so the parent alone cannot disambiguate them. `label` defaults to `None`, in which case the span is named `llm.{model}`.

- **Step 1: Write the failing tests**

Create `tests/test_openrouter_tracing.py`:

```python
"""What the LLM spans must capture — chosen for what was previously invisible.

Before this, chat_json could be rescued by json_repair on every single call and
nothing would say so; OpenRouter could serve a different model than the one
requested and nothing read the field that says which; and no counter anywhere
knew what an audit cost.
"""
from unittest.mock import patch

import httpx
import pytest

from app import tracing


@pytest.fixture(autouse=True)
def _isolated_tracer():
    exporter = tracing._reset_for_tests()
    yield exporter
    tracing._reset_for_tests(disable=True)


def _response(content, model="anthropic/claude-haiku-4.5", usage=None):
    body = {
        "choices": [{"message": {"content": content}}],
        "model": model,
        "usage": usage or {
            "prompt_tokens": 120,
            "completion_tokens": 45,
            "total_tokens": 165,
            "cost": 0.00031,
        },
    }
    return httpx.Response(200, json=body)


def _only_span(exporter):
    spans = exporter.get_finished_spans()
    assert len(spans) == 1, f"expected one span, got {[s.name for s in spans]}"
    return spans[0]


def test_clean_json_records_tokens_cost_and_model(_isolated_tracer):
    from app.openrouter import chat_json

    with patch("app.openrouter.httpx.post", return_value=_response('{"ok": 1}')), \
         patch("app.openrouter.settings") as s:
        s.OPENROUTER_API_KEY = "k"
        s.AUDIT_MODEL = "anthropic/claude-haiku-4.5"
        assert chat_json("prompt") == {"ok": 1}

    attrs = _only_span(_isolated_tracer).attributes
    assert attrs[tracing.SPAN_KIND] == tracing.LLM
    assert attrs[tracing.TOKEN_PROMPT] == 120
    assert attrs[tracing.TOKEN_COMPLETION] == 45
    assert attrs[tracing.TOKEN_TOTAL] == 165
    assert attrs[tracing.COST_TOTAL] == pytest.approx(0.00031)
    assert attrs["llm.json_repair_fired"] is False
    assert attrs["llm.json_sliced"] is False


def test_records_the_model_actually_served_not_just_requested(_isolated_tracer):
    """OpenRouter can reroute. Nothing in the app read this field before."""
    from app.openrouter import chat_json

    with patch("app.openrouter.httpx.post",
               return_value=_response('{"ok": 1}', model="anthropic/claude-haiku-4.5-20990101")), \
         patch("app.openrouter.settings") as s:
        s.OPENROUTER_API_KEY = "k"
        s.AUDIT_MODEL = "anthropic/claude-haiku-4.5"
        chat_json("prompt")

    attrs = _only_span(_isolated_tracer).attributes
    assert attrs[tracing.MODEL_NAME] == "anthropic/claude-haiku-4.5"
    assert attrs["llm.model_served"] == "anthropic/claude-haiku-4.5-20990101"


def test_narrated_json_is_flagged_as_sliced(_isolated_tracer):
    """The `:online` variants narrate around the object; _extract_json_object
    rescues it, and that rescue was previously silent."""
    from app.openrouter import chat_json

    narrated = 'Sure! Here you go:\n```json\n{"ok": 1}\n```\nHope that helps.'
    with patch("app.openrouter.httpx.post", return_value=_response(narrated)), \
         patch("app.openrouter.settings") as s:
        s.OPENROUTER_API_KEY = "k"
        s.AUDIT_MODEL = "m"
        assert chat_json("prompt") == {"ok": 1}

    assert _only_span(_isolated_tracer).attributes["llm.json_sliced"] is True


def test_repaired_json_is_flagged(_isolated_tracer):
    """An unescaped quote inside a string value — the documented Gemini case."""
    from app.openrouter import chat_json

    broken = '{"title": "a "quoted" thing", "ok": 1}'
    with patch("app.openrouter.httpx.post", return_value=_response(broken)), \
         patch("app.openrouter.settings") as s:
        s.OPENROUTER_API_KEY = "k"
        s.AUDIT_MODEL = "m"
        chat_json("prompt")

    assert _only_span(_isolated_tracer).attributes["llm.json_repair_fired"] is True


def test_a_failed_call_marks_the_span_and_still_raises(_isolated_tracer):
    from app.openrouter import chat_json

    with patch("app.openrouter.httpx.post",
               return_value=httpx.Response(429, text="rate limited")), \
         patch("app.openrouter.settings") as s:
        s.OPENROUTER_API_KEY = "k"
        s.AUDIT_MODEL = "m"
        with pytest.raises(RuntimeError, match="429"):
            chat_json("prompt")

    assert _only_span(_isolated_tracer).status.status_code.name == "ERROR"


def test_label_names_the_span(_isolated_tracer):
    """reflect() makes three LLM calls in one operation span; the parent alone
    cannot tell them apart."""
    from app.openrouter import chat_text

    with patch("app.openrouter.httpx.post", return_value=_response("some prose")), \
         patch("app.openrouter.settings") as s:
        s.OPENROUTER_API_KEY = "k"
        s.AUDIT_MODEL = "m"
        chat_text("q", label="platform_guidance")

    assert _only_span(_isolated_tracer).name == "platform_guidance"


def test_unlabelled_span_is_named_for_the_model(_isolated_tracer):
    from app.openrouter import chat_text

    with patch("app.openrouter.httpx.post", return_value=_response("prose")), \
         patch("app.openrouter.settings") as s:
        s.OPENROUTER_API_KEY = "k"
        s.AUDIT_MODEL = "m"
        chat_text("q", model="perplexity/sonar")

    assert _only_span(_isolated_tracer).name == "llm.perplexity/sonar"


def test_missing_usage_block_does_not_break_the_call(_isolated_tracer):
    """Token accounting is telemetry. A provider that omits usage must not
    fail an audit."""
    from app.openrouter import chat_json

    body = {"choices": [{"message": {"content": '{"ok": 1}'}}], "model": "m"}
    with patch("app.openrouter.httpx.post", return_value=httpx.Response(200, json=body)), \
         patch("app.openrouter.settings") as s:
        s.OPENROUTER_API_KEY = "k"
        s.AUDIT_MODEL = "m"
        assert chat_json("prompt") == {"ok": 1}

    attrs = _only_span(_isolated_tracer).attributes
    assert tracing.TOKEN_TOTAL not in attrs
```

- **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_openrouter_tracing.py -v`
Expected: FAIL — no spans produced, `assert len(spans) == 1` fails with `[]`.

- **Step 3: Add a shared span helper to `app/openrouter.py`**

At the top, after the existing imports, add:

```python
from app import tracing
```

Then, above `embed()`, add:

```python
def _span_name(label: str | None, model: str) -> str:
    """Span name: the caller's label if it gave one, else the model.

    `reflect()` makes three LLM calls inside one operation span, so the parent
    cannot disambiguate them; a label can.
    """
    return label or f"llm.{model}"


def _record_usage(rec: tracing.Recorder, data: dict, requested: str) -> None:
    """Copy OpenRouter's accounting onto the span.

    `usage` is documented as always present and `usage.cost` is the amount
    actually charged, but this stays defensive: token accounting is telemetry,
    and a provider that omits the block must not fail an audit.

    `model_served` is recorded separately from the requested model because
    OpenRouter can reroute, and nothing in this app read that field before —
    an audit attributed to haiku may not have been produced by haiku.
    """
    usage = data.get("usage") or {}
    rec.set(**{
        tracing.MODEL_NAME: requested,
        "llm.model_served": data.get("model"),
        tracing.TOKEN_PROMPT: usage.get("prompt_tokens"),
        tracing.TOKEN_COMPLETION: usage.get("completion_tokens"),
        tracing.TOKEN_TOTAL: usage.get("total_tokens"),
        tracing.COST_TOTAL: usage.get("cost"),
    })
```

- **Step 4: Wrap `chat_json`**

Replace the body of `chat_json` from the `model = model or settings.AUDIT_MODEL` line onward. The signature gains `label`:

```python
def chat_json(prompt: str, model: str | None = None, system: str | None = None,
            image_urls: list[str] | None = None, label: str | None = None) -> dict:
    model = model or settings.AUDIT_MODEL
    """Call OpenRouter with response_format=json_object and parse the result.
    If image_urls is provided, the user message becomes multi-part (vision)."""
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set in .env")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})

    if image_urls:
        parts = [{"type": "text", "text": prompt}]
        for url in image_urls:
            parts.append({"type": "image_url", "image_url": {"url": url}})
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": prompt})

    with tracing.span(_span_name(label, model), kind=tracing.LLM) as rec:
        rec.set(**{
            tracing.MODEL_NAME: model,
            tracing.INPUT_VALUE: prompt[:4000],
            "llm.has_system_prompt": system is not None,
            "llm.image_count": len(image_urls or []),
        })
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "Midas",
            },
            json={
                "model": model,
                "messages": messages,
                "response_format": {"type": "json_object"},
            },
            timeout=120,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"OpenRouter {r.status_code} for model {model}: {r.text}")
        data = r.json()
        if "choices" not in data:
            raise RuntimeError(f"OpenRouter unexpected response: {data}")
        _record_usage(rec, data, model)
        content = data["choices"][0]["message"]["content"]
        rec.set(**{tracing.OUTPUT_VALUE: (content or "")[:4000]})

        # response_format is a request, not a guarantee — models wrap JSON in
        # fences, and the `:online` search variants narrate before and after the
        # object. Take the outermost {...} span rather than pattern-matching each
        # way of missing.
        stripped = content.strip()
        content = _extract_json_object(stripped)
        # Both rescues were previously silent. A model that has started
        # narrating around its JSON, or emitting JSON that needs repairing, is
        # degrading in a way nothing used to report.
        rec.set(**{"llm.json_sliced": content != stripped})
        try:
            result = json.loads(content)
            rec.set(**{"llm.json_repair_fired": False})
            return result
        except json.JSONDecodeError:
            # Gemini sometimes emits unescaped quotes/newlines inside string
            # values. json_repair best-efforts a fix; if it still fails, raise
            # with the raw content.
            rec.set(**{"llm.json_repair_fired": True})
            repaired = repair_json(content)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"Model returned unparseable JSON: {e}\n---\n{content[:2000]}"
                )
```

- **Step 5: Wrap `chat_text`**

```python
def chat_text(prompt: str, model: str | None = None, system: str | None = None,
              label: str | None = None) -> str:
    """Call OpenRouter without response_format constraint. Returns raw text content.
    Used for models that don't support json_object mode (e.g. perplexity/sonar).
    """
    model = model or settings.AUDIT_MODEL
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set in .env")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    with tracing.span(_span_name(label, model), kind=tracing.LLM) as rec:
        rec.set(**{
            tracing.MODEL_NAME: model,
            tracing.INPUT_VALUE: prompt[:4000],
            "llm.has_system_prompt": system is not None,
        })
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "Midas",
            },
            json={"model": model, "messages": messages},
            timeout=60,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"OpenRouter {r.status_code} for model {model}: {r.text}")
        data = r.json()
        if "choices" not in data:
            raise RuntimeError(f"OpenRouter unexpected response: {data}")
        _record_usage(rec, data, model)
        out = data["choices"][0]["message"]["content"].strip()
        rec.set(**{tracing.OUTPUT_VALUE: out[:4000]})
        return out
```

- **Step 6: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_openrouter_tracing.py -v`
Expected: PASS (8 tests)

- **Step 7: Confirm the existing OpenRouter tests still pass**

Run: `venv/bin/python -m pytest tests/ -q -k "openrouter or audit or reflection"`
Expected: PASS. `label` is a new trailing keyword with a default, so no existing caller changes.

- **Step 8: Commit**

```bash
git add app/openrouter.py tests/test_openrouter_tracing.py
git commit -m "feat(tracing): LLM spans with tokens, cost, and the silent rescues

Records what was previously unknowable. json_repair and the brace-slice in
_extract_json_object both rescue malformed model output and neither said so —
this module's own docstring concedes a parse 'got rescued by luck'. Both are
now span attributes, so a model that starts narrating around its JSON is a
visible trend rather than a mystery.

Also records llm.model_served alongside the requested model. OpenRouter can
reroute, the response says what actually ran, and nothing read that field
before — an audit attributed to haiku may not have been produced by haiku.

Tokens and cost come straight off OpenRouter's usage block, which is always
present and includes the amount charged. Read defensively anyway: token
accounting is telemetry and a provider that omits it must not fail an audit.

New trailing 'label' keyword names the span, because reflect() makes three
LLM calls inside one operation span and the parent cannot disambiguate them."
```

---

### Task 3: Operation spans on the evidence loop

**Files:**
- Modify: `app/audits.py` (`audit_video`, and the apply path around line 528)
- Modify: `app/reflection.py` (`reflect`, `_should_reflect`, and the three LLM call sites)
- Modify: `app/measurement.py` (`eval_measurements`)
- Modify: `app/autopilot.py` (`tick`)
- Modify: `app/main.py` (call `tracing.configure()` at startup)
- Create: `tests/test_evidence_loop_tracing.py`

**Interfaces:**
- Consumes: `tracing.span`, `tracing.Recorder.set`, `tracing.configure`, constants from Task 1; the `label` keyword from Task 2.
- Produces: no new callable signatures. Span names: `tick`, `audit_video`, `apply_audit`, `reflect`, `eval_measurements`.

- **Step 1: Write the failing tests**

Create `tests/test_evidence_loop_tracing.py`:

```python
"""Spans on the loop that produces evidence.

The bug that motivated all of this — one channel with autopilot on and
measurement off, silently discarding 57 applies for a month — was invisible in
logs and took an NDJSON forensic dig to find. These attributes are chosen so it
would have been a one-day question instead.
"""
from unittest.mock import MagicMock, patch

import pytest

from app import tracing


@pytest.fixture(autouse=True)
def _isolated_tracer():
    exporter = tracing._reset_for_tests()
    yield exporter
    tracing._reset_for_tests(disable=True)


def _named(exporter, name):
    hits = [s for s in exporter.get_finished_spans() if s.name == name]
    assert hits, f"no span named {name}; got {[s.name for s in exporter.get_finished_spans()]}"
    return hits[0]


def test_should_reflect_records_its_decision(_isolated_tracer):
    """A trigger stuck on for three months should be one glance, not a dig."""
    from app.reflection import _should_reflect

    report = {
        "count": 171,
        "win_rate": 12.3,
        "distribution": {"win": 21, "neutral": 147, "regression": 3, "total": 171},
        "median_ctr_delta_pct": 0.4,
        "levers": {"title": 1.0, "description": 1.0, "tags": 1.0},
        "worst_audits": [],
        "best_audits": [],
    }
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=report):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        should, reason = _should_reflect("ch1")

    assert (should, reason) == (False, "performing_well")
    attrs = _named(_isolated_tracer, "should_reflect").attributes
    assert attrs["reflection.should"] is False
    assert attrs["reflection.reason"] == "performing_well"
    assert attrs["reflection.win_rate"] == pytest.approx(12.3)
    assert attrs["reflection.wins"] == 21
    assert attrs["reflection.neutrals"] == 147
    assert attrs["reflection.regressions"] == 3


def test_should_reflect_records_the_no_evidence_case(_isolated_tracer):
    from app.reflection import _should_reflect

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=None):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        _should_reflect("ch1")

    attrs = _named(_isolated_tracer, "should_reflect").attributes
    assert attrs["reflection.reason"] == "no_measured_outcomes"
    assert "reflection.win_rate" not in attrs


def test_audit_video_span_wraps_the_llm_span(_isolated_tracer):
    """An LLM span with no parent cannot answer 'why did this call happen'."""
    from app import audits

    video = {
        "id": "vid1", "channel_id": "ch1", "privacy_status": "public",
        "title": "t", "description": "d", "tags": [], "is_short": False,
    }
    suggestion = {
        "comparisons": {
            "title": {"suggested": "new title"},
            "description": {"suggested": "new desc"},
            "tags": {"suggested": ["a"]},
        },
        "issues": [], "reasoning": "r",
    }

    with patch("app.audits.supabase") as mock_sb, \
         patch("app.audits.chat_json", return_value=suggestion), \
         patch("app.audits.fetch_transcript", return_value=("transcript", "en")), \
         patch("app.audits._ensure_strategy_row"):
        tbl = mock_sb.return_value.table.return_value
        tbl.select.return_value.eq.return_value.single.return_value \
            .execute.return_value.data = video
        tbl.select.return_value.eq.return_value.execute.return_value.data = [{}]
        tbl.insert.return_value.execute.return_value.data = [{"id": 1}]
        audits.audit_video("vid1")

    span = _named(_isolated_tracer, "audit_video")
    assert span.attributes["video_id"] == "vid1"
    assert span.attributes["channel_id"] == "ch1"
    assert span.attributes["audit.transcript_available"] is True


def test_apply_span_records_whether_the_audit_can_ever_be_measured(_isolated_tracer):
    """THE attribute. measurement_enabled=False on the autopilot channel meant
    57 applies produced no evidence and nothing said so."""
    from app import audits

    assert hasattr(audits, "_record_apply_measurability"), (
        "expected a helper recording measurement_enabled on the apply span"
    )
    with tracing.span("apply_audit") as rec:
        audits._record_apply_measurability(rec, {"measurement_enabled": False})

    attrs = _named(_isolated_tracer, "apply_audit").attributes
    assert attrs["apply.measurement_enabled"] is False
    assert attrs["apply.will_be_measured"] is False


def test_apply_span_marks_a_measurable_channel(_isolated_tracer):
    from app import audits

    with tracing.span("apply_audit") as rec:
        audits._record_apply_measurability(rec, {"measurement_enabled": True})

    attrs = _named(_isolated_tracer, "apply_audit").attributes
    assert attrs["apply.will_be_measured"] is True
```

- **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_evidence_loop_tracing.py -v`
Expected: FAIL — no span named `should_reflect`; `_record_apply_measurability` does not exist.

- **Step 3: Instrument `_should_reflect` in `app/reflection.py`**

Add `from app import tracing` to the imports. Then wrap the body of `_should_reflect`. Keep every existing branch and return value; only the span is new:

```python
def _should_reflect(channel_id: str) -> tuple[bool, str]:
    """Return (should_reflect, reason)."""
    with tracing.span("should_reflect", channel_id=channel_id) as rec:
        should, reason, report = _should_reflect_inner(channel_id)
        rec.set(**{
            "reflection.should": should,
            "reflection.reason": reason,
        })
        if report is not None:
            dist = report["distribution"]
            rec.set(**{
                "reflection.win_rate": report["win_rate"],
                "reflection.wins": dist[MeasurementStatus.WIN],
                "reflection.neutrals": dist[MeasurementStatus.NEUTRAL],
                "reflection.regressions": dist[MeasurementStatus.REGRESSION],
                "reflection.median_ctr_delta_pct": report["median_ctr_delta_pct"],
                "reflection.verdict_count": report["count"],
            })
        return should, reason
```

Rename the existing function body to `_should_reflect_inner(channel_id) -> tuple[bool, str, dict | None]`, returning the report as a third element so the span can read it without a second query. Each existing `return False, "reflected_recently"` becomes `return False, "reflected_recently", None`; the ones after the report is built return the report. The final line becomes `return False, "performing_well", report`.

- **Step 4: Label the three reflection LLM calls**

In `app/reflection.py`, add the `label` keyword at each call site so the three calls inside one `reflect()` span are distinguishable:

- `derive_niche_queries`: `chat_json(prompt, model="anthropic/claude-haiku-4.5", label="derive_niche_queries")`
- `_get_platform_guidance`: `chat_text(query, model="perplexity/sonar", label="platform_guidance")`
- `_run_reflection`: `chat_json(user, model=settings.REFLECTION_MODEL, system=system, label="reflection_candidate")`

- **Step 5: Wrap `reflect`**

At the top of `reflect(channel_id)`, wrap the whole body:

```python
def reflect(channel_id: str) -> dict:
    """Full reflection cycle for one channel. Called weekly by scheduler.

    Returns dict describing what happened.
    """
    with tracing.span("reflect", channel_id=channel_id) as rec:
        result = _reflect_inner(channel_id)
        rec.set(**{
            "reflect.reflected": result.get("reflected"),
            "reflect.reason": result.get("reason"),
            "reflect.version_id": result.get("version_id"),
            "reflect.shadow_audits_created": result.get("shadow_audits_created"),
        })
        return result
```

Rename the existing body to `_reflect_inner`.

- **Step 6: Instrument `audit_video` and the apply path in `app/audits.py`**

Add `from app import tracing` to the imports. Add the helper above `audit_video`:

```python
def _record_apply_measurability(rec: tracing.Recorder, channel: dict | None) -> None:
    """Record whether this apply can ever produce evidence.

    The single most important attribute in the whole instrumentation. The apply
    path only stamps `awaiting_window` when the channel has
    `measurement_enabled`, and on 2026-08-23 the only channel with autopilot on
    was the one channel with that flag off — 57 applies in a month, every one
    landing on the `not_applicable` default with no result, nothing in the logs
    saying so. It took reading an NDJSON export to find. With this attribute it
    is a one-day question.
    """
    enabled = bool((channel or {}).get("measurement_enabled"))
    rec.set(**{
        "apply.measurement_enabled": enabled,
        "apply.will_be_measured": enabled,
    })
```

Wrap `audit_video`'s body in a span, setting attributes as facts become known:

```python
    with tracing.span("audit_video", video_id=video_id) as rec:
        # ... existing body, unchanged, plus:
        rec.set(**{
            "channel_id": v["channel_id"],
            "audit.is_short": bool(v.get("is_short")),
            "audit.prompt_source": (
                "override" if prompt_override
                else "shorts" if (v.get("is_short") and cfg_row.get("shorts_prompt"))
                else "generated" if cfg_row.get("generated_prompt")
                else "default"
            ),
            "audit.prompt_version_id": prompt_version_id,
        })
        # ... after fetch_transcript:
        rec.set(**{
            "audit.transcript_available": transcript is not None,
            "audit.transcript_lang": transcript_lang,
        })
        # ... after AuditSuggestion.from_llm:
        rec.set(**{
            "audit.suggestion_valid": suggestion.is_valid,
            "audit.rejection": suggestion.rejection(),
        })
```

In the apply function, wrap the write in a span and call the helper where `channel` is already in scope (immediately before the `measurement_patch` block near line 528):

```python
    with tracing.span("apply_audit", video_id=video["id"], audit_id=audit_id) as rec:
        _record_apply_measurability(rec, channel)
        # ... existing measurement_patch and update, unchanged
```

- **Step 7: Instrument `eval_measurements` in `app/measurement.py`**

Add `from app import tracing`. Wrap the sweep and record the outcome mix, so the dormant/coverage/hold split is a chart rather than a hypothesis:

```python
    with tracing.span("eval_measurements") as rec:
        # ... existing body, and immediately before the return:
        rec.set(**{
            "measurement.audits_in_flight": len(audits),
            "measurement.errors": errors,
            **{f"measurement.count.{status}": n for status, n in counts.items()},
        })
```

- **Step 8: Instrument `tick` in `app/autopilot.py`**

Add `from app import tracing`. Wrap the existing body of `tick()`. The outer `try/except` stays exactly as it is — the span is inside it, so a crashing tick is still swallowed by the existing handler and still recorded:

```python
def tick():
    """One pass of the autopilot loop. Processes at most one video and returns.
    ...
    """
    try:
        with tracing.span("tick") as rec:
            # ... existing body, and at each early return, before returning:
            #   rec.set(**{"tick.outcome": "quota_dormant"})   etc.
            ...
    except Exception as e:
        log.exception("Autopilot tick crashed: %s", e)
```

Set `tick.outcome` at each exit: `quota_dormant`, `no_channel`, `audit_paused`, `stale_sync`, `daily_cap`, `no_video`, `unsafe_model`, `token_expired`, `audit_timeout`, `audit_failed`, `quarantined`, `applied`. Also set `channel_id` once the channel is picked. Without this the tick is opaque: it returns silently at eleven different points and the logs distinguish only some of them.

- **Step 9: Configure tracing at startup in `app/main.py`**

Add `from app import tracing` to the imports. In the startup hook, before `scheduler.start()`:

```python
    tracing.configure()
```

And in the shutdown hook, before `scheduler.shutdown(wait=False)`:

```python
    tracing.flush()
```

- **Step 10: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_evidence_loop_tracing.py -v`
Expected: PASS (5 tests)

- **Step 11: Confirm nothing regressed**

Run: `venv/bin/python -m pytest -q`
Expected: the 7 pre-existing `*_live.py` failures only. In particular `tests/test_reflection.py` must still pass — Step 3 restructured `_should_reflect` into a wrapper plus `_should_reflect_inner`, and those tests patch `_build_perf_report` and call `_should_reflect`, so they exercise the wrapper.

- **Step 12: Commit**

```bash
git add app/audits.py app/reflection.py app/measurement.py app/autopilot.py app/main.py tests/test_evidence_loop_tracing.py
git commit -m "feat(tracing): spans on the loop that is supposed to produce evidence

The bug that motivated this work — one channel with autopilot on and
measurement off, discarding 57 applies over a month — was invisible in the
logs and took reading an NDJSON export to find. apply.will_be_measured makes
it a one-day question.

Also instruments the decisions that were previously unobservable: what
_should_reflect decided and on what distribution (a trigger stuck on for
three months should be one glance), the dormant/coverage/hold mix from the
measurement sweep, and tick's outcome — it returns silently at eleven
different points and the logs distinguish only some of them.

_should_reflect and reflect are split into a span wrapper plus an _inner
holding the original body, so the span reads the perf report already in hand
rather than issuing a second query. The three reflection LLM calls now pass
labels, because they share one operation span and the parent cannot tell them
apart.

tick's existing try/except is untouched and still outermost: a crashing tick
is swallowed exactly as before, and now also recorded."
```

---

### Task 4: Stand up Phoenix

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Create: `docs/OBSERVABILITY.md`
- Modify: `CLAUDE.md` (a short note that the phoenix database is deliberately outside the snapshot)

**Interfaces:**
- Consumes: `OTEL_ENABLED`, `OTEL_ENDPOINT` from Task 1.
- Produces: a Phoenix UI on `127.0.0.1:6006`, backed by a `phoenix` database in the existing cluster.

Phoenix is last on purpose: Tasks 1–3 are all verified against an in-memory exporter, so none of them needed a container. This task's only job is somewhere for the spans to land.

- **Step 1: Create the `phoenix` database**

Phoenix creates its own tables but not its own database, and `POSTGRES_DB=midas` only ever created `midas`. The cluster already exists, so an `initdb` script would never run — create it directly:

```bash
docker compose up -d db
docker compose exec -T db psql -U midas -d midas -c "SELECT 'exists' FROM pg_database WHERE datname='phoenix'"
docker compose exec -T db createdb -U midas phoenix
```

Expected: the `SELECT` returns no rows the first time; `createdb` is silent on success. Re-running `createdb` errors with "already exists", which is safe to ignore.

- **Step 2: Add the service to `docker-compose.yml`**

Insert after the `db` service block (before the `postgrest` comment block):

```yaml
  # ── Phoenix (LLM + evidence-loop tracing) ────────────────────────────────
  # Its own database in the same cluster, NOT its own volume. Two reasons:
  # app/backup.py runs pg_dump against a single DSN rather than pg_dumpall, so
  # a separate database keeps trace data out of the NAS snapshot by
  # construction — traces are telemetry, losing them is not a DR event, and
  # they must not bloat the snapshot CLAUDE.md is built around. And a bind
  # mount whose source is missing on the office machine silently becomes a
  # directory, which is a failure mode this deployment has already hit once.
  phoenix:
    # Pinned, like postgrest and pgvector above. `version-20.3.0` was the
    # latest published tag on 2026-08-23; verify it still exists before
    # deploying and bump deliberately, never track `latest`.
    image: arizephoenix/phoenix:version-20.3.0
    container_name: midas-phoenix
    depends_on:
      db:
        condition: service_healthy
    environment:
      PHOENIX_SQL_DATABASE_URL: postgresql://${POSTGRES_USER:-midas}:${POSTGRES_PASSWORD}@db:5432/phoenix
      # Trace retention. Start conservative on a machine whose disk is shared
      # with the operational database; see docs/OBSERVABILITY.md before raising
      # it, and measure a real span size rather than guessing.
      PHOENIX_ENABLE_PROMETHEUS: "false"
    ports:
      # Loopback only, like every other service here. 6006 is the UI and the
      # OTLP/HTTP collector; the app reaches it in-network as http://phoenix:6006.
      - "127.0.0.1:6006:6006"
    restart: unless-stopped
```

Then add the two env vars to the `midas` service's `environment:` block:

```yaml
      OTEL_ENABLED: ${OTEL_ENABLED:-false}
      OTEL_ENDPOINT: ${OTEL_ENDPOINT:-http://phoenix:6006/v1/traces}
```

- **Step 3: Document the settings in `.env.example`**

```
# ── Observability ────────────────────────────────────────────────────────
# Tracing is opt-in. false (the default) makes every span a no-op, so the
# instrumentation costs nothing until you turn it on.
OTEL_ENABLED=false
# The Phoenix collector. Inside docker-compose the host is the service name;
# from the host machine it is http://localhost:6006/v1/traces.
OTEL_ENDPOINT=http://phoenix:6006/v1/traces
OTEL_SERVICE_NAME=midas
```

- **Step 4: Bring it up and verify a span lands end to end**

```bash
docker compose up -d phoenix
docker compose logs --tail=30 phoenix
```

Expected: Phoenix logs a successful migration against the `phoenix` database and starts serving. Then, from the host:

```bash
OTEL_ENABLED=true OTEL_ENDPOINT=http://localhost:6006/v1/traces \
PYTHONPATH=. venv/bin/python -c "
from app import tracing
tracing.configure()
with tracing.span('smoke_test', kind=tracing.LLM) as rec:
    rec.set(**{tracing.MODEL_NAME: 'smoke', tracing.TOKEN_TOTAL: 1})
tracing.flush()
print('sent')
"
```

Expected: prints `sent`, and a `smoke_test` span appears at http://localhost:6006 within a few seconds.

- **Step 5: Verify the fail-open promise against a real dead collector**

```bash
docker compose stop phoenix
OTEL_ENABLED=true OTEL_ENDPOINT=http://localhost:6006/v1/traces \
PYTHONPATH=. venv/bin/python -c "
from app import tracing
tracing.configure()
with tracing.span('smoke_test') as rec:
    rec.set(k='v')
tracing.flush()
print('survived a dead collector')
"
docker compose start phoenix
```

Expected: prints `survived a dead collector`, exit code 0. This is the single most important check in the plan — it is the difference between telemetry and an outage.

- **Step 6: Write `docs/OBSERVABILITY.md`**

```markdown
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
```

- **Step 7: Note the snapshot boundary in `CLAUDE.md`**

Append to the database section:

```markdown
The `phoenix` database (trace data) is deliberately outside the snapshot —
`pg_dump` runs against a single DSN, so only `midas` is captured. A restore
comes back with no trace history. That is intended: see
`docs/OBSERVABILITY.md`.
```

- **Step 8: Run the full suite**

Run: `venv/bin/python -m pytest -q`
Expected: the 7 pre-existing `*_live.py` failures only.

- **Step 9: Commit**

```bash
git add docker-compose.yml .env.example docs/OBSERVABILITY.md CLAUDE.md
git commit -m "feat(observability): self-host Phoenix beside the database

Its own database in the existing cluster rather than its own volume. pg_dump
runs against a single DSN, so a separate database keeps traces out of the NAS
snapshot by construction — telemetry, not a DR asset, and it must not bloat
the snapshot CLAUDE.md is built around. Avoiding a bind mount is deliberate
too: a missing mount source on the office machine silently becomes a
directory, which this deployment has hit before.

Loopback-only on 6006, matching every other service. OTEL_ENABLED defaults to
false, so nothing changes until an environment opts in.

Phoenix comes last because tasks 1-3 were verified against an in-memory
exporter and needed no container. The one thing this task verifies that they
could not: stopping the collector and confirming a traced block still exits
zero."
```

- **Step 10: Hand off the office-machine deployment**

The office machine has **no git checkout** — it runs `.env`, `docker-compose.yml`, and a `.bat`, hand-carried. The app image updates itself; these two files do not. So this task is not deployed until the user physically copies over:

1. the updated `docker-compose.yml` (new `phoenix` service, two new env vars on `midas`)
2. the `.env` additions from Step 3

And runs Step 1 there to create the `phoenix` database, because the cluster on that machine already exists too.

Tell the user this explicitly rather than assuming a pull. Note also that `OTEL_ENABLED` should stay `false` on the first deploy — bring the service up, confirm it is healthy, then flip the flag, so a Phoenix misconfiguration cannot coincide with the app restart that would be blamed for it.

---

## Self-Review

**Spec coverage.** Step 3 of the spec maps as follows: separate `phoenix` database and snapshot exclusion → Task 4 Steps 1–2, 7; `app/tracing.py` as sole OTel importer → Task 1, with the guard test enforcing it; fail-open → Task 1 tests plus Task 4 Step 5 against a genuinely stopped collector; manual not auto instrumentation → Task 2; every LLM attribute named in the spec's table → Task 2 Step 1 tests. `llm.call_site` from the spec's table is intentionally **not** implemented — the parent operation span from Task 3 supplies that context, and where one operation makes several calls (`reflect`) the `label` keyword disambiguates them. `llm.latency_ms` is also dropped: span duration is already the measurement, and a hand-computed attribute would be a second, driftable definition of the same number. A third departure: the spec mentions publishing OTLP gRPC port 4317, and the compose file publishes only 6006 (UI + OTLP/HTTP). The app exports over HTTP and nothing in the stack speaks gRPC, so 4317 would be published surface with no consumer on a box that binds everything to loopback precisely to avoid that. All three departures are recorded here rather than silently omitted. Evidence-loop spans → Task 3, with `apply.will_be_measured` as the attribute that would have caught the motivating bug.

**Placeholders.** None. Every code step carries the actual code; every verification step names the command and the expected result.

**Type consistency.** `Recorder.set(**attributes)` is the only setter, used identically in Tasks 2 and 3. `tracing.span(name, kind=..., **attributes)` keeps one signature throughout. `_record_apply_measurability(rec, channel)` is asserted in Task 3 Step 1 and defined in Step 6 with matching parameters. The `label` keyword introduced in Task 2 is consumed in Task 3 Step 4. `_reset_for_tests(exporter=None, disable=False)` matches all three fixture uses.

**One risk worth flagging to the executor.** Task 3 Steps 3 and 5 split `_should_reflect` and `reflect` into a span wrapper plus an `_inner`. `_should_reflect_inner` must return a three-tuple from *every* branch — there are five `return` statements in the current function, and missing one produces a silent unpacking error at runtime rather than a test failure, because the existing tests only patch `_build_perf_report`. Re-read the whole function before editing, and run `tests/test_reflection.py` immediately after.
