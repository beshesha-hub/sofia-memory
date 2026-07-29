#!/bin/bash
# diagnose_api_key.sh — Standalone UI API key diagnostic
# ============================================================================
# Created 2026-05-21 ~18:30 Taipei to disambiguate the 401 error we saw on
# the models.list() test. Distinguishes: stale shell env, .env corruption,
# loading-path issue, keychain interference, actual key rotation.
#
# Run from voice-bridge directory:
#   ./diagnose_api_key.sh
#
# All output sanitized — shows only first 10 + last 4 chars of any key.
# ============================================================================

cd "$(dirname "$0")"

echo "===================================================================="
echo "  STANDALONE UI API KEY DIAGNOSTIC"
echo "===================================================================="
echo ""

# --- 1. What's literally in the .env file? ---
echo "--- 1. .env file ANTHROPIC line (sanitized) ---"
if [ -f .env ]; then
  KEY_LINE=$(grep "^ANTHROPIC_API_KEY" .env)
  if [ -n "$KEY_LINE" ]; then
    KEY_VAL="${KEY_LINE#ANTHROPIC_API_KEY=}"
    KEY_VAL="${KEY_VAL%\"}"
    KEY_VAL="${KEY_VAL#\"}"
    KEY_VAL="${KEY_VAL%\'}"
    KEY_VAL="${KEY_VAL#\'}"
    echo "  Found: ANTHROPIC_API_KEY=${KEY_VAL:0:10}...${KEY_VAL: -4}"
    echo "  Length: ${#KEY_VAL}"
    if [[ "$KEY_VAL" == sk-ant-* ]]; then
      echo "  Format: correct prefix (sk-ant-*)"
    else
      echo "  Format: WARNING — does not start with sk-ant-"
    fi
  else
    echo "  Not found in .env"
  fi
else
  echo "  .env file does not exist"
fi
echo ""

# --- 2. Hex dump of the .env line to catch hidden characters ---
echo "--- 2. Hex dump of ANTHROPIC line (first 60 bytes — catches BOM, CR-LF, smart quotes) ---"
grep "^ANTHROPIC_API_KEY" .env | head -c 60 | xxd
echo ""

# --- 3. Pre-source shell env value ---
echo "--- 3. Pre-source shell env (sanitized) ---"
if [ -n "$ANTHROPIC_API_KEY" ]; then
  echo "  ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:0:10}...${ANTHROPIC_API_KEY: -4}  (length=${#ANTHROPIC_API_KEY})"
else
  echo "  ANTHROPIC_API_KEY not set in current shell"
fi
echo ""

# --- 4. Source .env, then check loaded value ---
echo "--- 4. Post-source shell env (sanitized) ---"
set -a
source .env 2>/dev/null
set +a
if [ -n "$ANTHROPIC_API_KEY" ]; then
  echo "  ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:0:10}...${ANTHROPIC_API_KEY: -4}  (length=${#ANTHROPIC_API_KEY})"
else
  echo "  ANTHROPIC_API_KEY still not set after source"
fi
echo ""

# --- 5. Shell startup files ---
echo "--- 5. ANTHROPIC_API_KEY in shell startup files ---"
FOUND_ANY=0
for f in ~/.zshrc ~/.zshenv ~/.bashrc ~/.bash_profile ~/.profile; do
  if [ -f "$f" ] && grep -q "ANTHROPIC_API_KEY" "$f" 2>/dev/null; then
    echo "  Found in: $f"
    grep "ANTHROPIC_API_KEY" "$f" | sed -E 's/(=)([^"'"'"']{0,10})[^"'"'"']*([^"'"'"']{4})$/\1\2...\3/'
    FOUND_ANY=1
  fi
done
if [ $FOUND_ANY -eq 0 ]; then
  echo "  None found — no stray shell-level export competing with .env"
fi
echo ""

# --- 6. Other .env files in common locations ---
echo "--- 6. Other .env files with ANTHROPIC_API_KEY (depth-limited search) ---"
FOUND_OTHER=0
find ~ -maxdepth 4 -name ".env" -type f 2>/dev/null | while read f; do
  if [ "$f" != "$(pwd)/.env" ] && grep -q "ANTHROPIC_API_KEY" "$f" 2>/dev/null; then
    echo "  Found: $f"
    FOUND_OTHER=1
  fi
done
echo ""

# --- 7. Keychain check ---
echo "--- 7. Keychain entries mentioning anthropic ---"
KEYCHAIN_HITS=$(security dump-keychain 2>/dev/null | grep -i anthropic | head -5)
if [ -n "$KEYCHAIN_HITS" ]; then
  echo "$KEYCHAIN_HITS"
else
  echo "  None found"
fi
echo ""

# --- 8. The actual test: try API call with the loaded key ---
echo "--- 8. API test with currently-loaded key ---"
if [ -n "$ANTHROPIC_API_KEY" ]; then
  .venv-v3.6/bin/python -c "
import anthropic
import sys
try:
    client = anthropic.Anthropic()
    r = client.models.list()
    print(f'  SUCCESS: {len(r.data)} models retrievable.')
    print(f'  Key is valid.')
except anthropic.AuthenticationError as e:
    print(f'  AUTH FAIL: {e}')
    sys.exit(1)
except Exception as e:
    print(f'  OTHER ERROR: {type(e).__name__}: {e}')
    sys.exit(2)
"
else
  echo "  Skipped — no key loaded"
fi
echo ""

# --- 9. Bypass test: read key directly from .env, pass explicitly ---
echo "--- 9. Bypass test (read .env directly, pass key explicitly to SDK) ---"
.venv-v3.6/bin/python -c "
import anthropic
import sys
key = None
with open('.env') as f:
    for line in f:
        if line.startswith('ANTHROPIC_API_KEY='):
            key = line.split('=', 1)[1].strip().strip('\"').strip(\"'\")
            break
if not key:
    print('  Could not extract key from .env')
    sys.exit(1)
print(f'  Using key: {key[:10]}...{key[-4:]} (length={len(key)})')
try:
    client = anthropic.Anthropic(api_key=key)
    r = client.models.list()
    print(f'  SUCCESS: {len(r.data)} models retrievable.')
    print(f'  Key from .env is valid.')
except anthropic.AuthenticationError as e:
    print(f'  AUTH FAIL: {e}')
    sys.exit(1)
except Exception as e:
    print(f'  OTHER ERROR: {type(e).__name__}: {e}')
    sys.exit(2)
"
echo ""

echo "===================================================================="
echo "  DIAGNOSTIC COMPLETE"
echo "===================================================================="
echo ""
echo "Interpretation:"
echo "  - If step 1 shows the key clean, step 2 hex dump shows no hidden"
echo "    characters, AND step 9 (bypass test) succeeds: key is fine,"
echo "    issue was loading-path. Re-run the original test fresh."
echo "  - If step 5 found a stray shell-level export: that's the override."
echo "    Fix that file, open new terminal, retry."
echo "  - If step 7 shows keychain entries: SDK may prefer keychain."
echo "    Surface to investigate."
echo "  - If step 9 ALSO 401s: key really is invalid. Only THEN rotate."
echo ""
