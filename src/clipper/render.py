"""Render clips with ffmpeg: reframe + burned-in captions + SRT sidecar.

Formats (all 1080p, H.264/AAC):
- vertical   1080x1920 (9:16)  — Shorts / TikTok / Reels
- square     1080x1080 (1:1)   — feeds
- landscape  1920x1080 (16:9)  — YouTube / X

Captions are burned in with libass `subtitles`, bottom-centred, large,
from word timestamps grouped into short cues (max ~42 chars / line).
"""
from __future__ import annotations

import os
import subprocess

FONT = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"

FORMATS = {
    "vertical": {"w": 1080, "h": 1920, "ratio": "9:16", "fontsize": 64},
    "square": {"w": 1080, "h": 1080, "ratio": "1:1", "fontsize": 56},
    "landscape": {"w": 1920, "h": 1080, "ratio": "16:9", "fontsize": 48},
}

MAX_CUE_CHARS = 42


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def caption_cues(words: list, start: float, end: float) -> list:
    """Group words inside [start, end] into caption cues of <=2 lines.

    Each cue is (cue_start, cue_end, text) with times relative to the
    clip start, so the SRT lines up with the cut clip.
    """
    inside = [w for w in words if w.end > start and w.start < end]
    cues: list = []
    cur: list = []
    cur_len = 0
    for w in inside:
        if cur and cur_len + len(w.text) + 1 > MAX_CUE_CHARS:
            cues.append(_cue_from_words(cur, start))
            cur, cur_len = [], 0
        cur.append(w)
        cur_len += len(w.text) + 1
    if cur:
        cues.append(_cue_from_words(cur, start))
    return cues


def _cue_from_words(words: list, clip_start: float) -> tuple:
    text = " ".join(w.text for w in words)
    return (max(0.0, words[0].start - clip_start),
            max(0.0, words[-1].end - clip_start), text)


def write_srt(cues: list, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for i, (s, e, text) in enumerate(cues, 1):
            fh.write(f"{i}\n{_srt_time(s)} --> {_srt_time(e)}\n{text}\n\n")


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(cues: list, path: str, width: int, height: int, fontsize: int) -> None:
    """Write an .ass subtitle file with explicit PlayRes = output size.

    (The `subtitles` filter auto-converts SRT to ASS with a 384x288
    play resolution, which scales FontSize up ~2.8x on 1080p output —
    captions came out enormous. Writing ASS directly gives exact pixels.)
    """
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Noto Sans,{fontsize},&H00FFFFFF,&H000000FF,"
        "&H80000000,&H00000000,1,0,0,0,100,100,0,0,1,3,1,2,10,10,90,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header)
        for s, e, text in cues:
            fh.write(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Default,,0,0,0,,{text}\n")


def _crop_filter(fmt: str) -> str:
    """Center-crop to the target aspect ratio, then scale to 1080p.

    NOTE: commas inside min()/max() must be quoted — ffmpeg splits
    filter arguments on unquoted commas.
    """
    spec = FORMATS[fmt]
    if fmt == "vertical":
        crop = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0"
    elif fmt == "square":
        crop = ("crop='min(iw,ih)':'min(iw,ih)':"
                "'(iw-min(iw,ih))/2':'(ih-min(iw,ih))/2'")
    else:
        crop = "crop=iw:iw*9/16:0:(ih-iw*9/16)/2"
    return f"{crop},scale={spec['w']}:{spec['h']}:flags=lanczos"


def render_clip(source: str, start: float, end: float, fmt: str,
                ass_path: str | None, out_path: str,
                captions: bool = True) -> dict:
    """Cut one clip, reframe, optionally burn captions. Returns file stats.

    Captions come from a pre-written .ass file (exact pixel sizing —
    see write_ass); ass_path may be None when captions are off.
    """
    dur = end - start
    vf = _crop_filter(fmt)
    if captions and ass_path and os.path.exists(ass_path):
        esc = ass_path.replace(":", r"\:").replace("'", r"\'")
        vf += f",ass='{esc}'"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", source,
        "-vf", vf, "-af", "aresample=async=1",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        out_path,
    ]
    subprocess.run(cmd, check=True, timeout=600)
    size = os.path.getsize(out_path)
    return {"path": out_path, "bytes": size, "duration_s": round(dur, 2),
            "format": fmt}
