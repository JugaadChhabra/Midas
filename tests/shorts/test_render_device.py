import sys
import types
from unittest.mock import patch


def _fake_torch(cuda=False, mps=False):
    t = types.ModuleType("torch")
    t.cuda = types.SimpleNamespace(is_available=lambda: cuda)
    t.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: mps))
    return t


def test_pick_detection_prefers_cuda():
    from app.shorts.cutter.render import pick_detection_setup
    with patch.dict(sys.modules, {"torch": _fake_torch(cuda=True, mps=True)}):
        assert pick_detection_setup() == ("yolo11m.pt", "cuda")


def test_pick_detection_falls_back_to_mps():
    from app.shorts.cutter.render import pick_detection_setup
    with patch.dict(sys.modules, {"torch": _fake_torch(cuda=False, mps=True)}):
        assert pick_detection_setup() == ("yolo11m.pt", "mps")


def test_pick_detection_falls_back_to_cpu():
    from app.shorts.cutter.render import pick_detection_setup
    with patch.dict(sys.modules, {"torch": _fake_torch(cuda=False, mps=False)}):
        assert pick_detection_setup() == ("yolo11s.pt", "cpu")
