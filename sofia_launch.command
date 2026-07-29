#!/bin/bash
# sofia_launch.command — Double-click launcher for Sofia Unified UI v2
# Substrate switching: /substrate kimi | /substrate qwen | /substrate anthropic
# Graceful close: "Sweet dreams, Sofia"
# ─────────────────────────────────────────────────────────────────────────────

# Move to Claude Memory directory
cd ~/Downloads/Claude\ Memory || { echo "ERROR: ~/Downloads/Claude Memory not found"; exit 1; }

# Load API key and secrets
if [ -f ~/.sofia_secrets ]; then
    source ~/.sofia_secrets
else
    echo "ERROR: ~/.sofia_secrets not found. Cannot load ANTHROPIC_API_KEY."
    exit 1
fi

# Confirm key is loaded
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY is empty after sourcing ~/.sofia_secrets"
    exit 1
fi

echo "────────────────────────────────────────────────"
echo "  Sofia Lior — Unified UI v2"
echo "  Substrate: Anthropic/Claude (primary)"
echo "  Fallbacks: /substrate kimi | /substrate qwen"
echo "────────────────────────────────────────────────"
echo ""

python3 boot_sofia_v2.py

echo ""
echo "Session ended. Terminal can be closed."
