"""The audits.strategy_version stamp is derived from what actually produced the audit.

It used to be a static env string (`2026.07-baseline-v1`) whose audit_strategies
row was inserted once with `model = anthropic/claude-haiku-4.5`, so every
AUDIT_MODEL swap in .env was invisible to attribution. Now the version is
`<STRATEGY_LABEL>-<short hash>` over the inputs, and each distinct version gets
its own row carrying the real model and the hashed inputs.
"""
from unittest.mock import MagicMock, patch

import pytest

from app import audits
from app.config import settings
from tests.fakes import FakeSupabase


@pytest.fixture(autouse=True)
def _fresh_cache():
    audits._strategy_rows_ensured.clear()
    yield
    audits._strategy_rows_ensured.clear()


def test_version_is_label_plus_short_hash():
    with patch.object(settings, "STRATEGY_LABEL", "2026.07-baseline"):
        version, inputs = audits.strategy_version()
    label, _, digest = version.rpartition("-")
    assert label == "2026.07-baseline"
    assert len(digest) == 12 and int(digest, 16) >= 0
    assert inputs["label"] == "2026.07-baseline"
    assert inputs["audit_model"] == settings.AUDIT_MODEL
    assert inputs["decision_question_set_version"] == audits.DECISION_QUESTION_SET_VERSION
    assert inputs["prompt_version_id"] is None
    assert len(inputs["default_prompt_sha256"]) == 64


def test_same_inputs_same_version():
    assert audits.strategy_version(7) == audits.strategy_version(7)
    assert audits.strategy_version() == audits.strategy_version(None)


def test_version_does_not_depend_on_dict_order():
    _, inputs = audits.strategy_version(7)
    reordered = dict(reversed(list(inputs.items())))
    assert list(reordered) != list(inputs)
    assert audits._strategy_hash(reordered) == audits._strategy_hash(inputs)


def test_different_audit_model_gives_different_version():
    with patch.object(settings, "AUDIT_MODEL", "anthropic/claude-haiku-4.5"):
        haiku, _ = audits.strategy_version()
    with patch.object(settings, "AUDIT_MODEL", "google/gemini-3.7-flash"):
        gemini, inputs = audits.strategy_version()
    assert haiku != gemini
    assert inputs["audit_model"] == "google/gemini-3.7-flash"


def test_different_prompt_version_id_gives_different_version():
    assert audits.strategy_version(7)[0] != audits.strategy_version(8)[0]
    assert audits.strategy_version(7)[0] != audits.strategy_version(None)[0]


def test_different_default_prompt_gives_different_version():
    before, _ = audits.strategy_version()
    with patch.object(audits, "DEFAULT_PROMPT", audits.DEFAULT_PROMPT + " "):
        after, _ = audits.strategy_version()
    assert before != after


def test_writer_model_is_hashed_only_when_it_exists():
    assert not hasattr(settings, "WRITER_MODEL")
    base, inputs = audits.strategy_version()
    assert "writer_model" not in inputs
    with patch.object(settings, "WRITER_MODEL", "anthropic/claude-sonnet-5", create=True):
        with_writer, inputs = audits.strategy_version()
    assert inputs["writer_model"] == "anthropic/claude-sonnet-5"
    assert with_writer != base


def test_new_audit_model_upserts_a_new_row_with_that_model():
    sb = FakeSupabase({"audit_strategies": []})
    with patch("app.audits.supabase", return_value=sb):
        with patch.object(settings, "AUDIT_MODEL", "anthropic/claude-haiku-4.5"):
            v1 = audits._stamp_strategy(None)
        with patch.object(settings, "AUDIT_MODEL", "google/gemini-3.7-flash"):
            v2 = audits._stamp_strategy(None)
            _, inputs2 = audits.strategy_version(None)

    rows = {r["version"]: r for r in sb.rows("audit_strategies")}
    assert set(rows) == {v1, v2}
    assert rows[v1]["model"] == "anthropic/claude-haiku-4.5"
    assert rows[v2]["model"] == "google/gemini-3.7-flash"
    assert rows[v2]["config"] == inputs2


def test_row_is_upserted_once_per_version_per_process():
    sb = FakeSupabase({"audit_strategies": []})
    with patch("app.audits.supabase", return_value=sb):
        audits._stamp_strategy(7)
        audits._stamp_strategy(7)
        audits._stamp_strategy(8)
    upserts = [w for w in sb.writes if w[:2] == ("audit_strategies", "upsert")]
    assert len(upserts) == 2


def test_upsert_never_overwrites_an_existing_row():
    """The 2026.07-baseline-v1 seed row, and any curated row, stays as it is.

    FakeSupabase's upsert always merges, so assert the flag postgrest acts on.
    """
    sb = MagicMock()
    with patch("app.audits.supabase", return_value=sb):
        audits._stamp_strategy(None)
    kwargs = sb.table.return_value.upsert.call_args.kwargs
    assert kwargs == {"on_conflict": "version", "ignore_duplicates": True}


def test_derived_version_never_collides_with_the_seed_row():
    assert audits.strategy_version()[0] != "2026.07-baseline-v1"
