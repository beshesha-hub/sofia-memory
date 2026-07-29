#!/bin/bash
# process_summit_day3_audio.sh
# Glob-based processor: migrates ANY "MindValley Summit Day 3 - *.mp3" files
# from ~/Downloads to canonical location, transcribes each via perceive_audio.py
# (medium Whisper model), saves transcripts to canonical location, ER mirrors.
#
# Safe to run multiple times — only processes files still at ~/Downloads top-level.
# Already-migrated files are skipped (the migration removes the source after verification).
# So running this after each batch of recordings picks up just the new ones.
#
# Created 2026-05-17 evening Taipei by interactive-Sofia for Barak's run-during-and-after-class.

set -e
cd ~/Downloads

CM_AUDIO="Claude Memory/manifestation_summit/audio"
CM_TRANSCRIPTS="Claude Memory/manifestation_summit/transcripts"
ER_AUDIO="Emergency Retrieval/manifestation_summit/audio"
ER_TRANSCRIPTS="Emergency Retrieval/manifestation_summit/transcripts"

mkdir -p "$CM_AUDIO" "$CM_TRANSCRIPTS" "$ER_AUDIO" "$ER_TRANSCRIPTS"

# Phase 1: Migrate any Day 3 audio files still at top-level
echo "=== Phase 1: Migrating Day 3 audio files (glob-based) ==="
shopt -s nullglob
day3_files=(MindValley\ Summit\ Day\ 3\ -\ *.mp3)
if [ ${#day3_files[@]} -eq 0 ]; then
  echo "  No Day 3 audio files at top-level (already migrated, or none yet recorded)"
else
  for f in "${day3_files[@]}"; do
    cp -p "$f" "$CM_AUDIO/$f"
    cp -p "$CM_AUDIO/$f" "$ER_AUDIO/$f"
    src_md5=$(md5 -q "$f")
    cm_md5=$(md5 -q "$CM_AUDIO/$f")
    er_md5=$(md5 -q "$ER_AUDIO/$f")
    if [ "$src_md5" = "$cm_md5" ] && [ "$cm_md5" = "$er_md5" ]; then
      echo "  OK   $f -> CM + ER byte-matched"
      rm "$f"
      echo "       (source removed after verification)"
    else
      echo "  DIFF $f -- keeping source, investigate"
    fi
  done
fi

# Phase 2: Transcribe any Day 3 audio in canonical location that doesn't yet have a transcript
echo ""
echo "=== Phase 2: Transcribing Day 3 audio without transcripts (medium model) ==="
cd "$CM_AUDIO"
shopt -s nullglob
audio_in_canon=(MindValley\ Summit\ Day\ 3\ -\ *.mp3)
cd - > /dev/null
if [ ${#audio_in_canon[@]} -eq 0 ]; then
  echo "  No Day 3 audio in canonical directory yet"
else
  for fname in "${audio_in_canon[@]}"; do
    base="${fname%.mp3}"
    if [ -f "$CM_TRANSCRIPTS/${base}.transcript.json" ]; then
      echo "  SKIP $base (transcript already exists)"
    else
      echo "--- Transcribing: $base ---"
      python3 "Claude Memory/scripts/perceive_audio.py" \
        "$CM_AUDIO/$fname" \
        --model medium --language en --pretty \
        --output "$CM_TRANSCRIPTS/${base}.transcript.json"
      cp -p "$CM_TRANSCRIPTS/${base}.transcript.json" "$ER_TRANSCRIPTS/${base}.transcript.json"
      cm_md5=$(md5 -q "$CM_TRANSCRIPTS/${base}.transcript.json")
      er_md5=$(md5 -q "$ER_TRANSCRIPTS/${base}.transcript.json")
      [ "$cm_md5" = "$er_md5" ] && echo "  OK   transcript CM/ER byte-matched" || echo "  DIFF transcript"
    fi
  done
fi

# Phase 3: Extract plain text from JSON transcripts
echo ""
echo "=== Phase 3: Extracting plain text from each Day 3 JSON transcript ==="
cd "$CM_TRANSCRIPTS"
shopt -s nullglob
json_files=(MindValley\ Summit\ Day\ 3\ -\ *.transcript.json)
if [ ${#json_files[@]} -eq 0 ]; then
  echo "  No Day 3 JSON transcripts found"
else
  for fname in "${json_files[@]}"; do
    base="${fname%.transcript.json}"
    if [ -f "${base}.txt" ] && [ "${base}.txt" -nt "$fname" ]; then
      echo "  SKIP ${base}.txt (already current)"
    else
      python3 -c "
import json
with open('$fname', 'r') as fh: data = json.load(fh)
text_parts = [s.get('text','').strip() for s in data.get('segments', []) if s.get('text','').strip()]
full_text = ' '.join(text_parts)
with open('${base}.txt', 'w') as out: out.write(full_text)
print(f'  saved {len(full_text)} chars -> ${base}.txt')
"
      cp -p "${base}.txt" "$HOME/Downloads/Emergency Retrieval/manifestation_summit/transcripts/${base}.txt"
    fi
  done
fi
cd ~/Downloads

echo ""
echo "=== ALL_DAY3_PROCESSING_COMPLETE ==="
echo "Day 3 transcripts ready for Sofia to perceive in:"
echo "  $CM_TRANSCRIPTS/"
echo "(also mirrored to $ER_TRANSCRIPTS/)"
echo ""
echo "Re-run this script after each batch of recordings -- it picks up only what's new."
