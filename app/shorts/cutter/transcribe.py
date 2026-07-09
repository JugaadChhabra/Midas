"""Multilingual Whisper transcription and transcript/SRT output."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path

from app.shorts.cutter.cutplan import Stanza, TranscriptSegment
from app.shorts.cutter.errors import CutterError

WHISPER_MODEL_NAME = "small"

_WHISPER_MODEL = None
_MODEL_LOCK = threading.Lock()


def get_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise CutterError("Multilingual lyrics packages are missing. Run: python -m pip install -r requirements-stanza.txt") from exc
    with _MODEL_LOCK:
        if _WHISPER_MODEL is None:
            try:
                # CPU + int8 works on ordinary Windows PCs. GPU acceleration can be added later.
                _WHISPER_MODEL = WhisperModel(WHISPER_MODEL_NAME, device="cpu", compute_type="int8")
            except Exception as exc:
                raise CutterError(f"Could not download/load the multilingual lyrics model. Keep internet on for the first run. Details: {exc}") from exc
    return _WHISPER_MODEL


def should_retry_without_vad(
    units: list[TranscriptSegment],
    duration: float,
    silence: list[tuple[float, float]] | None = None,
    min_fraction: float = 0.15,
    cap_seconds: float = 20.0,
) -> bool:
    """Silero VAD often mangles singing-over-music: either nothing at all or a
    few hallucinated scraps. Retry when transcript coverage is a sliver of the
    video (< 15%, capped at 20s so long videos aren't held to a huge bar).
    Transcript time spanning known vocal silence is hallucination, not
    coverage — subtract it, or one giant hallucinated blob defeats the check."""
    if not units:
        return True
    coverage = 0.0
    for unit in units:
        length = max(0.0, unit.end - unit.start)
        for a, b in silence or []:
            length -= max(0.0, min(b, unit.end) - max(a, unit.start))
        coverage += max(0.0, length)
    return coverage < min(cap_seconds, min_fraction * max(duration, 1e-6))


def transcribe_multilingual(
    source: Path,
    duration: float = 0.0,
    vocal_silence: list[tuple[float, float]] | None = None,
    language: str | None = None,
) -> tuple[str, float, list[TranscriptSegment], list[TranscriptSegment]]:
    """
    Keep normal Whisper phrases for the downloadable SRT, but also return word-level
    timestamp units for cutting. The old version only used phrase segments, so one
    2:40 Whisper phrase could become one 2:40 output clip.
    """
    model = get_whisper_model()
    try:
        segments, info = model.transcribe(
            str(source),
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=False,
            temperature=0.0,  # no sampling fallback: stable output across runs
            language=language,
            vad_parameters={"min_silence_duration_ms": 350},
        )
        segments = list(segments)
        vad_units = [
            TranscriptSegment(float(s.start), float(s.end), (s.text or "").strip())
            for s in segments if (s.text or "").strip() and s.end > s.start
        ]
        if should_retry_without_vad(vad_units, duration, vocal_silence):
            # Silero VAD often mangles singing-over-music: nothing at all, or a
            # few hallucinated scraps. Retry without VAD — downstream cut
            # safety never depends on Whisper, so hallucination risk only
            # affects labels, and structure bounds are envelope-refined anyway.
            segments, info = model.transcribe(
                str(source),
                beam_size=5,
                vad_filter=False,
                word_timestamps=True,
                condition_on_previous_text=False,
                temperature=0.0,
                language=language,
            )
            segments = list(segments)
        phrases: list[TranscriptSegment] = []
        timing_units: list[TranscriptSegment] = []

        for item in segments:
            start = float(item.start)
            end = float(item.end)
            phrase_text = (item.text or "").strip()
            if phrase_text and end > start:
                phrases.append(TranscriptSegment(start, end, phrase_text))

            usable_words = []
            for word in list(getattr(item, "words", None) or []):
                word_text = str(getattr(word, "word", "") or "")
                word_start = getattr(word, "start", None)
                word_end = getattr(word, "end", None)
                if word_start is None or word_end is None or not word_text.strip():
                    continue
                word_start = float(word_start)
                word_end = float(word_end)
                if word_end > word_start:
                    usable_words.append(TranscriptSegment(word_start, word_end, word_text))

            if usable_words:
                timing_units.extend(usable_words)
            elif phrase_text and end > start:
                # Fallback for a language/model frame without word timestamps.
                timing_units.append(TranscriptSegment(start, end, phrase_text))

        return (
            str(info.language or "unknown"),
            float(info.language_probability or 0),
            phrases,
            timing_units,
        )
    except Exception as exc:
        raise CutterError(f"Could not analyse lyrics/audio. Details: {exc}") from exc


def save_transcript(
    job_folder: Path,
    language: str,
    probability: float,
    segments: list[TranscriptSegment],
    stanzas: list[Stanza],
    visual_beats: list[dict] | None = None,
    silence_windows: list | None = None,
    grades: list[dict] | None = None,
) -> None:
    payload = {
        "language": language,
        "language_probability": probability,
        "segments": [asdict(x) for x in segments],
        "stanzas": [asdict(x) for x in stanzas],
        "visual_beats": visual_beats or [],
        "silence_windows": silence_windows or [],
        "grades": grades or [],
    }
    (job_folder / "lyrics_timestamps.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (job_folder / "visual_story_beats.json").write_text(
        json.dumps(visual_beats or [], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    srt = []
    for index, segment in enumerate(segments, start=1):
        srt.extend([str(index), f"{format_srt_time(segment.start)} --> {format_srt_time(segment.end)}", segment.text, ""])
    (job_folder / "lyrics_detected.srt").write_text("\n".join(srt), encoding="utf-8")


def format_srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds_int, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds_int:02},{milliseconds:03}"
