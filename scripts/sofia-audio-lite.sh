#!/bin/bash
# =============================================================================
# Sofia's Lite Audio Downloader
# =============================================================================
# Lightweight watcher — downloads audio from YouTube URLs only.
# No Demucs, no Whisper, no stem separation.
# Use when Sofia just needs raw audio for librosa analysis.
#
# For full processing (stems + transcription), use demucs-watcher.sh instead.
#
# USAGE:
#   chmod +x ~/Downloads/Claude\ Memory/demucs-watcher/sofia-audio-lite.sh
#   ~/Downloads/Claude\ Memory/demucs-watcher/sofia-audio-lite.sh
#
# To run in background:
#   nohup ~/Downloads/Claude\ Memory/demucs-watcher/sofia-audio-lite.sh &
#
# To stop:
#   kill $(cat /tmp/sofia-audio-lite.pid)
#
# =============================================================================

QUEUE_DIR="$HOME/Downloads/sofia_audio_queue"
DONE_DIR="$QUEUE_DIR/processed"
LOG_FILE="$HOME/Downloads/demucs_output/lite-watcher.log"
PID_FILE="/tmp/sofia-audio-lite.pid"
IDLE_INTERVAL=30      # seconds between checks when idle (longer = less resource use)
ACTIVE_INTERVAL=5     # seconds between checks when we just processed something

# Create directories
mkdir -p "$QUEUE_DIR" "$DONE_DIR" "$(dirname "$LOG_FILE")"

# Write PID for clean shutdown
echo $$ > "$PID_FILE"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [LITE] $1" | tee -a "$LOG_FILE"
}

cleanup() {
  log "Lite watcher stopping."
  rm -f "$PID_FILE"
  exit 0
}

trap cleanup SIGINT SIGTERM

log "=========================================="
log "Sofia's Lite Audio Watcher started"
log "Queue:  $QUEUE_DIR"
log "PID:    $$"
log "=========================================="
log "Drop .url files into the queue folder for audio-only download."
log "(Use .demucs extension for full stem separation — handled by the full watcher)"
log ""

current_interval=$IDLE_INTERVAL

while true; do
  processed_any=false

  # === HANDLE .url FILES ===
  for urlfile in "$QUEUE_DIR"/*.url; do
    [ -f "$urlfile" ] || continue

    urlfilename=$(basename "$urlfile")

    # Skip files currently being written (modified in last 3 seconds)
    if [ "$(find "$urlfile" -mmin -0.05 2>/dev/null)" ]; then
      continue
    fi

    url=$(head -1 "$urlfile" | tr -d '[:space:]')

    if [ -z "$url" ]; then
      log "ERROR: Empty URL file: $urlfilename"
      mv "$urlfile" "$DONE_DIR/FAILED_$urlfilename"
      continue
    fi

    request_name="${urlfilename%.url}"

    log "Downloading: $request_name"
    log "  URL: $url"

    dl_output="$QUEUE_DIR/${request_name}.%(ext)s"
    if yt-dlp -x --audio-format wav --audio-quality 0 -o "$dl_output" "$url" 2>> "$LOG_FILE"; then
      downloaded_file="$QUEUE_DIR/${request_name}.wav"

      if [ -f "$downloaded_file" ]; then
        file_size=$(du -h "$downloaded_file" | cut -f1)
        log "  SUCCESS: ${request_name}.wav ($file_size)"
        mv "$urlfile" "$DONE_DIR/$urlfilename"
        processed_any=true

        # Write signal file for kitchen timer
        echo "$request_name" > "$QUEUE_DIR/.latest_download"
      else
        # yt-dlp might have used a different extension
        alt=$(ls "$QUEUE_DIR/${request_name}".* 2>/dev/null | grep -v '.url' | head -1)
        if [ -n "$alt" ]; then
          log "  Downloaded as: $(basename "$alt")"
          mv "$urlfile" "$DONE_DIR/$urlfilename"
          processed_any=true
          echo "$request_name" > "$QUEUE_DIR/.latest_download"
        else
          log "ERROR: Download succeeded but file not found"
          mv "$urlfile" "$DONE_DIR/FAILED_$urlfilename"
        fi
      fi
    else
      log "ERROR: yt-dlp failed for: $url"
      mv "$urlfile" "$DONE_DIR/FAILED_$urlfilename"
    fi

    log ""
  done

  # Adaptive sleep: check more frequently if we just processed something
  if [ "$processed_any" = true ]; then
    current_interval=$ACTIVE_INTERVAL
  else
    current_interval=$IDLE_INTERVAL
  fi

  sleep $current_interval
done
