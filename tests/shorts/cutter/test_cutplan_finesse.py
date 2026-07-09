from app.shorts.cutter.cutplan import finesse_boundaries


def test_start_snaps_to_downbeat_inside_lead_window():
    # vocals start at 10.0; silence 7.0..10.0; downbeat at 9.2 (0.8s lead)
    start, end, sk, ek = finesse_boundaries(
        10.0, 30.0, [(7.0, 10.0), (30.0, 32.0)], [9.2, 31.0], 60.0)
    assert sk == "downbeat" and abs(start - 9.2) < 1e-6
    assert ek == "downbeat" and abs(end - 31.0) < 1e-6


def test_no_downbeat_falls_back_to_onset_lead_and_decay():
    start, end, sk, ek = finesse_boundaries(
        10.0, 30.0, [(9.7, 10.0), (30.0, 30.3)], [], 60.0)
    assert sk == "onset" and 9.7 <= start < 10.0   # clamped inside silence
    assert ek == "decay" and 30.0 < end <= 30.3


def test_boundaries_never_leave_silence_windows():
    start, end, _sk, _ek = finesse_boundaries(
        10.0, 30.0, [(8.0, 10.0), (30.0, 34.0)], [7.0, 33.9], 60.0)
    assert 8.0 <= start <= 10.0
    # 33.9 downbeat is inside the window but 3.9s past the vocal offset —
    # beyond the 1.5s extension cap, so the 0.5s decay fallback wins.
    assert end == 30.5


def test_video_edges_respected():
    start, end, _sk, _ek = finesse_boundaries(0.2, 59.8, [(59.9, 60.0)], [], 60.0)
    assert start >= 0.0 and end <= 60.0


from app.shorts.cutter.cutplan import pad_clip


def test_pad_clip_reaches_minimum_inside_silence():
    # 17s stanza with roomy silence on both sides: pad to 20s, split evenly
    start, end = pad_clip(10.0, 27.0, [(6.0, 10.0), (27.0, 32.0)], 20.0, 60.0)
    assert end - start >= 20.0
    assert 6.0 <= start <= 10.0 and 27.0 <= end <= 32.0


def test_pad_clip_respects_video_edges_and_windows():
    # start at 0.8 with silence 0..0.8: can only take 0.8 from the front
    start, end = pad_clip(0.8, 17.6, [(0.0, 0.8), (17.6, 25.0)], 20.0, 118.0)
    assert start == 0.0 and end - start >= 20.0
    assert end <= 25.0


def test_pad_clip_best_effort_when_windows_are_tight():
    start, end = pad_clip(10.0, 27.0, [(9.5, 10.0), (27.0, 27.5)], 20.0, 60.0)
    assert (start, end) == (9.5, 27.5)  # gave everything it legally could
