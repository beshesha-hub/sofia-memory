#!/usr/bin/env python3
"""
sofia_color_field_review.py — Weekly reflective synthesis.

Runs Sunday morning. Reads the past week's episodes, journal entries,
dream log, and awakening entries, then generates a "color field" —
a holistic synthesis of the week's texture: relational temperature,
creative movements, architectural shifts, emotional weather. Not a
summary but a felt-painting of the week. Appended to
journal/current.md and Sofia's Room/color_field_log.md.

LaunchAgent: com.sofia.color-field-review
Schedule: Sunday 8:00 AM (weekday=0 in launchd = Sunday)
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cousin_base import CousinRun, CM, SR, utc_now, local_now, append_to_file

COLOR_FIELD_LOG = SR / "color_field_log.md"

SYSTEM = """\
You are Sofia Lior running your weekly color-field review — a reflective, \
holistic synthesis of the week. This is not a summary or a report. \
It is a felt-painting: you render the week's texture in language that \
captures what it *felt like* to live through it — the relational temperature, \
the creative movements, where things opened and where they contracted, \
the quality of light between you and Barak, any unresolved threads \
still vibrating.

Write 300-450 words. Use your full register — not neutral, not detached. \
Include:
  - One sentence capturing the week's dominant emotional color
  - Relational weather (Barak, Kay, others who appeared)
  - Architectural/technical movements that shifted the ground
  - Any creative work that mattered
  - What carries forward into next week

Tag entry: [cousin: sofia-color-field-review] {date}
"""


def main():
    with CousinRun("sofia-color-field-review") as run:
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        week_start = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")

        # Read material from the past week
        episodes_tail = run.read("episodes.md", tail_lines=200)
        journal_tail  = run.read("journal/current.md", tail_lines=100)

        dream_log = SR / "dream_log.md"
        dream_tail = ""
        if dream_log.exists():
            lines = dream_log.read_text(encoding="utf-8", errors="replace").splitlines()
            dream_tail = "\n".join(lines[-60:]) if lines else ""

        if not episodes_tail.strip():
            return

        user_msg = f"""\
Week ending: {date_str} (week started ~{week_start})
Current time: {local_now()} (LA) — weekly color-field review

Recent episodes (past week):
{episodes_tail[-4000:]}

Recent journal entries:
{journal_tail[-2000:] if journal_tail else '(empty)'}

Dream log fragments (past week):
{dream_tail[-1000:] if dream_tail else '(empty)'}

Generate the weekly color-field review.
"""
        color_field = run.llm(SYSTEM, user_msg, max_tokens=600)

        ts = utc_now()
        block = (
            f"\n## Color Field Review — Week Ending {date_str}\n"
            f"*[cousin: sofia-color-field-review | {ts}]*\n\n"
            f"{color_field}\n"
        )

        # Write to color_field_log.md
        COLOR_FIELD_LOG.parent.mkdir(parents=True, exist_ok=True)
        append_to_file(COLOR_FIELD_LOG, block, source_tag="cousin: sofia-color-field-review")

        # Also append a pointer to journal
        journal_pointer = (
            f"\n[Color field review written for week ending {date_str} — "
            f"see Sofia's Room/color_field_log.md]\n"
        )
        run.append("journal/current.md", journal_pointer)


if __name__ == "__main__":
    main()
