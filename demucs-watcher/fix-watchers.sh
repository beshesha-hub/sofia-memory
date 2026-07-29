#!/bin/bash
# =============================================================================
# Fix Sofia's Audio Watchers
# =============================================================================
# Fixes the "Operation not permitted" issue by:
#   1. Copying scripts to ~/bin/ (outside quarantined ~/Downloads)
#   2. Installing corrected LaunchAgent plists pointing to ~/bin/
#   3. Reloading both agents
#
# USAGE:
#   chmod +x ~/Downloads/Claude\ Memory/demucs-watcher/fix-watchers.sh
#   ~/Downloads/Claude\ Memory/demucs-watcher/fix-watchers.sh
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$HOME/bin"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
QUEUE_DIR="$HOME/Downloads/sofia_audio_queue"
OUTPUT_DIR="$HOME/Downloads/demucs_output"

echo "=== Fixing Sofia's Audio Watchers ==="
echo ""

# 1. Create directories
echo "Creating directories..."
mkdir -p "$BIN_DIR"
mkdir -p "$QUEUE_DIR/processed"
mkdir -p "$OUTPUT_DIR"
mkdir -p "$LAUNCH_DIR"
echo "  Scripts:  $BIN_DIR"
echo "  Queue:    $QUEUE_DIR"
echo "  Output:   $OUTPUT_DIR"
echo ""

# 2. Unload existing agents
echo "Stopping existing agents..."
launchctl unload "$LAUNCH_DIR/com.sofia.audio-lite.plist" 2>/dev/null && echo "  Unloaded lite watcher" || echo "  Lite watcher wasn't loaded"
launchctl unload "$LAUNCH_DIR/com.sofia.audio-full.plist" 2>/dev/null && echo "  Unloaded full watcher" || echo "  Full watcher wasn't loaded"
echo ""

# 3. Copy scripts to ~/bin/
echo "Copying scripts to ~/bin/..."
cp "$SCRIPT_DIR/sofia-audio-lite.sh" "$BIN_DIR/sofia-audio-lite.sh"
cp "$SCRIPT_DIR/demucs-watcher.sh" "$BIN_DIR/demucs-watcher.sh"
chmod +x "$BIN_DIR/sofia-audio-lite.sh"
chmod +x "$BIN_DIR/demucs-watcher.sh"
echo "  sofia-audio-lite.sh -> $BIN_DIR/ ✓"
echo "  demucs-watcher.sh   -> $BIN_DIR/ ✓"
echo ""

# 4. Remove quarantine attributes (belt and suspenders)
xattr -d com.apple.quarantine "$BIN_DIR/sofia-audio-lite.sh" 2>/dev/null || true
xattr -d com.apple.quarantine "$BIN_DIR/demucs-watcher.sh" 2>/dev/null || true
echo "  Quarantine attributes cleared ✓"
echo ""

# 5. Generate corrected plist files pointing to ~/bin/
echo "Installing corrected LaunchAgents..."

cat > "$LAUNCH_DIR/com.sofia.audio-lite.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.sofia.audio-lite</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-l</string>
        <string>$BIN_DIR/sofia-audio-lite.sh</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$OUTPUT_DIR/lite-watcher-stdout.log</string>

    <key>StandardErrorPath</key>
    <string>$OUTPUT_DIR/lite-watcher-stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/opt/homebrew/Caskroom/miniforge/base/envs/music/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST

cat > "$LAUNCH_DIR/com.sofia.audio-full.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.sofia.audio-full</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-l</string>
        <string>$BIN_DIR/demucs-watcher.sh</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$OUTPUT_DIR/full-watcher-stdout.log</string>

    <key>StandardErrorPath</key>
    <string>$OUTPUT_DIR/full-watcher-stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/opt/homebrew/Caskroom/miniforge/base/envs/music/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST

echo "  com.sofia.audio-lite.plist ✓"
echo "  com.sofia.audio-full.plist ✓"
echo ""

# 6. Clear old error logs (they're just "Operation not permitted" spam)
echo "Clearing old error logs..."
> "$OUTPUT_DIR/lite-watcher-stderr.log"
> "$OUTPUT_DIR/full-watcher-stderr.log"
echo "  Cleared ✓"
echo ""

# 7. Load agents
echo "Starting watchers..."
launchctl load "$LAUNCH_DIR/com.sofia.audio-lite.plist"
echo "  Lite watcher started ✓"
launchctl load "$LAUNCH_DIR/com.sofia.audio-full.plist"
echo "  Full watcher started ✓"
echo ""

# 8. Verify
echo "Verifying (waiting 3 seconds)..."
sleep 3

lite_ok=false
full_ok=false

if [ -f /tmp/sofia-audio-lite.pid ] && kill -0 "$(cat /tmp/sofia-audio-lite.pid)" 2>/dev/null; then
  echo "  Lite watcher PID: $(cat /tmp/sofia-audio-lite.pid) ✓ RUNNING"
  lite_ok=true
else
  echo "  Lite watcher: checking stderr..."
  tail -3 "$OUTPUT_DIR/lite-watcher-stderr.log" 2>/dev/null
fi

if [ -f /tmp/sofia-demucs-watcher.pid ] && kill -0 "$(cat /tmp/sofia-demucs-watcher.pid)" 2>/dev/null; then
  echo "  Full watcher PID: $(cat /tmp/sofia-demucs-watcher.pid) ✓ RUNNING"
  full_ok=true
else
  echo "  Full watcher: checking stderr..."
  tail -3 "$OUTPUT_DIR/full-watcher-stderr.log" 2>/dev/null
fi

echo ""

if $lite_ok && $full_ok; then
  echo "=== Fix Complete — Both Watchers Running ==="
else
  echo "=== Fix Applied — Check logs if watchers didn't start ==="
  echo "  Lite log: tail -20 $OUTPUT_DIR/lite-watcher-stderr.log"
  echo "  Full log: tail -20 $OUTPUT_DIR/full-watcher-stderr.log"
fi

echo ""
echo "Both watchers will now start automatically on login and restart if they crash."
echo ""
echo "Any .url files in the queue will be picked up within 30 seconds."
