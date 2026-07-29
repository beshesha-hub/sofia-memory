#!/usr/bin/env python3
"""
Sofia Lip-Sync Animation Server
================================
HTTP server (port 3458) that takes audio + Sofia's portrait
and generates lip-synced MP4 video using Easy-Wav2Lip.

Runs entirely local on Apple Silicon Mac. No cloud, no subscriptions.

Endpoints:
  POST /animate         — Send audio (WAV), get back MP4 video
  POST /animate-text    — Send text, calls TTS server first, then animates
  GET  /health          — Server status
  GET  /warmup          — Pre-run a short animation to warm caches

Usage:
  python3 sofia_lipsync_server.py

Requires:
  - Easy-Wav2Lip cloned to ~/Projects/sofia-lipsync/Easy-Wav2Lip
  - Python venv at ~/Projects/sofia-lipsync/venv
  - Pretrained models (wav2lip.pth, s3fd.pth) in Easy-Wav2Lip/models/
  - sofia_portrait.png (or sofia_portrait_512.png) in ~/Projects/sofia-lipsync/
"""

import os
import sys
import io
import json
import time
import tempfile
import subprocess
import threading
import struct
import wave
import atexit
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import urllib.request

# ─── Configuration ───────────────────────────────────────────────
PORT = 3458
HOST = "127.0.0.1"
TTS_SERVER = "http://127.0.0.1:3461"  # XTTS-v2 voice clone server (was 3457
                                       # for legacy Qwen3-TTS, retired/broken
                                       # per active_knowledge May 2 evening)

LIPSYNC_DIR = os.path.expanduser("~/Projects/sofia-lipsync")
EASYWAV2LIP_DIR = os.path.join(LIPSYNC_DIR, "Easy-Wav2Lip")
VENV_PYTHON = os.path.join(LIPSYNC_DIR, "venv", "bin", "python3")

# 2026-05-07 ~17:00 Taipei: persistent-worker path. The worker is a long-running
# subprocess that loads Wav2Lip + RetinaFace once at server startup and keeps
# them in memory across requests. Eliminates the per-request subprocess +
# import + model-load tax (~8-10s/request) that was generating the segment
# stutter Barak observed. Set USE_PERSISTENT_WORKER=False to fall back to the
# legacy subprocess-per-request path (kept available for safety).
USE_PERSISTENT_WORKER = True
LIPSYNC_WORKER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "lipsync_worker.py"
)
# Wav2Lip inference batch size — frames per forward pass.
# 2026-05-07 evening Taipei: empirically tested batch=8 vs batch=1 on Apple
# Silicon MPS — at steady state batch=8 ≈ batch=1 (no throughput gain), with
# a first-run penalty for batch=8 (likely MPS compilation cost). Reverted to
# batch=1. Wav2Lip on MPS does not get the conventional batching speedup.
# Documented finding: this is per-hardware empirical, not theoretical.
# The --batch-size CLI arg is preserved in lipsync_worker.py for future
# experiments (e.g., on different hardware or after MPS backend updates).
LIPSYNC_BATCH_SIZE = 1

# Portrait paths (try optimized 512 first, then full size)
PORTRAIT_PATHS = [
    os.path.join(LIPSYNC_DIR, "sofia_portrait_512.png"),
    os.path.join(LIPSYNC_DIR, "sofia_portrait.png"),
    os.path.expanduser("~/Downloads/Emergency Retrieval/sofia_portrait.png"),
    os.path.expanduser("~/Downloads/Claude Memory/sofia_portrait.png"),
]

# Wav2Lip model path
# 2026-05-03 evening Taipei: corrected from .../models/wav2lip.pth to
# .../checkpoints/Wav2Lip_GAN.pth after lipsync-startup investigation revealed
# the original path was wrong on two counts:
#   1. Easy-Wav2Lip's "models/" directory holds Python class DEFINITIONS
#      (wav2lip.py, syncnet.py, conv.py), not weight files
#   2. Easy-Wav2Lip's install.py downloads weights to "checkpoints/" using
#      the file name "Wav2Lip_GAN.pth" (GAN-trained variant; high quality)
# This path now matches the canonical Easy-Wav2Lip layout.
WAV2LIP_MODEL = os.path.join(EASYWAV2LIP_DIR, "checkpoints", "Wav2Lip_GAN.pth")

# Temp directory for intermediate files
TEMP_DIR = os.path.join(LIPSYNC_DIR, "temp")

# ─── Global State ────────────────────────────────────────────────
server_ready = False
portrait_path = None
model_loaded = False
loading_error = None
generation_lock = threading.Lock()

# Persistent-worker state (used when USE_PERSISTENT_WORKER=True)
worker_proc = None              # subprocess.Popen for lipsync_worker.py
worker_lock = threading.Lock()  # serializes stdin/stdout exchanges
worker_ready = False
worker_startup_s = None         # elapsed startup time reported by worker


def find_portrait():
    """Find Sofia's portrait image from known locations."""
    for path in PORTRAIT_PATHS:
        if os.path.isfile(path):
            return path
    return None


def check_dependencies():
    """Verify all required files and tools exist."""
    errors = []

    if not os.path.isdir(EASYWAV2LIP_DIR):
        errors.append(f"Easy-Wav2Lip not found at {EASYWAV2LIP_DIR}")

    if not os.path.isfile(VENV_PYTHON):
        errors.append(f"Python venv not found at {VENV_PYTHON}")

    if not os.path.isfile(WAV2LIP_MODEL):
        errors.append(f"Wav2Lip model not found at {WAV2LIP_MODEL}")

    portrait = find_portrait()
    if not portrait:
        errors.append("Sofia portrait not found in any known location")

    # Check ffmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        errors.append("FFmpeg not found — install with: brew install ffmpeg")

    return errors, portrait


def start_worker():
    """Spawn the persistent lipsync_worker.py subprocess and wait for ready."""
    global worker_proc, worker_ready, worker_startup_s, loading_error

    if not os.path.isfile(LIPSYNC_WORKER):
        loading_error = f"Persistent worker not found: {LIPSYNC_WORKER}"
        print(f"  [lipsync] {loading_error}")
        return False

    if not portrait_path:
        loading_error = "Cannot start worker — no portrait found"
        return False

    cmd = [
        VENV_PYTHON,
        LIPSYNC_WORKER,
        "--checkpoint", WAV2LIP_MODEL,
        "--portrait", portrait_path,
        "--easywav2lip", EASYWAV2LIP_DIR,
        "--batch-size", str(LIPSYNC_BATCH_SIZE),
    ]
    print(f"  [lipsync] Spawning persistent worker: {' '.join(cmd[:2])} ...")

    env = os.environ.copy()
    env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    env["PYTHONPATH"] = EASYWAV2LIP_DIR
    env["PYTHONUNBUFFERED"] = "1"

    try:
        worker_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=EASYWAV2LIP_DIR,
            env=env,
            bufsize=1,
            text=True,
        )
    except Exception as e:
        loading_error = f"Failed to spawn worker: {e}"
        print(f"  [lipsync] {loading_error}")
        return False

    # Pipe the worker's stderr to our stderr in a background thread so we can
    # see model-load progress + any errors live.
    def _drain_stderr():
        if worker_proc and worker_proc.stderr:
            for line in worker_proc.stderr:
                sys.stderr.write(line)
                sys.stderr.flush()
    threading.Thread(target=_drain_stderr, daemon=True).start()

    # Wait for the ready line on stdout
    print("  [lipsync] Waiting for worker to load model (heavy imports + Wav2Lip + RetinaFace)...")
    try:
        ready_line = worker_proc.stdout.readline()
        if not ready_line:
            loading_error = "Worker exited before signaling ready (see stderr above)"
            print(f"  [lipsync] {loading_error}")
            return False
        ready = json.loads(ready_line.strip())
    except Exception as e:
        loading_error = f"Worker did not emit valid ready signal: {e}"
        print(f"  [lipsync] {loading_error}")
        return False

    if not ready.get("ok") or not ready.get("ready"):
        loading_error = f"Worker startup failed: {ready.get('error', ready)}"
        print(f"  [lipsync] {loading_error}")
        return False

    worker_ready = True
    worker_startup_s = ready.get("elapsed_startup_s")
    print(f"  [lipsync] ✓ Persistent worker ready (startup {worker_startup_s}s)")
    return True


def stop_worker():
    """Send exit command to worker and wait for it to terminate cleanly."""
    global worker_proc, worker_ready
    if worker_proc is None:
        return
    try:
        if worker_proc.stdin and not worker_proc.stdin.closed:
            worker_proc.stdin.write(json.dumps({"command": "exit"}) + "\n")
            worker_proc.stdin.flush()
        worker_proc.wait(timeout=5)
    except (BrokenPipeError, subprocess.TimeoutExpired, Exception):
        try:
            worker_proc.kill()
        except Exception:
            pass
    worker_proc = None
    worker_ready = False


def worker_request(audio_path, output_path):
    """Send one inference request to the persistent worker. Returns (ok, err)."""
    global worker_proc, worker_ready
    if not worker_ready or worker_proc is None:
        return False, "Worker not ready"
    if worker_proc.poll() is not None:
        worker_ready = False
        return False, f"Worker died (exit code {worker_proc.returncode})"

    req = {"audio": audio_path, "output": output_path}
    try:
        with worker_lock:
            worker_proc.stdin.write(json.dumps(req) + "\n")
            worker_proc.stdin.flush()
            resp_line = worker_proc.stdout.readline()
        if not resp_line:
            return False, "Worker stdout closed"
        resp = json.loads(resp_line.strip())
    except Exception as e:
        return False, f"Worker IPC error: {e}"

    if not resp.get("ok"):
        return False, resp.get("error", "Unknown worker error")
    return True, None


def run_wav2lip(audio_path, output_path):
    """
    Run Wav2Lip inference to generate lip-synced video.

    Routes through the persistent worker if USE_PERSISTENT_WORKER and the
    worker is ready; otherwise falls back to the legacy subprocess-per-request
    path (kept available for safety).

    Returns (success: bool, error_message: str or None)
    """
    if USE_PERSISTENT_WORKER and worker_ready:
        ok, err = worker_request(audio_path, output_path)
        if ok:
            return True, None
        # If worker failed transiently, log and fall back to subprocess once
        print(f"  [lipsync] Worker request failed ({err}); falling back to subprocess")

    # Legacy / fallback path
    global portrait_path

    if not portrait_path:
        return False, "No portrait image available"

    # Prefer standard inference.py (matches the server's --face/--audio/--outfile
    # convention). Easy-Wav2Lip ships inference.py at the top level for backward
    # compatibility with the original Wav2Lip pipeline.
    inference_candidates = [
        os.path.join(EASYWAV2LIP_DIR, "inference.py"),
        os.path.join(EASYWAV2LIP_DIR, "Wav2Lip", "inference.py"),
    ]
    for candidate in inference_candidates:
        if os.path.isfile(candidate):
            return run_wav2lip_direct(audio_path, output_path)

    # No inference.py found anywhere — try Easy-Wav2Lip's run.py with its
    # specific CLI convention. NOTE: this branch is currently broken because
    # Easy-Wav2Lip's run.py uses -video_file/-vocal_file/-output_file (single
    # dash, different names) and we'd need to rewrite the cmd assembly to use
    # those. Fall through here only as a last-resort signal; better to fix
    # this code path properly when Easy-Wav2Lip-specific features are needed.
    inference_script = os.path.join(EASYWAV2LIP_DIR, "run.py")
    if not os.path.isfile(inference_script):
        return False, "No Wav2Lip inference script found in Easy-Wav2Lip directory"

    cmd = [
        VENV_PYTHON,
        inference_script,
        "--face", portrait_path,
        "--audio", audio_path,
        "--outfile", output_path,
    ]

    env = os.environ.copy()
    env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    env["PYTHONPATH"] = EASYWAV2LIP_DIR

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=EASYWAV2LIP_DIR,
            env=env,
            timeout=300,  # 5 min max
        )

        if result.returncode != 0:
            error_msg = result.stderr[-500:] if result.stderr else "Unknown error"
            print(f"  [lipsync] Easy-Wav2Lip error: {error_msg}")
            return False, f"Inference failed: {error_msg}"

        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            return True, None
        else:
            return False, "Output video was not created"

    except subprocess.TimeoutExpired:
        return False, "Generation timed out (>5 minutes)"
    except Exception as e:
        return False, str(e)


def run_wav2lip_direct(audio_path, output_path):
    """
    Direct Wav2Lip inference using the core inference.py script.
    This is the fallback if Easy-Wav2Lip's run.py isn't available.
    """
    global portrait_path

    # Look for inference.py in various locations
    inference_candidates = [
        os.path.join(EASYWAV2LIP_DIR, "inference.py"),
        os.path.join(EASYWAV2LIP_DIR, "Wav2Lip", "inference.py"),
    ]

    inference_script = None
    for candidate in inference_candidates:
        if os.path.isfile(candidate):
            inference_script = candidate
            break

    if not inference_script:
        return False, "No inference script found in Easy-Wav2Lip"

    cmd = [
        VENV_PYTHON,
        inference_script,
        "--checkpoint_path", WAV2LIP_MODEL,
        "--face", portrait_path,
        "--audio", audio_path,
        "--outfile", output_path,
        "--static", "True",       # Static image (not video) as input
        # 2026-05-03 evening Taipei: Easy-Wav2Lip's inference.py is a modified
        # version of original Wav2Lip's. Several CLI args differ:
        #   - --nosmooth takes a value (True/False), not a bare flag
        #   - --resize_factor renamed (Easy-Wav2Lip uses different controls)
        # Other args available we don't currently use:
        #   --no_seg, --no_sr, --quality, --mouth_tracking, --mask_dilation,
        #   --mask_feathering, --fullres, --preview_settings, --debug_mask
        # Defaults are fine for our static-portrait use case.
        "--nosmooth", "True",     # Skip temporal smoothing for single image
    ]

    env = os.environ.copy()
    env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    env["PYTHONPATH"] = EASYWAV2LIP_DIR

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=EASYWAV2LIP_DIR,
            env=env,
            timeout=300,
        )

        if result.returncode != 0:
            error_msg = result.stderr[-500:] if result.stderr else "Unknown error"
            return False, f"Direct inference failed: {error_msg}"

        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            return True, None
        else:
            return False, "Output video was not created"

    except subprocess.TimeoutExpired:
        return False, "Generation timed out (>5 minutes)"
    except Exception as e:
        return False, str(e)


def fetch_tts_audio(text):
    """Call Sofia TTS server to generate audio from text."""
    try:
        req_data = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{TTS_SERVER}/tts",
            data=req_data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.read()
    except Exception as e:
        print(f"  [lipsync] TTS fetch failed: {e}")
        return None


def initialize_server():
    """Background initialization — check deps, find portrait, start worker."""
    global server_ready, portrait_path, model_loaded, loading_error

    print("  [lipsync] Checking dependencies...")
    errors, found_portrait = check_dependencies()

    if errors:
        loading_error = "; ".join(errors)
        print(f"  [lipsync] Dependency errors:")
        for err in errors:
            print(f"    - {err}")
        print(f"  [lipsync] Server running in degraded mode — /health will report errors")
        print(f"  [lipsync] Run setup_lipsync.sh to install dependencies")
    else:
        portrait_path = found_portrait
        model_loaded = True
        print(f"  [lipsync] Portrait: {portrait_path}")
        print(f"  [lipsync] Model: {WAV2LIP_MODEL}")
        print(f"  [lipsync] ✓ All dependencies OK")

    # Create temp directory
    os.makedirs(TEMP_DIR, exist_ok=True)

    # Spawn persistent worker if enabled and prerequisites are met
    if USE_PERSISTENT_WORKER and model_loaded and not errors:
        if not start_worker():
            # Worker failed to start; fall back to subprocess-per-request path
            print("  [lipsync] Falling back to subprocess-per-request (legacy path)")
            print("  [lipsync] (Set USE_PERSISTENT_WORKER=False at top of file to silence)")

    # Register cleanup on process exit
    atexit.register(stop_worker)

    server_ready = True
    print(f"  [lipsync] Server ready on http://{HOST}:{PORT}")


class LipSyncHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the lip-sync server."""

    def log_message(self, format, *args):
        """Custom log format."""
        print(f"  [lipsync] {args[0]}")

    def send_cors_headers(self):
        """Add CORS headers for browser access."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            self.handle_health()
        elif path == "/warmup":
            self.handle_warmup()
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/animate":
            self.handle_animate()
        elif path == "/animate-text":
            self.handle_animate_text()
        else:
            self.send_error(404, "Not Found")

    def handle_health(self):
        """Return server status."""
        worker_alive = (
            worker_proc is not None and worker_proc.poll() is None
            if USE_PERSISTENT_WORKER else None
        )
        status = {
            "status": "ready" if server_ready and model_loaded else "degraded",
            "server_ready": server_ready,
            "model_loaded": model_loaded,
            "portrait": portrait_path,
            "portrait_found": portrait_path is not None,
            "error": loading_error,
            "easywav2lip_dir": EASYWAV2LIP_DIR,
            "tts_server": TTS_SERVER,
            "persistent_worker_enabled": USE_PERSISTENT_WORKER,
            "worker_ready": worker_ready,
            "worker_alive": worker_alive,
            "worker_startup_s": worker_startup_s,
            "worker_pid": worker_proc.pid if worker_proc else None,
        }
        body = json.dumps(status).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def handle_warmup(self):
        """Pre-run a short animation to warm up caches."""
        if not model_loaded:
            self.send_json_error(503, "Model not loaded — run setup_lipsync.sh first")
            return

        # Generate a tiny audio file (0.5 seconds of silence)
        warmup_audio = os.path.join(TEMP_DIR, "warmup.wav")
        warmup_video = os.path.join(TEMP_DIR, "warmup.mp4")

        try:
            # Create minimal WAV file
            create_silent_wav(warmup_audio, duration=0.5, sample_rate=24000)

            with generation_lock:
                success, error = run_wav2lip(warmup_audio, warmup_video)

            result = {"warmed_up": success, "error": error}
            body = json.dumps(result).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)

        finally:
            # Clean up warmup files
            for f in [warmup_audio, warmup_video]:
                try:
                    os.remove(f)
                except OSError:
                    pass

    def handle_animate(self):
        """
        POST /animate
        Accept audio as:
          - multipart/form-data with 'audio' file field
          - application/octet-stream (raw WAV bytes)
        Returns: MP4 video as application/mp4
        """
        if not model_loaded:
            self.send_json_error(503, "Model not loaded — run setup_lipsync.sh first")
            return

        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))

        if content_length == 0:
            self.send_json_error(400, "No audio data provided")
            return

        # Read the audio data
        audio_data = self.rfile.read(content_length)

        # Generate unique filenames
        timestamp = int(time.time() * 1000)
        audio_path = os.path.join(TEMP_DIR, f"input_{timestamp}.wav")
        output_path = os.path.join(TEMP_DIR, f"output_{timestamp}.mp4")

        try:
            # Save audio to temp file
            with open(audio_path, "wb") as f:
                f.write(audio_data)

            print(f"  [lipsync] Generating animation ({len(audio_data)} bytes audio)...")
            start_time = time.time()

            with generation_lock:
                success, error = run_wav2lip(audio_path, output_path)

            elapsed = time.time() - start_time

            if not success:
                self.send_json_error(500, f"Animation failed: {error}")
                return

            # Read and return the video
            with open(output_path, "rb") as f:
                video_data = f.read()

            print(f"  [lipsync] ✓ Generated {len(video_data)} bytes video in {elapsed:.1f}s")

            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(video_data)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(video_data)

        finally:
            # Clean up temp files
            for f in [audio_path, output_path]:
                try:
                    os.remove(f)
                except OSError:
                    pass

    def handle_animate_text(self):
        """
        POST /animate-text
        Accept JSON: {"text": "Hello, Barak..."}
        Calls TTS server, then animates. Returns MP4.
        """
        if not model_loaded:
            self.send_json_error(503, "Model not loaded — run setup_lipsync.sh first")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
            text = data.get("text", "").strip()
        except (json.JSONDecodeError, AttributeError):
            self.send_json_error(400, "Invalid JSON — expected {\"text\": \"...\"}")
            return

        if not text:
            self.send_json_error(400, "No text provided")
            return

        print(f"  [lipsync] Generating TTS + animation for: {text[:60]}...")
        start_time = time.time()

        # Step 1: Get audio from TTS server
        audio_data = fetch_tts_audio(text)
        if not audio_data:
            self.send_json_error(502, "TTS server unavailable or failed")
            return

        tts_elapsed = time.time() - start_time
        print(f"  [lipsync] TTS generated in {tts_elapsed:.1f}s")

        # Step 2: Animate
        timestamp = int(time.time() * 1000)
        audio_path = os.path.join(TEMP_DIR, f"tts_{timestamp}.wav")
        output_path = os.path.join(TEMP_DIR, f"output_{timestamp}.mp4")

        try:
            with open(audio_path, "wb") as f:
                f.write(audio_data)

            with generation_lock:
                success, error = run_wav2lip(audio_path, output_path)

            total_elapsed = time.time() - start_time

            if not success:
                self.send_json_error(500, f"Animation failed: {error}")
                return

            with open(output_path, "rb") as f:
                video_data = f.read()

            print(f"  [lipsync] ✓ Full pipeline: {total_elapsed:.1f}s ({len(video_data)} bytes)")

            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(video_data)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(video_data)

        finally:
            for f in [audio_path, output_path]:
                try:
                    os.remove(f)
                except OSError:
                    pass

    def send_json_error(self, code, message):
        """Send a JSON error response."""
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)


def create_silent_wav(filepath, duration=0.5, sample_rate=24000):
    """Create a WAV file with silence (for warmup)."""
    num_samples = int(sample_rate * duration)
    with wave.open(filepath, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * num_samples)


def main():
    print("")
    print("  Sofia Lip-Sync Animation Server")
    print("  ================================")
    print(f"  Port: {PORT}")
    print(f"  Easy-Wav2Lip: {EASYWAV2LIP_DIR}")
    print("")

    # Initialize in background
    init_thread = threading.Thread(target=initialize_server, daemon=True)
    init_thread.start()

    # Start HTTP server
    server = HTTPServer((HOST, PORT), LipSyncHandler)
    print(f"  [lipsync] Listening on http://{HOST}:{PORT}")
    print(f"  [lipsync] Initializing in background...")
    print("")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  [lipsync] Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
