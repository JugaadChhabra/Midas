"""Cut planning: full coverage, cuts only in vocal silence."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

MAX_CLIP_SECONDS = 58.0
MIN_CLIP_SECONDS = 4.0
PAUSE_CUT_SECONDS = 0.45
MAX_TRUSTED_TRANSCRIPT_GAP_SECONDS = 8.0
PAUSE_WINDOW_CAP_SECONDS = 10.0
SCENE_IN_SILENCE_BONUS = 3.0
WINDOW_LENGTH_BONUS_CAP = 2.0


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class Stanza:
    start: float
    end: float
    text: str
    boundary: str = "end"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def join_timed_text(items: list[TranscriptSegment]) -> str:
    """Preserve Whisper's leading spaces while also handling languages without them."""
    result = ""
    for item in items:
        value = item.text.strip()
        if not value:
            continue
        if not result:
            result = value
        elif item.text[:1].isspace() or value[:1] in ".,!?;:)]}।॥":
            result += item.text
        else:
            result += " " + value
    return result.strip()


def balanced_boundaries(duration: float, max_seconds: float) -> list[float]:
    """
    Return a safe, balanced timeline that covers 0..duration with no clip longer
    than max_seconds. For example, 185 seconds with a 58-second maximum becomes
    roughly 46, 46, 46, 47 rather than 58, 58, 58, 11.
    """
    if duration <= 0:
        return [0.0, 0.1]

    count = max(1, int(math.ceil(duration / max_seconds)))
    return [duration * index / count for index in range(count + 1)]


def lyric_pause_candidates(units: list[TranscriptSegment], duration: float) -> list[float]:
    """
    Get genuine lyric/speech pause positions from Whisper word timing.
    These are optional refinements only; they never decide whether video content
    is included, so weak transcription cannot make the middle disappear.
    """
    cleaned = sorted(
        [unit for unit in units if unit.end > unit.start and unit.text.strip()],
        key=lambda unit: (unit.start, unit.end),
    )

    candidates: list[float] = []
    previous: TranscriptSegment | None = None

    for unit in cleaned:
        if previous is not None:
            gap = max(0.0, unit.start - previous.end)
            if PAUSE_CUT_SECONDS <= gap <= MAX_TRUSTED_TRANSCRIPT_GAP_SECONDS:
                candidate = clamp((previous.end + unit.start) / 2, 0.0, duration)
                candidates.append(candidate)
        previous = unit

    # Deduplicate closely clustered pause candidates.
    deduped: list[float] = []
    for candidate in sorted(candidates):
        if not deduped or candidate - deduped[-1] >= 0.35:
            deduped.append(candidate)

    return deduped


def text_for_interval(
    units: list[TranscriptSegment],
    start: float,
    end: float,
    fallback: str,
) -> str:
    """Build a label/transcript snippet for one full-coverage output clip."""
    items = [
        unit for unit in units
        if unit.end > start and unit.start < end
    ]
    text = join_timed_text(items)
    return text or fallback


def _silent_candidates(
    silence: list[tuple[float, float]],
    scene_times: list[float],
    ideal: float,
    earliest: float,
    latest: float,
    prefer_visual_beats: bool,
) -> list[tuple[float, float, str]]:
    """Return (score, time, kind); lower score is better."""
    candidates: list[tuple[float, float, str]] = []
    for window_start, window_end in silence:
        low = max(earliest, window_start)
        high = min(latest, window_end)
        if low > high:
            continue
        point = clamp((window_start + window_end) / 2, low, high)
        bonus = 0.5 * min(window_end - window_start, WINDOW_LENGTH_BONUS_CAP)
        candidates.append((max(0.0, abs(point - ideal) - bonus), point, "pause"))
        if prefer_visual_beats:
            for scene_time in scene_times:
                if low <= scene_time <= high:
                    score = max(0.0, abs(scene_time - ideal) - SCENE_IN_SILENCE_BONUS)
                    candidates.append((score, scene_time, "scene-silent"))
    return candidates


def full_coverage_stanzas(
    units: list[TranscriptSegment],
    duration: float,
    max_seconds: float,
    silence: list[tuple[float, float]] | None = None,
    scene_times: list[float] | tuple = (),
    envelope: np.ndarray | None = None,
    hop: float = 0.05,
    prefer_visual_beats: bool = True,
    fallback_pauses: list[float] | None = None,
    short_silence: list[tuple[float, float]] | None = None,
) -> list[Stanza]:
    max_seconds = clamp(float(max_seconds or MAX_CLIP_SECONDS), 15.0, MAX_CLIP_SECONDS)
    if duration <= 0:
        return [Stanza(0.0, 0.1, "Empty video", "safety")]

    base = balanced_boundaries(duration, max_seconds)
    segment_count = len(base) - 1
    pause_window = min(PAUSE_WINDOW_CAP_SECONDS, max_seconds * 0.22)
    normalised: list[tuple[float, str]] = [(0.0, "start")]

    for index in range(1, segment_count):
        ideal = base[index]
        previous = normalised[-1][0]
        remaining = segment_count - index
        earliest = max(previous + MIN_CLIP_SECONDS, duration - remaining * max_seconds)
        latest = min(previous + max_seconds, duration - remaining * MIN_CLIP_SECONDS)

        if silence is not None:
            candidates = _silent_candidates(silence, list(scene_times), ideal,
                                            earliest, latest, prefer_visual_beats)
            if not candidates and short_silence:
                # No real line break in range: a short-but-real vocal pause
                # still beats cutting at an arbitrary quiet instant.
                candidates = [
                    (score, point, "short-pause")
                    for score, point, _kind in _silent_candidates(
                        short_silence, [], ideal, earliest, latest, False)
                ]
            if candidates:
                _score, chosen, kind = min(candidates,
                                           key=lambda c: (c[0], abs(c[1] - ideal)))
            elif envelope is not None and len(envelope):
                lo = max(0, int(earliest / hop))
                hi = min(len(envelope), max(lo + 1, int(latest / hop) + 1))
                if lo >= len(envelope):
                    chosen, kind = clamp(ideal, earliest, latest), "forced"
                else:
                    chosen = (lo + int(np.argmin(envelope[lo:hi]))) * hop
                    chosen = clamp(chosen, earliest, latest)
                    kind = "forced"
            else:
                chosen, kind = clamp(ideal, earliest, latest), "forced"
        else:
            # Degraded mode: no vocal data — old Whisper-gap behaviour.
            pauses = [p for p in (fallback_pauses or [])
                      if earliest <= p <= latest and abs(p - ideal) <= pause_window]
            if pauses:
                chosen = min(pauses, key=lambda p: abs(p - ideal))
                kind = "pause"
            else:
                chosen, kind = clamp(ideal, earliest, latest), "balanced"

        normalised.append((chosen, kind))

    normalised.append((duration, "end"))

    # --- assembly + full-coverage repair guard: copied VERBATIM from the old
    # main.py full_coverage_stanzas (lines 969–1038), unchanged ---
    stanzas: list[Stanza] = []
    for index in range(len(normalised) - 1):
        start = normalised[index][0]
        end = normalised[index + 1][0]
        boundary = normalised[index + 1][1]

        if end - start > max_seconds:
            end = min(duration, start + max_seconds)
            boundary = "safety"
        if end - start < 0.10:
            continue

        label = f"Rhyme Short {index + 1}"
        stanzas.append(
            Stanza(
                round(start, 3),
                round(end, 3),
                text_for_interval(units, start, end, label),
                boundary,
            )
        )

    if not stanzas:
        stanzas = [Stanza(0.0, duration, "Rhyme Short 1", "safety")]

    # Final full-coverage guard. It preserves every frame from 0 to duration,
    # even with weak audio/visual recognition or imperfect timestamps.
    repaired: list[Stanza] = []
    cursor = 0.0
    for index, stanza in enumerate(stanzas, start=1):
        end = duration if index == len(stanzas) else stanza.end
        end = min(duration, max(cursor + 0.10, end))

        while end - cursor > max_seconds + 0.001:
            piece_end = min(duration, cursor + max_seconds)
            repaired.append(
                Stanza(
                    round(cursor, 3),
                    round(piece_end, 3),
                    text_for_interval(units, cursor, piece_end, f"Rhyme Short {len(repaired) + 1}"),
                    "safety",
                )
            )
            cursor = piece_end

        repaired.append(
            Stanza(
                round(cursor, 3),
                round(end, 3),
                stanza.text or f"Rhyme Short {len(repaired) + 1}",
                stanza.boundary,
            )
        )
        cursor = end

    if repaired[-1].end < duration - 0.01:
        start = repaired[-1].end
        while start < duration - 0.01:
            end = min(duration, start + max_seconds)
            repaired.append(
                Stanza(
                    round(start, 3),
                    round(end, 3),
                    text_for_interval(units, start, end, f"Rhyme Short {len(repaired) + 1}"),
                    "safety",
                )
            )
            start = end

    return [item for item in repaired if item.end - item.start >= 0.10]


DOWNBEAT_LEAD_MIN = 0.3
DOWNBEAT_LEAD_MAX = 1.2
ONSET_LEAD_SECONDS = 0.4
END_DECAY_SECONDS = 0.5
END_EXTEND_MAX_SECONDS = 1.5


def finesse_boundaries(
    start: float,
    end: float,
    silence: list[tuple[float, float]],
    downbeats: list[float],
    duration: float,
) -> tuple[float, float, str, str]:
    """start = stanza vocal onset, end = stanza vocal offset. Walk the start
    back onto a downbeat (a breath of lead-in, on the beat) and the end out to
    the next downbeat while the rhyme decays. Never leave vocal silence."""
    lead_zone = next(((a, min(b, start)) for a, b in silence
                      if a <= start <= b + 0.1), None)
    new_start, start_kind = max(0.0, start - ONSET_LEAD_SECONDS), "onset"
    if lead_zone:
        new_start = clamp(new_start, lead_zone[0], start)
    lead_beats = [b for b in downbeats
                  if DOWNBEAT_LEAD_MIN <= start - b <= DOWNBEAT_LEAD_MAX
                  and (lead_zone is None or b >= lead_zone[0])]
    if lead_beats and lead_zone:
        new_start, start_kind = max(lead_beats), "downbeat"

    tail_zone = next(((max(a, end), b) for a, b in silence
                      if a - 0.1 <= end <= b), None)
    new_end, end_kind = min(duration, end + END_DECAY_SECONDS), "decay"
    if tail_zone:
        new_end = clamp(new_end, end, tail_zone[1])
    tail_beats = [b for b in downbeats
                  if 0.0 < b - end <= END_EXTEND_MAX_SECONDS
                  and tail_zone is not None and b <= tail_zone[1]]
    if tail_beats:
        new_end, end_kind = min(tail_beats), "downbeat"

    return round(new_start, 3), round(new_end, 3), start_kind, end_kind


def pad_clip(
    start: float,
    end: float,
    silence: list[tuple[float, float]],
    min_seconds: float,
    duration: float,
) -> tuple[float, float]:
    """Stretch a short clip toward min_seconds by taking instrumental lead-in/
    lead-out from the silence windows its boundaries sit in (a human editor
    pads a short hook the same way). Video edges count as available room.
    Best effort: never leaves the windows, may still come up short."""
    front_window = next(((a, b) for a, b in silence if a <= start <= b + 0.05),
                        None)
    back_window = next(((a, b) for a, b in silence if a - 0.05 <= end <= b),
                       None)
    front_limit = front_window[0] if front_window else start
    if front_limit <= 0.05 or start <= 0.05:
        front_limit = 0.0
    back_limit = back_window[1] if back_window else end
    back_limit = min(back_limit, duration)

    deficit = min_seconds - (end - start)
    if deficit <= 0:
        return start, end
    front_room = start - front_limit
    back_room = back_limit - end
    take_front = min(front_room, deficit / 2)
    take_back = min(back_room, deficit - take_front)
    take_front = min(front_room, deficit - take_back)  # rebalance leftovers
    return round(start - take_front, 3), round(end + take_back, 3)
