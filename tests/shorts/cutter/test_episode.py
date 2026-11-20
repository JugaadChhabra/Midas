"""Episode mode: an animated episode walked front to back in 45-50 s Shorts."""
import numpy as np

from app.shorts.cutter.cutplan import (
    EPISODE_MAX_SECONDS, EPISODE_MIN_SECONDS, episode_stanzas,
)


def _check_sequential(stanzas, duration):
    assert stanzas[0].start == 0.0
    for a, b in zip(stanzas, stanzas[1:]):
        assert a.end == b.start                       # no gap, no overlap
    for s in stanzas[:-1]:
        assert EPISODE_MIN_SECONDS - 1e-6 <= s.end - s.start <= EPISODE_MAX_SECONDS + 1e-6


def test_twenty_minute_episode_gives_about_25_clips_with_no_vocal_data():
    stanzas = episode_stanzas([], 1200.0)
    _check_sequential(stanzas, 1200.0)
    assert 24 <= len(stanzas) <= 26
    assert stanzas[-1].end == 1200.0 or 1200.0 - stanzas[-1].end < 20.0


def test_cuts_land_in_dialogue_pauses():
    # a pause every 7 s: every cut must sit inside one
    silence = [(t, t + 0.8) for t in np.arange(5.0, 600.0, 7.0)]
    stanzas = episode_stanzas([], 600.0, silence=silence)
    _check_sequential(stanzas, 600.0)
    for s in stanzas[:-1]:
        assert any(a <= s.end <= b for a, b in silence), s
        assert s.boundary in ("pause", "scene-silent")


def test_prefers_a_scene_change_inside_a_pause():
    silence = [(46.0, 47.0), (48.0, 49.5)]
    stanzas = episode_stanzas([], 120.0, silence=silence, scene_times=[48.7])
    assert stanzas[0].end == 48.7 and stanzas[0].boundary == "scene-silent"


def test_falls_back_to_quietest_point_without_pauses():
    hop = 0.05
    envelope = np.ones(int(200 / hop))
    envelope[int(46.2 / hop)] = 0.0
    stanzas = episode_stanzas([], 200.0, silence=[], envelope=envelope, hop=hop)
    assert abs(stanzas[0].end - 46.2) < hop and stanzas[0].boundary == "quietest"


def test_tiny_tail_dropped_real_tail_kept():
    # 3 clips of 47.5 cover 142.5; a 10 s remainder is an end card
    assert episode_stanzas([], 152.5)[-1].end < 152.5
    # a 30 s remainder ships as a shorter last Short
    last = episode_stanzas([], 172.5)[-1]
    assert last.end == 172.5 and last.end - last.start == 30.0


def test_short_video_is_one_clip():
    stanzas = episode_stanzas([], 40.0)
    assert len(stanzas) == 1 and (stanzas[0].start, stanzas[0].end) == (0.0, 40.0)
    assert episode_stanzas([], 0.0) == []
