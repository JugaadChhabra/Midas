from pathlib import Path

from app.shorts.cutter.cutplan import Stanza


def test_cut_video_returns_clip_records(tmp_path, monkeypatch):
    import app.shorts.cutter.pipeline as pipeline

    source = tmp_path / "source.mkv"
    source.write_bytes(b"fake")

    def fake_render_vertical(src, master, smart, temp_dir, camera_motion):
        Path(master).write_bytes(b"master")
        return {"mode": "Smart Follow", "scene_cut_times": [], "sample_times": [],
                "sample_targets": [], "camera_xs": [], "crop_size": [None],
                "visual_beats": [], "intended_offsets": []}

    monkeypatch.setattr(pipeline, "render_vertical", fake_render_vertical)
    monkeypatch.setattr(pipeline, "source_metadata", lambda s: (30.0, 1920, 1080))
    monkeypatch.setattr(pipeline, "vocal_silence_analysis", lambda s, t: (_ for _ in ()).throw(RuntimeError("no demucs in test")))
    monkeypatch.setattr(pipeline, "transcribe_multilingual",
                        lambda src, dur, windows, language=None: ("en", 0.9, [], []))
    monkeypatch.setattr(pipeline, "full_coverage_stanzas",
                        lambda *a, **k: [Stanza(start=0.0, end=10.0, text="a"),
                                         Stanza(start=10.0, end=20.0, text="b")])
    monkeypatch.setattr(pipeline, "grade_clips", lambda *a, **k: [
        {"verdict": "PASS", "reasons": []}, {"verdict": "PASS", "reasons": []}])
    monkeypatch.setattr(pipeline, "save_transcript", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "export_clip",
                        lambda master, dest, start, end: Path(dest).write_bytes(b"clip"))

    stages = []
    result = pipeline.cut_video(source, tmp_path / "job", "My_Video",
                                progress=lambda stage, pct: stages.append((stage, pct)))

    assert len(result["clips"]) == 2
    first = result["clips"][0]
    assert first["rank"] == 1 and first["start_s"] == 0.0 and first["end_s"] == 10.0
    assert Path(first["path"]).is_file()
    assert result["language"] == "en"
    assert result["clips"][0]["verdict"] == "PASS"
    assert result["clips"][1]["verdict"] == "PASS"
    assert not (tmp_path / "job" / "tmp").exists()       # scratch cleaned up
    assert any("render" in s for s, _ in stages)         # progress reported
