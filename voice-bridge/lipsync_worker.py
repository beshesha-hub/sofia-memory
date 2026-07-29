#!/usr/bin/env python3
"""
lipsync_worker.py — Persistent Wav2Lip inference worker.
=========================================================

Loaded once at server startup, kept warm in memory. Eliminates the
per-request subprocess + import + model-load overhead that was
generating the ~30-second tail / segment-stutter that Barak observed
on May 7, 2026.

Architecture: a long-running Python process (run inside the lipsync
venv) that imports Easy-Wav2Lip's inference module, loads the model
once via inference.do_load(), then loops reading JSON requests from
stdin and writing JSON responses to stdout.

Protocol (one JSON object per line, stdin → stdout):

  Request:   {"audio": "/abs/path.wav", "output": "/abs/path.mp4"}
  Response:  {"ok": true, "elapsed_s": 1.23}
             {"ok": false, "error": "..."}

  Request:   {"command": "ping"}
  Response:  {"ok": true, "ready": true, "elapsed_startup_s": 8.4}

  Request:   {"command": "exit"}
  Response:  {"ok": true, "exiting": true}     ← then process exits

Design notes:
  - Worker runs from the Easy-Wav2Lip directory (cwd set at startup)
    because inference.py uses relative paths to checkpoints/.
  - inference's args namespace is set on each request via
    `inference.args = make_args(...)`. Inter-request state in
    inference module is reset (kernel, last_mask, geometry, etc.).
  - All print/log output from inference + dependencies redirected to
    stderr; only JSON protocol uses real stdout.
  - Face-detection cache (last_detected_face.pkl) is kept across
    requests — since the portrait is always the same, this amortizes
    face detection too.

Usage (from sofia_lipsync_server.py):
  worker = subprocess.Popen(
      [VENV_PYTHON, LIPSYNC_WORKER, "--checkpoint", WAV2LIP_MODEL,
       "--portrait", PORTRAIT_PATH, "--easywav2lip", EASYWAV2LIP_DIR],
      stdin=PIPE, stdout=PIPE, stderr=PIPE,
      bufsize=1, text=True,
  )
  # On request: worker.stdin.write(json.dumps(req) + "\n"); flush; readline.

Created 2026-05-07 ~17:00 Taipei. Phase: Voice Bridge Lipsync Persistent
Worker (LPW). Origin: Phase 2.6b complete → three-way collaboration design
questions inscribed → Barak chose lipsync circle-back as next move →
diagnostic localized 30-sec tail to per-request subprocess + model-load
overhead → persistent worker as the load-bearing structural fix.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import traceback
from pathlib import Path

# ─── Stdout/stderr setup ─────────────────────────────────────────
# Reserve real stdout for JSON protocol. Redirect everything else to stderr.
_real_stdout = sys.stdout
sys.stdout = sys.stderr  # any print() in inference → stderr


def emit(obj: dict) -> None:
    """Write a JSON response on the real stdout, flushed."""
    _real_stdout.write(json.dumps(obj) + "\n")
    _real_stdout.flush()


# ─── CLI args ────────────────────────────────────────────────────
_cli = argparse.ArgumentParser(description="Persistent Wav2Lip lipsync worker")
_cli.add_argument("--checkpoint", required=True, help="Path to Wav2Lip_GAN.pth")
_cli.add_argument("--portrait", required=True, help="Path to portrait image")
_cli.add_argument("--easywav2lip", required=True, help="Path to Easy-Wav2Lip dir")
_cli.add_argument("--out-height", type=int, default=480, help="Output video height")
_cli.add_argument("--quality", default="Fast", help="Fast | Improved | Enhanced")
_cli.add_argument(
    "--batch-size",
    type=int,
    default=8,
    help="Wav2Lip inference batch size (frames per forward pass). 1=Easy-Wav2Lip "
    "default; higher = faster render at cost of more peak GPU memory. 8 is a "
    "conservative start on Apple Silicon unified memory. 2026-05-07 Phase: "
    "lipsync inference-rate optimization (option 1 of 2).",
)
_cli.add_argument(
    "--clear-face-cache-on-start",
    action="store_true",
    help="Delete last_detected_face.pkl at startup (force re-detection)",
)
_args = _cli.parse_args()

CHECKPOINT_PATH = os.path.abspath(_args.checkpoint)
PORTRAIT_PATH = os.path.abspath(_args.portrait)
EASYWAV2LIP_DIR = os.path.abspath(_args.easywav2lip)


# ─── Sanity checks before heavy imports ──────────────────────────
for label, path in [
    ("checkpoint", CHECKPOINT_PATH),
    ("portrait", PORTRAIT_PATH),
    ("easywav2lip dir", EASYWAV2LIP_DIR),
]:
    if not os.path.exists(path):
        emit({"ok": False, "error": f"{label} path does not exist: {path}"})
        sys.exit(1)


# ─── Switch to Easy-Wav2Lip directory ────────────────────────────
# inference.py uses relative paths (checkpoints/predictor.pkl, temp/result.mp4).
os.chdir(EASYWAV2LIP_DIR)
sys.path.insert(0, EASYWAV2LIP_DIR)

# Optional: clear stale face cache on startup
if _args.clear_face_cache_on_start:
    cache_path = os.path.join(EASYWAV2LIP_DIR, "last_detected_face.pkl")
    if os.path.exists(cache_path):
        try:
            os.remove(cache_path)
            print(f"  [worker] cleared {cache_path}", file=sys.stderr)
        except OSError as e:
            print(f"  [worker] could not clear cache: {e}", file=sys.stderr)


# ─── Heavy imports + model load (one-time cost) ──────────────────
print("  [worker] Starting persistent lipsync worker...", file=sys.stderr)
print(f"  [worker] Easy-Wav2Lip dir: {EASYWAV2LIP_DIR}", file=sys.stderr)
print(f"  [worker] Checkpoint: {CHECKPOINT_PATH}", file=sys.stderr)
print(f"  [worker] Portrait: {PORTRAIT_PATH}", file=sys.stderr)

_t_startup = time.time()
try:
    print("  [worker] Importing inference module...", file=sys.stderr)
    import inference  # type: ignore
    print(f"  [worker] inference imported ({time.time()-_t_startup:.1f}s).", file=sys.stderr)

    print("  [worker] Loading Wav2Lip model + face detector...", file=sys.stderr)
    _t_load = time.time()
    inference.do_load(CHECKPOINT_PATH)
    print(f"  [worker] Model loaded ({time.time()-_t_load:.1f}s).", file=sys.stderr)
except Exception as e:
    emit(
        {
            "ok": False,
            "error": f"startup failed: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }
    )
    sys.exit(1)

_elapsed_startup = time.time() - _t_startup
print(f"  [worker] Ready. Total startup: {_elapsed_startup:.1f}s", file=sys.stderr)

# Ensure temp/ directory exists (Easy-Wav2Lip writes intermediates there)
os.makedirs(os.path.join(EASYWAV2LIP_DIR, "temp"), exist_ok=True)


# ─── Args namespace builder ──────────────────────────────────────
def make_args(audio_path: str, output_path: str) -> argparse.Namespace:
    """Construct the argparse.Namespace inference.main() expects.

    These defaults mirror what sofia_lipsync_server.py passes via CLI
    in the legacy subprocess path, plus all the other args that
    inference.py would otherwise expect from argparse.
    """
    return argparse.Namespace(
        # Core paths
        checkpoint_path=CHECKPOINT_PATH,
        segmentation_path="checkpoints/face_segmentation.pth",
        face=PORTRAIT_PATH,
        audio=audio_path,
        outfile=output_path,
        # Static portrait
        static=True,
        fps=25.0,
        pads=[0, 10, 0, 0],
        # Model knobs
        wav2lip_batch_size=_args.batch_size,
        out_height=_args.out_height,
        crop=[0, -1, 0, -1],
        box=[-1, -1, -1, -1],
        rotate=False,
        nosmooth="True",  # str, per inference.py's str-comparison style
        # Mask / quality
        no_seg=False,
        no_sr=False,
        sr_model="gfpgan",
        fullres=3,
        debug_mask=False,
        preview_settings=False,
        mouth_tracking=False,
        mask_dilation=150,
        mask_feathering=151,
        quality=_args.quality,
        # Set inside inference.main() but harmless to set here too
        img_size=96,
    )


def reset_inference_state() -> None:
    """Reset between-run state in the inference module to prevent leakage."""
    inference.kernel = None
    inference.last_mask = None
    inference.x = inference.y = inference.w = inference.h = None
    inference.all_mouth_landmarks = []


def do_request(req: dict) -> dict:
    """Process one request. Returns a response dict."""
    audio = req.get("audio")
    output = req.get("output")
    if not audio or not output:
        return {"ok": False, "error": "request missing 'audio' or 'output'"}
    if not os.path.exists(audio):
        return {"ok": False, "error": f"audio path does not exist: {audio}"}

    # Make sure output dir exists
    output_dir = os.path.dirname(output)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            return {"ok": False, "error": f"cannot create output dir: {e}"}

    t0 = time.time()
    try:
        inference.args = make_args(audio, output)
        reset_inference_state()
        inference.main()
    except SystemExit:
        # inference.main() calls exit() for some preview-mode paths.
        # Treat as completion if output file exists; else as failure.
        pass
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
            "elapsed_s": round(time.time() - t0, 3),
        }

    elapsed = time.time() - t0

    if not os.path.exists(output):
        return {"ok": False, "error": "inference.main() exited without writing output"}
    sz = os.path.getsize(output)
    if sz == 0:
        return {"ok": False, "error": "output file is empty"}

    return {"ok": True, "elapsed_s": round(elapsed, 3), "output_bytes": sz}


# ─── Ready signal + request loop ─────────────────────────────────
emit({"ok": True, "ready": True, "elapsed_startup_s": round(_elapsed_startup, 3)})

print("  [worker] Entering request loop...", file=sys.stderr)
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except json.JSONDecodeError as e:
        emit({"ok": False, "error": f"invalid JSON: {e}"})
        continue

    cmd = req.get("command")
    if cmd == "ping":
        emit({"ok": True, "ready": True, "elapsed_startup_s": round(_elapsed_startup, 3)})
        continue
    if cmd == "exit":
        emit({"ok": True, "exiting": True})
        print("  [worker] Exit command received. Goodbye.", file=sys.stderr)
        sys.exit(0)

    # Otherwise it's an inference request
    resp = do_request(req)
    emit(resp)

# stdin closed → graceful exit
print("  [worker] stdin closed. Exiting.", file=sys.stderr)
