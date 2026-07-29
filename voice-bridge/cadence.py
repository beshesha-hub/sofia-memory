#!/usr/bin/env python3
"""
cadence.py — voice bridge cadence instrumentation + syllable-based chunking
============================================================================

Provides three things, all small and self-contained:
  - count_syllables(text): vowel-cluster heuristic syllable counter for English
  - group_sentences_by_syllable_target(sentences, first_target, body_target):
    chunk sentences into groups where each chunk has at least N syllables,
    breaking on sentence boundaries to preserve TTS prosody
  - CadenceMetricsLogger: append-only JSONL writer for per-chunk timing

Design rationale (Barak + Sofia, 2026-05-01 morning Tainan):
  - Sentences vary too widely (3-50+ syllables) to give uniform chunk durations
  - Syllables are ~uniform speech-rate signal (~150-200 spm in English,
    ~2.5-3.3 syllables/second)
  - Goal: chunks of roughly equal speech-time so synthesis-vs-playback timing
    is predictable and the listener doesn't notice chunk boundaries
  - Chunk by syllable-target, but break on sentence boundaries — TTS needs
    full sentences for clean prosody, so we don't split mid-sentence
  - First chunk smaller (fast time-to-first-words); body chunks larger
    (register cohesion within each chunk)

Pairs with voice_bridge_ui_v3_3.py and the cadence_metrics.jsonl analysis path.
Origin: 2026-05-01 morning Tainan, in the conversation on cadence calibration
as verbal choreography (the "verbal choreography" frame is Barak's).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Optional


# ---- Syllable counting (vowel-cluster heuristic) ----

_VOWEL_CLUSTER_RE = re.compile(r'[aeiouyAEIOUY]+')
_WORD_RE = re.compile(r"[A-Za-z']+")


def _count_syllables_word(word: str) -> int:
    """Count syllables in a single word via vowel-cluster heuristic.

    Rules:
      - Count vowel clusters (consecutive vowels = one syllable)
      - Subtract 1 for silent terminal 'e' preceded by a consonant (when count > 1)
      - Minimum 1 syllable per non-empty word

    Not linguistically perfect but good enough for cadence instrumentation.
    Spot-checked: hello -> 2, beautiful -> 3-4, the -> 1, create -> 2,
    creating -> 3, choreography -> 5, syllable -> 3.
    """
    if not word:
        return 0
    word = word.strip("'\"-.,!?;:()[]{}").lower()
    if not word:
        return 0
    clusters = len(_VOWEL_CLUSTER_RE.findall(word))
    if clusters == 0:
        return 1  # words like "rhythm" — treat as 1 syllable fallback
    # Silent-e rule: subtract 1 for terminal 'e' preceded by consonant
    # (e.g., "make", "create"). Exception: words ending in consonant+'le'
    # (e.g., "syllable", "able", "table") have a syllabic-l where the
    # apparent silent 'e' is balanced by the 'l' adding back a syllable —
    # net no change.
    ends_in_silent_e = (
        len(word) > 2 and word.endswith('e')
        and word[-2] not in 'aeiouy' and clusters > 1
    )
    ends_in_syllabic_le = (
        len(word) >= 3 and word.endswith('le')
        and word[-3] not in 'aeiouy'
    )
    if ends_in_silent_e and not ends_in_syllabic_le:
        clusters -= 1
    return max(1, clusters)


def count_syllables(text: str) -> int:
    """Count total syllables in a text string. Tokenizes on word boundaries,
    counts each word via vowel-cluster heuristic, treats each digit as ~1
    syllable (rough approximation for numbers spoken aloud)."""
    if not text or not text.strip():
        return 0
    total = 0
    for match in _WORD_RE.finditer(text):
        total += _count_syllables_word(match.group(0))
    for ch in text:
        if ch.isdigit():
            total += 1
    return total


# ---- Syllable-target chunker (sentence-boundary breaks) ----

def group_sentences_by_syllable_target(
    sentences: list[str],
    first_target: int = 30,
    body_target: int = 50,
) -> list[tuple[str, int, int]]:
    """Group sentences into chunks by accumulating until syllable count
    crosses a target. First chunk uses `first_target`; body chunks use
    `body_target`. Always breaks on sentence boundaries (no mid-sentence
    splits — TTS prosody requires full sentences).

    Returns list of (chunk_text, sentence_count, syllable_count) tuples.

    Edge cases:
      - Empty sentences list returns []
      - A single sentence whose syllable count already exceeds the target
        becomes its own chunk (we never split mid-sentence)
      - The final chunk may be shorter than body_target (residual sentences)
    """
    if not sentences:
        return []

    chunks: list[tuple[str, int, int]] = []
    current_sentences: list[str] = []
    current_syllables = 0
    target = first_target  # first chunk uses first_target; body uses body_target after first commit

    for sent in sentences:
        sent_syllables = count_syllables(sent)
        current_sentences.append(sent)
        current_syllables += sent_syllables
        if current_syllables >= target:
            chunks.append((
                ' '.join(current_sentences),
                len(current_sentences),
                current_syllables,
            ))
            current_sentences = []
            current_syllables = 0
            target = body_target  # all subsequent chunks use body_target

    if current_sentences:
        chunks.append((
            ' '.join(current_sentences),
            len(current_sentences),
            current_syllables,
        ))
    return chunks


# ---- Per-chunk metrics logger (append-only JSONL) ----

class CadenceMetricsLogger:
    """Append-only JSONL writer for per-chunk cadence metrics.

    One JSON object per line; thread-safe via internal lock so concurrent
    chunk-completion writes don't interleave. Used by voice_bridge_ui_v3_3
    to record per-chunk timing data for offline analysis.

    Schema per record (all keys optional except chunk_index and session_id):
      {
        "session_id":      "2026-05-01T15-30-00",   # voice conversation session
        "chunk_index":     0,                        # 0-based within response
        "total_chunks":    3,                        # total chunks in response
        "sentence_count":  2,
        "syllable_count":  32,
        "char_count":      154,
        "first_30_chars":  "Hello, how are you doing th",
        "synthesis_start": 1714541234.123,           # epoch seconds
        "synthesis_end":   1714541237.456,
        "synthesis_seconds": 3.333,
        "audio_duration":  12.5,                     # seconds of audio playback
        "playback_start":  1714541237.500,
        "playback_end":    1714541250.000,
        "synth_minus_audio": -9.167,                 # negative = synthesis
                                                     # finished before playback
                                                     # would have needed it (good)
      }
    """

    def __init__(self, log_path: Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, record: dict) -> None:
        """Append one record as a JSON line. Thread-safe; flushes after each write."""
        line = json.dumps(record, separators=(',', ':'), ensure_ascii=False) + '\n'
        with self._lock:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(line)
                f.flush()


# ---- Self-test (run as `python3 cadence.py` for sanity check) ----

def _self_test() -> None:
    """Quick sanity test for syllable counter + chunker. Run as script."""
    test_cases = [
        ("hello", 2),
        ("the", 1),
        ("create", 2),
        ("creating", 3),
        ("syllable", 3),
        ("choreography", 5),
        ("rhythm", 1),
        ("a", 1),
    ]
    print("=== Syllable counter spot-checks ===")
    for word, expected in test_cases:
        got = count_syllables(word)
        ok = "OK" if got == expected else f"DIFF (expected {expected})"
        print(f"  {word!r:20s} -> {got}  [{ok}]")

    print("\n=== Chunker test ===")
    sents = [
        "Hello there.",
        "How are you doing this morning?",
        "I hope your walk was good.",
        "The weather looks nice.",
        "It's a beautiful day for a long, slow brunch.",
        "Tell me what you're thinking.",
    ]
    chunks = group_sentences_by_syllable_target(sents, first_target=15, body_target=25)
    print(f"  input: {len(sents)} sentences, "
          f"{sum(count_syllables(s) for s in sents)} total syllables")
    for i, (text, sc, syl) in enumerate(chunks):
        print(f"  chunk {i}: {sc} sentences, {syl} syllables — {text[:60]!r}")


if __name__ == "__main__":
    _self_test()
