from app.shorts.cutter.structure import LyricStanza
from app.shorts.cutter.selection import (DEFAULT_WEIGHTS, Candidate, generate_candidates,
                       score_candidates)


def st(i, start, end, text="la", chorus=False, group=None):
    return LyricStanza(i, start, end, text, group, chorus)


def test_candidates_come_only_from_stanza_units():
    stanzas = [st(0, 0, 25), st(1, 27, 45), st(2, 47, 90)]
    cands = generate_candidates(stanzas)
    spans = {(c.start, c.end) for c in cands}
    assert (0.0, 25.0) in spans            # single stanza in band
    assert (0.0, 45.0) in spans            # adjacent pair in band
    assert (47.0, 90.0) in spans           # 43s stanza fits the band
    assert (27.0, 90.0) not in spans       # 63s pair does not
    for c in cands:
        length = c.end - c.start
        assert 15.0 <= length <= 45.0
        # 15-20s spans are allowed only as pad-to-minimum candidates
        assert c.needs_padding == (length < 20.0)


def test_short_chorus_pairs_with_neighbours():
    stanzas = [st(0, 0, 18), st(1, 20, 32, chorus=True, group=0), st(2, 34, 50)]
    cands = generate_candidates(stanzas)
    spans = {(c.start, c.end) for c in cands}
    assert (0.0, 32.0) in spans and (20.0, 50.0) in spans
    assert any(c.is_chorus for c in cands)


def test_scoring_prefers_chorus_with_clean_edges():
    stanzas = [st(0, 10, 40, chorus=True, group=0), st(1, 50, 80)]
    cands = generate_candidates(stanzas)
    silence = [(8.0, 10.0), (40.0, 42.0), (48.5, 50.0), (80.0, 81.5)]
    score_candidates(cands, stanzas, silence, downbeats=[9.5, 41.0],
                     scene_times=[10.1], sample_times=None, sample_targets=None,
                     camera_xs=None, crop_width=None)
    chorus = next(c for c in cands if c.is_chorus)
    verse = next(c for c in cands if not c.is_chorus)
    assert chorus.score > verse.score
    assert 0.0 <= verse.score <= 1.0
    assert set(chorus.components) == set(DEFAULT_WEIGHTS)


from app.shorts.cutter.selection import select_clips


def cand(start, end, score, indices, chorus=False):
    c = Candidate(start, end, indices, chorus)
    c.score = score
    return c


def test_select_no_overlap_highest_score_wins():
    stanzas = [st(0, 0, 30), st(1, 20, 45)]
    cands = [cand(0, 30, 0.9, [0]), cand(20, 45, 0.8, [1])]
    picked = select_clips(cands, stanzas, min_count=1)
    assert [(c.start, c.end) for c in picked] == [(0, 30)]


def test_select_caps_per_chorus_group():
    stanzas = [st(i, i * 30, i * 30 + 25, chorus=True, group=0) for i in range(4)]
    cands = [cand(s.start, s.end, 0.9, [s.index], chorus=True) for s in stanzas]
    picked = select_clips(cands, stanzas, min_count=1, per_group_cap=2)
    assert len(picked) == 2


def test_select_fills_to_min_count_and_flags():
    stanzas = [st(i, i * 30, i * 30 + 25) for i in range(5)]
    scores = [0.9, 0.8, 0.3, 0.2, 0.1]
    cands = [cand(s.start, s.end, scores[i], [s.index])
             for i, s in enumerate(stanzas)]
    picked = select_clips(cands, stanzas, min_count=4, floor=0.45)
    assert len(picked) == 4
    assert sum(1 for c in picked if c.below_floor) == 2
    assert [c.start for c in picked] == sorted(c.start for c in picked)


def test_select_respects_max_count():
    stanzas = [st(i, i * 30, i * 30 + 25) for i in range(12)]
    cands = [cand(s.start, s.end, 0.9, [s.index]) for s in stanzas]
    assert len(select_clips(cands, stanzas, max_count=8)) == 8


from app.shorts.cutter.selection import plan_highlights
from app.shorts.cutter.structure import SongStructure


def test_plan_highlights_end_to_end_synthetic():
    stanzas = [
        st(0, 10, 35, "machhli jal ki rani hai", chorus=True, group=0),
        st(1, 40, 65, "haath lagao dar jayegi"),
        st(2, 70, 95, "machhli jal ki rani hai", chorus=True, group=0),
    ]
    silence = [(8, 10), (35, 40), (65, 70), (95, 100)]
    song = SongStructure(stanzas, 120.0, [], [9.5, 36.0, 69.0, 96.0], "lyrics")
    clips, diagnostics = plan_highlights(
        song, silence, scene_times=[], sample_times=None, sample_targets=None,
        camera_xs=None, crop_width=None, duration=100.0)
    assert 1 <= len(clips) <= 8
    # every boundary inside a silence window (or video edge)
    for clip in clips:
        assert any(a - 0.101 <= clip.start <= b + 0.101 for a, b in silence) or clip.start == 0.0
        assert any(a - 0.101 <= clip.end <= b + 0.101 for a, b in silence) or clip.end == 100.0
        assert "+" in clip.boundary
    assert len(diagnostics) >= len(clips)
    assert all("components" in d and "selected" in d for d in diagnostics)
    assert sum(1 for d in diagnostics if d["selected"]) == len(clips)
    # clips are non-overlapping and sorted
    for a, b in zip(clips, clips[1:]):
        assert a.end <= b.start


def test_plan_highlights_empty_structure_returns_nothing():
    song = SongStructure([], 0.0, [], [], "none")
    clips, diagnostics = plan_highlights(song, [], [], None, None, None, None, 100.0)
    assert clips == [] and diagnostics == []


def test_fragmented_stanzas_form_multi_stanza_runs():
    # ten 6s stanzas with 2s gaps: singles/pairs never reach 20s,
    # but runs of 3+ do — a fragmented-transcript song must still yield clips
    stanzas = [st(i, i * 8.0, i * 8.0 + 6.0) for i in range(10)]
    cands = generate_candidates(stanzas)
    assert cands, "expected multi-stanza runs"
    assert all(20.0 <= c.end - c.start <= 45.0 for c in cands)
    assert any(len(c.stanza_indices) >= 3 for c in cands)


def test_padding_never_creates_overlap():
    stanzas = [
        st(0, 0.8, 17.6, "hook hook hook", chorus=True, group=0),
        st(1, 19.8, 51.1, "verse verse verse"),
    ]
    silence = [(0.0, 0.8), (17.6, 19.8), (51.1, 55.0)]
    song = SongStructure(stanzas, 100.0, [], [], "lyrics")
    clips, _diag = plan_highlights(song, silence, [], None, None, None, None, 60.0)
    assert len(clips) == 2
    for a, b in zip(clips, clips[1:]):
        assert a.end <= b.start  # padding must stop at the neighbour


def test_selection_prefers_lyric_coverage_over_repeats():
    stanzas = [
        st(0, 0, 25, "mummy ki roti gol gol papa ka paisa gol gol", chorus=True, group=0),
        st(1, 30, 55, "mummy ki roti gol gol papa ka paisa gol gol", chorus=True, group=0),
        st(2, 60, 85, "chanda gol suraj gol hum bhi gol tum bhi gol"),
    ]
    cands = [cand(0, 25, 0.85, [0], chorus=True),
             cand(30, 55, 0.80, [1], chorus=True),   # near-duplicate lyrics
             cand(60, 85, 0.70, [2])]                # distinct verse
    picked = select_clips(cands, stanzas, min_count=1, max_count=2)
    spans = [(c.start, c.end) for c in picked]
    assert (0, 25) in spans          # best chorus still leads
    assert (60, 85) in spans         # distinct lyrics beat the duplicate
    assert (30, 55) not in spans


def test_diversity_penalty_does_not_block_much_better_repeat():
    stanzas = [
        st(0, 0, 25, "same hook line here", chorus=True, group=0),
        st(1, 30, 55, "same hook line here", chorus=True, group=0),
        st(2, 60, 85, "totally different verse"),
    ]
    cands = [cand(0, 25, 0.95, [0], chorus=True),
             cand(30, 55, 0.90, [1], chorus=True),
             cand(60, 85, 0.15, [2])]                # distinct but junk
    picked = select_clips(cands, stanzas, min_count=1, max_count=2, floor=0.45)
    spans = [(c.start, c.end) for c in picked]
    assert (0, 25) in spans and (30, 55) in spans    # junk never wins on diversity alone
