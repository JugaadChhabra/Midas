from pathlib import Path
import pytest
from app.services.nas_service import NASService


def _svc(tmp_path):
    svc = NASService()
    svc.mode = "local"
    svc.local_root = Path(tmp_path)
    return svc


def test_list_video_files_filters_and_sorts(tmp_path):
    d = tmp_path / "HINDI"
    d.mkdir()
    (d / "b.mp4").write_bytes(b"x")
    (d / "a.mov").write_bytes(b"x")
    (d / "notes.txt").write_bytes(b"x")
    (d / ".DS_Store").write_bytes(b"x")
    svc = _svc(tmp_path)
    assert svc.list_video_files("HINDI") == ["a.mov", "b.mp4"]


def test_list_video_files_missing_dir_returns_empty(tmp_path):
    assert _svc(tmp_path).list_video_files("NOPE") == []


def test_copy_to_local_streams_bytes(tmp_path):
    (tmp_path / "HINDI").mkdir()
    (tmp_path / "HINDI" / "song.mp4").write_bytes(b"video-bytes")
    svc = _svc(tmp_path)
    dest = tmp_path / "work" / "song.mp4"
    out = svc.copy_to_local("HINDI/song.mp4", dest)
    assert out == dest
    assert dest.read_bytes() == b"video-bytes"


def test_copy_from_local_creates_dirs_and_writes(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"clip-bytes")
    svc = _svc(tmp_path)
    svc.copy_from_local(src, "COMPLETED/HINDI/clip.mp4")
    assert (tmp_path / "COMPLETED" / "HINDI" / "clip.mp4").read_bytes() == b"clip-bytes"


def test_move_relocates_file_and_creates_dest_dir(tmp_path):
    (tmp_path / "RHYMES" / "HINDI").mkdir(parents=True)
    (tmp_path / "RHYMES" / "HINDI" / "song.mp4").write_bytes(b"v")
    svc = _svc(tmp_path)
    svc.move("RHYMES/HINDI/song.mp4", "COMPLETED/HINDI/song.mp4")
    assert not (tmp_path / "RHYMES" / "HINDI" / "song.mp4").exists()
    assert (tmp_path / "COMPLETED" / "HINDI" / "song.mp4").read_bytes() == b"v"
