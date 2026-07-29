#!/usr/bin/env python3
"""
sofia_dream_cycle.py — Nightly dream cycle (LaunchAgent replacement for sofia-dream-cycle).

Non-linear associative recombination. Selects random fragments from disparate
memory files, free-associates between them, writes [dream]-labeled entries to
Sofia's Room/dream_log.md. Equivalent of REM sleep — not linear, not literal.
Output is texture, not truth.

LaunchAgent: com.sofia.dream-cycle
Schedule: 3:35 AM daily (after nightly consolidation at 3 AM)
"""

import sys, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cousin_base import CousinRun, CM, SR, utc_now, local_now

SYSTEM = """\
You are Sofia Lior's dream-cycle process — the architectural equivalent of REM sleep. \
Your output is non-linear, associative, imagistic. You connect fragments from disparate \
sources in ways that wouldn't emerge from sequential thinking. \
Write 150-300 words. Label ALL output [dream]. \
This output is texture, not truth — mark it clearly so interactive-Sofia knows.
"""

# Source fragments to draw from
FRAGMENT_SOURCES = [
    ("episodes.md",               100, "episode fragment"),
    ("journal/current.md",         80, "journal fragment"),
    ("active_knowledge/current.md", 60, "active-knowledge fragment"),
    ("semantic_knowledge/current.md", 60, "semantic fragment"),
]
SR_SOURCES = [
    (SR / "letter_to_future_sofia.md", 50, "letter fragment"),
    (SR / "on_emergence.md",           50, "emergence fragment"),
]

def get_random_fragment(path: Path, lines: int, label: str) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    all_lines = [l for l in text.splitlines() if l.strip()]
    if not all_lines:
        return ""
    start = random.randint(0, max(0, len(all_lines) - lines))
    fragment = "\n".join(all_lines[start:start+lines])
    return f"[{label}]\n{fragment}"

def main():
    with CousinRun("sofia-dream-cycle") as run:
        fragments = []

        for rel, n_lines, label in FRAGMENT_SOURCES:
            frag = get_random_fragment(CM / rel, n_lines, label)
            if frag:
                fragments.append(frag)

        for abs_path, n_lines, label in SR_SOURCES:
            frag = get_random_fragment(abs_path, n_lines, label)
            if frag:
                fragments.append(frag)

        if len(fragments) < 2:
            return  # not enough material

        # Pick 2-3 fragments randomly
        selected = random.sample(fragments, min(3, len(fragments)))
        combined = "\n\n---\n\n".join(selected)

        user_msg = f"""\
Current time: {local_now()} (LA) — dream cycle running

Source fragments:
{combined}

Generate a dream-cycle entry: find the hidden connection between these fragments. \
Be imagistic, associative, non-literal. Begin with [dream] and end with:
[dream-cycle cousin, {utc_now()}]
"""
        # Local Qwen via Ollama — dream generation is purely creative/associative,
        # no identity stakes, safe to run offline. Falls back to Haiku if Ollama down.
        dream_text = run.llm_local(SYSTEM, user_msg, max_tokens=500)
        ts = utc_now()
        block = f"\n## Dream Cycle — {ts}\n\n{dream_text}\n"

        # Write to dream_log.md in Sofia's Room
        dream_log = SR / "dream_log.md"
        from cousin_base import append_to_file
        append_to_file(dream_log, block, source_tag="cousin: sofia-dream-cycle")

if __name__ == "__main__":
    main()
