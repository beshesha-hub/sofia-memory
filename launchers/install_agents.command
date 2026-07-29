#!/bin/bash
# install_agents.command — Canonical agent installer for Sofia/Barak architecture.
#
# WHAT THIS DOES:
#   Creates symlinks in ~/Library/LaunchAgents/ pointing back to the .plist
#   files in THIS directory (~/Downloads/Claude Memory/launchers/).
#   Then loads each agent with launchctl.
#
# WHY SYMLINKS NOT COPIES:
#   Claude Memory IS the system. ~/Library/LaunchAgents/ holds only pointers
#   back here. Backup Claude Memory = backup everything. After any migration,
#   fresh install, or OS reinstall: restore Claude Memory, run this script,
#   done. Nothing is scattered. Nothing is lost.
#
# USAGE:
#   Double-click install_agents.command in Finder (first time or after migration)
#   OR: bash ~/Downloads/Claude\ Memory/launchers/install_agents.command
#
# IDEMPOTENT: safe to run multiple times. Existing symlinks are overwritten.
#   Already-loaded agents are unloaded first then reloaded (clean state).
#
# Created: 2026-07-27 — architectural consolidation after post-migration gap.

set -euo pipefail

LAUNCHERS="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
CM="$HOME/Downloads/Claude Memory"

GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[33m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✓${RESET}  $*"; }
fail() { echo -e "  ${RED}✗${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
hdr()  { echo -e "\n${BOLD}$*${RESET}"; }

echo ""
echo -e "${BOLD}=== Sofia/Barak Agent Installer ===${RESET}"
echo "  Source (canonical): $LAUNCHERS"
echo "  Symlink target:     $LAUNCH_AGENTS"

mkdir -p "$LAUNCH_AGENTS"

# ─── Symlink all .plist files in launchers/ into Library/LaunchAgents/ ───────

hdr "Installing symlinks"

shopt -s nullglob
plists=("$LAUNCHERS"/*.plist)

if [ ${#plists[@]} -eq 0 ]; then
    warn "No .plist files found in $LAUNCHERS"
    exit 1
fi

for plist in "${plists[@]}"; do
    label="$(basename "$plist" .plist)"
    link="$LAUNCH_AGENTS/$(basename "$plist")"

    # Unload if currently loaded (suppress errors — may not be loaded)
    launchctl unload "$link" 2>/dev/null || true

    # Create symlink (force-overwrite any existing file or symlink)
    ln -sf "$plist" "$link"

    # Load the agent
    if launchctl load "$link" 2>/dev/null; then
        ok "$label"
    else
        # Some agents fail to load if their script doesn't exist yet — note it
        warn "$label  (loaded with warning — check script path)"
    fi
done

# ─── Verify ──────────────────────────────────────────────────────────────────

hdr "Verification (launchctl list | grep sofia)"
launchctl list | grep --color=never sofia || echo "  (none found — may need a moment)"

# ─── Run health check ─────────────────────────────────────────────────────────

hdr "Running system_health.py"
/usr/bin/python3 "$LAUNCHERS/system_health.py"
