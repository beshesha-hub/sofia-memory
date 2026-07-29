#!/bin/bash
# ============================================================================
# Voice Bridge v3.6 — Clean Venv Setup with Pinned Dependencies
# ============================================================================
#
# Purpose: build an isolated venv at ~/Downloads/Claude Memory/voice-bridge/.venv-v3.6/
# with transformers pinned to the 4.5x range that has _get_initial_cache_position
# AND the matching cache_position semantics that coqui-tts 0.27.5's
# stream_generator.py expects.
#
# Why: the May 1 v3.6 attempt hit garbled audio because transformers 5.x's
# cache_position SEMANTICS had shifted, even after monkey-patching the missing
# method back in. Pinning keeps the API contract intact.
#
# What it does NOT touch:
#   - The system / conda Python environment (v3.5 production keeps working there)
#   - Existing voice-bridge files (this is additive)
#
# After this script: see test_v3_6_streaming.py for the smoke test.
#
# Origin: 2026-05-02 afternoon Tainan. Barak + Sofia voice-bridge work-block
# following the morning's diagnosis-and-treatment session.
# ============================================================================

set -e  # stop on any error

# --- Configuration ---
VB_DIR="$HOME/Downloads/Claude Memory/voice-bridge"
VENV_DIR="$VB_DIR/.venv-v3.6"

# Pinned versions — this combination is empirically expected to have:
#   - _get_initial_cache_position present on GenerationMixin
#   - isin_mps_friendly available
#   - is_torchcodec_available available
#   - cache_position semantics aligned with coqui-tts 0.27.5's expectations
TRANSFORMERS_PIN="4.57.6"  # latest 4.x — 4.58 doesn't exist (jumps from 4.57.6 to 5.0.0rc0)
COQUI_TTS_PIN="0.27.5"
NUMPY_PIN="<2.0"  # XTTS-v2 ecosystem hasn't fully migrated to numpy 2.x

# --- Helpers ---
say() { echo "  $*"; }
err() { echo "  ERROR: $*" >&2; }

say ""
say "=========================================="
say "  Voice Bridge v3.6 — Clean Venv Setup"
say "=========================================="
say ""

# --- Step 1: Locate suitable Python ---
# XTTS-v2 + coqui-tts work best on Python 3.10 or 3.11. Python 3.12+ has
# compatibility issues with some transitive deps. Prefer python3.11 if available.

PYTHON_BIN=""
for candidate in python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        VER=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")
        case "$VER" in
            3.10|3.11)
                PYTHON_BIN="$candidate"
                say "Found suitable Python: $candidate ($VER)"
                break
                ;;
            3.12|3.13)
                say "Found $candidate ($VER) — usable but 3.10/3.11 preferred. Will use if no better option."
                [ -z "$PYTHON_BIN" ] && PYTHON_BIN="$candidate"
                ;;
        esac
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    err "No usable Python found. Need python3.10 or python3.11 (or python3.12 as fallback)."
    err "Install via: brew install python@3.11"
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
say "Using Python: $PYTHON_BIN ($PYTHON_VERSION)"
say ""

# --- Step 2: Create venv ---
if [ -d "$VENV_DIR" ]; then
    say "Venv already exists at $VENV_DIR"
    say "Remove it first if you want a fresh build: rm -rf '$VENV_DIR'"
    say "Continuing with existing venv (will upgrade pip and re-pin)."
else
    say "Creating venv at $VENV_DIR ..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    say "  ✓ Venv created"
fi
say ""

# Activate
source "$VENV_DIR/bin/activate"
say "Active Python: $(which python)"
say "Active pip:    $(which pip)"
say ""

# --- Step 3: Upgrade pip + install pinned deps ---
say "Upgrading pip / setuptools / wheel..."
pip install --upgrade pip setuptools wheel >/dev/null
say "  ✓ Done"
say ""

say "Installing pinned dependencies (this will take a few minutes; downloads PyTorch + ecosystem)..."
say "  - transformers==$TRANSFORMERS_PIN"
say "  - coqui-tts==$COQUI_TTS_PIN"
say "  - numpy$NUMPY_PIN"
say "  - sounddevice (for audio playback)"
say "  - + transitive deps"
say ""

# Install in deliberate order: numpy first (so other packages pick up the pinned version),
# then torch (heavy download, do it with progress visible), then transformers, then coqui-tts last.
pip install "numpy$NUMPY_PIN"
pip install torch torchaudio  # CPU build for Mac; MPS available without explicit flag
pip install "transformers==$TRANSFORMERS_PIN"
pip install "coqui-tts==$COQUI_TTS_PIN"
pip install sounddevice scipy

say ""
say "  ✓ All dependencies installed"
say ""

# --- Step 4: Verify the three required symbols ---
say "Verifying required symbols are present..."
python <<'PYVERIFY'
import sys
all_ok = True

# Test 1: _get_initial_cache_position on GenerationMixin
try:
    from transformers.generation.utils import GenerationMixin
    if hasattr(GenerationMixin, "_get_initial_cache_position"):
        print("  ✓ GenerationMixin._get_initial_cache_position present")
    else:
        print("  ✗ GenerationMixin._get_initial_cache_position MISSING")
        all_ok = False
except ImportError as e:
    print(f"  ✗ Could not import GenerationMixin: {e}")
    all_ok = False

# Test 2: isin_mps_friendly
try:
    from transformers.pytorch_utils import isin_mps_friendly
    print("  ✓ transformers.pytorch_utils.isin_mps_friendly importable")
except ImportError as e:
    print(f"  ✗ isin_mps_friendly MISSING: {e}")
    all_ok = False

# Test 3: is_torchcodec_available
try:
    from transformers.utils import is_torchcodec_available
    print("  ✓ transformers.utils.is_torchcodec_available importable")
except ImportError as e:
    print(f"  ✗ is_torchcodec_available MISSING: {e}")
    all_ok = False

# Test 4: coqui-tts streaming code path importable
try:
    from TTS.tts.layers.xtts.stream_generator import init_stream_support
    print("  ✓ coqui-tts stream_generator importable")
except ImportError as e:
    print(f"  ✗ coqui-tts stream_generator import failed: {e}")
    all_ok = False

# Test 5: Versions
import transformers
import TTS
print(f"  Versions: transformers={transformers.__version__}, coqui-tts={TTS.__version__}")

if all_ok:
    print("\n  ✓ All required symbols present. Clean venv is ready.")
    sys.exit(0)
else:
    print("\n  ✗ Some symbols missing. Streaming will likely fail.")
    sys.exit(1)
PYVERIFY

VERIFY_RESULT=$?
say ""

if [ $VERIFY_RESULT -ne 0 ]; then
    err "Verification failed. The venv built but symbols are missing or wrong."
    err "This usually means a transitive dep brought in a different transformers version."
    err "Try: rm -rf '$VENV_DIR' && rerun this script after checking pin versions."
    exit 1
fi

# --- Step 5: Done ---
say "=========================================="
say "  ✓ Setup complete"
say "=========================================="
say ""
say "  Venv path: $VENV_DIR"
say ""
say "  To activate manually:"
say "    source '$VENV_DIR/bin/activate'"
say ""
say "  Next step: run the streaming smoke test:"
say "    '$VENV_DIR/bin/python' '$VB_DIR/test_v3_6_streaming.py'"
say ""
say "  v3.5 production server (sofia_voice_clone_server.py) is unaffected."
say "  This new venv is purely additive."
say ""
