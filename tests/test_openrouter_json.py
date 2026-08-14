"""chat_json must find the JSON object even when the model talks around it.

The `:online` web-search variants narrate. A live probe of
`anthropic/claude-opus-5:online` on 2026-08-13 returned, verbatim in shape:

    I'll research current YouTube SEO practices for kids' content before
    building this.```json
    {"generated_prompt": "..."}
    ```
    ...and the compilation/loop-stream note comes from evergreen demand...

So `response_format: {"type": "json_object"}` is NOT enforced once the web plugin
is active: there is a preamble, a fence that is not at position 0, and trailing
prose after the closing brace. The old fence-stripper only fired on
`content.startswith("```")`, so it missed this entirely and the parse fell
through to json_repair — which happened to rescue it. That is luck, not a
contract, and this is the highest-leverage call in the system: its output becomes
the standing audit prompt for a whole channel.

Extracting the outermost {...} span handles all three cases deterministically and
leaves json_repair as the genuine last resort it was meant to be.
"""
from __future__ import annotations

import pytest

from app.openrouter import _extract_json_object

# The exact shape probe A returned — preamble, mid-string fence, trailing prose.
ONLINE_REPLY = (
    "I'll research current YouTube SEO practices for kids' content before "
    'building this.```json\n{\n  "generated_prompt": "ROLE\\nYou are the '
    'METADATA AUDITOR."\n}\n```\n\n...and the compilation/loop-stream note comes '
    "from evergreen demand and long background-viewing sessions in kids content."
)


def test_plain_json_is_returned_unchanged():
    """The overwhelmingly common case: the model honoured json_object."""
    assert _extract_json_object('{"a": 1}') == '{"a": 1}'


def test_fence_at_position_zero_still_works():
    """The case the old code did handle — don't regress it."""
    assert _extract_json_object('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_preamble_before_a_fence_is_stripped():
    """The :online failure. The old startswith('```') check missed this."""
    out = _extract_json_object(ONLINE_REPLY)
    import json

    assert json.loads(out)["generated_prompt"].startswith("ROLE")


def test_trailing_prose_after_the_object_is_dropped():
    assert _extract_json_object('{"a": 1}\n\nHope that helps!') == '{"a": 1}'


def test_nested_braces_are_not_truncated():
    """Slicing to the LAST closing brace, not the first, is what makes the real
    audit payload survive — comparisons/issues nest several levels deep."""
    src = '{"comparisons": {"title": {"suggested": "x"}}, "issues": []}'
    assert _extract_json_object(f"here you go:\n{src}\ndone") == src


def test_braces_inside_strings_do_not_confuse_it():
    src = '{"prompt": "return {{\\"a\\": 1}} exactly"}'
    import json

    assert json.loads(_extract_json_object(src))["prompt"].startswith("return")


@pytest.mark.parametrize("text", ["", "no json here at all", "[1, 2, 3]"])
def test_no_object_falls_through_unchanged(text):
    """Return the input untouched so the caller's own error path — and its error
    message quoting the raw content — stays intact."""
    assert _extract_json_object(text) == text
