import numpy as np
import pytest

from app.shorts.cutter.framing import (
    FrameSample,
    TargetPoint,
    assign_scene_ids,
    character_beats,
    fill_gaps_per_scene,
    group_targets,
    scene_cut_times,
    solve_camera_path,
)


def sample(t, boxes=(), labels=(), ids=(), scene=0):
    return FrameSample(t, list(boxes), list(labels), list(ids), scene)


def test_scene_cut_times_thresholds_and_min_gap():
    times = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    dists = [0.0, 0.1, 0.9, 0.8, 0.1, 0.9]
    # 1.0 crosses threshold; 1.5 is within min_gap of 1.0 so skipped; 2.5 is a new cut
    assert scene_cut_times(times, dists, threshold=0.42, min_gap=1.0) == [1.0, 2.5]


def test_assign_scene_ids():
    times = [0.0, 0.5, 1.0, 1.5, 2.0]
    assert assign_scene_ids(times, [1.0]) == [0, 0, 1, 1, 1]


def test_group_targets_frames_group_when_it_fits():
    # Two characters spanning 300..700 = 400px span, crop 500 -> fits (400 <= 0.92*500)
    s = sample(0.0, boxes=[(300, 0, 450, 100), (550, 0, 700, 100)],
               labels=["person", "person"], ids=[1, 2])
    [t] = group_targets([s], crop_width=500, frame_width=1920)
    assert t.mode == "group"
    assert t.x == pytest.approx(500.0)


def test_group_targets_falls_back_to_primary_and_sticks():
    # Span 1400px > 0.92*500 -> primary = bigger box (person id 1); stays sticky next sample
    a = sample(0.0, boxes=[(100, 0, 500, 400), (1400, 0, 1500, 80)],
               labels=["person", "person"], ids=[1, 2])
    b = sample(0.25, boxes=[(120, 0, 520, 400), (1400, 0, 1510, 90)],
               labels=["person", "person"], ids=[1, 2])
    t1, t2 = group_targets([a, b], crop_width=500, frame_width=1920)
    assert t1.mode == "primary" and t1.primary_key == "person#1"
    assert t1.x == pytest.approx(300.0)
    assert t2.primary_key == "person#1"


def test_fill_gaps_interpolates_within_scene_only():
    targets = [
        TargetPoint(0.0, 100.0, "group", None, "person"),
        TargetPoint(1.0, None, "none", None, ""),
        TargetPoint(2.0, 300.0, "group", None, "person"),
        TargetPoint(3.0, None, "none", None, ""),  # scene 1, no detections at all
    ]
    filled = fill_gaps_per_scene(targets, [0, 0, 0, 1], frame_width=1920)
    assert filled == pytest.approx([100.0, 200.0, 300.0, 960.0])


def test_camera_zero_lag_on_constant_target():
    times = [i / 6 for i in range(60)]
    xs = [800.0] * 60
    path = solve_camera_path(times, xs, [0] * 60, crop_width=500, max_x=1400)
    # camera left edge should sit at target - crop/2 = 550 for every point
    assert all(abs(x - 550) <= 2 for _, x in path)


def test_camera_snaps_at_scene_boundary():
    times = [i / 6 for i in range(120)]
    xs = [300.0] * 60 + [1600.0] * 60
    ids = [0] * 60 + [1] * 60
    path = solve_camera_path(times, xs, ids, crop_width=500, max_x=1420)
    # last sample of scene 0 near 300-250=50; first of scene 1 near 1350: full jump
    assert abs(path[59][1] - 50) <= 2
    assert abs(path[60][1] - 1350) <= 2


def test_camera_speed_cap_within_scene():
    times = [i / 6 for i in range(120)]
    xs = [0.0] * 30 + [1900.0] * 90  # step target inside one scene
    path = solve_camera_path(times, xs, [0] * 120, crop_width=500, max_x=1420,
                             max_speed_frac=0.12)
    max_move = 500 * 0.12 / 6 + 2  # per-sample cap + rounding slack
    for i in range(1, len(path)):
        assert abs(path[i][1] - path[i - 1][1]) <= max_move


def test_camera_locked_profile_holds_scene_median():
    times = [i / 6 for i in range(60)]
    xs = list(np.linspace(200, 900, 60))
    path = solve_camera_path(times, xs, [0] * 60, crop_width=500, max_x=1400,
                             max_speed_frac=0.0)
    assert len({x for _, x in path}) == 1


def test_camera_path_x_never_exceeds_odd_max_x():
    # Regression: even() rounds 99 -> 100, pushing x past max_x=99.
    # Uses 2 samples so scene duration < min_scene_seconds → median path returns
    # exactly 99.0, and even(99.0) = 100 before the fix.
    # After the fix every returned x must satisfy 0 <= x <= max_x.
    times = [0.0, 1.0]  # 2 samples: duration(1s) < min_scene_seconds(1.5s)
    # Target far to the right so wanted clamps to max_x=99 in every frame
    xs = [9999.0, 9999.0]
    path = solve_camera_path(times, xs, [0, 0], crop_width=500, max_x=99)
    for _t, x in path:
        assert 0 <= x <= 99, f"x={x} exceeds bounds [0, 99]"


def test_character_beats_requires_stability_and_gap():
    targets = []
    # subject A for 3s, subject B stable from t=3
    for i in range(18):
        targets.append(TargetPoint(i / 6, 100.0, "primary", "person#1", "person"))
    for i in range(18, 36):
        targets.append(TargetPoint(i / 6, 900.0, "primary", "person#2", "person"))
    beats = character_beats(targets)
    assert len(beats) == 1
    assert beats[0][0] == pytest.approx(3.0)
    # one flickering sample must NOT create a beat
    flicker = targets[:18] + [TargetPoint(3.0, 900.0, "primary", "person#2", "person")] + [
        TargetPoint(3.0 + (i + 1) / 6, 100.0, "primary", "person#1", "person") for i in range(18)
    ]
    assert character_beats(flicker) == []


def test_split_on_target_jumps_sustained_jump_snaps_camera():
    from app.shorts.cutter.framing import split_on_target_jumps

    times = [i / 6 for i in range(60)]
    xs = [300.0] * 30 + [1500.0] * 30  # subject relocates and stays
    ids = [0] * 60
    new_ids = split_on_target_jumps(times, xs, ids, crop_width=500)
    assert new_ids[29] != new_ids[30], "sustained jump must split the scene"
    path = solve_camera_path(times, xs, new_ids, crop_width=500, max_x=1400)
    assert abs(path[29][1] - 50) <= 2 and abs(path[30][1] - 1250) <= 2


def test_split_on_target_jumps_ignores_one_sample_spike():
    from app.shorts.cutter.framing import split_on_target_jumps

    times = [i / 6 for i in range(60)]
    xs = [300.0] * 30 + [1500.0] + [300.0] * 29  # detector spike, returns
    new_ids = split_on_target_jumps(times, xs, [0] * 60, crop_width=500)
    assert len(set(new_ids)) == 1, "a one-sample spike must not split"


def test_split_on_target_jumps_ignores_fast_continuous_pan():
    from app.shorts.cutter.framing import split_on_target_jumps

    times = [i / 6 for i in range(60)]
    xs = list(np.linspace(0.0, 1800.0, 60))  # steep ramp, never settles
    new_ids = split_on_target_jumps(times, xs, [0] * 60, crop_width=500)
    assert len(set(new_ids)) == 1, "continuous motion must not split"


def test_split_on_target_jumps_preserves_real_scene_boundaries():
    from app.shorts.cutter.framing import split_on_target_jumps

    times = [i / 6 for i in range(40)]
    xs = [100.0] * 40
    ids = [0] * 20 + [1] * 20
    new_ids = split_on_target_jumps(times, xs, ids, crop_width=500)
    assert new_ids[19] != new_ids[20]
