"""Smart-crop analysis (YOLO + scene/colour heuristics) and ffmpeg rendering."""
from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from app.shorts.cutter.errors import CutterError
from app.shorts.cutter.framing import (
    FrameSample, apply_colour_fallback, assign_scene_ids, character_beats,
    fill_gaps_per_scene, group_targets, lead_room_offsets, scene_cut_times,
    solve_camera_path, solve_camera_path_hold, split_on_target_jumps,
    PREFERRED_LABELS,
)
from app.shorts.cutter.util import clamp, even, safe_name

# Analyse at a few samples per second, then let FFmpeg render every source frame.
ANALYSIS_FPS = 6.0

# Camera speed constants keyed by motion profile name.
CAMERA_SPEED_FRACS = {"locked": 0.0, "calm": 0.20, "follow": 0.35}
DEFAULT_CAMERA_MOTION = "calm"
MIN_BOX_AREA_RATIO = 0.002

_YOLO_MODEL = None
_YOLO_MODEL_NAME: str = ""
_YOLO_DEVICE: str = "cpu"
_YOLO_LOCK = threading.Lock()


@dataclass
class CropPoint:
    time: float
    x: int
    source: str


@dataclass
class VisualBeat:
    time: float
    kind: str
    label: str = ""
    strength: float = 0.0


def require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise CutterError("FFmpeg was not found. Install it (brew install ffmpeg) and restart Midas.")
    return ffmpeg


def pick_detection_setup() -> tuple[str, str]:
    """(model_name, device). YOLO11m on Apple GPU; YOLO11s on CPU."""
    try:
        import torch
        if torch.backends.mps.is_available():
            return "yolo11m.pt", "mps"
    except Exception:
        pass
    return "yolo11s.pt", "cpu"


def get_yolo_model():
    global _YOLO_MODEL, _YOLO_MODEL_NAME, _YOLO_DEVICE
    if _YOLO_MODEL is not None:
        return _YOLO_MODEL
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise CutterError("Smart Follow packages are missing. Run: python -m pip install -r requirements-stanza.txt") from exc
    with _YOLO_LOCK:
        if _YOLO_MODEL is None:
            try:
                model_name, device = pick_detection_setup()
                _YOLO_MODEL_NAME = model_name
                _YOLO_DEVICE = device
                _YOLO_MODEL = YOLO(model_name)
            except Exception as exc:
                raise CutterError(f"Could not load Smart Follow model. Connect to the internet for the first model download. Details: {exc}") from exc
    return _YOLO_MODEL


def source_metadata(source: Path) -> tuple[float, int, int]:
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise CutterError("OpenCV could not read this video.")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if width < 2 or height < 2:
            raise CutterError("This video has invalid dimensions.")
        return (count / fps if count else 0.0), width, height
    finally:
        cap.release()


def crop_geometry(width: int, height: int) -> tuple[int, int]:
    target_ratio = 9 / 16
    if width / height >= target_ratio:
        crop_height = even(height)
        crop_width = even(crop_height * target_ratio)
    else:
        crop_width = even(width)
        crop_height = even(crop_width / target_ratio)
    return min(crop_width, even(width)), min(crop_height, even(height))


def normalise_camera_motion(value: str | None) -> str:
    value = str(value or DEFAULT_CAMERA_MOTION).strip().lower()
    return value if value in CAMERA_SPEED_FRACS else DEFAULT_CAMERA_MOTION


def scene_histogram(frame: np.ndarray) -> np.ndarray:
    """Compact HSV signature used for detecting a hard visual scene change."""
    small = cv2.resize(frame, (160, 90))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])
    cv2.normalize(histogram, histogram)
    return histogram


def character_boxes(result, width: int, height: int) -> list[tuple]:
    """All character-labelled boxes: (x1, y1, x2, y2, label, track_id)."""
    if result.boxes is None or len(result.boxes) == 0:
        return []
    names = result.names
    boxes = result.boxes.xyxy.cpu().tolist()
    classes = result.boxes.cls.int().cpu().tolist()
    ids = (result.boxes.id.int().cpu().tolist()
           if getattr(result.boxes, "id", None) is not None else [None] * len(boxes))
    frame_area = float(width * height)
    output = []
    for box, class_id, track_id in zip(boxes, classes, ids):
        label = str(names.get(class_id, class_id)).lower()
        if label not in PREFERRED_LABELS:
            continue
        x1, y1, x2, y2 = box
        if max(0.0, (x2 - x1) * (y2 - y1)) / frame_area < MIN_BOX_AREA_RATIO:
            continue
        output.append((x1, y1, x2, y2, label, int(track_id) if track_id is not None else None))
    return output


LOGO_BAND_FRAC = 0.18  # channel logos/titles live in the top band of rhyme videos
COLOUR_BLOB_MIN_AREA_FRAC = 0.01
COLOUR_BLOB_DOMINANCE = 2.0
COLOUR_BLOB_EDGE_RATIO = 1.15  # subject regions carry more detail than walls


def colour_subject_x(frame: np.ndarray) -> float | None:
    """
    Class-agnostic fallback for object/animal characters YOLO cannot label
    (stars, moons, vegetables...). Cartoon subjects are typically the largest
    saturated-and-bright region. Returns the subject centre as a fraction of
    frame width, or None unless one blob clearly dominates — a wrong guess is
    worse than the centre default.
    """
    small = cv2.resize(frame, (320, 180))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).astype(np.float64)
    energy = (hsv[:, :, 1] / 255.0) * (hsv[:, :, 2] / 255.0)
    energy[: int(180 * LOGO_BAND_FRAC), :] = 0
    threshold = max(0.25, float(np.percentile(energy, 90)))
    mask = (energy >= threshold).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    def blob_score(contour) -> float:
        x, y, w, h = cv2.boundingRect(contour)
        return float(cv2.contourArea(contour)) * (0.5 + float(energy[y:y + h, x:x + w].mean()))

    scored = sorted((blob_score(c), index) for index, c in enumerate(contours))
    best_score, best_index = scored[-1]
    best = contours[best_index]
    if cv2.contourArea(best) < 180 * 320 * COLOUR_BLOB_MIN_AREA_FRAC:
        return None
    if len(scored) > 1 and best_score < COLOUR_BLOB_DOMINANCE * scored[-2][0]:
        return None
    x, y, w, h = cv2.boundingRect(best)
    # Saturation alone picks walls and furniture on detailed sets. A real
    # subject (character, star, coin) carries internal/outline detail; a flat
    # saturated wall does not — and a wrong guess is worse than the centre
    # default, which object close-ups in this catalogue are composed around.
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    detail = np.abs(cv2.Laplacian(gray, cv2.CV_64F))
    region_detail = float(detail[y:y + h, x:x + w].mean())
    frame_detail = float(detail.mean()) + 1e-6
    if region_detail < COLOUR_BLOB_EDGE_RATIO * frame_detail:
        return None
    return (x + w / 2) / 320


def analyse_smart_crop(source: Path, camera_motion: str = DEFAULT_CAMERA_MOTION):
    camera_motion = normalise_camera_motion(camera_motion)
    model = get_yolo_model()
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise CutterError("OpenCV could not read this video.")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = count / fps if count else 0.0
        crop_width, crop_height = crop_geometry(width, height)
        crop_y = even((height - crop_height) / 2)
        max_x = max(0, width - crop_width)
        step = max(1, int(round(fps / ANALYSIS_FPS)))

        times: list[float] = []
        distances: list[float] = []
        detections: list[list[tuple]] = []
        colour_xs: list[float | None] = []
        previous_hist = None
        frame_number = 0

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            timestamp = frame_number / fps
            hist = scene_histogram(frame)
            distance = (float(cv2.compareHist(previous_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
                        if previous_hist is not None else 0.0)
            previous_hist = hist
            try:
                result = model.track(frame, persist=True, verbose=False,
                                     imgsz=640, conf=0.25, device=_YOLO_DEVICE)[0]
                boxes = character_boxes(result, width, height)
            except Exception:
                boxes = []
            times.append(timestamp)
            distances.append(distance)
            detections.append(boxes)
            colour_xs.append(colour_subject_x(frame) if not boxes else None)
            for _ in range(step - 1):
                if not cap.grab():
                    break
            frame_number += step
    finally:
        cap.release()

    if not times:
        times, distances, detections, colour_xs = [0.0], [0.0], [[]], [None]

    cuts = scene_cut_times(times, distances)
    scene_ids = assign_scene_ids(times, cuts)
    samples = [
        FrameSample(t, [b[:4] for b in boxes], [b[4] for b in boxes],
                    [b[5] for b in boxes], scene)
        for t, boxes, scene in zip(times, detections, scene_ids)
    ]
    targets = group_targets(samples, crop_width, width)
    targets = apply_colour_fallback(targets, colour_xs, width)
    filled = fill_gaps_per_scene(targets, scene_ids, width)
    # Undetected jump cuts / character switches become virtual scene cuts so
    # the camera snaps instead of dragging across the frame.
    camera_scene_ids = split_on_target_jumps(times, filled, scene_ids, crop_width)
    offsets = lead_room_offsets(times, filled, camera_scene_ids, crop_width)
    if camera_motion == "follow":
        path = solve_camera_path(times, filled, camera_scene_ids, crop_width, max_x,
                                 max_speed_frac=CAMERA_SPEED_FRACS[camera_motion])
    else:
        # Editor-style default: hold a composed frame, snap on cuts/relocations.
        path = solve_camera_path_hold(
            times, filled, camera_scene_ids, crop_width, max_x,
            max_speed_frac=max(0.12, CAMERA_SPEED_FRACS[camera_motion]),
            lead_offsets=offsets)
    points = [CropPoint(t, x, "plan") for t, x in path]

    char_beats = [VisualBeat(t, "character", label, 1.0) for t, label in character_beats(targets)]
    scene_beats = [VisualBeat(t, "scene", "scene change", 1.0) for t in cuts]

    metadata = {
        "model": _YOLO_MODEL_NAME,
        "analysis_fps": ANALYSIS_FPS,
        "source_fps": fps,
        "source_size": [width, height],
        "crop_size": [crop_width, crop_height],
        "duration_seconds": duration,
        "camera_motion": camera_motion,
        "scene_cut_times": cuts,
        "sample_times": times,
        "sample_targets": filled,
        "camera_xs": [x for _t, x in path],
        "intended_offsets": offsets,
        "visual_beats": [asdict(b) for b in sorted(char_beats + scene_beats, key=lambda b: b.time)],
        "detected_samples": sum(1 for d in detections if d),
        "character_beats": len(char_beats),
        "scene_beats": len(scene_beats),
    }
    return points, crop_width, crop_height, crop_y, duration, metadata


def ffmpeg_filter_path(path: Path) -> str:
    return path.resolve().as_posix().replace(":", r"\:")


def run_ffmpeg(command: list[str]) -> None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise CutterError(f"Could not start FFmpeg: {exc}") from exc
    if result.returncode != 0:
        info = (result.stderr or result.stdout or "Unknown FFmpeg error")[-3500:]
        raise CutterError(f"FFmpeg could not process this video.\n\n{info}")


def write_crop_commands(points: list[CropPoint], duration: float, path: Path) -> None:
    lines = []
    for index, point in enumerate(points):
        if index + 1 < len(points):
            nxt = points[index + 1]
            seg_end = max(nxt.time, point.time + 0.05)
            seg_length = max(0.05, seg_end - point.time)
            expression = f"{point.x}+({nxt.x - point.x})*(t-{point.time:.3f})/{seg_length:.3f}"
        else:
            expression = str(point.x)
        lines.append(f"{point.time:.3f} crop@smart x {expression};")
    if points and duration > points[-1].time + 0.01:
        lines.append(f"{duration:.3f} crop@smart x {points[-1].x};")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_vertical(
    source: Path,
    destination: Path,
    smart: bool,
    job_folder: Path,
    camera_motion: str = DEFAULT_CAMERA_MOTION,
) -> dict:
    ffmpeg = require_ffmpeg()
    if not smart:
        command = [
            ffmpeg, "-hide_banner", "-y", "-i", str(source),
            "-vf", "scale=-2:1920,crop=1080:1920:(iw-1080)/2:0,setsar=1",
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(destination),
        ]
        run_ffmpeg(command)
        return {"mode": "Centre Crop"}

    points, crop_width, crop_height, crop_y, duration, metadata = analyse_smart_crop(
        source,
        camera_motion,
    )
    commands_path = job_folder / "crop_commands.txt"
    filter_path = job_folder / "smart_filter.txt"
    write_crop_commands(points, duration, commands_path)

    graph = (
        f"[0:v]sendcmd=f='{ffmpeg_filter_path(commands_path)}',"
        f"crop@smart=w={crop_width}:h={crop_height}:x={points[0].x}:y={crop_y},"
        f"scale=1080:1920:flags=lanczos,setsar=1[v]"
    )
    filter_path.write_text(graph + "\n", encoding="utf-8")
    command = [
        ffmpeg, "-hide_banner", "-y", "-i", str(source),
        "-filter_complex_script", str(filter_path),
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(destination),
    ]
    run_ffmpeg(command)
    metadata["mode"] = f"Smart Follow ({normalise_camera_motion(camera_motion)})"
    return metadata


def export_clip(master: Path, destination: Path, start: float, end: float) -> None:
    ffmpeg = require_ffmpeg()
    length = max(0.1, end - start)
    fade = min(0.15, length / 4)
    command = [ffmpeg, "-hide_banner", "-y", "-ss", f"{start:.3f}", "-i", str(master),
               "-t", f"{length:.3f}", "-map", "0:v:0", "-map", "0:a?",
               "-af", f"afade=t=in:st=0:d={fade:.3f},"
                      f"afade=t=out:st={max(0.0, length - fade):.3f}:d={fade:.3f}",
               "-c:v", "libx264", "-preset", "medium", "-crf", "18",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
               str(destination)]
    run_ffmpeg(command)
