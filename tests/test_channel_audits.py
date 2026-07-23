from unittest.mock import MagicMock, patch

from app.channel_audits import audits_for_channel


def _run(columns="id,video_id,status", video_columns="channel_id"):
    """Build the query against a fake client and return (sb, result)."""
    sb = MagicMock()
    with patch("app.channel_audits.supabase", return_value=sb):
        result = audits_for_channel("UC_test", columns, video_columns)
    return sb, result


def test_queries_audits_table_not_videos():
    # The whole point: scope audits by channel WITHOUT a separate videos pull
    # (the old all-video-ids form truncated at Supabase's 1000-row cap).
    sb, _ = _run()
    sb.table.assert_called_once_with("audits")
    tables = [c.args[0] for c in sb.table.call_args_list]
    assert "videos" not in tables


def test_select_embeds_inner_join_on_videos():
    sb, _ = _run(columns="id,video_id,status,created_at")
    select_arg = sb.table.return_value.select.call_args.args[0]
    assert select_arg == "id,video_id,status,created_at,videos!inner(channel_id)"


def test_filters_on_embedded_channel_id():
    sb, _ = _run()
    sb.table.return_value.select.return_value.eq.assert_called_once_with(
        "videos.channel_id", "UC_test"
    )


def test_video_columns_widen_the_embed():
    sb, _ = _run(columns="id,video_id", video_columns="channel_id,title")
    select_arg = sb.table.return_value.select.call_args.args[0]
    assert select_arg == "id,video_id,videos!inner(channel_id,title)"


def test_returns_chainable_query():
    # Callers chain .eq()/.order()/.limit()/.execute() onto the result.
    sb, result = _run()
    assert result is sb.table.return_value.select.return_value.eq.return_value
