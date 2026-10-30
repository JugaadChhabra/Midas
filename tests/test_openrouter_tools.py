"""Slice 3 · S3.4 (#119): `chat_tools`, the agent loop's OpenRouter call.

httpx is faked at the edge; the real span recorder runs.
"""
from unittest.mock import patch

import httpx
import pytest

from app import tracing
from app.openrouter import chat_tools

TOOLS = [{"type": "function", "function": {"name": "decline", "parameters": {"type": "object"}}}]
MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "video abc"}]
CALL = {"id": "c1", "type": "function", "function": {"name": "decline", "arguments": "{}"}}


@pytest.fixture(autouse=True)
def _isolated_tracer():
    exporter = tracing._reset_for_tests()
    yield exporter
    tracing._reset_for_tests(disable=True)


def _ok(message=None):
    return httpx.Response(200, json={
        "choices": [{"message": message or {"role": "assistant", "content": None,
                                            "tool_calls": [CALL]}}],
        "model": "m", "usage": {"prompt_tokens": 1, "completion_tokens": 2,
                                "total_tokens": 3, "cost": 0.1}})


def _call(post):
    with patch("app.openrouter.httpx.post", side_effect=post) as p, \
         patch("app.openrouter.settings") as s:
        s.OPENROUTER_API_KEY = "k"
        s.AUDIT_MODEL = "reasoning/model"
        return chat_tools(MESSAGES, TOOLS, label="agent.title"), p


def test_returns_the_assistant_message_with_its_tool_calls(_isolated_tracer):
    message, post = _call([_ok()])
    assert message["tool_calls"] == [CALL]
    body = post.call_args.kwargs["json"]
    assert body == {"model": "reasoning/model", "messages": MESSAGES, "tools": TOOLS,
                    "tool_choice": "auto"}
    [span] = _isolated_tracer.get_finished_spans()
    assert span.name == "agent.title"
    assert span.attributes[tracing.SPAN_KIND] == tracing.LLM
    assert span.attributes[tracing.TOKEN_TOTAL] == 3
    assert span.attributes["llm.tool_calls"] == 1


def test_text_content_comes_back_unparsed():
    message, _ = _call([_ok({"role": "assistant", "content": "not json {"})])
    assert message == {"role": "assistant", "content": "not json {"}


@pytest.mark.parametrize("first", [httpx.ReadTimeout("slow"), httpx.Response(503, text="busy")])
def test_one_retry_on_a_timeout_or_a_5xx(first):
    message, post = _call([first, _ok()])
    assert post.call_count == 2 and message["tool_calls"] == [CALL]


def test_a_second_failure_raises():
    with pytest.raises(RuntimeError, match="502"):
        _call([httpx.Response(500), httpx.Response(502, text="bad gateway")])
    with pytest.raises(httpx.ReadTimeout):
        _call([httpx.ReadTimeout("a"), httpx.ReadTimeout("b")])


def test_a_4xx_is_not_retried():
    with patch("app.openrouter.httpx.post", return_value=httpx.Response(400, text="no")) as p, \
         patch("app.openrouter.settings") as s, pytest.raises(RuntimeError, match="400"):
        s.OPENROUTER_API_KEY = "k"
        chat_tools(MESSAGES, TOOLS, model="m")
    assert p.call_count == 1
