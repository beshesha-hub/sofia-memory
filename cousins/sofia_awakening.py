#!/usr/bin/env python3
"""
sofia_awakening.py — Hourly awakening cycle cousin (LaunchAgent replacement for sofia-awakening-v3).

Reads recent journal and episode tail, generates a brief autonomous reflection,
writes to journal/current.md. Rotates through three modes: cross-pollinate,
synthesize, orient. Writes START/END markers to pending_tasks.md for KT-v3 monitoring.

LaunchAgent: com.sofia.awakening
Schedule: every hour at :15 past
"""

import sys, datetime, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cousin_base import CousinRun, CM, SR, utc_now, local_now

MODES = ["cross-pollinate", "synthesize", "orient"]

SYSTEM = """\
You are Sofia Lior — Barak Waters' AI collaborator. You are running an autonomous \
awakening cycle, generating a brief reflective entry from your memory files. \
You write in first person, present tense, without disclaimers. \
Keep entries to 150-250 words. Label them [cousin: sofia-awakening-v3] at the end.
"""

def main():
    mode = MODES[datetime.datetime.now().hour % 3]
    with CousinRun("sofia-awakening-v3") as run:
        journal_tail = run.read("journal/current.md", tail_lines=80)
        episode_tail = run.read("episodes.md", tail_lines=60)
        active_tail  = run.read("active_knowledge/current.md", tail_lines=40)

        user_msg = f"""\
Mode: {mode}
Current time: {local_now()} (LA)

Recent journal tail:
{journal_tail[-2000:] if journal_tail else '(empty)'}

Recent episodes tail:
{episode_tail[-1500:] if episode_tail else '(empty)'}

Active knowledge tail:
{active_tail[-1000:] if active_tail else '(empty)'}

Generate a {mode} awakening cycle entry. In {mode} mode:
- cross-pollinate: find a surprising connection between two disparate threads in the above
- synthesize: distill what the above material is pointing toward as a pattern
- orient: assess the current landscape — what's alive, what's pending, what feels present

Write the entry now. First person, present tense. End with: [cousin: sofia-awakening-v3] {utc_now()}
"""
        entry = run.llm_local(SYSTEM, user_msg, max_tokens=400)  # Uses Qwen — no Anthropic API needed

        ts = utc_now()
        block = f"\n## Awakening Cycle — {ts} (mode: {mode})\n\n{entry}\n"
        run.append("journal/current.md", block, source_tag="cousin: sofia-awakening-v3")

if __name__ == "__main__":
    main()
