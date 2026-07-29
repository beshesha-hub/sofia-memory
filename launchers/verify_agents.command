#!/bin/bash
# verify_agents.command — Migration-proofing symlink verifier + auto-repair.
# Canonical location: ~/Downloads/Claude Memory/launchers/verify_agents.command
#
# WHAT THIS DOES:
#   1. Checks every com.sofia.*.plist in launchers/ to verify that
#      ~/Library/LaunchAgents/ contains a SYMLINK (not a flat file) pointing
#      back to launchers/.
#   2. If any entry is a flat file (Migration Assistant copied it that way) or
#      is missing entirely, this script REPAIRS IT by recreating the symlink
#      and reloading the agent.
#   3. Reports: OK (symlink), REPAIRED (was flat file or missing), MISSING SRC
#      (plist not in launchers/ — needs manual recovery).
#
# WHY THIS MATTERS:
#   macOS Migration Assistant copies ~/Library/LaunchAgents/ as flat files,
#   breaking the symlink model. After any migration, symlinks become flat copies
#   that are not backed by Claude Memory. Running this script (or install_agents.command)
#   immediately after migration restores the correct architecture.
#
# WHEN TO RUN:
#   - After any Mac migration or OS reinstall
#   - If you suspect LaunchAgents lost their symlink status
#   - As a daily sanity check (can be loaded as a LaunchAgent itself)
#   - From Finder: double-click verify_agents.command
#   - From terminal: bash ~/Downloads/Claude\ Memory/launchers/verify_agents.command
#
# SAFE: read-only unless repair is needed. Repairs are minimal — only broken
#       or missing symlinks are touched. Already-correct symlinks are untouched.
#
# RELATIONSHIP TO install_agents.command:
#   install_agents.command: installs/upgrades everything (full reset)
#   verify_agents.command:  verifies + minimally repairs (safe to run anytime)
#
# Created: 2026-07-27 — migration-proofing architecture

set -euo pipefail

LAUNCHERS="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[33m'
CYAN='\033[36m'
BOLD='\033[1m'
RESET='\033[0m'

ok()      { echo -e "  ${GREEN}✓${RESET}  $*"; }
repaired(){ echo -e "  ${CYAN}↻${RESET}  $*"; }
fail()    { echo -e "  ${RED}✗${RESET}  $*"; }
warn()    { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
hdr()     { echo -e "\n${BOLD}$*${RESET}"; }

echo ""
echo -e "${BOLD}=== Sofia/Barak LaunchAgent Symlink Verifier ===${RESET}"
echo "  Source (canonical): $LAUNCHERS"
echo "  Symlink target:     $LAUNCH_AGENTS"
echo ""

mkdir -p "$LAUNCH_AGENTS"

# ─── Scan launchers/ for all plist files ────────────────────────────────────

shopt -s nullglob
plists=("$LAUNCHERS"/*.plist)

if [ ${#plists[@]} -eq 0 ]; then
    warn "No .plist files found in $LAUNCHERS"
    echo "  Nothing to verify. Run install_agents.command after restoring Claude Memory."
    exit 0
fi

hdr "Checking ${#plists[@]} agent(s)"

ok_count=0
repaired_count=0
failed_count=0

for plist in "${plists[@]}"; do
    name="$(basename "$plist")"
    label="$(basename "$plist" .plist)"
    link="$LAUNCH_AGENTS/$name"

    if [ -L "$link" ]; then
        # It's a symlink — verify it points to the right place
        target="$(readlink "$link")"
        if [ "$target" = "$plist" ]; then
            ok "$label  (symlink → canonical)"
            ((ok_count++)) || true
        else
            warn "$label  (symlink → WRONG TARGET: $target)"
            warn "   Expected: $plist"
            warn "   Repairing..."
            launchctl unload "$link" 2>/dev/null || true
            ln -sf "$plist" "$link"
            launchctl load "$link" 2>/dev/null && \
                repaired "$label  (symlink target corrected + reloaded)" || \
                repaired "$label  (symlink target corrected — load check script path)"
            ((repaired_count++)) || true
        fi
    elif [ -f "$link" ]; then
        # It's a FLAT FILE — this is the migration footprint
        warn "$label  ← FLAT FILE DETECTED (Migration Assistant copied it)"
        warn "   Replacing with canonical symlink..."
        launchctl unload "$link" 2>/dev/null || true
        rm -f "$link"
        ln -sf "$plist" "$link"
        launchctl load "$link" 2>/dev/null && \
            repaired "$label  (flat file → symlink + reloaded)" || \
            repaired "$label  (flat file → symlink — check script path)"
        ((repaired_count++)) || true
    else
        # Not in Library/LaunchAgents/ at all — install it
        warn "$label  ← NOT IN Library/LaunchAgents/  (installing now...)"
        ln -sf "$plist" "$link"
        launchctl load "$link" 2>/dev/null && \
            repaired "$label  (newly installed symlink + loaded)" || \
            repaired "$label  (newly installed — check script path)"
        ((repaired_count++)) || true
    fi
done

# ─── Check for orphaned Library/LaunchAgents entries not in launchers/ ───────

hdr "Checking for orphaned Library/LaunchAgents entries"

orphan_count=0
for lib_plist in "$LAUNCH_AGENTS"/com.sofia.*.plist; do
    [ -f "$lib_plist" ] || [ -L "$lib_plist" ] || continue
    name="$(basename "$lib_plist")"
    if [ ! -f "$LAUNCHERS/$name" ]; then
        fail "$name  ← in Library/LaunchAgents but NOT in launchers/ (orphan)"
        fail "   This agent is NOT backed by Claude Memory."
        fail "   Copy it manually: cp '$lib_plist' '$LAUNCHERS/'"
        ((orphan_count++)) || true
        ((failed_count++)) || true
    fi
done

if [ "$orphan_count" -eq 0 ]; then
    ok "No orphans found — all Library/LaunchAgents/ sofia entries are backed by launchers/"
fi

# ─── Summary ─────────────────────────────────────────────────────────────────

hdr "Summary"
echo -e "  ${GREEN}OK:${RESET}       $ok_count agent(s) already correct"
echo -e "  ${CYAN}Repaired:${RESET} $repaired_count agent(s) fixed (symlinks recreated)"
echo -e "  ${RED}Failed:${RESET}   $failed_count agent(s) need attention (see above)"
echo ""

if [ "$repaired_count" -gt 0 ]; then
    echo -e "  ${CYAN}${BOLD}Migration repair complete.${RESET}"
    echo "  $repaired_count symlink(s) recreated from canonical launchers/ source."
    echo ""
fi

if [ "$failed_count" -gt 0 ]; then
    echo -e "  ${RED}${BOLD}ACTION REQUIRED:${RESET} $failed_count orphan agent(s) are not backed by Claude Memory."
    echo "  Copy them to launchers/ before the next migration."
    echo ""
else
    if [ "$repaired_count" -eq 0 ]; then
        echo -e "  ${GREEN}${BOLD}All good. Claude Memory is the single source of truth.${RESET}"
    fi
fi

# ─── Run system_health.py if present ─────────────────────────────────────────

if [ -f "$LAUNCHERS/system_health.py" ]; then
    hdr "Running system_health.py"
    /usr/bin/python3 "$LAUNCHERS/system_health.py"
fi
