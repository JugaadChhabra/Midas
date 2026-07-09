"""Candidate segments from song structure; scoring; greedy selection. Pure."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.shorts.cutter.cutplan import Stanza, finesse_boundaries, pad_clip
from app.shorts.cutter.structure import LyricStanza, SongStructure

MIN_HIGHLIGHT_SECONDS = 20.0
MAX_HIGHLIGHT_SECONDS = 45.0
MIN_CLIPS = 4
MAX_CLIPS = 8
SCORE_FLOOR = 0.45
PER_GROUP_CAP = 2
DEFAULT_WEIGHTS = {
    "chorus": 0.30, "onset": 0.20, "resolution": 0.20,
    "framing": 0.15, "motion_start": 0.10, "scene_align": 0.05,
}


PAD_MIN_SECONDS = 15.0


@dataclass
class Candidate:
    start: float
    end: float
    stanza_indices: list[int]
    is_chorus: bool
    components: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    below_floor: bool = False
    needs_padding: bool = False


def generate_candidates(
    stanzas: list[LyricStanza],
    min_seconds: float = MIN_HIGHLIGHT_SECONDS,
    max_seconds: float = MAX_HIGHLIGHT_SECONDS,
) -> list[Candidate]:
    def make(span: list[LyricStanza]) -> Candidate | None:
        start, end = span[0].start, span[-1].end
        length = end - start
        if not (PAD_MIN_SECONDS <= length <= max_seconds):
            return None
        # just-under-minimum spans ship padded with instrumental lead-in/out
        return Candidate(start, end, [s.index for s in span],
                         any(s.is_chorus for s in span),
                         needs_padding=length < min_seconds)

    seen: set[tuple[float, float]] = set()
    output: list[Candidate] = []

    def add(span: list[LyricStanza]) -> None:
        candidate = make(span)
        if candidate and (candidate.start, candidate.end) not in seen:
            seen.add((candidate.start, candidate.end))
            output.append(candidate)

    for i, stanza in enumerate(stanzas):
        # runs of consecutive stanzas: fragmented transcripts split verses
        # into many tiny stanzas, and only a run reaches the length band
        span: list[LyricStanza] = []
        for j in range(i, len(stanzas)):
            span.append(stanzas[j])
            if span[-1].end - span[0].start > max_seconds:
                break
            add(span[:])
        # short chorus: pair with the preceding stanza so the hook still ships
        if stanza.is_chorus and stanza.end - stanza.start < min_seconds and i > 0:
            add([stanzas[i - 1], stanza])
    return output


def _near(value: float, points: list[float], tolerance: float) -> bool:
    return any(abs(value - p) <= tolerance for p in points)


def _in_silence(silence: list[tuple[float, float]], t: float, slack: float = 0.1) -> bool:
    return any(a - slack <= t <= b + slack for a, b in silence)


def _framing_fraction(candidate, sample_times, sample_targets, camera_xs, crop_width):
    indices = [i for i, t in enumerate(sample_times)
               if candidate.start <= t <= candidate.end]
    if not indices:
        return 0.5  # neutral: no data is not a failure
    band = crop_width * 0.125
    ok = sum(1 for i in indices
             if abs(sample_targets[i] - (camera_xs[i] + crop_width / 2)) <= band)
    return ok / len(indices)


def _motion_at_start(candidate, sample_times, sample_targets, crop_width,
                     window: float = 1.5) -> float:
    indices = [i for i, t in enumerate(sample_times)
               if candidate.start <= t <= candidate.start + window]
    if len(indices) < 2:
        return 0.5
    moves = [abs(sample_targets[j] - sample_targets[i])
             for i, j in zip(indices, indices[1:])]
    return float(min(1.0, np.mean(moves) / (0.02 * crop_width)))


def score_candidates(
    candidates: list[Candidate],
    stanzas: list[LyricStanza],
    silence: list[tuple[float, float]],
    downbeats: list[float],
    scene_times: list[float],
    sample_times: list[float] | None,
    sample_targets: list[float] | None,
    camera_xs: list[int] | None,
    crop_width: int | None,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
) -> None:
    have_framing = bool(sample_times and sample_targets and camera_xs and crop_width)
    for candidate in candidates:
        c: dict[str, float] = {}
        c["chorus"] = 1.0 if candidate.is_chorus else 0.0
        c["onset"] = (0.6 * (1.0 if _in_silence(silence, candidate.start) or
                             candidate.start <= 0.1 else 0.0)
                      + 0.4 * (1.0 if _near(candidate.start, downbeats, 0.35) else 0.0))
        c["resolution"] = (0.6 * (1.0 if _in_silence(silence, candidate.end) else 0.0)
                           + 0.4 * (1.0 if _near(candidate.end, downbeats, 0.35) else 0.0))
        # quantised to 0.05 steps: YOLO float jitter must not reshuffle picks
        c["framing"] = (round(_framing_fraction(candidate, sample_times,
                                                sample_targets, camera_xs,
                                                crop_width) * 20) / 20
                        if have_framing else 0.5)
        c["motion_start"] = (round(_motion_at_start(candidate, sample_times,
                                                    sample_targets,
                                                    crop_width) * 20) / 20
                             if have_framing else 0.5)
        c["scene_align"] = 1.0 if (_near(candidate.start, scene_times, 0.5)
                                   or _near(candidate.end, scene_times, 0.5)) else 0.0
        candidate.components = c
        candidate.score = round(sum(weights[k] * c[k] for k in weights), 4)


DIVERSITY_WEIGHT = 0.35


def select_clips(
    candidates: list[Candidate],
    stanzas: list[LyricStanza],
    min_count: int = MIN_CLIPS,
    max_count: int = MAX_CLIPS,
    floor: float = SCORE_FLOOR,
    per_group_cap: int = PER_GROUP_CAP,
    diversity_weight: float = DIVERSITY_WEIGHT,
) -> list[Candidate]:
    from app.shorts.cutter.structure import stanza_char_similarity, stanza_similarity

    groups = {s.index: s.repetition_group for s in stanzas}
    texts = {s.index: s.text for s in stanzas}

    def overlaps(candidate: Candidate, chosen: list[Candidate]) -> bool:
        return any(candidate.start < c.end and candidate.end > c.start
                   for c in chosen)

    def group_of(candidate: Candidate) -> int | None:
        found = [groups[i] for i in candidate.stanza_indices
                 if groups.get(i) is not None]
        return found[0] if found else None

    def text_of(candidate: Candidate) -> str:
        return " ".join(texts.get(i, "") for i in candidate.stanza_indices).strip()

    def lyric_overlap(candidate: Candidate, chosen: list[Candidate]) -> float:
        text = text_of(candidate)
        if not text or not chosen:
            return 0.0
        return max((max(stanza_similarity(text, text_of(c)),
                        stanza_char_similarity(text, text_of(c)))
                    for c in chosen if text_of(c)), default=0.0)

    picked: list[Candidate] = []
    group_counts: dict[int, int] = {}

    def try_pick(pool: list[Candidate], allow_below_floor: bool,
                 limit: int) -> None:
        remaining = list(pool)
        while remaining and len(picked) < limit:
            # MMR-style: quality minus lyric similarity to what's already in —
            # a repeat of the same hook must beat a distinct verse on merit
            def effective(c: Candidate) -> float:
                return c.score - diversity_weight * lyric_overlap(c, picked)

            candidate = max(remaining, key=effective)
            remaining.remove(candidate)
            if not allow_below_floor and candidate.score < floor:
                continue
            if allow_below_floor and candidate.score >= floor:
                continue
            if overlaps(candidate, picked):
                continue
            group = group_of(candidate)
            if group is not None and group_counts.get(group, 0) >= per_group_cap:
                continue
            candidate.below_floor = candidate.score < floor
            picked.append(candidate)
            if group is not None:
                group_counts[group] = group_counts.get(group, 0) + 1

    try_pick(candidates, allow_below_floor=False, limit=max_count)
    if len(picked) < min_count:
        # fill only up to the minimum — honest flags, user decides
        try_pick(candidates, allow_below_floor=True, limit=min_count)
    return sorted(picked, key=lambda c: c.start)


def plan_highlights(
    song: SongStructure,
    silence: list[tuple[float, float]],
    scene_times: list[float],
    sample_times: list[float] | None,
    sample_targets: list[float] | None,
    camera_xs: list[int] | None,
    crop_width: int | None,
    duration: float,
) -> tuple[list[Stanza], list[dict]]:
    candidates = generate_candidates(song.stanzas)
    if not candidates:
        return [], []
    score_candidates(candidates, song.stanzas, silence, song.downbeats,
                     scene_times, sample_times, sample_targets,
                     camera_xs, crop_width)
    picked = select_clips(candidates, song.stanzas)
    picked_keys = {(c.start, c.end) for c in picked}

    text_by_index = {s.index: s.text for s in song.stanzas}
    clips: list[Stanza] = []
    for index, candidate in enumerate(picked):
        start, end, start_kind, end_kind = finesse_boundaries(
            candidate.start, candidate.end, silence, song.downbeats, duration)
        if end - start < MIN_HIGHLIGHT_SECONDS:
            start, end = pad_clip(start, end, silence,
                                  MIN_HIGHLIGHT_SECONDS, duration)
        # lead-in/padding may reach into a neighbouring pick — clamp to it
        if clips and start < clips[-1].end:
            start = clips[-1].end
        if index + 1 < len(picked):
            end = min(end, picked[index + 1].start)
        text = " ".join(text_by_index[i] for i in candidate.stanza_indices).strip()
        clips.append(Stanza(start, end, text or f"Rhyme Short {len(clips) + 1}",
                            f"{start_kind}+{end_kind}"))

    diagnostics = [{
        "start": c.start, "end": c.end, "stanza_indices": c.stanza_indices,
        "is_chorus": c.is_chorus, "score": c.score, "components": c.components,
        "selected": (c.start, c.end) in picked_keys, "below_floor": c.below_floor,
    } for c in sorted(candidates, key=lambda c: -c.score)]
    return clips, diagnostics
