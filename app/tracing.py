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


#: Milliseconds `flush()` will wait for the exporter, and no longer.
#
# `TracerProvider.force_flush` defaults to 30_000ms, and the OTLP/HTTP exporter
# retries with backoff inside that window — so with Phoenix down, an unbounded
# flush blocks for half a minute. The `midas` service declares no
# `stop_grace_period`, so Docker's default is 10s: the container would be
# SIGKILLed mid-flush and everything queued after `flush()` in the shutdown path
# would never run. A telemetry outage must not change how the app shuts down.
FLUSH_TIMEOUT_MS = 2000


def flush() -> None:
    """Best-effort flush of pending spans. Never raises, never blocks long.

    For process shutdown and for tests that need the export path to run before
    assertions rather than at interpreter exit.
    """
    if _provider is None:
        return
    try:
        _provider.force_flush(FLUSH_TIMEOUT_MS)
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
    # No atexit hook. TracerProvider registers its own `shutdown` at exit, and
    # this function is called ~40+ times a run — each call would leak a provider
    # AND a fresh hook, all of which fire at interpreter exit, long after the
    # test that installed the exporter. The deliberately-exploding exporter in
    # tests/test_tracing.py then raised there, ending an all-green suite's
    # stderr in a traceback indistinguishable from a real failure.
    _provider = TracerProvider(shutdown_on_exit=False)
    # Simple, not batched: tests assert on spans immediately after the block.
    _provider.add_span_processor(SimpleSpanProcessor(exporter))
    # `trace.set_tracer_provider` refuses to overwrite, so hold the tracer
    # directly instead of going through the global.
    _tracer = _provider.get_tracer("midas-test")
    return exporter
