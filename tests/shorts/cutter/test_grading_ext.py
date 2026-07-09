from app.shorts.cutter.cutplan import Stanza
from app.shorts.cutter.grading import grade_clips


def test_lead_room_offset_is_not_a_framing_miss():
    stanza = Stanza(0.0, 10.0, "x", "downbeat+downbeat")
    times = [i * 0.5 for i in range(20)]
    targets = [460.0] * 20            # subject deliberately left of centre
    camera_xs = [300] * 20            # crop 400 → centre 500; offset +40 → 460
    offsets = [40.0] * 20
    with_offset = grade_clips([stanza], None, times, targets, camera_xs, 400,
                              intended_offsets=offsets)
    without = grade_clips([stanza], None, times, targets, camera_xs, 400)
    assert with_offset[0]["framing_score"] == 1.0
    assert without[0]["framing_score"] == 1.0  # 40px is inside the 50px band anyway

    targets_far = [420.0] * 20        # 80px off centre: outside band...
    offsets_far = [80.0] * 20         # ...but exactly the intended lead room
    graded = grade_clips([Stanza(0, 10, "x", "d+d")], None, times, targets_far,
                         camera_xs, 400, intended_offsets=offsets_far)
    assert graded[0]["framing_score"] == 1.0


def test_selection_info_lands_in_grade():
    stanza = Stanza(0.0, 10.0, "x", "downbeat+decay")
    info = [{"score": 0.72, "is_chorus": True, "components": {"chorus": 1.0}}]
    grades = grade_clips([stanza], None, None, None, None, None,
                         selection_info=info)
    assert grades[0]["selection"]["is_chorus"] is True
    assert grades[0]["boundary"] == "downbeat+decay"
