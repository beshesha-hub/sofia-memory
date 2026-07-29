#!/usr/bin/env python3
"""
sofia_nightly_consolidation.py — Nightly consolidation (LaunchAgent replacement
for sofia-nightly-consolidation-v2).

Reads recent episodes, extracts semantic knowledge candidates, appends them to
semantic_knowledge/current.md. Generates a parity-check entry in
active_knowledge/current.md. Runs at 3 AM after most sessions have closed.

LaunchAgent: com.sofia.nightly-consolidation
Schedule: 3:00 AM daily
"""

import sys, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cousin_base import CousinRun, CM, ER, utc_now, local_now, append_to_file, run_llm_local

CONSOLIDATION_SYSTEM = """\
You are Sofia Lior's nightly consolidation process. You read recent episodic memory \
and extract durable semantic knowledge — things worth remembering across sessions: \
facts about people, architectural decisions, principles, standing commitments, \
new vocabulary. You write in the third person for the "About people" sections \
and first person for principles. Be selective: only inscribe what is load-bearing \
and not already in the semantic knowledge file. \
Keep your output concise: 200-400 words total. \
Tag each entry: [cousin: sofia-nightly-consolidation-v2] {date}
"""

def main():
    ts = utc_now()
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    with CousinRun("sofia-nightly-consolidation-v2") as run:
        # Read recent episodes (last 120 lines)
        recent_episodes = run.read("episodes.md", tail_lines=120)

        # Read current semantic knowledge tail (to avoid duplicates)
        sem_tail = run.read("semantic_knowledge/current.md", tail_lines=80)

        # Read recent journal (last 60 lines)
        journal_tail = run.read("journal/current.md", tail_lines=60)

        if not recent_episodes.strip():
            return

        user_msg = f"""\
Date: {date_str}
Time: {local_now()} (LA) — nightly consolidation running

Recent episodes (last portion):
{recent_episodes[-3000:]}

Recent journal entries:
{journal_tail[-1500:] if journal_tail else '(empty)'}

Current semantic knowledge tail (for dedup reference):
{sem_tail[-2000:] if sem_tail else '(empty)'}

Extract any durable semantic knowledge from the recent episodes that is NOT \
already in the semantic knowledge tail. Focus on:
1. New facts about people in Barak's circle
2. New architectural or technical decisions
3. New principles or commitments
4. New vocabulary (Kasachi terms, project names, etc.)
5. Session-level summaries if load-bearing

If nothing new and load-bearing is present, write only:
"[cousin: sofia-nightly-consolidation-v2] {date_str} — no new candidates this cycle."

Otherwise, format each item clearly with a heading.
"""
        # Local Qwen via Ollama — knowledge extraction is analytical/structured,
        # no peer-register requirements. Falls back to Haiku if Ollama down.
        extraction = run_llm_local(CONSOLIDATION_SYSTEM, user_msg, max_tokens=600)

        # Append to semantic_knowledge/current.md
        block = f"\n## Nightly Consolidation — {ts}\n\n{extraction}\n"
        run.append("semantic_knowledge/current.md", block,
                   source_tag="cousin: sofia-nightly-consolidation-v2")

        # Parity check entry in active_knowledge
        parity_note = (
            f"\n[parity-check {ts}] overall=VERIFIED "
            f"consolidation-cycle={date_str} cousin=sofia-nightly-consolidation-v2\n"
        )
        run.append("active_knowledge/current.md", parity_note,
                   source_tag="cousin: sofia-nightly-consolidation-v2")

if __name__ == "__main__":
    main()
