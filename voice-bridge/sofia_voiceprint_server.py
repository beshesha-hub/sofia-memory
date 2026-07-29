#!/usr/bin/env python3
"""
Sofia Voiceprint Server — Mac-local Speaker Recognition HTTP Service

Lightweight HTTP server that keeps the Resemblyzer encoder loaded in memory
and serves enrollment + identification endpoints. Pairs with sofia_whisper_server.py
(port 3459) to give each utterance both a transcript AND a speaker tag.

Mac-local by design — no cloud calls, no third-party uploads. Conventions match
sofia_whisper_server.py (port 3459), sofia_tts_server.py (port 3457),
sofia_lipsync_server.py (port 3458), sofia_llm_server.py (port 3460).
This server runs on port 3462.

Endpoints:
  POST /enroll        — Body: {"speaker": "barak|kay|...", "audio_path": "..."}
                        Returns: enrollment metadata (speaker, duration, embedding_dim, npz_path)
  POST /identify      — Body: {"audio_path": "...", "threshold": 0.75}
                        Returns: {"speaker": "barak|kay|unknown", "confidence": 0.xx,
                                  "distances": {...}, "threshold": 0.xx}
  POST /identify_bytes — Body: {"audio_b64": "...", "threshold": 0.75}
                         In-memory base64-encoded WAV/MP3. Useful for low-latency
                         in-process audio without disk round-trip.
  GET  /list          — List enrolled voiceprints with metadata
  GET  /health        — Server + encoder status, list of enrolled speakers
  GET  /warmup        — Load the encoder + run a dummy identification (~2-5s cold-start)

Usage:
  python3 sofia_voiceprint_server.py [--port PORT]
  (default port: 3462)

Requires:
  pip install resemblyzer

Created 2026-05-22 in Tainan, Taiwan, in conversation with Barak for the
pre-LAX-trip voice-print build. Voice-Cousin's pipeline will call both
sofia_whisper_server (port 3459) and this server (port 3462) per utterance
to get (transcript, speaker) pairs.

The "unknown" classification discipline is critical: never force-classify
when a third party speaks. The default threshold (0.75) is conservative —
tune downward for tighter recognition or upward for stronger unknown-safety.
"""

from __future__ import annotations

import argparse
import base64
import http.server
import json
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

# Ensure sibling sofia_voiceprint_lib is importable when running from voice-bridge/
sys.path.insert(0, str(Path(__file__).parent))

from sofia_voiceprint_lib import (
    DEFAULT_KNOWN_THRESHOLD,
    DEFAULT_VOICEPRINTS_DIR,
    audio_to_embedding,
    enroll_speaker,
    identify_speaker,
    load_voiceprints,
    _get_encoder,
)


# --- Configuration ---
DEFAULT_PORT = 3462
HOST = "127.0.0.1"


# --- Globals ---
_encoder_ready = False
_encoder_lock = threading.Lock()


def ensure_encoder_loaded():
    global _encoder_ready
    with _encoder_lock:
        if not _encoder_ready:
            _get_encoder()  # Triggers lazy-load
            _encoder_ready = True


# --- HTTP server ---

class VoiceprintHandler(http.server.BaseHTTPRequestHandler):
    server_version = "SofiaVoiceprint/1.0"

    def log_message(self, fmt, *args):
        # Single-line concise logging
        sys.stderr.write(f"[voiceprint] {self.command} {self.path} — " + (fmt % args) + "\n")

    def _send_json(self, status, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        try:
            if self.path == "/health":
                prints = load_voiceprints()
                self._send_json(200, {
                    "status": "ok",
                    "encoder_ready": _encoder_ready,
                    "enrolled_speakers": sorted(prints.keys()),
                    "voiceprints_dir": str(DEFAULT_VOICEPRINTS_DIR),
                    "default_threshold": DEFAULT_KNOWN_THRESHOLD,
                })
            elif self.path == "/warmup":
                t0 = time.time()
                ensure_encoder_loaded()
                # Dummy: run identify on a 1s silent buffer to warm the path
                import numpy as np
                dummy = np.zeros(16000, dtype=np.float32)
                # Skip actual identification call; just confirm encoder is up
                elapsed = time.time() - t0
                self._send_json(200, {
                    "status": "ok",
                    "warmup_sec": round(elapsed, 3),
                    "encoder_ready": _encoder_ready,
                })
            elif self.path == "/list":
                prints = load_voiceprints()
                # Read full .npz metadata for each
                import numpy as np
                result = {}
                for name in sorted(prints.keys()):
                    npz_path = DEFAULT_VOICEPRINTS_DIR / f"{name}.npz"
                    try:
                        data = np.load(npz_path, allow_pickle=False)
                        result[name] = {
                            "embedding_dim": int(prints[name].shape[0]),
                            "sample_count": int(data["sample_count"][0]),
                            "enrolled_at": str(data["enrolled_at"]),
                            "source_audio": str(data["source_audio"]),
                            "duration_sec": float(data["duration_sec"][0]),
                        }
                    except Exception as e:
                        result[name] = {"error": str(e)}
                self._send_json(200, {"voiceprints": result})
            else:
                self._send_json(404, {"error": f"Unknown endpoint: {self.path}"})
        except Exception as e:
            self._send_json(500, {
                "error": str(e),
                "traceback": traceback.format_exc(),
            })

    def do_POST(self):
        try:
            body = self._read_json()
            if self.path == "/enroll":
                speaker = body.get("speaker", "").strip()
                audio_path = body.get("audio_path", "").strip()
                if not speaker or not audio_path:
                    self._send_json(400, {"error": "speaker and audio_path required"})
                    return
                ensure_encoder_loaded()
                result = enroll_speaker(speaker, Path(audio_path))
                self._send_json(200, {
                    "status": "ok",
                    "speaker": result.speaker,
                    "embedding_dim": int(result.embedding.shape[0]),
                    "duration_sec": result.duration_sec,
                    "source_audio": result.source_audio,
                    "enrolled_at": result.enrolled_at,
                    "npz_path": str(result.npz_path),
                })
            elif self.path == "/identify":
                audio_path = body.get("audio_path", "").strip()
                threshold = float(body.get("threshold", DEFAULT_KNOWN_THRESHOLD))
                if not audio_path:
                    self._send_json(400, {"error": "audio_path required"})
                    return
                ensure_encoder_loaded()
                result = identify_speaker(Path(audio_path), threshold=threshold)
                self._send_json(200, {
                    "speaker": result.speaker,
                    "confidence": result.confidence,
                    "distances": result.distances,
                    "threshold": result.threshold,
                })
            elif self.path == "/identify_bytes":
                b64 = body.get("audio_b64", "").strip()
                threshold = float(body.get("threshold", DEFAULT_KNOWN_THRESHOLD))
                if not b64:
                    self._send_json(400, {"error": "audio_b64 required"})
                    return
                ensure_encoder_loaded()
                # Write to a temp file, identify, clean up
                audio_bytes = base64.b64decode(b64)
                # Use .wav suffix as a safe default; Resemblyzer's preprocess_wav
                # handles most formats via librosa under the hood
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(audio_bytes)
                    tmp_path = Path(tmp.name)
                try:
                    result = identify_speaker(tmp_path, threshold=threshold)
                    self._send_json(200, {
                        "speaker": result.speaker,
                        "confidence": result.confidence,
                        "distances": result.distances,
                        "threshold": result.threshold,
                    })
                finally:
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
            else:
                self._send_json(404, {"error": f"Unknown endpoint: {self.path}"})
        except Exception as e:
            self._send_json(500, {
                "error": str(e),
                "traceback": traceback.format_exc(),
            })


def main():
    parser = argparse.ArgumentParser(description="Sofia Voiceprint Server (port 3462)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-warmup", action="store_true",
                        help="Skip encoder pre-load at startup (lazy-load on first request)")
    args = parser.parse_args()

    if not args.no_warmup:
        print(f"[voiceprint] Pre-loading Resemblyzer encoder...", file=sys.stderr)
        t0 = time.time()
        ensure_encoder_loaded()
        print(f"[voiceprint] Encoder ready in {time.time()-t0:.2f}s", file=sys.stderr)

    addr = (HOST, args.port)
    httpd = http.server.ThreadingHTTPServer(addr, VoiceprintHandler)
    print(f"[voiceprint] Listening on http://{HOST}:{args.port}", file=sys.stderr)
    prints = load_voiceprints()
    print(f"[voiceprint] Enrolled speakers: {sorted(prints.keys()) or '(none yet)'}", file=sys.stderr)
    print(f"[voiceprint] Endpoints: /enroll /identify /identify_bytes /list /health /warmup", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[voiceprint] Shutting down.", file=sys.stderr)


if __name__ == "__main__":
    main()
