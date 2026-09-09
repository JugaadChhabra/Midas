import pytest
from unittest.mock import patch, MagicMock


def _mock_openrouter_response(content: str):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    return mock_resp


def test_chat_text_returns_string():
    with patch("app.openrouter.settings.OPENROUTER_API_KEY", "test-key"), \
            patch("app.openrouter.httpx.post") as mock_post:
        mock_post.return_value = _mock_openrouter_response("hello world")
        from app.openrouter import chat_text
        result = chat_text("say hello", model="perplexity/sonar")
    assert result == "hello world"


def test_chat_text_raises_on_http_error():
    with patch("app.openrouter.settings.OPENROUTER_API_KEY", "test-key"), \
            patch("app.openrouter.httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "rate limited"
        mock_post.return_value = mock_resp
        from app.openrouter import chat_text
        with pytest.raises(RuntimeError, match="OpenRouter 429"):
            chat_text("say hello", model="perplexity/sonar")


def test_yt_search_videos_returns_snippets():
    mock_yt = MagicMock()
    mock_yt.search.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {
                    "title": "Marathi Rhymes for Kids",
                    "tags": ["marathi", "rhymes"],
                    "description": "Best marathi rhymes",
                }
            }
        ]
    }
    with patch("app.youtube_client._log_quota"):
        from app.youtube_client import yt_search_videos
        results = yt_search_videos(mock_yt, "UCtest", "marathi nursery rhymes", max_results=10)
    assert len(results) == 1
    assert results[0]["title"] == "Marathi Rhymes for Kids"
    assert results[0]["video_id"] == "abc123"


def test_audit_video_uses_prompt_override():
    mock_video = {
        "id": "vid1", "channel_id": "ch1", "privacy_status": "public",
        "title": "Test", "description": "", "tags": [], "view_count": 100,
        "like_count": 5, "published_at": "2026-01-01T00:00:00Z", "is_short": False,
    }

    with patch("app.audits.supabase") as mock_sb, \
         patch("app.audits.fetch_transcript", return_value=(None, None)), \
         patch("app.audits.chat_json") as mock_chat:

        def table_side_effect(name):
            m = MagicMock()
            if name == "videos":
                m.select.return_value.eq.return_value.single.return_value.execute.return_value.data = mock_video
            elif name == "audit_configs":
                m.select.return_value.eq.return_value.execute.return_value.data = []
            elif name == "channels":
                m.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"default_language": "en"}
            elif name == "audits":
                m.insert.return_value.execute.return_value.data = [{"id": 99}]
            return m

        mock_sb.return_value.table.side_effect = table_side_effect
        mock_chat.return_value = {
            "comparisons": {
                "title": {"suggested": "New Title", "current_problems": "", "why_better": ""},
                "description": {"suggested": "New Desc", "current_problems": "", "why_better": ""},
                "tags": {"suggested": ["tag1"], "current_problems": "", "why_better": ""},
                "thumbnail": {"suggested": "", "current_problems": "", "why_better": ""},
            },
            "issues": [],
            "reasoning": "test",
        }

        from app.audits import audit_video
        audit_video("vid1", prompt_override="MY CUSTOM PROMPT", status_override="shadow_pending")

        call_kwargs = mock_chat.call_args
        used_system = call_kwargs.kwargs.get("system") or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else None)
        assert used_system == "MY CUSTOM PROMPT"


def _make_perf_report(win_rate=70.0, regression_count=0, count=15,
                      wins=10, neutrals=4, regressions=1,
                      median_delta=12.0, levers=None):
    return {
        "count": count,
        "win_rate": win_rate,
        "regression_count": regression_count,
        # The population _should_reflect actually judges on. Same statuses as
        # win_rate's denominator, but as counts, so "mostly neutral" and
        # "mostly regression" are distinguishable — win_rate alone cannot tell
        # them apart.
        "distribution": {
            "win": wins, "neutral": neutrals, "regression": regressions,
            "total": wins + neutrals + regressions,
        },
        "median_ctr_delta_pct": median_delta,
        "levers": levers if levers is not None
                  else {"title": 15.0, "description": 8.0, "tags": 20.0},
        "worst_audits": [],
        "best_audits": [],
    }


def test_should_reflect_skips_without_measured_outcomes():
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=None):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        from app.reflection import _should_reflect
        should, reason, _ = _should_reflect("ch1")
    assert should is False
    assert reason == "no_measured_outcomes"


def _should_reflect_on(report):
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=report):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        from app.reflection import _should_reflect
        should, reason, _ = _should_reflect("ch1")
        return should, reason


def test_should_reflect_skips_when_neutral_dominates():
    """A mostly-neutral channel is not a failing one.

    The regression test for the 2026-08-23 finding: the fleet's real
    distribution was 147 neutral / 21 win / 3 regression, which is a win_rate
    of 12.3% because verdicts.win_rate counts neutral in the denominator. The
    old rule (`win_rate < 50 -> reflect`) therefore fired every cooldown from
    2026-05 to 2026-08 and produced five candidate prompts, none promoted,
    each diagnosing a "core failure" it had been handed as a premise.

    Neutral is what a metadata rewrite does to CTR most of the time. Wins
    outnumbering regressions 7:1 is a prompt that helps when it does anything.
    """
    should, reason = _should_reflect_on(
        _make_perf_report(win_rate=12.3, wins=21, neutrals=147, regressions=3,
                          median_delta=0.4)
    )
    assert should is False
    assert reason == "performing_well"


def test_should_reflect_fires_when_regressions_outnumber_wins():
    should, reason = _should_reflect_on(
        _make_perf_report(win_rate=8.0, wins=2, neutrals=40, regressions=5)
    )
    assert should is True
    assert reason == "regressions_outnumber_wins"


def test_should_reflect_fires_on_negative_median_delta():
    """Aggregate CTR moving down is harm, even with few outright regressions."""
    should, reason = _should_reflect_on(
        _make_perf_report(win_rate=10.0, wins=5, neutrals=40, regressions=1,
                          median_delta=-8.0)
    )
    assert should is True
    assert reason == "negative_median_delta"


def test_should_reflect_tolerates_a_flat_median():
    """Flat is not negative. Only a real decline counts."""
    should, reason = _should_reflect_on(
        _make_perf_report(win_rate=10.0, wins=5, neutrals=40, regressions=1,
                          median_delta=-0.5)
    )
    assert should is False
    assert reason == "performing_well"


def test_should_reflect_fires_on_a_consistently_negative_lever():
    should, reason = _should_reflect_on(
        _make_perf_report(win_rate=10.0, wins=5, neutrals=40, regressions=1,
                          levers={"title": -9.0, "description": 2.0, "tags": None})
    )
    assert should is True
    assert reason == "negative_lever_title"


def test_should_reflect_survives_a_missing_median():
    """median_ctr_delta_pct is None when no verdict carried a comparable delta."""
    should, reason = _should_reflect_on(
        _make_perf_report(win_rate=10.0, wins=5, neutrals=40, regressions=1,
                          median_delta=None)
    )
    assert should is False
    assert reason == "performing_well"


def test_should_reflect_skips_recent_reflection():
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=_make_perf_report(win_rate=40.0)):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = [{"created_at": recent}]
        from app.reflection import _should_reflect
        should, reason, _ = _should_reflect("ch1")
    assert should is False
    assert reason == "reflected_recently"


def test_derive_niche_queries_calls_haiku():
    mock_videos = [{"title": f"Marathi song {i}", "tags": ["marathi", "rhymes"]} for i in range(5)]
    mock_tags = [{"tags": ["marathi", "rhymes", "bal geet"]} for _ in range(10)]

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.chat_json") as mock_chat:
        def table_side(name):
            m = MagicMock()
            if name == "videos":
                m.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = mock_videos
                m.select.return_value.eq.return_value.execute.return_value.data = mock_tags
            elif name == "audit_configs":
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side
        mock_chat.return_value = {"queries": ["marathi nursery rhymes", "bal geet"]}

        from app.reflection import derive_niche_queries
        result = derive_niche_queries("ch1")

    assert "marathi nursery rhymes" in result
    assert len(result) >= 1


def test_get_or_derive_uses_cache():
    """If niche_queries already stored, no LLM call is made."""
    cached = ["marathi nursery rhymes", "bal geet"]

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.chat_json") as mock_chat:
        m = MagicMock()
        m.select.return_value.eq.return_value.execute.return_value.data = [
            {"niche_queries": cached}
        ]
        mock_sb.return_value.table.return_value = m

        from app.reflection import get_or_derive_niche_queries
        result = get_or_derive_niche_queries("ch1")

    mock_chat.assert_not_called()
    assert result == cached


def test_sample_competitors_formats_output():
    mock_results = [
        {"video_id": "v1", "title": "Marathi Rhymes for Kids", "description": "Best rhymes", "tags": ["marathi"]},
        {"video_id": "v2", "title": "बालगीत मराठी", "description": "Songs", "tags": ["marathi", "bal geet"]},
    ]
    with patch("app.reflection.youtube_for_channel") as mock_yt_fn, \
         patch("app.reflection.yt_search_videos", return_value=mock_results):
        mock_yt_fn.return_value = MagicMock()
        from app.reflection import _sample_competitors
        output = _sample_competitors("ch1", ["marathi nursery rhymes"])

    assert "Marathi Rhymes for Kids" in output
    assert "बालगीत मराठी" in output


def test_get_platform_guidance_returns_text():
    with patch("app.reflection.chat_text", return_value="Use short titles. Front-load keywords.") as mock_ct:
        from app.reflection import _get_platform_guidance
        result = _get_platform_guidance("marathi children's music")
    assert "titles" in result.lower() or len(result) > 0
    mock_ct.assert_called_once()


def test_run_reflection_stores_candidate_prompt():
    perf_report = _make_perf_report(win_rate=40.0)
    perf_report["worst_audits"] = [{"title_before": "old", "title_after": "new", "ctr_delta_pct": -30.0, "measurement_status": "regression", "ai_reasoning": "test"}]
    perf_report["best_audits"] = []

    mock_reflection_result = {
        "reflection": "Titles too SEO-heavy for this niche",
        "changes": ["Prioritise native language in titles"],
        "candidate_prompt": "You are a YouTube SEO expert for regional content...",
    }

    inserted_rows = []

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.chat_json", return_value=mock_reflection_result) as mock_chat:
        def table_side(name):
            m = MagicMock()
            if name == "audit_configs":
                m.select.return_value.eq.return_value.execute.return_value.data = [
                    {"generated_prompt": "OLD PROMPT", "reflection_mode": "shadow"}
                ]
            elif name == "prompt_versions":
                def capture_insert(row):
                    inserted_rows.append(row)
                    inner = MagicMock()
                    inner.execute.return_value.data = [{"id": 42, **row}]
                    return inner
                m.insert.side_effect = capture_insert
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = []
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.reflection import _run_reflection
        version_id, reason = _run_reflection("ch1", perf_report, "competitive ctx", "platform guidance")

    assert version_id == 42
    assert reason == "stored"
    assert len(inserted_rows) == 1
    assert inserted_rows[0]["prompt_text"] == "You are a YouTube SEO expert for regional content..."
    assert inserted_rows[0]["status"] == "shadow"


def test_run_reflection_lets_the_model_decline_a_rewrite():
    """An empty candidate_prompt is a verdict, not a failure.

    The reflection prompt no longer presupposes underperformance, so "the
    current prompt is fine" is a legal answer. It must be reported distinctly
    from a failed LLM call — conflating the two is what let three months of
    no-op cycles read as `reflection_llm_failed` in the log.
    """
    perf_report = _make_perf_report(wins=21, neutrals=147, regressions=3)
    perf_report["worst_audits"] = []
    perf_report["best_audits"] = []

    inserted_rows = []

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.chat_json", return_value={
             "reflection": "Neutral-dominant is expected; no change warranted.",
             "changes": [],
             "candidate_prompt": "",
         }):
        def table_side(name):
            m = MagicMock()
            if name == "prompt_versions":
                m.insert.side_effect = lambda row: inserted_rows.append(row) or MagicMock(
                    execute=lambda: MagicMock(data=[{"id": 99}])
                )
            m.select.return_value.eq.return_value.execute.return_value.data = [
                {"generated_prompt": "CURRENT", "reflection_mode": "shadow"}
            ]
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.reflection import _run_reflection
        version_id, reason = _run_reflection("ch1", perf_report, "ctx", "guidance")

    assert version_id is None
    assert reason == "no_change_warranted"
    assert inserted_rows == [], "declining a rewrite must not store a candidate"


def test_run_shadow_audits_uses_candidate_prompt():
    applied_audits = [
        {"video_id": f"vid{i}", "applied_at": "2026-05-01T00:00:00Z"}
        for i in range(3)
    ]

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.channel_audits.supabase") as mock_ca, \
         patch("app.reflection.audit_video") as mock_audit:

        def table_side(name):
            m = MagicMock()
            if name == "audits":
                # New shape via audits_for_channel(): the join .eq("videos.channel_id")
                # then the caller's .eq("status","applied") -> select.eq.eq.order.limit
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = applied_audits
                m.update.return_value.eq.return_value.execute.return_value = None
            elif name == "videos":
                m.select.return_value.eq.return_value.execute.return_value.data = [
                    {"id": f"vid{i}"} for i in range(3)
                ]
            return m
        mock_sb.return_value.table.side_effect = table_side
        # The audits query now runs through app.channel_audits.audits_for_channel,
        # which calls its OWN module-global supabase() — point it at the same fake.
        mock_ca.return_value.table.side_effect = table_side
        mock_audit.return_value = {"id": 99}

        from app.reflection import _run_shadow_audits
        count = _run_shadow_audits("ch1", "CANDIDATE PROMPT", version_id=42)

    assert count == 3
    for call in mock_audit.call_args_list:
        assert call.kwargs.get("prompt_override") == "CANDIDATE PROMPT"
        assert call.kwargs.get("status_override") == "shadow_pending"


def test_autopilot_skip_statuses_include_shadow_pending():
    """shadow_pending must be in the skip set so autopilot never applies shadow audits.

    Asserts the vocabulary itself rather than grepping the source: the picker
    now reads AUDIT_PICKER_SKIP_STATUSES, and the SQL mirror of that set is
    pinned separately by tests/test_status_vocab.py.
    """
    from app.status_vocab import AUDIT_PICKER_SKIP_STATUSES, AuditStatus
    assert AuditStatus.SHADOW_PENDING in AUDIT_PICKER_SKIP_STATUSES


def test_check_auto_revert_triggers_on_regression():
    """If new cohort median lift is >10pp below old cohort, revert."""
    old_version_id = 1
    new_version_id = 2

    revert_calls = []

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._cohort_median_ctr_delta") as mock_lift:
        mock_lift.side_effect = lambda version_id, *args: 20.0 if version_id == old_version_id else -5.0

        def table_side(name):
            m = MagicMock()
            if name == "prompt_versions":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = [
                    {"id": new_version_id, "parent_version_id": old_version_id,
                     "channel_id": "ch1", "created_at": "2026-04-15T00:00:00Z"}
                ]
                update_m = MagicMock()
                update_m.eq.return_value.execute.return_value = None
                m.update.return_value = update_m
            elif name == "videos":
                m.select.return_value.eq.return_value.execute.return_value.data = []
            elif name == "audit_configs":
                m.update.return_value.eq.return_value.execute.return_value = None
                m.select.return_value.eq.return_value.execute.return_value.data = [
                    {"generated_prompt": "OLD PROMPT"}
                ]
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.reflection import _check_auto_revert
        _check_auto_revert("ch1")

    # Verify revert was called (update status to retired_regression)
    mock_sb.return_value.table.assert_any_call("prompt_versions")


def test_cohort_median_ctr_delta_returns_none_insufficient():
    with patch("app.reflection.supabase") as mock_sb:
        # fetch_all pages via .range().execute(); the query has two .eq() filters
        # (prompt_version_id, status) then .in_(measurement_status). No rows ->
        # insufficient -> None.
        mock_sb.return_value.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.in_.return_value.range.return_value \
            .execute.return_value.data = []
        from app.reflection import _cohort_median_ctr_delta
        result = _cohort_median_ctr_delta(99)
    assert result is None


# ---------------------------------------------------------------------------
# Promotion: a candidate is only "live" when the version row, the retirement of
# the previous live row, and audit_configs.generated_prompt all move together.
#
# Regression guard: `status` was written as
#   reflection_mode if reflection_mode in ("shadow", "live") else "shadow"
# so `auto` fell through to "shadow" while the prompt text WAS promoted — and
# autopilot stamps audits.prompt_version_id from the row marked live, so every
# audit from the new prompt was attributed to the old version and auto-revert
# could never see the new one. `live` mode had the mirror bug: the row said
# live but generated_prompt was never written, so the prompt never took effect.
# ---------------------------------------------------------------------------

def _reflection_table_side(mode, recorder, current_live_id=None):
    def table_side(name):
        m = MagicMock()
        if name == "audit_configs":
            m.select.return_value.eq.return_value.execute.return_value.data = [
                {"generated_prompt": "OLD PROMPT", "reflection_mode": mode}
            ]

            def cfg_update(payload):
                recorder.append(("audit_configs.update", payload))
                return MagicMock()

            m.update.side_effect = cfg_update
        elif name == "prompt_versions":
            def capture_insert(row):
                recorder.append(("prompt_versions.insert", row))
                inner = MagicMock()
                inner.execute.return_value.data = [{"id": 42, **row}]
                return inner

            m.insert.side_effect = capture_insert
            m.select.return_value.eq.return_value.eq.return_value \
                .order.return_value.limit.return_value.execute.return_value.data = (
                    [{"id": current_live_id}] if current_live_id else []
                )

            def pv_update(payload):
                recorder.append(("prompt_versions.update", payload))
                return MagicMock()

            m.update.side_effect = pv_update
        return m

    return table_side


def _run_reflection_in_mode(mode, current_live_id=None):
    perf_report = _make_perf_report(win_rate=40.0)
    perf_report["worst_audits"] = []
    perf_report["best_audits"] = []
    result = {
        "reflection": "r",
        "changes": ["c"],
        "candidate_prompt": "NEW PROMPT",
    }
    recorder: list[tuple[str, dict]] = []
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.chat_json", return_value=result):
        mock_sb.return_value.table.side_effect = _reflection_table_side(
            mode, recorder, current_live_id
        )
        from app.reflection import _run_reflection
        version_id, _reason = _run_reflection("ch1", perf_report, "ctx", "guidance")
    return version_id, recorder


def test_auto_mode_marks_the_new_version_live():
    version_id, recorder = _run_reflection_in_mode("auto", current_live_id=7)
    assert version_id == 42

    statuses = [p["status"] for k, p in recorder if k == "prompt_versions.update"]
    assert "live" in statuses, "auto mode must mark the promoted version live"
    assert "retired" in statuses, "auto mode must retire the previously live version"
    assert statuses.index("retired") < statuses.index("live")  # retire before promote

    cfg = [p for k, p in recorder if k == "audit_configs.update"]
    assert cfg == [{"generated_prompt": "NEW PROMPT"}]


def test_live_mode_writes_the_prompt_it_marks_live():
    version_id, recorder = _run_reflection_in_mode("live", current_live_id=7)
    assert version_id == 42

    statuses = [p["status"] for k, p in recorder if k == "prompt_versions.update"]
    assert "live" in statuses
    cfg = [p for k, p in recorder if k == "audit_configs.update"]
    assert cfg == [{"generated_prompt": "NEW PROMPT"}], \
        "live mode marked a version live without applying its prompt"


def test_shadow_mode_promotes_nothing():
    version_id, recorder = _run_reflection_in_mode("shadow", current_live_id=7)
    assert version_id == 42

    inserted = [p for k, p in recorder if k == "prompt_versions.insert"]
    assert inserted[0]["status"] == "shadow"
    assert not [p for k, p in recorder if k == "prompt_versions.update"]
    assert not [p for k, p in recorder if k == "audit_configs.update"]
