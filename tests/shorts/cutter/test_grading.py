import numpy as np
import pytest

from app.shorts.cutter.cutplan import Stanza
from app.shorts.cutter.grading import grade_clips


def make_vocal(duration, quiet_at=(), hop=0.05):
    env = np.full(int(duration / hop), 1.0)
    for t in quiet_at:
        idx = int(t / hop)
        env[max(0, idx - 4):idx + 4] = 0.0
    return {"envelope": env, "hop": hop, "threshold": 0.1, "windows": []}


def centered_camera(times, target, crop_width):
    return [int(target - crop_width / 2)] * len(times)


def test_pass_when_cuts_silent_and_framing_centered():
    times = [i / 6 for i in range(180)]  # 30s
    targets = [800.0] * 180
    cams = centered_camera(times, 800.0, 500)
    stanzas = [Stanza(0.0, 15.0, "a", "pause"), Stanza(15.0, 30.0, "b", "end")]
    grades = grade_clips(stanzas, make_vocal(30.0, quiet_at=[15.0]), times, targets, cams, 500)
    assert [g["verdict"] for g in grades] == ["PASS", "PASS"]
    assert grades[0]["framing_score"] == pytest.approx(1.0)


def test_check_when_boundary_forced():
    # Quiet at the cut point so vocal loudness is not the trigger;
    # boundary="forced" alone must be enough to flip the verdict to CHECK.
    times = [i / 6 for i in range(180)]
    targets = [800.0] * 180
    cams = centered_camera(times, 800.0, 500)
    stanzas = [Stanza(0.0, 15.0, "a", "forced"), Stanza(15.0, 30.0, "b", "end")]
    grades = grade_clips(stanzas, make_vocal(30.0, quiet_at=[15.0]), times, targets, cams, 500)
    assert grades[0]["verdict"] == "CHECK"
    assert any("forced" in r for r in grades[0]["reasons"])


def test_check_when_cut_is_loud():
    # Boundary="pause" so the forced-cut path is not triggered;
    # all-loud envelope at the cut makes cut_end_ok False for the first clip.
    times = [i / 6 for i in range(180)]
    targets = [800.0] * 180
    cams = centered_camera(times, 800.0, 500)
    stanzas = [Stanza(0.0, 15.0, "a", "pause"), Stanza(15.0, 30.0, "b", "end")]
    grades = grade_clips(stanzas, make_vocal(30.0), times, targets, cams, 500)
    assert grades[0]["verdict"] == "CHECK"
    assert grades[0]["cut_end_ok"] is False
    assert any("vocal" in r for r in grades[0]["reasons"])


def test_check_when_framing_off_center():
    times = [i / 6 for i in range(90)]
    targets = [800.0] * 90
    cams = [0] * 90  # camera stuck at left edge; subject at 800 far off-center
    stanzas = [Stanza(0.0, 15.0, "a", "pause")]
    grades = grade_clips(stanzas, make_vocal(15.0, quiet_at=[15.0]), times, targets, cams, 500)
    assert grades[0]["verdict"] == "CHECK"
    assert grades[0]["framing_score"] == pytest.approx(0.0)


def test_unverified_when_no_vocal_or_framing_data():
    stanzas = [Stanza(0.0, 15.0, "a", "balanced")]
    [grade] = grade_clips(stanzas, None, None, None, None, None)
    assert grade["verdict"] == "CHECK"
    assert grade["cut_start_ok"] is None and grade["framing_score"] is None
    assert any("unverified" in r for r in grade["reasons"])


def test_short_pause_boundary_is_flagged():
    times = [i / 6 for i in range(90)]
    targets = [800.0] * 90
    cams = [int(800 - 250)] * 90
    stanzas = [Stanza(0.0, 15.0, "a", "short-pause")]
    [g] = grade_clips(stanzas, make_vocal(15.0, quiet_at=[15.0]), times, targets, cams, 500)
    assert g["verdict"] == "CHECK"
    assert any("short" in r for r in g["reasons"])
