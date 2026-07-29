#!/bin/bash
# vp_self_launcher.sh — LaunchAgent wrapper for Sofia's Expanded VP (vp_self.py)
# Invoked by com.sofia.vp-self.plist when vp_self_trigger.json is written.
set -euo pipefail
source "$HOME/.sofia_secrets" 2>/dev/null || true
cd "$HOME/Downloads/Claude Memory"
exec python3 "$HOME/Downloads/Claude Memory/vp_self.py" "$@"
