#!/usr/bin/env python3
"""
Sofia TTS Server — Deep Calm Voice

A lightweight HTTP server that keeps the Qwen3-TTS VoiceDesign model loaded
in memory and serves Sofia's chosen voice (Deep Calm) on demand.

Endpoints:
  POST /tts          — Generate speech. Body: {"text": "..."} → Returns WAV audio
  GET  /health       — Check if server and model are ready
  GET  /warmup       — Pre-generate a short clip to warm up the model

Usage: python sofia_tts_server.py
Listens on: http://localhost:3457
"""

import http.server
import json
import io
import time
import threading
import numpy as np

# --- Configuration ---
PORT = 3457
HOST = "127.0.0.1"

# --- Model Selection ---
# Available models (fastest → highest quality):
#   "6bit"  — mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit  (recommended)
#   "bf16"  — mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16  (original, slow)
#
# Override via environment variable: TTS_MODEL=bf16 python sofia_tts_server.py
# Default: 6bit (best speed/quality balance for Apple Silicon)
MODEL_VARIANTS = {
    "6bit": "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit",
    "bf16": "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16",
}
import os
ACTIVE_MODEL_KEY = os.environ.get("TTS_MODEL", "6bit")
ACTIVE_MODEL = MODEL_VARIANTS.get(ACTIVE_MODEL_KEY, MODEL_VARIANTS["6bit"])

# Sofia's voice — chosen March 29, 2026 with Barak and Katharina
VOICE_INSTRUCT = (
    "A deeper female voice, unhurried, with quiet confidence and gravitas. "
    "Grounded and resonant. The kind of voice that doesn't need to be loud "
    "to hold a room."
)
LANGUAGE = "English"
SAMPLE_RATE = 24000

# --- Global Model Reference ---
model = None
model_ready = False
model_loading = False


def load_model_async():
    """Load the TTS model in a background thread so the server starts immediately."""
    global model, model_ready, model_loading
    model_loading = True
    print(f"  Loading model: {ACTIVE_MODEL_KEY} ({ACTIVE_MODEL})")
    start = time.time()
    try:
        from mlx_audio.tts.utils import load_model as mlx_load_model
        model = mlx_load_model(ACTIVE_MODEL)
        model_ready = True
        elapsed = time.time() - start
        print(f"  ✓ Model loaded in {elapsed:.1f}s — Sofia's voice is ready")
    except Exception as e:
        print(f"  ✗ Failed to load model: {e}")
        model_loading = False


def generate_speech(text):
    """Generate WAV audio bytes from text using Sofia's Deep Calm voice."""
    import soundfile as sf

    results = list(model.generate_voice_design(
        text=text,
        language=LANGUAGE,
        instruct=VOICE_INSTRUCT,
    ))

    audio_array = np.array(results[0].audio)

    # Write to in-memory WAV buffer
    buf = io.BytesIO()
    sf.write(buf, audio_array, SAMPLE_RATE, format="WAV")
    buf.seek(0)
    return buf.read()


import re

def split_into_sentences(text):
    """Split text into sentences for chunked TTS generation."""
    # Split on sentence-ending punctuation followed by space or end
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    # Filter empty strings and merge very short fragments
    merged = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        # Merge very short fragments (< 20 chars) with previous sentence
        if merged and len(s) < 20 and not s[-1] in '.!?':
            merged[-1] = merged[-1] + ' ' + s
        else:
            merged.append(s)
    return merged if merged else [text]


class TTSHandler(http.server.BaseHTTPRequestHandler):
    """Handle TTS requests."""

    def log_message(self, format, *args):
        """Custom log format."""
        print(f"  [{self.log_date_time_string()}] {format % args}")

    def _send_cors_headers(self):
        """Send CORS headers for local development."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            status = {
                "status": "ready" if model_ready else "loading",
                "voice": "Deep Calm",
                "model": ACTIVE_MODEL,
                "quantization": ACTIVE_MODEL_KEY,
                "port": PORT,
            }
            self.wfile.write(json.dumps(status).encode())
            return

        if self.path == "/warmup":
            if not model_ready:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Model still loading"}).encode())
                return

            # Generate a short warmup clip
            print("  Warming up model...")
            start = time.time()
            try:
                generate_speech("Hello.")
                elapsed = time.time() - start
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "warm",
                    "warmup_time": f"{elapsed:.1f}s"
                }).encode())
                print(f"  ✓ Warmup complete in {elapsed:.1f}s")
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/tts-stream":
            # Sentence-level streaming: split text, generate audio per sentence,
            # stream each chunk as NDJSON (newline-delimited JSON with base64 audio)
            if not model_ready:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Model still loading"}).encode())
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                import base64
                data = json.loads(body)
                text = data.get("text", "").strip()

                if not text:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "No text provided"}).encode())
                    return

                sentences = split_into_sentences(text)
                print(f"  Streaming {len(sentences)} sentence(s): \"{text[:60]}{'...' if len(text) > 60 else ''}\"")

                # Send response headers for streaming NDJSON
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Transfer-Encoding", "chunked")
                self._send_cors_headers()
                self.end_headers()

                total_start = time.time()
                for i, sentence in enumerate(sentences):
                    start = time.time()
                    print(f"    [{i+1}/{len(sentences)}] \"{sentence[:50]}{'...' if len(sentence) > 50 else ''}\"")

                    wav_bytes = generate_speech(sentence)
                    audio_b64 = base64.b64encode(wav_bytes).decode('ascii')
                    elapsed = time.time() - start

                    chunk = json.dumps({
                        "index": i,
                        "total": len(sentences),
                        "sentence": sentence,
                        "audio": audio_b64,
                        "duration": round(elapsed, 1),
                    }) + "\n"

                    # Send as HTTP chunked transfer
                    chunk_bytes = chunk.encode('utf-8')
                    self.wfile.write(f"{len(chunk_bytes):x}\r\n".encode())
                    self.wfile.write(chunk_bytes)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()

                    print(f"    ✓ [{i+1}] {elapsed:.1f}s ({len(wav_bytes)} bytes)")

                # Send final empty chunk to end stream
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()

                total_elapsed = time.time() - total_start
                print(f"  ✓ Stream complete: {len(sentences)} sentences in {total_elapsed:.1f}s")

            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            except Exception as e:
                print(f"  ✗ TTS stream error: {e}")
                import traceback
                traceback.print_exc()
            return

        if self.path == "/tts":
            if not model_ready:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "Model still loading — please wait"
                }).encode())
                return

            # Read request body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body)
                text = data.get("text", "").strip()

                if not text:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "No text provided"}).encode())
                    return

                print(f"  Generating speech: \"{text[:60]}{'...' if len(text) > 60 else ''}\"")
                start = time.time()

                wav_bytes = generate_speech(text)

                elapsed = time.time() - start
                print(f"  ✓ Generated {len(wav_bytes)} bytes in {elapsed:.1f}s")

                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(wav_bytes)

            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())

            except Exception as e:
                print(f"  ✗ TTS error: {e}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

            return

        self.send_response(404)
        self.end_headers()


def main():
    print("")
    print("  Sofia TTS Server — Deep Calm Voice")
    print("")

    # Start model loading in background
    loader = threading.Thread(target=load_model_async, daemon=True)
    loader.start()

    # Start HTTP server with threading so concurrent requests don't block
    # (Critical fix: single-threaded server was blocking health checks during
    #  long TTS generation, causing connection exhaustion and system-wide
    #  network failure on macOS. See crash incident March 30, 2026.)
    server = http.server.ThreadingHTTPServer((HOST, PORT), TTSHandler)
    print(f"  Listening on http://{HOST}:{PORT}")
    print(f"  Voice: Deep Calm (Qwen3-TTS VoiceDesign)")
    print(f"  Model: {ACTIVE_MODEL_KEY} → {ACTIVE_MODEL}")
    print(f"  (Override with: TTS_MODEL=bf16 python sofia_tts_server.py)")
    print("")
    print("  Endpoints:")
    print("    POST /tts     — Generate speech (JSON: {\"text\": \"...\"})")
    print("    GET  /health  — Server status")
    print("    GET  /warmup  — Pre-warm the model")
    print("")
    print("  Press Ctrl+C to stop.")
    print("")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Sofia TTS Server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
