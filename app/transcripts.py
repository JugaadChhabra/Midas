"""Fetch YouTube video transcripts as a content signal for audits.

The transcript is *content only* — its language never determines the output
language. The channel's `default_language` controls every generated string;
this module just hands the audit prompt the raw text + a detected-language tag
so the prompt can be explicit about the distinction.
"""
import logging
import re
from typing import Optional

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
)
from youtube_transcript_api.proxies import GenericProxyConfig, ProxyConfig, WebshareProxyConfig

from app.config import settings

log = logging.getLogger("midas.transcripts")

_LANG_NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "bn": "Bengali",
    "ta": "Tamil", "te": "Telugu", "gu": "Gujarati", "kn": "Kannada",
    "ml": "Malayalam", "pa": "Punjabi", "ur": "Urdu",
}


def lang_display_name(code: str | None) -> str:
    if not code:
        return "unknown"
    return _LANG_NAMES.get(code, code)


def _build_proxy_config() -> Optional[ProxyConfig]:
    if settings.WEBSHARE_PROXY_USERNAME and settings.WEBSHARE_PROXY_PASSWORD:
        log.info("Using Webshare rotating proxy for transcript fetches")
        return WebshareProxyConfig(
            proxy_username=settings.WEBSHARE_PROXY_USERNAME,
            proxy_password=settings.WEBSHARE_PROXY_PASSWORD,
        )
    if settings.YOUTUBE_PROXY_URL:
        log.info("Using generic proxy for transcript fetches: %s", settings.YOUTUBE_PROXY_URL)
        return GenericProxyConfig(https_url=settings.YOUTUBE_PROXY_URL)
    return None


_VTT_TIMESTAMP_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d+)")


def _vtt_to_snippets(vtt: str) -> list[dict]:
    """Parse WebVTT text into a list of {text, start} dicts."""
    snippets: list[dict] = []
    lines = vtt.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            m = _VTT_TIMESTAMP_RE.match(line)
            start = 0.0
            if m:
                h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                start = h * 3600 + mi * 60 + s + ms / 1000
            text_parts: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip():
                raw = lines[i].strip()
                raw = re.sub(r"<[^>]+>", "", raw)  # strip VTT inline tags
                if raw:
                    text_parts.append(raw)
                i += 1
            if text_parts:
                snippets.append({"text": " ".join(text_parts), "start": start})
        else:
            i += 1
    return snippets


def _fetch_via_captions_api(video_id: str, channel_id: str) -> tuple[str | None, str | None]:
    """Fallback: fetch transcript via YouTube Data API captions endpoints.

    Uses the channel owner's OAuth credentials so there is no IP restriction.
    Costs 50 (captions.list) + 200 (captions.download) = 250 quota units per call.
    """
    from app.youtube_client import (  # local import to avoid circular dependency
        TokenExpiredError,
        youtube_for_channel,
        yt_captions_download,
        yt_captions_list,
    )

    try:
        yt = youtube_for_channel(channel_id)
    except TokenExpiredError:
        log.warning("Token expired for channel %s — cannot fall back to captions API", channel_id)
        return None, None
    except Exception as e:
        log.warning("Could not build YouTube client for channel %s: %s", channel_id, e)
        return None, None

    try:
        items = yt_captions_list(yt, channel_id, video_id)
    except Exception as e:
        log.warning("captions.list failed for %s: %s", video_id, e)
        return None, None

    if not items:
        log.info("No caption tracks found via API for %s", video_id)
        return None, None

    # Prefer manual (non-ASR) tracks; fall back to ASR.
    manual = [t for t in items if t.get("snippet", {}).get("trackKind") != "asr"]
    asr = [t for t in items if t.get("snippet", {}).get("trackKind") == "asr"]
    track = (manual or asr or items)[0]

    caption_id = track["id"]
    lang = track.get("snippet", {}).get("language")

    try:
        raw = yt_captions_download(yt, channel_id, caption_id)
    except Exception as e:
        log.warning("captions.download failed for %s (track %s): %s", video_id, caption_id, e)
        return None, None

    snippets = _vtt_to_snippets(raw.decode("utf-8", errors="replace"))
    if not snippets:
        return None, None

    kept_parts: list[str] = []
    for s in snippets:
        if s["start"] < _PRE_ROLL_SKIP_SECONDS:
            continue
        if _is_ad_snippet(s["text"]):
            continue
        kept_parts.append(s["text"])

    text = " ".join(kept_parts).strip()
    if not text:
        return None, None

    if len(text) > settings.TRANSCRIPT_MAX_CHARS:
        text = text[:settings.TRANSCRIPT_MAX_CHARS] + " [...truncated]"

    log.info("Transcript for %s via captions API: %d chars (lang=%s)", video_id, len(text), lang)
    return text, lang


# Pre-roll filter. Many rhymes start with a 5–10s ad for the company's app
# (Play Store / App Store / Playschool plug, "subscribe now", etc.) before
# the actual song begins. We strip snippets that fall in the pre-roll window
# AND any snippet anywhere that mentions one of the ad markers — the second
# pass catches mid-roll plugs too.
_PRE_ROLL_SKIP_SECONDS = 12.0
_AD_MARKERS = (
    "play store", "app store", "playschool",
    "subscribe", "download",
)


def _is_ad_snippet(text: str) -> bool:
    t = text.lower()
    return any(marker in t for marker in _AD_MARKERS)


def _snippet_text(s) -> str:
    return getattr(s, "text", None) or (s.get("text") if isinstance(s, dict) else "") or ""


def _snippet_start(s) -> float:
    return float(getattr(s, "start", None) or (s.get("start") if isinstance(s, dict) else 0.0) or 0.0)


def _fetch_from_youtube(video_id: str, channel_id: str | None = None) -> tuple[str | None, str | None]:
    """Download from YouTube. Return (text, detected_language_code), both None when
    unavailable. Two network calls: list, then fetch. Callers should go through
    fetch_transcript() so the result is cached.

    Tries youtube-transcript-api first. On IP block, falls back to the YouTube
    Data API captions endpoints (requires channel_id for OAuth credentials).

    Preference order: manually-uploaded > auto-generated > anything available.
    Quality matters more than language match — channel.default_language drives
    output language regardless.
    """
    api = YouTubeTranscriptApi(proxy_config=_build_proxy_config())
    try:
        listing = api.list(video_id)
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
        log.info("No transcript for %s: %s", video_id, type(e).__name__)
        return None, None
    except RequestBlocked as e:
        log.warning("IP blocked fetching transcript for %s — trying captions API fallback", video_id)
        if channel_id:
            return _fetch_via_captions_api(video_id, channel_id)
        log.warning("No channel_id provided; cannot fall back to captions API for %s", video_id)
        return None, None
    except Exception as e:
        log.warning("Transcript listing failed for %s: %s", video_id, e)
        return None, None

    try:
        all_transcripts = list(listing)
    except Exception as e:
        log.warning("Transcript iteration failed for %s: %s", video_id, e)
        return None, None
    if not all_transcripts:
        return None, None

    manual = [t for t in all_transcripts if not getattr(t, "is_generated", True)]
    generated = [t for t in all_transcripts if getattr(t, "is_generated", False)]
    transcript = (manual or generated or all_transcripts)[0]

    try:
        fetched = transcript.fetch()
    except Exception as e:
        log.warning("Transcript fetch failed for %s: %s", video_id, e)
        return None, None

    kept_parts: list[str] = []
    dropped_preroll = 0
    dropped_ad = 0
    for s in fetched:
        snippet_text = _snippet_text(s)
        if not snippet_text:
            continue
        if _snippet_start(s) < _PRE_ROLL_SKIP_SECONDS:
            dropped_preroll += 1
            continue
        if _is_ad_snippet(snippet_text):
            dropped_ad += 1
            continue
        kept_parts.append(snippet_text)

    text = " ".join(kept_parts).strip()
    if not text:
        return None, None

    if len(text) > settings.TRANSCRIPT_MAX_CHARS:
        text = text[:settings.TRANSCRIPT_MAX_CHARS] + " [...truncated]"

    lang = getattr(transcript, "language_code", None)
    log.info(
        "Transcript for %s: %d chars (lang=%s, generated=%s, dropped_preroll=%d, dropped_ad=%d)",
        video_id, len(text), lang, getattr(transcript, "is_generated", None),
        dropped_preroll, dropped_ad,
    )
    return text, lang


# ── Cache ─────────────────────────────────────────────────────────────────────
# A transcript is immutable content, but _fetch_from_youtube costs two network
# calls, and every path that touches a video wanted its own copy: the audit, the
# embedding pass, each re-audit of a quarantined row, and one per shadow audit.
# Shadow audits are the worst offender by construction — they replay a candidate
# prompt over videos that have already been audited, so the text was certainly
# fetched before.
#
# Table, not a column on `videos`: audit_video() reads that row with select("*"),
# so widening it would pull up to 8 KB of transcript into every read that does not
# want it. See supabase/migrations/20260814000000_video_transcripts.sql.

#: How long a "no transcript" verdict stands before we look again. A video can gain
#: auto-captions after publish, so the negative cache has to expire — but not so
#: fast that captions-disabled videos are re-probed on every audit, which is the
#: cost this exists to remove.
NEGATIVE_CACHE_DAYS = 14


def _cache_read(video_id: str) -> Optional[dict]:
    from app.db import supabase

    res = (
        supabase().table("video_transcripts")
        .select("video_id,text,lang,available,fetched_at")
        .eq("video_id", video_id)
        .execute()
    )
    return (res.data or [None])[0]


def _cache_write(row: dict) -> None:
    from app.db import supabase

    supabase().table("video_transcripts").upsert(row).execute()


def _negative_is_stale(fetched_at: str | None) -> bool:
    from datetime import datetime, timedelta, timezone

    if not fetched_at:
        return True
    try:
        when = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when < datetime.now(timezone.utc) - timedelta(days=NEGATIVE_CACHE_DAYS)


def fetch_transcript(video_id: str, channel_id: str | None = None) -> tuple[str | None, str | None]:
    """(text, language_code) for a video, from cache when we already have it.

    Read-through: cache hit returns immediately, a miss downloads and stores. Both
    outcomes are stored — a video with no transcript records that fact, or it gets
    re-probed on every audit forever.

    Every cache operation is best-effort. This is an optimisation, and an
    unmigrated database or a write racing another worker must degrade to the old
    behaviour rather than stop auditing.
    """
    try:
        row = _cache_read(video_id)
    except Exception as e:
        log.warning("Transcript cache read failed for %s (%s); fetching live", video_id, e)
        row = None

    if row is not None:
        if row.get("available"):
            return row.get("text"), row.get("lang")
        if not _negative_is_stale(row.get("fetched_at")):
            return None, None
        log.info("Transcript for %s was unavailable %d+ days ago; re-probing",
                 video_id, NEGATIVE_CACHE_DAYS)

    text, lang = _fetch_from_youtube(video_id, channel_id)

    from datetime import datetime, timezone

    try:
        _cache_write({
            "video_id": video_id,
            "text": text,
            "lang": lang,
            "available": text is not None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        log.warning("Transcript cache write failed for %s (%s); continuing", video_id, e)

    return text, lang
