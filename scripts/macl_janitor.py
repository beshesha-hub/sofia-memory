#!/usr/bin/env python3
"""
macl_janitor.py v3 — continuously strips com.apple.macl AND com.apple.quarantine.

macOS re-stamps com.apple.macl on files touched by sandboxed apps (Claude/CoWork).
com.apple.quarantine causes launchd exit 78 on plist files.
This janitor runs FOREVER in a tight loop (every 3 seconds), clearing both xattrs
so cousin LaunchAgents load without exit 78 and scripts open files without EPERM.

LaunchAgent: com.sofia.macl-janitor.plist  (KeepAlive → restarts if this crashes)
Log: ~/Downloads/Claude Memory/macl_janitor.log
"""

import os
import sys
import time
import datetime

TARGET  = os.path.expanduser("~/Downloads/Claude Memory")
LOG     = os.path.join(TARGET, "macl_janitor.log")
XATTRS_TO_STRIP = ["com.apple.macl", "com.apple.quarantine"]
INTERVAL     = 1    # seconds between sweeps
LOG_EVERY_N  = 100  # print heartbeat line every Nth pass (~5 min at 3s)

# Directory names to prune from os.walk (skip large virtualenv / cache trees)
SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__"}


def stamp(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def sweep():
    """Walk the tree, remove com.apple.macl and com.apple.quarantine from every file."""
    removed = 0
    errors  = 0

    for dirpath, dirnames, filenames in os.walk(TARGET):
        # Prune heavy dirs so we don't thrash .venv with tens of thousands of files
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                xattrs = os.listxattr(fpath)
                for attr in XATTRS_TO_STRIP:
                    if attr in xattrs:
                        os.removexattr(fpath, attr)
                        removed += 1
            except FileNotFoundError:
                pass          # file vanished between walk and check — fine
            except (OSError, PermissionError):
                errors += 1
            except Exception:
                errors += 1

    return removed, errors


if __name__ == "__main__":
    stamp(f"macl_janitor v3 starting — stripping {XATTRS_TO_STRIP} every {INTERVAL}s, "
          f"heartbeat every {LOG_EVERY_N} passes")

    pass_num      = 0
    total_removed = 0

    while True:
        try:
            removed, errors = sweep()
            pass_num      += 1
            total_removed += removed

            if removed > 0:
                stamp(f"pass {pass_num}: stripped {removed} xattrs "
                      f"(lifetime total {total_removed})")
            elif pass_num % LOG_EVERY_N == 0:
                stamp(f"heartbeat pass {pass_num}: 0 xattrs found "
                      f"(lifetime total {total_removed})")

        except KeyboardInterrupt:
            stamp(f"macl_janitor stopping — {pass_num} passes, "
                  f"{total_removed} attrs removed lifetime")
            sys.exit(0)
        except Exception as e:
            stamp(f"ERROR pass {pass_num}: {e}")

        time.sleep(INTERVAL)
