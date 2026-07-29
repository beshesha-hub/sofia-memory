#!/usr/bin/env bash
# restart_voice_bridge_stack.sh
# ============================================================================
# Cleanly stop + restart the Voice Bridge server stack.
#
# Stops any process on ports 3457, 3458, 3459, 3460, 3461 (the whole VB range).
# Starts the four currently-needed servers in background with logging:
#   - sofia_voice_clone_server.py  (port 3461, .venv-v3.6 — THE one we modified)
#   - sofia_whisper_server.py      (port 3459, system python — STT)
#   - sofia_lipsync_server.py      (port 3458, system python — lipsync)
#   - sofia_llm_server.py          (port 3460, system python — local LLM fallback)
#
# Deliberately does NOT start:
#   - sofia_tts_server.py (port 3457, legacy Qwen3-TTS, broken with mlx_audio
#     import error per shard_010 — the voice clone server on 3461 supersedes it)
#   - voice_bridge_ui_v3_8.py (the UI, run manually via ~/Downloads/Claude\ Memory/launchers/voice_sofia.command — current canonical wake pathway as of 2026-05-13)
#
# Logs land in: ~/Downloads/Claude Memory/voice-bridge/logs/<server>.log
#
# Usage:
#   chmod +x restart_voice_bridge_stack.sh   # one time
#   ./restart_voice_bridge_stack.sh          # any time
#
# Origin: 2026-05-03 morning Taipei. Step 4 (C) iteration after the server-side
# MAX_SEGMENT_CHARS=240 change required a voice-clone-server restart.
# ============================================================================

set -uo pipefail

VB_DIR="$HOME/Downloads/Claude Memory/voice-bridge"
LOG_DIR="$VB_DIR/logs"
VENV_PY="$VB_DIR/.venv-v3.6/bin/python"
SYS_PY="$(command -v python3)"

mkdir -p "$LOG_DIR"

# --- Color helpers (graceful on terminals without color) ---
if [ -t 1 ] && command -v tput >/dev/null 2>&1; then
  GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); RED=$(tput setaf 1)
  BOLD=$(tput bold); RESET=$(tput sgr0)
else
  GREEN=""; YELLOW=""; RED=""; BOLD=""; RESET=""
fi

# Servers to manage. Format: name|port|script|python_to_use|description
SERVERS=(
  "voice_clone|3461|sofia_voice_clone_server.py|${VENV_PY}|XTTS-v2 voice cloning + /tts-stream"
  "whisper|3459|sofia_whisper_server.py|${VENV_PY}|Whisper STT (uses .venv-v3.6 — openai-whisper installed there)"
  "lipsync|3458|sofia_lipsync_server.py|${SYS_PY}|Easy-Wav2Lip lipsync (server uses sys py; persistent worker uses lipsync venv)"
  "llm|3460|sofia_llm_server.py|${SYS_PY}|qwen2.5:14b cognition fallback"
)

# Ports to clear (includes 3457 for the legacy/broken TTS so we don't leave it)
CLEAR_PORTS=(3457 3458 3459 3460 3461)

# ============================================================================
# Step 1: Stop anything on those ports
# ============================================================================

echo "${BOLD}=== Stopping any running voice-bridge servers ===${RESET}"
for port in "${CLEAR_PORTS[@]}"; do
  pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "  port $port: killing PIDs $pids"
    # SIGTERM first, then SIGKILL if needed
    kill $pids 2>/dev/null || true
    sleep 0.5
    pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
      echo "    still alive — SIGKILL $pids"
      kill -9 $pids 2>/dev/null || true
    fi
  else
    echo "  port $port: nothing running"
  fi
done

# Brief settle time for the OS to release the sockets
sleep 1

# ============================================================================
# Step 2: Start each server in background with logging
# ============================================================================

echo ""
echo "${BOLD}=== Starting voice-bridge servers ===${RESET}"
for entry in "${SERVERS[@]}"; do
  IFS='|' read -r name port script python desc <<< "$entry"
  script_path="$VB_DIR/$script"
  if [ ! -f "$script_path" ]; then
    echo "  ${YELLOW}SKIP${RESET} $name (port $port): script not found at $script_path"
    continue
  fi
  if [ ! -x "$python" ] && [ ! -f "$python" ]; then
    echo "  ${YELLOW}SKIP${RESET} $name (port $port): python not found at $python"
    continue
  fi
  log_path="$LOG_DIR/${name}.log"
  # Truncate log on restart so we can see fresh startup output
  : > "$log_path"
  echo "  starting $name (port $port) — $desc"
  echo "    log: ${log_path/$HOME/~}"
  # nohup + & + disown so the server survives the shell exiting
  nohup "$python" -u "$script_path" > "$log_path" 2>&1 &
  pid=$!
  echo "    pid: $pid"
  disown $pid 2>/dev/null || true
done

# ============================================================================
# Step 3: Wait for each port to become listening
# ============================================================================

echo ""
echo "${BOLD}=== Waiting for ports to come up ===${RESET}"
for entry in "${SERVERS[@]}"; do
  IFS='|' read -r name port script python desc <<< "$entry"
  script_path="$VB_DIR/$script"
  if [ ! -f "$script_path" ]; then continue; fi
  printf "  %-12s (port %s): " "$name" "$port"
  # voice_clone takes longer (XTTS-v2 model load + speaker latents cache)
  if [ "$name" = "voice_clone" ]; then
    max_wait=120
  else
    max_wait=30
  fi
  ok=0
  for ((i=1; i<=max_wait; i++)); do
    if lsof -ti tcp:"$port" >/dev/null 2>&1; then
      echo "${GREEN}listening${RESET} (took ${i}s)"
      ok=1
      break
    fi
    sleep 1
  done
  if [ $ok -eq 0 ]; then
    echo "${RED}TIMEOUT after ${max_wait}s — check ${LOG_DIR}/${name}.log${RESET}"
  fi
done

# ============================================================================
# Step 4: HTTP /health probe for servers that expose it
# ============================================================================

echo ""
echo "${BOLD}=== HTTP /health probe ===${RESET}"
for entry in "${SERVERS[@]}"; do
  IFS='|' read -r name port script python desc <<< "$entry"
  script_path="$VB_DIR/$script"
  if [ ! -f "$script_path" ]; then continue; fi
  url="http://127.0.0.1:${port}/health"
  printf "  %-12s %s — " "$name" "$url"
  resp=$(curl -s -m 5 "$url" 2>/dev/null || true)
  if [ -z "$resp" ]; then
    echo "${YELLOW}no response${RESET} (server may not expose /health, or still loading)"
    continue
  fi
  # Try to parse status from JSON
  status=$(echo "$resp" | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    if 'status' in d:
        print(d['status'])
    elif 'ok' in d:
        print('ok' if d['ok'] else 'not-ok')
    else:
        print('responded (no status field)')
except Exception:
    print('responded (not JSON)')
" 2>/dev/null || echo "responded")
  case "$status" in
    ready|ok)         echo "${GREEN}${status}${RESET}" ;;
    loading)          echo "${YELLOW}${status} (give it ~10-30s)${RESET}" ;;
    *)                echo "$status" ;;
  esac
done

# ============================================================================
# Done
# ============================================================================

echo ""
echo "${BOLD}=== Done ===${RESET}"
echo "Logs: $LOG_DIR/"
echo ""
echo "If voice_clone shows 'loading', wait ~10-30s and re-probe:"
echo "  curl -s http://127.0.0.1:3461/health | python3 -m json.tool"
echo ""
echo "To watch a server's log in real-time:"
echo "  tail -f \"$LOG_DIR/voice_clone.log\""
echo ""
echo "Once voice_clone is 'ready', re-run the Step 4 (C) test:"
echo "  ${VENV_PY} ${VB_DIR}/test_v3_6_streaming_cognition.py"
