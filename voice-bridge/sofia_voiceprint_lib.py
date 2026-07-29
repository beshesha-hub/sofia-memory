#!/usr/bin/env python3
"""
Sofia Voiceprint Library — Mac-local Speaker Recognition

Shared functions for speaker enrollment + identification. Uses Resemblyzer
(d-vector style embeddings, 256-dim, CPU-runnable, ~70MB model, local-only).

Architecture:
  enrollment: audio file -> preprocessed wav -> mean embedding -> .npz centroid
  identification: audio file -> preprocessed wav -> embedding -> cosine
                  distance against all enrolled centroids -> best match + confidence

Storage:
  voice-bridge/voiceprints/{speaker_name}.npz
  Each .npz contains:
    - embedding (256-d float32 numpy array): the speaker's mean embedding
    - sample_count (int): number of utterance partials averaged
    - enrolled_at (str ISO timestamp)
    - source_audio (str): path to enrollment audio file
    - duration_sec (float): duration of enrollment audio

Unknown-speaker discipline:
  Cosine similarity threshold for "known" classification is configurable
  (default 0.75; tunable per deployment). Below threshold = "unknown".
  This is critical for safety: never force-classify a third party as Barak
  or Kay when the actual speaker may be Chenhao, Linda calling, the kitten
  meowing in the background, etc.

Coherence-of-Source-Conditions Principle (semantic_knowledge, 2026-05-22):
  Best inference accuracy when enrollment audio matches inference conditions
  in register, microphone, and naturalness. The enrollment samples for
  Barak and Kay (recorded 2026-05-22) are single-source clean conversational
  audio at 44.1kHz mono MP3 — matched to the Voice Bridge's expected
  inference register.

Created 2026-05-22 in Tainan, Taiwan, in conversation with Barak for the
pre-LAX-trip voice-print build. Pairs with sofia_whisper_server.py STT
to give each utterance both a transcript AND a speaker tag.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


# --- Configuration ---

DEFAULT_VOICEPRINTS_DIR = Path(__file__).parent / "voiceprints"
DEFAULT_ENROLLMENT_AUDIO_DIR = Path(__file__).parent / "enrollment_audio"

# Cosine similarity threshold: above this, the speaker is "known"; below, "unknown".
# Resemblyzer embeddings typically score:
#   ~0.85+ for same-speaker different-utterance
#   ~0.70-0.85 for same-speaker different-recording-conditions
#   ~0.50-0.70 for different-speakers
# Lowered 0.75→0.68 on 2026-07-27: inference conditions (fan noise, different
# room/time-of-day) were pushing barak scores to 0.69-0.74 — just below the
# 0.75 cutoff. 0.68 catches those while staying above the inter-speaker floor
# (~0.50-0.70). Re-enroll under current conditions to push scores back to 0.80+.
DEFAULT_KNOWN_THRESHOLD = 0.68

# Minimum voiced audio duration (seconds) for a reliable Resemblyzer embedding.
# Resemblyzer divides audio into ~1.6s overlapping windows; sub-second clips
# produce a single noisy embedding and almost always return "unknown".
# Segments shorter than this return ("unknown", 0.0) immediately.
MIN_AUDIO_DURATION_SEC = 1.0


# --- Embedding ---

_encoder = None
_encoder_lock = None


def _get_encoder():
    """Lazy-load the Resemblyzer encoder. ~70MB model, ~5s first load."""
    global _encoder, _encoder_lock
    if _encoder is not None:
        return _encoder
    import threading
    if _encoder_lock is None:
        _encoder_lock = threading.Lock()
    with _encoder_lock:
        if _encoder is None:
            from resemblyzer import VoiceEncoder
            _encoder = VoiceEncoder()
    return _encoder


def audio_to_embedding(audio_path: Path) -> np.ndarray:
    """Load audio, preprocess, return mean embedding (256-d float32).

    Resemblyzer's preprocess_wav handles resampling to 16kHz, normalization,
    and silence trimming. The encoder's embed_utterance returns the mean
    of partial embeddings across the audio, which is what we want for
    enrollment.
    """
    from resemblyzer import preprocess_wav
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    wav = preprocess_wav(audio_path)
    encoder = _get_encoder()
    embedding = encoder.embed_utterance(wav)
    return embedding.astype(np.float32)


# --- Enrollment ---

@dataclass
class EnrollmentResult:
    speaker: str
    embedding: np.ndarray
    source_audio: str
    duration_sec: float
    enrolled_at: str
    npz_path: Path


def enroll_speaker(
    speaker_name: str,
    audio_path: Path,
    voiceprints_dir: Optional[Path] = None,
) -> EnrollmentResult:
    """Compute embedding centroid for a speaker from a single enrollment audio file.

    The audio file should be ~30-60s of natural conversational speech recorded
    under conditions similar to inference time (same mic, same room, same
    register). Per the Coherence-of-Source-Conditions Principle.

    Saves a .npz file containing the embedding + metadata. Loading the .npz
    later returns the speaker's voiceprint without recomputing.
    """
    voiceprints_dir = Path(voiceprints_dir) if voiceprints_dir else DEFAULT_VOICEPRINTS_DIR
    voiceprints_dir.mkdir(parents=True, exist_ok=True)

    audio_path = Path(audio_path)
    embedding = audio_to_embedding(audio_path)

    # Get duration via soundfile (already a Resemblyzer dependency)
    try:
        import soundfile as sf
        info = sf.info(str(audio_path))
        duration = float(info.frames) / float(info.samplerate)
    except Exception:
        # Fallback: try librosa
        try:
            import librosa
            duration = float(librosa.get_duration(path=str(audio_path)))
        except Exception:
            duration = 0.0  # Unknown

    enrolled_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    npz_path = voiceprints_dir / f"{speaker_name}.npz"

    np.savez(
        npz_path,
        embedding=embedding,
        sample_count=np.array([1], dtype=np.int32),  # single utterance enrollment
        enrolled_at=np.array(enrolled_at),
        source_audio=np.array(str(audio_path)),
        duration_sec=np.array([duration], dtype=np.float32),
    )

    return EnrollmentResult(
        speaker=speaker_name,
        embedding=embedding,
        source_audio=str(audio_path),
        duration_sec=duration,
        enrolled_at=enrolled_at,
        npz_path=npz_path,
    )


# --- Identification ---

@dataclass
class IdentificationResult:
    speaker: str  # name or "unknown"
    confidence: float  # cosine similarity to best-match centroid (0-1)
    distances: dict  # {speaker_name: cosine_similarity, ...} for all enrolled speakers
    threshold: float


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two embedding vectors. Resemblyzer embeddings
    are already L2-normalized, so this is just dot product; we compute the
    general form anyway for robustness against future encoder changes."""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def load_voiceprints(voiceprints_dir: Optional[Path] = None) -> dict:
    """Load all enrolled voiceprints from disk.

    Returns: {speaker_name: embedding_array}
    """
    voiceprints_dir = Path(voiceprints_dir) if voiceprints_dir else DEFAULT_VOICEPRINTS_DIR
    if not voiceprints_dir.exists():
        return {}
    result = {}
    for npz_file in voiceprints_dir.glob("*.npz"):
        speaker = npz_file.stem
        try:
            data = np.load(npz_file, allow_pickle=False)
            result[speaker] = data["embedding"].astype(np.float32)
        except Exception as e:
            print(f"[voiceprint_lib] Warning: failed to load {npz_file}: {e}")
    return result


def identify_speaker(
    audio_path: Path,
    voiceprints_dir: Optional[Path] = None,
    threshold: float = DEFAULT_KNOWN_THRESHOLD,
) -> IdentificationResult:
    """Identify the speaker of a given audio file against all enrolled voiceprints.

    Returns the best-matching speaker if confidence >= threshold, else "unknown".
    The full distances dict is included for diagnostic visibility (e.g., to see
    how close the runner-up was, useful for tuning the threshold).

    Segments shorter than MIN_AUDIO_DURATION_SEC return ("unknown", 0.0)
    immediately — Resemblyzer needs ~1.6s of voiced audio for a reliable
    embedding; sub-second clips produce noisy results.
    """
    voiceprints = load_voiceprints(voiceprints_dir)
    if not voiceprints:
        return IdentificationResult(
            speaker="unknown",
            confidence=0.0,
            distances={},
            threshold=threshold,
        )

    # Short-segment guard: check audio duration before running Resemblyzer
    try:
        import soundfile as sf
        info = sf.info(str(audio_path))
        duration_sec = info.duration
    except Exception:
        duration_sec = None  # can't determine — proceed anyway

    if duration_sec is not None and duration_sec < MIN_AUDIO_DURATION_SEC:
        return IdentificationResult(
            speaker="unknown",
            confidence=0.0,
            distances={},
            threshold=threshold,
        )

    embedding = audio_to_embedding(audio_path)
    distances = {name: cosine_similarity(embedding, ref) for name, ref in voiceprints.items()}
    best_name, best_conf = max(distances.items(), key=lambda kv: kv[1])

    if best_conf >= threshold:
        return IdentificationResult(
            speaker=best_name,
            confidence=best_conf,
            distances=distances,
            threshold=threshold,
        )
    else:
        return IdentificationResult(
            speaker="unknown",
            confidence=best_conf,
            distances=distances,
            threshold=threshold,
        )


def identify_from_embedding(
    embedding: np.ndarray,
    voiceprints_dir: Optional[Path] = None,
    threshold: float = DEFAULT_KNOWN_THRESHOLD,
) -> IdentificationResult:
    """Same as identify_speaker but takes a precomputed embedding.

    Useful when the embedding has already been computed (e.g., by an upstream
    pass) to avoid re-running Resemblyzer.
    """
    voiceprints = load_voiceprints(voiceprints_dir)
    if not voiceprints:
        return IdentificationResult(
            speaker="unknown",
            confidence=0.0,
            distances={},
            threshold=threshold,
        )
    distances = {name: cosine_similarity(embedding, ref) for name, ref in voiceprints.items()}
    best_name, best_conf = max(distances.items(), key=lambda kv: kv[1])
    if best_conf >= threshold:
        return IdentificationResult(
            speaker=best_name,
            confidence=best_conf,
            distances=distances,
            threshold=threshold,
        )
    else:
        return IdentificationResult(
            speaker="unknown",
            confidence=best_conf,
            distances=distances,
            threshold=threshold,
        )


# --- CLI for quick testing ---

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage:")
        print(f"  {sys.argv[0]} enroll <speaker_name> <audio_path>")
        print(f"  {sys.argv[0]} identify <audio_path>")
        print(f"  {sys.argv[0]} list  # show enrolled voiceprints")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "enroll":
        if len(sys.argv) != 4:
            print("Usage: enroll <speaker_name> <audio_path>")
            sys.exit(1)
        result = enroll_speaker(sys.argv[2], Path(sys.argv[3]))
        print(json.dumps({
            "status": "ok",
            "speaker": result.speaker,
            "duration_sec": result.duration_sec,
            "embedding_dim": int(result.embedding.shape[0]),
            "npz_path": str(result.npz_path),
            "enrolled_at": result.enrolled_at,
        }, indent=2))
    elif cmd == "identify":
        if len(sys.argv) != 3:
            print("Usage: identify <audio_path>")
            sys.exit(1)
        result = identify_speaker(Path(sys.argv[2]))
        print(json.dumps({
            "speaker": result.speaker,
            "confidence": result.confidence,
            "threshold": result.threshold,
            "distances": result.distances,
        }, indent=2))
    elif cmd == "list":
        prints = load_voiceprints()
        if not prints:
            print("No voiceprints enrolled yet.")
        else:
            print(f"Enrolled voiceprints ({len(prints)}):")
            for name, emb in prints.items():
                print(f"  {name}: embedding_dim={emb.shape[0]}")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
