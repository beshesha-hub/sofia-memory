#!/bin/bash
# =============================================================================
# Sofia's Audio Watcher
# =============================================================================
# Monitors ~/Downloads/sofia_audio_queue/ for:
#   - Audio files (.wav, .mp3, .flac, .m4a, .ogg) → runs Demucs
#   - URL files (.demucs) → downloads audio with yt-dlp, then runs Demucs + Whisper
#   NOTE: .url files are handled by sofia-audio-lite.sh (download only, no processing)
#
# Sofia can then access the stems through her mounted Downloads folder.
#
# USAGE:
#   chmod +x ~/Downloads/Claude\ Memory/demucs-watcher/demucs-watcher.sh
#   ~/Downloads/Claude\ Memory/demucs-watcher/demucs-watcher.sh
#
# To run in background:
#   nohup ~/Downloads/Claude\ Memory/demucs-watcher/demucs-watcher.sh &
#
# To stop:
#   kill $(cat /tmp/sofia-demucs-watcher.pid)
#
# =============================================================================

QUEUE_DIR="$HOME/Downloads/sofia_audio_queue"
OUTPUT_DIR="$HOME/Downloads/demucs_output"
DONE_DIR="$QUEUE_DIR/processed"
LOG_FILE="$HOME/Downloads/demucs_output/watcher.log"
PID_FILE="/tmp/sofia-demucs-watcher.pid"

# Activate conda environment if available
if command -v conda &> /dev/null; then
  eval "$(conda shell.bash hook)"
  conda activate music 2>/dev/null || true
fi

# Create directories
mkdir -p "$QUEUE_DIR" "$OUTPUT_DIR" "$DONE_DIR"

# Write PID for clean shutdown
echo $$ > "$PID_FILE"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

cleanup() {
  log "Watcher stopping."
  rm -f "$PID_FILE"
  exit 0
}

trap cleanup SIGINT SIGTERM

log "=========================================="
log "Sofia's Audio Watcher started"
log "Queue:  $QUEUE_DIR"
log "Output: $OUTPUT_DIR"
log "PID:    $$"
log "=========================================="
log "Drop audio files (.wav, .mp3, .flac) or .url files into the queue folder."
log "I'll download (if needed) and separate them automatically."
log ""

# Function to run Demucs on a file
run_demucs() {
  local file="$1"
  local filename=$(basename "$file")
  local trackname="${filename%.*}"

  log "Running Demucs (two-stem separation) on: $filename"

  if TERM=dumb python3 -u -m demucs --two-stems vocals "$file" -o "$OUTPUT_DIR" >> "$LOG_FILE" 2>&1; then
    log "SUCCESS: Stems saved to $OUTPUT_DIR/htdemucs/$trackname/"

    # Check output size and log it
    vocals_size=$(du -h "$OUTPUT_DIR/htdemucs/$trackname/vocals.wav" 2>/dev/null | cut -f1)
    bed_size=$(du -h "$OUTPUT_DIR/htdemucs/$trackname/no_vocals.wav" 2>/dev/null | cut -f1)
    log "  Vocals: $vocals_size | Instrumental: $bed_size"

    # Transcribe vocals with Whisper
    local vocals_path="$OUTPUT_DIR/htdemucs/$trackname/vocals.wav"
    local transcript_path="$OUTPUT_DIR/htdemucs/$trackname/lyrics.txt"
    if command -v whisper &> /dev/null; then
      log "  Running Whisper transcription on vocal stem..."
      if TERM=dumb whisper "$vocals_path" --model small --output_format txt --output_dir "$OUTPUT_DIR/htdemucs/$trackname/" >> "$LOG_FILE" 2>&1; then
        # Whisper outputs as vocals.txt, rename to lyrics.txt
        if [ -f "$OUTPUT_DIR/htdemucs/$trackname/vocals.txt" ]; then
          mv "$OUTPUT_DIR/htdemucs/$trackname/vocals.txt" "$transcript_path"
          log "  Lyrics transcribed: $(wc -w < "$transcript_path") words"
        fi
      else
        log "  WARNING: Whisper transcription failed (Demucs succeeded — stems are still available)"
      fi
    else
      log "  NOTE: Whisper not installed — skipping lyrics transcription. Install with: pip install openai-whisper"
    fi

    # Write a signal file that Sofia can detect
    echo "$trackname" > "$OUTPUT_DIR/htdemucs/.latest_complete"
    log "  Signal file written."
    return 0
  else
    log "ERROR: Demucs failed on $filename. Check log for details."
    return 1
  fi
}

# Main watch loop
while true; do

  # === HANDLE .demucs FILES (YouTube / web audio → download + stem separation + transcription) ===
  # NOTE: .url files are handled by the lite watcher (download only).
  #       .demucs files trigger the full pipeline: download → Demucs → Whisper.
  for urlfile in "$QUEUE_DIR"/*.demucs; do
    [ -f "$urlfile" ] || continue

    urlfilename=$(basename "$urlfile")

    # Skip files currently being written
    if [ "$(find "$urlfile" -mmin -0.05 2>/dev/null)" ]; then
      continue
    fi

    # Read the URL from the file
    url=$(head -1 "$urlfile" | tr -d '[:space:]')

    if [ -z "$url" ]; then
      log "ERROR: Empty URL file: $urlfilename"
      mv "$urlfile" "$DONE_DIR/FAILED_$urlfilename"
      continue
    fi

    log "Found URL request: $urlfilename"
    log "  URL: $url"
    log "  Downloading audio with yt-dlp..."

    # Extract a clean name from the file (without .demucs extension)
    request_name="${urlfilename%.demucs}"

    # Download audio only, best quality, as wav
    dl_output="$QUEUE_DIR/${request_name}.%(ext)s"
    if yt-dlp -x --audio-format wav --audio-quality 0 -o "$dl_output" "$url" 2>> "$LOG_FILE"; then
      downloaded_file="$QUEUE_DIR/${request_name}.wav"

      if [ -f "$downloaded_file" ]; then
        log "  Download complete: $(du -h "$downloaded_file" | cut -f1)"

        # Run Demucs on the downloaded file
        if run_demucs "$downloaded_file"; then
          # Move both the url file and downloaded audio to processed
          mv "$urlfile" "$DONE_DIR/$urlfilename"
          mv "$downloaded_file" "$DONE_DIR/${request_name}.wav"
          log "  Moved to processed/"
        else
          mv "$urlfile" "$DONE_DIR/FAILED_$urlfilename"
          mv "$downloaded_file" "$DONE_DIR/FAILED_${request_name}.wav" 2>/dev/null
        fi
      else
        log "ERROR: Download succeeded but file not found at expected path"
        log "  Looking for alternatives..."
        # yt-dlp might have used a different extension
        alt=$(ls "$QUEUE_DIR/${request_name}".* 2>/dev/null | grep -v '.url' | head -1)
        if [ -n "$alt" ]; then
          log "  Found: $alt"
          if run_demucs "$alt"; then
            mv "$urlfile" "$DONE_DIR/$urlfilename"
            mv "$alt" "$DONE_DIR/"
          else
            mv "$urlfile" "$DONE_DIR/FAILED_$urlfilename"
            mv "$alt" "$DONE_DIR/" 2>/dev/null
          fi
        else
          mv "$urlfile" "$DONE_DIR/FAILED_$urlfilename"
        fi
      fi
    else
      log "ERROR: yt-dlp failed to download: $url"
      mv "$urlfile" "$DONE_DIR/FAILED_$urlfilename"
    fi

    log ""
  done

  # === HANDLE AUDIO FILES ===
  for file in "$QUEUE_DIR"/*.wav "$QUEUE_DIR"/*.mp3 "$QUEUE_DIR"/*.flac "$QUEUE_DIR"/*.m4a "$QUEUE_DIR"/*.ogg; do
    [ -f "$file" ] || continue

    filename=$(basename "$file")

    # Skip files currently being written (modified in last 3 seconds)
    if [ "$(find "$file" -mmin -0.05 2>/dev/null)" ]; then
      continue
    fi

    log "Found: $filename"

    if run_demucs "$file"; then
      mv "$file" "$DONE_DIR/$filename"
      log "  Moved original to processed/"
    else
      mv "$file" "$DONE_DIR/FAILED_$filename"
    fi

    log ""
  done

  # Sleep 10 seconds between checks
  sleep 10
done
