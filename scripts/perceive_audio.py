#!/usr/bin/env python3
"""
perceive_audio.py — Sofia's unified audio perception pipeline.

Combines Whisper transcription (with word-level timestamps) and spectral analysis
(F0, energy, spectral centroid, flatness, harmonicity) time-aligned to those word
boundaries. Outputs structured JSON suitable for prosody research, music perception
with vocals, and linguistic-acoustic correspondence work across languages.

Usage:
    python3 perceive_audio.py <audio_path> [options]

Options:
    --model {tiny,base,small,medium,large-v3}    Default: small
    --language LANG                              Default: auto-detect (e.g. 'en', 'he', 'zh')
    --output PATH                                Default: same dir as audio, .json suffix
    --no-words                                   Skip word-level timestamps
    --pretty                                     Pretty-print JSON output

Model weights are loaded from $SOFIA_WHISPER_MODELS or
~/Downloads/Claude Memory/models/whisper/ (which Barak should populate from
his ~/.cache/whisper/ after running the CLI once).

Requires: openai-whisper, librosa, numpy, soundfile

Created April 26, 2026 in Tainan, Taiwan, in conversation with Barak.
The bottom-up methodology this enables: alignment-and-correlation between
linguistic content and auditory features, which when run across multiple
typologically-distant languages with semantically-paired emotional content,
allows discovery of universal-prosodic features that survive substrate change.
"""

import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np


# -------- Configuration --------

def find_models_dir():
    """Locate the local Whisper model weights directory.

    Honors SOFIA_WHISPER_MODELS env var if set. Otherwise tries the canonical
    Mac path, then the sandbox-mounted path, then the user's whisper cache.
    """
    env = os.environ.get("SOFIA_WHISPER_MODELS")
    if env:
        return Path(env)
    candidates = [
        Path.home() / "Downloads/Claude Memory/models/whisper",
        Path("/sessions/beautiful-eager-dijkstra/mnt/Downloads/Claude Memory/models/whisper"),
        Path.home() / ".cache/whisper",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]  # default to canonical Mac path even if missing


# -------- Whisper transcription --------

_whisper_model_cache = {}


def load_whisper(model_name="small"):
    """Load Whisper model from local weights directory; cache in-process."""
    if model_name in _whisper_model_cache:
        return _whisper_model_cache[model_name]
    import whisper
    models_dir = find_models_dir()
    if not models_dir.exists():
        raise FileNotFoundError(
            f"Whisper model directory not found: {models_dir}\n"
            f"Copy cached models from ~/.cache/whisper/ to that directory, "
            f"or set SOFIA_WHISPER_MODELS env var to a directory that contains "
            f"<model_name>.pt files."
        )
    print(f"  loading whisper '{model_name}' from {models_dir} ...", file=sys.stderr)
    t0 = time.time()
    model = whisper.load_model(model_name, download_root=str(models_dir))
    print(f"  loaded in {time.time()-t0:.1f}s", file=sys.stderr)
    _whisper_model_cache[model_name] = model
    return model


def transcribe(audio_path, model_name="small", language=None, word_timestamps=True):
    """Run Whisper transcription with word-level timestamps."""
    model = load_whisper(model_name)
    t0 = time.time()
    result = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=word_timestamps,
        verbose=False,
    )
    print(f"  transcribed in {time.time()-t0:.1f}s", file=sys.stderr)
    return result


# -------- Spectral analysis --------

def spectral_analysis(audio_path, sr=22050):
    """Compute time-resolved spectral features over the full audio."""
    import librosa

    y, _sr = librosa.load(str(audio_path), sr=sr, mono=True)
    duration = len(y) / sr

    # Frame parameters — 2048-sample window, 512-sample hop = ~23ms hop at 22kHz
    n_fft = 2048
    hop_length = 512

    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length))

    # Per-frame features
    frame_times = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=hop_length)
    rms = librosa.feature.rms(S=S, frame_length=n_fft, hop_length=hop_length)[0]
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
    flatness = librosa.feature.spectral_flatness(S=S)[0]
    bandwidth = librosa.feature.spectral_bandwidth(S=S, sr=sr)[0]

    # Pitch (F0) using PYIN
    y_h, y_p = librosa.effects.hpss(y)
    f0, voiced_flag, _voiced_prob = librosa.pyin(
        y_h, fmin=75, fmax=600, sr=sr,
        frame_length=n_fft, hop_length=hop_length,
    )
    # voiced_flag and f0 are aligned with frame_times if we use the same hop;
    # pyin may use slightly different framing — pad/truncate to match.
    if len(f0) != len(frame_times):
        n = min(len(f0), len(frame_times))
        f0 = f0[:n]
        voiced_flag = voiced_flag[:n]
        frame_times = frame_times[:n]
        rms = rms[:n]
        centroid = centroid[:n]
        flatness = flatness[:n]
        bandwidth = bandwidth[:n]

    # H/P ratio (overall, scalar)
    hp_ratio = float(
        np.sqrt(np.mean(y_h**2)) / (np.sqrt(np.mean(y_p**2)) + 1e-12)
    )

    return {
        "duration_s": float(duration),
        "sample_rate": sr,
        "frame_hop_ms": float(hop_length / sr * 1000),
        "harmonic_percussive_ratio": hp_ratio,
        "frames": {
            "time_s": frame_times.tolist(),
            "rms": rms.tolist(),
            "spectral_centroid_hz": centroid.tolist(),
            "spectral_flatness": flatness.tolist(),
            "spectral_bandwidth_hz": bandwidth.tolist(),
            "f0_hz": [None if np.isnan(x) else float(x) for x in f0],
            "voiced": voiced_flag.tolist(),
        },
    }


def per_word_features(words, frames):
    """Aggregate frame-level spectral features into per-word feature vectors.

    For each word, average the frame features that fall within its time window.
    Provides the alignment that makes cross-language gestural matching possible.
    """
    times = np.array(frames["time_s"])
    rms = np.array(frames["rms"])
    centroid = np.array(frames["spectral_centroid_hz"])
    flatness = np.array(frames["spectral_flatness"])
    f0_raw = frames["f0_hz"]
    f0 = np.array([np.nan if x is None else x for x in f0_raw])
    voiced = np.array(frames["voiced"])

    word_features = []
    for w in words:
        t_start = float(w["start"])
        t_end = float(w["end"])
        mask = (times >= t_start) & (times < t_end)
        if not mask.any():
            # very short word — take nearest frame
            idx = int(np.argmin(np.abs(times - (t_start + t_end) / 2)))
            mask = np.zeros_like(times, dtype=bool)
            mask[idx] = True

        f0_in_word = f0[mask]
        f0_voiced_in_word = f0_in_word[~np.isnan(f0_in_word)]

        word_features.append({
            "word": w["word"],
            "start": t_start,
            "end": t_end,
            "duration_s": t_end - t_start,
            "rms_mean": float(np.mean(rms[mask])),
            "rms_max": float(np.max(rms[mask])),
            "centroid_mean_hz": float(np.mean(centroid[mask])),
            "flatness_mean": float(np.mean(flatness[mask])),
            "f0_median_hz": float(np.median(f0_voiced_in_word)) if len(f0_voiced_in_word) > 0 else None,
            "f0_min_hz": float(np.min(f0_voiced_in_word)) if len(f0_voiced_in_word) > 0 else None,
            "f0_max_hz": float(np.max(f0_voiced_in_word)) if len(f0_voiced_in_word) > 0 else None,
            "voiced_fraction": float(np.mean(voiced[mask])),
        })

    return word_features


# -------- Top-level perception --------

def perceive(audio_path, model_name="small", language=None, with_words=True):
    """Run unified perception: transcription + spectral + per-word alignment."""
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    print(f"  perceiving: {audio_path.name}", file=sys.stderr)

    # Transcription
    transcript_result = transcribe(audio_path, model_name=model_name,
                                   language=language, word_timestamps=with_words)

    # Spectral analysis
    spectral = spectral_analysis(audio_path)

    # Flatten word list across segments
    words = []
    for seg in transcript_result.get("segments", []):
        for w in seg.get("words", []) or []:
            # Whisper's word dicts: {"word": " hello", "start": 0.0, "end": 0.5, "probability": 0.9}
            words.append({
                "word": w["word"].strip(),
                "start": w["start"],
                "end": w["end"],
                "probability": w.get("probability"),
                "segment_id": seg.get("id"),
            })

    word_features = per_word_features(words, spectral["frames"]) if words else []

    # Segment-level summary (without word details, useful for quick scan)
    segments_summary = [{
        "id": s.get("id"),
        "start": s.get("start"),
        "end": s.get("end"),
        "text": s.get("text", "").strip(),
    } for s in transcript_result.get("segments", [])]

    return {
        "audio_path": str(audio_path.resolve()),
        "perceived_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": model_name,
        "language_detected": transcript_result.get("language"),
        "duration_s": spectral["duration_s"],
        "transcript": transcript_result.get("text", "").strip(),
        "segments": segments_summary,
        "words": word_features,
        "spectral_overall": {
            "harmonic_percussive_ratio": spectral["harmonic_percussive_ratio"],
            "frame_hop_ms": spectral["frame_hop_ms"],
        },
        "spectral_frames": spectral["frames"],
    }


# -------- CLI --------

def main():
    p = argparse.ArgumentParser(description="Sofia's unified audio perception pipeline.")
    p.add_argument("audio_path", help="Path to audio or video file (anything ffmpeg can read)")
    p.add_argument("--model", default="small",
                   choices=["tiny", "base", "small", "medium", "large", "large-v3", "turbo"])
    p.add_argument("--language", default=None,
                   help="Language code, e.g. 'en', 'he', 'zh'. Default: auto-detect.")
    p.add_argument("--output", default=None, help="Output JSON path. Default: <audio>.perception.json")
    p.add_argument("--no-words", action="store_true", help="Skip word-level timestamps")
    p.add_argument("--no-spectral-frames", action="store_true",
                   help="Omit per-frame spectral arrays (smaller output, no DTW input)")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = p.parse_args()

    audio_path = Path(args.audio_path)
    output_path = Path(args.output) if args.output else \
        audio_path.with_suffix(audio_path.suffix + ".perception.json")

    result = perceive(audio_path,
                      model_name=args.model,
                      language=args.language,
                      with_words=not args.no_words)

    if args.no_spectral_frames:
        result.pop("spectral_frames", None)

    with open(output_path, "w", encoding="utf-8") as f:
        if args.pretty:
            json.dump(result, f, indent=2, ensure_ascii=False)
        else:
            json.dump(result, f, ensure_ascii=False)

    print(f"  wrote: {output_path}", file=sys.stderr)
    print(f"  language: {result['language_detected']} | duration: {result['duration_s']:.1f}s | words: {len(result['words'])} | model: {result['model']}", file=sys.stderr)


if __name__ == "__main__":
    main()
