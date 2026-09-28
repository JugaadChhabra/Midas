"""audits.prompt_version_id is stamped by audit_video, at the insert.

Two defects motivated this:

1. The stamp was a post-hoc UPDATE in the *callers* — autopilot and
   reflection._run_shadow_audits each had their own copy — so audits from
   run_audit / run_bulk_audit / reaudit_quarantined were never stamped at
   all, and _cohort_median_ctr_delta silently ignores NULLs.

2. The caller stamped the live version unconditionally, without checking
   whether that version's prompt was the one actually used. audit_video
   falls back to DEFAULT_PROMPT when audit_configs.generated_prompt is
   empty, so the caller would label those audits with a version whose
   prompt never ran.

So the rule is: stamp the live version only when the channel's
generated_prompt was the prompt actually sent to the model.

strategy_version is stamped at the same insert, derived from the same
prompt_version_id (see tests/test_strategy_version.py for the derivation).
"""
from unittest.mock import MagicMock, patch

import pytest

MOCK_VIDEO = {
    "id": "vid1", "channel_id": "ch1", "privacy_status": "public",
    "title": "Test", "description": "", "tags": [], "view_count": 100,
    "like_count": 5, "published_at": "2026-01-01T00:00:00Z", "is_short": False,
}

LLM_RESULT = {
    "comparisons": {
        "title": {"suggested": "New Title", "current_problems": "", "why_better": ""},
        "description": {"suggested": "New Desc", "current_problems": "", "why_better": ""},
        "tags": {"suggested": ["tag1"], "current_problems": "", "why_better": ""},
    },
    "issues": [],
    "reasoning": "test",
}


def _run_audit_video(cfg_row, live_version_id, strategy_upserts=None, **kwargs):
    """Call audit_video against a mocked world; return (inserted_row, system_prompt).

    Pass a list as `strategy_upserts` to collect the audit_strategies upserts.
    """
    from app import audits

    inserted = {}
    audits._strategy_rows_ensured.clear()

    with patch("app.audits.supabase") as mock_sb, \
         patch("app.audits.fetch_transcript", return_value=(None, None)), \
         patch("app.audits.chat_json", return_value=LLM_RESULT) as mock_chat:

        def table_side_effect(name):
            m = MagicMock()
            if name == "videos":
                m.select.return_value.eq.return_value.single.return_value \
                    .execute.return_value.data = MOCK_VIDEO
            elif name == "audit_configs":
                m.select.return_value.eq.return_value.execute.return_value.data = (
                    [cfg_row] if cfg_row is not None else []
                )
            elif name == "channels":
                m.select.return_value.eq.return_value.single.return_value \
                    .execute.return_value.data = {"default_language": "en"}
            elif name == "prompt_versions":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = (
                        [{"id": live_version_id}] if live_version_id else []
                    )
            elif name == "audit_strategies" and strategy_upserts is not None:
                def capture_strategy(row, **_kw):
                    strategy_upserts.append(row)
                    return MagicMock()
                m.upsert.side_effect = capture_strategy
            elif name == "audits":
                def capture(row):
                    inserted.update(row)
                    inner = MagicMock()
                    inner.execute.return_value.data = [{"id": 99, **row}]
                    return inner
                m.insert.side_effect = capture
            return m

        mock_sb.return_value.table.side_effect = table_side_effect

        from app.audits import audit_video
        audit_video("vid1", **kwargs)

    system = mock_chat.call_args.kwargs.get("system")
    return inserted, system


def test_stamps_live_version_when_generated_prompt_is_used():
    row, system = _run_audit_video(
        {"generated_prompt": "CHANNEL PROMPT"}, live_version_id=7
    )
    assert system == "CHANNEL PROMPT"
    assert row["prompt_version_id"] == 7


def test_no_stamp_when_falling_back_to_default_prompt():
    """The live config's case: generated_prompt is empty, so DEFAULT_PROMPT ran.

    A live version can still exist (retired ones aside), and stamping it here
    would attribute the audit to a prompt the model never saw.
    """
    from app.audits import DEFAULT_PROMPT

    row, system = _run_audit_video(
        {"generated_prompt": ""}, live_version_id=7  # a live version EXISTS...
    )
    assert system == DEFAULT_PROMPT           # ...but it is not what ran
    assert row["prompt_version_id"] is None


def test_no_stamp_when_no_config_row_at_all():
    row, system = _run_audit_video(None, live_version_id=7)
    assert row["prompt_version_id"] is None


def test_no_stamp_when_shorts_prompt_is_used():
    short_video = dict(MOCK_VIDEO, is_short=True)
    with patch.dict(MOCK_VIDEO, short_video, clear=True):
        row, system = _run_audit_video(
            {"generated_prompt": "CHANNEL PROMPT", "shorts_prompt": "SHORTS PROMPT"},
            live_version_id=7,
        )
    assert system == "SHORTS PROMPT"
    assert row["prompt_version_id"] is None


def test_prompt_override_stamps_the_caller_supplied_version():
    """Shadow audits: reflection passes the candidate's version, not the live one."""
    row, system = _run_audit_video(
        {"generated_prompt": "CHANNEL PROMPT"},
        live_version_id=7,
        prompt_override="CANDIDATE PROMPT",
        status_override="shadow_pending",
        prompt_version_id=12,
    )
    assert system == "CANDIDATE PROMPT"
    assert row["prompt_version_id"] == 12
    assert row["status"] == "shadow_pending"


def test_prompt_override_without_a_version_is_not_attributed_to_live():
    row, _ = _run_audit_video(
        {"generated_prompt": "CHANNEL PROMPT"},
        live_version_id=7,
        prompt_override="ONE OFF PROMPT",
    )
    assert row["prompt_version_id"] is None


def test_callers_no_longer_stamp_after_the_fact():
    """The stamp lives at the insert; the duplicated caller-side UPDATEs are gone.

    Passing prompt_version_id= as a kwarg is fine (that's the seam); writing it
    back with a follow-up update() is what this forbids.
    """
    import inspect
    from app import autopilot, reflection

    for fn in (autopilot.tick, reflection._run_shadow_audits):
        assert '{"prompt_version_id"' not in inspect.getsource(fn), (
            f"{fn.__qualname__} still stamps prompt_version_id after the insert"
        )


def test_audit_is_stamped_with_the_derived_strategy_version():
    """The insert carries the version derived from THIS audit's prompt_version_id."""
    from app.audits import strategy_version
    from app.config import settings

    upserts = []
    with patch.object(settings, "AUDIT_MODEL", "google/gemini-3.7-flash"):
        row, _ = _run_audit_video(
            {"generated_prompt": "CHANNEL PROMPT"}, live_version_id=7,
            strategy_upserts=upserts,
        )
        expected, inputs = strategy_version(7)

    assert row["strategy_version"] == expected
    assert row["strategy_version"] != "2026.07-baseline-v1"
    assert [u["version"] for u in upserts] == [expected]
    assert upserts[0]["model"] == "google/gemini-3.7-flash"
    assert upserts[0]["config"] == inputs


def test_default_prompt_audit_is_stamped_without_a_prompt_version():
    from app.audits import strategy_version

    row, _ = _run_audit_video({"generated_prompt": ""}, live_version_id=7)
    assert row["strategy_version"] == strategy_version(None)[0]
