#!/bin/bash
# install_launchagents.sh — Install all Sofia LaunchAgents.
# Replaces CoWork scheduled tasks with native Mac LaunchAgents.
# Safe to re-run: unloads before reloading.
#
# Usage: bash ~/Downloads/Claude\ Memory/launchagents/install_launchagents.sh
# Verify: launchctl list | grep sofia

set -e
PLIST_DIR="$HOME/Downloads/Claude Memory/launchagents"
AGENT_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Downloads/Claude Memory/launchagents/logs"

mkdir -p "$LOG_DIR" "$AGENT_DIR"

install_agent() {
    local name="$1"
    local src="$PLIST_DIR/$name.plist"
    local dst="$AGENT_DIR/$name.plist"
    if [ ! -f "$src" ]; then
        echo "  SKIP $name (plist not found)"
        return
    fi
    launchctl unload "$dst" 2>/dev/null || true
    cp "$src" "$dst"
    launchctl load "$dst"
    echo "  ✓ $name"
}

echo ""
echo "Installing Sofia LaunchAgents (CoWork-independent cousins)..."
echo ""

# Infrastructure (pure Python, no LLM)
install_agent "com.sofia.preboot-handoff-rebuild"

# Cousin processes (call Anthropic API via cousin_base.py)
# NOTE: These require ANTHROPIC_API_KEY in the environment.
# LaunchAgents inherit a minimal environment — add the key via:
#   launchctl setenv ANTHROPIC_API_KEY "sk-..."
# Or source ~/.sofia_secrets inside each script (cousin_base.py handles this).
install_agent "com.sofia.awakening"
install_agent "com.sofia.sentinel"
install_agent "com.sofia.kitchen-timer"
install_agent "com.sofia.dream-cycle"
install_agent "com.sofia.nightly-consolidation"

# Extended cousins (completed 2026-06-11)
install_agent "com.sofia.audit-log-mirror"   # hourly belt-and-suspenders ER sync
install_agent "com.sofia.listener"           # Qwen context absorber (every 30 min)
install_agent "com.sofia.color-field-review" # Sunday 8 AM weekly synthesis
install_agent "com.sofia.music-exploration"  # Saturday 9 AM creative exploration

# Autonomous VP (KeepAlive — restarts automatically)
install_agent "com.sofia.vp-self"            # Expanded VP — auto-restarts, Qwen-backed

echo ""
echo "Done. Verify:"
echo "  launchctl list | grep sofia"
echo ""
echo "If API calls fail, ensure the key is visible to LaunchAgents:"
echo "  launchctl setenv ANTHROPIC_API_KEY \"\$ANTHROPIC_API_KEY\""
