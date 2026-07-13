import socket
from unittest.mock import MagicMock, patch

import pytest
from pathlib import Path

from app.shorts.cutter.download import BGUTIL_POT_SCRIPT, is_youtube_url, ytdlp_options
from app.shorts.cutter.download import (
    _ensure_pot_provider_ready,
    _looks_like_token_failure,
    _provider_mint_token,
    refresh_pot_provider,
)
from app.shorts.cutter.errors import CutterError


def _fake_response(status_code=200, json_body=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    resp.text = text
    return resp


def test_youtube_urls_accepted():
    for url in [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=1s",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "youtube.com/watch?v=dQw4w9WgXcQ",
    ]:
        assert is_youtube_url(url), url


def test_non_youtube_urls_rejected():
    for url in ["https://vimeo.com/12345", "https://example.com/watch?v=dQw4w9WgXcQ", "not a url", ""]:
        assert not is_youtube_url(url), url


def test_ytdlp_options_native_quality_and_mweb():
    options = ytdlp_options()
    assert options["format"] == "bv*+ba/b"          # no height/codec cap
    assert options["merge_output_format"] == "mkv"
    clients = options["extractor_args"]["youtube"]["player_client"]
    assert clients[0] == "mweb" and "default" in clients


def test_ytdlp_options_po_token_backend_follows_script_presence():
    # The bgutil PO-token script is a gitignored local artifact: present on a
    # configured machine, absent in CI. ytdlp_options() must wire the script
    # backend when the file exists and degrade gracefully (omit it) when it
    # doesn't — so this test is environment-independent.
    options = ytdlp_options()
    if BGUTIL_POT_SCRIPT.is_file():
        script = options["extractor_args"]["youtubepot-bgutilscript"]["script_path"][0]
        assert Path(script) == BGUTIL_POT_SCRIPT
    else:
        assert "youtubepot-bgutilscript" not in options["extractor_args"]


def test_ytdlp_options_uses_http_provider_when_env_set(monkeypatch):
    monkeypatch.setenv("BGUTIL_POT_HTTP_BASE_URL", "http://bgutil-provider:4416")
    from app.shorts.cutter.download import ytdlp_options
    opts = ytdlp_options()
    ea = opts["extractor_args"]
    assert ea["youtubepot-bgutilhttp"]["base_url"] == ["http://bgutil-provider:4416"]
    assert "youtubepot-bgutilscript" not in ea   # HTTP takes precedence over script


def test_ytdlp_options_falls_back_to_script_when_env_absent(monkeypatch):
    monkeypatch.delenv("BGUTIL_POT_HTTP_BASE_URL", raising=False)
    from app.shorts.cutter.download import ytdlp_options, BGUTIL_POT_SCRIPT
    opts = ytdlp_options()
    ea = opts["extractor_args"]
    assert "youtubepot-bgutilhttp" not in ea
    # script provider present iff the local script exists (env-independent, matches CI)
    assert ("youtubepot-bgutilscript" in ea) == BGUTIL_POT_SCRIPT.is_file()


def test_pot_provider_preflight_raises_when_unreachable():
    # An unreachable provider must fail with an honest, actionable error rather
    # than letting yt-dlp degrade to a token-less client and report the source
    # video as "not available". Port 1 is not listening → connection refused.
    with pytest.raises(CutterError, match="PO-token provider unreachable"):
        _ensure_pot_provider_ready("http://127.0.0.1:1", attempts=1, delay=0)


def test_pot_provider_preflight_passes_when_listening_and_minting():
    # Port open AND the provider mints a token → ready.
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        with patch("app.shorts.cutter.download._provider_mint_token", return_value="tok"):
            _ensure_pot_provider_ready(f"http://127.0.0.1:{port}", attempts=1, delay=0)
    finally:
        srv.close()


def test_pot_provider_preflight_raises_when_port_open_but_not_minting():
    # The whole point of layer 1: a provider whose HTTP port is open but that
    # cannot mint a token must fail loudly here — otherwise yt-dlp silently
    # falls back to a token-less client and YouTube lies "video not available".
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        with patch("app.shorts.cutter.download._provider_mint_token",
                   side_effect=CutterError("empty token")):
            with pytest.raises(CutterError, match="empty token"):
                _ensure_pot_provider_ready(f"http://127.0.0.1:{port}", attempts=1, delay=0)
    finally:
        srv.close()


def test_provider_mint_token_returns_token_on_success():
    with patch("httpx.post", return_value=_fake_response(200, {"poToken": "abc123"})):
        assert _provider_mint_token("http://prov:4416") == "abc123"


def test_provider_mint_token_raises_on_empty_token():
    with patch("httpx.post", return_value=_fake_response(200, {"poToken": ""})):
        with pytest.raises(CutterError, match="empty token"):
            _provider_mint_token("http://prov:4416")


def test_provider_mint_token_raises_on_server_error():
    with patch("httpx.post", return_value=_fake_response(500, {"error": "boom"})):
        with pytest.raises(CutterError, match="could not mint"):
            _provider_mint_token("http://prov:4416")


def test_provider_mint_token_raises_when_unreachable():
    import httpx
    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(CutterError, match="unreachable"):
            _provider_mint_token("http://prov:4416")


def test_looks_like_token_failure_matches_the_misleading_error():
    assert _looks_like_token_failure("ERROR: [youtube] sHgbTxzyyc0: This video is not available")
    assert _looks_like_token_failure("Sign in to confirm you're not a bot")
    assert _looks_like_token_failure("Requested format is not available")


def test_looks_like_token_failure_ignores_unrelated_errors():
    assert not _looks_like_token_failure("HTTP Error 404: Not Found")
    assert not _looks_like_token_failure("Private video. Sign in if you've been granted access")


def test_refresh_pot_provider_is_best_effort_and_swallows_errors():
    import httpx
    # Even if the provider is unreachable, the scheduled refresh must never raise.
    with patch("httpx.post", side_effect=httpx.ConnectError("down")):
        refresh_pot_provider("http://prov:4416")  # no exception


def test_refresh_pot_provider_hits_invalidate_endpoints():
    calls = []

    def _record(url, *a, **k):
        calls.append(url)
        return _fake_response(204)

    with patch("httpx.post", side_effect=_record):
        refresh_pot_provider("http://prov:4416")
    assert any(u.endswith("/invalidate_it") for u in calls)


def test_fetch_video_retries_after_refreshing_provider_on_token_failure():
    yt_dlp = pytest.importorskip("yt_dlp")
    from app.shorts.cutter import download as dl

    dest = Path("/tmp/does-not-matter")
    good = (Path("/tmp/vid.mkv"), "Title")
    attempts = {"n": 0}

    def _dl_once(options, url, dest_dir):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise yt_dlp.utils.DownloadError("ERROR: [youtube] x: This video is not available")
        return good

    with patch.dict("os.environ", {"BGUTIL_POT_HTTP_BASE_URL": "http://prov:4416"}), \
         patch.object(dl, "_ensure_pot_provider_ready"), \
         patch.object(dl, "_download_once", side_effect=_dl_once), \
         patch.object(dl, "refresh_pot_provider") as refresh, \
         patch.object(dl, "_provider_mint_token", return_value="tok"), \
         patch("pathlib.Path.mkdir"):
        result = dl.fetch_video("https://youtu.be/x", dest)

    assert result == good
    assert attempts["n"] == 2          # retried exactly once
    # The retry must reset the *integrity token* (deep session state that goes
    # stale), not just per-video caches — otherwise a fresh mint is still built
    # on the stale session and the download fails again with "not available".
    refresh.assert_called_once_with("http://prov:4416")


def test_fetch_video_raises_honest_provider_error_when_mint_stays_dead():
    yt_dlp = pytest.importorskip("yt_dlp")
    from app.shorts.cutter import download as dl

    dest = Path("/tmp/does-not-matter")

    def _dl_once(options, url, dest_dir):
        raise yt_dlp.utils.DownloadError("ERROR: [youtube] x: This video is not available")

    with patch.dict("os.environ", {"BGUTIL_POT_HTTP_BASE_URL": "http://prov:4416"}), \
         patch.object(dl, "_ensure_pot_provider_ready"), \
         patch.object(dl, "_download_once", side_effect=_dl_once), \
         patch.object(dl, "refresh_pot_provider"), \
         patch.object(dl, "_provider_mint_token", side_effect=CutterError("empty token")), \
         patch("pathlib.Path.mkdir"):
        with pytest.raises(CutterError, match="provider is not minting"):
            dl.fetch_video("https://youtu.be/x", dest)
