#!/bin/bash
# fix_transformers_for_xtts.sh
# =============================
# Pin transformers to a version that's compatible with both F5-TTS and
# coqui-tts (XTTS-v2). The latter expects isin_mps_friendly in
# transformers.pytorch_utils, which exists in 4.45-4.49 but may have been
# removed/renamed in 4.50+.
#
# Strategy:
#   1. Print current transformers version (diagnosis)
#   2. Reinstall transformers==4.49.0 (known to have isin_mps_friendly,
#      and compatible with current F5-TTS / accelerate / torch versions)
#   3. Verify the import that was failing
#   4. Tell user to re-run install_xtts_v2.sh

set -e

echo "================================================================"
echo "Pinning transformers to a version compatible with both F5-TTS"
echo "and coqui-tts (XTTS-v2)"
echo "================================================================"

# ---- 1. Diagnose ----
echo ""
echo "[1/4] Current transformers version:"
python3 -c "import transformers; print(f'  transformers {transformers.__version__}')"
python3 -c "
from transformers.pytorch_utils import __dict__ as d
has = 'isin_mps_friendly' in d
print(f'  isin_mps_friendly present: {has}')
"

# ---- 2. Install pinned version ----
echo ""
echo "[2/4] Installing transformers==4.49.0..."
pip3 install --break-system-packages "transformers==4.49.0" 2>&1 | tail -10
echo ""

# ---- 3. Verify the import ----
echo "[3/4] Verifying the import that was failing..."
python3 <<'PYEOF'
try:
    from transformers.pytorch_utils import isin_mps_friendly
    print("  isin_mps_friendly import: OK")
except ImportError as e:
    print(f"  STILL BROKEN: {e}")
    raise SystemExit(1)
try:
    from TTS.api import TTS
    print("  TTS.api import: OK")
except Exception as e:
    print(f"  TTS.api still broken: {type(e).__name__}: {e}")
    raise SystemExit(1)
print("  Both imports succeed — coqui-tts should now work.")
PYEOF

# ---- 4. Confirm F5-TTS still works ----
echo ""
echo "[4/4] Checking F5-TTS still imports (in case the transformers downgrade broke it)..."
python3 <<'PYEOF'
try:
    from f5_tts.api import F5TTS
    print("  f5_tts.api import: OK — F5-TTS still works")
except Exception as e:
    print(f"  F5-TTS broken: {type(e).__name__}: {e}")
    print(f"  We may need a different transformers version. Tell Sofia.")
    raise SystemExit(1)
PYEOF

echo ""
echo "================================================================"
echo "Fix complete. Re-run the XTTS-v2 install script:"
echo "  bash ~/Downloads/Claude\\ Memory/scripts/install_xtts_v2.sh"
echo ""
echo "It's idempotent — pip install will see coqui-tts is already there"
echo "and skip; the smoke test will run with the now-importable TTS module."
echo "================================================================"
