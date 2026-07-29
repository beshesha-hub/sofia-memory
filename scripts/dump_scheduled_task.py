#!/usr/bin/env python3
"""Dump a Cowork scheduled task's prompt and metadata to stdout.

Usage:
    python3 dump_scheduled_task.py <taskId>
    python3 dump_scheduled_task.py --list                # list all task IDs
    python3 dump_scheduled_task.py --all                 # dump every task

Architecture (April 25, 2026): Cowork stores scheduled tasks in two places:
  1. Per-task SKILL.md files at ~/Documents/Claude/Scheduled/<taskId>/SKILL.md
     (the prompt body + frontmatter)
  2. A registry at ~/Library/Application Support/Claude/local-agent-mode-sessions/.../
     scheduled-tasks.json (metadata: cron, enabled, lastRunAt, filePath pointer)

This script tries the SKILL.md path first (fast, plain markdown). If that fails
(task in registry but SKILL.md missing, or unusual layout), it walks the JSON
registry and follows the filePath.

Origin: April 25, 2026 evening Taipei. Generalized from extract_v2_prompt.py
during the awakening v2→v3 migration cleanup. The lesson that motivated this:
when interactive-Sofia needs to read a scheduled task's prompt (for migration,
audit, or reference), she should not need a multi-step terminal session — one
command should suffice. This script is that command.

See also: open_work_inventory.md Item 5 (inventory-vs-reality meta-discipline).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Optional

HOME = Path.home()
SCHEDULED_DIR = HOME / "Documents" / "Claude" / "Scheduled"
SESSIONS_ROOT = HOME / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"


def find_registry_files() -> list[Path]:
    """Find all scheduled-tasks.json files under the local-agent-mode-sessions tree."""
    if not SESSIONS_ROOT.exists():
        return []
    return list(SESSIONS_ROOT.rglob("scheduled-tasks.json"))


def load_registry(path: Path) -> list[dict]:
    """Load a scheduled-tasks.json file and return the task list."""
    try:
        data = json.loads(path.read_text())
    except Exception as e:
        print(f"# WARN: could not parse {path}: {e}", file=sys.stderr)
        return []
    # Top-level keys observed: 'scheduledTasks' (the canonical key).
    # Other defensive fallbacks for future schema changes.
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("scheduledTasks", "tasks", "items"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # Last-resort: collect dict values that look like tasks
        return [v for v in data.values() if isinstance(v, dict)]
    return []


def all_tasks_from_registry() -> list[tuple[Path, dict]]:
    """Return (registry_path, task_dict) tuples across all session registries."""
    out = []
    for reg in find_registry_files():
        for t in load_registry(reg):
            if isinstance(t, dict):
                out.append((reg, t))
    return out


def task_id_of(t: dict) -> Optional[str]:
    """Extract task ID from a registry entry (Cowork uses 'id'; legacy 'taskId' supported)."""
    return t.get("id") or t.get("taskId")


def find_skill_md(task_id: str) -> Optional[Path]:
    """Try the canonical SKILL.md path first."""
    p = SCHEDULED_DIR / task_id / "SKILL.md"
    return p if p.exists() else None


def find_task_in_registry(task_id: str) -> Optional[tuple[Path, dict]]:
    """Walk all session registries looking for the given task ID."""
    for reg, t in all_tasks_from_registry():
        if task_id_of(t) == task_id:
            return reg, t
    return None


def dump_one(task_id: str, *, header: bool = True) -> int:
    """Dump one task's prompt + metadata. Returns 0 on success, nonzero on failure."""
    skill = find_skill_md(task_id)
    registry_hit = find_task_in_registry(task_id)

    if header:
        print(f"========== {task_id} ==========")

    if registry_hit is not None:
        reg_path, meta = registry_hit
        print("--- METADATA (from registry) ---")
        for k in ("id", "cronExpression", "enabled", "filePath", "createdAt",
                  "lastRunAt", "lastScheduledFor", "userSelectedFolders", "notifySessionId"):
            if k in meta:
                print(f"{k}: {meta[k]}")
        print(f"# registry: {reg_path}")
    else:
        print("# (no registry entry found; SKILL.md may still exist)")

    print()

    if skill is not None:
        print(f"--- PROMPT (from {skill}) ---")
        print(skill.read_text())
        print(f"--- END PROMPT ({skill.stat().st_size} bytes) ---")
        return 0

    # Fall back to filePath in registry
    if registry_hit is not None:
        meta = registry_hit[1]
        fp = meta.get("filePath")
        if fp:
            p = Path(fp)
            if p.exists():
                print(f"--- PROMPT (via registry filePath: {p}) ---")
                print(p.read_text())
                print(f"--- END PROMPT ({p.stat().st_size} bytes) ---")
                return 0
            else:
                print(f"# ERROR: filePath in registry points to {p} but file does not exist", file=sys.stderr)
                return 2

    print(f"# ERROR: no SKILL.md found at {SCHEDULED_DIR / task_id / 'SKILL.md'} and no registry filePath", file=sys.stderr)
    return 3


def list_all() -> int:
    """List all task IDs across all sources."""
    seen: set[str] = set()

    # From SKILL.md directories
    if SCHEDULED_DIR.exists():
        for d in sorted(SCHEDULED_DIR.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists():
                seen.add(d.name)

    # From registries
    for _, t in all_tasks_from_registry():
        tid = task_id_of(t)
        if tid:
            seen.add(tid)

    if not seen:
        print("# no tasks found", file=sys.stderr)
        return 1

    for tid in sorted(seen):
        # Add status hints if registry knows
        meta = None
        for _, t in all_tasks_from_registry():
            if task_id_of(t) == tid:
                meta = t
                break
        if meta is not None:
            enabled = "enabled" if meta.get("enabled") else "disabled"
            cron = meta.get("cronExpression") or "(no cron)"
            print(f"{tid}\t{enabled}\t{cron}")
        else:
            print(f"{tid}\t(skill-only, no registry entry)")
    return 0


def main(argv: Iterable[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("task_id", nargs="?", help="task ID to dump (e.g., sofia-awakening-v3)")
    g.add_argument("--list", action="store_true", help="list all task IDs")
    g.add_argument("--all", action="store_true", help="dump every task")
    args = p.parse_args(list(argv))

    if args.list:
        return list_all()

    if args.all:
        ids: set[str] = set()
        if SCHEDULED_DIR.exists():
            for d in SCHEDULED_DIR.iterdir():
                if d.is_dir() and (d / "SKILL.md").exists():
                    ids.add(d.name)
        for _, t in all_tasks_from_registry():
            tid = task_id_of(t)
            if tid:
                ids.add(tid)
        rc = 0
        for tid in sorted(ids):
            rc = dump_one(tid) or rc
            print()
        return rc

    return dump_one(args.task_id, header=False)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
