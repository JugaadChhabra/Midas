"""Trust layer: grade each clip from data already computed. No re-decoding."""
from __future__ import annotations

import numpy as np

from app.shorts.cutter.cutplan import Stanza

FRAMING_BAND_FRAC = 0.125   # middle 25% of the frame
FRAMING_PASS_FRACTION = 0.85
CUT_SLACK_SECONDS = 0.10
CUT_LOUDNESS_TOLERANCE = 1.5


def _quiet_at(vocal: dict, time: float) -> bool:
    envelope, hop, threshold = vocal["envelope"], vocal["hop"], vocal["threshold"]
    lo = max(0, int((time - CUT_SLACK_SECONDS) / hop))
    hi = min(len(envelope), max(lo + 1, int((time + CUT_SLACK_SECONDS) / hop) + 1))
    if lo >= len(envelope):
        return True  # boundary at/after end of audio
    return float(np.min(envelope[lo:hi])) < threshold * CUT_LOUDNESS_TOLERANCE


def _framing_score(
    stanza: Stanza,
    times: list[float],
    targets: list[float],
    camera_xs: list[int],
    crop_width: int,
    offsets: list[float] | None = None,
) -> float | None:
    indices = [i for i, t in enumerate(times) if stanza.start <= t <= stanza.end]
    if not indices:
        return None
    band = crop_width * FRAMING_BAND_FRAC
    ok = sum(
        1 for i in indices
        if abs(targets[i] - (camera_xs[i] + crop_width / 2
                             - (offsets[i] if offsets else 0.0))) <= band
    )
    return ok / len(indices)


def grade_clips(
    stanzas: list[Stanza],
    vocal: dict | None,
    sample_times: list[float] | None,
    sample_targets: list[float] | None,
    camera_xs: list[int] | None,
    crop_width: int | None,
    intended_offsets: list[float] | None = None,
    selection_info: list[dict] | None = None,
) -> list[dict]:
    grades: list[dict] = []
    have_framing = bool(sample_times and sample_targets and camera_xs and crop_width)

    for index, stanza in enumerate(stanzas):
        reasons: list[str] = []
        cut_start_ok: bool | None = None
        cut_end_ok: bool | None = None
        framing: float | None = None

        if vocal is not None:
            cut_start_ok = index == 0 or _quiet_at(vocal, stanza.start)
            cut_end_ok = index == len(stanzas) - 1 or _quiet_at(vocal, stanza.end)
            if not cut_start_ok:
                reasons.append(f"vocals audible at clip start ({stanza.start:.1f}s)")
            if not cut_end_ok:
                reasons.append(f"vocals audible at clip end ({stanza.end:.1f}s)")
        else:
            reasons.append("cut safety unverified (no vocal analysis)")

        if stanza.boundary == "forced":
            reasons.append("forced cut: no vocal silence in legal range")
        elif stanza.boundary == "short-pause":
            reasons.append("cut in a short vocal pause (<0.9s) — no full line break was available")

        if have_framing:
            framing = _framing_score(stanza, sample_times, sample_targets,
                                     camera_xs, crop_width, intended_offsets)
            if framing is not None and framing < FRAMING_PASS_FRACTION:
                reasons.append(f"subject centered only {framing:.0%} of the time")
        else:
            reasons.append("framing unverified (centre crop or no samples)")

        grade = {
            "verdict": "PASS" if not reasons else "CHECK",
            "framing_score": framing,
            "cut_start_ok": cut_start_ok,
            "cut_end_ok": cut_end_ok,
            "boundary": stanza.boundary,
            "reasons": reasons,
        }
        if selection_info is not None and index < len(selection_info):
            grade["selection"] = selection_info[index]
        grades.append(grade)
    return grades
