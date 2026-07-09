import numpy as np
import pytest

from app.shorts.cutter.cutplan import MIN_CLIP_SECONDS, Stanza, full_coverage_stanzas


def flat_envelope(duration, hop=0.05, level=1.0):
    return np.full(int(duration / hop), level)


def coverage_ok(stanzas, duration):
    assert stanzas[0].start == 0.0
    assert stanzas[-1].end == pytest.approx(duration, abs=0.02)
    for a, b in zip(stanzas, stanzas[1:]):
        assert a.end == pytest.approx(b.start, abs=0.001)


def test_boundaries_land_inside_silence_windows():
    duration = 120.0
    silence = [(55.0, 56.0), (61.0, 62.0)]
    stanzas = full_coverage_stanzas([], duration, 58.0, silence=silence,
                                    envelope=flat_envelope(duration), hop=0.05)
    coverage_ok(stanzas, duration)
    interior = [s.end for s in stanzas[:-1]]
    for cut in interior:
        assert any(ws <= cut <= we for ws, we in silence), f"cut {cut} outside silence"
    assert all(s.boundary in {"pause", "scene-silent", "end"} for s in stanzas)


def test_scene_cut_inside_silence_wins():
    duration = 120.0
    silence = [(50.0, 53.0), (60.0, 61.0)]
    # scene cut at 52.0 sits inside the first window: it should be chosen exactly
    stanzas = full_coverage_stanzas([], duration, 58.0, silence=silence,
                                    scene_times=[52.0],
                                    envelope=flat_envelope(duration), hop=0.05)
    assert stanzas[0].end == pytest.approx(52.0)
    assert stanzas[1].start == pytest.approx(52.0)
    assert stanzas[0].boundary == "scene-silent"


def test_forced_cut_picks_envelope_minimum():
    duration = 100.0
    env = flat_envelope(duration)
    env[900] = 0.01  # quietest point at t=45.0
    stanzas = full_coverage_stanzas([], duration, 58.0, silence=[],
                                    envelope=env, hop=0.05)
    coverage_ok(stanzas, duration)
    forced = [s for s in stanzas if s.boundary == "forced"]
    assert forced and forced[0].end == pytest.approx(45.0, abs=0.1)


def test_clip_length_legality_and_full_coverage():
    duration = 300.0
    silence = [(i * 10.0, i * 10.0 + 0.5) for i in range(1, 30)]
    stanzas = full_coverage_stanzas([], duration, 45.0, silence=silence,
                                    envelope=flat_envelope(duration), hop=0.05)
    coverage_ok(stanzas, duration)
    for s in stanzas:
        assert s.end - s.start <= 45.0 + 0.01
        assert s.end - s.start >= MIN_CLIP_SECONDS - 0.01 or s.boundary == "safety"


def test_fallback_mode_uses_pauses_and_balanced():
    # pause at 45.0 is within the ±10s window of the ideal balanced boundary (40.0)
    stanzas = full_coverage_stanzas([], 120.0, 58.0, silence=None,
                                    fallback_pauses=[45.0])
    coverage_ok(stanzas, 120.0)
    assert stanzas[0].end == pytest.approx(45.0)
    assert stanzas[0].boundary == "pause"


def test_prefer_visual_beats_false_ignores_scene_times():
    duration = 120.0
    silence = [(50.0, 53.0), (60.0, 61.0)]
    with_beats = full_coverage_stanzas([], duration, 58.0, silence=silence,
                                       scene_times=[52.0],
                                       envelope=flat_envelope(duration), hop=0.05,
                                       prefer_visual_beats=False)
    assert all(s.boundary != "scene-silent" for s in with_beats)


def test_forced_cut_finds_minimum_at_range_end():
    # Regression: minimum at exactly latest bound should be included in search.
    # duration=100.0, max_seconds=58.0 gives boundary 1 legal range [42.0, 58.0].
    # Set envelope minimum at t=58.0 (index 1160 with hop=0.05).
    duration = 100.0
    env = flat_envelope(duration)
    env[int(58.0 / 0.05)] = 0.01  # index 1160, t=58.0
    stanzas = full_coverage_stanzas([], duration, 58.0, silence=[],
                                    envelope=env, hop=0.05)
    coverage_ok(stanzas, duration)
    forced = [s for s in stanzas if s.boundary == "forced"]
    assert forced and forced[0].end == pytest.approx(58.0, abs=0.1)


def test_forced_cut_envelope_shorter_than_video():
    # Regression: if the vocal envelope covers only 30s but the video is 100s,
    # the forced-cut legal range [42, 58] is entirely past the end of the envelope.
    # envelope[lo:hi] would be empty, causing a ValueError in np.argmin.
    # After the fix: should NOT raise; coverage must be intact; boundary is "forced".
    duration = 100.0
    envelope = flat_envelope(30.0)  # envelope covers only 0..30s
    stanzas = full_coverage_stanzas([], duration, 58.0, silence=[],
                                    envelope=envelope, hop=0.05)
    # Must not raise; full coverage must be intact
    coverage_ok(stanzas, duration)
    interior = [s for s in stanzas[:-1]]
    assert any(s.boundary == "forced" for s in interior)


def test_short_pause_beats_forced_but_loses_to_real_silence():
    duration = 120.0
    env = flat_envelope(duration)
    # no long silence in the first boundary's legal range, but a short pause exists
    stanzas = full_coverage_stanzas([], duration, 58.0, silence=[],
                                    short_silence=[(45.0, 45.6)],
                                    envelope=env, hop=0.05)
    coverage_ok(stanzas, duration)
    assert stanzas[0].end == pytest.approx(45.3, abs=0.1)
    assert stanzas[0].boundary == "short-pause"
    # when a real line break exists too, it must win even if farther from ideal
    stanzas2 = full_coverage_stanzas([], duration, 58.0,
                                     silence=[(52.0, 53.2)],
                                     short_silence=[(41.0, 41.6)],
                                     envelope=env, hop=0.05)
    assert stanzas2[0].boundary == "pause"
    assert stanzas2[0].end == pytest.approx(52.6, abs=0.1)
