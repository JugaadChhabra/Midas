"""Song structure: stanzas, chorus repetition groups, beat grid. Pure module."""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np

from app.shorts.cutter.cutplan import TranscriptSegment, clamp, join_timed_text

STANZA_SILENCE_SECONDS = 1.4
LYRIC_SIMILARITY_THRESHOLD = 0.70
MIN_AUDIO_REPEAT_SECONDS = 8.0
BOUND_REFINE_WINDOW = 0.6


@dataclass
class LyricStanza:
    index: int
    start: float
    end: float
    text: str
    repetition_group: int | None = None
    is_chorus: bool = False


@dataclass
class SongStructure:
    stanzas: list[LyricStanza]
    tempo: float
    beats: list[float]
    downbeats: list[float]
    chorus_source: str  # "lyrics" | "audio" | "none"


def group_stanzas(
    units: list[TranscriptSegment],
    silence: list[tuple[float, float]],
    gap_seconds: float = STANZA_SILENCE_SECONDS,
) -> list[LyricStanza]:
    cleaned = sorted(
        [u for u in units if u.end > u.start and u.text.strip()],
        key=lambda u: (u.start, u.end),
    )
    if not cleaned:
        return []

    def long_break(prev_end: float, next_start: float) -> bool:
        if next_start - prev_end >= gap_seconds:
            return True
        return any(
            min(b, next_start) - max(a, prev_end) >= gap_seconds
            for a, b in silence
        )

    groups: list[list[TranscriptSegment]] = [[cleaned[0]]]
    for unit in cleaned[1:]:
        if long_break(groups[-1][-1].end, unit.start):
            groups.append([unit])
        else:
            groups[-1].append(unit)

    return [
        LyricStanza(i, g[0].start, max(u.end for u in g), join_timed_text(g))
        for i, g in enumerate(groups)
    ]


def beat_grid(mono: np.ndarray, sr: int) -> tuple[float, list[float], list[float]]:
    """Beats from the full mix (percussion lives in the accompaniment).
    Downbeats = the 4-beat phase with the strongest onsets. Low-confidence
    grids return an empty downbeat list and callers fall back to onsets."""
    import librosa

    if not len(mono) or float(np.max(np.abs(mono))) < 1e-4:
        return 0.0, [], []
    tempo, frames = librosa.beat.beat_track(y=mono, sr=sr)
    beats = [float(t) for t in librosa.frames_to_time(frames, sr=sr)]
    tempo = float(np.atleast_1d(tempo)[0])
    if len(beats) < 8:
        return tempo, beats, []
    onset = librosa.onset.onset_strength(y=mono, sr=sr)
    strengths = onset[np.clip(frames, 0, len(onset) - 1)]
    phase = max(range(4), key=lambda p: float(np.mean(strengths[p::4])))
    return tempo, beats, beats[phase::4]


def audio_repetition_ranges(
    mono: np.ndarray,
    sr: int,
    min_repeat: float = MIN_AUDIO_REPEAT_SECONDS,
    hop_length: int = 2048,
) -> list[tuple[float, float]]:
    """Chroma self-similarity: the strongest lag whose diagonal carries
    sustained mass marks (t, t+lag) as a repeated section pair."""
    import librosa

    if len(mono) < sr * 2 * min_repeat:
        return []
    chroma = librosa.util.normalize(
        librosa.feature.chroma_stft(y=mono, sr=sr, hop_length=hop_length), axis=0)
    frame_dt = hop_length / sr
    n = chroma.shape[1]
    sim = chroma.T @ chroma
    min_lag = int(min_repeat / frame_dt)
    if n <= 2 * min_lag:
        return []
    lags = range(min_lag, n - min_lag)
    best_lag = max(lags, key=lambda lag: float(np.mean(np.diagonal(sim, offset=lag))))
    diag = np.diagonal(sim, offset=best_lag)
    # Scale-free: a uniform perfect repeat keeps its whole diagonal "strong"
    # (mean+std would reject half of it); the 0.6 floor rejects unrelated audio.
    strong = (diag >= 0.85 * float(np.max(diag))) & (diag >= 0.6)
    # Close momentary dips (note transitions, consonants): a repeat is still a
    # repeat across a sub-half-second mismatch.
    gap_frames = max(1, int(0.5 / frame_dt))
    strong = strong.copy()
    weak_run: int | None = None
    for i in range(len(strong)):
        if strong[i]:
            if weak_run is not None and i - weak_run <= gap_frames and weak_run > 0:
                strong[weak_run:i] = True
            weak_run = None
        elif weak_run is None:
            weak_run = i

    ranges: list[tuple[float, float]] = []

    def emit(i0: int, i1: int) -> None:
        if (i1 - i0) * frame_dt >= min_repeat:
            a, b = i0 * frame_dt, i1 * frame_dt
            lag_s = best_lag * frame_dt
            ranges.extend([(round(a, 3), round(b, 3)),
                           (round(a + lag_s, 3), round(b + lag_s, 3))])

    run_start: int | None = None
    for i, flag in enumerate(strong):
        if flag and run_start is None:
            run_start = i
        elif not flag and run_start is not None:
            emit(run_start, i)
            run_start = None
    if run_start is not None:
        emit(run_start, len(strong))
    return sorted(ranges)


def apply_audio_repetitions(
    stanzas: list[LyricStanza],
    ranges: list[tuple[float, float]],
) -> bool:
    changed = False
    for stanza in stanzas:
        length = max(1e-6, stanza.end - stanza.start)
        covered = sum(
            max(0.0, min(b, stanza.end) - max(a, stanza.start)) for a, b in ranges)
        if covered / length >= 0.5:
            stanza.repetition_group = 0
            stanza.is_chorus = True
            changed = True
    return changed


MIN_SILENCE_STANZA_SECONDS = 2.0


def stanzas_from_silence(
    silence: list[tuple[float, float]],
    duration: float,
    min_span: float = MIN_SILENCE_STANZA_SECONDS,
) -> list[LyricStanza]:
    """Transcript-free fallback: the vocal-active spans between silence
    windows are the structural units. Text stays empty — labels come from
    the audio self-similarity path, never invented."""
    edges = [0.0]
    for a, b in sorted(silence):
        edges.extend([a, b])
    edges.append(duration)
    stanzas: list[LyricStanza] = []
    for start, end in zip(edges[::2], edges[1::2]):
        if end - start >= min_span:
            stanzas.append(LyricStanza(len(stanzas), round(start, 3),
                                       round(end, 3), ""))
    return stanzas


def build_structure(
    units: list[TranscriptSegment],
    silence: list[tuple[float, float]],
    envelope: np.ndarray,
    hop: float,
    threshold: float,
    mix_mono: np.ndarray,
    sr: int,
    duration: float | None = None,
) -> SongStructure:
    stanzas = refine_stanza_bounds(
        group_stanzas(units, silence), envelope, hop, threshold)
    if not stanzas and duration:
        # Empty/garbled transcript (instrumental-heavy videos): fall back to
        # envelope-derived structural units; chorus can only come from audio.
        stanzas = stanzas_from_silence(silence, duration)
    chorus_source = "none"
    if any(s.text for s in stanzas) and label_repetitions(stanzas):
        chorus_source = "lyrics"
    elif any(s.text for s in stanzas) and label_repetitions(stanzas, mode="chars"):
        chorus_source = "lyrics-chars"
    elif apply_audio_repetitions(stanzas, audio_repetition_ranges(mix_mono, sr)):
        chorus_source = "audio"
    tempo, beats, downbeats = beat_grid(mix_mono, sr)
    return SongStructure(stanzas, tempo, beats, downbeats, chorus_source)


_NON_LYRIC = re.compile(r"[^\w\sऀ-ॿ]|[_।॥]")


def normalise_lyric(text: str) -> str:
    return re.sub(r"\s+", " ", _NON_LYRIC.sub(" ", text.lower())).strip()


def stanza_similarity(a: str, b: str) -> float:
    words_a = normalise_lyric(a).split()
    words_b = normalise_lyric(b).split()
    if not words_a or not words_b:
        return 0.0
    return SequenceMatcher(None, words_a, words_b).ratio()


def stanza_char_similarity(a: str, b: str) -> float:
    """Character-level ratio survives Whisper transliteration drift
    (येज पाप्पा / येस बाभा / जेस पापा) that defeats word-level matching."""
    chars_a = normalise_lyric(a).replace(" ", "")
    chars_b = normalise_lyric(b).replace(" ", "")
    if not chars_a or not chars_b:
        return 0.0
    return SequenceMatcher(None, chars_a, chars_b).ratio()


CHAR_SIMILARITY_THRESHOLD = 0.40


def label_repetitions(
    stanzas: list[LyricStanza],
    threshold: float | None = None,
    mode: str = "words",
) -> bool:
    if threshold is None:
        threshold = (LYRIC_SIMILARITY_THRESHOLD if mode == "words"
                     else CHAR_SIMILARITY_THRESHOLD)
    similarity = stanza_similarity if mode == "words" else stanza_char_similarity
    n = len(stanzas)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if similarity(stanzas[i].text, stanzas[j].text) >= threshold:
                parent[find(j)] = find(i)

    members: dict[int, list[int]] = {}
    for i in range(n):
        members.setdefault(find(i), []).append(i)

    groups = [ids for ids in members.values() if len(ids) >= 2]
    if not groups:
        return False

    groups.sort(key=lambda ids: (len(ids),
                                 sum(stanzas[i].end - stanzas[i].start for i in ids)))
    for group_id, ids in enumerate(groups):
        for i in ids:
            stanzas[i].repetition_group = group_id
    for i in groups[-1]:  # largest group = the chorus/hook
        stanzas[i].is_chorus = True
    return True


def refine_stanza_bounds(
    stanzas: list[LyricStanza],
    envelope: np.ndarray,
    hop: float,
    threshold: float,
    window: float = BOUND_REFINE_WINDOW,
) -> list[LyricStanza]:
    """Whisper timestamps are fuzzy; the vocal envelope is not. Snap each
    stanza edge to the first/last audible vocal frame near it."""
    if not len(envelope):
        return stanzas
    out: list[LyricStanza] = []
    for stanza in stanzas:
        start, end = stanza.start, stanza.end
        lo = max(0, int((start - window) / hop))
        hi = min(len(envelope), int((start + window) / hop) + 1)
        loud = np.nonzero(envelope[lo:hi] >= threshold)[0]
        if len(loud):
            start = (lo + int(loud[0])) * hop
        lo2 = max(0, int((end - window) / hop))
        hi2 = min(len(envelope), int((end + window) / hop) + 1)
        loud2 = np.nonzero(envelope[lo2:hi2] >= threshold)[0]
        if len(loud2):
            end = (lo2 + int(loud2[-1]) + 1) * hop
        if end <= start:
            start, end = stanza.start, stanza.end
        out.append(LyricStanza(stanza.index, round(start, 3), round(end, 3),
                               stanza.text, stanza.repetition_group, stanza.is_chorus))
    return out
