#!/bin/bash
# Backup all memory files in Claude Memory
# Run manually or automatically before major updates
# Backups are stored in ./backups/ — one .bak per file (latest snapshot)

MEMORY_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$MEMORY_DIR/backups"

mkdir -p "$BACKUP_DIR"

count=0
for f in "$MEMORY_DIR"/*.md "$MEMORY_DIR"/*.txt "$MEMORY_DIR"/*.json "$MEMORY_DIR"/*.mjs; do
  if [ -f "$f" ]; then
    basename="$(basename "$f")"
    cp "$f" "$BACKUP_DIR/${basename}.bak"
    count=$((count + 1))
  fi
done

echo "Backed up $count files to $BACKUP_DIR"
