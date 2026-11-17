"""report.md — one plain-English reason per clip, with measured signals."""
from __future__ import annotations

from .select import reason_text


def _clock(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_report(source_name: str, source_duration: float, language: str,
                 clips: list, formats: list) -> str:
    lines = [
        f"# Video Clipping Report — {source_name}",
        "",
        f"Source duration: {_clock(source_duration)} ({source_duration:.1f}s) · "
        f"language: {language} · clips: {len(clips)} · formats: {', '.join(formats)}",
        "",
        "Clips are cut on sentence boundaries from the transcript. "
        "Each reason names a measured signal; no retention or virality "
        "data was used because the source does not expose any.",
        "",
    ]
    for i, clip in enumerate(clips, 1):
        w = clip["window"]
        lines += [
            f"## Clip {i} — {_clock(w.start)} to {_clock(w.end)} "
            f"({w.duration:.0f}s) · {', '.join(formats)}",
            "",
            f"**Spoken text:** {w.text}",
            "",
            f"**Why this moment:** {reason_text(w)}",
            "",
            "**Signals:** " + ", ".join(
                f"{k}={v}" for k, v in w.signals.items()
            ) + f" · score={w.score:.3f}",
            "",
            "**Files:** " + ", ".join(
                f"`{f['path'].split('/')[-1]}` ({f['bytes'] // 1024} KB)"
                for f in clip["files"]
            ),
            "",
        ]
    return "\n".join(lines)
