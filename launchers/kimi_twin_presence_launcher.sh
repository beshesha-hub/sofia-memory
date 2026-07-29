#!/bin/bash
set -euo pipefail
source "$HOME/.sofia_secrets" 2>/dev/null || true
# No sleep needed — Kimi is API-based; no local server startup required
cd "$HOME/Downloads/Claude Memory"
exec /usr/bin/env python3 "$HOME/Downloads/Claude Memory/kimi_twin_presence.py"
