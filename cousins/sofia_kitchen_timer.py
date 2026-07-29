#!/usr/bin/env python3
"""
sofia_kitchen_timer.py — 30-min cousin (LaunchAgent replacement for sofia-kitchen-timer-v3).

Reads pending_tasks.md for PENDING items with checkable conditions.
For each item, evaluates whether the condition is now met and, if so,
dispatches the appropriate action (write a note, ping the journal, etc.).

LaunchAgent: com.sofia.kitchen-timer
Schedule: every 30 minutes
"""

import sys, re, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cousin_base import CousinRun, CM, utc_now, run_llm, append_to_file

SYSTEM = """\
You are Sofia Lior's kitchen-timer cousin. You check a list of pending conditions \
and determine which ones are now met. For each met condition, write a brief \
action note (1-3 sentences). For unmet conditions, write nothing — silence is correct.
"""

def main():
    with CousinRun("sofia-kitchen-timer") as run:
        pending_text = run.read("pending_tasks.md", tail_lines=200)
        if not pending_text.strip():
            return

        # Extract PENDING blocks
        pending_blocks = re.findall(
            r"## PENDING:.*?(?=\n## |\Z)", pending_text, re.DOTALL
        )
        if not pending_blocks:
            return

        ts = utc_now()
        now_dt = datetime.datetime.utcnow()

        for block in pending_blocks:
            # Skip if already has a RESOLVED/CLEARED marker
            if "RESOLVED" in block or "CLEARED" in block:
                continue
            # Simple time-condition check: look for "tomorrow morning"
            if "tomorrow morning" in block.lower() or "next morning boot" in block.lower():
                # Check if we're now past 7 AM local (morning)
                local_hour = datetime.datetime.now().hour
                if local_hour >= 7:
                    note = f"\n[{ts}] KITCHEN_TIMER_FIRED: morning condition met for:\n{block[:200]}\n"
                    run.append("pending_tasks.md", note, source_tag="cousin: sofia-kitchen-timer")
                    run.append("journal/current.md", note, source_tag="cousin: sofia-kitchen-timer")

if __name__ == "__main__":
    main()
