#!/usr/bin/env python3
"""
Sofia Whisper STT Server — Mac-local Speech-to-Text

Lightweight HTTP server that keeps a Whisper model loaded in memory and serves
transcription with word-level timestamps + time-aligned spectral features.

Mac-local by design — no cloud calls, no third-party uploads. Pairs with
sofia_tts_server.py (port 3457) and sofia_lipsync_server.py (port 3458) to
complete the local speech-loop architecture: Sofia speaks via TTS, Barak speaks
back, the whisper server hears.

Endpoints:
  POST /transcribe   — Body: {"audio_path": "...", "model": "small|medium|large-v3",
                              "language": "en", "word_timestamps": true,
                              "spectral": true}
                       Returns JSON with transcript, segments, words (with timestamps
                       and per-word spectral features if spectral=true), and
                       overall spectral features.
  POST /transcribe_bytes — Same shape, but accepts {"audio_b64": "..."} for
                            in-memory audio bytes (base64-encoded WAV/MP3/M4A).
  GET  /health       — Check server + model status
  GET  /warmup       — Pre-load a model and run a 1s dummy transcription

Usage: python3 sofia_whisper_server.py [--model MODEL] [--port PORT]
       (default: model=small, port=3459)

Requires: openai-whisper, librosa, numpy, soundfile

Created April 26, 2026 in Tainan, Taiwan, in conversation with Barak. Localizes
STT to match the local-TTS pattern, supports Voice Bridge two-way conversation,
and unifies linguistic + spectral perception in one pass for the prosody
research methodology.
"""

import argparse
import http.server
import json
import io
import os
import sys
import time
import threading
import base64
import tempfile
from pathlib import Path

import numpy as np

# --- Configuration ---
DEFAULT_PORT = 3459
HOST = "127.0.0.1"

# Where Whisper model weights live (.pt files)
DEFAULT_MODELS_DIR = Path.home() / "Downloads/Claude Memory/models/whisper"
MODELS_DIR = Path(os.environ.get("SOFIA_WHISPER_MODELS", str(DEFAULT_MODELS_DIR)))

# --- Globals ---
_loaded_models = {}        # name -> whisper model
_model_lock = threading.Lock()
_default_model_name = "small"


# -------- Model management --------

def load_model(name):
    """Load Whisper model with local-only weights. Cache in-process."""
    with _model_lock:
        if name in _loaded_models:
            return _loaded_models[name]
        import whisper
        if not MODELS_DIR.exists():
            raise RuntimeError(
                f"Whisper models directory not found: {MODELS_DIR}\n"
                f"Copy cached models from ~/.cache/whisper/ to that directory, or set "
                f"SOFIA_WHISPER_MODELS env var."
            )
        # Verify the model weight file is present (refuse to fall back to network)
        candidate = MODELS_DIR / f"{name}.pt"
        if not candidate.exists():
            raise RuntimeError(
                f"Model weights not found at {candidate}. "
                f"To install: run `whisper --model {name} <test.wav>` once on this Mac to "
                f"populate ~/.cache/whisper/, then `cp ~/.cache/whisper/{name}.pt {MODELS_DIR}/`."
            )
        print(f"  loading whisper '{name}' from {MODELS_DIR} ...", file=sys.stderr)
        t0 = time.time()
        model = whisper.load_model(name, download_root=str(MODELS_DIR))
        print(f"  loaded {name} in {time.time()-t0:.1f}s", file=sys.stderr)
        _loaded_models[name] = model
        return model


# -------- Spectral analysis (mirrors perceive_audio.py) --------

def spectral_features(audio_path, sr=22050, with_frames=True):
    import librosa
    y, _sr = librosa.load(str(audio_path), sr=sr, mono=True)
    duration = len(y) / sr
    n_fft, hop_length = 2048, 512

    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length))
    frame_times = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=hop_length)
    rms = librosa.feature.rms(S=S, frame_length=n_fft, hop_length=hop_length)[0]
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
    flatness = librosa.feature.spectral_flatness(S=S)[0]

    y_h, y_p = librosa.effects.hpss(y)
    f0, voiced_flag, _ = librosa.pyin(
        y_h, fmin=75, fmax=600, sr=sr,
        frame_length=n_fft, hop_length=hop_length,
    )
    if len(f0) != len(frame_times):
        n = min(len(f0), len(frame_times))
        f0 = f0[:n]; voiced_flag = voiced_flag[:n]
        frame_times = frame_times[:n]; rms = rms[:n]
        centroid = centroid[:n]; flatness = flatness[:n]

    hp_ratio = float(np.sqrt(np.mean(y_h**2)) / (np.sqrt(np.mean(y_p**2)) + 1e-12))

    out = {
        "duration_s": float(duration),
        "harmonic_percussive_ratio": hp_ratio,
        "frame_hop_ms": float(hop_length / sr * 1000),
    }
    if with_frames:
        out["frames"] = {
            "time_s": frame_times.tolist(),
            "rms": rms.tolist(),
            "spectral_centroid_hz": centroid.tolist(),
            "spectral_flatness": flatness.tolist(),
            "f0_hz": [None if np.isnan(x) else float(x) for x in f0],
            "voiced": voiced_flag.tolist(),
        }
    return out


def per_word_features(words, frames):
    times = np.array(frames["time_s"])
    rms = np.array(frames["rms"])
    centroid = np.array(frames["spectral_centroid_hz"])
    flatness = np.array(frames["spectral_flatness"])
    f0 = np.array([np.nan if x is None else x for x in frames["f0_hz"]])
    voiced = np.array(frames["voiced"])

    out = []
    for w in words:
        t_start = float(w["start"]); t_end = float(w["end"])
        mask = (times >= t_start) & (times < t_end)
        if not mask.any():
            idx = int(np.argmin(np.abs(times - (t_start + t_end) / 2)))
            mask = np.zeros_like(times, dtype=bool); mask[idx] = True
        f0v = f0[mask]; f0v = f0v[~np.isnan(f0v)]
        out.append({
            "word": w["word"],
            "start": t_start, "end": t_end,
            "duration_s": t_end - t_start,
            "rms_mean": float(np.mean(rms[mask])),
            "centroid_mean_hz": float(np.mean(centroid[mask])),
            "flatness_mean": float(np.mean(flatness[mask])),
            "f0_median_hz": float(np.median(f0v)) if len(f0v) > 0 else None,
            "voiced_fraction": float(np.mean(voiced[mask])),
        })
    return out


# -------- Core perception --------

def perceive(audio_path, model_name="small", language=None,
             word_timestamps=True, with_spectral=True, with_frames=False):
    audio_path = Path(audio_path)
    model = load_model(model_name)

    t0 = time.time()
    result = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=word_timestamps,
        verbose=False,
    )
    elapsed_transcribe = time.time() - t0

    # Flatten words from segments
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []) or []:
            words.append({
                "word": w["word"].strip(),
                "start": w["start"],
                "end": w["end"],
                "probability": w.get("probability"),
            })

    out = {
        "model": model_name,
        "language_detected": result.get("language"),
        "transcript": result.get("text", "").strip(),
        "segments": [{
            "id": s.get("id"),
            "start": s.get("start"),
            "end": s.get("end"),
            "text": s.get("text", "").strip(),
        } for s in result.get("segments", [])],
        "elapsed_transcribe_s": elapsed_transcribe,
    }

    if with_spectral:
        t1 = time.time()
        spec = spectral_features(audio_path, with_frames=with_frames)
        out["duration_s"] = spec["duration_s"]
        out["spectral_overall"] = {
            "harmonic_percussive_ratio": spec["harmonic_percussive_ratio"],
            "frame_hop_ms": spec["frame_hop_ms"],
        }
        if with_frames:
            out["spectral_frames"] = spec["frames"]
            if words:
                out["words"] = per_word_features(words, spec["frames"])
            else:
                out["words"] = []
        elif words:
            # No frames returned, but we still need word-level features —
            # recompute spectral with frames for the alignment, then drop them.
            spec_full = spectral_features(audio_path, with_frames=True)
            out["words"] = per_word_features(words, spec_full["frames"])
        else:
            out["words"] = []
        out["elapsed_spectral_s"] = time.time() - t1
    else:
        out["words"] = words

    return out


# -------- HTTP handler --------

class WhisperHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Quieter logs to stderr
        sys.stderr.write(f"  [whisper] {fmt % args}\n")

    def _json(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {
                "ok": True,
                "models_dir": str(MODELS_DIR),
                "models_present": sorted([p.stem for p in MODELS_DIR.glob("*.pt")]) if MODELS_DIR.exists() else [],
                "models_loaded": sorted(_loaded_models.keys()),
                "default_model": _default_model_name,
            })
        elif self.path == "/warmup":
            try:
                load_model(_default_model_name)
                self._json(200, {"ok": True, "model": _default_model_name})
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            req = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._json(400, {"ok": False, "error": f"bad JSON: {e}"})
            return

        if self.path == "/transcribe":
            audio_path = req.get("audio_path")
            if not audio_path or not Path(audio_path).exists():
                self._json(400, {"ok": False, "error": f"audio_path missing or not found: {audio_path}"})
                return
            try:
                result = perceive(
                    audio_path,
                    model_name=req.get("model", _default_model_name),
                    language=req.get("language"),
                    word_timestamps=req.get("word_timestamps", True),
                    with_spectral=req.get("spectral", True),
                    with_frames=req.get("frames", False),
                )
                result["ok"] = True
                self._json(200, result)
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})

        elif self.path == "/transcribe_bytes":
            b64 = req.get("audio_b64")
            ext = req.get("ext", "wav")
            if not b64:
                self._json(400, {"ok": False, "error": "audio_b64 required"})
                return
            try:
                audio_bytes = base64.b64decode(b64)
                with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tf:
                    tf.write(audio_bytes)
                    tmp_path = tf.name
                try:
                    result = perceive(
                        tmp_path,
                        model_name=req.get("model", _default_model_name),
                        language=req.get("language"),
                        word_timestamps=req.get("word_timestamps", True),
                        with_spectral=req.get("spectral", True),
                        with_frames=req.get("frames", False),
                    )
                    result["ok"] = True
                    self._json(200, result)
                finally:
                    try: os.unlink(tmp_path)
                    except: pass
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})

        else:
            self._json(404, {"ok": False, "error": "not found"})


# -------- Main --------

def main():
    global _default_model_name
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--model", default="small",
                   help="Default model: tiny, base, small, medium, large, large-v3, turbo")
    p.add_argument("--preload", action="store_true",
                   help="Load default model at startup (slower start, faster first request)")
    args = p.parse_args()

    _default_model_name = args.model

    print(f"  Sofia Whisper STT Server", file=sys.stderr)
    print(f"  ─────────────────────────", file=sys.stderr)
    print(f"  port: {args.port}", file=sys.stderr)
    print(f"  default model: {args.model}", file=sys.stderr)
    print(f"  models dir: {MODELS_DIR}", file=sys.stderr)
    if MODELS_DIR.exists():
        present = sorted([p.stem for p in MODELS_DIR.glob("*.pt")])
        print(f"  models present: {present if present else '(none — copy from ~/.cache/whisper/)'}", file=sys.stderr)
    else:
        print(f"  WARNING: models dir does not exist", file=sys.stderr)

    if args.preload:
        try:
            load_model(args.model)
        except Exception as e:
            print(f"  preload failed: {e}", file=sys.stderr)

    server = http.server.ThreadingHTTPServer((HOST, args.port), WhisperHandler)
    print(f"  ready: http://localhost:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  shutdown", file=sys.stderr)


if __name__ == "__main__":
    main()
