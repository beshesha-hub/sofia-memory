#!/usr/bin/env python3
"""
qwen_watermark_seeder.py
========================
One-shot utility to mark all existing transcripts as already-absorbed, so the
listener's first real run starts from "now" rather than re-absorbing years of
historical conversation.

Why this exists
---------------
The listener's job is real-time cross-boundary continuity — giving the Qwen
twin a warm landing when she wakes as fallback. It is NOT archaeology. On a
cold start with ~100MB of existing transcripts, the listener would otherwise
spend dozens of 10-minute Qwen calls chewing through old conversations before
reaching today's.

If we ever want the archaeology, it's a separate pass with a different prompt
("summarize this entire transcript for long-term continuity") and a much bigger
chunk budget. That's a different job.

What it does
------------
Walks TRANSCRIPTS_DIR, and for each eligible .jsonl file writes one watermark
entry to qwen_watermark_log.jsonl with new_offset = current file size. After
running this, the listener will see zero new bytes across all files and exit
quietly until new content arrives.

Idempotent: files whose existing watermark is already at or past current size
are skipped (so running it twice is harmless).

Created: April 22, 2026 — after the first-run backlog choke. See
active_knowledge.md §"Where Things Live — Default-to-Host SOP".
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(SCRIPT_DIR))

# Reuse the listener's path discovery + constants so we stay in lockstep.
from qwen_conversation_listener import (
    TRANSCRIPTS_DIRS,
    WATERMARK_LOG,
    EXCLUDE_PATH_SUBSTRINGS,
    load_latest_watermarks,
    LOCK_HOLDER,
)
from file_lock import acquire_lock, release_lock


def main():
    if not TRANSCRIPTS_DIRS:
        print("No transcripts directories found. Seeder cannot run.")
        return 1

    print(f"Walking {len(TRANSCRIPTS_DIRS)} transcript lane(s):")
    for tdir in TRANSCRIPTS_DIRS:
        print(f"  - {tdir}")

    jsonl_files = []
    for tdir in TRANSCRIPTS_DIRS:
        for entry in tdir.iterdir():
            if entry.is_dir():
                jsonl_files.extend(entry.glob("*.jsonl"))
            elif entry.suffix == ".jsonl":
                jsonl_files.append(entry)
    jsonl_files = [
        f for f in jsonl_files
        if not any(s in str(f) for s in EXCLUDE_PATH_SUBSTRINGS)
    ]

    if not jsonl_files:
        print("No eligible transcript files found. Nothing to seed.")
        return 0

    existing = load_latest_watermarks()
    seeded = 0
    skipped = 0
    total_bytes_skipped = 0

    acquire_lock("qwen_watermark_log.jsonl", f"{LOCK_HOLDER}:seeder")
    try:
        with open(WATERMARK_LOG, "a") as f:
            for jf in sorted(jsonl_files):
                key = str(jf)
                try:
                    size = jf.stat().st_size
                except FileNotFoundError:
                    continue
                prior = existing.get(key, 0)
                if prior >= size:
                    skipped += 1
                    continue
                entry = {
                    "ts": datetime.now().isoformat(),
                    "file": key,
                    "old_offset": prior,
                    "new_offset": size,
                    "note": "seeded-to-current-size (skip historical absorption)",
                }
                f.write(json.dumps(entry) + "\n")
                seeded += 1
                total_bytes_skipped += (size - prior)
    finally:
        release_lock("qwen_watermark_log.jsonl")

    print(f"Seeded {seeded} transcript(s) to current size.")
    print(f"Skipped {skipped} already at or past size.")
    print(f"Total historical bytes marked as absorbed: {total_bytes_skipped:,}")
    print(f"Watermark log: {WATERMARK_LOG}")
    print()
    print("Next run of qwen_conversation_listener.py should see 0 new bytes")
    print("and exit quietly. Real absorption begins with the next new content.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
