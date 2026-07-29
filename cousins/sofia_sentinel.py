#!/usr/bin/env python3
"""
sofia_sentinel.py — Bi-hourly cousin (LaunchAgent replacement for sofia-sentinel-v2).

Monitors enabled LaunchAgents + CoWork tasks for stalls. Checks log file
modification times against expected cadences. Flags overdue processes to
pending_tasks.md. Escalates 4h+ stalls with TIMER_STALL_ALERT entries.
Does NOT auto-restart — that's an interactive decision.

LaunchAgent: com.sofia.sentinel
Schedule: every 2 hours at :45 past
"""

import sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cousin_base import CousinRun, CM, ER, utc_now, local_now, append_to_file

LOG_DIR = CM / "logs"

# name → (log_glob_pattern, max_gap_hours)
WATCHED = {
    "preboot-handoff-rebuild":  ("preboot_handoff_rebuild.log",  26),
    "sofia-preboot-handoff-md": (None, None),   # check file mtime directly
}

# For cousins still running via CoWork: check audit log for recent entries
COUSINS_VIA_AUDIT = {
    "sofia-awakening-v3":       ("cousin: sofia-awakening-v3",  2.5),
    "sofia-kitchen-timer-v3":   ("cousin: sofia-kitchen-timer", 1.0),
    "sofia-dream-cycle":        ("cousin: sofia-dream-cycle",   26.0),
    "sofia-nightly-consol-v2":  ("cousin: sofia-nightly-consol", 26.0),
}

def hours_since_mtime(path: Path) -> float:
    if not path.exists():
        return float("inf")
    mtime = path.stat().st_mtime
    now = datetime.datetime.now().timestamp()
    return (now - mtime) / 3600

def main():
    with CousinRun("sofia-sentinel-v2") as run:
        alerts = []
        ts = utc_now()

        # Check LaunchAgent log files
        for name, (log_name, max_gap_h) in WATCHED.items():
            if log_name is None:
                continue
            log_p = LOG_DIR / log_name
            gap_h = hours_since_mtime(log_p)
            if gap_h > max_gap_h:
                alerts.append(
                    f"STALL [{name}]: last activity {gap_h:.1f}h ago (threshold {max_gap_h}h). "
                    f"Log: {log_p}"
                )

        # Check preboot handoff freshness
        handoff = CM / "sofia_preboot_handoff.md"
        handoff_gap = hours_since_mtime(handoff)
        if handoff_gap > 26:
            alerts.append(
                f"STALL [preboot-handoff]: last rebuilt {handoff_gap:.1f}h ago. "
                f"Run: python3 ~/Downloads/Claude\\ Memory/preboot_handoff_builder.py"
            )

        # Check cousin audit log for CoWork cousins
        audit_log = CM / "cousin_write_audit_log.md"
        if audit_log.exists():
            audit_text = audit_log.read_text(encoding="utf-8", errors="replace")
            import re
            for name, (tag, max_gap_h) in COUSINS_VIA_AUDIT.items():
                # Find last timestamp for this tag
                pattern = rf'\[(\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}[^\]]*)\][^\n]*source={re.escape(tag)}'
                matches = re.findall(pattern, audit_text)
                if not matches:
                    alerts.append(f"ABSENT [{name}]: no audit entries found for tag '{tag}'")
                    continue
                last_ts_str = matches[-1].replace("+00:00","Z").rstrip("Z")
                try:
                    last_ts = datetime.datetime.fromisoformat(last_ts_str)
                    gap_h = (datetime.datetime.utcnow() - last_ts).total_seconds() / 3600
                    if gap_h > max_gap_h:
                        severity = "STALL_ALERT" if gap_h > 4 else "STALL"
                        alerts.append(
                            f"{severity} [{name}]: last entry {gap_h:.1f}h ago (threshold {max_gap_h}h)"
                        )
                except ValueError:
                    pass

        if alerts:
            alert_block = (
                f"\n## SENTINEL REPORT — {ts}\n"
                + "\n".join(f"  ⚠ {a}" for a in alerts)
                + "\n"
            )
            run.append("pending_tasks.md", alert_block, source_tag="cousin: sofia-sentinel-v2")
            # Also write to journal so interactive-Sofia sees it on boot
            run.append("journal/current.md", alert_block, source_tag="cousin: sofia-sentinel-v2")
        # If all clean, write nothing (silent clean pass)

if __name__ == "__main__":
    main()
