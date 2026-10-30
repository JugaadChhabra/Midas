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

WARM = {"backlinks_enabled": True, "has_related_block": False,
        "backlink_candidates": 3}                                 # rules: backlinks
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
    assert rules({**WARM, "backlinks_stopped": True}) == "no_change"     # S1.4: lever stopped
    with patch.object(settings, "BACKLINK_MIN_CANDIDATES", 4):
        assert rules(WARM) == "no_change"
    assert rules({**WARM, "backlinks_enabled": False}) == "no_change"   # S3.3: off or no heading


#: S3.3: a video the title rule takes (CTR under the channel median).
TITLE = {"title_enabled": True, "is_short": False, "title_excluded": False,
         "ctr": 0.01, "channel_median_ctr": 0.05}


def test_triage_rules_answer_title_after_backlinks():
    rules = decide.TRIAGE.rules
    assert rules(TITLE) == "title"
    assert rules({**TITLE, **WARM}) == "backlinks"                      # backlinks first
    assert rules({**TITLE, **WARM, "backlinks_stopped": True}) == "title"
    assert rules({**TITLE, **WARM, "has_related_block": True}) == "title"
    assert rules({**TITLE, **WARM, "backlinks_enabled": False}) == "title"


@pytest.mark.parametrize("change", [
    {"title_enabled": False}, {"title_enabled": None}, {"is_short": True},
    {"title_excluded": True}, {"ctr": 0.05}, {"ctr": 0.06}, {"ctr": None},
    {"channel_median_ctr": None},
])
def test_triage_rules_never_answer_title_for(change):
    assert decide.TRIAGE.rules({**TITLE, **change}) == "no_change"


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


# ── the log id links a decision to its intervention (Slice 1 S1.4, #65) ──

def test_decide_returns_its_decision_log_id():
    sb = FakeSupabase({"decision_log": [{"id": 4}]}, serial=("decision_log",))
    with patch("app.decide.supabase", return_value=sb):
        d = _decide("llm")
    assert d.log_id == 5
    assert d == RULES_BACKLINKS                     # the id isn't part of the answer
    assert sb.rows("decision_log")[-1]["id"] == 5


def test_a_failed_log_write_leaves_no_log_id():
    class Down:
        def table(self, name):
            raise RuntimeError("db down")

    with patch("app.decide.supabase", return_value=Down()):
        assert _decide("llm").log_id is None


def test_link_points_the_decision_at_its_intervention():
    sb = FakeSupabase({"decision_log": [{"id": 5, "intervention_id": None},
                                        {"id": 6, "intervention_id": None}]})
    with patch("app.decide.supabase", return_value=sb):
        decide.link(5, 42)
        decide.link(None, 43)                       # no log row: nothing to link
    assert [r["intervention_id"] for r in sb.rows("decision_log")] == [42, None]


# ── NEXT_WATCH: the per-pair question, in shadow (Slice 1 S1.5, #66) ─────

PAIR = {"source_video_id": "vidA", "source_title": "Rhyme A",
        "target_video_id": "vidB", "target_channel_id": "UCx", "target_title": "Rhyme B",
        "similarity": 0.85, "join_low": 0.8}


def test_next_watch_rules_say_yes_at_or_above_join_low():
    rules = decide.NEXT_WATCH.rules
    assert decide.NEXT_WATCH.answers == ("yes", "no")
    assert rules(PAIR) == "yes"
    assert rules({**PAIR, "similarity": 0.8}) == "yes"                 # ≥, not >
    assert rules({**PAIR, "similarity": 0.79}) == "no"
    assert rules({**PAIR, "join_low": None}) == "no"
    assert rules({**PAIR, "similarity": None}) == "no"
    assert rules({}) == "no"


def test_next_watch_rules_answer_is_used_and_the_backend_logged_in_shadow(sb):
    with patch.object(settings, "DECIDE_BACKEND", "llm"), \
         patch("app.decide.openrouter.chat_json", _llm_says("no", {"yes": 0.1, "no": 0.9})):
        d = decide.decide(decide.NEXT_WATCH, "vidA->vidB", PAIR)
    assert d == decide.Decision("next_watch", "yes", {"yes": 1.0, "no": 0.0})
    (row,) = sb.rows("decision_log")
    assert (row["subject"], row["rules_answer"], row["used"]) == ("vidA->vidB", "yes", "rules")
    assert row["jev_answer"] == "no" and row["jev_probs"] == {"yes": 0.1, "no": 0.9}
    assert row["question_set_version"] == decide.QUESTION_SET_VERSION


def test_next_watch_backend_failure_still_logs_the_row_without_its_answer(sb):
    def down(*a, **kw):
        raise RuntimeError("OpenRouter 503")

    for chat in (down, _llm_says("backlinks", P(backlinks=1.0))):     # error; a TRIAGE answer
        with patch.object(settings, "DECIDE_BACKEND", "llm"), \
             patch("app.decide.openrouter.chat_json", chat):
            assert decide.decide(decide.NEXT_WATCH, "vidA->vidB", PAIR).answer == "yes"
    rows = sb.rows("decision_log")
    assert len(rows) == 2
    assert all(r["jev_answer"] is None and r["jev_probs"] is None for r in rows)
    assert {r["rules_answer"] for r in rows} == {"yes"}


def test_llm_backend_asks_next_watch_with_its_question_and_label():
    seen = {}

    def fake_chat_json(prompt, model=None, system=None, image_urls=None, label=None):
        seen.update(prompt=prompt, label=label)
        return {"answer": "yes", "probs": {"yes": 0.7, "no": 0.3}}

    with patch("app.decide.openrouter.chat_json", fake_chat_json):
        decide._BACKENDS["llm"](decide.NEXT_WATCH, "vidA->vidB", PAIR)
    assert decide.NEXT_WATCH.question in seen["prompt"]
    assert "ALLOWED ANSWERS: yes, no" in seen["prompt"]
    assert '"target_title": "Rhyme B"' in seen["prompt"]
    assert seen["label"] == "decide.next_watch"


def test_the_s3_3_bump_reaches_the_strategy_stamp():
    """S3.3 changed TRIAGE's rules (title after backlinks), so the version moved
    past S1.5's, and the audit stamp hashes the new one."""
    assert decide.QUESTION_SET_VERSION == "2026.11-s3-v1"
    current, inputs = audits.strategy_version(audits.DEFAULT_PROMPT, audits.PROMPT_SOURCE_DEFAULT)
    assert inputs["decision_question_set_version"] == decide.QUESTION_SET_VERSION
    with patch.object(decide, "QUESTION_SET_VERSION", "2026.10-s1-v2"):
        previous, _ = audits.strategy_version(audits.DEFAULT_PROMPT, audits.PROMPT_SOURCE_DEFAULT)
    assert current != previous
