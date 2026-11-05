"""
settings.py - persistent, validated user settings.

* Every value is type-checked and range-clamped on load, so a hand-edited or corrupt file can never
  crash the game or put it in a broken state: bad entries silently fall back to the default.
* Writes are atomic (temp file + rename) so a crash mid-save cannot corrupt the file.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict

QUALITIES = ["classic", "balanced", "premium", "ultra"]

QUALITY_PROFILES: Dict[str, Dict[str, Any]] = {
    # premium=False -> the original fixed-function pipeline (what the syllabus labs use)
    "classic":  {"premium": False, "scale": 1.0,  "bloom_levels": 0, "msaa": 4},
    "balanced": {"premium": True,  "scale": 0.85, "bloom_levels": 3, "msaa": 0},
    "premium":  {"premium": True,  "scale": 1.0,  "bloom_levels": 4, "msaa": 0},
    "ultra":    {"premium": True,  "scale": 1.5,  "bloom_levels": 4, "msaa": 0},
}

DEFAULTS: Dict[str, Any] = {
    "quality": "premium",
    "bloom": 0.85,           # bloom strength
    "film_grain": True,
    "motion_fx": True,       # False = reduced motion (no aberration / radial blur / speed lines / shake)
    "fov": 68.0,             # base field of view, degrees
    "master_vol": 0.85,
    "music_vol": 0.60,
    "sfx_vol": 0.90,
    "colorblind": False,     # colour-name labels on gates + names in the HUD
    "show_fps": False,
    "fullscreen": False,
    "rumble": True,
    "steer_sens": 1.0,
}

RANGES = {
    "bloom": (0.0, 1.6), "fov": (55.0, 95.0), "master_vol": (0.0, 1.0), "music_vol": (0.0, 1.0),
    "sfx_vol": (0.0, 1.0), "steer_sens": (0.6, 1.5),
}


def sanitize(key: str, value: Any) -> Any:
    """Return a valid value for key (the default if value is unusable)."""
    default = DEFAULTS[key]
    if key == "quality":
        return value if value in QUALITIES else default
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:   # NaN check
            return default
        lo, hi = RANGES[key]
        return float(min(hi, max(lo, value)))
    return default


class Settings:
    def __init__(self, path: str | None = None):
        self.path = path
        self.d: Dict[str, Any] = dict(DEFAULTS)
        if path:
            self.load()

    # dict-like access with validation on write
    def __getitem__(self, key: str) -> Any:
        return self.d[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        self.d[key] = sanitize(key, value)

    def profile(self) -> Dict[str, Any]:
        return QUALITY_PROFILES[self.d["quality"]]

    def reset(self) -> None:
        self.d = dict(DEFAULTS)

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if not isinstance(raw, dict):
                return
        except (OSError, ValueError):
            return
        for key in DEFAULTS:
            if key in raw:
                self.d[key] = sanitize(key, raw[key])

    def save(self) -> bool:
        if not self.path:
            return False
        try:
            folder = os.path.dirname(os.path.abspath(self.path))
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".settings-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.d, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False
