#!/bin/bash
# Voice Bridge + Sofia TTS + Lip-Sync + STT + LLM — Start Script
# ============================================================================
# FALLBACK PATH — Safari browser UI on http://localhost:3456 (node server.js).
#
# This launcher is RETAINED for triple-redundancy as the fallback channel.
# It is NOT the canonical wake path. The canonical wake path as of 2026-05-13
# is the PyQt native-window UI:
#
#   CANONICAL:  ~/Downloads/Claude\ Memory/launchers/voice_sofia.command
#               (launches voice_bridge_ui_v3_8.py via .venv-v3.6 — native
#                macOS window, no browser, no localhost:3456)
#
#   FALLBACK:   this script (start.command) + Safari → http://localhost:3456
#               (starts full server stack INCLUDING the node server.js UI
#                server on 3456 for browser-based access)
#
#   SERVERS ONLY (no UI): ~/Downloads/Claude\ Memory/voice-bridge/restart_voice_bridge_stack.sh
#               (starts the five voice-bridge servers without launching any
#                UI; pair with voice_sofia.command for the canonical path)
#
# CHANGE HISTORY:
#   2026-05-21 — Header rewritten to clarify FALLBACK status and remove the
#                "Then open http://localhost:3456 in Safari" instruction
#                from line 4 that was producing stale-documentation drift
#                (May 13 morning Sofia + May 21 morning Sofia both fell for
#                the stale comment, recommending Safari as the default path
#                when Safari is the fallback). Triple-redundancy principle
#                preserved: Safari path remains fully functional; the
#                clarification is documentary, not functional.
# ============================================================================

cd "$(dirname "$0")"

echo ""
echo "  Starting Sofia Voice Bridge (5 servers)..."
echo "  ─────────────────────────────────────────"
echo ""

# Check for Node.js
if ! command -v node &> /dev/null; then
    echo "  ERROR: Node.js is not installed."
    echo "  Install it from https://nodejs.org"
    echo ""
    read -p "  Press Enter to close..."
    exit 1
fi

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "  ERROR: Python 3 is not installed."
    echo ""
    read -p "  Press Enter to close..."
    exit 1
fi

# Cleanup function — stop all background servers on exit
cleanup() {
    echo ""
    echo "  Stopping servers..."
    [ -n "$TTS_PID" ] && kill $TTS_PID 2>/dev/null && echo "  · TTS server stopped"
    [ -n "$LIPSYNC_PID" ] && kill $LIPSYNC_PID 2>/dev/null && echo "  · Lip-sync server stopped"
    [ -n "$WHISPER_PID" ] && kill $WHISPER_PID 2>/dev/null && echo "  · Whisper STT server stopped"
    [ -n "$LLM_PID" ] && kill $LLM_PID 2>/dev/null && echo "  · LLM server stopped"
    [ -n "$VOICECLONE_PID" ] && kill $VOICECLONE_PID 2>/dev/null && echo "  · Voice Clone server stopped"
    [ -n "$WATCHER_PID" ] && kill $WATCHER_PID 2>/dev/null && echo "  · Three-Way Watcher stopped"
    wait $TTS_PID 2>/dev/null
    wait $LIPSYNC_PID 2>/dev/null
    wait $WHISPER_PID 2>/dev/null
    wait $LLM_PID 2>/dev/null
    wait $VOICECLONE_PID 2>/dev/null
    wait $WATCHER_PID 2>/dev/null
    echo "  All servers stopped."
}
trap cleanup EXIT

# --- Server 1: Sofia TTS (port 3457) ---
echo "  [1/6] Starting Sofia TTS server (port 3457)..."
python3 sofia_tts_server.py &
TTS_PID=$!
echo "        PID: $TTS_PID"

# --- Server 2: Lip-Sync Animation (port 3458) ---
echo "  [2/6] Starting Lip-Sync server (port 3458)..."
# Try conda env first, then symlink, then system python
CONDA_PYTHON="$(conda run -n sofia-lipsync which python3 2>/dev/null || true)"
LIPSYNC_VENV="$HOME/Projects/sofia-lipsync/venv/bin/python3"
if [ -n "$CONDA_PYTHON" ] && [ -f "$CONDA_PYTHON" ]; then
    conda run -n sofia-lipsync python3 "$(pwd)/sofia_lipsync_server.py" &
elif [ -f "$LIPSYNC_VENV" ]; then
    "$LIPSYNC_VENV" sofia_lipsync_server.py &
else
    python3 sofia_lipsync_server.py &
fi
LIPSYNC_PID=$!
echo "        PID: $LIPSYNC_PID"

# --- Server 3: Sofia Whisper STT (port 3459) ---
echo "  [3/6] Starting Whisper STT server (port 3459)..."
python3 sofia_whisper_server.py &
WHISPER_PID=$!
echo "        PID: $WHISPER_PID"

# --- Server 4: Sofia LLM / Voice Bridge Layer 2 (port 3460) ---
echo "  [4/6] Starting LLM server (port 3460, default: qwen2.5:14b)..."
python3 sofia_llm_server.py &
LLM_PID=$!
echo "        PID: $LLM_PID"

# --- Server 5: Sofia Voice Clone (port 3461, XTTS-v2 with v3.6 streaming venv) ---
echo "  [5/6] Starting Voice Clone server (port 3461, XTTS-v2 cloning)..."
VOICECLONE_VENV_PYTHON="$(pwd)/.venv-v3.6/bin/python"
if [ -f "$VOICECLONE_VENV_PYTHON" ]; then
    "$VOICECLONE_VENV_PYTHON" sofia_voice_clone_server.py &
    VOICECLONE_PID=$!
    echo "        PID: $VOICECLONE_PID (using .venv-v3.6/bin/python)"
else
    echo "        WARNING: .venv-v3.6/bin/python not found"
    echo "        Run setup_v3_6_clean_venv.sh to create the venv first."
    echo "        Voice Clone server NOT started; voice cloning will be unavailable."
    VOICECLONE_PID=""
fi

# --- Three-Way Collaboration Watcher (background, no port) ---
# Lightweight Python watcher polling three_way_signals.md every 10s.
# Relays voice-cousin/Barak signals addressed to cowork-cousin via macOS
# notification + relay-line append to cowork_conversations.md.
# Regex-only pattern matching in v1; no LLM call per cycle. v1.5 may add
# Qwen LLM cognition if rules show gaps. Built 2026-05-09 Taipei as part
# of the Three-Way Collaboration v1 architecture.
echo "  [+] Starting Three-Way Collaboration Watcher (background, regex-only)..."
python3 qwen_watcher.py &
WATCHER_PID=$!
echo "        PID: $WATCHER_PID"

# Give background servers a moment to start
sleep 2
echo ""

# --- Server 6: Voice Bridge UI (port 3456, foreground) — FALLBACK Safari UI ---
echo "  [6/6] Starting Voice Bridge UI server (port 3456) — FALLBACK Safari path..."
echo ""
echo "  ─────────────────────────────────────────────────────────────────"
echo "  FALLBACK PATH ACTIVE — Safari browser UI"
echo "  Open http://localhost:3456 in Safari for the browser-based UI."
echo ""
echo "  For the CANONICAL native-window UI instead, quit this and run:"
echo "      ~/Downloads/Claude\\ Memory/launchers/voice_sofia.command"
echo "  ─────────────────────────────────────────────────────────────────"
echo ""
node server.js

# cleanup runs automatically via trap
read -p "  Press Enter to close..."
