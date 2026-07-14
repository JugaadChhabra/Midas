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


# yt-dlp emits these when it was forced onto a token-less client (the PO-token
# provider handed it nothing). YouTube then wrongly reports a live video as gone.
# Matching them lets us refresh the provider and retry instead of failing as if
# the source video were deleted. Kept lowercase for case-insensitive matching.
TOKENLESS_FAILURE_SIGNATURES = (
    "this video is not available",
    "sign in to confirm you're not a bot",
    "requested format is not available",
    "no video formats found",
)


def _looks_like_token_failure(message: str) -> bool:
    """True when a yt-dlp error smells like a token-less fallback, not a real
    missing/private video."""
    m = (message or "").lower()
    return any(sig in m for sig in TOKENLESS_FAILURE_SIGNATURES)


def _provider_mint_token(base_url: str, timeout: float = 30.0, bypass_cache: bool = False) -> str:
    """Ask the bgutil sidecar to actually mint a PO token. Returns a non-empty
    token or raises CutterError. This proves the provider *works* — not merely
    that its HTTP port is open, which is the gap that lets token-less downloads
    slip through and surface as "video not available"."""
    import httpx

    url = f"{base_url.rstrip('/')}/get_pot"
    body = {"bypass_cache": True} if bypass_cache else {}
    try:
        resp = httpx.post(url, json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        raise CutterError(
            f"PO-token provider unreachable at {base_url} — shorts downloads need it. "
            f"Is the bgutil-provider sidecar running? ({exc})"
        ) from exc
    if resp.status_code != 200:
        detail = ""
        try:
            detail = (resp.json() or {}).get("error", "")
        except Exception:
            detail = (resp.text or "")[:200]
        raise CutterError(
            f"PO-token provider at {base_url} could not mint a token "
            f"(HTTP {resp.status_code}: {detail}). Restart the bgutil-provider sidecar."
        )
    token = (resp.json() or {}).get("poToken")
    if not token:
        raise CutterError(
            f"PO-token provider at {base_url} returned an empty token — it is up but not "
            f"minting. yt-dlp would fall back to a token-less client and YouTube would "
            f"wrongly report the video as unavailable. Restart the bgutil-provider sidecar."
        )
    return token


def refresh_pot_provider(base_url: str | None = None, timeout: float = 10.0) -> None:
    """Force the sidecar to re-establish its session. Called on a schedule so a
    long-lived provider never drifts into serving a stale integrity token (a
    known bgutil failure mode). Fully best-effort — never raises."""
    import httpx

    base_url = base_url or os.getenv("BGUTIL_POT_HTTP_BASE_URL")
    if not base_url:
        return
    base = base_url.rstrip("/")
    # /invalidate_it drops the integrity token (the deep session state that goes
    # stale); /invalidate_caches drops cached per-video tokens. Do both.
    for path in ("/invalidate_it", "/invalidate_caches"):
        try:
            httpx.post(f"{base}{path}", timeout=timeout)
        except httpx.HTTPError:
            pass


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
        # YouTube requires a JS runtime to solve the "n" signature challenge, or it
        # returns no formats ("video not available") even with a valid PO token.
        # node ships on the dev Mac and is installed in the Docker image (Dockerfile).
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
                break
        except OSError as exc:
            last_err = exc
            if i < attempts - 1:
                time.sleep(delay)
    else:
        raise CutterError(
            f"PO-token provider unreachable at {base_url} — shorts downloads need it. "
            f"Is the bgutil-provider sidecar running? ({last_err})"
        )
    # The port being open only proves the HTTP server booted — not that it can
    # mint. Prove minting works before we start the download, else yt-dlp
    # silently drops to a token-less client and YouTube lies "video not
    # available". A couple retries ride out a slow first botguard solve.
    mint_err: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            _provider_mint_token(base_url)
            return
        except CutterError as exc:
            mint_err = exc
            if i < attempts - 1:
                time.sleep(delay)
    raise mint_err


def _download_once(options: dict, url: str, dest_dir: Path) -> tuple[Path, str]:
    """One yt-dlp download pass. Raises yt_dlp.utils.DownloadError on failure so
    the caller can decide whether it's a token issue worth retrying."""
    import yt_dlp

    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url.strip(), download=True)
    requested = (info or {}).get("requested_downloads") or []
    downloaded_path = Path(requested[0]["filepath"]) if requested else None
    if downloaded_path is None or not downloaded_path.is_file():
        raise CutterError("The link did not produce a playable video file. Check that the video is public.")
    return downloaded_path, safe_name(str(info.get("title") or "downloaded_video"))


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
        return _download_once(options, url, dest_dir)
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc)
        # A token-less fallback makes YouTube wrongly report a live video as
        # "not available". Retry once on that signature — in BOTH provider modes,
        # because the failure is transient and a fresh token usually fixes it
        # ("failed, but worked on retry"). Never surface the misleading "not
        # available" as if the video were deleted.
        if _looks_like_token_failure(msg):
            if http_base:
                # HTTP provider (Docker): fully refresh — drop BOTH the stale
                # integrity token (/invalidate_it) and per-video caches
                # (/invalidate_caches) — then re-mint and retry. Only clearing the
                # per-video cache re-mints on the same stale session and fails
                # again identically.
                refresh_pot_provider(http_base)
                try:
                    _provider_mint_token(http_base, bypass_cache=True)
                except CutterError as mint_exc:
                    raise CutterError(
                        "Download failed and the PO-token provider is not minting valid tokens "
                        "(this is a provider issue, not a missing video). "
                        f"Restart the bgutil-provider sidecar. ({mint_exc})"
                    ) from exc
                try:
                    return _download_once(options, url, dest_dir)
                except yt_dlp.utils.DownloadError as exc2:
                    raise CutterError(
                        "Download still failed after refreshing the PO-token provider. "
                        "If the video plays in a browser, the provider likely needs updating or "
                        f"restarting — the video is not the problem. ({exc2})"
                    ) from exc2
            else:
                # Script mode (local node script): it re-mints a fresh token on
                # every yt-dlp invocation, so a plain retry is the equivalent of
                # refresh-and-retry. Previously this path had NO retry, so the
                # first transient token-less blip failed the whole job.
                try:
                    return _download_once(options, url, dest_dir)
                except yt_dlp.utils.DownloadError as exc2:
                    raise CutterError(
                        "Download failed twice with a token-less error. If the video plays "
                        "in a browser, the local PO-token script isn't minting a valid token "
                        f"— check that node and the bgutil script work. ({exc2})"
                    ) from exc2
        raise CutterError(f"Could not download this video link: {exc}") from exc
