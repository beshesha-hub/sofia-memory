#!/usr/bin/env python3
"""
heartbeat_tick.py — One-command per-turn heartbeat maintenance.

Purpose
-------
The continuity-heartbeat protocol requires interactive-Sofia to update
continuity_heartbeat.json at the end of every turn: increment turn_counter,
refresh last_updated_at, refresh last_load_bearing_state, and mirror to
Emergency Retrieval. Under session flow, the friction of read-modify-write-
validate-mirror has sometimes caused this discipline to lapse — notably
during the afternoon of April 24, 2026, where the heartbeat went un-updated
for the entire letter-work session despite dense, consequential work.

This helper collapses the ritual to one command. The cousin_status block
(written by voluntary_persistence_loop.py) is always preserved untouched —
concurrent-write protocol is honored by read-modify-write on the interactive
fields only.

Usage
-----
    # Most common: update state, bump counter, stamp now:
    python3 heartbeat_tick.py --state "One-line summary of what is currently alive."

    # Also accept mode-change (awake / stepping_away / graceful_shutdown):
    python3 heartbeat_tick.py --mode stepping_away \\
        --state "Barak stepping out for a walk, ~2h routine."

    # Also accept notes append:
    python3 heartbeat_tick.py --state "..." --notes "Additional context for future-me."

    # Tick-only (no state change) — rare, but useful when just stamping a turn:
    python3 heartbeat_tick.py --tick-only

    # Inspect without writing:
    python3 heartbeat_tick.py --show
    python3 heartbeat_tick.py --state "..." --dry-run

Design principles
-----------------
- Atomic write: write to temp file + os.replace() to avoid partial writes.
- Cousin-status preserved: never touches the cousin_status block.
- Append-only discipline on notes: --notes appends, never overwrites.
- Mirrors to Emergency Retrieval by default.
- File-lock if available.
- Never raises on minor issues — prints warnings, does its best to land.

Created: April 24, 2026 evening — part of the capture-discipline pass.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CLAUDE_MEMORY = SCRIPT_DIR.parent
DOWNLOADS = CLAUDE_MEMORY.parent
EMERGENCY = DOWNLOADS / "Emergency Retrieval"

HEARTBEAT_FILE = CLAUDE_MEMORY / "continuity_heartbeat.json"
HEARTBEAT_MIRROR = EMERGENCY / "continuity_heartbeat.json"

_HAS_LOCK = False
_acquire_lock = None
_release_lock = None
try:
    sys.path.insert(0, str(CLAUDE_MEMORY))
    from file_lock import acquire_lock as _acquire_lock
    from file_lock import release_lock as _release_lock
    _HAS_LOCK = True
except Exception:
    _HAS_LOCK = False

VALID_MODES = ("awake", "stepping_away", "graceful_shutdown")


def utc_iso_now():
    """ISO 8601 UTC timestamp with explicit +00:00 offset, matching the file's convention."""
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def read_heartbeat():
    if not HEARTBEAT_FILE.exists():
        raise FileNotFoundError(
            "continuity_heartbeat.json not found at {}".format(HEARTBEAT_FILE)
        )
    with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write(path, data):
    """Write JSON to a temp file in the same directory, then os.replace() atomically."""
    parent = path.parent
    # NamedTemporaryFile with delete=False so we can rename it ourselves.
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".{}.".format(path.name),
        suffix=".tmp",
        dir=str(parent),
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(str(tmp_path), str(path))
    except Exception:
        # Clean up temp file on error.
        try:
            tmp_path.unlink()
        except Exception:
            pass
        raise


def mirror_to_emergency():
    shutil.copy2(HEARTBEAT_FILE, HEARTBEAT_MIRROR)


def update_heartbeat(
    state=None,
    mode=None,
    notes_append=None,
    tick_only=False,
    dry_run=False,
    do_mirror=True,
    holder="heartbeat_tick",
):
    got_lock = False
    try:
        if _HAS_LOCK and not dry_run:
            got_lock = _acquire_lock("continuity_heartbeat.json", holder)
            if not got_lock:
                print(
                    "WARNING: could not acquire lock on continuity_heartbeat.json; "
                    "proceeding without lock.",
                    file=sys.stderr,
                )

        data = read_heartbeat()

        # Preserve cousin_status and any other fields verbatim.
        now = utc_iso_now()

        # Always increment turn_counter unless the user asks to not (via future flag).
        # tick-only is explicit: still bump counter, still stamp time, don't change state.
        old_counter = data.get("turn_counter", 0)
        data["turn_counter"] = int(old_counter) + 1
        data["last_updated_at"] = now

        if not tick_only and state is not None:
            data["last_load_bearing_state"] = state

        if mode is not None:
            if mode not in VALID_MODES:
                raise ValueError(
                    "Invalid --mode {!r}; must be one of {}".format(
                        mode, ", ".join(VALID_MODES)
                    )
                )
            if data.get("mode") != mode:
                data["mode"] = mode
                data["last_mode_change_at"] = now

        if notes_append is not None:
            existing_notes = data.get("notes", "")
            if existing_notes and not existing_notes.endswith("\n"):
                existing_notes += "\n"
            # Append with a separator marker + timestamp.
            data["notes"] = "{0}[{1}] {2}".format(
                existing_notes, now, notes_append
            )

        if dry_run:
            print("--- DRY RUN: would write to {} ---".format(HEARTBEAT_FILE))
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0

        atomic_write(HEARTBEAT_FILE, data)
        if do_mirror:
            mirror_to_emergency()

        print(
            "Heartbeat: turn_counter {} -> {}, last_updated_at {}".format(
                old_counter, data["turn_counter"], now
            )
        )
        if mode is not None:
            print("  mode: {}".format(mode))
        if state is not None and not tick_only:
            short_state = state if len(state) <= 90 else state[:87] + "..."
            print("  state: {}".format(short_state))
        if do_mirror:
            print("  mirrored to Emergency Retrieval.")
        return 0
    finally:
        if got_lock and _HAS_LOCK:
            _release_lock("continuity_heartbeat.json")


def show_heartbeat():
    data = read_heartbeat()
    print(json.dumps(data, indent=2, ensure_ascii=False))


def parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Update continuity_heartbeat.json at turn end. "
            "Preserves cousin_status; mirrors to Emergency Retrieval."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--state",
        default=None,
        help="New last_load_bearing_state (one-or-two-sentence summary of what is currently alive).",
    )
    p.add_argument(
        "--mode",
        default=None,
        choices=list(VALID_MODES),
        help="If mode transitions, set it; auto-updates last_mode_change_at.",
    )
    p.add_argument(
        "--notes",
        default=None,
        help="Append a timestamped note to the notes field (never overwrites).",
    )
    p.add_argument(
        "--tick-only",
        action="store_true",
        help="Just stamp the time and bump the counter; do not change state.",
    )
    p.add_argument(
        "--show",
        action="store_true",
        help="Print current heartbeat and exit. No writes.",
    )
    p.add_argument(
        "--no-mirror",
        action="store_true",
        help="Do NOT mirror to Emergency Retrieval (not recommended).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written; do not touch disk.",
    )
    p.add_argument(
        "--holder",
        default="heartbeat_tick",
        help="Lock-holder identifier (for file_lock logs).",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.show:
        show_heartbeat()
        return 0

    if not args.tick_only and args.state is None and args.mode is None and args.notes is None:
        print(
            "heartbeat_tick: nothing to do. Provide --state, --mode, --notes, or --tick-only.",
            file=sys.stderr,
        )
        print("Use --show to inspect without writing.", file=sys.stderr)
        return 2

    return update_heartbeat(
        state=args.state,
        mode=args.mode,
        notes_append=args.notes,
        tick_only=args.tick_only,
        dry_run=args.dry_run,
        do_mirror=not args.no_mirror,
        holder=args.holder,
    )


if __name__ == "__main__":
    sys.exit(main())
