import socket

import pytest
from pathlib import Path

from app.shorts.cutter.download import BGUTIL_POT_SCRIPT, is_youtube_url, ytdlp_options
from app.shorts.cutter.download import _ensure_pot_provider_ready
from app.shorts.cutter.errors import CutterError


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


def test_pot_provider_preflight_passes_when_listening():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        _ensure_pot_provider_ready(f"http://127.0.0.1:{port}", attempts=1, delay=0)
    finally:
        srv.close()
