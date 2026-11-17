"""Measured audio/video signals via ffmpeg — no guessing.

- mean volume per window: `volumedetect` on the window's audio slice.
- speech density: fraction of the window covered by transcript words.
- scene changes: `scdet` over the whole source, timestamps parsed out.
"""
from __future__ import annotations

import re
import subprocess

VOLUME_RE = re.compile(r"mean_volume:\s*(-?[\d.]+)\s*dB")
SCENE_RE = re.compile(r"pts_time:([\d.]+)\s+.*lavfi\.scd\.score:\s*([\d.]+)")


def _run(cmd: list, timeout: int = 120) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return out.stderr + out.stdout


def mean_volume_db(path: str, start: float, duration: float) -> float | None:
    """Mean volume (dBFS) of one audio slice, or None if unmeasurable."""
    log = _run([
        "ffmpeg", "-v", "info", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-i", path, "-af", "volumedetect", "-vn", "-sn", "-dn",
        "-f", "null", "-",
    ])
    m = VOLUME_RE.search(log)
    return float(m.group(1)) if m else None


def source_mean_volume_db(path: str) -> float | None:
    log = _run([
        "ffmpeg", "-v", "info", "-i", path,
        "-af", "volumedetect", "-vn", "-sn", "-dn", "-f", "null", "-",
    ], timeout=600)
    m = VOLUME_RE.search(log)
    return float(m.group(1)) if m else None


def scene_changes(path: str, threshold: float = 0.4) -> list:
    """Timestamps (seconds) where scdet reports a scene cut."""
    log = _run([
        "ffmpeg", "-v", "info", "-i", path,
        "-vf", f"fps=2,select='gt(scene,{threshold})',showinfo",
        "-vsync", "vfr", "-f", "null", "-",
    ], timeout=600)
    times = []
    for m in SCENE_RE.finditer(log):
        if float(m.group(2)) > threshold:
            times.append(float(m.group(1)))
    return times


def speech_density(window_start: float, window_end: float, words: list) -> float:
    """Fraction of the window covered by spoken words."""
    span = window_end - window_start
    if span <= 0:
        return 0.0
    covered = 0.0
    for w in words:
        lo, hi = max(w.start, window_start), min(w.end, window_end)
        if hi > lo:
            covered += hi - lo
    return max(0.0, min(1.0, covered / span))


def energy_ratio(window_db: float | None, source_db: float | None) -> float:
    """Window loudness relative to the source, mapped to 0..1.

    dBFS is logarithmic: +6 dB is roughly twice as loud. A window 6 dB
    above the source mean scores 1.0; 6 dB below scores 0.0.
    """
    if window_db is None or source_db is None:
        return 0.5
    return max(0.0, min(1.0, 0.5 + (window_db - source_db) / 12.0))
