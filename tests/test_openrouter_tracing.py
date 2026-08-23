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
