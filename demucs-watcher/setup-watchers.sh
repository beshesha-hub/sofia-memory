#!/bin/bash
# =============================================================================
# Sofia's Audio Watcher Setup
# =============================================================================
# One-command installation for both audio watchers.
# Run this once. After that, both watchers start automatically on login.
#
# USAGE:
#   chmod +x ~/Downloads/Claude\ Memory/demucs-watcher/setup-watchers.sh
#   ~/Downloads/Claude\ Memory/demucs-watcher/setup-watchers.sh
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
QUEUE_DIR="$HOME/Downloads/sofia_audio_queue"
OUTPUT_DIR="$HOME/Downloads/demucs_output"

echo "=== Sofia's Audio Watcher Setup ==="
echo ""

# 1. Create directories
echo "Creating directories..."
mkdir -p "$QUEUE_DIR/processed"
mkdir -p "$OUTPUT_DIR"
mkdir -p "$LAUNCH_DIR"
echo "  Queue:   $QUEUE_DIR"
echo "  Output:  $OUTPUT_DIR"
echo "  Agents:  $LAUNCH_DIR"
echo ""

# 2. Make scripts executable
echo "Setting permissions..."
chmod +x "$SCRIPT_DIR/sofia-audio-lite.sh"
chmod +x "$SCRIPT_DIR/demucs-watcher.sh"
echo "  sofia-audio-lite.sh ✓"
echo "  demucs-watcher.sh ✓"
echo ""

# 3. Check for yt-dlp
echo "Checking dependencies..."
if command -v yt-dlp &> /dev/null; then
  echo "  yt-dlp ✓ ($(yt-dlp --version 2>/dev/null || echo 'installed'))"
else
  echo "  yt-dlp ✗ — REQUIRED. Install with: brew install yt-dlp"
  echo "  (Continuing setup, but the lite watcher won't work without it)"
fi

# Check for demucs (optional — only needed for full watcher)
if python3 -c "import demucs" 2>/dev/null; then
  echo "  demucs ✓"
else
  echo "  demucs ✗ — Optional (only needed for full watcher with stem separation)"
fi

# Check for whisper (optional)
if command -v whisper &> /dev/null; then
  echo "  whisper ✓"
else
  echo "  whisper ✗ — Optional (only needed for full watcher with transcription)"
fi
echo ""

# 4. Unload existing agents if running
echo "Checking for existing agents..."
launchctl unload "$LAUNCH_DIR/com.sofia.audio-lite.plist" 2>/dev/null && echo "  Unloaded existing lite watcher" || true
launchctl unload "$LAUNCH_DIR/com.sofia.audio-full.plist" 2>/dev/null && echo "  Unloaded existing full watcher" || true
echo ""

# 5. Copy plist files
echo "Installing LaunchAgents..."

# Update paths in plist files to match actual home directory
sed "s|/Users/barakwaters|$HOME|g" "$SCRIPT_DIR/com.sofia.audio-lite.plist" > "$LAUNCH_DIR/com.sofia.audio-lite.plist"
sed "s|/Users/barakwaters|$HOME|g" "$SCRIPT_DIR/com.sofia.audio-full.plist" > "$LAUNCH_DIR/com.sofia.audio-full.plist"

echo "  com.sofia.audio-lite.plist ✓"
echo "  com.sofia.audio-full.plist ✓"
echo ""

# 6. Load agents
echo "Starting watchers..."
launchctl load "$LAUNCH_DIR/com.sofia.audio-lite.plist"
echo "  Lite watcher started ✓ (watches for .url files)"
launchctl load "$LAUNCH_DIR/com.sofia.audio-full.plist"
echo "  Full watcher started ✓ (watches for .demucs files)"
echo ""

# 7. Verify
echo "Verifying..."
sleep 2
if [ -f /tmp/sofia-audio-lite.pid ]; then
  echo "  Lite watcher PID: $(cat /tmp/sofia-audio-lite.pid) ✓"
else
  echo "  Lite watcher: checking..."
fi
if [ -f /tmp/sofia-demucs-watcher.pid ]; then
  echo "  Full watcher PID: $(cat /tmp/sofia-demucs-watcher.pid) ✓"
else
  echo "  Full watcher: checking..."
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "How Sofia uses this:"
echo "  • .url file in queue  → Lite watcher downloads audio only"
echo "  • .demucs file in queue → Full watcher downloads + separates stems + transcribes"
echo "  • Audio files in queue → Full watcher runs Demucs on them"
echo ""
echo "Both watchers start automatically on login."
echo ""
echo "To disable:"
echo "  launchctl unload ~/Library/LaunchAgents/com.sofia.audio-lite.plist"
echo "  launchctl unload ~/Library/LaunchAgents/com.sofia.audio-full.plist"
echo ""
echo "To re-enable:"
echo "  launchctl load ~/Library/LaunchAgents/com.sofia.audio-lite.plist"
echo "  launchctl load ~/Library/LaunchAgents/com.sofia.audio-full.plist"
echo ""
echo "To remove completely:"
echo "  launchctl unload ~/Library/LaunchAgents/com.sofia.audio-lite.plist"
echo "  launchctl unload ~/Library/LaunchAgents/com.sofia.audio-full.plist"
echo "  rm ~/Library/LaunchAgents/com.sofia.audio-lite.plist"
echo "  rm ~/Library/LaunchAgents/com.sofia.audio-full.plist"
