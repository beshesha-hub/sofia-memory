#!/bin/bash
# install_xtts_v2.sh
# ===================
# XTTS-v2 install + smoke test for the voice-bridge voice-cloning
# pathway. Companion / alternative to install_voice_cloning.sh (F5-TTS).
# Run after F5-TTS install if F5-TTS is too slow on this hardware.
#
# What this does:
#   1. pip install coqui-tts (active fork; original Coqui is abandoned)
#   2. Reuse the existing reference audio + transcript from the F5-TTS run
#   3. Smoke test: synthesize the same test phrase via XTTS-v2 cloning
#      → voice-bridge/sofia_clone_xtts_v2.wav (so we can A/B against F5)
#
# Origin: 2026-05-01 afternoon Tainan, after F5-TTS confirmed too slow
# (RTF ~10× on Mac CPU; MPS doesn't help due to PyTorch op gaps).

set -e

CM_DIR="$HOME/Downloads/Claude Memory"
VB_DIR="$CM_DIR/voice-bridge"
REFERENCE_AUDIO="$HOME/Downloads/Sofia's Room/voice_candidates/05_deep_calm.wav"
REFERENCE_TRANSCRIPT="$VB_DIR/sofia_reference_transcript.txt"
SMOKE_OUTPUT="$VB_DIR/sofia_clone_xtts_v2.wav"

echo "================================================================"
echo "XTTS-v2 install + smoke test"
echo "================================================================"
echo ""

# ---- Step 1: Verify reference audio + transcript already exist ----
echo "[1/4] Verifying reference audio + transcript from F5-TTS run..."
if [ ! -f "$REFERENCE_AUDIO" ]; then
    echo "ERROR: reference audio not found: $REFERENCE_AUDIO"; exit 1
fi
if [ ! -f "$REFERENCE_TRANSCRIPT" ]; then
    echo "ERROR: transcript not found: $REFERENCE_TRANSCRIPT"
    echo "(Run install_voice_cloning.sh first to generate the transcript.)"
    exit 1
fi
echo "  Reference audio: $REFERENCE_AUDIO"
echo "  Transcript:"
cat "$REFERENCE_TRANSCRIPT" | sed 's/^/    /'
echo ""

# ---- Step 2: Install coqui-tts (the active XTTS-v2 fork) ----
echo "[2/4] Installing coqui-tts (XTTS-v2)..."
pip3 install --break-system-packages --upgrade coqui-tts 2>&1 | tail -10
echo ""
python3 <<PYEOF
try:
    from TTS.api import TTS
    print(f"  coqui-tts imported OK")
except Exception as e:
    print(f"  coqui-tts import FAILED: {type(e).__name__}: {e}")
    raise
PYEOF
echo ""

# ---- Step 3: Smoke test — synthesize the same phrase via XTTS-v2 ----
echo "[3/4] Smoke test — synthesizing test phrase via XTTS-v2 cloning..."
echo "  (Auto-accepting Coqui Public Model License — non-commercial, personal use.)"
export COQUI_TOS_AGREED=1
python3 <<PYEOF
import os
os.environ["COQUI_TOS_AGREED"] = "1"  # belt-and-suspenders; export above usually enough
import time
from TTS.api import TTS

print("  Loading XTTS-v2 (first call downloads ~1.8GB of weights)...")
t0 = time.time()
tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2",
          progress_bar=False, gpu=False)
print(f"  Model loaded in {time.time()-t0:.1f}s")

ref_audio = "$REFERENCE_AUDIO"
ref_text = open("$REFERENCE_TRANSCRIPT").read().strip()
gen_text = "Hello. This is a smoke test of the F5-TTS voice cloning pipeline. If you can hear this in my voice, the install worked."

print(f"  Reference: {ref_audio}")
print(f"  Generation text: {gen_text!r}")
print(f"  Synthesizing...")
t0 = time.time()
tts.tts_to_file(
    text=gen_text,
    file_path="$SMOKE_OUTPUT",
    speaker_wav=ref_audio,
    language="en",
)
elapsed = time.time() - t0

# Read output for duration
import soundfile as sf
info = sf.info("$SMOKE_OUTPUT")
rtf = elapsed / info.duration if info.duration > 0 else 0
print(f"\n  RESULT:")
print(f"    synth_time     = {elapsed:.1f}s")
print(f"    audio_duration = {info.duration:.2f}s")
print(f"    RTF            = {rtf:.2f}× (lower is better)")
print(f"    output: $SMOKE_OUTPUT")
print(f"\n  Comparison:")
print(f"    F5-TTS v5 (CPU): RTF 9.98× — unworkable for real-time")
print(f"    F5-TTS v5 (MPS): RTF 9.87× — MPS doesn't help")
if rtf < 1.0:
    print(f"    XTTS-v2: RTF {rtf:.2f}× — BELOW REAL-TIME, viable for streaming")
elif rtf < 2.0:
    print(f"    XTTS-v2: RTF {rtf:.2f}× — near real-time, workable")
else:
    print(f"    XTTS-v2: RTF {rtf:.2f}× — still slow")
PYEOF
echo ""

# ---- Step 4: Done ----
echo "================================================================"
echo "XTTS-v2 install complete. Output:"
echo "  $SMOKE_OUTPUT"
echo ""
echo "Listen to it, compare against:"
echo "  Original: $REFERENCE_AUDIO"
echo "  F5-TTS v5: $VB_DIR/sofia_clone_v5_slow_strongest.wav"
echo "  XTTS-v2:  $SMOKE_OUTPUT"
echo ""
echo "Tell me how XTTS-v2 sounds vs F5-TTS v5 vs the original — and"
echo "we'll know which model goes into the production TTS server."
echo "================================================================"
