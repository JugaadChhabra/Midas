import struct
import wave

import numpy as np
import pytest

from app.shorts.cutter.vocals import _load_wav_stereo, rms_envelope, silence_threshold, silence_windows


def test_rms_envelope_shape_and_values():
    sr = 1000
    loud = np.ones(sr)          # 1s of loud
    quiet = np.zeros(sr)        # 1s of silence
    env = rms_envelope(np.concatenate([loud, quiet]), sr, hop_seconds=0.05)
    assert len(env) == 40
    assert env[5] == pytest.approx(1.0, abs=0.01)
    assert env[30] == pytest.approx(0.0, abs=0.001)


def test_silence_threshold_floor_and_relative():
    quiet_track = np.full(100, 1e-5)
    assert silence_threshold(quiet_track) == pytest.approx(10 ** (-45 / 20))
    loud_track = np.full(100, 0.8)
    assert silence_threshold(loud_track) == pytest.approx(0.05 * 0.8)


def test_silence_windows_min_duration_and_edges():
    hop = 0.05
    env = np.array([1.0] * 20 + [0.0] * 10 + [1.0] * 20 + [0.0] * 4 + [1.0] * 2 + [0.0] * 8)
    windows = silence_windows(env, hop, threshold=0.5, min_duration=0.35)
    # 10 hops = 0.5s window at [1.0, 1.5]; the 4-hop gap (0.2s) is too short;
    # the trailing 8 hops = 0.4s window runs to the end of audio
    assert windows[0] == (pytest.approx(1.0), pytest.approx(1.5))
    assert windows[1] == (pytest.approx(2.8), pytest.approx(3.2))
    assert len(windows) == 2


def test_load_wav_stereo(tmp_path):
    """_load_wav_stereo reads a stdlib-written stereo 16-bit PCM WAV correctly."""
    n_samples = 100
    sr = 44100
    channels = 2
    # Known int16 values: left channel = 16384 (≈ 0.5), right channel = -16384 (≈ -0.5)
    left_val = np.int16(16384)
    right_val = np.int16(-16384)
    interleaved = np.empty(n_samples * channels, dtype=np.int16)
    interleaved[0::2] = left_val
    interleaved[1::2] = right_val
    raw_frames = interleaved.tobytes()

    wav_file = tmp_path / "test_stereo.wav"
    with wave.open(str(wav_file), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)  # 16-bit
        handle.setframerate(sr)
        handle.writeframes(raw_frames)

    audio, rate = _load_wav_stereo(wav_file)

    assert rate == sr
    assert audio.shape == (2, n_samples)
    assert audio.dtype == np.float32
    # left channel ≈ 16384/32768 = 0.5
    assert audio[0, 0] == pytest.approx(16384.0 / 32768.0, abs=1e-4)
    # right channel ≈ -16384/32768 = -0.5
    assert audio[1, 0] == pytest.approx(-16384.0 / 32768.0, abs=1e-4)


def test_breath_gaps_do_not_qualify_as_cut_windows():
    # A 0.4s vocal gap is a breath between words, not a line break (user
    # observed perceptually mid-lyric cuts landing in such gaps).
    hop = 0.05
    env = np.array([1.0] * 20 + [0.0] * 8 + [1.0] * 20 + [0.0] * 20 + [1.0] * 10)
    windows = silence_windows(env, hop, threshold=0.5)
    assert windows == [(pytest.approx(2.4), pytest.approx(3.4))], (
        "only the 1.0s line-break gap should qualify; the 0.4s breath must not"
    )
