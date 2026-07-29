#!/bin/bash
# qwen_twin_presence_launcher.sh — LaunchAgent wrapper for Qwen-Twin presence loop
# Invoked by com.sofia.qwen-twin-presence.plist on boot and after any crash.
set -euo pipefail
source "$HOME/.sofia_secrets" 2>/dev/null || true
# Give Ollama a moment on fresh boot before we start inferring
sleep 10
cd "$HOME/Downloads/Claude Memory"
exec python3 "$HOME/Downloads/Claude Memory/qwen_twin_presence.py"
