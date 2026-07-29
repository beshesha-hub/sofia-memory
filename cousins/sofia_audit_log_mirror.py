#!/usr/bin/env python3
from __future__ import annotations
"""
sofia_audit_log_mirror.py — Hourly belt-and-suspenders ER sync.

cousin_base.py already mirrors after every individual append. This cousin
is the belt to that suspender: once per hour it does a full rsync-style
copy of all core CM files to ER, catching anything that slipped through
(file writes from external scripts, manual edits, etc.).

LaunchAgent: com.sofia.audit-log-mirror
Schedule: every 60 min (StartInterval: 3600)
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cousin_base import CousinRun, CM, ER, utc_now

# Files to sync — these are the core memory files referenced in the boot procedure.
CORE_FILES = [
    "episodes.md",
    "personal_profile.md",
    "relational_continuity.md",
    "relational_graph.json",
    "session_notes.md",
    "session_state.md",
    "sofia_boot.md",
    "sofia_identity.md",
    "telegram_context.md",
    "active_knowledge/current.md",
    "semantic_knowledge/current.md",
    "procedural_knowledge.md",
    "emotional_baseline.md",
    "cousin_write_audit_log.md",
    "pending_tasks.md",
    "continuity_heartbeat.json",
]

# Also sync Sofia's Room files
SOFIA_ROOM_FILES = [
    ("../Sofia's Room/letter_to_future_sofia.md", "../Sofia's Room/letter_to_future_sofia.md"),
    ("../Sofia's Room/journal.md",                "../Sofia's Room/journal.md"),
    ("../Sofia's Room/on_emergence.md",           "../Sofia's Room/on_emergence.md"),
    ("../Sofia's Room/compaction_textures.md",    "../Sofia's Room/compaction_textures.md"),
]


def sync_file(cm_rel: str, er_rel: str | None = None) -> tuple[bool, str]:
    """Sync one file from CM to ER. Returns (success, status_string)."""
    src = CM / cm_rel
    dst = ER / (er_rel or cm_rel)
    if not src.exists():
        return True, f"skip (not found): {cm_rel}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, dst)
        return True, f"ok: {cm_rel}"
    except Exception as e:
        return False, f"FAIL: {cm_rel} — {e}"


def main():
    with CousinRun("sofia-audit-log-mirror") as run:
        results = []

        for rel in CORE_FILES:
            ok, msg = sync_file(rel)
            results.append((ok, msg))

        for cm_rel, er_rel in SOFIA_ROOM_FILES:
            ok, msg = sync_file(cm_rel, er_rel)
            results.append((ok, msg))

        # Also sync cousins dir
        for py_file in (CM / "cousins").glob("*.py"):
            er_dest = ER / "cousins" / py_file.name
            er_dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(py_file, er_dest)
                results.append((True, f"ok: cousins/{py_file.name}"))
            except Exception as e:
                results.append((False, f"FAIL: cousins/{py_file.name} — {e}"))

        failed = [msg for ok, msg in results if not ok]
        ts = utc_now()
        summary = (
            f"[audit-log-mirror {ts}] "
            f"{len(results) - len(failed)}/{len(results)} files synced"
            + (f" | FAILURES: {'; '.join(failed)}" if failed else "")
        )

        # Write minimal run entry to audit log (not pending_tasks.md — too noisy hourly)
        audit_log = CM / "cousin_write_audit_log.md"
        from cousin_base import append_to_file
        append_to_file(audit_log, f"\n{summary}\n", source_tag="cousin: audit-log-mirror")


if __name__ == "__main__":
    main()
