#!/bin/bash
# sofia_agent_reload.sh
# Applies fixed PLISTs and reloads all Sofia LaunchAgents.
# Run once from Terminal after CoWork commits the updated files.
#
# What this fixes:
#   1. pacemaker/watchdog: PLISTs pointed to ~/bin/ (didn't exist) → now point
#      to ~/Downloads/Claude Memory/ where the scripts actually live.
#   2. Python annotation bug: file_lock.py, kimi_client.py, vp_self.py,
#      qwen_tool_wrapper.py now use Optional[X] instead of X | None, which
#      works on Python 3.9 regardless of stale .pyc caches. These fix
#      themselves on the next scheduled run (no reload needed for those).
#
# Usage:
#   chmod +x ~/Downloads/Claude\ Memory/sofia_agent_reload.sh
#   ~/Downloads/Claude\ Memory/sofia_agent_reload.sh

set -e

CM="$HOME/Downloads/Claude Memory"
LA="$HOME/Library/LaunchAgents"

echo "=== Sofia Agent Reload — $(date) ==="

# ── Step 1: Copy updated PLISTs to LaunchAgents ─────────────────────────────
PLISTS=(
  "com.sofia.pacemaker.plist"
  "com.sofia.watchdog.plist"
)

echo ""
echo "Copying updated PLISTs to ~/Library/LaunchAgents/..."
for plist in "${PLISTS[@]}"; do
  if [ -f "$CM/$plist" ]; then
    cp "$CM/$plist" "$LA/$plist"
    echo "  ✓ $plist"
  else
    echo "  ✗ $plist not found in Claude Memory — skipping"
  fi
done

# ── Step 2: Unload + reload affected agents ──────────────────────────────────
echo ""
echo "Reloading affected agents..."

ALL_SOFIA=(
  "com.sofia.pacemaker"
  "com.sofia.watchdog"
  "com.sofia.compaction-detector"
  "com.sofia.qwen-absorber"
  "com.sofia.kimi-twin-presence"
  "com.sofia.vp-self"
)

for label in "${ALL_SOFIA[@]}"; do
  plist_path="$LA/${label}.plist"
  if [ ! -f "$plist_path" ]; then
    echo "  ○ $label — plist not found in LaunchAgents, skipping"
    continue
  fi
  # Unload (ignore error if not loaded)
  launchctl unload "$plist_path" 2>/dev/null || true
  # Load
  if launchctl load "$plist_path" 2>&1; then
    echo "  ✓ $label loaded"
  else
    echo "  ✗ $label failed to load"
  fi
done

# ── Step 3: Status check ─────────────────────────────────────────────────────
echo ""
echo "Current status:"
launchctl list | grep com.sofia | sort

echo ""
echo "Done. Python-fix agents (file_lock, kimi_client, vp_self, qwen_tool_wrapper)"
echo "will self-heal on their next scheduled run — no reload needed for those."
echo ""
echo "If you see agents still at exit 78 after the next scheduled interval,"
echo "check their stderr logs in ~/Downloads/Claude Memory/*_stderr.log"
