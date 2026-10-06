"""Phase B · B5 — decide() answers with the rules and logs its backend in shadow (#36).

OpenRouter and the database are faked at the edge: `openrouter.chat_json` is
replaced by a function returning the model's JSON, and `decision_log` lives in a
FakeSupabase. decide() itself runs for real.
"""
from unittest.mock import patch

import pytest

from app import audits, decide
from app.config import settings
from tests.fakes import FakeSupabase

WARM = {"has_related_block": False, "backlink_candidates": 3}    # rules: backlinks
COLD = {"has_related_block": False, "backlink_candidates": 0}    # rules: no_change


def P(**given):
    """A probability for every TRIAGE answer: the given ones, 0.0 for the rest."""
    return {a: float(given.get(a, 0.0)) for a in decide.TRIAGE.answers}


RULES_BACKLINKS = decide.Decision("triage", "backlinks", P(backlinks=1.0))


def _llm_says(answer, probs):
    def fake_chat_json(prompt, model=None, system=None, image_urls=None, label=None):
        return {"answer": answer, "probs": probs}
    return fake_chat_json


def _fake_jev(question_set, subject, context):
    return decide.Decision(question_set=question_set.name, answer="no_change",
                           probs=P(backlinks=0.3, no_change=0.7))


@pytest.fixture
def sb():
    sb = FakeSupabase({"decision_log": []})
    with patch("app.decide.supabase", return_value=sb):
        yield sb


def _decide(backend, context=WARM, chat=None, **kw):
    chat = chat or _llm_says("no_change", P(backlinks=0.2, no_change=0.8))
    with patch.object(settings, "DECIDE_BACKEND", backend), \
         patch("app.decide.openrouter.chat_json", chat):
        return decide.decide(decide.TRIAGE, "vid1", context, **kw)


# ── the rules baseline (spec Part 2 §2.2) ────────────────────────────────

def test_triage_rules():
    rules = decide.TRIAGE.rules
    assert rules(WARM) == "backlinks"
    assert rules(COLD) == "no_change"
    assert rules({"has_related_block": True, "backlink_candidates": 9}) == "no_change"
    assert rules({"has_related_block": False, "backlink_candidates": None}) == "no_change"
    assert rules({}) == "no_change"
    with patch.object(settings, "BACKLINK_MIN_CANDIDATES", 4):
        assert rules(WARM) == "no_change"


# ── both backends return the same typed shape ────────────────────────────

def test_llm_and_jev_backends_return_the_same_typed_shape():
    with patch("app.decide.openrouter.chat_json", _llm_says("backlinks", P(backlinks=0.9, no_change=0.1))):
        llm = decide._BACKENDS["llm"](decide.TRIAGE, "vid1", WARM)
    jev = _fake_jev(decide.TRIAGE, "vid1", WARM)
    for d in (llm, jev):
        assert type(d) is decide.Decision
        assert d.question_set == "triage"
        assert d.answer in decide.TRIAGE.answers
        assert set(d.probs) == set(decide.TRIAGE.answers)
        assert all(type(p) is float for p in d.probs.values())
    assert llm == decide.Decision("triage", "backlinks", P(backlinks=0.9, no_change=0.1))


def test_a_fake_jev_backend_is_logged_like_the_llm_one(sb):
    with patch.dict(decide._BACKENDS, {"jev": _fake_jev}):
        _decide("jev")
    _decide("llm")
    jev_row, llm_row = sb.rows("decision_log")
    assert set(jev_row) == set(llm_row)
    assert jev_row["jev_answer"] == llm_row["jev_answer"] == "no_change"
    assert jev_row["jev_probs"] == P(backlinks=0.3, no_change=0.7)


def test_llm_backend_asks_through_chat_json_with_the_question_and_answers():
    seen = {}

    def fake_chat_json(prompt, model=None, system=None, image_urls=None, label=None):
        seen.update(prompt=prompt, label=label)
        return {"answer": "no_change", "probs": {**P(), "no_change": 1}}

    with patch("app.decide.openrouter.chat_json", fake_chat_json):
        d = decide._BACKENDS["llm"](decide.TRIAGE, "vid1", WARM)
    assert d.probs == P(no_change=1.0)
    assert decide.TRIAGE.question in seen["prompt"]
    assert "no_change, backlinks, playlist, short_link, title" in seen["prompt"]
    assert '"backlink_candidates": 3' in seen["prompt"]
    assert seen["label"] == "decide.triage"


# ── shadow: logged, never used ───────────────────────────────────────────

def test_shadow_decision_is_logged_and_the_rules_answer_is_used(sb):
    d = _decide("llm", WARM, chat=_llm_says("no_change", P(backlinks=0.2, no_change=0.8)))
    assert d == RULES_BACKLINKS

    (row,) = sb.rows("decision_log")
    assert row["subject"] == "vid1"
    assert row["rules_answer"] == "backlinks"
    assert row["jev_answer"] == "no_change"
    assert row["jev_probs"] == P(backlinks=0.2, no_change=0.8)
    assert row["used"] == "rules"
    assert row["intervention_id"] is None


def test_backend_agreeing_or_not_never_changes_the_answer(sb):
    for llm_answer in decide.TRIAGE.answers:
        for context, expected in ((WARM, "backlinks"), (COLD, "no_change")):
            d = _decide("llm", context, chat=_llm_says(llm_answer, P(**{llm_answer: 0.99})))
            assert d.answer == expected
    assert {r["used"] for r in sb.rows("decision_log")} == {"rules"}


def test_intervention_id_is_logged(sb):
    _decide("llm", intervention_id=42)
    assert sb.rows("decision_log")[0]["intervention_id"] == 42


# ── a failing backend fails closed to the rules answer ───────────────────

def test_jev_stub_fails_closed_to_the_rules_answer(sb, caplog):
    def no_llm(*a, **kw):
        raise AssertionError("the jev backend must not fall through to the LLM")

    d = _decide("jev", WARM, chat=no_llm)
    assert d == RULES_BACKLINKS
    (row,) = sb.rows("decision_log")
    assert row["rules_answer"] == "backlinks"
    assert row["jev_answer"] is None and row["jev_probs"] is None
    assert row["used"] == "rules"
    assert "NotConfigured" in caplog.text


def test_jev_stub_raises_not_configured():
    with pytest.raises(decide.NotConfigured):
        decide._BACKENDS["jev"](decide.TRIAGE, "vid1", WARM)


@pytest.mark.parametrize("chat", [
    pytest.param(_llm_says("maybe", P(backlinks=1.0)), id="answer-not-allowed"),
    pytest.param(_llm_says("backlinks", P(backlinks=1.5)), id="prob-out-of-range"),
    pytest.param(_llm_says("backlinks", [0.5]), id="probs-not-an-object"),
    pytest.param(_llm_says("backlinks", {**P(backlinks=0.5), "other": 0.5}), id="prob-for-unknown-answer"),
    pytest.param(_llm_says("backlinks", {"backlinks": 0.9, "no_change": 0.1}), id="probs-miss-an-answer"),
])
def test_malformed_llm_answer_falls_back_to_the_rules(sb, chat):
    assert _decide("llm", COLD, chat=chat).answer == "no_change"
    (row,) = sb.rows("decision_log")
    assert row["jev_answer"] is None and row["used"] == "rules"


def test_llm_error_falls_back_to_the_rules(sb):
    def down(*a, **kw):
        raise RuntimeError("OpenRouter 503")

    assert _decide("llm", WARM, chat=down).answer == "backlinks"
    assert sb.rows("decision_log")[0]["jev_answer"] is None


def test_unknown_backend_falls_back_to_the_rules(sb):
    assert _decide("sarvam", COLD).answer == "no_change"
    assert sb.rows("decision_log")[0]["jev_answer"] is None


def test_a_failed_log_write_does_not_change_the_answer(caplog):
    with patch("app.decide.supabase", return_value=FakeSupabase({})):   # no decision_log table
        assert _decide("llm", WARM).answer == "backlinks"
    assert "decision_log write failed" in caplog.text


# ── the question-set version: log row and strategy stamp ─────────────────

def test_question_set_version_is_in_the_log_row_and_the_strategy_stamp(sb):
    _decide("llm")
    _, inputs = audits.strategy_version(audits.DEFAULT_PROMPT, audits.PROMPT_SOURCE_DEFAULT)
    assert sb.rows("decision_log")[0]["question_set_version"] == decide.QUESTION_SET_VERSION
    assert inputs["decision_question_set_version"] == decide.QUESTION_SET_VERSION
    assert decide.QUESTION_SET_VERSION != "none"


def test_changing_the_question_set_version_changes_both(sb):
    before, _ = audits.strategy_version(audits.DEFAULT_PROMPT, audits.PROMPT_SOURCE_DEFAULT)
    with patch.object(decide, "QUESTION_SET_VERSION", "2099.01-test"):
        after, inputs = audits.strategy_version(audits.DEFAULT_PROMPT, audits.PROMPT_SOURCE_DEFAULT)
        _decide("llm")
    assert after != before
    assert inputs["decision_question_set_version"] == "2099.01-test"
    assert sb.rows("decision_log")[0]["question_set_version"] == "2099.01-test"
