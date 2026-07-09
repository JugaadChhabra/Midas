import wave
from pathlib import Path

import numpy as np

from app.shorts.cutter.vocals import load_mix_mono


def test_load_mix_mono(tmp_path: Path):
    path = tmp_path / "t.wav"
    stereo = (np.random.default_rng(0).integers(-1000, 1000, (441, 2))
              .astype(np.int16))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(stereo.tobytes())
    mono, sr = load_mix_mono(path)
    assert sr == 44100 and mono.shape == (441,) and mono.dtype == np.float32
