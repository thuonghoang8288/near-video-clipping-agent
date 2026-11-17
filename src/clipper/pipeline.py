"""Pipeline: source -> transcript -> scored windows -> clips + report.

Everything runs locally (ffmpeg + faster-whisper). No paid API, no
network call except the optional first-time whisper model download.
"""
from __future__ import annotations

import json
import os
import time

from . import analyze, render, select
from .report import build_report
from .transcribe import save_transcript, transcribe


def run(source: str, out_dir: str, clip_count: int = 5,
        formats: tuple = ("vertical",), captions: bool = True,
        language: str | None = None, model: str = "tiny",
        min_s: float = select.MIN_WINDOW_S,
        max_s: float = select.MAX_WINDOW_S) -> dict:
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    timings: dict = {}

    # 1. Transcribe (word timestamps).
    t = time.time()
    transcript = transcribe(source, model=model, language=language)
    timings["transcribe_s"] = round(time.time() - t, 1)
    save_transcript(transcript, os.path.join(out_dir, "transcript.json"))

    # 2. Measured signals for the whole source.
    t = time.time()
    src_db = analyze.source_mean_volume_db(source)
    scenes = analyze.scene_changes(source)
    timings["signals_s"] = round(time.time() - t, 1)

    # 3. Score every candidate window, pick top-N non-overlapping.
    # Two passes: pass 1 scores without per-window volume (neutral 0.5)
    # so we only spend an ffmpeg call on the ~80 best candidates.
    candidates = select.candidate_windows(transcript.sentences, min_s, max_s)
    for w in candidates:
        dens = analyze.speech_density(w.start, w.end, transcript.words)
        sc = sum(1 for s in scenes if w.start <= s <= w.end)
        select.score_window(w, 0.5, dens, sc)
    shortlist = sorted(candidates, key=lambda x: -x.score)[:80]
    for w in shortlist:
        wdb = analyze.mean_volume_db(source, w.start, w.duration)
        dens = analyze.speech_density(w.start, w.end, transcript.words)
        sc = sum(1 for s in scenes if w.start <= s <= w.end)
        select.score_window(w, analyze.energy_ratio(wdb, src_db), dens, sc)
    picked = select.select_windows(shortlist, clip_count)
    timings["scoring_s"] = round(time.time() - t, 1)

    # 4. Render clips + SRTs + report.
    t = time.time()
    clips = []
    for i, w in enumerate(picked, 1):
        cues = render.caption_cues(transcript.words, w.start, w.end)
        srt = os.path.join(out_dir, f"clip{i}.srt")
        render.write_srt(cues, srt)
        files = []
        for fmt in formats:
            ass = None
            if captions:
                spec = render.FORMATS[fmt]
                ass = os.path.join(out_dir, f"clip{i}-{fmt}.ass")
                render.write_ass(cues, ass, spec["w"], spec["h"], spec["fontsize"])
            out = os.path.join(out_dir, f"clip{i}-{fmt}.mp4")
            files.append(render.render_clip(
                source, w.start, w.end, fmt, ass, out, captions=captions))
        clips.append({
            "index": i,
            "start": round(w.start, 2),
            "end": round(w.end, 2),
            "duration_s": round(w.duration, 2),
            "text": w.text,
            "score": w.score,
            "signals": w.signals,
            "files": files,
        })
    report = build_report(os.path.basename(source), transcript.duration,
                          transcript.language, [
                              {"window": w, "files": c["files"]}
                              for w, c in zip(picked, clips)
                          ], list(formats))
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(report)
    timings["render_s"] = round(time.time() - t, 1)

    manifest = {
        "source": os.path.basename(source),
        "source_duration_s": round(transcript.duration, 2),
        "language": transcript.language,
        "clip_count": len(clips),
        "formats": list(formats),
        "captions": captions,
        "model": model,
        "candidates_scored": len(candidates),
        "scene_changes": len(scenes),
        "source_mean_volume_db": src_db,
        "clips": clips,
        "timings_s": timings,
        "total_s": round(time.time() - t0, 1),
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return manifest
