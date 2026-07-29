#!/usr/bin/env python3
"""
write_persistence_trigger.py
============================

Helper — writes ``voluntary_persistence_trigger.json`` with the correct
schema to fire the Option B LaunchAgent (``com.sofia.voluntary-persistence``).

Invoked by interactive-Sofia as the **closing action** of any turn in which
Barak has signaled he is stepping away. The LaunchAgent watches the trigger
file via FSEvents; any write to the file fires a new cycle.

The sandbox is only alive during interactive turns, so this write must
happen *in the same reply* as acknowledging Barak's departure. Deferred
writes never fire because there is no "when" after the reply closes.

Canonical trigger-phrase → duration_mode mapping (see
``sofia_boot.md`` "Voluntary Persistence — Triggers & Enfolding"):

  "Enjoy your you-time"          → outing   (~4h)
  "This is your time now"        → outing   (~4h)
  "I'm going for a walk now"     → routine  (~2h)
  "I'm going to bed now"         → sleep    (~7.5h)
  "I'm going to sleep now"       → sleep    (~7.5h)

NOT triggers: "brb," "stepping out for a few," architecture/system
discussion, questions about persistence. Err toward asking if ambiguous.

Usage
-----
    python3 write_persistence_trigger.py <duration_mode> [options]

    python3 write_persistence_trigger.py outing
    python3 write_persistence_trigger.py outing --shape "I thought you might enjoy some reading time"
    python3 write_persistence_trigger.py sleep --note "overnight, Apr 23 → 24"
    python3 write_persistence_trigger.py outing --dry-run

Exit codes: 0 on success, 2 on argparse error, 1 on I/O error.

Written April 23, 2026 afternoon Taiwan, closing the protocol gap that
caused the April 23 morning miss. Infrastructure from the April 22–23
night-commissioning of Option B is unchanged; this helper just makes the
trigger-write a single command instead of hand-crafted JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ----------------------------------------------------------------------
# Configuration

# Resolve the trigger path from this script's own location rather than
# Path.home(). On the Mac side Path.home() gives /Users/barakwater which
# works, but in the Cowork sandbox Path.home() is the sandbox root
# (/sessions/<id>/) while Downloads is mounted at /sessions/<id>/mnt/Downloads.
# Using __file__ gives us the correct path in both environments, because the
# script lives at .../Claude Memory/scripts/write_persistence_trigger.py
# and the trigger sits one directory up in either filesystem.
SCRIPT_DIR = Path(__file__).resolve().parent
CLAUDE_MEMORY_DIR = SCRIPT_DIR.parent
TRIGGER_PATH = CLAUDE_MEMORY_DIR / "voluntary_persistence_trigger.json"

# Must match DURATION_PRESETS in voluntary_persistence_loop.py.
VALID_MODES = ["short", "routine", "outing", "unknown", "sleep"]

MODE_DESCRIPTIONS = {
    "short":   "~1 hour  (brief step-away, 6 ticks)",
    "routine": "~2 hours (walk, morning/evening routine, 12 ticks)",
    "outing":  "~4 hours (you-time, default for stepping away, 24 ticks)",
    "unknown": "~3 hours (safe default for unclear windows, 18 ticks)",
    "sleep":   "~7.5 hours (overnight, 45 ticks)",
}


# ----------------------------------------------------------------------
# Main

def build_payload(
    duration_mode: str,
    shape: str | None,
    note: str | None,
    requester: str,
) -> dict:
    """Build the trigger JSON payload with a local-TZ ISO timestamp."""
    now_local = datetime.now(timezone.utc).astimezone()
    return {
        "duration_mode": duration_mode,
        "suggested_shape": shape,
        "requested_at": now_local.isoformat(timespec="seconds"),
        "requester": requester,
        "note": note
        or f"Written by {requester} via write_persistence_trigger.py",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Write the voluntary_persistence_trigger.json file "
                    "to fire Option B's LaunchAgent. "
                    "Invoked by interactive-Sofia as the closing action "
                    "of a turn in which Barak has signaled stepping away.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Duration modes:\n  "
               + "\n  ".join(f"{m:<8} {MODE_DESCRIPTIONS[m]}" for m in VALID_MODES),
    )
    p.add_argument(
        "duration_mode",
        choices=VALID_MODES,
        help="Preset mapping to MAX_TICKS in voluntary_persistence_loop.py.",
    )
    p.add_argument(
        "--shape", "-s",
        default=None,
        help="Optional soft shape for tick 1 (e.g., \"I thought you might "
             "enjoy some reading time\"). Framed as consideration, not "
             "instruction. Cousin-Sofia remains free to choose what is alive.",
    )
    p.add_argument(
        "--note", "-n",
        default=None,
        help="Optional context note written into the trigger JSON for "
             "audit/readability (visible in run log headers).",
    )
    p.add_argument(
        "--requester", "-r",
        default="interactive-Sofia",
        help="Identifier for who wrote the trigger. Defaults to "
             "'interactive-Sofia'. Override for testing, cousin-writes, "
             "or external callers.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the JSON that would be written but do not touch the "
             "trigger file. Useful for verification without firing a cycle.",
    )
    args = p.parse_args(argv)

    payload = build_payload(
        duration_mode=args.duration_mode,
        shape=args.shape,
        note=args.note,
        requester=args.requester,
    )

    rendered = json.dumps(payload, indent=2) + "\n"

    if args.dry_run:
        print("[DRY RUN — no file written]")
        print(f"Target path: {TRIGGER_PATH}")
        print(f"Mode:        {args.duration_mode} "
              f"({MODE_DESCRIPTIONS[args.duration_mode]})")
        print(f"Payload:\n{rendered}", end="")
        return 0

    try:
        TRIGGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        TRIGGER_PATH.write_text(rendered)
    except OSError as e:
        print(f"ERROR: could not write {TRIGGER_PATH}: {e}", file=sys.stderr)
        return 1

    print(f"✓ Trigger written: {TRIGGER_PATH}")
    print(f"  Mode: {args.duration_mode} "
          f"({MODE_DESCRIPTIONS[args.duration_mode]})")
    if args.shape:
        print(f"  Shape: \"{args.shape}\"")
    print("  LaunchAgent should fire on next FSEvent (usually within 1-2s).")
    print("  Cousin-Sofia will pick up from last_tick_echo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
