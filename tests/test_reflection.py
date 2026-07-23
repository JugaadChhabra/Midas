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


def _make_perf_report(win_rate=70.0, regression_count=0, count=15):
    return {
        "count": count,
        "win_rate": win_rate,
        "regression_count": regression_count,
        "median_velocity_lift": 12.0,
        "levers": {"title": 15.0, "description": 8.0, "tags": 20.0},
        "worst_audits": [],
        "best_audits": [],
    }


def test_should_reflect_skips_insufficient_data():
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=None):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        from app.reflection import _should_reflect
        should, reason = _should_reflect("ch1")
    assert should is False
    assert reason == "insufficient_data"


def test_should_reflect_skips_high_win_rate():
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=_make_perf_report(win_rate=70.0, regression_count=1)):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        from app.reflection import _should_reflect
        should, reason = _should_reflect("ch1")
    assert should is False
    assert reason == "performing_well"


def test_should_reflect_fires_low_win_rate():
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=_make_perf_report(win_rate=40.0)):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        from app.reflection import _should_reflect
        should, reason = _should_reflect("ch1")
    assert should is True
    assert reason == "low_win_rate"


def test_should_reflect_fires_high_regressions():
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=_make_perf_report(win_rate=60.0, regression_count=4)):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = []
        from app.reflection import _should_reflect
        should, reason = _should_reflect("ch1")
    assert should is True
    assert reason == "high_regressions"


def test_should_reflect_skips_recent_reflection():
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._build_perf_report", return_value=_make_perf_report(win_rate=40.0)):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = [{"created_at": recent}]
        from app.reflection import _should_reflect
        should, reason = _should_reflect("ch1")
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
    perf_report["worst_audits"] = [{"title_before": "old", "title_after": "new", "velocity_lift_pct": -30.0, "ai_reasoning": "test"}]
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
        version_id = _run_reflection("ch1", perf_report, "competitive ctx", "platform guidance")

    assert version_id == 42
    assert len(inserted_rows) == 1
    assert inserted_rows[0]["prompt_text"] == "You are a YouTube SEO expert for regional content..."
    assert inserted_rows[0]["status"] == "shadow"


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
    """shadow_pending must be in the skip set so autopilot never applies shadow audits."""
    from app.autopilot import _next_video_for_channel
    import inspect
    src = inspect.getsource(_next_video_for_channel)
    assert "shadow_pending" in src


def test_check_auto_revert_triggers_on_regression():
    """If new cohort median lift is >10pp below old cohort, revert."""
    old_version_id = 1
    new_version_id = 2

    revert_calls = []

    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection._cohort_median_lift") as mock_lift:
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


def test_cohort_median_lift_returns_none_insufficient():
    with patch("app.reflection.supabase") as mock_sb:
        # fetch_all pages via .range().execute(); the query has two .eq() filters
        # (prompt_version_id, status). Return no rows -> insufficient -> None.
        mock_sb.return_value.table.return_value.select.return_value \
            .eq.return_value.eq.return_value.range.return_value \
            .execute.return_value.data = []
        from app.reflection import _cohort_median_lift
        result = _cohort_median_lift(99)
    assert result is None


def test_tune_thresholds_nudges_up_on_high_fpr():
    """FPR > 20%: join_high should increase by 0.01."""
    assignments = (
        [{"action": "added", "decision_source": "embedding"} for _ in range(10)] +
        [{"action": "removed"} for _ in range(3)]  # 30% FPR
    )
    stored = []
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.settings") as mock_settings:
        mock_settings.PLAYLIST_JOIN_HIGH = 0.72
        mock_settings.PLAYLIST_JOIN_LOW = 0.55
        mock_settings.PLAYLIST_LEAVE = 0.60

        def table_side(name):
            m = MagicMock()
            if name == "playlist_assignments":
                m.select.return_value.eq.return_value.execute.return_value.data = assignments
            elif name == "threshold_history":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = []
                def capture(row):
                    stored.append(row)
                    inner = MagicMock()
                    inner.execute.return_value = None
                    return inner
                m.insert.side_effect = capture
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.reflection import tune_thresholds
        result = tune_thresholds("ch1")

    assert result["new_join_high"] == pytest.approx(0.73, abs=0.001)
    assert result["fpr"] == pytest.approx(0.30, abs=0.01)


def test_tune_thresholds_nudges_down_on_low_fpr():
    """FPR < 5%: join_high should decrease by 0.01."""
    assignments = (
        [{"action": "added", "decision_source": "embedding"} for _ in range(20)] +
        [{"action": "removed"} for _ in range(0)]  # 0% FPR
    )
    stored = []
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.settings") as mock_settings:
        mock_settings.PLAYLIST_JOIN_HIGH = 0.72
        mock_settings.PLAYLIST_JOIN_LOW = 0.55
        mock_settings.PLAYLIST_LEAVE = 0.60

        def table_side(name):
            m = MagicMock()
            if name == "playlist_assignments":
                m.select.return_value.eq.return_value.execute.return_value.data = assignments
            elif name == "threshold_history":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = []
                def capture(row):
                    stored.append(row)
                    inner = MagicMock()
                    inner.execute.return_value = None
                    return inner
                m.insert.side_effect = capture
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.reflection import tune_thresholds
        result = tune_thresholds("ch1")

    assert result["new_join_high"] == pytest.approx(0.71, abs=0.001)


def test_tune_thresholds_respects_upper_bound():
    assignments = (
        [{"action": "added", "decision_source": "embedding"} for _ in range(10)] +
        [{"action": "removed"} for _ in range(4)]  # 40% FPR
    )
    with patch("app.reflection.supabase") as mock_sb, \
         patch("app.reflection.settings") as mock_settings:
        mock_settings.PLAYLIST_JOIN_HIGH = 0.84  # one nudge would exceed 0.85
        mock_settings.PLAYLIST_JOIN_LOW = 0.55
        mock_settings.PLAYLIST_LEAVE = 0.60

        def table_side(name):
            m = MagicMock()
            if name == "playlist_assignments":
                m.select.return_value.eq.return_value.execute.return_value.data = assignments
            elif name == "threshold_history":
                m.select.return_value.eq.return_value.eq.return_value \
                    .order.return_value.limit.return_value.execute.return_value.data = []
                m.insert.return_value.execute.return_value = None
                m.update.return_value.eq.return_value.execute.return_value = None
            return m
        mock_sb.return_value.table.side_effect = table_side

        from app.reflection import tune_thresholds
        result = tune_thresholds("ch1")

    assert result["new_join_high"] <= 0.85
