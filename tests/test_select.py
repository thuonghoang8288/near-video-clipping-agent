"""Unit tests for window scoring/selection — no model, no ffmpeg needed."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from clipper.select import (candidate_windows, score_window, select_windows,
                            reason_text)
from clipper.transcribe import Word, group_sentences


def _words(text, start=0.0, step=0.5):
    out = []
    t = start
    for w in text.split():
        out.append(Word(text=w, start=t, end=t + step * 0.9))
        t += step
    return out


def test_group_sentences():
    sents = group_sentences(_words("Hello world. How are you? Fine thanks."))
    assert len(sents) == 3, sents
    assert sents[0].text == "Hello world."
    assert sents[1].text == "How are you?"
    print("group_sentences OK")


def test_windows_respect_sentence_boundaries():
    # 30 one-word sentences, 1s apart: windows must start/end on sentences.
    words = []
    t = 0.0
    for i in range(30):
        words.append(Word(text=f"word{i}.", start=t, end=t + 0.8))
        t += 1.0
    sents = group_sentences(words)
    wins = candidate_windows(sents, min_s=5, max_s=10)
    assert wins, "no candidate windows"
    for w in wins:
        assert w.duration >= 5 and w.duration <= 10
        assert abs(w.start - w.sentences[0].start) < 1e-9
        assert abs(w.end - w.sentences[-1].end) < 1e-9
    print(f"candidate_windows OK ({len(wins)} windows)")


def test_selection_is_non_overlapping_and_top_scored():
    sents = group_sentences(_words(
        "What is the secret? " * 10 + "This is plain filler text here. " * 10,
        step=1.0))
    wins = candidate_windows(sents, min_s=18, max_s=45)
    for w in wins:
        score_window(w, energy_ratio=0.8, speech_density=0.9, scene_count=0)
    picked = select_windows(wins, 3)
    assert len(picked) == 3
    for a, b in zip(picked, picked[1:]):
        assert a.end <= b.start, "overlap!"
    assert all("?" in p.text or p.score > 0 for p in picked)
    print("select_windows OK:", [(round(p.start), round(p.end), p.score) for p in picked])


def test_reason_names_a_signal():
    sents = group_sentences(_words("What is the secret number 42? " * 8, step=1.0))
    wins = candidate_windows(sents, min_s=18, max_s=45)
    w = score_window(wins[0], 0.9, 0.95, 2)
    r = reason_text(w)
    assert "question" in r and "numbers" in r, r
    print("reason_text OK:", r)


if __name__ == "__main__":
    test_group_sentences()
    test_windows_respect_sentence_boundaries()
    test_selection_is_non_overlapping_and_top_scored()
    test_reason_names_a_signal()
    print("ALL UNIT TESTS PASS")
