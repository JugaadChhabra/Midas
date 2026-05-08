"""Fetch YouTube video transcripts as a content signal for audits.

The transcript is *content only* — its language never determines the output
language. The channel's `default_language` controls every generated string;
this module just hands the audit prompt the raw text + a detected-language tag
so the prompt can be explicit about the distinction.
"""
import logging

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

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


def fetch_transcript(video_id: str) -> tuple[str | None, str | None]:
    """Return (text, detected_language_code). Both None when unavailable.

    Preference order: manually-uploaded > auto-generated > anything available.
    Quality matters more than language match — channel.default_language drives
    output language regardless.

    Uses the youtube-transcript-api 1.x instance API: `api.list()` returns a
    TranscriptList of Transcript objects; `transcript.fetch()` returns a
    FetchedTranscript iterable of snippet objects with `.text`.
    """
    api = YouTubeTranscriptApi()
    try:
        listing = api.list(video_id)
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
        log.info("No transcript for %s: %s", video_id, type(e).__name__)
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
