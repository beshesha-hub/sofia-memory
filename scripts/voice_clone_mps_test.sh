#!/bin/bash
# voice_clone_mps_test.sh
# ========================
# Forces F5-TTS onto Apple Silicon MPS (Metal Performance Shaders) and
# benchmarks v5 synthesis. Compares against the CPU-default time we
# already measured (~100s for ~10s of audio = RTF 10×).
#
# What this tells us:
#   - Does MPS work for F5-TTS at all? (some torch ops aren't MPS-supported)
#   - If yes, what's the speedup factor?
#   - Is the speedup enough to make v5 viable for real-time conversation?

set -e

CM_DIR="$HOME/Downloads/Claude Memory"
VB_DIR="$CM_DIR/voice-bridge"
REFERENCE_AUDIO="$HOME/Downloads/Sofia's Room/voice_candidates/05_deep_calm.wav"
REFERENCE_TRANSCRIPT="$VB_DIR/sofia_reference_transcript.txt"

echo "================================================================"
echo "F5-TTS — MPS (Apple Silicon GPU) acceleration test"
echo "================================================================"

python3 <<PYEOF
import time
import torch

# ---- 1. Probe MPS availability ----
print("[1/3] Checking MPS availability...")
print(f"  torch.backends.mps.is_available(): {torch.backends.mps.is_available()}")
print(f"  torch.backends.mps.is_built():     {torch.backends.mps.is_built()}")
if not torch.backends.mps.is_available():
    print("  MPS not available on this system. Aborting MPS test.")
    raise SystemExit(0)

# ---- 2. Try to load F5-TTS with explicit MPS device ----
print("\n[2/3] Loading F5-TTS with device='mps'...")
from f5_tts.api import F5TTS

t0 = time.time()
try:
    tts = F5TTS(device="mps")
    print(f"  F5TTS(device='mps') loaded in {time.time()-t0:.1f}s")
except Exception as e:
    print(f"  F5TTS(device='mps') FAILED: {type(e).__name__}: {e}")
    print(f"  Falling back to default-device load to verify CPU still works...")
    tts = F5TTS()
    print(f"  Default load OK in {time.time()-t0:.1f}s — MPS path is the issue")
    raise SystemExit(1)

# Inspect what device the underlying model actually ended up on
try:
    # F5TTS internals: ema_model holds the diffusion model
    sample_param = next(tts.ema_model.parameters())
    print(f"  Underlying model is on device: {sample_param.device}")
except Exception as e:
    print(f"  Could not introspect device: {e}")

# ---- 3. Run v5 synthesis on MPS, time it, compare to CPU ----
print("\n[3/3] Running v5 synthesis on MPS (speed=0.55, nfe_step=64, cfg_strength=3.0)...")
ref_text = open("$REFERENCE_TRANSCRIPT").read().strip()
gen_text = "Hello. This is a smoke test of the F5-TTS voice cloning pipeline. If you can hear this in my voice, the install worked."
out_path = "$VB_DIR/sofia_clone_v5_mps.wav"

t0 = time.time()
try:
    audio_data, samplerate, _ = tts.infer(
        ref_file="$REFERENCE_AUDIO",
        ref_text=ref_text,
        gen_text=gen_text,
        speed=0.55,
        nfe_step=64,
        cfg_strength=3.0,
        file_wave=out_path,
    )
    elapsed = time.time() - t0
    duration = len(audio_data) / float(samplerate)
    rtf = elapsed / duration
    print(f"\n  RESULT:")
    print(f"    synth_time   = {elapsed:.1f}s")
    print(f"    audio_duration = {duration:.2f}s")
    print(f"    RTF (synth/audio) = {rtf:.2f}× (lower is better)")
    print(f"    output: {out_path}")
    print(f"\n  Comparison:")
    print(f"    CPU v5 was: 100.0s synth / 10.02s audio = RTF 9.98×")
    cpu_rtf = 9.98
    speedup = cpu_rtf / rtf if rtf > 0 else 0
    print(f"    MPS speedup vs CPU: {speedup:.2f}× faster")
    if rtf < 1.0:
        print(f"    → BELOW REAL-TIME — viable for streaming conversation")
    elif rtf < 2.0:
        print(f"    → Near real-time — workable for thoughtful turns")
    else:
        print(f"    → Still slow — would need different strategy")
except Exception as e:
    print(f"  Synthesis on MPS FAILED: {type(e).__name__}: {e}")
    print(f"  This usually means a torch op isn't MPS-implemented.")
    print(f"  We'd need to switch to XTTS-v2 or run F5-TTS on CPU only.")
    raise
PYEOF

echo ""
echo "================================================================"
echo "Listen to sofia_clone_v5_mps.wav (if synthesis succeeded) — should"
echo "sound identical to v5 (same model, same params, just faster device)."
echo "================================================================"
