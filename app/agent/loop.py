"""Slice 3 · S3.4 — the title agent's loop (spec Part 6 S3.4, Part 2 §3.1, F5, F11, F14; #119).

    run_title_agent(video)  -- AgentResult: a title, a decline, or a failure,
                               with the run's trajectory

Hand-rolled: each turn sends the messages and every tool's schema to
`openrouter.chat_tools` (AUDIT_MODEL, the reasoning model; the writer tool
uses WRITER_MODEL), runs the tools the model called (app/agent/tools.py) and
sends their results back as JSON text, a tool's error included. It ends on a
terminal tool or after AGENT_MAX_TURNS turns:

  - `submit_title` passing `titles.check` -> `title`; failing, the failure
    goes back to the model once, and a second failing submit -> `failed`,
    `checks_failed`;
  - `decline` -> `decline` (no YouTube call, no quota);
  - no terminal tool by the last turn -> `failed`, `turn_cap`.

The trajectory (`interventions.trajectory`, written by app/agent_tick.py on
every agent row) is the model, the turns, how the run ended, each submitted
title with its check, and every message, tool call and tool result, each
text cut to TRAJECTORY_CHARS. If chat_tools raises (OpenRouter down after its
retry), the exception goes on to the caller with the trajectory so far as its
`trajectory` attribute.
"""
from __future__ import annotations

import json
import logging
from typing import NamedTuple

from app import titles
from app.agent import tools
from app.config import settings
from app.openrouter import chat_tools

log = logging.getLogger("midas.agent")

TITLE = "title"
DECLINE = "decline"
FAILED = "failed"
#: A failed run's reason (`payload.error.reason` on its cancelled row).
TURN_CAP = "turn_cap"
CHECKS_FAILED = "checks_failed"

#: Each message, tool call and tool result is cut to this many characters in
#: the trajectory (the model gets them whole).
TRAJECTORY_CHARS = 2000

#: Sent when the model answers without calling a tool.
NUDGE = "Call a tool. End with submit_title or decline."


class AgentResult(NamedTuple):
    """`kind` "title" | "decline" | "failed"; `title` for a title; `reason`
    the model's reasoning (title), its reason (decline), or `turn_cap` /
    `checks_failed` (failed); `trajectory` the stored run."""
    kind: str
    title: str | None
    reason: str | None
    trajectory: dict


def _cut(text) -> str | None:
    return None if text is None else str(text)[:TRAJECTORY_CHARS]


def _first_message(subject: tools.Subject) -> str:
    return f"Video: {subject.video['id']}\nChannel language: {subject.channel.language}"


def tools_called(trajectory: dict) -> list[str]:
    """The tool names the run called, in order (terminal ones included)."""
    return [c["name"] for m in trajectory.get("messages", ())
            for c in m.get("tool_calls") or ()]


def run_title_agent(video: dict, *, channel: titles.ChannelContext | None = None
                    ) -> AgentResult:
    """Run the title agent on `video` (a `videos` row). `channel` is its
    channel's `titles.channel_context`, read when not passed. Writes nothing."""
    channel = channel or titles.channel_context(video["channel_id"])
    subject = tools.Subject({**video, "default_language": channel.language}, channel)
    model = settings.AUDIT_MODEL
    messages = [{"role": "system", "content": titles.agent_system_prompt()},
                {"role": "user", "content": _first_message(subject)}]
    trajectory = {"model": model, "writer_model": settings.WRITER_MODEL,
                  "max_turns": settings.AGENT_MAX_TURNS, "turns": 0, "end": None,
                  "submits": [],
                  "messages": [{"role": m["role"], "content": _cut(m["content"])}
                               for m in messages]}

    def end(kind: str, title: str | None, reason: str | None,
            detail: str | None = None) -> AgentResult:
        trajectory["end"] = {"kind": kind, "reason": reason if kind == FAILED else None,
                             "detail": detail}
        return AgentResult(kind, title, reason, trajectory)

    def send(entry: dict, message: dict) -> None:
        messages.append(message)
        trajectory["messages"].append(entry)

    for turn in range(1, settings.AGENT_MAX_TURNS + 1):
        trajectory["turns"] = turn
        try:
            reply = chat_tools(messages, tools.SCHEMAS, model=model, label="agent.title")
        except Exception as e:
            trajectory["end"] = {"kind": FAILED, "reason": "exception",
                                 "detail": f"{type(e).__name__}: {e}"}
            e.trajectory = trajectory
            raise
        calls = reply.get("tool_calls") or []
        assistant = {"role": "assistant", "content": reply.get("content")}
        if calls:
            assistant["tool_calls"] = calls
        send({"role": "assistant", "content": _cut(reply.get("content")),
              "tool_calls": [{"id": c.get("id"), "name": (c.get("function") or {}).get("name"),
                              "arguments": _cut((c.get("function") or {}).get("arguments"))}
                             for c in calls]},
             assistant)
        if not calls:
            send({"role": "user", "content": NUDGE}, {"role": "user", "content": NUDGE})
            continue
        for c in calls:
            name = (c.get("function") or {}).get("name")
            raw = (c.get("function") or {}).get("arguments") or "{}"
            try:
                args = raw if isinstance(raw, dict) else json.loads(raw)
                if not isinstance(args, dict):
                    raise ValueError("not an object")
            except (TypeError, ValueError) as e:
                args, result = None, {"error": f"arguments are not a JSON object: {e}"}
            if args is not None and name == tools.DECLINE:
                return end(DECLINE, None, str(args.get("reason") or ""))
            if args is not None and name == tools.SUBMIT_TITLE:
                title = args.get("title")
                failure = (titles.check(title.strip(), subject.video)
                           if isinstance(title, str) else "title: not a string")
                trajectory["submits"].append({"title": _cut(title), "check": failure,
                                              "reasoning": _cut(args.get("reasoning"))})
                if failure is None:
                    return end(TITLE, title.strip(), str(args.get("reasoning") or ""))
                if len(trajectory["submits"]) >= 2:
                    return end(FAILED, None, CHECKS_FAILED, "; ".join(
                        f"{s['title']!r}: {s['check']}" for s in trajectory["submits"]))
                result = {"error": f"check failed: {failure}. Submit once more, or decline; "
                                   "a second failing title ends the run."}
            elif args is not None:
                result = tools.call(name, subject, args)
            content = json.dumps(result, ensure_ascii=False, default=str)
            send({"role": "tool", "tool_call_id": c.get("id"), "name": name,
                  "content": _cut(content)},
                 {"role": "tool", "tool_call_id": c.get("id"), "content": content})
    return end(FAILED, None, TURN_CAP, f"no submit_title or decline in "
                                       f"{settings.AGENT_MAX_TURNS} turns")
