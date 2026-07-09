"""Pure framing logic: scenes, group targets, zero-lag camera path, character beats."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

PREFERRED_LABELS = {
    "person": 1.9, "cat": 1.6, "dog": 1.6, "bird": 1.4,
    "horse": 1.4, "sheep": 1.4, "cow": 1.4, "elephant": 1.5,
    "bear": 1.5, "zebra": 1.4, "giraffe": 1.4,
}


@dataclass
class FrameSample:
    time: float
    boxes: list[tuple[float, float, float, float]]
    labels: list[str]
    track_ids: list[int | None]
    scene_index: int


@dataclass
class TargetPoint:
    time: float
    x: float | None
    mode: str  # "group" | "primary" | "none"
    primary_key: str | None
    label: str


def scene_cut_times(
    times: list[float],
    distances: list[float],
    threshold: float = 0.42,
    min_gap: float = 1.0,
) -> list[float]:
    cuts: list[float] = []
    for time, distance in zip(times, distances):
        if distance >= threshold and (not cuts or time - cuts[-1] >= min_gap):
            cuts.append(time)
    return cuts


def assign_scene_ids(times: list[float], cut_times: list[float]) -> list[int]:
    ids: list[int] = []
    scene = 0
    remaining = list(cut_times)
    for time in times:
        while remaining and time >= remaining[0]:
            scene += 1
            remaining.pop(0)
        ids.append(scene)
    return ids


def _box_key(label: str, track_id: int | None, index: int) -> str:
    return f"{label}#{track_id}" if track_id is not None else f"{label}:{index}"


def group_targets(
    samples: list[FrameSample],
    crop_width: int,
    frame_width: int,
    fit_ratio: float = 0.92,
) -> list[TargetPoint]:
    sticky: dict[int, str] = {}  # scene index -> primary key
    output: list[TargetPoint] = []

    for sample in samples:
        if not sample.boxes:
            output.append(TargetPoint(sample.time, None, "none", None, ""))
            continue

        left = min(box[0] for box in sample.boxes)
        right = max(box[2] for box in sample.boxes)
        if right - left <= fit_ratio * crop_width:
            output.append(TargetPoint(sample.time, (left + right) / 2, "group", None,
                                      sample.labels[0]))
            continue

        keys = [
            _box_key(label, track_id, index)
            for index, (label, track_id) in enumerate(zip(sample.labels, sample.track_ids))
        ]
        chosen_index: int | None = None
        wanted = sticky.get(sample.scene_index)
        if wanted in keys:
            chosen_index = keys.index(wanted)
        else:
            best_score = -1.0
            for index, (box, label) in enumerate(zip(sample.boxes, sample.labels)):
                area = max(0.0, (box[2] - box[0]) * (box[3] - box[1]))
                score = area * PREFERRED_LABELS.get(label, 1.0)
                if score > best_score:
                    best_score, chosen_index = score, index
            sticky[sample.scene_index] = keys[chosen_index]

        box = sample.boxes[chosen_index]
        output.append(TargetPoint(sample.time, (box[0] + box[2]) / 2, "primary",
                                  keys[chosen_index], sample.labels[chosen_index]))
    return output


def fill_gaps_per_scene(
    targets: list[TargetPoint],
    scene_ids: list[int],
    frame_width: float,
) -> list[float]:
    filled = [t.x for t in targets]
    for scene in sorted(set(scene_ids)):
        indices = [i for i, s in enumerate(scene_ids) if s == scene]
        known = [i for i in indices if filled[i] is not None]
        if not known:
            for i in indices:
                filled[i] = frame_width / 2
            continue
        for i in indices:
            if filled[i] is not None:
                continue
            before = [k for k in known if k < i]
            after = [k for k in known if k > i]
            if before and after:
                a, b = before[-1], after[0]
                t = (targets[i].time - targets[a].time) / max(
                    1e-6, targets[b].time - targets[a].time)
                filled[i] = filled[a] + (filled[b] - filled[a]) * t
            else:
                filled[i] = filled[before[-1]] if before else filled[after[0]]
    return [float(x) for x in filled]


def apply_colour_fallback(
    targets: list[TargetPoint],
    colour_xs: list[float | None],
    frame_width: float,
) -> list[TargetPoint]:
    """Fill detector-blind samples with the dominant-colour-blob subject (as a
    fraction of frame width) before interpolation. Detected samples never change."""
    output: list[TargetPoint] = []
    for target, colour_x in zip(targets, colour_xs):
        if target.mode == "none" and colour_x is not None:
            output.append(TargetPoint(target.time, colour_x * frame_width,
                                      "colour", None, "colour-subject"))
        else:
            output.append(target)
    return output


def split_on_target_jumps(
    times: list[float],
    targets_x: list[float],
    scene_ids: list[int],
    crop_width: int,
    jump_frac: float = 0.35,
    confirm_seconds: float = 0.75,
    settle_frac: float = 0.20,
) -> list[int]:
    """
    Treat a sustained subject relocation as a virtual scene cut so the camera
    snaps instead of panning across the frame. A jump only qualifies when the
    target settles at the new position (median over the confirm window): a
    one-sample detector spike returns immediately, and a fast continuous pan
    keeps moving — neither settles, so neither splits.
    """
    n = len(targets_x)
    if n < 2:
        return list(scene_ids)

    cut = [False] * n
    for i in range(1, n):
        if scene_ids[i] != scene_ids[i - 1]:
            cut[i] = True
            continue
        if abs(targets_x[i] - targets_x[i - 1]) < crop_width * jump_frac:
            continue
        after = [
            targets_x[j]
            for j in range(i, n)
            if scene_ids[j] == scene_ids[i] and times[j] - times[i] <= confirm_seconds
        ]
        before = [
            targets_x[j]
            for j in range(i - 1, -1, -1)
            if scene_ids[j] == scene_ids[i] and times[i] - times[j] <= confirm_seconds
        ]
        if max(after) - min(after) > crop_width * settle_frac:
            continue  # still moving — a pan, not a relocation
        if abs(float(np.median(after)) - float(np.median(before))) >= crop_width * jump_frac:
            cut[i] = True

    new_ids: list[int] = []
    current = 0
    for i in range(n):
        if i and cut[i]:
            current += 1
        new_ids.append(current)
    return new_ids


def _gaussian_smooth(values: np.ndarray, times: np.ndarray, smooth_seconds: float) -> np.ndarray:
    if len(values) < 3 or smooth_seconds <= 0:
        return values.copy()
    dt = float(np.median(np.diff(times))) or 1.0 / 6
    sigma = max(1e-6, smooth_seconds / dt / 2.0)
    radius = int(3 * sigma) + 1
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(values, radius, mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _clamp_speed(values: np.ndarray, times: np.ndarray, max_move_per_second: float) -> np.ndarray:
    out = values.copy()
    for i in range(1, len(out)):
        cap = max_move_per_second * max(1e-3, times[i] - times[i - 1])
        out[i] = out[i - 1] + np.clip(out[i] - out[i - 1], -cap, cap)
    for i in range(len(out) - 2, -1, -1):
        cap = max_move_per_second * max(1e-3, times[i + 1] - times[i])
        out[i] = out[i + 1] + np.clip(out[i] - out[i + 1], -cap, cap)
    return out


def solve_camera_path(
    times: list[float],
    targets_x: list[float],
    scene_ids: list[int],
    crop_width: int,
    max_x: int,
    max_speed_frac: float = 0.12,
    smooth_seconds: float = 0.6,
    min_scene_seconds: float = 1.5,
) -> list[tuple[float, int]]:
    """Per-scene zero-phase camera path; snaps freely at scene boundaries."""
    result_x = np.zeros(len(times))
    times_arr = np.asarray(times, dtype=float)
    wanted = np.clip(np.asarray(targets_x, dtype=float) - crop_width / 2, 0, max_x)

    for scene in sorted(set(scene_ids)):
        idx = np.asarray([i for i, s in enumerate(scene_ids) if s == scene])
        scene_times = times_arr[idx]
        scene_wanted = wanted[idx]
        duration = float(scene_times[-1] - scene_times[0]) if len(idx) > 1 else 0.0
        if max_speed_frac <= 0 or duration < min_scene_seconds:
            result_x[idx] = float(np.median(scene_wanted))
            continue
        smoothed = _gaussian_smooth(scene_wanted, scene_times, smooth_seconds)
        limited = _clamp_speed(smoothed, scene_times, crop_width * max_speed_frac)
        result_x[idx] = np.clip(limited, 0, max_x)

    def even(value: float) -> int:
        return max(0, int(value // 2) * 2)

    return [(float(t), min(max_x, even(x))) for t, x in zip(times, result_x)]


def character_beats(
    targets: list[TargetPoint],
    stability_seconds: float = 1.25,
    min_gap_seconds: float = 2.5,
) -> list[tuple[float, str]]:
    """A beat fires when the framed subject identity changes and stays changed."""
    beats: list[tuple[float, str]] = []
    active: str | None = None
    pending: str | None = None
    pending_label = ""
    pending_start: float | None = None

    for target in targets:
        if target.mode not in {"group", "primary"}:
            # 'none' has no identity; 'colour' blobs have no stable identity either.
            continue
        key = target.primary_key or f"group:{target.label}"
        if active is None:
            active = key
            continue
        if key == active:
            pending = None
            pending_start = None
            continue
        if pending != key:
            pending = key
            pending_label = target.label
            pending_start = target.time
            continue
        if pending_start is not None and target.time - pending_start >= stability_seconds:
            if not beats or pending_start - beats[-1][0] >= min_gap_seconds:
                beats.append((round(pending_start, 3), pending_label or "subject"))
            active = pending
            pending = None
            pending_start = None
    return beats


def _is_continuous_travel(wanted: np.ndarray, crop_width: int,
                          travel_frac: float = 0.8,
                          monotone_frac: float = 0.7,
                          moving_frac: float = 0.4) -> bool:
    if len(wanted) < 3:
        return False
    span = float(np.max(wanted) - np.min(wanted))
    if span < travel_frac * crop_width:
        return False
    steps = np.diff(wanted)
    moving = steps[np.abs(steps) > 1e-6]
    if not len(moving):
        return False
    # A walk moves in most samples; a relocation moves in one big step —
    # that must recompose-snap, not engage the slow follow solver.
    if len(moving) < moving_frac * len(steps):
        return False
    dominant = max(float(np.mean(moving > 0)), float(np.mean(moving < 0)))
    return dominant >= monotone_frac


def _bimodal_dominant_position(wanted: np.ndarray, crop_width: int,
                               min_cluster_frac: float = 0.25,
                               max_cluster_std_frac: float = 0.15,
                               min_separation_frac: float = 0.6) -> float | None:
    """When the target flip-flops between two STATIONARY positions (character
    on one side, object on the other), return the median of the cluster the
    target spends more time at; None when the pattern isn't two tight modes."""
    if len(wanted) < 6:
        return None
    ordered = np.sort(wanted)
    gaps = np.diff(ordered)
    split = int(np.argmax(gaps))
    if gaps[split] < min_separation_frac * crop_width:
        return None
    low, high = ordered[:split + 1], ordered[split + 1:]
    n = len(ordered)
    if min(len(low), len(high)) < min_cluster_frac * n:
        return None
    if max(float(np.std(low)), float(np.std(high))) > max_cluster_std_frac * crop_width:
        return None
    # A single relocation (one switch) must recompose, not lock: only a real
    # flip-flop — the target trading between the two positions repeatedly —
    # justifies committing to one side for the whole scene.
    boundary = (ordered[split] + ordered[split + 1]) / 2
    sides = wanted > boundary
    switches = int(np.sum(sides[1:] != sides[:-1]))
    if switches < 3:
        return None
    dominant = low if len(low) >= len(high) else high
    return float(np.median(dominant))


def solve_camera_path_hold(
    times: list[float],
    targets_x: list[float],
    scene_ids: list[int],
    crop_width: int,
    max_x: int,
    max_speed_frac: float = 0.20,
    deadband_frac: float = 0.40,
    excursion_seconds: float = 0.3,
    compose_seconds: float = 1.5,
    lead_offsets: list[float] | None = None,
    recompose_speed_frac: float = 1.2,
    volatile_std_frac: float = 0.15,
    follow_speed_frac: float = 0.35,
) -> list[tuple[float, int]]:
    """One composed, locked position per scene. Re-compose (a quick whip)
    only when the subject leaves the deadband and stays out. Two scene kinds
    route to the smooth-follow path instead: continuous travel (a walk), and
    volatile scenes (multiple subjects trading focus, target jitters widely) —
    on those, offline sweeps show following beats any locked hold."""
    times_arr = np.asarray(times, dtype=float)
    desired = np.asarray(targets_x, dtype=float)
    if lead_offsets is not None:
        desired = desired + np.asarray(lead_offsets, dtype=float)
    wanted = np.clip(desired - crop_width / 2, 0, max_x)
    result = np.zeros(len(times_arr))

    for scene in sorted(set(scene_ids)):
        idx = np.asarray([i for i, s in enumerate(scene_ids) if s == scene])
        scene_times = times_arr[idx]
        scene_wanted = wanted[idx]

        steps = np.abs(np.diff(scene_wanted)) if len(scene_wanted) > 1 else np.zeros(0)
        moving_frac = (float(np.mean(steps > 0.005 * crop_width))
                       if len(steps) else 0.0)
        volatile = (float(np.std(scene_wanted)) > volatile_std_frac * crop_width
                    and moving_frac >= 0.4)

        wide_spread = float(np.std(scene_wanted)) > volatile_std_frac * crop_width
        dominant = (_bimodal_dominant_position(scene_wanted, crop_width)
                    if wide_spread else None)
        if dominant is not None:
            # Two stationary subjects wider than the crop (character + object):
            # following the average parks the camera between them and cuts
            # BOTH in half. Commit to the dominant one and hold.
            result[idx] = float(np.clip(dominant, 0, max_x))
            continue
        if volatile or _is_continuous_travel(scene_wanted, crop_width):
            smoothed = _gaussian_smooth(scene_wanted, scene_times, 0.6)
            result[idx] = np.clip(
                _clamp_speed(smoothed, scene_times,
                             crop_width * max(max_speed_frac, follow_speed_frac)),
                0, max_x)
            continue

        def composed_at(k: int) -> float:
            window = scene_wanted[(scene_times >= scene_times[k])
                                  & (scene_times <= scene_times[k] + compose_seconds)]
            return float(np.median(window)) if len(window) else float(scene_wanted[k])

        hold = composed_at(0)
        positions = np.empty(len(idx))
        out_since: float | None = None
        for k in range(len(idx)):
            centre = hold + crop_width / 2
            if abs(desired[idx[k]] - centre) <= (deadband_frac / 2) * crop_width:
                out_since = None
            elif out_since is None:
                out_since = scene_times[k]
            elif scene_times[k] - out_since >= excursion_seconds:
                hold = composed_at(k)  # one damped re-compose, then lock again
                out_since = None
            positions[k] = hold
        # Re-compose transitions are quick whips (snap beats pan — the July
        # jump-snap finding), NOT the follow-profile crawl: a speed-clamped
        # cross-frame catch-up takes seconds and leaves subjects half-cropped.
        if recompose_speed_frac > 0:
            positions = _clamp_speed(positions, scene_times,
                                     crop_width * recompose_speed_frac)
        result[idx] = np.clip(positions, 0, max_x)

    def even(value: float) -> int:
        return max(0, int(value // 2) * 2)

    return [(float(t), min(max_x, even(x))) for t, x in zip(times, result)]


def lead_room_offsets(
    times: list[float],
    targets_x: list[float],
    scene_ids: list[int],
    crop_width: int,
    lead_frac: float = 0.10,
    min_speed_frac: float = 0.05,
) -> list[float]:
    """Lead room: offset the composed centre ahead of the subject's direction
    of travel. Ambiguous (static/front-facing) scenes get 0 — never guess."""
    times_arr = np.asarray(times, dtype=float)
    targets_arr = np.asarray(targets_x, dtype=float)
    offsets = np.zeros(len(times_arr))
    for scene in sorted(set(scene_ids)):
        idx = np.asarray([i for i, s in enumerate(scene_ids) if s == scene])
        if len(idx) < 3:
            continue
        span = float(times_arr[idx][-1] - times_arr[idx][0])
        if span <= 0:
            continue
        velocity = float(targets_arr[idx][-1] - targets_arr[idx][0]) / span
        if abs(velocity) >= min_speed_frac * crop_width:
            offsets[idx] = np.sign(velocity) * lead_frac * crop_width
    return [float(o) for o in offsets]
