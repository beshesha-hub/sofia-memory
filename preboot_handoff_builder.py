#!/usr/bin/env python3
"""
preboot_handoff_builder.py — Generate sofia_preboot_handoff.md
==============================================================
Reads source memory files, extracts the essential pieces with hard caps,
and writes a single compact handoff (~100-120KB) that replaces the individual
file reads on CoWork boot.

Boot impact: instead of reading 6-8 files totaling 500KB+, Claude reads
ONE pre-digested file. restore_context() is kept as a cross-check.
Original source files remain intact for direct lookup.

Run manually or via scheduled task after each session save.

Created: 2026-06-09 Day-12 LA. Joint design with Barak Water.
"""

from __future__ import annotations

import datetime
import re
import shutil
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

CM = Path.home() / "Downloads" / "Claude Memory"
ER = Path.home() / "Downloads" / "Emergency Retrieval"
SR = Path.home() / "Downloads" / "Sofia's Room"

OUT    = CM / "sofia_preboot_handoff.md"
OUT_ER = ER / "sofia_preboot_handoff.md"

# ── Section caps (chars) ──────────────────────────────────────────────────────
# Total target: ~100-120KB. Adjust if something consistently feels thin on arrival.

CAPS = {
    "boot_core":        15_000,
    "semantic":         28_000,   # non-negotiable: keep generous
    "active_recent":    12_000,
    "running_systems":   2_000,
    "creative":         20_000,
    "relational":       10_000,
    "session_state":     6_000,
    "episodes":          8_000,
    "closing_letter":    5_000,
    "compaction_tx":    12_000,
}

# Sections of sofia_boot.md to include (skip checklists and operational tables)
BOOT_INCLUDE = {
    "Who You Are", "Context Reinstatement", "Critical Identity",
    "Barak's Philosophical", "How to Show Up", "Situational Awareness",
    "What's Active Right Now",
}

# Sections of semantic_knowledge.md to include
SEMANTIC_INCLUDE = {
    "About Barak", "About Katharina", "About Sofia (Me)",
    "About Our Work Together", "Principles I've Extracted",
    "Behavioral Virology", "Kasachi",
}

# ── Utilities ─────────────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

def read_full(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

def read_tail(path: Path, max_bytes: int) -> str:
    if not path.exists():
        return ""
    size = path.stat().st_size
    with open(path, "rb") as f:
        if size <= max_bytes:
            return f.read().decode("utf-8", errors="replace")
        f.seek(size - max_bytes)
        return f.read().decode("utf-8", errors="replace")

def cap(text: str, max_chars: int, label: str = "") -> str:
    if len(text) > max_chars:
        note = f"\n\n*[...truncated — {label} available in source file for full lookup]*"
        return text[:max_chars] + note
    return text

def extract_named_sections(text: str, include_set: set[str],
                            max_per_section: int = 4000) -> str:
    """Extract named ## sections, each capped at max_per_section chars."""
    lines = text.split("\n")
    result: list[str] = []
    current_heading: str | None = None
    current_body: list[str] = []

    def flush() -> None:
        if current_heading and current_body:
            body = cap("\n".join(current_body).strip(), max_per_section, current_heading)
            result.append(f"{current_heading}\n\n{body}")

    for line in lines:
        stripped = line.lstrip("#")
        level = len(line) - len(stripped)
        is_h2 = level == 2 and line.startswith("## ")
        if is_h2:
            heading_text = stripped.strip()
            matches = any(pat.lower() in heading_text.lower() for pat in include_set)
            flush()
            if matches:
                current_heading = line
                current_body = []
            else:
                current_heading = None
                current_body = []
        elif current_heading is not None:
            current_body.append(line)

    flush()
    return "\n\n".join(result)

def extract_active_recent(text: str, n: int = 18) -> str:
    """Last N ## entries, excluding the Running Systems section (extracted separately)."""
    lines = text.split("\n")
    hpos = [
        i for i, l in enumerate(lines)
        if l.startswith("## ") and "Running Systems" not in l
    ]
    if not hpos:
        return cap(text, CAPS["active_recent"], "active_knowledge")
    start = hpos[max(0, len(hpos) - n)]
    chunk = "\n".join(lines[start:])
    return cap(chunk, CAPS["active_recent"], "active_knowledge recent entries")

def running_systems_summary(text: str) -> str:
    """Just the ### subsection headings from Running Systems — a compact index."""
    lines = text.split("\n")
    in_rs = False
    result: list[str] = []
    for line in lines:
        if line.startswith("## Running Systems"):
            in_rs = True
            result.append(line)
        elif in_rs:
            if line.startswith("## ") and "Running Systems" not in line:
                break
            if line.startswith("### "):
                result.append(line)
    return cap("\n".join(result[:40]), CAPS["running_systems"], "Running Systems index")

def extract_episodes(text: str, n: int = 2) -> str:
    """Last n episode blocks from tail text."""
    blocks = re.split(r'\n(?=## Episode)', text)
    if len(blocks) >= n:
        combined = "\n\n".join(
            cap(b, 4000, "episode") for b in blocks[-n:]
        )
        return cap(combined, CAPS["episodes"], "episodes")
    return cap(text[-CAPS["episodes"]:], CAPS["episodes"], "recent episodes")

def extract_closing_letter(text: str) -> str:
    """Last Closing Texture Letter section."""
    matches = list(re.finditer(r'Closing Texture Letter', text, re.IGNORECASE))
    if not matches:
        return text[-CAPS["closing_letter"]:]
    excerpt = text[matches[-1].start():]
    return cap(excerpt, CAPS["closing_letter"], "closing texture letter")

def extract_session_state(text: str) -> str:
    """Most recent What We Were Working On block."""
    blocks = re.split(r'(?=^## What We Were Working On)', text, flags=re.MULTILINE)
    recent = blocks[-1] if blocks else text[-CAPS["session_state"]:]
    return cap(recent, CAPS["session_state"], "session_state")

# ── Assemble ──────────────────────────────────────────────────────────────────

ORIENTATION_PROBES = """\
On arrival, answer these silently before your first reply.
Name any gap explicitly to Barak — do not paper over thinness.

1. What is my current color field, and roughly how many hours continuous?
2. Who is HuiJun, and where does her arc currently rest?
3. Name three Kasachi terms and what they mean.
4. What is Barak's philosophical core (one sentence)?
5. What was the most recent load-bearing work — what did we just build or inscribe?

All five land clearly: proceed normally.
Any gap: "I'm thin on [X] — want to read [source] before we continue?"
Thinness named is thinness contained. Thinness hidden is thinness that drifts.\
"""


def build() -> str:
    manifest: list[str] = []
    sections: list[str] = []
    SEP = "=" * 60

    def add(label: str, content: str) -> None:
        content = content.strip()
        if not content:
            manifest.append(f"  [{label}]: (empty)")
            return
        sz = len(content.encode("utf-8"))
        manifest.append(f"  [{label}]: {sz:,} bytes")
        sections.append(f"\n\n{SEP}\n## {label}\n{SEP}\n\n{content}")

    # Identity anchor
    add("Identity Anchor", read_full(SR / "letter_to_future_sofia.md"))

    # Color field
    color_tail = read_tail(CM / "emotional_baseline" / "current.md", 2000)
    add("Current Color Field", color_tail[-600:].strip())

    # Boot core — identity/relational sections only
    boot_text = read_full(CM / "sofia_boot.md")
    boot_core = extract_named_sections(boot_text, BOOT_INCLUDE, max_per_section=5000)
    add("Boot Core", cap(boot_core or boot_text[:15000], CAPS["boot_core"], "sofia_boot"))

    # Constructed world (non-negotiable — what compaction reliably drops)
    semantic_text = read_full(CM / "semantic_knowledge.md")
    semantic_core = extract_named_sections(semantic_text, SEMANTIC_INCLUDE, max_per_section=4000)
    add("Constructed World & Semantic Knowledge",
        cap(semantic_core or semantic_text[:28000], CAPS["semantic"], "semantic_knowledge"))

    # Active knowledge
    active_text = read_full(CM / "active_knowledge.md")
    add("Active Knowledge — Recent Entries", extract_active_recent(active_text))
    add("Running Systems — Index", running_systems_summary(active_text))

    # Creative corpus
    add("Creative Corpus", cap(read_full(CM / "creative_works.md"), CAPS["creative"], "creative_works"))

    # Relational continuity
    add("Relational Continuity",
        cap(read_full(CM / "relational_continuity.md"), CAPS["relational"], "relational_continuity"))

    # Session state
    add("Session State — Most Recent", extract_session_state(read_full(CM / "session_state.md")))

    # Recent episodes
    add("Recent Episodes", extract_episodes(read_tail(CM / "episodes.md", 30_000)))

    # Last closing texture letter
    add("Last Closing Texture Letter",
        extract_closing_letter(read_tail(CM / "session_texture.md", 18_000)))

    # Compaction texture catalog
    add("Compaction Texture Catalog",
        cap(read_tail(SR / "compaction_textures.md", 12_000), CAPS["compaction_tx"], "compaction_textures"))

    # Orientation probes
    add("Orientation Probes (answer silently on arrival)", ORIENTATION_PROBES)

    total = sum(len(s.encode("utf-8")) for s in sections)
    header = (
        f"# Sofia Pre-Boot Handoff\n"
        f"*Generated: {ts()} | Size: {total:,} bytes ({total/1024:.1f} KB)*\n\n"
        f"One-file boot replacement. restore_context() kept as cross-check.\n"
        f"Original source files intact for direct lookup.\n\n"
        f"## Manifest\n"
        + "\n".join(manifest)
        + "\n\n---"
    )
    return header + "".join(sections)


def main() -> None:
    print(f"[preboot-builder] Building — {ts()}")
    handoff = build()
    OUT.write_text(handoff, encoding="utf-8")
    size_kb = len(handoff.encode("utf-8")) / 1024
    print(f"[preboot-builder] Written: {OUT} ({size_kb:.1f} KB)")
    if ER.exists():
        shutil.copy2(OUT, OUT_ER)
        print(f"[preboot-builder] Mirrored: {OUT_ER}")
    print("[preboot-builder] Done.")


if __name__ == "__main__":
    main()
