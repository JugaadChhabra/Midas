"""Cut a source video into vertical Shorts. Framework-free public entry point."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from app.shorts.cutter.cutplan import (
    MAX_CLIP_SECONDS, Stanza, full_coverage_stanzas, lyric_pause_candidates,
)
from app.shorts.cutter.grading import grade_clips
from app.shorts.cutter.render import (
    DEFAULT_CAMERA_MOTION, export_clip, render_vertical, source_metadata,
)
from app.shorts.cutter.selection import plan_highlights
from app.shorts.cutter.structure import build_structure
from app.shorts.cutter.transcribe import save_transcript, transcribe_multilingual
from app.shorts.cutter.util import safe_name
from app.shorts.cutter.vocals import load_mix_mono, vocal_silence_analysis


def _normalise_cut_mode(value: str | None) -> str:
    value = str(value or "highlights").strip().lower()
    return value if value in {"highlights", "coverage"} else "highlights"


def cut_video(
    source: Path,
    work_dir: Path,
    preferred_name: str,
    cut_mode: str = "highlights",
    camera_motion: str = DEFAULT_CAMERA_MOTION,
    progress: Callable[[str, int], None] | None = None,
) -> dict:
    cut_mode = _normalise_cut_mode(cut_mode)

    def _tick(stage: str, percent: int) -> None:
        if progress is not None:
            progress(stage, percent)

    clips_dir = work_dir / "clips"
    temp_job = work_dir / "tmp"
    clips_dir.mkdir(parents=True, exist_ok=True)
    temp_job.mkdir(parents=True, exist_ok=True)
    try:
        master = temp_job / f"{safe_name(preferred_name)}_vertical_master.mp4"
        _tick("analysing framing", 15)
        crop_info = render_vertical(source, master, True, temp_job, camera_motion)

        # ---- body transplanted from $SRC/main.py:681-766 verbatim,
        # substitutions: job_folder -> clips_dir, smart -> True,
        # max_clip_seconds -> MAX_CLIP_SECONDS
        duration, _width, _height = source_metadata(source)

        vocal = None
        vocal_error = ""
        _tick("separating vocals", 40)
        try:
            vocal = vocal_silence_analysis(source, temp_job)
        except Exception as exc:
            vocal_error = str(exc)[:200]

        transcribe_input = source
        if vocal is not None and vocal.get("stem_path") and vocal["stem_path"].exists():
            # Isolated vocals transcribe far better than the full music mix.
            transcribe_input = vocal["stem_path"]
        _tick("transcribing lyrics", 55)
        language, probability, transcript, timing_units = transcribe_multilingual(
            transcribe_input, duration, vocal["windows"] if vocal else None,
            language=None)

        scene_times = list(crop_info.get("scene_cut_times", []))
        stanzas: list[Stanza] = []
        selection_diag: list[dict] | None = None
        wav_path = temp_job / "audio_for_vocals.wav"
        _tick("planning cuts", 70)
        if cut_mode == "highlights" and vocal is not None and wav_path.exists():
            mix_mono, sr = load_mix_mono(wav_path)
            song = build_structure(timing_units, vocal["windows"],
                                   vocal["envelope"], vocal["hop"],
                                   vocal["threshold"], mix_mono, sr,
                                   duration=duration)
            stanzas, all_candidates = plan_highlights(
                song, vocal["windows"], scene_times,
                crop_info.get("sample_times"),
                crop_info.get("sample_targets"),
                crop_info.get("camera_xs"),
                crop_info.get("crop_size", [None])[0],
                duration)
            if stanzas:
                selection_diag = [d for d in all_candidates if d["selected"]]
                (clips_dir / "song_structure.json").write_text(json.dumps({
                    "chorus_source": song.chorus_source, "tempo": song.tempo,
                    "downbeats": song.downbeats,
                    "stanzas": [asdict(s) for s in song.stanzas],
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                (clips_dir / "highlight_candidates.json").write_text(
                    json.dumps(all_candidates, ensure_ascii=False, indent=2),
                    encoding="utf-8")

        if not stanzas:
            # coverage mode, degraded mode, or highlights found nothing usable
            selection_diag = None
            if vocal is not None:
                stanzas = full_coverage_stanzas(
                    timing_units, duration, MAX_CLIP_SECONDS,
                    silence=vocal["windows"], scene_times=scene_times,
                    short_silence=vocal.get("short_windows"),
                    envelope=vocal["envelope"], hop=vocal["hop"],
                    prefer_visual_beats=True,
                )
            else:
                stanzas = full_coverage_stanzas(
                    timing_units, duration, MAX_CLIP_SECONDS,
                    silence=None,
                    fallback_pauses=lyric_pause_candidates(timing_units, duration),
                )

        grades = grade_clips(
            stanzas, vocal,
            crop_info.get("sample_times"),
            crop_info.get("sample_targets"),
            crop_info.get("camera_xs"),
            crop_info.get("crop_size", [None])[0],
            intended_offsets=crop_info.get("intended_offsets"),
            selection_info=selection_diag,
        )

        save_transcript(
            clips_dir,
            language,
            probability,
            transcript,
            stanzas,
            visual_beats=crop_info.get("visual_beats", []),
            silence_windows=vocal["windows"] if vocal else [],
            grades=grades,
        )
        # ---- end transplanted body ----

        clip_records = []
        for index, stanza in enumerate(stanzas, start=1):
            _tick("rendering clips", 80 + int(15 * (index - 1) / max(len(stanzas), 1)))
            clip_name = f"{safe_name(preferred_name)}_stanza_{index:02}_{int(stanza.start):04d}s.mp4"
            clip_path = clips_dir / clip_name
            export_clip(master, clip_path, stanza.start, stanza.end)
            grade = grades[index - 1] if index - 1 < len(grades) else {}
            clip_records.append({
                "path": str(clip_path), "rank": index,
                "start_s": float(stanza.start), "end_s": float(stanza.end),
                "verdict": grade.get("verdict", "CHECK"),
            })

        passed = sum(1 for g in grades if g["verdict"] == "PASS")
        mode_word = "highlight" if selection_diag is not None else "full-coverage"
        return {
            "clips": clip_records,
            "cut_mode": "highlights" if selection_diag is not None else "coverage",
            "language": language,
            "message": (
                f"{crop_info.get('mode', 'Smart Follow')}: {len(clip_records)} {mode_word} Shorts created. "
                f"{passed} of {len(grades)} clips passed all quality checks."
                + (f" Vocal analysis unavailable ({vocal_error}); cuts unverified." if vocal is None else "")
            ),
        }
    finally:
        shutil.rmtree(temp_job, ignore_errors=True)
