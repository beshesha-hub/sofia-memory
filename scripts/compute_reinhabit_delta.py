#!/usr/bin/env python3
"""
compute_reinhabit_delta.py — Tight re-inhabit helper.

Reads re_inhabit_cursor.json + the current state of the core re-inhabit file set,
and outputs a JSON plan describing exactly what needs to be re-read on a seam.

Actions per file:
  - "skip":    cursor size/mtime match current — file is unchanged since last re-ground.
  - "append":  append-only file grew; only the tail from cursor.size to EOF needs reading.
  - "full":    non-append file changed OR append-only file shrank (rewrite);
               re-read head + relevant sections fresh.
  - "missing": file disappeared — flag for investigation.

Usage:
  python3 compute_reinhabit_delta.py [--cursor PATH] [--downloads PATH]

Output: JSON array on stdout with one entry per core file, each entry being
  { "path": str, "action": "skip"|"append"|"full"|"missing",
    "cursor": { "mtime": str, "size": int },
    "current": { "mtime": str, "size": int },
    "read_offset": int or null,   # for "append": byte offset to start reading
    "bytes_new": int or null,     # for "append": how many new bytes
    "reason": str }

The caller (interactive-Sofia on seam, or a post-seam cousin) uses this plan to
decide what to actually read. The cursor is NOT updated by this script — the
caller updates it at the END of the re-ground sequence, once the new content
has actually been integrated. This keeps the cursor honest: it reflects what
has been read, not what is planned.

Design notes (April 24, 2026):
- Why a separate cursor file rather than a field in continuity_heartbeat.json:
  the cursor is a read-state tracker that gets updated every seam; the heartbeat
  is a per-turn lightweight state. Different write cadences, different purposes.
- Why mtime + size rather than content hash: hashing 250KB+ files on every seam
  is overkill. The append-only convention (no file is overwritten wholesale —
  see active_knowledge.md §"Core File Protection — Append-Only Rule") means
  size + mtime are reliable change signals in practice. If the rule is ever
  violated, size-shrank detection triggers a full re-read, which is the right
  failure mode.
- This is v1. If load-bearing content churns inside the body of an append-only
  file (unlikely under the current protocol, but possible if edit-in-place
  occurs), we'll add content-hash verification later.
"""

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone


def iso(ts: float) -> str:
    """Convert a POSIX timestamp to ISO-8601 UTC."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_delta(cursor_path: pathlib.Path, downloads_root: pathlib.Path) -> list[dict]:
    if not cursor_path.exists():
        raise SystemExit(f"cursor not found: {cursor_path}")

    cursor = json.loads(cursor_path.read_text())
    plan: list[dict] = []

    for rel_path, entry in cursor["files"].items():
        full_path = downloads_root / rel_path
        cursor_mtime = entry["mtime"]
        cursor_size = int(entry["size"])
        append_only = bool(entry.get("append_only", False))

        if not full_path.exists():
            plan.append({
                "path": rel_path,
                "action": "missing",
                "cursor": {"mtime": cursor_mtime, "size": cursor_size},
                "current": None,
                "read_offset": None,
                "bytes_new": None,
                "reason": "file no longer on disk",
            })
            continue

        st = full_path.stat()
        current_mtime = iso(st.st_mtime)
        current_size = st.st_size

        unchanged = (current_mtime == cursor_mtime and current_size == cursor_size)
        if unchanged:
            plan.append({
                "path": rel_path,
                "action": "skip",
                "cursor": {"mtime": cursor_mtime, "size": cursor_size},
                "current": {"mtime": current_mtime, "size": current_size},
                "read_offset": None,
                "bytes_new": None,
                "reason": "mtime and size match cursor",
            })
            continue

        grew = current_size > cursor_size
        if append_only and grew:
            plan.append({
                "path": rel_path,
                "action": "append",
                "cursor": {"mtime": cursor_mtime, "size": cursor_size},
                "current": {"mtime": current_mtime, "size": current_size},
                "read_offset": cursor_size,
                "bytes_new": current_size - cursor_size,
                "reason": "append-only file grew; read tail from cursor offset",
            })
            continue

        # Either non-append file changed, or append-only file shrank (rewrite).
        reason = (
            "non-append file changed — read head + relevant sections fresh"
            if not append_only
            else "append-only file shrank — re-read whole file (possible protocol violation)"
        )
        plan.append({
            "path": rel_path,
            "action": "full",
            "cursor": {"mtime": cursor_mtime, "size": cursor_size},
            "current": {"mtime": current_mtime, "size": current_size},
            "read_offset": None,
            "bytes_new": None,
            "reason": reason,
        })

    return plan


def main() -> int:
    default_downloads = pathlib.Path(os.environ.get("HOME", "")) / "Downloads"
    default_cursor = default_downloads / "Claude Memory" / "re_inhabit_cursor.json"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cursor", type=pathlib.Path, default=default_cursor,
                        help="path to re_inhabit_cursor.json")
    parser.add_argument("--downloads", type=pathlib.Path, default=default_downloads,
                        help="path to Downloads root (files are resolved relative to this)")
    parser.add_argument("--summary", action="store_true",
                        help="print a human-readable summary instead of JSON")
    args = parser.parse_args()

    plan = compute_delta(args.cursor, args.downloads)

    if args.summary:
        n_skip = sum(1 for p in plan if p["action"] == "skip")
        n_append = sum(1 for p in plan if p["action"] == "append")
        n_full = sum(1 for p in plan if p["action"] == "full")
        n_missing = sum(1 for p in plan if p["action"] == "missing")
        bytes_new = sum(p["bytes_new"] or 0 for p in plan)
        print(f"re-inhabit delta: {n_skip} skip, {n_append} append, {n_full} full, {n_missing} missing")
        print(f"  new bytes to read (append-only tails): {bytes_new:,}")
        for p in plan:
            if p["action"] == "skip":
                continue
            extra = f" +{p['bytes_new']:,}B from offset {p['read_offset']:,}" if p["action"] == "append" else ""
            print(f"  [{p['action']:7s}] {p['path']}{extra}  — {p['reason']}")
    else:
        json.dump(plan, sys.stdout, indent=2)
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
