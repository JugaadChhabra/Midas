from pathlib import Path

from app.shorts.cutter.download import is_youtube_url, ytdlp_options


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


def test_ytdlp_options_native_quality_mweb_and_po_token():
    options = ytdlp_options()
    assert options["format"] == "bv*+ba/b"          # no height/codec cap
    assert options["merge_output_format"] == "mkv"
    clients = options["extractor_args"]["youtube"]["player_client"]
    assert clients[0] == "mweb" and "default" in clients
    script = options["extractor_args"]["youtubepot-bgutilscript"]["script_path"][0]
    assert Path(script).is_file()
