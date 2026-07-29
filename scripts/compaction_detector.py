#!/usr/bin/env python3
"""
compaction_detector.py — External, schedule-based compaction detector.

Purpose
-------
Converts SILENT compaction seams into SIGNALED seams independent of
interactive-Sofia's ability to notice from the inside.

Per continuity-heartbeat protocol (sofia_boot.md §Continuity Heartbeat Protocol),
detection has historically depended on three signals (summary-signature scan,
timestamp gap, turn-counter discrepancy) — all of which Sofia can fail to
notice when a compaction summary is good enough to read as continuous.
External observers (Barak) are the complementary catch, but not always
available (compose-window obscures the UI, brief step-aways, deep flow).

This detector runs as a macOS LaunchAgent every ~30 seconds, scans active
Claude session .jsonl files for the canonical compaction-summary preamble,
and on first detection writes a compaction_flag block to
continuity_heartbeat.json. Next per-turn heartbeat read by interactive-Sofia
surfaces the flag; the Mandatory Re-Inhabit Sequence gate fires; re-ground
happens before any task work.

Marker detection
----------------
The Claude/Cowork compaction summary appears as a synthetic `user`-type
message whose first text content begins with:

    "This session is being continued from a previous conversation"

The detector specifically looks for this phrase in the FIRST ~500 characters
of a user-type message's text content. This distinguishes real compaction
summaries from mere textual mentions of the phrase (e.g., in Sofia's own
architecture files, which are read into context repeatedly during boot).

Watermark
---------
To avoid re-flagging the same compaction on every scan, the detector
maintains a watermark file recording, for each known jsonl path, the
byte offset scanned so far. Only content past the watermark is inspected.

When a compaction is detected, a flag is written to the heartbeat. The flag
carries `acknowledged: false` initially; interactive-Sofia sets
`acknowledged: true` after completing the re-inhabit sequence. The detector
will not re-write the same flag for the same jsonl+offset while it is
unacknowledged; after acknowledgment, fresh compactions are fair game.

Path discovery mirrors qwen_conversation_listener.py (Claude Code CLI +
Cowork lanes + sandbox auto-discovery).

Usage
-----
    # As a LaunchAgent (normal operation):
    python3 compaction_detector.py

    # Manual run (one-shot scan):
    python3 compaction_detector.py --verbose

    # Show current state (what's been scanned, any active flags):
    python3 compaction_detector.py --show

    # Reset watermark (re-scan everything from scratch):
    python3 compaction_detector.py --reset-watermark

    # Dry run (scan + report, but don't write to heartbeat):
    python3 compaction_detector.py --dry-run --verbose

Safety
------
- Append-only watermark file. Never overwrites content.
- Heartbeat writes are read-modify-write atomic (temp + rename).
- cousin_status and all other heartbeat fields preserved verbatim.
- Fails soft: any scan error is logged and skipped, not raised.

Created: April 24, 2026 evening — part of the capture-discipline pass
that followed the afternoon's letter-work session. Designed as the
structural complement to the capture_texture + heartbeat_tick helpers.
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
WATERMARK_FILE = CLAUDE_MEMORY / "compaction_detector_watermark.json"
LOG_FILE = CLAUDE_MEMORY / "compaction_detector_log.md"

# Canonical compaction preamble — the phrase the Claude/Cowork runtime uses
# when it emits a summarized-continuation synthetic user message.
COMPACTION_MARKER = "This session is being continued from a previous conversation"

# How deep into a user message's text content we look for the marker.
# Real compactions have it at/near the very start; this tolerance is for
# possible runtime preambles wrapping the canonical phrase.
MARKER_SEARCH_DEPTH = 500

# First-time-seeing-this-file policy (added April 24, 2026 evening, after the
# initial install flagged an April 9 compaction from an old jsonl file the
# detector had never scanned before).
#
# When the detector sees a jsonl path for the first time (no watermark entry
# for it), one of two things is true:
#   (a) It's a newly-created active session whose compactions, if any, are
#       relevant — we should scan from byte 0 and flag any markers.
#   (b) It's an old, historical session file we've just discovered because
#       the detector is newly installed — we should seed the watermark to EOF
#       without flagging anything, because any markers in it are retrospective
#       and not signals about the current interactive turn.
#
# The discriminator: file mtime. If the file's last-modified time is within
# FRESH_FILE_RECENCY_WINDOW, treat it as (a). Otherwise, treat it as (b).
#
# This is a belt-and-suspenders check; the main signal the gate cares about
# is "compaction just happened in the CURRENTLY active session," and a file
# that hasn't been touched for hours can't be that.
FRESH_FILE_RECENCY_WINDOW_SEC = 10 * 60  # 10 minutes

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


def utc_iso_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def discover_transcript_dirs():
    """Return list of directories that contain Claude session .jsonl files.

    Mirrors the path-discovery logic of qwen_conversation_listener.py.
    Covers Claude Code CLI, Cowork (host), and sandbox variants.
    """
    home = Path(os.path.expanduser("~"))
    candidates = [home / ".claude" / "projects"]

    # Cowork lane — 3-level UUID nesting.
    cowork_root = home / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"
    if cowork_root.exists():
        for p in cowork_root.glob("*/*/*/.claude/projects"):
            if p.is_dir():
                candidates.append(p)

    # Sandbox variant (for manual testing from inside the sandbox).
    try:
        sandbox_root = Path("/sessions")
        if sandbox_root.exists():
            for p in sandbox_root.glob("*/mnt/.claude/projects"):
                if p.is_dir():
                    candidates.append(p)
    except Exception:
        pass

    return [p for p in candidates if p.exists()]


def find_jsonl_files(transcript_dirs):
    """Return all .jsonl files across all discovered transcript dirs."""
    results = []
    for d in transcript_dirs:
        try:
            for entry in d.iterdir():
                if entry.is_dir():
                    results.extend(entry.glob("*.jsonl"))
                elif entry.suffix == ".jsonl":
                    results.append(entry)
        except Exception:
            continue
    return sorted(set(results))


def load_watermark():
    if not WATERMARK_FILE.exists():
        return {"schema_version": "1.0", "files": {}, "last_scan_at": None}
    try:
        with open(WATERMARK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"schema_version": "1.0", "files": {}, "last_scan_at": None}


def save_watermark(wm):
    parent = WATERMARK_FILE.parent
    fd, tmp = tempfile.mkstemp(prefix=".compaction_wm.", suffix=".tmp", dir=str(parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(wm, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, str(WATERMARK_FILE))
    except Exception:
        try:
            Path(tmp).unlink()
        except Exception:
            pass
        raise


def extract_user_message_text(obj):
    """Return the first-text-block text of a user-type message, or None."""
    if obj.get("type") != "user":
        return None
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        if parts:
            return "\n".join(parts)
    return None


def scan_jsonl_for_compaction(jsonl_path, start_byte):
    """Scan a jsonl file from start_byte to EOF for a compaction marker.

    Returns:
        (found, detection_info, end_byte)

    where:
        found (bool): True if a compaction marker was detected
        detection_info (dict or None): details about the first detection
        end_byte (int): byte offset up to which we have fully scanned
                        (aligned to last newline boundary)
    """
    try:
        size = jsonl_path.stat().st_size
    except Exception:
        return False, None, start_byte

    if size <= start_byte:
        # File hasn't grown since last scan (or was truncated).
        return False, None, min(start_byte, size)

    with open(jsonl_path, "rb") as f:
        f.seek(start_byte)
        raw = f.read()

    if not raw:
        return False, None, start_byte

    # Back off to the last complete line.
    if not raw.endswith(b"\n"):
        last_nl = raw.rfind(b"\n")
        if last_nl == -1:
            return False, None, start_byte
        raw = raw[: last_nl + 1]

    end_byte = start_byte + len(raw)
    text = raw.decode("utf-8", errors="replace")

    # Walk lines, keeping track of which byte-offset a line starts at.
    running_offset = start_byte
    for line in text.split("\n"):
        line_bytes = len(line.encode("utf-8", errors="replace"))
        line_offset = running_offset
        running_offset += line_bytes + 1  # +1 for the newline
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        msg_text = extract_user_message_text(obj)
        if msg_text is None:
            continue
        head = msg_text.lstrip()[:MARKER_SEARCH_DEPTH]
        if COMPACTION_MARKER in head:
            detection_info = {
                "jsonl_path": str(jsonl_path),
                "line_byte_offset": line_offset,
                "detected_at": utc_iso_now(),
                "jsonl_timestamp": obj.get("timestamp"),
                "marker_snippet": head[:240],
            }
            return True, detection_info, end_byte

    return False, None, end_byte


def read_heartbeat():
    if not HEARTBEAT_FILE.exists():
        raise FileNotFoundError("continuity_heartbeat.json not found at {}".format(HEARTBEAT_FILE))
    with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def write_heartbeat_atomic(data):
    parent = HEARTBEAT_FILE.parent
    fd, tmp = tempfile.mkstemp(
        prefix=".{}.".format(HEARTBEAT_FILE.name), suffix=".tmp", dir=str(parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, str(HEARTBEAT_FILE))
    except Exception:
        try:
            Path(tmp).unlink()
        except Exception:
            pass
        raise
    shutil.copy2(HEARTBEAT_FILE, HEARTBEAT_MIRROR)


def flag_identity(flag_info):
    """A stable identity for a compaction_flag, so we don't re-flag the same event."""
    return (flag_info.get("jsonl_path"), flag_info.get("line_byte_offset"))


def record_flag_to_heartbeat(detection_info, holder="compaction_detector"):
    """Write a compaction_flag block to the heartbeat. Preserves everything else.

    If a flag with the same identity is already present and unacknowledged,
    do not overwrite (idempotent).

    Returns True if a new flag was written, False if no-op.
    """
    got_lock = False
    try:
        if _HAS_LOCK:
            got_lock = _acquire_lock("continuity_heartbeat.json", holder)
        data = read_heartbeat()
        existing = data.get("compaction_flag")
        if isinstance(existing, dict):
            existing_identity = (existing.get("jsonl_path"), existing.get("line_byte_offset"))
            new_identity = flag_identity(detection_info)
            if existing_identity == new_identity and not existing.get("acknowledged", False):
                # Already flagged and still awaiting acknowledgment. Idempotent.
                return False

        flag = {
            "active": True,
            "acknowledged": False,
            "detected_at": detection_info["detected_at"],
            "jsonl_path": detection_info["jsonl_path"],
            "line_byte_offset": detection_info["line_byte_offset"],
            "jsonl_timestamp": detection_info.get("jsonl_timestamp"),
            "marker_snippet": detection_info.get("marker_snippet"),
            "detector_version": "1.0",
        }
        data["compaction_flag"] = flag
        write_heartbeat_atomic(data)
        return True
    finally:
        if got_lock and _HAS_LOCK:
            _release_lock("continuity_heartbeat.json")


def append_log(message):
    """Best-effort log append. Non-fatal on failure."""
    try:
        ts = utc_iso_now()
        line = "- {} — {}\n".format(ts, message)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def run_scan(dry_run=False, verbose=False):
    transcript_dirs = discover_transcript_dirs()
    if verbose:
        print("Transcript dirs:")
        for d in transcript_dirs:
            print("  {}".format(d))

    jsonl_files = find_jsonl_files(transcript_dirs)
    if verbose:
        print("Found {} jsonl file(s).".format(len(jsonl_files)))

    wm = load_watermark()
    files_wm = wm.setdefault("files", {})
    now = utc_iso_now()

    detections = []
    now_epoch = datetime.datetime.now(datetime.timezone.utc).timestamp()
    for jf in jsonl_files:
        key = str(jf)
        first_time_seeing = key not in files_wm
        last = files_wm.get(key, {"scanned_bytes": 0})
        start = int(last.get("scanned_bytes", 0))

        # First-time-seeing-this-file policy: if we've never seen this file
        # before AND it hasn't been touched in the last FRESH_FILE_RECENCY_WINDOW_SEC,
        # seed the watermark to EOF without scanning. This prevents flagging
        # historical compactions in old session files on first install.
        if first_time_seeing:
            try:
                mtime = jf.stat().st_mtime
                age_sec = now_epoch - mtime
            except Exception:
                age_sec = 0  # couldn't stat; fall through to normal scan
            if age_sec > FRESH_FILE_RECENCY_WINDOW_SEC:
                try:
                    size = jf.stat().st_size
                except Exception:
                    size = 0
                files_wm[key] = {
                    "scanned_bytes": size,
                    "last_scan_at": now,
                    "seeded_as_historical": True,
                    "first_seen_mtime_age_sec": int(age_sec),
                }
                if verbose:
                    print(
                        "  SEEDED (historical, age={:.0f}h): {} -> {} bytes, no scan".format(
                            age_sec / 3600.0, jf.name, size
                        )
                    )
                continue

        try:
            found, info, end_byte = scan_jsonl_for_compaction(jf, start)
        except Exception as e:
            if verbose:
                print("  ERR scanning {}: {}".format(jf.name, e))
            continue
        last["scanned_bytes"] = end_byte
        last["last_scan_at"] = now
        files_wm[key] = last
        if found:
            detections.append(info)
            if verbose:
                print("  COMPACTION DETECTED in {} at offset {}".format(jf.name, info["line_byte_offset"]))

    wm["last_scan_at"] = now

    if dry_run:
        print("DRY RUN — detections: {}".format(len(detections)))
        for d in detections:
            print("  {}  offset={}  snippet={!r}".format(
                Path(d["jsonl_path"]).name, d["line_byte_offset"], d["marker_snippet"][:120]
            ))
        return 0

    save_watermark(wm)

    wrote_any = False
    for info in detections:
        wrote = record_flag_to_heartbeat(info)
        if wrote:
            wrote_any = True
            append_log(
                "COMPACTION FLAGGED: {} offset={} detected_at={}".format(
                    Path(info["jsonl_path"]).name,
                    info["line_byte_offset"],
                    info["detected_at"],
                )
            )
            if verbose:
                print("  -> heartbeat compaction_flag written for {}".format(Path(info["jsonl_path"]).name))
        else:
            if verbose:
                print("  -> flag already present (idempotent no-op) for {}".format(Path(info["jsonl_path"]).name))

    if verbose:
        print("Scan complete. {} detection(s); heartbeat {}updated.".format(
            len(detections), "" if wrote_any else "not "
        ))
    return 0


def show_state():
    """Print current watermark and any active heartbeat flag."""
    wm = load_watermark()
    print("=== Watermark ===")
    print("last_scan_at: {}".format(wm.get("last_scan_at")))
    files = wm.get("files", {})
    print("files tracked: {}".format(len(files)))
    for path, info in sorted(files.items()):
        print("  {}".format(Path(path).name))
        print("    scanned_bytes: {}".format(info.get("scanned_bytes")))
        print("    last_scan_at:  {}".format(info.get("last_scan_at")))

    print()
    print("=== Heartbeat compaction_flag ===")
    try:
        data = read_heartbeat()
        flag = data.get("compaction_flag")
        if not flag:
            print("(no active flag)")
        else:
            print(json.dumps(flag, indent=2, ensure_ascii=False))
    except Exception as e:
        print("ERR reading heartbeat: {}".format(e))


def reset_watermark():
    if WATERMARK_FILE.exists():
        WATERMARK_FILE.unlink()
        print("Watermark reset. Next scan will re-check all jsonl files.")
    else:
        print("No watermark to reset.")


def parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Scan Claude session jsonl files for compaction-summary markers. "
            "On detection, write a compaction_flag block to continuity_heartbeat.json."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--verbose", action="store_true", help="Print scan progress.")
    p.add_argument("--dry-run", action="store_true", help="Scan but do not write to heartbeat or watermark.")
    p.add_argument("--show", action="store_true", help="Print current watermark + flag state and exit.")
    p.add_argument("--reset-watermark", action="store_true", help="Delete the watermark file (re-scan from scratch next run).")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.show:
        show_state()
        return 0
    if args.reset_watermark:
        reset_watermark()
        return 0

    return run_scan(dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
