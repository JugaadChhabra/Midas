from unittest.mock import MagicMock, patch
import pytest


def _sb_with_jobs(existing_jobs, insert_recorder):
    sb = MagicMock()

    def table(name):
        t = MagicMock()
        t.select.return_value.in_.return_value.execute.return_value.data = existing_jobs
        def _insert(fields):
            insert_recorder.append(fields)
            i = MagicMock()
            i.execute.return_value.data = [{"id": len(insert_recorder), **fields}]
            return i
        t.insert.side_effect = _insert
        return t

    sb.table.side_effect = table
    return sb


def test_enqueue_rejects_unknown_language():
    from app.shorts import nas_source
    with patch.object(nas_source, "list_source_languages", return_value=["HINDI"]):
        with pytest.raises(ValueError):
            nas_source.enqueue_language_jobs("KLINGON")


def test_enqueue_skips_in_flight_and_capped_files():
    from app.shorts import nas_source
    files = ["a.mp4", "b.mp4", "c.mp4", "d.mp4"]
    existing = [
        {"source_nas_path": "HINDI/b.mp4", "status": "DOWNLOADING"},   # in-flight -> skip
        {"source_nas_path": "HINDI/c.mp4", "status": "FAILED"},
        {"source_nas_path": "HINDI/c.mp4", "status": "FAILED"},
        {"source_nas_path": "HINDI/c.mp4", "status": "FAILED"},        # 3 fails -> skip
    ]
    recorder = []
    with patch.object(nas_source, "list_source_languages", return_value=["HINDI"]), \
         patch.object(nas_source.nas_service, "list_video_files", return_value=files), \
         patch.object(nas_source, "supabase", return_value=_sb_with_jobs(existing, recorder)):
        n = nas_source.enqueue_language_jobs("HINDI")
    assert n == 2                                   # a.mp4 and d.mp4 only
    paths = sorted(r["source_nas_path"] for r in recorder)
    assert paths == ["HINDI/a.mp4", "HINDI/d.mp4"]
    assert all(r["status"] == "CREATED" and r["language"] == "HINDI" for r in recorder)


def test_enqueue_respects_limit():
    from app.shorts import nas_source
    recorder = []
    with patch.object(nas_source, "list_source_languages", return_value=["HINDI"]), \
         patch.object(nas_source.nas_service, "list_video_files", return_value=["a.mp4", "b.mp4", "c.mp4"]), \
         patch.object(nas_source, "supabase", return_value=_sb_with_jobs([], recorder)):
        n = nas_source.enqueue_language_jobs("HINDI", limit=2)
    assert n == 2
    assert len(recorder) == 2
