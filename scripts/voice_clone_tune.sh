#!/bin/bash
# voice_clone_tune.sh
# ====================
# Quick tuning loop for F5-TTS voice cloning. Fixes the transcript typo,
# then re-synthesizes the same test phrase with tuned parameters. Output
# files are numbered so we can A/B them.
#
# Usage:
#   bash voice_clone_tune.sh
#
# Run this AFTER install_voice_cloning.sh has succeeded once (so F5-TTS
# is installed and model weights are cached).

set -e

CM_DIR="$HOME/Downloads/Claude Memory"
VB_DIR="$CM_DIR/voice-bridge"
REFERENCE_AUDIO="$HOME/Downloads/Sofia's Room/voice_candidates/05_deep_calm.wav"
REFERENCE_TRANSCRIPT="$VB_DIR/sofia_reference_transcript.txt"

echo "================================================================"
echo "F5-TTS tuning loop — re-synthesize with adjusted parameters"
echo "================================================================"

# ---- Fix the transcript (Whisper heard Barak as 'Birak') ----
echo ""
echo "[1/2] Correcting transcript: 'Birak' -> 'Barak'..."
if [ -f "$REFERENCE_TRANSCRIPT" ]; then
    if grep -q "Birak" "$REFERENCE_TRANSCRIPT"; then
        sed -i.bak 's/Birak/Barak/g' "$REFERENCE_TRANSCRIPT"
        echo "  Updated transcript:"
        cat "$REFERENCE_TRANSCRIPT" | sed 's/^/    /'
    else
        echo "  Already correct (no 'Birak' found):"
        cat "$REFERENCE_TRANSCRIPT" | sed 's/^/    /'
    fi
else
    echo "ERROR: transcript file missing. Run install_voice_cloning.sh first."
    exit 1
fi
echo ""

# ---- Re-synthesize with multiple parameter sets for A/B comparison ----
echo "[2/2] Re-synthesizing test phrase with tuned parameters..."
python3 <<PYEOF
import time
from f5_tts.api import F5TTS

print("  Loading F5-TTS (cached after first run)...")
t0 = time.time()
tts = F5TTS()
print(f"  Loaded in {time.time()-t0:.1f}s")

ref_file = "$REFERENCE_AUDIO"
ref_text = open("$REFERENCE_TRANSCRIPT").read().strip()
gen_text = "Hello. This is a smoke test of the F5-TTS voice cloning pipeline. If you can hear this in my voice, the install worked."

# A/B parameter sets — tuned versions to compare against the v1 default
# baseline (which was rushed and bright). Targets: slower pace, stronger
# reference conditioning, more diffusion steps.
runs = [
    {
        "label": "v2_slower",
        "out": "$VB_DIR/sofia_clone_v2_slower.wav",
        "speed": 0.7,
        "nfe_step": 32,
        "cfg_strength": 2.0,
    },
    {
        "label": "v3_slowest",
        "out": "$VB_DIR/sofia_clone_v3_slowest.wav",
        "speed": 0.55,
        "nfe_step": 32,
        "cfg_strength": 2.0,
    },
    {
        "label": "v4_slow_strong",
        "out": "$VB_DIR/sofia_clone_v4_slow_strong.wav",
        "speed": 0.6,
        "nfe_step": 48,
        "cfg_strength": 2.5,
    },
    {
        "label": "v5_slow_strongest",
        "out": "$VB_DIR/sofia_clone_v5_slow_strongest.wav",
        "speed": 0.55,
        "nfe_step": 64,
        "cfg_strength": 3.0,
    },
]

for r in runs:
    print(f"\n  --- {r['label']} (speed={r['speed']}, nfe_step={r['nfe_step']}, cfg_strength={r['cfg_strength']}) ---")
    t0 = time.time()
    audio_data, samplerate, _ = tts.infer(
        ref_file=ref_file,
        ref_text=ref_text,
        gen_text=gen_text,
        speed=r["speed"],
        nfe_step=r["nfe_step"],
        cfg_strength=r["cfg_strength"],
        file_wave=r["out"],
    )
    elapsed = time.time() - t0
    duration = len(audio_data) / float(samplerate)
    print(f"    synth_time={elapsed:.1f}s  audio_duration={duration:.2f}s  output={r['out']}")

print("\n================================================================")
print("Done. Listen to the four outputs and compare with the original:")
print(f"  Original:  $REFERENCE_AUDIO")
for r in runs:
    print(f"  {r['label']:20s}: {r['out']}")
print("================================================================")
PYEOF
