import numpy as np

from app.shorts.cutter.framing import solve_camera_path_hold


def test_holds_locked_through_subject_wiggle():
    times = [i * 0.2 for i in range(50)]
    targets = [500 + 20 * np.sin(i) for i in range(50)]  # dance wiggle
    path = solve_camera_path_hold(times, targets, [0] * 50, 400, 1000)
    xs = {x for _t, x in path}
    assert len(xs) == 1  # one locked position, zero drift


def test_recomposes_after_sustained_excursion():
    times = [i * 0.1 for i in range(100)]
    targets = [300.0] * 40 + [720.0] * 60  # subject relocates and stays
    path = solve_camera_path_hold(times, targets, [0] * 100, 400, 1000)
    assert path[10][1] == path[0][1]                  # held before
    assert abs(path[-1][1] - (720 - 200)) <= 20        # re-composed after
    assert path[-1][1] != path[0][1]


def test_snaps_between_scenes():
    times = [i * 0.2 for i in range(40)]
    targets = [200.0] * 20 + [800.0] * 20
    ids = [0] * 20 + [1] * 20
    path = solve_camera_path_hold(times, targets, ids, 400, 1000)
    assert path[19][1] != path[20][1]  # instant snap at scene boundary
    assert len({x for _t, x in path[:20]}) == 1
    assert len({x for _t, x in path[20:]}) == 1


def test_falls_back_to_follow_for_continuous_travel():
    times = [i * 0.2 for i in range(60)]
    targets = [i * 12.0 for i in range(60)]  # walks across the whole frame
    path = solve_camera_path_hold(times, targets, [0] * 60, 400, 1000)
    xs = [x for _t, x in path]
    assert xs[-1] > xs[0] + 200  # camera travelled with the subject


from app.shorts.cutter.framing import lead_room_offsets


def test_lead_room_faces_direction_of_travel():
    times = [i * 0.2 for i in range(30)]
    targets = [100.0 + i * 15 for i in range(30)]  # moving right
    offsets = lead_room_offsets(times, targets, [0] * 30, 400)
    assert all(o > 0 for o in offsets)
    assert max(offsets) <= 0.12 * 400 + 1e-6


def test_static_subject_gets_no_offset():
    times = [i * 0.2 for i in range(30)]
    offsets = lead_room_offsets(times, [500.0] * 30, [0] * 30, 400)
    assert all(o == 0.0 for o in offsets)


def test_direction_is_per_scene():
    times = [i * 0.2 for i in range(40)]
    targets = [100.0 + i * 15 for i in range(20)] + [900.0 - i * 15 for i in range(20)]
    ids = [0] * 20 + [1] * 20
    offsets = lead_room_offsets(times, targets, ids, 400)
    assert all(o > 0 for o in offsets[:20])
    assert all(o < 0 for o in offsets[20:])


def test_recompose_catches_up_fast():
    # subject relocates across the frame mid-scene: the camera must arrive
    # within ~1.5s, not crawl at the follow-profile speed cap
    times = [i * 0.1 for i in range(100)]
    targets = [200.0] * 40 + [1500.0] * 60   # relocation at t=4.0s
    path = solve_camera_path_hold(times, targets, [0] * 100, 608, 1312)
    arrive = next(t for t, x in path if abs(x - (1500 - 304)) < 60)
    assert arrive <= 4.0 + 0.5 + 1.5  # excursion confirm + fast move


def test_bimodal_flipflop_commits_to_one_subject():
    # target alternates between a character (200) and an object (1400) —
    # averaging parks the camera between them and cuts BOTH in half
    times = [i * 0.2 for i in range(60)]
    targets = [200.0 if (i // 3) % 2 == 0 else 1400.0 for i in range(60)]
    path = solve_camera_path_hold(times, targets, [0] * 60, 608, 1312)
    centres = [x + 304 for _t, x in path]
    # camera must sit ON one of the subjects, never in no-man's land
    assert all(abs(c - 200) < 150 or abs(c - 1400) < 150 for c in centres)
    # and must commit: one locked position, not bouncing
    assert len({x for _t, x in path}) == 1


def test_wandering_target_still_follows():
    # genuinely wandering subject (smooth sweep + noise): follow, don't lock
    import numpy as np
    times = [i * 0.2 for i in range(80)]
    targets = [700 + 500 * np.sin(i * 0.15) + 40 * np.sin(i) for i in range(80)]
    path = solve_camera_path_hold(times, targets, [0] * 80, 608, 1312)
    xs = [x for _t, x in path]
    assert max(xs) - min(xs) > 300  # camera moved with the subject
