import numpy as np

from app.shorts.cutter.cutplan import TranscriptSegment
from app.shorts.cutter.structure import (LyricStanza, SongStructure, apply_audio_repetitions,
                       audio_repetition_ranges, beat_grid, build_structure,
                       group_stanzas, refine_stanza_bounds)


def seg(start, end, text):
    return TranscriptSegment(start, end, text)


def test_group_stanzas_splits_on_long_silence():
    units = [seg(0.0, 1.0, "ek"), seg(1.2, 2.0, "do"),
             seg(4.0, 5.0, "teen"), seg(5.2, 6.0, "char")]
    silence = [(2.0, 4.0)]
    stanzas = group_stanzas(units, silence)
    assert len(stanzas) == 2
    assert stanzas[0].text == "ek do"
    assert (stanzas[1].start, stanzas[1].end) == (4.0, 6.0)


def test_group_stanzas_ignores_breath_gaps():
    units = [seg(0.0, 1.0, "ek"), seg(1.5, 2.5, "do")]  # 0.5s gap, no window
    assert len(group_stanzas(units, [])) == 1


def test_group_stanzas_splits_on_gap_even_without_window():
    units = [seg(0.0, 1.0, "ek"), seg(3.0, 4.0, "do")]  # 2s transcript gap
    assert len(group_stanzas(units, [])) == 2


def st(i, start, end, text):
    return LyricStanza(i, start, end, text)


def test_normalise_lyric_strips_punctuation_and_case():
    from app.shorts.cutter.structure import normalise_lyric
    assert normalise_lyric("Machhli Jal Ki, Rani Hai!") == "machhli jal ki rani hai"
    assert normalise_lyric("मछली जल की रानी है।") == "मछली जल की रानी है"


def test_similarity_of_repeated_chorus_is_high():
    from app.shorts.cutter.structure import stanza_similarity
    a = "machhli jal ki rani hai jeevan uska paani hai"
    b = "machhli jal ki raani hai jeevan uska pani hai"  # whisper drift
    assert stanza_similarity(a, b) >= 0.7
    assert stanza_similarity(a, "haath lagao dar jayegi") < 0.5


def test_label_repetitions_finds_chorus_group():
    from app.shorts.cutter.structure import label_repetitions
    stanzas = [
        st(0, 0, 10, "machhli jal ki rani hai jeevan uska paani hai"),
        st(1, 12, 22, "haath lagao dar jayegi bahar nikalo mar jayegi"),
        st(2, 24, 34, "machhli jal ki rani hai jeevan uska pani hai"),
        st(3, 36, 46, "machhli jal ki rani hai jeevan uska paani hai"),
    ]
    assert label_repetitions(stanzas) is True
    assert stanzas[0].is_chorus and stanzas[2].is_chorus and stanzas[3].is_chorus
    assert not stanzas[1].is_chorus
    assert stanzas[0].repetition_group == stanzas[2].repetition_group


def test_label_repetitions_returns_false_when_nothing_repeats():
    from app.shorts.cutter.structure import label_repetitions
    stanzas = [st(0, 0, 10, "pehla alag hai"), st(1, 12, 22, "doosra bhi alag")]
    assert label_repetitions(stanzas) is False
    assert stanzas[0].repetition_group is None


def test_refine_bounds_snaps_to_vocal_energy():
    stanzas = [LyricStanza(0, 1.0, 3.0, "x")]
    hop, threshold = 0.05, 0.5
    envelope = np.zeros(100)
    envelope[24:56] = 1.0  # vocals actually run 1.2s..2.8s
    out = refine_stanza_bounds(stanzas, envelope, hop, threshold)
    assert abs(out[0].start - 1.2) < 0.06
    assert abs(out[0].end - 2.8) < 0.06


def _click_track(sr=22050, bpm=120, seconds=20):
    t = np.zeros(sr * seconds, dtype=np.float32)
    period = int(sr * 60 / bpm)
    for i in range(0, len(t), period):
        t[i:i + 200] = np.sin(2 * np.pi * 440 * np.arange(200) / sr).astype(np.float32)
    return t


def test_beat_grid_finds_stable_tempo():
    tempo, beats, downbeats = beat_grid(_click_track(), 22050)
    assert 110 <= tempo <= 130
    assert len(beats) >= 30
    assert len(downbeats) >= 7
    assert all(b in beats for b in downbeats)


def test_beat_grid_degrades_on_silence():
    tempo, beats, downbeats = beat_grid(np.zeros(22050 * 4, dtype=np.float32), 22050)
    assert downbeats == [] or len(downbeats) < 3  # no confident grid — fine


def _repeating_melody(sr=22050):
    """A-B-A over 30s: 10s motif, 10s different, same 10s motif again."""
    def tone_seq(freqs, seconds):
        out = []
        for f in freqs:
            n = int(sr * seconds / len(freqs))
            out.append(np.sin(2 * np.pi * f * np.arange(n) / sr))
        return np.concatenate(out)
    a = tone_seq([262, 330, 392, 330, 262, 392, 330, 262], 10.0)
    b = tone_seq([294, 370, 440, 494, 440, 370, 294, 440], 10.0)
    return np.concatenate([a, b, a]).astype(np.float32)


def test_audio_repetition_ranges_finds_aba_repeat():
    ranges = audio_repetition_ranges(_repeating_melody(), 22050, min_repeat=8.0)
    assert ranges, "expected at least one repeated range"
    assert any(r[0] < 10.0 for r in ranges)      # the first A occurrence
    assert any(r[0] >= 15.0 for r in ranges)     # the repeated A occurrence


def test_apply_audio_repetitions_marks_overlapping_stanzas():
    stanzas = [st(0, 0, 9, "aaa"), st(1, 10, 19, "bbb"), st(2, 20, 29, "aaa2")]
    changed = apply_audio_repetitions(stanzas, [(0.0, 9.0), (20.0, 29.0)])
    assert changed is True
    assert stanzas[0].is_chorus and stanzas[2].is_chorus and not stanzas[1].is_chorus


def test_build_structure_prefers_lyric_path():
    units = [seg(0.0, 4.0, "machhli jal ki rani hai"),
             seg(6.0, 10.0, "haath lagao dar jayegi"),
             seg(12.0, 16.0, "machhli jal ki raani hai")]
    silence = [(4.0, 6.0), (10.0, 12.0)]
    envelope = np.ones(int(16.0 / 0.05))
    result = build_structure(units, silence, envelope, 0.05, 0.5,
                             _click_track(seconds=16), 22050)
    assert isinstance(result, SongStructure)
    assert result.chorus_source == "lyrics"
    assert result.stanzas[0].is_chorus and result.stanzas[2].is_chorus


def test_stanzas_from_silence_when_transcript_empty():
    from app.shorts.cutter.structure import stanzas_from_silence
    silence = [(8.0, 10.0), (35.0, 37.0), (60.0, 62.0)]
    stanzas = stanzas_from_silence(silence, 90.0)
    spans = [(s.start, s.end) for s in stanzas]
    assert (0.0, 8.0) in spans          # before first silence
    assert (10.0, 35.0) in spans        # between silences
    assert (62.0, 90.0) in spans        # after last silence
    assert all(s.text == "" for s in stanzas)
    assert [s.index for s in stanzas] == list(range(len(stanzas)))


def test_stanzas_from_silence_drops_tiny_spans():
    from app.shorts.cutter.structure import stanzas_from_silence
    stanzas = stanzas_from_silence([(1.0, 2.0), (2.5, 4.0)], 5.0)
    assert all(s.end - s.start >= 2.0 for s in stanzas)  # 2.0..2.5 dropped


def test_build_structure_uses_silence_stanzas_without_transcript():
    silence = [(8.0, 10.0), (35.0, 37.0)]
    envelope = np.ones(int(60.0 / 0.05))
    result = build_structure([], silence, envelope, 0.05, 0.5,
                             _click_track(seconds=20), 22050, duration=60.0)
    assert len(result.stanzas) >= 2
    assert result.chorus_source in {"audio", "none"}


def test_char_level_fallback_catches_transliteration_drift():
    from app.shorts.cutter.structure import label_repetitions
    # real Whisper drift from the Johny Johny run — word-level fails on these
    stanzas = [
        st(0, 24, 43, "जाने झ्वोनी येज पाप्पा इ Moscow नो पाप्पा तेलिंग लाइस नो बापा"),
        st(1, 62, 73, "जोनी जोनी येस बाभा यीटीं दावी नो भाभा टेलीं लाइस नो भाभा अपन"),
        st(2, 104, 106, "वाद वाद वाद वाद वाद वाद"),
        st(3, 114, 124, "जोनी जोनी जेस पापा इदीं चोकलिट नोग पापा नोग पापा अपन नो वाद"),
    ]
    assert label_repetitions(stanzas) is False        # word-level: nothing
    assert label_repetitions(stanzas, mode="chars") is True
    assert stanzas[0].is_chorus and stanzas[1].is_chorus and stanzas[3].is_chorus
    assert not stanzas[2].is_chorus


def test_char_mode_does_not_group_unrelated_text():
    from app.shorts.cutter.structure import label_repetitions
    stanzas = [st(0, 0, 10, "आाााँ अगुग"), st(1, 12, 22, "बाँइसा कोँछ्वेदो"),
               st(2, 24, 34, "वाद वाद वाद वाद")]
    assert label_repetitions(stanzas, mode="chars") is False
