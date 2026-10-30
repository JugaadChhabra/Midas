"""Slice 3 · S3.4 (#119): the title agent's loop and its tools.

The real loop, tools, checks, title context and stamp run against
FakeSupabase (the S3.2 world, tests/test_titles.py); OpenRouter is faked at
the edge: `chat_tools` (the reasoning model) and `titles.chat_json` (the
writer).
"""
import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app import titles
from app.agent import loop, tools
from tests.test_titles import A, C, CH, D, E, MARATHI, _video, replies, world
from tests.test_titles import wired as titles_wired


@contextmanager
def wired(sb, **kw):
    with titles_wired(sb, **kw) as writer, patch("app.agent.tools.supabase", return_value=sb):
        yield writer


def call(name, cid=None, **args):
    return {"id": cid or f"call_{name}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


class Model:
    """A fake chat_tools answering each turn with the next scripted reply (a
    list of tool calls, or a string of text), recording what it was sent."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.sent: list[list[dict]] = []

    def __call__(self, messages, tools_, *, model=None, label=None):
        self.sent.append([dict(m) for m in messages])
        self.model, self.label, self.tools = model, label, tools_
        turn = self.turns.pop(0) if self.turns else [call("get_video")]
        if isinstance(turn, str):
            return {"role": "assistant", "content": turn}
        return {"role": "assistant", "content": None, "tool_calls": turn}

    def tool_results(self, turn: int) -> list[dict]:
        """The tool results the model was sent on `turn` (1-based)."""
        return [json.loads(m["content"]) for m in self.sent[turn - 1] if m["role"] == "tool"]


def run(model, *, chat=None, video=A, **settings_):
    sb = world()
    with wired(sb, chat=chat) as writer, \
         patch("app.agent.loop.chat_tools", side_effect=model), \
         patch.multiple(titles.settings, AUDIT_MODEL="reasoning/model",
                        **{"AGENT_MAX_TURNS": 12, **settings_}):
        result = loop.run_title_agent(_video(video))
    return result, sb, writer


# ── how a run ends ────────────────────────────────────────────────────────

def test_a_valid_submit_ends_with_the_title():
    model = Model([call("get_video"), call("get_search_terms")],
                  [call("submit_title", title=MARATHI, reasoning="plain words")])
    result, sb, _ = run(model)
    assert (result.kind, result.title, result.reason) == ("title", MARATHI, "plain words")
    assert result.trajectory["turns"] == 2 and result.trajectory["model"] == "reasoning/model"
    assert result.trajectory["end"] == {"kind": "title", "reason": None, "detail": None}
    assert loop.tools_called(result.trajectory) == ["get_video", "get_search_terms",
                                                    "submit_title"]
    assert model.model == "reasoning/model" and model.label == "agent.title"
    assert {t["function"]["name"] for t in model.tools} == {
        "get_video", "get_transcript", "get_traffic_mix", "get_search_terms",
        "get_channel_top_performers", "get_title_history", "write_candidates",
        "submit_title", "decline"}
    assert sb.writes == []


def test_the_first_messages_are_the_agent_prompt_and_the_video_id_and_language_only():
    model = Model([call("decline", reason="works")])
    run(model)
    system, user = model.sent[0]
    assert system == {"role": "system", "content": titles.agent_system_prompt()}
    assert "a title that\n  already works is a valid outcome" in system["content"]
    assert titles.TITLE_BRIEF.format(title_max=100) in system["content"]
    assert user == {"role": "user", "content": f"Video: {A}\nChannel language: mr (Marathi)"}


def test_decline_ends_the_run_with_its_reason():
    result, sb, writer = run(Model([call("decline", reason="the title already works")]))
    assert (result.kind, result.title, result.reason) == (
        "decline", None, "the title already works")
    assert result.trajectory["end"]["kind"] == "decline"
    writer.assert_not_called()
    assert sb.writes == []


def test_the_turn_cap_ends_failed():
    model = Model()                                  # get_video, forever
    result, _, _ = run(model, AGENT_MAX_TURNS=3)
    assert (result.kind, result.title, result.reason) == ("failed", None, "turn_cap")
    assert len(model.sent) == 3 and result.trajectory["turns"] == 3
    assert result.trajectory["end"]["reason"] == "turn_cap"


def test_an_invalid_submit_gets_its_failure_back_once_then_fails():
    model = Model([call("submit_title", title="Twinkle in English", reasoning="r1")],
                  [call("submit_title", title="Still English", reasoning="r2")])
    result, _, _ = run(model)
    [back] = model.tool_results(2)
    assert "check failed: script: no Devanagari character" in back["error"]
    assert (result.kind, result.reason) == ("failed", "checks_failed")
    assert [s["check"] for s in result.trajectory["submits"]] == [
        "script: no Devanagari character"] * 2
    assert "Still English" in result.trajectory["end"]["detail"]
    assert len(model.sent) == 2


def test_an_invalid_submit_can_be_followed_by_a_valid_one():
    model = Model([call("submit_title", title=f"Rhyme {A}", reasoning="same")],
                  [call("submit_title", title=MARATHI, reasoning="fixed")])
    result, _, _ = run(model)
    assert (result.kind, result.title) == ("title", MARATHI)
    assert [s["check"] for s in result.trajectory["submits"]] == [
        "unchanged: the same as the current title", None]


def test_a_text_reply_is_nudged_to_call_a_tool():
    model = Model("I think the title is fine.", [call("decline", reason="fine")])
    result, _, _ = run(model)
    assert result.kind == "decline"
    assert model.sent[1][-1] == {"role": "user", "content": loop.NUDGE}


# ── tool errors come back as text ─────────────────────────────────────────

def test_tool_errors_come_back_to_the_model_as_text():
    bad_json = {"id": "c9", "type": "function",
                "function": {"name": "get_video", "arguments": "{not json"}}
    model = Model([call("get_channel_top_performers", order="middle"), call("no_such_tool"),
                   bad_json, call("get_video", surprise=1), call("get_search_terms")],
                  [call("decline", reason="r")])
    with patch.object(titles, "_search_terms", side_effect=RuntimeError("db down")):
        result, _, _ = run(model)
    errors = [r["error"] for r in model.tool_results(2)]
    assert errors[0] == "order must be 'best' or 'worst', not 'middle'"
    assert errors[1] == "unknown tool 'no_such_tool'"
    assert errors[2].startswith("arguments are not a JSON object")
    assert errors[3].startswith("TypeError")
    assert errors[4] == "RuntimeError: db down"
    tool_messages = [m for m in model.sent[1] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == [
        "call_get_channel_top_performers", "call_no_such_tool", "c9", "call_get_video",
        "call_get_search_terms"]
    assert result.kind == "decline"


def test_a_chat_tools_failure_raises_with_the_trajectory_so_far():
    model = Model([call("get_video")])

    def flaky(messages, tools_, **kw):
        if len(model.sent) == 1:
            raise RuntimeError("OpenRouter 503")
        return model(messages, tools_, **kw)

    with pytest.raises(RuntimeError) as e:
        run(flaky)
    assert e.value.trajectory["turns"] == 2
    assert e.value.trajectory["end"] == {"kind": "failed", "reason": "exception",
                                         "detail": "RuntimeError: OpenRouter 503"}
    assert loop.tools_called(e.value.trajectory) == ["get_video"]


# ── the trajectory ────────────────────────────────────────────────────────

def test_the_trajectory_cuts_each_text_to_2000_characters_but_the_model_gets_it_whole():
    long_transcript = "ट्विंकल " * 900                     # ~7,200 characters
    model = Model([call("get_transcript")], [call("decline", reason="x" * 3000)])
    with patch.object(titles, "_transcript", return_value=long_transcript):
        result, _, _ = run(model)
    [sent] = model.tool_results(2)
    assert sent["text"] == long_transcript
    entries = result.trajectory["messages"]
    assert [e["role"] for e in entries] == ["system", "user", "assistant", "tool",
                                            "assistant"]
    assert len(entries[3]["content"]) == loop.TRAJECTORY_CHARS
    assert all(len(e["content"] or "") <= loop.TRAJECTORY_CHARS for e in entries)
    assert all(len(c["arguments"]) <= loop.TRAJECTORY_CHARS
               for e in entries for c in e.get("tool_calls") or ())
    json.dumps(result.trajectory)                        # storable as jsonb


# ── the tools ─────────────────────────────────────────────────────────────

def _subject(sb, vid=A, cache_only=True):
    channel = titles.channel_context(CH)
    return tools.Subject({**_video(vid), "default_language": channel.language}, channel,
                         cache_only)


def test_get_video_get_transcript_get_traffic_mix():
    sb = world()
    with wired(sb), patch.object(titles.settings, "TRANSCRIPT_MAX_CHARS", 8):
        s = _subject(sb)
        v = tools.get_video(s)
        assert v == {"video_id": A, "title": f"Rhyme {A}",
                     "description": "Twinkle twinkle\nLyrics", "default_language": "mr",
                     "impressions_28d": 5000, "ctr_28d": 0.02,
                     "channel_median_ctr": 0.0275}
        assert tools.get_transcript(s) == {"available": True, "text": "twinkle "}
        assert tools.get_transcript(_subject(sb, C)) == {"available": False}
        assert tools.get_traffic_mix(s) == {"views_by_source_28d": {
            "Browse features": 10, "YouTube search": 135}}
    assert sb.writes == []


def test_get_search_terms_returns_at_most_25():
    sb = world()
    sb._tables["video_traffic_source_daily"] += [
        {"id": 100 + i, "video_id": A, "channel_id": CH, "date": "2026-10-19",
         "source_type": 5, "source_detail": f"term {i:02d}", "views": 1} for i in range(30)]
    with wired(sb):
        terms = tools.get_search_terms(_subject(sb))["search_terms"]
    assert len(terms) == 25
    assert terms[:2] == [{"term": "twinkle", "views": 30}, {"term": "baa baa", "views": 5}]


def test_get_channel_top_performers_best_and_worst_leave_the_video_out():
    sb = world()
    with wired(sb):
        best = tools.get_channel_top_performers(_subject(sb, C))
        worst = tools.get_channel_top_performers(_subject(sb, C), order="worst")
    assert best["order"] == "best"
    assert [v["video_id"] for v in best["videos"]] == [D, A]        # C left out
    # No browse or suggested views: 0, ties by id.
    assert [v["video_id"] for v in worst["videos"]][:3] == ["bVideo00001", "bigVideo001", E]
    assert C not in {v["video_id"] for v in worst["videos"]}
    assert worst["videos"][0]["views_per_impression"] == 0
    assert len(worst["videos"]) <= tools.TOP_PERFORMERS


def test_get_title_history_is_newest_first_and_capped():
    sb = world()
    sb._tables["audits"] = [
        {"id": i, "video_id": A, "created_at": f"2026-09-{i:02d}T00:00:00+00:00",
         "title_before": f"old {i}", "suggested_title": f"house {i}", "status": "applied",
         "measurement_status": "neutral"} for i in range(1, 13)]
    sb._tables["interventions"] = [
        {"id": 1, "video_id": A, "lever": "title", "origin": "midas", "status": "judged",
         "created_at": "2026-10-05T00:00:00+00:00", "payload": {"title": "agent title"},
         "measurement_result": {"delta": -0.2}},
        {"id": 2, "video_id": A, "lever": "backlinks", "origin": "midas",
         "status": "measuring", "created_at": "2026-10-06T00:00:00+00:00", "payload": {}},
        {"id": 3, "video_id": E, "lever": "title", "origin": "midas", "status": "judged",
         "created_at": "2026-10-07T00:00:00+00:00", "payload": {"title": "not A"}}]
    with wired(sb):
        history = tools.get_title_history(_subject(sb))["history"]
    assert len(history) == 10
    assert history[0] == {"kind": "title_intervention", "created_at": "2026-10-05T00:00:00+00:00",
                          "origin": "midas", "status": "judged", "title": "agent title",
                          "delta": -0.2}
    assert history[1] == {"kind": "audit", "created_at": "2026-09-12T00:00:00+00:00",
                          "title_before": "old 12", "title": "house 12", "status": "applied",
                          "measurement_status": "neutral"}
    assert [h["created_at"] for h in history] == sorted(
        (h["created_at"] for h in history), reverse=True)


def test_write_candidates_is_the_writer_on_the_title_context():
    sb = world()
    with wired(sb, chat=replies([MARATHI, "two"])) as writer:
        out = tools.write_candidates(_subject(sb))
    assert out == {"candidates": [{"title": MARATHI, "reason": f"why {MARATHI}"},
                                  {"title": "two", "reason": "why two"}]}
    assert writer.call_args.kwargs["model"] == "writer/model"
    assert writer.call_args.kwargs["label"] == "titles.write"
    assert "Current title: Rhyme aVideo00001" in writer.call_args.args[0]
    assert sb.writes == []


def test_the_agent_stamp_hashes_its_own_prompt_and_reasoning_model():
    with patch.object(titles.settings, "AUDIT_MODEL", "reasoning/a"):
        a, inputs = titles.strategy_inputs(titles.AGENT)
        pipeline, _ = titles.strategy_inputs(titles.PIPELINE)
    with patch.object(titles.settings, "AUDIT_MODEL", "reasoning/b"):
        b, _ = titles.strategy_inputs(titles.AGENT)
        assert titles.strategy_inputs(titles.PIPELINE)[0] == pipeline
    assert inputs["agent_model"] == "reasoning/a"
    assert inputs["prompt_sha256"] != titles.strategy_inputs(titles.PIPELINE)[1]["prompt_sha256"]
    assert len({a, b, pipeline}) == 3
