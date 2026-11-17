"""Clip-window scoring and selection.

Rules (mirrors the market's public Video Clipping Agent listings):
- windows are 18-45s, non-overlapping, and always start/end on sentence
  boundaries (cuts come from the transcript, not from the picture);
- every chosen window carries a stated, measured reason (keyword density,
  question/number hooks, audio energy, speech density, scene changes);
- no retention/virality claim is made when the source exposes none.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MIN_WINDOW_S = 18.0
MAX_WINDOW_S = 45.0
IDEAL_MIN_S = 25.0
IDEAL_MAX_S = 40.0

HOOK_WORDS = {
    "how", "why", "what", "when", "where", "which", "who",
    "secret", "never", "always", "best", "worst", "mistake", "mistakes",
    "free", "new", "first", "stop", "start", "exactly", "really",
    "actually", "important", "amazing", "incredible", "simple", "easy",
    "truth", "lie", "lies", "nobody", "everyone", "everybody",
}
NUMBER_RE = re.compile(r"\d")


@dataclass
class Window:
    start: float
    end: float
    sentences: list
    score: float = 0.0
    signals: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)


def _keyword_score(text: str) -> float:
    lowered = text.lower()
    words = re.findall(r"[a-z']+", lowered)
    if not words:
        return 0.0
    hits = sum(1 for w in words if w in HOOK_WORDS)
    hits += len(NUMBER_RE.findall(text))  # concrete numbers are hooks
    hits += text.count("?") * 2  # questions are strong hooks
    return min(1.0, hits / max(4.0, len(words) * 0.12))


def _length_fit(duration: float) -> float:
    if duration < MIN_WINDOW_S or duration > MAX_WINDOW_S:
        return 0.0
    if IDEAL_MIN_S <= duration <= IDEAL_MAX_S:
        return 1.0
    if duration < IDEAL_MIN_S:
        return (duration - MIN_WINDOW_S) / (IDEAL_MIN_S - MIN_WINDOW_S)
    return (MAX_WINDOW_S - duration) / (MAX_WINDOW_S - IDEAL_MAX_S)


def candidate_windows(sentences: list, min_s: float = MIN_WINDOW_S,
                      max_s: float = MAX_WINDOW_S) -> list:
    """All windows of consecutive sentences within [min_s, max_s]."""
    out: list = []
    n = len(sentences)
    for i in range(n):
        for j in range(i, n):
            start = sentences[i].start
            end = sentences[j].end
            dur = end - start
            if dur > max_s:
                break
            if dur >= min_s:
                out.append(Window(start=start, end=end, sentences=sentences[i:j + 1]))
    return out


def score_window(w: Window, energy_ratio: float, speech_density: float,
                 scene_count: int, max_scenes: int = 5) -> Window:
    """Score one window. All inputs are measured, none are invented."""
    kw = _keyword_score(w.text)
    length = _length_fit(w.duration)
    energy = max(0.0, min(1.0, energy_ratio))  # 0..1, 1 = loudest part
    scenes = min(1.0, scene_count / max(1, max_scenes))
    score = 0.35 * kw + 0.25 * speech_density + 0.20 * energy + 0.10 * scenes + 0.10 * length
    w.score = round(score, 4)
    w.signals = {
        "keyword_density": round(kw, 3),
        "speech_density": round(speech_density, 3),
        "audio_energy": round(energy, 3),
        "scene_changes": scene_count,
        "length_fit": round(length, 3),
    }
    return w


def select_windows(windows: list, count: int) -> list:
    """Greedy top-N by score, skipping any window overlapping a pick."""
    picked: list = []
    for w in sorted(windows, key=lambda x: -x.score):
        if len(picked) >= count:
            break
        if any(not (w.end <= p.start or w.start >= p.end) for p in picked):
            continue
        picked.append(w)
    return sorted(picked, key=lambda x: x.start)


def reason_text(w: Window) -> str:
    """One plain-English reason line, naming the measured signals."""
    s = w.signals
    bits = []
    if "?" in w.text:
        bits.append("asks a question")
    if NUMBER_RE.search(w.text):
        bits.append("contains concrete numbers")
    if s.get("keyword_density", 0) >= 0.5:
        bits.append(f"high hook-word density ({s['keyword_density']:.2f})")
    if s.get("speech_density", 0) >= 0.8:
        bits.append(f"dense speech ({s['speech_density']:.0%} of the window is spoken)")
    if s.get("audio_energy", 0) >= 0.7:
        bits.append(f"above-average audio energy ({s['audio_energy']:.2f})")
    if s.get("scene_changes", 0):
        bits.append(f"{s['scene_changes']} scene change(s)")
    bits.append("self-contained sentences")
    return "; ".join(bits) + "."
