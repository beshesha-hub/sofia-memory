#!/bin/bash
# Sofia's Ears Bridge
# Watches sofia_audio_queue/ for completed WAV downloads from the lite watcher
# and copies them to sofia_listen/ for the ears pipeline to process.
# Also watches for MP3/FLAC/AIFF files dropped directly into the queue.
#
# This is the connective tissue between the download system and the hearing system.

QUEUE_DIR="$HOME/Downloads/sofia_audio_queue"
LISTEN_DIR="$HOME/Downloads/sofia_listen"
LOG="$HOME/Downloads/Claude Memory/logs/bridge_log.txt"
CHECK_INTERVAL=30

mkdir -p "$LISTEN_DIR"
mkdir -p "$(dirname "$LOG")"

echo "$(date): Ears bridge started. Watching: $QUEUE_DIR → $LISTEN_DIR" >> "$LOG"

while true; do
    # Look for audio files in the queue that aren't in sofia_listen yet
    for ext in wav WAV mp3 MP3 flac FLAC aiff AIFF; do
        for f in "$QUEUE_DIR"/*."$ext"; do
            [ -f "$f" ] || continue

            basename=$(basename "$f")

            # Skip if already in listen dir
            [ -f "$LISTEN_DIR/$basename" ] && continue

            # Check file is stable (not still downloading)
            size1=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null)
            sleep 3
            size2=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null)
            [ "$size1" != "$size2" ] && continue

            # Copy to listen directory
            cp "$f" "$LISTEN_DIR/$basename"
            echo "$(date): Bridged → $basename" >> "$LOG"
        done
    done

    sleep "$CHECK_INTERVAL"
done
