"""Phase B · B5 — decide() and the decision_log, shadow only (spec Part 3 B5, Part 2 §2.2, §7; #36).

A decision is one question from a question set, asked about one subject (a
video, a pair, a candidate):

    decide(question_set, subject, context) -> Decision

The rules answer it in code; a backend (DECIDE_BACKEND) answers it too, with
probabilities. In Phase B every decision is a shadow decision: both answers go
to `decision_log`, stamped with QUESTION_SET_VERSION, and only the rules answer
is returned. A backend that fails, including the jev stub until access exists,
leaves the rules answer standing and logs the row without a backend answer;
decide() never raises over a backend.

QUESTION_SET_VERSION covers every question set defined here: bump it when a
question, its answers or its rules change. It is hashed into the A6 strategy
stamp (app/audits.py strategy_version), so a stamp names the questions that
produced it.

Nothing in Phase B calls decide(); Slice 1's triage does.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from app import openrouter
from app.config import settings
from app.db import supabase
from app.status_vocab import DecisionUsed

log = logging.getLogger(__name__)

QUESTION_SET_VERSION = "2026.10-b5-v1"


@dataclass(frozen=True)
class Decision:
    """One answer to a question set: the answer and a probability per allowed answer.

    The rules answer carries 1.0 on itself and 0.0 on the rest; a backend's
    carries what it reports.
    """

    question_set: str
    answer: str
    probs: dict[str, float]


@dataclass(frozen=True)
class QuestionSet:
    name: str
    question: str
    answers: tuple[str, ...]
    #: The rules baseline: context -> one of `answers`.
    rules: Callable[[dict], str]


class NotConfigured(Exception):
    """The backend has no access set up (jev, until Phase B is over)."""


def _triage_rules(context: dict) -> str:
    """Spec Part 2 §2.2: backlinks if the description has no related block and
    at least BACKLINK_MIN_CANDIDATES candidates exist; otherwise no_change."""
    if (not context.get("has_related_block")
            and (context.get("backlink_candidates") or 0) >= settings.BACKLINK_MIN_CANDIDATES):
        return "backlinks"
    return "no_change"


TRIAGE = QuestionSet(
    name="triage",
    question=(
        "Which lever, if any, should change this video this week to route more "
        "viewers to it? `backlinks`: add a related-videos block to its "
        "description. `playlist`: add it to a playlist. `short_link`: link a "
        "Short to it. `title`: rewrite its title. `no_change`: leave it alone."
    ),
    # Spec Part 2 §2.2's options. The rules choose only backlinks or no_change
    # (Slice 1); the backend may choose any.
    answers=("no_change", "backlinks", "playlist", "short_link", "title"),
    rules=_triage_rules,
)


def _validated(question_set: QuestionSet, answer, probs) -> Decision:
    """A Decision, or ValueError when the answer or probabilities are malformed.

    Every allowed answer needs a probability (spec Part 2 §2.2); they aren't
    required to sum to 1.
    """
    if answer not in question_set.answers:
        raise ValueError(f"answer {answer!r} not in {list(question_set.answers)}")
    if not isinstance(probs, dict):
        raise ValueError(f"probs must be an object, got {type(probs).__name__}")
    clean = {}
    for key, p in probs.items():
        if key not in question_set.answers:
            raise ValueError(f"probability for unknown answer {key!r}")
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1:
            raise ValueError(f"probability for {key!r} must be in [0, 1], got {p!r}")
        clean[key] = float(p)
    if set(clean) != set(question_set.answers):
        raise ValueError(f"probs must cover every answer {list(question_set.answers)}, got {sorted(clean)}")
    return Decision(question_set=question_set.name, answer=answer, probs=clean)


_LLM_SYSTEM = (
    "You answer one multiple-choice question about a YouTube video for a kids' "
    "nursery-rhyme channel network. Choose exactly one of the allowed answers and "
    "give your probability for each allowed answer."
)


def _llm_backend(question_set: QuestionSet, subject: str, context: dict) -> Decision:
    prompt = "\n".join([
        f"QUESTION: {question_set.question}",
        f"ALLOWED ANSWERS: {', '.join(question_set.answers)}",
        f"SUBJECT: {subject}",
        f"CONTEXT: {json.dumps(context, sort_keys=True, default=str)}",
        "",
        'Return only JSON: {"answer": "<one allowed answer>", '
        '"probs": {"<allowed answer>": <probability 0..1>, ...}}',
    ])
    reply = openrouter.chat_json(prompt, system=_LLM_SYSTEM, label=f"decide.{question_set.name}")
    return _validated(question_set, reply.get("answer"), reply.get("probs"))


def _jev_backend(question_set: QuestionSet, subject: str, context: dict) -> Decision:
    raise NotConfigured("jev backend: no access yet (spec Part 3 B5); no Jev calls in Phase B")


_BACKENDS: dict[str, Callable[[QuestionSet, str, dict], Decision]] = {
    "llm": _llm_backend,
    "jev": _jev_backend,
}


def _backend_answer(question_set: QuestionSet, subject: str, context: dict) -> Decision | None:
    """The configured backend's answer, or None (logged) if it failed."""
    name = settings.DECIDE_BACKEND
    backend = _BACKENDS.get(name)
    if backend is None:
        log.warning("decide %s %s: unknown DECIDE_BACKEND %r (expected one of %s); rules answer stands",
                    question_set.name, subject, name, sorted(_BACKENDS))
        return None
    try:
        return backend(question_set, subject, context)
    except Exception as e:
        log.warning("decide %s %s: %s backend failed; rules answer stands: %s: %s",
                    question_set.name, subject, name, type(e).__name__, e)
        return None


def decide(question_set: QuestionSet, subject: str, context: dict,
           intervention_id: int | None = None) -> Decision:
    """The rules answer to `question_set` for `subject`, with the backend's in shadow.

    Logs one decision_log row (rules answer, backend answer and probabilities,
    used = rules). A failed log write is logged and doesn't change the answer.
    """
    answer = question_set.rules(context)
    rules = _validated(question_set, answer,
                       {a: 1.0 if a == answer else 0.0 for a in question_set.answers})
    shadow = _backend_answer(question_set, subject, context)
    row = {
        "question_set_version": QUESTION_SET_VERSION,
        "subject": subject,
        "rules_answer": rules.answer,
        "jev_answer": shadow.answer if shadow else None,
        "jev_probs": shadow.probs if shadow else None,
        "used": DecisionUsed.RULES,
        "intervention_id": intervention_id,
    }
    try:
        supabase().table("decision_log").insert(row).execute()
    except Exception as e:
        log.warning("decide %s %s: decision_log write failed: %s", question_set.name, subject, e)
    return rules
