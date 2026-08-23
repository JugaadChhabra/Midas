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


def test_a_raising_exporter_is_invisible_to_the_caller():
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


def test_flush_cannot_block_past_the_container_grace_period(monkeypatch):
    """An unbounded force_flush is a shutdown hazard, not just slow telemetry.

    TracerProvider.force_flush defaults to 30s and the OTLP exporter retries
    inside that window; the container's stop grace is 10s. Flushing without a
    bound means SIGKILL before the rest of the shutdown path runs.
    """
    seen = []

    class RecordingProvider:
        def force_flush(self, timeout_millis=None):
            seen.append(timeout_millis)
            return True

    monkeypatch.setattr(tracing, "_provider", RecordingProvider())
    tracing.flush()

    assert seen, "flush() did not call force_flush at all"
    timeout = seen[0]
    assert timeout is not None, "force_flush was left to its 30s default"
    assert 0 < timeout <= 5000, f"flush timeout {timeout}ms is not a usable bound"


def test_configure_does_not_build_a_second_provider(monkeypatch):
    """Idempotency, on the path where it can actually go wrong.

    With OTEL_ENABLED false configure() returns on line 2, so a test written
    that way asserts nothing. Here the enabled path really runs — with a
    collectorless exporter, so no socket and no live Phoenix is needed — and the
    second call must reuse what the first built rather than stacking another
    provider and another BatchSpanProcessor onto the process.
    """
    from opentelemetry.exporter.otlp.proto.http import trace_exporter
    from opentelemetry.sdk import trace as sdk_trace

    built = []

    class _Collectorless:
        """Stands in for the OTLP exporter: no socket, no retry loop."""

        def export(self, spans):
            return None

        def shutdown(self):
            return None

        def force_flush(self, timeout_millis=None):
            return True

    class _CountingProvider(sdk_trace.TracerProvider):
        def __init__(self, *args, **kwargs):
            # No atexit hook, for the same reason _reset_for_tests skips one:
            # a provider built inside a test must not still be shutting down at
            # interpreter exit, long after the test that made it.
            kwargs["shutdown_on_exit"] = False
            super().__init__(*args, **kwargs)
            built.append(self)

    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter",
                        lambda **kwargs: _Collectorless())
    monkeypatch.setattr(sdk_trace, "TracerProvider", _CountingProvider)
    monkeypatch.setattr(tracing.settings, "OTEL_ENABLED", True)
    monkeypatch.setattr(tracing, "_configured", False)
    monkeypatch.setattr(tracing, "_tracer", None)
    monkeypatch.setattr(tracing, "_provider", None)

    tracing.configure()
    first_tracer, first_provider = tracing._tracer, tracing._provider
    tracing.configure()

    # Guards against the vacuous version of this test: if the enabled path had
    # silently failed open, everything below would pass on None == None.
    assert first_tracer is not None and first_provider is not None
    assert len(built) == 1, f"configure() built {len(built)} providers, not 1"
    assert tracing._tracer is first_tracer
    assert tracing._provider is first_provider

    built[0].shutdown()


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
