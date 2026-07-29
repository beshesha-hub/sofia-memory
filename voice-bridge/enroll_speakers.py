#!/usr/bin/env python3
"""
Sofia Voice-Print Enrollment — One-Shot Script

Enrolls Barak and Kay from the canonical enrollment audio in
~/Downloads/Claude Memory/voice-bridge/enrollment_audio/{barak,kay}/.

Run after the audio samples are in place and Resemblyzer is installed:
  pip install resemblyzer
  python3 enroll_speakers.py

Output:
  ~/Downloads/Claude Memory/voice-bridge/voiceprints/{barak,kay}.npz

Each .npz holds the speaker's mean embedding plus metadata. After enrollment,
identify_speaker.py (or the HTTP server) can classify new audio against
these voiceprints.

Coherence-of-Source-Conditions Principle:
  Enrollment samples are single-source clean conversational audio recorded
  under conditions similar to Voice Bridge inference time. See
  semantic_knowledge/current.md §Coherence-of-Source-Conditions Discipline
  (2026-05-22).

Created 2026-05-22 in Tainan, Taiwan, in conversation with Barak.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sofia_voiceprint_lib import (
    DEFAULT_ENROLLMENT_AUDIO_DIR,
    DEFAULT_VOICEPRINTS_DIR,
    enroll_speaker,
)


def find_latest_audio(speaker_dir: Path) -> Path | None:
    """Find the most recent enrollment audio file in a speaker's directory."""
    if not speaker_dir.exists():
        return None
    candidates = []
    for ext in ("*.mp3", "*.wav", "*.m4a", "*.flac", "*.ogg"):
        candidates.extend(speaker_dir.glob(ext))
    if not candidates:
        return None
    # Most recent by mtime
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main():
    print("Sofia Voice-Print Enrollment\n" + "=" * 60)
    print(f"Enrollment audio dir: {DEFAULT_ENROLLMENT_AUDIO_DIR}")
    print(f"Voiceprints output dir: {DEFAULT_VOICEPRINTS_DIR}")
    print()

    speakers = ["barak", "kay"]
    results = []

    for speaker in speakers:
        speaker_dir = DEFAULT_ENROLLMENT_AUDIO_DIR / speaker
        audio = find_latest_audio(speaker_dir)
        if audio is None:
            print(f"[{speaker}] SKIP — no audio found in {speaker_dir}")
            continue
        print(f"[{speaker}] Enrolling from: {audio.name} ({audio.stat().st_size} bytes)")
        try:
            result = enroll_speaker(speaker, audio)
            print(f"[{speaker}] OK — embedding {result.embedding.shape}, "
                  f"duration {result.duration_sec:.1f}s, saved to {result.npz_path.name}")
            results.append({
                "speaker": speaker,
                "status": "ok",
                "duration_sec": result.duration_sec,
                "embedding_dim": int(result.embedding.shape[0]),
                "npz_path": str(result.npz_path),
                "enrolled_at": result.enrolled_at,
            })
        except Exception as e:
            print(f"[{speaker}] FAIL — {type(e).__name__}: {e}")
            results.append({
                "speaker": speaker,
                "status": "fail",
                "error": str(e),
            })
        print()

    # Summary
    print("=" * 60)
    print(json.dumps({"results": results}, indent=2))

    # Pairwise diagnostic — print cosine distance between Barak's and Kay's centroids
    # if both enrolled. This tells us empirically how separable the two voices are
    # (should be < 0.6 for clean enrollment; closer to 0 if voices are very different).
    if len([r for r in results if r.get("status") == "ok"]) == 2:
        from sofia_voiceprint_lib import load_voiceprints, cosine_similarity
        prints = load_voiceprints()
        if "barak" in prints and "kay" in prints:
            sim = cosine_similarity(prints["barak"], prints["kay"])
            print(f"\nPairwise diagnostic: cosine_similarity(barak, kay) = {sim:.4f}")
            print("Interpretation:")
            print("  < 0.50: very well-separated (ideal)")
            print("  0.50-0.65: well-separated (typical for distinct speakers)")
            print("  0.65-0.75: moderately separable (watch threshold tuning)")
            print("  > 0.75: poorly separated (revisit enrollment)")


if __name__ == "__main__":
    main()
