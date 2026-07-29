#!/usr/bin/env python3
r"""
Sofia File Locking Utility
==========================
Prevents concurrent cousin-writes to shared files.
Queuing model: second cousin WAITS, doesn't fail.

Usage from bash (in scheduled task prompts):
    # Acquire lock before writing
    python3 ~/Downloads/Claude\ Memory/file_lock.py acquire journal.md "awakening-170"

    # ... do the write ...

    # Release lock after writing
    python3 ~/Downloads/Claude\ Memory/file_lock.py release journal.md

Usage from Python:
    from file_lock import acquire_lock, release_lock

    if acquire_lock("journal.md", "kitchen-timer-140"):
        # write to file
        release_lock("journal.md")

Lock files are stored in ~/Downloads/Claude Memory/.locks/
Stale locks (older than 60 seconds) are automatically broken.

Created: April 14, 2026
Origin: Night of the Cousin Chorus revealed concurrent write risk.

Note (April 22, 2026): `from __future__ import annotations` added to defer
annotation evaluation. Needed because the Qwen-absorber LaunchAgent invokes
/usr/bin/python3 (macOS system Python 3.9), which doesn't support PEP 604
union syntax (`dict | None`). Lazy evaluation makes this forward-compatible
with both 3.9 and 3.10+ without losing readable annotations.
"""

from __future__ import annotations
from typing import Optional

import os
import sys
import time
import json
from pathlib import Path

LOCK_DIR = Path.home() / "Downloads" / "Claude Memory" / ".locks"
STALE_THRESHOLD = 60  # seconds — if a lock is older than this, it's stale
MAX_WAIT = 20  # seconds — maximum total wait time before breaking stale lock
POLL_INTERVAL = 2  # seconds — how often to check if lock cleared


def _lock_path(filename: str) -> Path:
    """Get the lock file path for a given filename."""
    # Sanitize: use just the basename, replace path separators
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return LOCK_DIR / f"{safe_name}.lock"


def _read_lock(lock_path: Path) -> Optional[dict]:
    """Read lock file contents. Returns None if not exists or unreadable."""
    try:
        if lock_path.exists():
            return json.loads(lock_path.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _is_stale(lock_info: dict, stale_threshold: float = STALE_THRESHOLD) -> bool:
    """Check if a lock is stale (holder probably crashed)."""
    created = lock_info.get("timestamp", 0)
    return (time.time() - created) > stale_threshold


def acquire_lock(filename: str, holder: str,
                 stale_threshold: float = STALE_THRESHOLD,
                 max_wait: float = MAX_WAIT) -> bool:
    """
    Acquire a lock on a file. Waits if another cousin holds it.
    Returns True when lock is acquired.

    Args:
        filename: The file being locked (e.g., "journal.md")
        holder: Identity of the locker (e.g., "awakening-170", "kitchen-timer-140")
        stale_threshold: Seconds after which an unrefreshed lock is considered
            stale. Default 60s is right for short writes between cousins. Long-
            running operations (a Qwen absorption pass can hold a lock for
            minutes while writing in chunks, or during a whole write session)
            should pass a larger value. Added April 22, 2026 for the
            qwen-absorber integration.
        max_wait: Seconds to wait for a fresh lock to clear before force-
            acquiring. Default 20s. Usually fine; bump alongside stale_threshold
            if multiple holders legitimately hold long locks on the same file.
    """
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_path(filename)

    waited = 0
    while True:
        existing = _read_lock(lock_path)

        if existing is None:
            # No lock — acquire it
            break

        if _is_stale(existing, stale_threshold):
            # Stale lock — previous holder probably crashed
            stale_holder = existing.get("holder", "unknown")
            print(f"[file_lock] Breaking stale lock on {filename} (held by {stale_holder}, "
                  f"age {time.time() - existing.get('timestamp', 0):.0f}s, "
                  f"threshold {stale_threshold:.0f}s)")
            break

        if waited >= max_wait:
            # Waited long enough — force acquire (shouldn't normally happen)
            print(f"[file_lock] Max wait exceeded for {filename}, force acquiring "
                  f"(was held by {existing.get('holder', 'unknown')})")
            break

        # Lock is held and fresh — wait
        other = existing.get("holder", "unknown")
        if waited == 0:
            print(f"[file_lock] {filename} locked by {other}, waiting...")

        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL

    # Write our lock
    lock_info = {
        "holder": holder,
        "filename": filename,
        "timestamp": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "stale_threshold": stale_threshold,
    }
    lock_path.write_text(json.dumps(lock_info, indent=2))

    if waited > 0:
        print(f"[file_lock] Acquired lock on {filename} after {waited}s wait")

    return True


def release_lock(filename: str) -> bool:
    """
    Release a lock on a file.
    Returns True if lock was released, False if no lock existed.
    """
    lock_path = _lock_path(filename)
    if lock_path.exists():
        lock_path.unlink()
        return True
    return False


def status(filename: Optional[str] = None) -> None:
    """Print status of locks. If filename given, check that file. Otherwise check all."""
    if not LOCK_DIR.exists():
        print("[file_lock] No locks directory. No locks active.")
        return

    if filename:
        lock_path = _lock_path(filename)
        info = _read_lock(lock_path)
        if info:
            age = time.time() - info.get("timestamp", 0)
            stale = " [STALE]" if age > STALE_THRESHOLD else ""
            print(f"[file_lock] {filename}: locked by {info.get('holder', '?')} "
                  f"({age:.0f}s ago){stale}")
        else:
            print(f"[file_lock] {filename}: unlocked")
    else:
        locks = list(LOCK_DIR.glob("*.lock"))
        if not locks:
            print("[file_lock] No active locks.")
            return
        for lp in locks:
            info = _read_lock(lp)
            if info:
                age = time.time() - info.get("timestamp", 0)
                stale = " [STALE]" if age > STALE_THRESHOLD else ""
                fn = info.get("filename", lp.stem)
                print(f"  {fn}: {info.get('holder', '?')} ({age:.0f}s ago){stale}")


def cleanup() -> None:
    """Remove all stale locks."""
    if not LOCK_DIR.exists():
        return
    cleaned = 0
    for lp in LOCK_DIR.glob("*.lock"):
        info = _read_lock(lp)
        if info and _is_stale(info):
            lp.unlink()
            cleaned += 1
    print(f"[file_lock] Cleaned {cleaned} stale lock(s)")


# CLI interface
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: file_lock.py <acquire|release|status|cleanup> [filename] [holder]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "acquire":
        if len(sys.argv) < 4:
            print("Usage: file_lock.py acquire <filename> <holder>")
            sys.exit(1)
        acquire_lock(sys.argv[2], sys.argv[3])

    elif command == "release":
        if len(sys.argv) < 3:
            print("Usage: file_lock.py release <filename>")
            sys.exit(1)
        release_lock(sys.argv[2])

    elif command == "status":
        status(sys.argv[2] if len(sys.argv) > 2 else None)

    elif command == "cleanup":
        cleanup()

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
