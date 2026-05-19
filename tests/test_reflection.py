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
    with patch("app.openrouter.httpx.post") as mock_post:
        mock_post.return_value = _mock_openrouter_response("hello world")
        from app.openrouter import chat_text
        result = chat_text("say hello", model="perplexity/sonar")
    assert result == "hello world"


def test_chat_text_raises_on_http_error():
    with patch("app.openrouter.httpx.post") as mock_post:
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
