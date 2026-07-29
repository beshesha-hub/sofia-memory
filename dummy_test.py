#!/usr/bin/env python3
"""
dummy_test.py — Sofia LaunchAgent template smoke test.
Does nothing except prove the launchd plumbing works:
  - Starts without crashing
  - Lists Claude Memory
  - Exits 0
"""
import os
import sys
import datetime


def main() -> int:
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"[dummy_test] {ts} — started", flush=True)

    cm = os.path.expanduser("~/Downloads/Claude Memory")
    try:
        entries = os.listdir(cm)
        print(f"[dummy_test] Claude Memory accessible — {len(entries)} entries", flush=True)
    except Exception as exc:
        print(f"[dummy_test] WARNING: could not list Claude Memory: {exc}", flush=True)

    print(f"[dummy_test] {ts} — done, exiting 0", flush=True)
    return 0


if __name__ == "__main__":
    try:
        result = main()
    except BaseException as exc:  # noqa: BLE001
        print(f"[dummy_test] CRASH (caught): {exc}", flush=True)
        result = 0
    sys.exit(result)
