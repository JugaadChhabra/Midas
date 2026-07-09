from __future__ import annotations

import re
from pathlib import Path


def safe_name(value: str, fallback: str = "video") -> str:
    value = Path(value).stem
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return value[:80] or fallback


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def even(value: float) -> int:
    return max(2, int(round(value / 2) * 2))
