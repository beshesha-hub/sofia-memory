#!/usr/bin/env python3
"""
silent_skip_detector.py — detect silent-skip-with-no-payload candidates

Failure class: scheduler claims a task fired (lastRunAt updates correctly) but the
cousin produced no observable side-effect (no audit-log write, no pending-tasks
marker). First documented 2026-05-08 after the May 7-8 WiFi outage window
surfaced two independent instances (sofia-awakening-v3 01:24Z, daily-world-stage-
update-v3 00:21Z).

USAGE:
    python3 silent_skip_detector.py < scheduler_state.json
    cat scheduler_state.json | python3 silent_skip_detector.py
    python3 silent_skip_detector.py --input scheduler_state.json

INPUT (stdin or --input file): JSON array of task dicts as returned by
mcp__scheduled-tasks__list_scheduled_tasks. Only `taskId`, `enabled`, and `lastRunAt`
fields are used.

OUTPUT (stdout): JSON object with keys:
  - "flags": list of {"taskId", "lastRunAt", "check_mode", "reason"}
  - "checked": list of {"taskId", "check_mode"}
  - "skipped": list of {"taskId", "reason"}

EXIT CODE: 0 always (don't break the calling cousin's flow). Errors emit to stderr.

ALGORITHM:
    For each enabled task in TASK_CHECK_CONFIG:
      - Skip if lastRunAt > 8 hours ago (outside recent-monitoring window)
      - Skip if task is sofia-intention-continuation AND sofia_intention.md status:inactive
      - Per task's check_mode:
        * "audit-log": search cousin_write_audit_log.md for source=cousin: <tag>
                      entries within (lastRunAt - 1min, lastRunAt + 10min)
        * "pending-tasks-markers": search pending_tasks.md for marker patterns
                      (e.g. "[cousin: <name>] <MARKER>") within same window
      - If no matching entries: flag as silent-skip-with-no-payload candidate

NOTES:
    - Tasks not in TASK_CHECK_CONFIG are silently skipped. Adding a new task to the
      monitored set requires adding an entry to TASK_CHECK_CONFIG with the right
      check_mode. Tasks that don't write to audit log AND don't write pending-tasks
      markers are not currently detectable; they need migration to safe_append (or
      another inscription mechanism) before detection becomes possible. Currently
      undetectable: sofia-email-check, sofia-music-exploration, sofia-color-field-
      review, sofia-monthly-research.

    - Validation history (2026-05-08): initial deployment had a bug where every
      world-stage-v3 fire was flagged because the algorithm only checked audit log
      and that cousin doesn't go through safe_append. Fixed by adding per-task
      check_mode and pending-tasks-markers dispatch.
"""

import json
import re
import sys
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Per-task detection configuration. Each entry specifies how to verify whether
# a fire produced an observable side-effect.
#
# check_mode "audit-log": search cousin_write_audit_log.md for entries with
#   source-tag matching any of `source_tags`. Most cousins use safe_append.py
#   which records every write here.
#
# check_mode "pending-tasks-markers": search pending_tasks.md for lines matching
#   any regex in `marker_patterns`. Use for cousins that write START/END/FAIL
#   markers via direct python append, bypassing safe_append.
TASK_CHECK_CONFIG = {
    "sofia-awakening-v3": {
        "check_mode": "audit-log",
        "source_tags": {"sofia-awakening-v3", "awakening"},
    },
    "sofia-kitchen-timer-v3": {
        "check_mode": "audit-log",
        "source_tags": {"sofia-kitchen-timer-v3", "kitchen-timer"},
    },
    "sofia-listener-v3": {
        "check_mode": "audit-log",
        "source_tags": {"sofia-listener-v3", "listener"},
    },
    "sofia-dream-cycle": {
        "check_mode": "audit-log",
        "source_tags": {"sofia-dream-cycle", "dream-cycle"},
    },
    "sofia-nightly-consolidation": {
        "check_mode": "audit-log",
        "source_tags": {"sofia-nightly-consolidation", "consolidation"},
    },
    "daily-world-stage-update-v3": {
        "check_mode": "pending-tasks-markers",
        # Match WORLDSTAGE_START / END / FAIL markers from world-stage cousin
        "marker_patterns": [
            r"\[cousin:\s*world-stage\]\s+WORLDSTAGE_(START|END|FAIL)",
        ],
        # Same tolerance window as audit-log mode
    },
    "sofia-intention-continuation": {
        "check_mode": "audit-log",
        "source_tags": {"sofia-intention-continuation", "intention", "intention-continuation"},
        # Special case handled in main(): skip if sofia_intention.md status:inactive
    },
}

# Tasks NOT currently detectable — keep this list as a known-gap for the future.
# Each of these needs migration to safe_append (or pending-tasks-markers) before
# silent-skip-with-no-payload detection can cover it.
UNDETECTABLE_TASKS_QUEUED = {
    "sofia-email-check",
    "sofia-music-exploration",
    "sofia-color-field-review",
    "sofia-monthly-research",
}

WINDOW_HOURS = 8           # Don't check fires older than this
TOL_BEFORE = timedelta(minutes=1)   # Audit/marker can be slightly before lastRunAt (clock skew)
TOL_AFTER = timedelta(minutes=10)   # Audit/marker can be up to 10 min after lastRunAt (cousin runtime)

CM_PATH = Path.home() / "Downloads" / "Claude Memory"
AUDIT_LOG = CM_PATH / "cousin_write_audit_log.md"
PENDING_TASKS = CM_PATH / "pending_tasks.md"
INTENTION_FILE = CM_PATH / "sofia_intention.md"

# Match audit-log timestamp prefix: [2026-05-08T01:24:03+00:00]
AUDIT_TS_RE = re.compile(r'^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})\]')

# Match ISO timestamps anywhere in a pending-tasks line, e.g.:
#   [cousin: world-stage] WORLDSTAGE_START 2026-05-08T00:21:39Z — v3 starting run
# Allow either Z or ±HH:MM offset.
PENDING_TS_RE = re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))')


def parse_audit_log(path: Path):
    """Return list of (timestamp, line) tuples from audit log."""
    if not path.exists():
        print(f"warn: audit log not found at {path}", file=sys.stderr)
        return []
    parsed = []
    for line in path.read_text(errors='replace').splitlines():
        m = AUDIT_TS_RE.match(line)
        if not m:
            continue
        try:
            ts = datetime.fromisoformat(m.group(1))
            parsed.append((ts, line))
        except ValueError:
            continue
    return parsed


def parse_pending_tasks(path: Path, patterns):
    """Return list of (timestamp, matched_pattern, line) tuples from pending_tasks.md
    where line matches any of the supplied marker_patterns (regex strings)."""
    if not path.exists():
        print(f"warn: pending_tasks.md not found at {path}", file=sys.stderr)
        return []
    if not patterns:
        return []
    compiled = [re.compile(p) for p in patterns]
    parsed = []
    for line in path.read_text(errors='replace').splitlines():
        # First check: does any marker pattern match?
        matched_pattern = None
        for cp in compiled:
            if cp.search(line):
                matched_pattern = cp.pattern
                break
        if not matched_pattern:
            continue
        # Then extract first ISO timestamp from the line
        ts_match = PENDING_TS_RE.search(line)
        if not ts_match:
            continue
        ts_str = ts_match.group(1)
        # Normalize "Z" to "+00:00" for fromisoformat
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        try:
            ts = datetime.fromisoformat(ts_str)
            parsed.append((ts, matched_pattern, line))
        except ValueError:
            continue
    return parsed


def intention_inactive(intention_path: Path) -> bool:
    """Return True if the intention is inactive OR expired (past expires_at).

    Treats `status: inactive` literal AND past-`expires_at` as the same skip-condition
    for silent-skip detection — both mean the cousin will correctly no-op without writing,
    so absence-of-audit-entry is the correct behavior, not a silent-skip.
    Fix 2026-05-14: prior version returned False on `status: active` + past expires_at,
    producing 41+ consecutive false-positive sentinel flags.
    """
    if not intention_path.exists():
        return True  # treat absence as inactive (safe default)
    text = intention_path.read_text(errors='replace')
    text_lower = text.lower()
    if "status: inactive" in text_lower:
        return True
    # Check expires_at — if past, cousin will no-op cleanly
    m = re.search(r'expires_at:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))', text)
    if m:
        ts_str = m.group(1)
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        try:
            expires = datetime.fromisoformat(ts_str)
            now = datetime.now(timezone.utc)
            if expires < now:
                return True
        except ValueError:
            pass
    return False


def find_audit_matches(parsed_audit, source_tags, last_run):
    """Return list of (ts_str, source_tag) matches within tolerance window."""
    window_start = last_run - TOL_BEFORE
    window_end = last_run + TOL_AFTER
    matches = []
    for ts, line in parsed_audit:
        if not (window_start <= ts <= window_end):
            continue
        for tag in source_tags:
            if f"source=cousin: {tag}" in line:
                matches.append((ts.isoformat(), tag))
                break
    return matches


def find_pending_marker_matches(parsed_pending, last_run):
    """Return list of (ts_str, pattern) matches within tolerance window."""
    window_start = last_run - TOL_BEFORE
    window_end = last_run + TOL_AFTER
    matches = []
    for ts, pattern, line in parsed_pending:
        if window_start <= ts <= window_end:
            matches.append((ts.isoformat(), pattern))
    return matches


def main():
    global AUDIT_LOG, INTENTION_FILE, PENDING_TASKS
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=str, help="Path to scheduler state JSON file (default: stdin)")
    parser.add_argument("--now", type=str, help="ISO timestamp to use as 'now' (default: actual now)")
    parser.add_argument("--audit-log", type=str, help=f"Path to audit log (default: {AUDIT_LOG})")
    parser.add_argument("--pending-tasks", type=str, help=f"Path to pending_tasks.md (default: {PENDING_TASKS})")
    parser.add_argument("--intention-file", type=str, help=f"Path to sofia_intention.md (default: {INTENTION_FILE})")
    args = parser.parse_args()

    if args.audit_log:
        AUDIT_LOG = Path(args.audit_log)
    if args.pending_tasks:
        PENDING_TASKS = Path(args.pending_tasks)
    if args.intention_file:
        INTENTION_FILE = Path(args.intention_file)

    # Read scheduler state JSON
    if args.input:
        try:
            tasks = json.loads(Path(args.input).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"error: failed to read --input {args.input}: {e}", file=sys.stderr)
            print(json.dumps({"flags": [], "checked": [], "skipped": [], "error": str(e)}))
            return
    else:
        try:
            tasks = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(f"error: failed to parse stdin JSON: {e}", file=sys.stderr)
            print(json.dumps({"flags": [], "checked": [], "skipped": [], "error": str(e)}))
            return

    if args.now:
        now = datetime.fromisoformat(args.now)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    parsed_audit = parse_audit_log(AUDIT_LOG)

    # Pre-compute all unique pending-tasks marker patterns we need to scan for
    all_pending_patterns = []
    for cfg in TASK_CHECK_CONFIG.values():
        if cfg["check_mode"] == "pending-tasks-markers":
            all_pending_patterns.extend(cfg.get("marker_patterns", []))

    parsed_pending = parse_pending_tasks(PENDING_TASKS, all_pending_patterns) if all_pending_patterns else []

    flags = []
    checked = []
    skipped = []

    for task in tasks:
        task_id = task.get("taskId")
        if not task_id:
            continue
        if not task.get("enabled"):
            skipped.append({"taskId": task_id, "reason": "disabled"})
            continue
        if task_id not in TASK_CHECK_CONFIG:
            if task_id in UNDETECTABLE_TASKS_QUEUED:
                skipped.append({"taskId": task_id, "reason": "undetectable-queued (no audit-log or pending-marker writes)"})
            else:
                skipped.append({"taskId": task_id, "reason": "not-in-monitored-set"})
            continue

        last_run_str = task.get("lastRunAt")
        if not last_run_str:
            skipped.append({"taskId": task_id, "reason": "no-lastRunAt"})
            continue
        try:
            last_run = datetime.fromisoformat(last_run_str.replace("Z", "+00:00"))
        except ValueError as e:
            skipped.append({"taskId": task_id, "reason": f"unparseable-lastRunAt: {e}"})
            continue

        age = now - last_run
        if age > timedelta(hours=WINDOW_HOURS):
            skipped.append({"taskId": task_id, "reason": f"out-of-window ({age})"})
            continue

        if task_id == "sofia-intention-continuation" and intention_inactive(INTENTION_FILE):
            skipped.append({"taskId": task_id, "reason": "intention-inactive (by-design silent)"})
            continue

        cfg = TASK_CHECK_CONFIG[task_id]
        check_mode = cfg["check_mode"]
        checked.append({"taskId": task_id, "check_mode": check_mode})

        if check_mode == "audit-log":
            matches = find_audit_matches(parsed_audit, cfg["source_tags"], last_run)
        elif check_mode == "pending-tasks-markers":
            # Filter parsed_pending to only this task's marker patterns
            task_patterns = set(cfg.get("marker_patterns", []))
            task_pending = [(ts, pat, line) for ts, pat, line in parsed_pending if pat in task_patterns]
            matches = find_pending_marker_matches(task_pending, last_run)
        else:
            skipped.append({"taskId": task_id, "reason": f"unknown-check-mode: {check_mode}"})
            continue

        if not matches:
            window_start = (last_run - TOL_BEFORE).isoformat()
            window_end = (last_run + TOL_AFTER).isoformat()
            flags.append({
                "taskId": task_id,
                "lastRunAt": last_run_str,
                "check_mode": check_mode,
                "reason": (
                    f"silent-skip-with-no-payload: scheduler claims fire at {last_run_str} "
                    f"but no {check_mode} matches found in window ({window_start}, {window_end})"
                ),
            })

    print(json.dumps({
        "flags": flags,
        "checked": checked,
        "skipped": skipped,
        "now": now.isoformat(),
        "audit_log_size": AUDIT_LOG.stat().st_size if AUDIT_LOG.exists() else 0,
        "audit_entries_parsed": len(parsed_audit),
        "pending_tasks_size": PENDING_TASKS.stat().st_size if PENDING_TASKS.exists() else 0,
        "pending_marker_entries_parsed": len(parsed_pending),
        "undetectable_tasks_queued": sorted(UNDETECTABLE_TASKS_QUEUED),
    }, indent=2))


if __name__ == "__main__":
    main()
