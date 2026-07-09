"""Vocal-stem silence detection. Silence windows are the only legal cut zones."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

HOP_SECONDS = 0.05
# Cut-eligible silence must be a real line break, not a breath between words:
# ~0.4s gaps occur mid-line in sung rhymes and produced perceptually mid-lyric cuts.
MIN_SILENCE_SECONDS = 0.90
# Short-but-real pauses (breath-length): last-resort cut zones, always flagged.
SHORT_SILENCE_SECONDS = 0.45
SILENCE_FLOOR_DB = -45.0
RELATIVE_LEVEL = 0.05  # fraction of the stem's 95th-percentile loudness


def rms_envelope(samples: np.ndarray, sr: int, hop_seconds: float = HOP_SECONDS) -> np.ndarray:
    hop = max(1, int(sr * hop_seconds))
    usable = len(samples) - len(samples) % hop
    if usable <= 0:
        return np.zeros(0)
    frames = samples[:usable].reshape(-1, hop)
    return np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))


def silence_threshold(envelope: np.ndarray) -> float:
    floor = 10 ** (SILENCE_FLOOR_DB / 20)
    if len(envelope) == 0:
        return floor
    return max(floor, RELATIVE_LEVEL * float(np.percentile(envelope, 95)))


def silence_windows(
    envelope: np.ndarray,
    hop_seconds: float,
    threshold: float,
    min_duration: float = MIN_SILENCE_SECONDS,
) -> list[tuple[float, float]]:
    windows: list[tuple[float, float]] = []
    start: float | None = None
    for index, value in enumerate(envelope):
        if value < threshold:
            if start is None:
                start = index * hop_seconds
        elif start is not None:
            end = index * hop_seconds
            if end - start >= min_duration:
                windows.append((start, end))
            start = None
    if start is not None:
        end = len(envelope) * hop_seconds
        if end - start >= min_duration:
            windows.append((start, end))
    return windows


def _extract_audio(source: Path, destination: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg not found")
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-y", "-i", str(source),
         "-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(destination)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {(result.stderr or '')[-500:]}")


def _load_wav_stereo(wav_path: Path) -> tuple[np.ndarray, int]:
    """Read our own FFmpeg-extracted PCM WAV: (channels, samples) float32 in [-1, 1]."""
    import wave

    with wave.open(str(wav_path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())
    if channels != 2:
        raise RuntimeError(f"Expected stereo WAV, got {channels} channel(s)")
    if width != 2:
        raise RuntimeError(f"Expected 16-bit PCM WAV, got sample width {width}")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return samples.reshape(-1, channels).T.copy(), rate


def _separate_vocals(wav_path: Path) -> tuple[np.ndarray, int]:
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    model = get_model("htdemucs")
    # CPU is byte-deterministic (verified 2026-07-08); MPS leaves float jitter
    # in the stem that nudges transcripts and shuffles clip picks run-to-run.
    # ~19s for a 2-minute video — reproducibility is worth it.
    device = "cpu"
    audio, sr = _load_wav_stereo(wav_path)
    if sr != model.samplerate:
        raise RuntimeError(f"Extracted WAV is {sr} Hz; expected {model.samplerate}")
    wav = torch.from_numpy(audio)
    reference = wav.mean(0)
    normalised = (wav - reference.mean()) / (reference.std() + 1e-8)
    # shifts=0 is essential: apply_model defaults to ONE RANDOM time shift per
    # run (unseeded random.randint), which made stems — and everything
    # downstream: transcripts, stanzas, clip picks — differ on every run.
    try:
        sources = apply_model(model, normalised[None], device=device,
                              split=True, overlap=0.1, shifts=0)[0]
    except Exception:
        # MPS occasionally fails on some ops; retry once on CPU before giving up.
        sources = apply_model(model, normalised[None], device="cpu",
                              split=True, overlap=0.1, shifts=0)[0]
    vocals = sources[model.sources.index("vocals")]
    vocals = vocals * (reference.std() + 1e-8) + reference.mean()
    return vocals.mean(0).cpu().numpy(), sr


def _write_mono_wav(samples: np.ndarray, sr: int, destination: Path) -> None:
    import wave

    clipped = np.clip(samples, -1.0, 1.0)
    with wave.open(str(destination), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes((clipped * 32767.0).astype(np.int16).tobytes())


def vocal_silence_analysis(source: Path, work_dir: Path) -> dict:
    """Raises on any failure. The caller decides how to degrade."""
    wav_path = work_dir / "audio_for_vocals.wav"
    _extract_audio(source, wav_path)
    vocal_track, sr = _separate_vocals(wav_path)
    # The isolated stem transcribes far better than the full mix: no music
    # bed to confuse Whisper's language detection or trip temperature
    # fallback into unstable output.
    stem_path = work_dir / "vocal_stem.wav"
    _write_mono_wav(vocal_track, sr, stem_path)
    envelope = rms_envelope(vocal_track, sr)
    threshold = silence_threshold(envelope)
    all_pauses = silence_windows(envelope, HOP_SECONDS, threshold,
                                 min_duration=SHORT_SILENCE_SECONDS)
    return {
        "stem_path": stem_path,
        "envelope": envelope,
        "short_windows": [
            (a, b) for a, b in all_pauses
            if b - a < MIN_SILENCE_SECONDS
        ],
        "hop": HOP_SECONDS,
        "threshold": threshold,
        "windows": silence_windows(envelope, HOP_SECONDS, threshold),
    }


def load_mix_mono(wav_path: Path) -> tuple[np.ndarray, int]:
    """Mono float32 mix for beat tracking / self-similarity. Reuses our own
    FFmpeg-extracted WAV — never torchaudio."""
    stereo, sr = _load_wav_stereo(wav_path)
    return stereo.mean(axis=0).astype(np.float32), sr
