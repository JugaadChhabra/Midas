"""Native-quality YouTube download: yt-dlp with mweb client + bgutil PO tokens."""
from __future__ import annotations

import os
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

from app.shorts.cutter.errors import CutterError
from app.shorts.cutter.util import safe_name

MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024 * 1024

# app/shorts/cutter/download.py -> repo root is parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
BGUTIL_POT_SCRIPT = _REPO_ROOT / "tools" / "bgutil-pot" / "server" / "build" / "generate_once.js"

# Keep in sync with the client-side check in app/static/shorts.html.
YOUTUBE_URL_RE = re.compile(
    r"^(https?://)?(www\.|m\.)?"
    r"(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)"
    r"[A-Za-z0-9_-]{11}([&?/].*)?$"
)


def is_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_URL_RE.match(url.strip()))


def ytdlp_options() -> dict:
    # The user's channel videos are PO-token-gated: without a token YouTube caps
    # downloads at 360p (or returns no formats at all when embedding is disabled).
    # bgutil's script mode mints tokens per request via node; mweb is the client
    # that actually serves full-quality https formats with a token, with the
    # default client rotation kept as fallback for videos where mweb misses.
    options = {
        # Grab the true best streams at the source's native resolution/fps —
        # above 1080p YouTube only serves VP9/AV1, so no codec/container filter.
        # MKV holds any codec pair; the pipeline re-renders clips to mp4 anyway.
        "format": "bv*+ba/b",
        "merge_output_format": "mkv",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_DOWNLOAD_BYTES,
        # YouTube requires a JS runtime for anti-bot challenges; node ships on this Mac.
        "js_runtimes": {"deno": {"path": None}, "node": {"path": None}},
        "remote_components": ["ejs:github"],
        "extractor_args": {"youtube": {"player_client": ["mweb", "default"]}},
    }
    http_base = os.getenv("BGUTIL_POT_HTTP_BASE_URL")
    if http_base:
        # Docker: a bgutil-provider sidecar mints tokens over HTTP.
        options["extractor_args"]["youtubepot-bgutilhttp"] = {"base_url": [http_base]}
    elif BGUTIL_POT_SCRIPT.is_file():
        # Mac: mint tokens per request via the local node script.
        options["extractor_args"]["youtubepot-bgutilscript"] = {
            "script_path": [str(BGUTIL_POT_SCRIPT)],
        }
    return options


def _ensure_pot_provider_ready(base_url: str, attempts: int = 5, delay: float = 2.0) -> None:
    """Wait for the bgutil PO-token sidecar to accept connections, or fail clearly.

    In Docker the provider is a separate service, so a job can start before it is
    ready (startup race) or when it is down. Without a token yt-dlp silently drops
    to a token-less client and YouTube answers "This video is not available" — a
    misleading error that looks like the source video is gone. A short connect
    retry rides out the startup race; a persistent failure is reported honestly.
    """
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        return  # malformed URL — let yt-dlp surface its own error
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    last_err: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return
        except OSError as exc:
            last_err = exc
            if i < attempts - 1:
                time.sleep(delay)
    raise CutterError(
        f"PO-token provider unreachable at {base_url} — shorts downloads need it. "
        f"Is the bgutil-provider sidecar running? ({last_err})"
    )


def fetch_video(url: str, dest_dir: Path) -> tuple[Path, str]:
    """Download `url` into dest_dir at native quality. Returns (path, safe title)."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise CutterError("ML dependencies not installed — run: pip install -r requirements-ml.txt") from exc
    dest_dir.mkdir(parents=True, exist_ok=True)
    options = ytdlp_options()
    http_base = os.getenv("BGUTIL_POT_HTTP_BASE_URL")
    if http_base:
        _ensure_pot_provider_ready(http_base)
    options["outtmpl"] = str(dest_dir / "source_%(id)s.%(ext)s")
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url.strip(), download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise CutterError(f"Could not download this video link: {exc}") from exc
    requested = (info or {}).get("requested_downloads") or []
    downloaded_path = Path(requested[0]["filepath"]) if requested else None
    if downloaded_path is None or not downloaded_path.is_file():
        raise CutterError("The link did not produce a playable video file. Check that the video is public.")
    return downloaded_path, safe_name(str(info.get("title") or "downloaded_video"))
