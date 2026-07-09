import numpy as np
import pytest

from app.shorts.cutter.render import colour_subject_x
from app.shorts.cutter.framing import TargetPoint, apply_colour_fallback


def frame_with_rects(rects, size=(360, 640)):
    """Dark frame with saturated BGR rectangles: (x, y, w, h, colour)."""
    frame = np.full((size[0], size[1], 3), 20, dtype=np.uint8)
    for x, y, w, h, colour in rects:
        frame[y:y + h, x:x + w] = colour
    return frame


def test_colour_subject_found_for_dominant_blob():
    frame = frame_with_rects([(400, 150, 120, 120, (0, 200, 255))])  # big yellow blob
    fx = colour_subject_x(frame)
    assert fx is not None
    assert fx == pytest.approx((400 + 60) / 640, abs=0.03)


def test_colour_subject_none_when_two_similar_blobs():
    frame = frame_with_rects([
        (80, 150, 100, 100, (0, 200, 255)),
        (460, 150, 100, 100, (255, 100, 0)),
    ])
    assert colour_subject_x(frame) is None, "no dominant subject -> no guess"


def test_colour_subject_ignores_top_logo_band():
    frame = frame_with_rects([(0, 0, 200, 40, (0, 0, 255))])  # logo strip only
    assert colour_subject_x(frame) is None


def test_colour_subject_none_on_flat_frame():
    assert colour_subject_x(np.full((360, 640, 3), 30, dtype=np.uint8)) is None


def test_apply_colour_fallback_fills_only_undetected():
    targets = [
        TargetPoint(0.0, 500.0, "primary", "person#1", "person"),
        TargetPoint(0.25, None, "none", None, ""),
        TargetPoint(0.5, None, "none", None, ""),
    ]
    out = apply_colour_fallback(targets, [None, 0.75, None], frame_width=1920)
    assert out[0].x == 500.0 and out[0].mode == "primary"
    assert out[1].x == pytest.approx(0.75 * 1920) and out[1].mode == "colour"
    assert out[2].x is None and out[2].mode == "none"


def test_flat_saturated_wall_rejected_on_detailed_frame():
    # A detailed scene (textured content everywhere) where the most saturated
    # region is a featureless wall: the blob must NOT win — centre default is
    # better than framing a wall (the fan/coin/earth failure of 2026-07-08).
    rng = np.random.default_rng(7)
    frame = rng.integers(60, 160, (360, 640, 3)).astype(np.uint8)  # detail
    frame[:, 480:] = (40, 160, 200)  # flat saturated wall strip on the right
    assert colour_subject_x(frame) is None
