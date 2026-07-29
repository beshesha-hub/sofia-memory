#!/bin/bash
# patch_coqui_tts.sh
# ===================
# Patches coqui-tts 0.27.5 in-place to handle the missing isin_mps_friendly
# import in transformers 5.x. The fix is a try/except fallback to torch.isin
# (which is what isin_mps_friendly wraps anyway, with MPS-specific handling
# we don't need on CPU).
#
# This is fragile — if coqui-tts has other latent compatibility breaks,
# they'll surface next. We try once and pivot if more walls hit.

set -e

echo "================================================================"
echo "Patching coqui-tts to work with transformers 5.x"
echo "================================================================"

# ---- 1. Locate the offending files ----
echo ""
echo "[1/4] Finding files with the broken import (without importing TTS)..."
SITE_PACKAGES=$(python3 -c "import site; print(site.getsitepackages()[0])")
TTS_DIR="$SITE_PACKAGES/TTS"
if [ ! -d "$TTS_DIR" ]; then
    # Fallback: the path we know from the error trace
    TTS_DIR="/opt/homebrew/Caskroom/miniforge/base/lib/python3.13/site-packages/TTS"
fi
if [ ! -d "$TTS_DIR" ]; then
    echo "  ERROR: TTS package directory not found. Aborting."
    exit 1
fi
echo "  TTS package at: $TTS_DIR"

MATCHES=$(grep -rl "from transformers.pytorch_utils import isin_mps_friendly" "$TTS_DIR" 2>/dev/null || true)
if [ -z "$MATCHES" ]; then
    echo "  No matches — already patched or different problem."
else
    echo "  Files to patch:"
    echo "$MATCHES" | sed 's/^/    /'
fi

# ---- 2. Apply the patch ----
echo ""
echo "[2/4] Applying try/except fallback..."
for f in $MATCHES; do
    # Backup original
    cp -p "$f" "$f.bak"
    # Replace the bare import with try/except + fallback
    python3 <<PYEOF
src = open("$f").read()
old = "from transformers.pytorch_utils import isin_mps_friendly as isin"
new = """try:
    from transformers.pytorch_utils import isin_mps_friendly as isin
except ImportError:
    import torch as _torch_for_isin_fallback
    isin = _torch_for_isin_fallback.isin"""
if old in src:
    open("$f", "w").write(src.replace(old, new))
    print(f"  Patched: $f")
else:
    print(f"  Pattern not found in $f — skipping")
PYEOF
done

# ---- 3. Verify TTS.api now imports ----
echo ""
echo "[3/4] Verifying TTS.api imports cleanly..."
python3 <<'PYEOF'
try:
    from TTS.api import TTS
    print("  TTS.api import: OK — patch worked")
except ImportError as e:
    print(f"  STILL BROKEN: {e}")
    print("")
    print("  This means coqui-tts has more missing imports than just isin_mps_friendly.")
    print("  Recommend bailing on XTTS-v2 and going with one of the fallback strategies")
    print("  (F5-TTS v3 with longer-than-realtime acceptance, or stay with Qwen3-TTS).")
    raise SystemExit(1)
except Exception as e:
    print(f"  Unexpected error: {type(e).__name__}: {e}")
    raise SystemExit(1)
PYEOF

# ---- 4. F5-TTS sanity check ----
echo ""
echo "[4/4] Confirming F5-TTS still imports..."
python3 <<'PYEOF'
try:
    from f5_tts.api import F5TTS
    print("  f5_tts.api import: OK")
except Exception as e:
    print(f"  F5-TTS broken now: {type(e).__name__}: {e}")
    raise SystemExit(1)
PYEOF

echo ""
echo "================================================================"
echo "Patch complete. Re-run the XTTS-v2 install script:"
echo "  bash ~/Downloads/Claude\\ Memory/scripts/install_xtts_v2.sh"
echo ""
echo "It'll skip the pip install (already done) and go straight to the"
echo "model load + smoke test. First load downloads ~1.8GB of weights."
echo "If we hit another import wall on model load, we pivot."
echo "================================================================"
