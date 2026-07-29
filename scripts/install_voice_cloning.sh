#!/bin/bash
# install_voice_cloning.sh
# =========================
# F5-TTS install + reference setup + smoke test for the voice-bridge
# voice-cloning pathway. Run this once on the host Mac. Idempotent: safe
# to re-run if it bails partway through.
#
# What this does:
#   1. pip install f5-tts (and runtime deps: torch, torchaudio, soundfile,
#      vocos, librosa, transformers, etc.)
#   2. Verify the reference audio file exists and is the right format
#   3. Auto-transcribe the reference via the local Whisper server (port 3459)
#   4. Save the transcript to voice-bridge/sofia_reference_transcript.txt
#   5. Smoke test: synthesize a short test phrase using the cloned voice;
#      save to voice-bridge/sofia_clone_smoke_test.wav
#
# Origin: 2026-05-01 afternoon Tainan. Companion to voice_bridge_ui_v3_4
# and the Option C voice-cloning trajectory. Pairs with cadence.py /
# v3_3 / v3_4 as the substrate-level register fix.

set -e  # exit on any error

CM_DIR="$HOME/Downloads/Claude Memory"
VB_DIR="$CM_DIR/voice-bridge"
REFERENCE_AUDIO="$HOME/Downloads/Sofia's Room/voice_candidates/05_deep_calm.wav"
REFERENCE_TRANSCRIPT="$VB_DIR/sofia_reference_transcript.txt"
SMOKE_TEST_OUTPUT="$VB_DIR/sofia_clone_smoke_test.wav"
WHISPER_URL="http://127.0.0.1:3459"

echo "================================================================"
echo "F5-TTS install + reference setup + smoke test"
echo "================================================================"
echo ""

# ---- Step 1: Verify reference audio ----
echo "[1/5] Checking reference audio..."
if [ ! -f "$REFERENCE_AUDIO" ]; then
    echo "ERROR: reference audio not found at:"
    echo "  $REFERENCE_AUDIO"
    echo "Aborting."
    exit 1
fi
echo "  Found: $REFERENCE_AUDIO"
python3 <<PYEOF
import soundfile as sf
info = sf.info("$REFERENCE_AUDIO")
print(f"  Duration: {info.duration:.2f}s  Samplerate: {info.samplerate}Hz  Channels: {info.channels}  Format: {info.subtype}")
assert 6.0 <= info.duration <= 30.0, f"Duration {info.duration:.2f}s outside F5-TTS sweet spot (6-30s)"
print("  Format check: OK")
PYEOF
echo ""

# ---- Step 2: Install F5-TTS ----
echo "[2/5] Installing F5-TTS..."
pip3 install --break-system-packages --upgrade f5-tts 2>&1 | tail -10
echo ""
echo "  Verifying import..."
python3 -c "import f5_tts; print(f'  f5_tts version: {getattr(f5_tts, \"__version__\", \"unknown\")}')"
echo ""

# ---- Step 3: Verify Whisper server ----
echo "[3/5] Checking Whisper server (port 3459)..."
if curl -s --max-time 3 "$WHISPER_URL/health" > /tmp/whisper_health.json 2>&1; then
    if grep -q '"ok": *true' /tmp/whisper_health.json; then
        echo "  Whisper server: OK"
    else
        echo "  Whisper server responded but not ok:"
        cat /tmp/whisper_health.json
        echo ""
        echo "Start the Whisper server first (it's auto-spawned by the voice bridge,"
        echo "or run: python3 $VB_DIR/sofia_whisper_server.py)"
        exit 1
    fi
else
    echo "  Whisper server unreachable. Starting it now in background..."
    python3 "$VB_DIR/sofia_whisper_server.py" > /tmp/whisper_for_install.log 2>&1 &
    WHISPER_PID=$!
    echo "  Spawned (pid $WHISPER_PID); waiting up to 30s for it to come up..."
    for i in $(seq 1 30); do
        sleep 1
        if curl -s --max-time 1 "$WHISPER_URL/health" > /dev/null 2>&1; then
            echo "  Whisper ready after ${i}s."
            break
        fi
    done
    if ! curl -s --max-time 2 "$WHISPER_URL/health" > /dev/null; then
        echo "  Whisper still not responding. Check /tmp/whisper_for_install.log"
        exit 1
    fi
fi
echo ""

# ---- Step 4: Transcribe reference ----
echo "[4/5] Transcribing reference audio via Whisper..."
python3 <<PYEOF
import base64, json, urllib.request
audio_bytes = open("$REFERENCE_AUDIO", "rb").read()
payload = json.dumps({
    "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
    "ext": "wav",
    "model": "small",
    "language": "en",
    "word_timestamps": False,
    "spectral": False,
}).encode("utf-8")
req = urllib.request.Request(
    "$WHISPER_URL/transcribe_bytes",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=60) as resp:
    data = json.loads(resp.read().decode("utf-8"))
if not data.get("ok"):
    raise SystemExit(f"Whisper failed: {data.get('error', 'unknown')}")
transcript = (data.get("transcript") or "").strip()
print(f"  Transcript ({len(transcript)} chars):")
print(f"    {transcript!r}")
with open("$REFERENCE_TRANSCRIPT", "w", encoding="utf-8") as f:
    f.write(transcript + "\n")
print(f"  Saved to: $REFERENCE_TRANSCRIPT")
PYEOF
echo ""

# ---- Step 5: Smoke test — synthesize a test phrase using the cloned voice ----
echo "[5/5] Smoke test — synthesizing a test phrase via F5-TTS..."
python3 <<PYEOF
import time
print("  Loading F5-TTS model (first load downloads weights, may take a few minutes)...")
t0 = time.time()
from f5_tts.api import F5TTS
tts = F5TTS()
print(f"  Model loaded in {time.time()-t0:.1f}s")

ref_audio = "$REFERENCE_AUDIO"
ref_text = open("$REFERENCE_TRANSCRIPT").read().strip()
gen_text = "Hello. This is a smoke test of the F5-TTS voice cloning pipeline. If you can hear this in my voice, the install worked."

print(f"  Reference: {ref_audio}")
print(f"  Reference text: {ref_text!r}")
print(f"  Generation text: {gen_text!r}")
print(f"  Synthesizing...")
t0 = time.time()
audio_data, samplerate, _ = tts.infer(
    ref_file=ref_audio,
    ref_text=ref_text,
    gen_text=gen_text,
    file_wave="$SMOKE_TEST_OUTPUT",
)
print(f"  Synthesized in {time.time()-t0:.1f}s, sr={samplerate}Hz, samples={len(audio_data)}")
print(f"  Output: $SMOKE_TEST_OUTPUT")
PYEOF
echo ""

echo "================================================================"
echo "Install complete. Smoke test output saved to:"
echo "  $SMOKE_TEST_OUTPUT"
echo ""
echo "Listen to it — that's F5-TTS-cloned-Sofia speaking."
echo "Next step: I'll write sofia_voice_clone_server.py (TTS server"
echo "endpoint that wraps F5-TTS so the voice bridge can call it)."
echo "================================================================"
