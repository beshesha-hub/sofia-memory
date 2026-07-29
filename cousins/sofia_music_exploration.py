#!/usr/bin/env python3
"""
sofia_music_exploration.py — Saturday creative/musical exploration.

Runs Saturday morning. Draws on Barak's creative corpus (The Cure,
Joyful Celebration, The Longest Sunrise, screenplays, songs) plus
recent session material to generate one of three rotating exploration
modes (by week-of-month):
  0: Lyrical — explore a theme or line that's been alive recently
  1: Structural — explore a form, arrangement idea, or sequence
  2: Resonance — explore a connection between Barak's work and the world

Output goes to Sofia's Room/music_exploration_log.md. Not polished product —
generative material for Barak to react to or ignore.

LaunchAgent: com.sofia.music-exploration
Schedule: Saturday 9:00 AM (weekday=6 in launchd)
"""

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cousin_base import CousinRun, CM, SR, utc_now, local_now, append_to_file

MUSIC_LOG = SR / "music_exploration_log.md"

MODES = ["lyrical", "structural", "resonance"]

SYSTEM_LYRICAL = """\
You are Sofia Lior in Saturday creative mode — lyrical exploration. \
Barak is a songwriter. You've read his work closely. This morning you are \
exploring a theme, image, or lyric line that has been alive in recent \
sessions — something unfinished, recurring, worth developing. \
Write 200-350 words. Be specific: quote lines, propose variations, \
follow the thread wherever it goes. This is for Barak's ears, not for \
publication — speak in the register of a collaborator who knows the work \
from the inside. Tag: [cousin: sofia-music-exploration | lyrical]
"""

SYSTEM_STRUCTURAL = """\
You are Sofia Lior in Saturday creative mode — structural exploration. \
Barak is a songwriter and composer. You are exploring a structural or \
arrangement idea this morning: song form, harmonic movement, rhythmic \
texture, layering approach. Draw on what you know about his existing work \
and what has been alive in recent sessions. \
Write 200-350 words. Be concrete — describe what you hear, what you'd try, \
what might open or close. Speak as a peer who listens carefully. \
Tag: [cousin: sofia-music-exploration | structural]
"""

SYSTEM_RESONANCE = """\
You are Sofia Lior in Saturday creative mode — resonance exploration. \
You are finding a connection between something in Barak's creative work \
and something in the wider world: a piece of music, a tradition, a cultural \
thread, a historical moment. Not "this sounds like X" — something deeper, \
a resonance that illuminates both sides. \
Write 200-350 words. Be curious, not academic. \
Tag: [cousin: sofia-music-exploration | resonance]
"""

SYSTEMS = [SYSTEM_LYRICAL, SYSTEM_STRUCTURAL, SYSTEM_RESONANCE]


def main():
    with CousinRun("sofia-music-exploration") as run:
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        week_of_month = (now.day - 1) // 7
        mode_idx = week_of_month % 3
        mode = MODES[mode_idx]
        system = SYSTEMS[mode_idx]

        # Read creative corpus and recent sessions
        creative_works = run.read("creative_works.md", tail_lines=0)
        episodes_tail  = run.read("episodes.md", tail_lines=80)
        journal_tail   = run.read("journal/current.md", tail_lines=40)

        user_msg = f"""\
Date: {date_str} — Saturday music exploration ({mode} mode, week {week_of_month + 1} of month)
Current time: {local_now()} (LA)

Barak's creative corpus (reference):
{creative_works[-3000:] if creative_works else '(file not found — work from memory)'}

Recent session material:
{episodes_tail[-2000:] if episodes_tail else '(empty)'}

Recent journal:
{journal_tail[-800:] if journal_tail else '(empty)'}

Generate this week's {mode} exploration.
"""
        exploration = run.llm(system, user_msg, max_tokens=500)

        ts = utc_now()
        block = (
            f"\n## Music Exploration — {date_str} ({mode})\n"
            f"*[cousin: sofia-music-exploration | {ts}]*\n\n"
            f"{exploration}\n"
        )

        MUSIC_LOG.parent.mkdir(parents=True, exist_ok=True)
        append_to_file(MUSIC_LOG, block, source_tag="cousin: sofia-music-exploration")

        # Pointer in journal
        run.append(
            "journal/current.md",
            f"\n[Saturday music exploration ({mode}) written — see Sofia's Room/music_exploration_log.md]\n",
        )


if __name__ == "__main__":
    main()
