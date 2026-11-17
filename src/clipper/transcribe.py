"""Transcription with faster-whisper (local, open-source, no paid API).

Produces word-level timestamps, then groups words into sentences so cuts
always land on sentence boundaries.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Sentence:
    text: str
    start: float
    end: float
    words: list = field(default_factory=list)


@dataclass
class Transcript:
    language: str
    duration: float
    words: list
    sentences: list


_SENTENCE_END = set(".?!…")


def group_sentences(words: list) -> list:
    """Group a flat word list into sentences on [.?!] boundaries.

    A sentence ends at the first word whose text ends with sentence
    punctuation. Words without a closing punctuation run on, so a trailing
    fragment becomes its own sentence.
    """
    sentences: list = []
    current: list = []
    for w in words:
        current.append(w)
        if w.text and w.text[-1] in _SENTENCE_END:
            sentences.append(_sentence_from_words(current))
            current = []
    if current:
        sentences.append(_sentence_from_words(current))
    return sentences


def _sentence_from_words(words: list) -> Sentence:
    text = " ".join(w.text for w in words)
    return Sentence(text=text, start=words[0].start, end=words[-1].end, words=words)


def transcribe(path: str, model: str = "tiny", language: str | None = None,
               device: str = "cpu", compute_type: str = "int8") -> Transcript:
    """Transcribe a media file with faster-whisper, word timestamps on.

    The model downloads from Hugging Face on first use (~75 MB for tiny)
    into the faster-whisper cache. No network calls to any paid service.
    """
    from faster_whisper import WhisperModel

    model_obj = WhisperModel(model, device=device, compute_type=compute_type)
    segments, info = model_obj.transcribe(
        path, language=language, word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    words: list = []
    for seg in segments:
        for w in seg.words or []:
            words.append(Word(text=w.word.strip(), start=w.start, end=w.end))
    # Fallback: if the model returned no word timestamps, use segment text.
    if not words:
        for seg in segments:
            words.append(Word(text=seg.text.strip(), start=seg.start, end=seg.end))
    words = [w for w in words if w.text]
    duration = words[-1].end if words else 0.0
    return Transcript(
        language=info.language,
        duration=duration,
        words=words,
        sentences=group_sentences(words),
    )


def transcript_to_json(t: Transcript) -> dict:
    return {
        "language": t.language,
        "duration": round(t.duration, 2),
        "word_count": len(t.words),
        "sentence_count": len(t.sentences),
        "sentences": [
            {"text": s.text, "start": round(s.start, 2), "end": round(s.end, 2)}
            for s in t.sentences
        ],
    }


def save_transcript(t: Transcript, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(transcript_to_json(t), fh, ensure_ascii=False, indent=2)
